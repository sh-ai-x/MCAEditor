"""
MCA Qt - Terminal Backend.

QThread-based worker that manages a terminal process for the
integrated terminal widget.

Two backends are supported:

1. **pywinpty PTY** (preferred) — Uses the Windows ConPTY API via
   ``pywinpty``'s native C++ extension for full ANSI escape sequence
   support, colors, and interactive programs.
2. **subprocess fallback** — When pywinpty is not available (e.g. inside
   Maya's embedded Python), falls back to ``subprocess.Popen`` with
   piped stdin/stdout.  Line-oriented tools (pip, git, python, Claude
   Code) work fine; full-screen interactive programs (vim, less) do not
   because pipes are not a real PTY.

Data flows through a thread-safe buffer (``drain_buffer()``) that
the terminal widget's render timer polls at ~60fps.  This avoids
cross-thread ``Signal(bytes)`` delivery issues on some PySide6/Qt
builds.

Dependencies:
    - pywinpty >= 2.0.0 (``pip install pywinpty``) — optional
    - PySide6 or PySide2 (QThread, Signal)
    - Windows 10 version 1809+ (for ConPTY, used internally by pywinpty)
"""

import os
import shutil
import subprocess
import logging
import threading
import time

from mca_qt.qt_compat import QThread, Signal

# Module-level logger.
logger = logging.getLogger(__name__)


# --- pywinpty Availability Check --------------------------------------------

# WinPTY reference — set by _ensure_conpty() on first successful import.
WinPTY = None

# Initial availability flag — may be updated later by _ensure_conpty()
# if the venv path was injected after this module was first imported.
HAS_CONPTY = False

# Try the import immediately.  If it fails now, _ensure_conpty() will
# retry later (e.g. after setup_venv() injects the venv site-packages).
try:
    from winpty import PTY as WinPTY
    HAS_CONPTY = True
    logger.debug("pywinpty available — integrated terminal enabled")
except ImportError:
    logger.info(
        "pywinpty not available at import time — will retry when terminal starts. "
        "Install pywinpty for full PTY support: pip install pywinpty"
    )


def _ensure_conpty():
    """
    Lazy re-check for pywinpty availability.

    The module-level ``from winpty import PTY`` can fail if this module
    was imported before ``setup_venv()`` had a chance to inject the venv
    site-packages into ``sys.path``.  This function retries the import
    and updates the module globals so the terminal can start even if the
    initial import failed.

    Called at the top of ``run()`` and by ``check_conpty()`` so callers
    can get an up-to-date answer.

    :return: *True* if pywinpty is now available.
    :rtype: bool
    """
    global HAS_CONPTY, WinPTY

    # Already available — nothing to do.
    if HAS_CONPTY and WinPTY is not None:
        return True

    # First attempt — winpty may already be importable.
    try:
        from winpty import PTY as _PTY
        WinPTY = _PTY
        HAS_CONPTY = True
        logger.info("pywinpty now available (late import succeeded)")
        return True
    except (ImportError, Exception):
        pass

    # Second attempt — re-inject the venv site-packages path.
    # Maya can reset sys.path after initializePlugin() runs, dropping
    # the path that setup_venv() injected at startup.  Re-inject it
    # now so the import can find pywinpty.
    try:
        from mca_core.venv_manager import inject_venv_path
        injected = inject_venv_path()
        if injected:
            logger.info("Re-injected venv path: %s", injected)
            # Retry the import now that the path is on sys.path.
            from winpty import PTY as _PTY
            WinPTY = _PTY
            HAS_CONPTY = True
            logger.info("pywinpty available after venv path re-injection")
            return True
    except ImportError as exc:
        _log_conpty_diagnosis(exc)
        return False
    except Exception as exc:
        logger.warning("pywinpty import failed with unexpected error: %s", exc)
        _log_conpty_diagnosis(exc)
        return False

    return False


def _log_conpty_diagnosis(exc):
    """
    Log detailed diagnostics about why pywinpty can't be imported.

    Checks the venv state, sys.path, and whether the winpty package
    files exist on disk.  Outputs at WARNING level so it's visible
    in Maya's Script Editor.

    :param Exception exc: The import exception that occurred.
    """
    import sys as _sys

    logger.warning("pywinpty import failed: %s", exc)

    # Check if the venv site-packages is on sys.path.
    try:
        from mca_core.venv_manager import get_venv_site_packages
        sp = get_venv_site_packages()
        if sp is None:
            logger.warning("  Venv site-packages: NOT FOUND (venv may not exist)")
        elif not any(os.path.normcase(os.path.normpath(p)) ==
                     os.path.normcase(os.path.normpath(sp))
                     for p in _sys.path):
            logger.warning("  Venv site-packages exists but NOT on sys.path: %s", sp)
        else:
            logger.warning("  Venv site-packages on sys.path: %s", sp)

            # Check if winpty files exist in site-packages.
            winpty_dir = os.path.join(sp, "winpty")
            if os.path.isdir(winpty_dir):
                contents = os.listdir(winpty_dir)
                logger.warning("  winpty/ directory found: %s", contents[:10])
            else:
                # Check for .pyd files.
                pyd_files = [f for f in os.listdir(sp)
                             if f.startswith("winpty") and f.endswith(".pyd")]
                if pyd_files:
                    logger.warning("  winpty .pyd files found: %s", pyd_files)
                else:
                    logger.warning("  winpty NOT installed in site-packages")
    except Exception as diag_exc:
        logger.warning("  (diagnosis failed: %s)", diag_exc)


def check_conpty():
    """
    Public helper: check whether pywinpty is available (with lazy retry).

    Unlike the module-level ``HAS_CONPTY`` constant, this function
    retries the import if it previously failed — useful after
    ``setup_venv()`` injects the venv path.

    :return: *True* if pywinpty is available.
    :rtype: bool
    """
    return _ensure_conpty()


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

        # The subprocess.Popen object — used as fallback when pywinpty
        # is not available (e.g. inside Maya's embedded Python).
        self._proc = None

        # Flag to signal the read loop to stop.
        self._running = False

        # Thread-safe data buffer — the render timer on the main thread
        # polls this via drain_buffer() for reliable data delivery.
        self._data_buffer = []
        self._buffer_lock = threading.Lock()

        # First-data flag for diagnostic logging.
        self._first_data_logged = False

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
        Thread main: create the terminal process and read output.

        Retries the pywinpty import (in case the venv path was injected
        after module load), then dispatches to ``_run_pty()`` or
        ``_run_subprocess()`` accordingly.
        """
        self._running = True

        # Lazy re-check: pywinpty may have become available since the
        # module was first imported (e.g. setup_venv() ran afterward).
        has_pty = _ensure_conpty()
        logger.info("Terminal backend thread started (thread=%s, HAS_CONPTY=%s)",
                     self.currentThread(), has_pty)

        try:
            if has_pty:
                self._run_pty()
            else:
                self._run_subprocess()
        except Exception as e:
            logger.error("Terminal backend error: %s: %s",
                          type(e).__name__, e, exc_info=True)

        # --- Cleanup ---
        exit_code = self._get_exit_code()
        self._running = False
        self.process_exited.emit(exit_code)
        logger.info("Terminal backend thread finished (exit_code=%d)", exit_code)

    # --- PTY Backend (pywinpty) ----------------------------------------------

    def _run_pty(self):
        """
        Run the terminal using pywinpty's ConPTY backend.

        Creates a pseudo-terminal via ``pywinpty.PTY``, spawns the shell,
        and reads output in a tight loop with small sleeps between
        non-blocking reads.  This is the preferred path — full ANSI
        escape sequence support, colors, interactive programs.
        """
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

                # Log the first data chunk at INFO level — confirms the
                # PTY is alive and producing output.
                if not self._first_data_logged:
                    self._first_data_logged = True
                    logger.info("PTY first data: %d bytes (PTY read loop OK)",
                                len(raw))

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

    # --- Subprocess Backend (fallback) ---------------------------------------

    def _run_subprocess(self):
        """
        Run the terminal using a plain ``subprocess.Popen`` pipe.

        This fallback is used when pywinpty is not available (e.g.
        inside Maya's embedded Python where native extensions may not
        load).  Pipes are not a real PTY so full-screen interactive
        programs (vim, less) won't work, but line-oriented tools like
        pip, git, python, and Claude Code work fine.

        Reads from stdout using ``os.read()`` on the raw file
        descriptor for efficient, non-blocking-ish chunk reads.
        """
        logger.info("pywinpty not available — using subprocess fallback")

        # Build environment with TERM set so programs know we're not
        # a full terminal (avoids them trying full-screen tricks).
        env = os.environ.copy()
        env["TERM"] = "dumb"

        # Spawn the shell with merged stdout/stderr.
        # CREATE_NO_WINDOW prevents a visible console window from
        # flashing on screen when the subprocess starts.
        self._proc = subprocess.Popen(
            [self._shell],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self._cwd,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        logger.info("Subprocess spawned: shell=%s, pid=%d",
                     self._shell, self._proc.pid)

        # --- Read loop ---
        # os.read() on the raw fd gives us chunk-at-a-time reads
        # without the buffering that proc.stdout.read() would impose.
        fd = self._proc.stdout.fileno()
        while self._running:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                # Pipe closed — process exited.
                if self._running:
                    logger.info("Subprocess stdout pipe closed — shell exited")
                break

            if chunk:
                # Store in the thread-safe buffer.
                with self._buffer_lock:
                    self._data_buffer.append(chunk)

                # Also emit signal (may not be reliably delivered).
                self.data_received.emit(chunk)
            else:
                # Empty read means EOF — shell exited.
                if self._running:
                    logger.info("Subprocess EOF — shell exited")
                break

    # --- Exit Code -----------------------------------------------------------

    def _get_exit_code(self):
        """
        Retrieve the child process exit code.

        Checks the PTY backend first, then the subprocess fallback.

        :return: Exit code, or -1 if unavailable.
        :rtype: int
        """
        # PTY path — ask pywinpty for the exit status.
        if self._pty:
            try:
                code = self._pty.get_exitstatus()
                if code is not None:
                    return code
            except Exception:
                pass

        # Subprocess path — poll for the return code.
        if self._proc:
            try:
                self._proc.poll()
                if self._proc.returncode is not None:
                    return self._proc.returncode
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
        Write bytes to the terminal's stdin (the shell's input).

        Dispatches to pywinpty or subprocess pipe depending on which
        backend is active.  Thread-safe.

        :param bytes data: Raw bytes to send to the shell.
        """
        if not self._running:
            return

        # PTY path — pywinpty.PTY.write() expects a string.
        if self._pty:
            try:
                if isinstance(data, bytes):
                    text = data.decode("utf-8", errors="replace")
                else:
                    text = data
                self._pty.write(text)
            except Exception as e:
                logger.error("PTY write error: %s", e)

        # Subprocess path — write raw bytes to stdin pipe.
        elif self._proc and self._proc.stdin:
            try:
                if isinstance(data, str):
                    data = data.encode("utf-8")
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except (OSError, BrokenPipeError) as e:
                logger.error("Subprocess write error: %s", e)

    def resize(self, rows, cols):
        """
        Resize the terminal to new dimensions.

        Called when the terminal widget is resized to keep the shell
        informed about the available screen real estate.  Only the
        PTY backend supports real resize — subprocess pipes silently
        ignore the request since they have no concept of terminal size.

        :param int rows: New row count.
        :param int cols: New column count.
        """
        self._rows = rows
        self._cols = cols

        # PTY path — inform the ConPTY of the new size.
        if self._pty and self._running:
            try:
                self._pty.set_size(cols, rows)
                logger.debug("PTY resized to %dx%d", cols, rows)
            except Exception as e:
                logger.error("PTY resize error: %s", e)

        # Subprocess path — no-op, pipes don't support resize.

    def terminate(self):
        """
        Stop the read loop and kill the child process.

        Handles cleanup for both PTY and subprocess backends.
        Safe to call from the main thread.  Explicitly kills the
        child shell process so Maya doesn't hang on exit waiting
        for orphaned ConPTY children.
        """
        self._running = False

        # PTY path — explicitly kill the child shell process via its
        # PID so the ConPTY closes cleanly.  Relying on garbage
        # collection alone is not reliable during Maya shutdown —
        # the GC may never run, leaving the shell alive and causing
        # Maya's process to hang as a zombie.
        if self._pty:
            try:
                pid = self._pty.pid
                if pid:
                    import signal
                    os.kill(pid, signal.SIGTERM)
                    logger.info("Sent SIGTERM to PTY child (pid=%d)", pid)
            except (ProcessLookupError, OSError):
                # Process already exited — that's fine.
                pass
            except Exception as exc:
                logger.warning("Failed to kill PTY child: %s", exc)
            self._pty = None

        # Subprocess path — actively kill the child process and close
        # its stdin pipe so the read loop's os.read() returns EOF.
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

        # Wait for the thread to finish (with timeout to avoid deadlocks).
        if self.isRunning():
            self.wait(3000)
