"""
MCA Core - Native Console Embedding Widget.

Embeds a REAL Windows console window (PowerShell, WSL, cmd, ...) inside
a Qt widget by reparenting its native HWND -- no custom terminal
emulator, no ANSI/VT100 parser, no PTY library. Windows' own console
host renders everything, so interactive full-screen TUI apps (Claude
Code, Codex, vim, htop) work exactly as they would in a real terminal
window.

This trades the previous approach (plain QProcess + text pipes, which
could not reliably feed non-ASCII input to Windows PowerShell's
non-interactive stdin parser -- see git history) for a well-known
Win32 technique: spawn the process with its own console, locate that
console's HWND via AttachConsole()/GetConsoleWindow() (the documented,
PID-stable way -- EnumWindows + PID matching is NOT reliable because
window ownership can transfer to an internal conhost/OpenConsole
process shortly after startup), then SetParent() it into a container
widget and keep it resized to fill that widget.

This is a well-known but unofficial technique (not a supported Win32
scenario) -- Microsoft does not guarantee reparented console windows
behave identically to top-level ones. Keep it isolated behind this one
widget so any future console-specific quirk is easy to find and fix.

Dependencies:
    - ctypes (stdlib) -- Win32 API calls
    - subprocess (stdlib) -- spawning the console process
    - mca_qt.qt_compat (QWidget, QTimer)

Side Effects:
    - Spawns a console child process (e.g. powershell.exe, wsl.exe) on
      widget creation.
    - Reparents that process's top-level window via SetParent().
    - Terminates the child process in cleanup().
"""

import ctypes
import logging
import platform
import subprocess
from ctypes import wintypes

from mca_qt.qt_compat import QWidget, QTimer

# Module-level logger.
logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _kernel32.AttachConsole.argtypes = [wintypes.DWORD]
    _kernel32.AttachConsole.restype = wintypes.BOOL
    _kernel32.FreeConsole.restype = wintypes.BOOL
    _kernel32.GetConsoleWindow.restype = wintypes.HWND

    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.SetParent.restype = wintypes.HWND
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
    _user32.MoveWindow.argtypes = [
        wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.BOOL,
    ]
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _IO_COUNTERS(ctypes.Structure):
        """Mirrors the Win32 IO_COUNTERS struct (unused fields, but the
        layout must match exactly for JOBOBJECT_EXTENDED_LIMIT_INFORMATION)."""

        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        """Mirrors the Win32 JOBOBJECT_BASIC_LIMIT_INFORMATION struct."""

        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        """Mirrors the Win32 JOBOBJECT_EXTENDED_LIMIT_INFORMATION struct."""

        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

# --- Win32 constants ---------------------------------------------------------

_CREATE_NEW_CONSOLE = 0x00000010
_GWL_STYLE = -16
_WS_CHILD = 0x40000000
_WS_POPUP = -0x80000000  # 0x80000000 interpreted as a signed LONG
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_SW_SHOW = 5

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOBOBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

# How long (ms) to keep retrying AttachConsole after spawning before
# giving up -- the child's console is normally ready within ~0.3s.
_ATTACH_RETRY_TOTAL_MS = 3000
_ATTACH_RETRY_INTERVAL_MS = 100

# How long (ms) to wait for the child process to exit on cleanup before
# killing it outright.
_STOP_TIMEOUT_MS = 2000


class EmbeddedConsoleWidget(QWidget):
    """
    Hosts a real Windows console process, reparented to fill this widget.

    :param list command: Argv for the console process, e.g.
        ``["powershell.exe", "-NoLogo", "-NoExit"]`` or
        ``["wsl.exe", "--cd", scripts_dir]``.
    :param str cwd: Working directory to launch the process in
        (ignored by ``wsl.exe``, which only honors its own ``--cd`` arg).
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, command, cwd=None, parent=None):
        """
        Start *command* as a console child process and begin embedding it.

        :param list command: Argv for the console process.
        :param str cwd: Working directory for the child process.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)

        self._command = command
        self._cwd = cwd
        self._process = None
        self._console_hwnd = None
        self._attach_attempts_left = 0
        self._job_handle = None

        if not _IS_WINDOWS:
            logger.warning("Native console embedding requires Windows.")
            return

        self._start_process()

    # --- Process lifecycle ----------------------------------------------------

    def _start_process(self):
        """Spawn the console child process and start polling for its HWND."""
        try:
            self._process = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except OSError as exc:
            logger.warning("Failed to start %r: %s", self._command, exc)
            return

        self._assign_kill_on_close_job(self._process.pid)

        self._attach_attempts_left = (
            _ATTACH_RETRY_TOTAL_MS // _ATTACH_RETRY_INTERVAL_MS
        )
        self._attach_timer = QTimer(self)
        self._attach_timer.setInterval(_ATTACH_RETRY_INTERVAL_MS)
        self._attach_timer.timeout.connect(self._try_attach)
        self._attach_timer.start()

    def _assign_kill_on_close_job(self, pid):
        """
        Put the child process in a Job Object with KILL_ON_JOB_CLOSE.

        Guarantees the console process is terminated by Windows itself
        the moment our own process exits for ANY reason -- including a
        crash or a force-kill that skips cleanup() entirely. Without
        this, a hard-killed editor leaves the embedded PowerShell/WSL
        process running as an orphan (confirmed while testing this
        widget: ``taskkill /F /T`` on the editor process did not stop
        the reparented console, since the OS process tree and the
        reparented *window* tree are unrelated).

        Failure here is non-fatal -- the process still gets terminated
        on the normal path via cleanup(), this is extra protection for
        the abnormal path.

        :param int pid: PID of the already-spawned child process.
        """
        job_handle = _kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            logger.warning("CreateJobObjectW failed; no crash-safety net for pid %d", pid)
            return

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            job_handle,
            _JOBOBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            logger.warning("SetInformationJobObject failed for pid %d", pid)
            _kernel32.CloseHandle(job_handle)
            return

        process_handle = _kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid,
        )
        if not process_handle:
            logger.warning("OpenProcess failed for pid %d", pid)
            _kernel32.CloseHandle(job_handle)
            return

        if _kernel32.AssignProcessToJobObject(job_handle, process_handle):
            # Keep the job handle alive for the widget's lifetime -- Windows
            # applies KILL_ON_JOB_CLOSE when the LAST handle to the job
            # closes, which happens automatically if our process exits
            # without ever calling cleanup().
            self._job_handle = job_handle
        else:
            logger.warning("AssignProcessToJobObject failed for pid %d", pid)
            _kernel32.CloseHandle(job_handle)

        _kernel32.CloseHandle(process_handle)

    def _try_attach(self):
        """
        Poll ``AttachConsole()`` for the child's console window.

        Retries on a short timer because the child's console is not
        guaranteed to be ready the instant the process object exists.
        Once found, reparents it and stops the timer.
        """
        self._attach_attempts_left -= 1
        hwnd = self._get_console_hwnd(self._process.pid)

        if hwnd is None:
            if self._attach_attempts_left <= 0:
                self._attach_timer.stop()
                logger.warning(
                    "Gave up waiting for console window for pid %d",
                    self._process.pid,
                )
            return

        self._attach_timer.stop()
        self._console_hwnd = hwnd
        self._embed(hwnd)

    @staticmethod
    def _get_console_hwnd(pid):
        """
        Resolve a process's console window handle.

        Uses ``AttachConsole()``/``GetConsoleWindow()`` rather than
        enumerating top-level windows and matching on owning PID --
        ownership of the console window can transfer to an internal
        conhost/OpenConsole process shortly after the child starts,
        which makes PID-based ``EnumWindows`` matching unreliable.

        :param int pid: Target process ID.
        :return: The console HWND, or None if unavailable.
        :rtype: int or None
        """
        _kernel32.FreeConsole()
        if not _kernel32.AttachConsole(pid):
            return None
        hwnd = _kernel32.GetConsoleWindow()
        _kernel32.FreeConsole()
        return hwnd or None

    def _embed(self, hwnd):
        """
        Reparent the console window into this widget and size it to fit.

        :param int hwnd: The console window handle to embed.
        """
        style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
        new_style = (style & ~_WS_POPUP & ~_WS_CAPTION & ~_WS_THICKFRAME) | _WS_CHILD
        _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, new_style)

        container_hwnd = int(self.winId())
        _user32.SetParent(hwnd, container_hwnd)
        _user32.ShowWindow(hwnd, _SW_SHOW)
        self._resize_console()

        logger.info("Embedded console hwnd 0x%x for %r", hwnd, self._command)

    def resizeEvent(self, event):
        """Keep the embedded console filling this widget on resize."""
        super().resizeEvent(event)
        self._resize_console()

    def _resize_console(self):
        """Resize the embedded console window to match this widget's size."""
        if self._console_hwnd is None:
            return
        if not _user32.IsWindow(self._console_hwnd):
            self._console_hwnd = None
            return
        _user32.MoveWindow(
            self._console_hwnd, 0, 0, self.width(), self.height(), True,
        )

    # --- Cleanup ----------------------------------------------------------------

    def cleanup(self):
        """
        Terminate the console child process.

        Called by the plugin's ``deactivate()`` so the process doesn't
        linger after the panel is removed or the editor closes.
        Destroying this widget's HWND also destroys the reparented
        console window (it is a WS_CHILD of it), but that alone does
        not guarantee the underlying process exits.
        """
        if hasattr(self, "_attach_timer"):
            self._attach_timer.stop()

        if self._job_handle is not None:
            # Not required for crash-safety (our process exiting closes
            # this automatically), just tidy on the normal close path.
            _kernel32.CloseHandle(self._job_handle)
            self._job_handle = None

        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=_STOP_TIMEOUT_MS / 1000.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self._console_hwnd = None
