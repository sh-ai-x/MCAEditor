"""
MCA Qt - Terminal Backend.

QThread-based worker that manages a terminal process for the
integrated terminal widget.

Three backends are supported (auto-selected by platform):

1. **pywinpty PTY** (Windows, preferred) — Uses the Windows ConPTY API via
   ``pywinpty``'s native C++ extension for full ANSI escape sequence
   support, colors, and interactive programs.
2. **Unix PTY** (macOS/Linux, preferred) — Uses Python's stdlib ``pty``
   module (``pty.openpty()``) to create a real pseudo-terminal.  The
   shell runs interactively with a prompt, line editing, and ANSI
   color support — no third-party packages required.
3. **subprocess fallback** — Last resort when neither PTY backend is
   available.  Falls back to ``subprocess.Popen`` with piped
   stdin/stdout.  Line-oriented tools (pip, git, python) work fine;
   full-screen interactive programs (vim, less) do not because pipes
   are not a real PTY.

Data flows through a thread-safe buffer (``drain_buffer()``) that
the terminal widget's render timer polls at ~60fps.  This avoids
cross-thread ``Signal(bytes)`` delivery issues on some PySide6/Qt
builds.

Dependencies:
    - pywinpty >= 2.0.0 (``pip install pywinpty``) — optional, Windows only
    - PySide6 or PySide2 (QThread, Signal)
    - Windows 10 version 1809+ (for ConPTY, used internally by pywinpty)
"""

import os
import platform
import shutil
import subprocess
import logging
import threading
import time

from mca_qt.qt_compat import QThread, Signal

# Module-level logger.
logger = logging.getLogger(__name__)


# --- PTY Availability Checks ------------------------------------------------

# WinPTY reference — set by _ensure_conpty() on first successful import.
WinPTY = None

# Initial availability flag — may be updated later by _ensure_conpty()
# if the venv path was injected after this module was first imported.
HAS_CONPTY = False

# Unix PTY availability — True on macOS/Linux where stdlib pty works.
HAS_UNIX_PTY = False

if platform.system() == "Windows":
    # pywinpty (Windows ConPTY) — try the import immediately.  If it fails
    # now, _ensure_conpty() will retry later (e.g. after setup_venv()
    # injects the venv site-packages).
    try:
        from winpty import PTY as WinPTY
        HAS_CONPTY = True
        logger.debug("pywinpty available — integrated terminal enabled")
    except ImportError:
        logger.info(
            "pywinpty not available at import time — will retry when terminal starts. "
            "Install pywinpty for full PTY support: pip install pywinpty"
        )
else:
    # macOS/Linux — use Python's stdlib pty module for a real pseudo-terminal.
    # No third-party packages needed.
    try:
        import pty as _pty_probe   # noqa: F401
        import fcntl as _fcntl_probe  # noqa: F401
        HAS_UNIX_PTY = True
        logger.debug("Unix PTY available (stdlib pty module) — full terminal on %s",
                      platform.system())
    except ImportError:
        logger.debug("Unix PTY not available — will use subprocess pipe fallback")


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

    # pywinpty is Windows-only — skip entirely on other platforms.
    if platform.system() != "Windows":
        return False

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


def check_unix_pty():
    """
    Public helper: check whether the Unix PTY backend is available.

    Returns True on macOS/Linux where Python's stdlib ``pty`` module
    provides real pseudo-terminal support.  Always False on Windows.

    :return: *True* if Unix PTY is available.
    :rtype: bool
    """
    return HAS_UNIX_PTY


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

        # Unix PTY file descriptors (macOS/Linux) — master_fd is used for
        # reading/writing, child_pid is the shell process PID.
        self._unix_master_fd = None
        self._unix_child_pid = None

        # The subprocess.Popen object — used as last-resort fallback when
        # neither pywinpty nor Unix PTY is available.
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

        On Windows: prefers PowerShell (pwsh for PS7+, then powershell.exe),
        falls back to cmd.exe.
        On macOS/Linux: prefers zsh, falls back to bash, then sh.

        :return: Full path to the shell executable.
        :rtype: str
        """
        if platform.system() == "Windows":
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
        else:
            # macOS/Linux — prefer zsh (macOS default), then bash.
            # Also check $SHELL env var which reflects user preference.
            user_shell = os.environ.get("SHELL", "")
            if user_shell and shutil.which(user_shell):
                return user_shell

            for shell_name in ("zsh", "bash", "sh"):
                found = shutil.which(shell_name)
                if found:
                    return found

            return "/bin/sh"

    # --- Thread Entry Point --------------------------------------------------

    def run(self):
        """
        Thread main: create the terminal process and read output.

        Selects the best available backend for the current platform:
        - Windows: pywinpty (ConPTY), then subprocess fallback
        - macOS/Linux: Unix PTY (stdlib pty), then subprocess fallback
        """
        self._running = True

        # Lazy re-check: pywinpty may have become available since the
        # module was first imported (e.g. setup_venv() ran afterward).
        has_conpty = _ensure_conpty()
        logger.info("Terminal backend thread started (thread=%s, HAS_CONPTY=%s, "
                     "HAS_UNIX_PTY=%s)", self.currentThread(), has_conpty, HAS_UNIX_PTY)

        try:
            if has_conpty:
                # Windows with pywinpty — full ConPTY support.
                self._run_pty()
            elif HAS_UNIX_PTY:
                # macOS/Linux — stdlib pty for a real pseudo-terminal.
                self._run_unix_pty()
            else:
                # Last resort — subprocess pipe fallback.
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

    # --- Unix PTY Backend (macOS/Linux) --------------------------------------

    def _run_unix_pty(self):
        """
        Run the terminal using Python's stdlib ``pty`` module (macOS/Linux).

        Creates a real pseudo-terminal via ``pty.openpty()``, spawns the
        shell as a child process connected to the slave side, and reads
        output from the master fd.  The shell sees a real terminal and
        runs interactively with a prompt, line editing, and ANSI colors.

        This is the preferred backend on macOS/Linux — no third-party
        packages required.
        """
        import pty
        import fcntl
        import struct
        import termios
        import select
        import signal

        # --- Step 1: Create the PTY pair ---
        master_fd, slave_fd = pty.openpty()

        # Set the terminal size on the slave so the shell knows its
        # dimensions at startup (before the first prompt is drawn).
        winsize = struct.pack("HHHH", self._rows, self._cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        # Store master fd for write() and resize() calls from other threads.
        self._unix_master_fd = master_fd

        # --- Step 2: Fork and exec the shell ---
        # Build environment — keep the user's env but set TERM for proper
        # ANSI support.  xterm-256color is widely supported and gives the
        # shell full color capabilities.
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = str(self._cols)
        env["LINES"] = str(self._rows)

        # macOS SSL fix — Maya's environment doesn't include the system
        # CA certificate bundle.  Node.js apps like Claude Code need
        # NODE_EXTRA_CA_CERTS to find the system certs, and Python apps
        # need SSL_CERT_FILE.  Without these, all HTTPS requests fail
        # with "SSL certificate verification failed".
        if platform.system() == "Darwin":
            cert_file = "/etc/ssl/cert.pem"
            if os.path.isfile(cert_file):
                env.setdefault("SSL_CERT_FILE", cert_file)
                env.setdefault("NODE_EXTRA_CA_CERTS", cert_file)

        pid = os.fork()
        if pid == 0:
            # --- Child process ---
            # Create a new session so the child becomes the session leader
            # and the slave PTY becomes its controlling terminal.
            os.setsid()

            # Set the slave as the controlling terminal.
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

            # Redirect stdin/stdout/stderr to the slave PTY.
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)

            # Close the master fd in the child — only the parent reads it.
            os.close(master_fd)

            # Close the original slave fd (now duplicated to 0/1/2).
            if slave_fd > 2:
                os.close(slave_fd)

            # Exec the shell as a login shell (-l) so it sources the
            # user's profile (.zprofile, .bash_profile, etc.).  This is
            # critical on macOS where GUI apps like Maya launch with a
            # minimal PATH that doesn't include Homebrew, nvm, etc.
            os.execvpe(self._shell, [self._shell, "-l"], env)
            # If exec fails, exit the child.
            os._exit(1)

        # --- Parent process ---
        # Close the slave fd in the parent — only the child uses it.
        os.close(slave_fd)

        self._unix_child_pid = pid
        logger.info("Unix PTY spawned: shell=%s, pid=%d, size=%dx%d",
                     self._shell, pid, self._cols, self._rows)

        # --- Step 3: Read loop ---
        # Use select() with a short timeout for responsive, non-busy reads.
        while self._running:
            try:
                # Wait up to 50ms for data — balances responsiveness with
                # CPU usage.  select() returns immediately if data is ready.
                readable, _, _ = select.select([master_fd], [], [], 0.05)
            except (ValueError, OSError):
                # fd was closed or became invalid — shell exited.
                if self._running:
                    logger.info("Unix PTY select() error — shell exited")
                break

            if readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    # Read error — PTY closed, shell exited.
                    if self._running:
                        logger.info("Unix PTY read error — shell exited")
                    break

                if chunk:
                    # Log the first data chunk to confirm the pipeline works.
                    if not self._first_data_logged:
                        self._first_data_logged = True
                        logger.info("Unix PTY first data: %d bytes (read loop OK)",
                                    len(chunk))

                    # Store in the thread-safe buffer.
                    with self._buffer_lock:
                        self._data_buffer.append(chunk)

                    # Also emit signal (may not be reliably delivered).
                    self.data_received.emit(chunk)
                else:
                    # Empty read means EOF — shell exited.
                    if self._running:
                        logger.info("Unix PTY EOF — shell exited")
                    break

        # --- Cleanup ---
        # Close the master fd.
        try:
            os.close(master_fd)
        except OSError:
            pass
        self._unix_master_fd = None

        # Wait for the child process to avoid zombies.
        try:
            _, status = os.waitpid(pid, os.WNOHANG)
            if os.WIFEXITED(status):
                self._unix_exit_code = os.WEXITSTATUS(status)
            else:
                self._unix_exit_code = -1
        except ChildProcessError:
            # Already reaped.
            self._unix_exit_code = 0
        except Exception:
            self._unix_exit_code = -1

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
        # On non-Windows platforms, subprocess pipe is the normal backend
        # (pywinpty is Windows-only ConPTY).  Only log at INFO on Windows
        # where it indicates a missing optional dependency.
        if platform.system() == "Windows":
            logger.info("pywinpty not available — using subprocess fallback")
        else:
            logger.debug("Using subprocess pipe backend (normal for %s)",
                         platform.system())

        # Build environment with TERM set so programs know we're not
        # a full terminal (avoids them trying full-screen tricks).
        env = os.environ.copy()
        env["TERM"] = "dumb"

        # Spawn the shell with merged stdout/stderr.
        # CREATE_NO_WINDOW prevents a visible console window from
        # flashing on screen when the subprocess starts (Windows only).
        kwargs = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self._cwd,
            env=env,
        )
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        self._proc = subprocess.Popen([self._shell], **kwargs)

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

        Checks all three backends: pywinpty PTY, Unix PTY, subprocess.

        :return: Exit code, or -1 if unavailable.
        :rtype: int
        """
        # pywinpty PTY path — ask pywinpty for the exit status.
        if self._pty:
            try:
                code = self._pty.get_exitstatus()
                if code is not None:
                    return code
            except Exception:
                pass

        # Unix PTY path — exit code was captured in _run_unix_pty().
        if hasattr(self, "_unix_exit_code"):
            return self._unix_exit_code

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

        Dispatches to the active backend (pywinpty, Unix PTY, or
        subprocess pipe).  Thread-safe.

        :param bytes data: Raw bytes to send to the shell.
        """
        if not self._running:
            logger.warning("write(): backend not running, dropping %d bytes",
                           len(data) if data else 0)
            return

        # pywinpty PTY path — pywinpty.PTY.write() expects a string.
        if self._pty:
            try:
                if isinstance(data, bytes):
                    text = data.decode("utf-8", errors="replace")
                else:
                    text = data
                # Log paste-sized writes at DEBUG to avoid flooding
                # Maya's Script Editor.  Only the paste_clipboard()
                # caller logs at INFO for user-visible diagnostics.
                if len(text) > 10:
                    logger.debug("PTY write: %d chars", len(text))
                self._pty.write(text)
            except Exception as e:
                logger.error("PTY write error: %s", e)

        # Unix PTY path — write raw bytes to the master fd.
        elif self._unix_master_fd is not None:
            try:
                if isinstance(data, str):
                    data = data.encode("utf-8")
                os.write(self._unix_master_fd, data)
            except OSError as e:
                logger.error("Unix PTY write error: %s", e)

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
        informed about the available screen real estate.  Both PTY
        backends (pywinpty and Unix) support real resize.  Subprocess
        pipes silently ignore the request since they have no concept
        of terminal size.

        :param int rows: New row count.
        :param int cols: New column count.
        """
        self._rows = rows
        self._cols = cols

        # pywinpty PTY path — inform the ConPTY of the new size.
        if self._pty and self._running:
            try:
                self._pty.set_size(cols, rows)
                logger.debug("PTY resized to %dx%d", cols, rows)
            except Exception as e:
                logger.error("PTY resize error: %s", e)

        # Unix PTY path — send TIOCSWINSZ ioctl to update terminal size.
        elif self._unix_master_fd is not None and self._running:
            try:
                import fcntl
                import struct
                import termios
                import signal as _signal
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self._unix_master_fd, termios.TIOCSWINSZ, winsize)
                # Send SIGWINCH to the child so the shell redraws its prompt.
                if self._unix_child_pid:
                    os.kill(self._unix_child_pid, _signal.SIGWINCH)
                logger.debug("Unix PTY resized to %dx%d", cols, rows)
            except Exception as e:
                logger.error("Unix PTY resize error: %s", e)

        # Subprocess path — no-op, pipes don't support resize.

    def terminate(self):
        """
        Stop the read loop and kill the child process.

        Handles cleanup for all three backends (pywinpty, Unix PTY,
        subprocess).  Safe to call from the main thread.  Explicitly
        kills the child shell process so Maya doesn't hang on exit
        waiting for orphaned children.
        """
        self._running = False

        # pywinpty PTY path — explicitly kill the child shell process via
        # its PID so the ConPTY closes cleanly.  Relying on garbage
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

        # Unix PTY path — kill the child process and close the master fd.
        if self._unix_child_pid:
            try:
                import signal
                os.kill(self._unix_child_pid, signal.SIGTERM)
                logger.info("Sent SIGTERM to Unix PTY child (pid=%d)",
                            self._unix_child_pid)
            except (ProcessLookupError, OSError):
                # Process already exited.
                pass
            except Exception as exc:
                logger.warning("Failed to kill Unix PTY child: %s", exc)

            # Reap the child to avoid zombie processes.
            try:
                os.waitpid(self._unix_child_pid, os.WNOHANG)
            except ChildProcessError:
                pass
            except Exception:
                pass
            self._unix_child_pid = None

        if self._unix_master_fd is not None:
            try:
                os.close(self._unix_master_fd)
            except OSError:
                pass
            self._unix_master_fd = None

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
