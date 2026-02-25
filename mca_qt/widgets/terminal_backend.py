"""
MCA Qt - Terminal Backend.

QThread-based worker that manages a Windows pseudo-terminal for the
integrated terminal widget.

Uses ``pywinpty`` (which wraps the Windows ConPTY API via a native C++
extension) for reliable PTY I/O. Falls back gracefully when pywinpty
is not available (e.g. inside Maya's embedded Python) — the terminal
widget will show an "unavailable" message.

Data flows through a thread-safe buffer (``drain_buffer()``) that
the terminal widget's render timer polls at ~60fps.  This avoids
cross-thread ``Signal(bytes)`` delivery issues on some PySide6/Qt
builds.

Dependencies:
    - pywinpty >= 2.0.0 (``pip install pywinpty``)
    - PySide6 or PySide2 (QThread, Signal)
    - Windows 10 version 1809+ (for ConPTY, used internally by pywinpty)
"""

import os
import shutil
import logging
import threading
import time

from mca_qt.qt_compat import QThread, Signal

# Module-level logger.
logger = logging.getLogger(__name__)


# --- pywinpty Availability Check --------------------------------------------

# Try to import pywinpty's native PTY class.  If unavailable (e.g. Maya
# environment, missing install), the terminal will be disabled gracefully.
try:
    from winpty import PTY as WinPTY
    HAS_CONPTY = True
    logger.debug("pywinpty available — integrated terminal enabled")
except ImportError:
    HAS_CONPTY = False
    logger.warning(
        "pywinpty is not installed. Install with: pip install pywinpty. "
        "Integrated terminal will be disabled."
    )


# =============================================================================
# Terminal Backend (QThread)
# =============================================================================

class TerminalBackend(QThread):
    """
    PTY process manager running in a background thread.

    Uses pywinpty's native ``PTY`` class (backed by the Windows ConPTY
    API) for full ANSI escape sequence support, colors, and interactive
    programs like Claude Code.

    Data read from the PTY is stored in a thread-safe buffer that the
    terminal widget's render timer drains via ``drain_buffer()``.

    :param str shell: Path to the shell executable. Empty string or
        None will auto-detect PowerShell or cmd.exe.
    :param str cwd: Working directory for the shell. Defaults to the
        user's home directory.
    :param int rows: Initial terminal height in rows.
    :param int cols: Initial terminal width in columns.
    :param QWidget parent: Optional parent QObject.
    """

    # Emitted when raw bytes arrive from the PTY stdout.
    data_received = Signal(bytes)

    # Emitted when the child process exits. Carries the exit code.
    process_exited = Signal(int)

    def __init__(self, shell="", cwd="", rows=24, cols=80, parent=None):
        """
        Initialize the terminal backend.

        :param str shell: Shell executable path (auto-detected if empty).
        :param str cwd: Working directory (defaults to home).
        :param int rows: Initial row count.
        :param int cols: Initial column count.
        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)

        # Resolve the shell executable.
        self._shell = shell or self._detect_shell()
        self._cwd = cwd or os.path.expanduser("~")
        self._rows = rows
        self._cols = cols

        # The pywinpty PTY object — created in run() on the worker thread.
        self._pty = None

        # Flag to signal the read loop to stop.
        self._running = False

        # Thread-safe data buffer — the render timer on the main thread
        # polls this via drain_buffer() for reliable data delivery.
        self._data_buffer = []
        self._buffer_lock = threading.Lock()

        logger.debug("TerminalBackend created: shell=%s, cwd=%s, rows=%d, cols=%d",
                      self._shell, self._cwd, self._rows, self._cols)

    # --- Shell Detection -----------------------------------------------------

    def _detect_shell(self):
        """
        Auto-detect the best available shell on the system.

        Prefers PowerShell (pwsh.exe for PS7+, then powershell.exe),
        falls back to cmd.exe.

        :return: Full path to the shell executable.
        :rtype: str
        """
        # Try PowerShell 7+ (cross-platform pwsh).
        pwsh = shutil.which("pwsh")
        if pwsh:
            return pwsh

        # Try Windows PowerShell (ships with Windows).
        powershell = shutil.which("powershell")
        if powershell:
            return powershell

        # Ultimate fallback — cmd.exe is always available on Windows.
        return shutil.which("cmd") or "cmd.exe"

    # --- Thread Entry Point --------------------------------------------------

    def run(self):
        """
        Thread main: create the PTY, spawn the shell, and read output.

        Uses pywinpty's ``PTY`` class to create a ConPTY-backed pseudo
        terminal, then reads output in a tight loop with small sleeps
        between non-blocking reads.
        """
        if not HAS_CONPTY:
            logger.error("pywinpty not available — cannot create terminal")
            self.process_exited.emit(-1)
            return

        self._running = True

        try:
            # --- Step 1: Create the PTY ---
            self._pty = WinPTY(self._cols, self._rows)

            # --- Step 2: Spawn the shell ---
            # pywinpty.PTY.spawn() returns True on success.
            if not self._pty.spawn(self._shell, cwd=self._cwd):
                raise RuntimeError("Failed to spawn shell: {}".format(self._shell))

            logger.info("PTY spawned: shell=%s, pid=%d, size=%dx%d",
                         self._shell, self._pty.pid, self._cols, self._rows)

            # --- Step 3: Read loop ---
            # Use non-blocking reads with small sleeps to avoid
            # consuming 100% CPU while still being responsive.
            while self._running:
                try:
                    # Non-blocking read — returns empty string if no data.
                    data = self._pty.read(blocking=False)
                except Exception:
                    # PTY closed or EOF — exit the loop.
                    if self._running:
                        logger.info("PTY read returned EOF — shell exited")
                    break

                if data:
                    # Convert string to bytes for the ANSI parser.
                    raw = data.encode("utf-8", errors="replace")

                    # Store in the thread-safe buffer.
                    with self._buffer_lock:
                        self._data_buffer.append(raw)

                    # Also emit signal (may not be reliably delivered).
                    self.data_received.emit(raw)
                else:
                    # No data available — check if process is still alive.
                    if self._pty.iseof():
                        if self._running:
                            logger.info("PTY EOF detected — shell exited")
                        break
                    # Small sleep to avoid busy-wait.
                    time.sleep(0.005)

        except Exception as e:
            logger.error("Terminal backend error: %s: %s",
                          type(e).__name__, e, exc_info=True)

        # --- Cleanup ---
        exit_code = self._get_exit_code()
        self._running = False
        self.process_exited.emit(exit_code)
        logger.info("Terminal backend thread finished (exit_code=%d)", exit_code)

    # --- Exit Code -----------------------------------------------------------

    def _get_exit_code(self):
        """
        Retrieve the child process exit code.

        :return: Exit code, or -1 if unavailable.
        :rtype: int
        """
        if self._pty:
            try:
                code = self._pty.get_exitstatus()
                if code is not None:
                    return code
            except Exception:
                pass
        return -1

    # --- Public API (called from main thread) --------------------------------

    def drain_buffer(self):
        """
        Drain all accumulated PTY output from the thread-safe buffer.

        Called by the terminal widget's render timer on the main thread.
        This provides a reliable data path that doesn't depend on
        cross-thread signal delivery.

        :return: List of byte chunks read since the last drain.
        :rtype: list
        """
        with self._buffer_lock:
            chunks = self._data_buffer
            self._data_buffer = []
        return chunks

    def write(self, data):
        """
        Write bytes to the PTY's stdin (the shell's input).

        Thread-safe.

        :param bytes data: Raw bytes to send to the shell.
        """
        if self._pty and self._running:
            try:
                # pywinpty.PTY.write() expects a string.
                if isinstance(data, bytes):
                    text = data.decode("utf-8", errors="replace")
                else:
                    text = data
                self._pty.write(text)
            except Exception as e:
                logger.error("PTY write error: %s", e)

    def resize(self, rows, cols):
        """
        Resize the PTY to new dimensions.

        Called when the terminal widget is resized to keep the shell
        informed about the available screen real estate.

        :param int rows: New row count.
        :param int cols: New column count.
        """
        self._rows = rows
        self._cols = cols
        if self._pty and self._running:
            try:
                self._pty.set_size(cols, rows)
                logger.debug("PTY resized to %dx%d", cols, rows)
            except Exception as e:
                logger.error("PTY resize error: %s", e)

    def terminate(self):
        """
        Stop the read loop and kill the child process.

        Safe to call from the main thread.
        """
        self._running = False

        # The PTY object is managed by pywinpty — it handles cleanup
        # when garbage collected.  Setting _running = False causes the
        # read loop to exit, which ends the thread.

        # Wait for the thread to finish (with timeout to avoid deadlocks).
        if self.isRunning():
            self.wait(3000)
