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


# --- Internal Exceptions ----------------------------------------------------

class _ConPTYBrokenError(RuntimeError):
    """Raised when pywinpty's ConPTY spawns but doesn't forward output."""
    pass


# --- Direct ConPTY via ctypes -----------------------------------------------
# On some Windows 11 Insider builds (e.g. 26200), conpty.dll is missing
# from System32 and kernel32.CreatePseudoConsole (used by pywinpty) fails
# to forward shell output.  However, pywinpty 3.0.3 ships its own
# conpty.dll which DOES work when called directly.  This module provides
# a ctypes fallback that calls conpty.dll's CreatePseudoConsole instead
# of kernel32's, giving a real PTY even on broken Windows builds.

HAS_DIRECT_CONPTY = False
_CONPTY_DLL_PATH = None

if platform.system() == "Windows":
    # Look for conpty.dll: first in System32, then bundled with pywinpty.
    import ctypes
    import ctypes.wintypes as _wt

    _sys32_dll = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"),
                              "System32", "conpty.dll")
    if os.path.isfile(_sys32_dll):
        _CONPTY_DLL_PATH = _sys32_dll
    else:
        # Try to find pywinpty's bundled copy.
        try:
            import winpty as _wp
            _pkg_dll = os.path.join(os.path.dirname(_wp.__file__), "conpty.dll")
            if os.path.isfile(_pkg_dll):
                _CONPTY_DLL_PATH = _pkg_dll
        except ImportError:
            pass

    if _CONPTY_DLL_PATH:
        try:
            _conpty_dll = ctypes.WinDLL(_CONPTY_DLL_PATH)
            # Verify the key export exists.
            _conpty_dll.CreatePseudoConsole
            HAS_DIRECT_CONPTY = True
            logger.debug("Direct ConPTY available: %s", _CONPTY_DLL_PATH)
        except Exception as _e:
            logger.debug("Direct ConPTY not available: %s", _e)


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

        # Platform guard: Unix PTY must never run on Windows (even if
        # pty module is importable in UE's embedded Python).
        is_windows = platform.system() == "Windows"

        try:
            if has_conpty:
                # Windows with pywinpty — try ConPTY first.
                self._run_pty()
            elif not is_windows and HAS_UNIX_PTY:
                # macOS/Linux — stdlib pty for a real pseudo-terminal.
                self._run_unix_pty()
            else:
                # Last resort — subprocess pipe fallback.
                self._run_subprocess()
        except _ConPTYBrokenError:
            # pywinpty's ConPTY spawned but didn't forward output.
            # Try calling conpty.dll directly — works on Windows 11
            # Insider builds where kernel32's path is broken.  This
            # fallback is the normal working path on newer Win11 builds,
            # so log at debug level to avoid alarming the user.
            if HAS_DIRECT_CONPTY:
                logger.debug("pywinpty ConPTY unavailable — using direct "
                             "conpty.dll path")
                # Clear any stale data from the broken pywinpty session
                # so the ANSI parser starts fresh with the new ConPTY.
                with self._buffer_lock:
                    self._data_buffer.clear()
                self._first_data_logged = False
                try:
                    self._run_direct_conpty()
                except Exception as e2:
                    logger.error("Direct ConPTY also failed: %s", e2,
                                 exc_info=True)
            else:
                logger.error("ConPTY broken and no direct conpty.dll "
                             "fallback available")
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

        Includes a 3-second sanity check after spawn to detect broken
        ConPTY implementations (e.g. Windows 11 Insider builds where
        kernel32's CreatePseudoConsole doesn't forward shell output).
        Raises ``_ConPTYBrokenError`` if only escape sequences arrive.
        """
        import re

        # --- Step 1: Create the PTY ---
        self._pty = WinPTY(self._cols, self._rows)

        # --- Step 2: Spawn the shell ---
        if not self._pty.spawn(self._shell, cwd=self._cwd):
            raise RuntimeError("Failed to spawn shell: {}".format(self._shell))

        logger.info("PTY spawned: shell=%s, pid=%d, size=%dx%d",
                     self._shell, self._pty.pid, self._cols, self._rows)

        # --- Step 3: Sanity check ---
        # Wait up to 3 seconds for printable (non-escape-sequence) output.
        # A working ConPTY sends the shell prompt within this window.
        prompt_received = False
        sanity_deadline = time.time() + 3.0
        init_data = []

        while self._running and time.time() < sanity_deadline:
            try:
                data = self._pty.read(blocking=False)
            except Exception:
                if self._pty.iseof():
                    break
                time.sleep(0.01)
                continue
            if data:
                raw = data.encode("utf-8", errors="replace")
                init_data.append(raw)
                # Strip ANSI escape sequences and check for visible chars.
                stripped = re.sub(rb'\x1b\[[^a-zA-Z]*[a-zA-Z]', b'', raw)
                stripped = re.sub(rb'\x1b\][^\x07]*\x07', b'', stripped)
                if stripped.strip():
                    prompt_received = True
                    break
            else:
                if self._pty.iseof():
                    break
                time.sleep(0.05)

        if not prompt_received and self._running and not self._pty.iseof():
            # Expected on newer Windows 11 builds where pywinpty's
            # kernel32 path is broken — the direct conpty.dll fallback
            # handles this cleanly, so keep the log quiet.
            logger.debug("pywinpty ConPTY sanity check failed after 3s — "
                         "falling back to direct conpty.dll")
            self._pty = None
            raise _ConPTYBrokenError("ConPTY not forwarding shell output")

        # Push sanity-check data into the buffer.
        if init_data:
            with self._buffer_lock:
                self._data_buffer.extend(init_data)
            if not self._first_data_logged:
                self._first_data_logged = True

        # --- Step 4: Read loop ---
        while self._running:
            try:
                data = self._pty.read(blocking=False)
            except Exception as read_exc:
                # pywinpty raises WinptyError on non-blocking reads when
                # no data is available.  Only break if the process exited.
                if self._pty.iseof():
                    if self._running:
                        logger.info("PTY read exception + EOF — shell exited")
                    break
                logger.debug("PTY non-blocking read (not EOF): %s", read_exc)
                time.sleep(0.01)
                continue

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

    # --- Direct ConPTY Backend (ctypes) ----------------------------------------

    def _run_direct_conpty(self):
        """
        Run the terminal using conpty.dll directly via ctypes.

        This fallback is used when pywinpty's ConPTY path fails (it calls
        kernel32.CreatePseudoConsole which relies on the system conhost).
        On some Windows 11 Insider builds, the system conhost is broken
        but conpty.dll's own CreatePseudoConsole works because it bundles
        its own console implementation.

        Creates pipes, calls conpty.dll's CreatePseudoConsole, spawns
        the shell, and reads output from the pipe.  This is a real PTY
        — full ANSI support, interactive programs, cursor positioning.
        """
        import ctypes
        import ctypes.wintypes as wt

        dll = ctypes.WinDLL(_CONPTY_DLL_PATH)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # --- Constants ---
        PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
        EXTENDED_STARTUPINFO_PRESENT = 0x00080000

        # --- Structures ---
        class COORD(ctypes.Structure):
            _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]

        class STARTUPINFOW(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR),
                ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
                ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE),
            ]

        class STARTUPINFOEXA(ctypes.Structure):
            _fields_ = [
                ("StartupInfo", STARTUPINFOW),
                ("lpAttributeList", ctypes.c_void_p),
            ]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD),
            ]

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("nLength", wt.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wt.BOOL),
            ]

        # --- Helper: create an anonymous pipe ---
        def _create_pipe():
            r_h, w_h = wt.HANDLE(), wt.HANDLE()
            sa = SECURITY_ATTRIBUTES()
            sa.nLength = ctypes.sizeof(sa)
            sa.bInheritHandle = True
            if not k32.CreatePipe(ctypes.byref(r_h), ctypes.byref(w_h),
                                  ctypes.byref(sa), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            return r_h.value, w_h.value

        # --- Step 1: Create pipes ---
        pty_in_read, pty_in_write = _create_pipe()
        pty_out_read, pty_out_write = _create_pipe()

        # --- Step 2: Create pseudo-console via conpty.dll ---
        size = COORD(self._cols, self._rows)
        hPC = wt.HANDLE()
        hr = dll.CreatePseudoConsole(
            size, wt.HANDLE(pty_in_read), wt.HANDLE(pty_out_write),
            wt.DWORD(0), ctypes.byref(hPC),
        )
        if hr != 0:
            raise RuntimeError(
                "conpty.dll CreatePseudoConsole failed: HRESULT 0x{:08x}"
                .format(hr & 0xFFFFFFFF))

        logger.info("Direct ConPTY created via %s", _CONPTY_DLL_PATH)

        # Store for resize and cleanup.
        self._direct_conpty_handle = hPC
        self._direct_conpty_dll = dll
        self._direct_conpty_k32 = k32
        self._direct_conpty_in_write = pty_in_write
        self._direct_conpty_out_read = pty_out_read

        # --- Step 3: Spawn shell with the pseudo-console ---
        attr_size = ctypes.c_size_t(0)
        k32.InitializeProcThreadAttributeList(None, 1, 0,
                                              ctypes.byref(attr_size))
        attr_list = (ctypes.c_byte * attr_size.value)()
        if not k32.InitializeProcThreadAttributeList(attr_list, 1, 0,
                                                     ctypes.byref(attr_size)):
            raise ctypes.WinError(ctypes.get_last_error())

        if not k32.UpdateProcThreadAttribute(
                attr_list, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                hPC, ctypes.sizeof(wt.HANDLE), None, None):
            raise ctypes.WinError(ctypes.get_last_error())

        si = STARTUPINFOEXA()
        si.StartupInfo.cb = ctypes.sizeof(si)
        si.lpAttributeList = ctypes.cast(attr_list, ctypes.c_void_p).value
        pi = PROCESS_INFORMATION()

        if not k32.CreateProcessW(
                None, self._shell, None, None, False,
                EXTENDED_STARTUPINFO_PRESENT, None, self._cwd,
                ctypes.byref(si.StartupInfo), ctypes.byref(pi)):
            raise ctypes.WinError(ctypes.get_last_error())

        self._direct_conpty_pid = pi.dwProcessId
        self._direct_conpty_hProcess = pi.hProcess
        logger.info("Direct ConPTY shell spawned: pid=%d, shell=%s",
                     pi.dwProcessId, self._shell)

        # Close handles the child owns.
        k32.CloseHandle(wt.HANDLE(pty_in_read))
        k32.CloseHandle(wt.HANDLE(pty_out_write))
        k32.CloseHandle(pi.hThread)

        # --- Step 4: Read loop ---
        # Use PeekNamedPipe before ReadFile so the loop never blocks
        # indefinitely.  This lets terminate() set _running=False and
        # the thread exits within one poll cycle (~5ms) — no need for
        # cross-thread ClosePseudoConsole or CancelIo, which caused
        # crashes on editor close.
        buf = (ctypes.c_ubyte * 4096)()
        bytes_read = wt.DWORD()
        avail = wt.DWORD()
        pipe_handle = wt.HANDLE(pty_out_read)

        while self._running:
            # Check if data is available without blocking.
            peek_ok = k32.PeekNamedPipe(
                pipe_handle, None, 0, None, ctypes.byref(avail), None,
            )
            if not peek_ok:
                # Pipe broken — shell exited or pseudo-console closed.
                err = ctypes.get_last_error()
                if self._running:
                    logger.info("Direct ConPTY pipe closed — shell exited "
                                "(PeekNamedPipe error %d)", err)
                break

            if avail.value == 0:
                # No data yet — sleep briefly to avoid busy-wait, then
                # re-check _running at the top of the loop.
                time.sleep(0.005)
                continue

            # Data is available — read it (non-blocking since we peeked).
            success = k32.ReadFile(
                pipe_handle, buf, 4096,
                ctypes.byref(bytes_read), None,
            )
            if success and bytes_read.value > 0:
                chunk = bytes(buf[:bytes_read.value])

                if not self._first_data_logged:
                    self._first_data_logged = True
                    logger.info("Direct ConPTY first data: %d bytes", len(chunk))

                with self._buffer_lock:
                    self._data_buffer.append(chunk)
                self.data_received.emit(chunk)
            elif not success:
                err = ctypes.get_last_error()
                if err == 109:  # ERROR_BROKEN_PIPE — shell exited.
                    if self._running:
                        logger.info("Direct ConPTY pipe closed — shell exited")
                    break
                logger.debug("Direct ConPTY ReadFile error: %d", err)
                break

        # --- Cleanup ---
        # ClosePseudoConsole may already have been called by terminate()
        # from the main thread — the try/except handles double-close.
        try:
            dll.ClosePseudoConsole(hPC)
        except Exception:
            pass
        # Kill and close the child process.
        try:
            k32.TerminateProcess(pi.hProcess, 1)
        except Exception:
            pass
        try:
            k32.CloseHandle(pi.hProcess)
        except Exception:
            pass
        # Close pipe handles — safe now that the read loop has exited.
        try:
            k32.CloseHandle(wt.HANDLE(pty_out_read))
        except Exception:
            pass
        try:
            k32.CloseHandle(wt.HANDLE(pty_in_write))
        except Exception:
            pass

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
        # Direct ConPTY path — query process exit code.
        if hasattr(self, "_direct_conpty_hProcess"):
            try:
                import ctypes
                import ctypes.wintypes as wt
                exit_code = wt.DWORD()
                self._direct_conpty_k32.GetExitCodeProcess(
                    self._direct_conpty_hProcess, ctypes.byref(exit_code))
                if exit_code.value != 259:  # STILL_ACTIVE
                    return exit_code.value
            except Exception:
                pass

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

        # Direct ConPTY path — write raw bytes to the input pipe.
        if hasattr(self, "_direct_conpty_in_write"):
            try:
                import ctypes
                import ctypes.wintypes as wt
                if isinstance(data, str):
                    data = data.encode("utf-8")
                written = wt.DWORD()
                self._direct_conpty_k32.WriteFile(
                    wt.HANDLE(self._direct_conpty_in_write),
                    data, len(data), ctypes.byref(written), None,
                )
            except Exception as e:
                logger.error("Direct ConPTY write error: %s", e)
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

        # Direct ConPTY path — resize via conpty.dll.
        if hasattr(self, "_direct_conpty_handle") and self._running:
            try:
                import ctypes
                import ctypes.wintypes as wt

                class COORD(ctypes.Structure):
                    _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]

                size = COORD(cols, rows)
                self._direct_conpty_dll.ResizePseudoConsole(
                    self._direct_conpty_handle, size)
                logger.debug("Direct ConPTY resized to %dx%d", cols, rows)
            except Exception as e:
                logger.debug("Direct ConPTY resize error: %s", e)
            return

        # pywinpty PTY path — inform the ConPTY of the new size.
        if self._pty and self._running:
            try:
                self._pty.set_size(cols, rows)
                logger.debug("PTY resized to %dx%d", cols, rows)
            except Exception as e:
                logger.debug("PTY resize error: %s", e)

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

        # Direct ConPTY path — the read loop uses PeekNamedPipe (non-blocking),
        # so setting _running=False above is enough to stop it within ~5ms.
        # All handle cleanup happens in the worker thread's own cleanup
        # section after the loop exits.  Do NOT touch any ConPTY handles
        # from the main thread — cross-thread handle operations crash.

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

        # Wait for the thread to finish.  With the pseudo-console/PTY/pipe
        # now closed, the blocking ReadFile should return immediately.
        # Use a short timeout as a safety net — never block Maya's main
        # thread for more than 1 second on editor close.
        if self.isRunning():
            self.wait(1000)
