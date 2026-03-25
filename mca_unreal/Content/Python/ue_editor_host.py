"""
MCA Editor — Unreal Engine Host Script.

Launches the PySide6 MCA Editor as a free-floating Qt window that floats
above UE's main window via Win32 owner-window relationship. Same editor
as Maya — same codebase, same features, same theme — but configured for UE:

  - No MEL language option (Python + Text only)
  - UE Output Log tailed into the MCA Editor output panel
  - Separate session workspace (ue_scripts/)
  - dcc_version="UE5" for session isolation

The C++ plugin passes UE's main window HWND to launch(). We use
SetWindowLongPtrW(qt_hwnd, GWLP_HWNDPARENT, ue_hwnd) to establish a
Win32 owner-window relationship. This makes the editor:
  - Float above UE's window (but NOT above other applications)
  - Minimize/restore together with UE
  - Behave as a proper owned popup — no WS_EX_TOPMOST hack

Called by the C++ MCAEditorModule when the user clicks the toolbar button.

Dependencies:
    - PySide6 (installed via managed venv)
    - mca_core, mca_qt packages (from MCA Editor source)
"""

import sys
import os
import re
import logging
import ctypes
import ctypes.wintypes

# --- UE logging helper -----------------------------------------------------
# Python's logging module does NOT route to UE's Output Log.
# Use unreal.log() for messages that must appear in the UE log.
try:
    import unreal as _unreal
    def _ue_log(msg):
        _unreal.log(f"[MCAEditor] {msg}")
    def _ue_log_warning(msg):
        _unreal.log_warning(f"[MCAEditor] {msg}")
    def _ue_log_error(msg):
        _unreal.log_error(f"[MCAEditor] {msg}")
except ImportError:
    # Running outside UE — fall back to print.
    _unreal = None
    def _ue_log(msg):
        print(f"[MCAEditor] {msg}")
    def _ue_log_warning(msg):
        print(f"[MCAEditor] WARNING: {msg}")
    def _ue_log_error(msg):
        print(f"[MCAEditor] ERROR: {msg}")

# --- Module-level logger ---------------------------------------------------
logger = logging.getLogger("mca_editor.ue_host")


# --- Win32 Owner-Window Constants & ctypes Setup ---------------------------
# GWLP_HWNDPARENT (-8) sets the OWNER of a WS_POPUP window (despite the
# misleading name). An owned window floats above its owner in z-order but
# NOT above other applications — unlike WS_EX_TOPMOST which is global.
_GWLP_HWNDPARENT = -8

# SetWindowPos flags — apply style changes without moving/resizing.
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020

# user32 function signatures for 64-bit Windows.
_user32 = ctypes.windll.user32

# SetWindowLongPtrW: sets window attributes. On x64, LONG_PTR is 8 bytes.
_user32.SetWindowLongPtrW.argtypes = [
    ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_longlong
]
_user32.SetWindowLongPtrW.restype = ctypes.c_longlong

# GetWindowLongPtrW: retrieves window attributes. Used to verify ownership.
_user32.GetWindowLongPtrW.argtypes = [
    ctypes.wintypes.HWND, ctypes.c_int
]
_user32.GetWindowLongPtrW.restype = ctypes.c_longlong

# IsWindow: validates that an HWND is still a live window.
_user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
_user32.IsWindow.restype = ctypes.wintypes.BOOL

# SetWindowPos: needed to apply FRAMECHANGED after owner change.
_user32.SetWindowPos.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.wintypes.BOOL


# --- Module-level state (survives across Python calls in UE) ---------------
_mca_editor_window = None
_mca_app = None
_log_tailer = None       # UELogTailer instance for piping UE logs to the output panel.
_last_qt_hwnd = 0        # Last known HWND of the Qt editor window.
_ue_owner_hwnd = 0       # HWND of UE's main window (owner for z-ordering).
_window_geometry = None  # In-memory geometry cache for within-session reopen.

# QSettings key names for cross-restart persistence.
_QSETTINGS_ORG = "MCAEditor"
_QSETTINGS_APP = "UEPlugin"
_KEY_WAS_OPEN = "ue_editor/was_open"
_KEY_GEOMETRY = "ue_editor/geometry"


# --- Persistent state helpers (QSettings — survives UE restarts) -----------

def _save_persistent_state(was_open, geometry=None):
    """
    Save editor state to QSettings so it persists across UE restarts.

    :param bool was_open: Whether the editor was open (for auto-reopen).
    :param QByteArray geometry: Window geometry from saveGeometry(), or None.
    """
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        settings.setValue(_KEY_WAS_OPEN, was_open)
        if geometry is not None:
            settings.setValue(_KEY_GEOMETRY, geometry)
        settings.sync()
        _ue_log(f"Saved persistent state: was_open={was_open}, geometry={'yes' if geometry else 'no'}")
    except Exception as exc:
        _ue_log_warning(f"Could not save persistent state: {exc}")


def _load_persistent_state():
    """
    Load saved editor state from QSettings.

    :return: Tuple of (was_open, geometry).
    :rtype: tuple(bool, QByteArray or None)
    """
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        was_open = settings.value(_KEY_WAS_OPEN, False, type=bool)
        geometry = settings.value(_KEY_GEOMETRY, None)
        _ue_log(f"Loaded persistent state: was_open={was_open}, geometry={'yes' if geometry else 'no'}")
        return was_open, geometry
    except Exception as exc:
        _ue_log_warning(f"Could not load persistent state: {exc}")
        return False, None


# ============================================================================
# Step 1: Locate MCA Editor source packages
# ============================================================================

# Resolution order:
# 1. Bundled packages alongside this script (Content/Python/mca_core/)
#    — used in distribution builds where packages are packed into the plugin.
# 2. MCA_EDITOR_SOURCE environment variable — for custom installs or CI.
# 3. Hardcoded dev path — for development from the repo checkout.

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLED_DIR = _SCRIPT_DIR  # mca_core/ sits next to ue_editor_host.py in dist
_DEV_DIR = os.environ.get("MCA_EDITOR_SOURCE", r"E:\Projects\MCAEditor")

# Prefer bundled packages (distribution), fall back to dev checkout.
if os.path.isdir(os.path.join(_BUNDLED_DIR, "mca_core")):
    _MCA_SOURCE_DIR = _BUNDLED_DIR
elif os.path.isdir(_DEV_DIR):
    _MCA_SOURCE_DIR = _DEV_DIR
else:
    _MCA_SOURCE_DIR = None
    _ue_log_error("Cannot find MCA Editor packages (checked bundled + dev paths)")

if _MCA_SOURCE_DIR and _MCA_SOURCE_DIR not in sys.path:
    sys.path.insert(0, _MCA_SOURCE_DIR)
    logger.info("Added MCA source to path: %s", _MCA_SOURCE_DIR)


# ============================================================================
# Step 2: Set up managed venv for PySide6
# ============================================================================

def _setup_venv():
    """
    Ensure PySide6 and other deps are available via the managed venv.

    UE's Python doesn't include PySide6 — we install it into a versioned
    venv at ~/Documents/mca_preferences/.venv-X.Y/.
    """
    try:
        from mca_core.venv_manager import setup_venv, REQUIRED_PACKAGES

        # Add PySide6 to the requirements since UE doesn't ship it.
        ue_requirements = dict(REQUIRED_PACKAGES)
        ue_requirements["PySide6>=6.5.0"] = "PySide6"

        setup_venv(requirements=ue_requirements)
        _ue_log("Venv setup complete — PySide6 available")
    except Exception as exc:
        _ue_log_warning(f"Venv setup failed: {exc} — checking if PySide6 is importable")
        try:
            import PySide6
            _ue_log(f"PySide6 already importable: {PySide6.__file__}")
        except ImportError:
            _ue_log_error("PySide6 not available and venv setup failed — cannot launch editor")
            raise


# ============================================================================
# Step 3: UE Output Log Tailer
# ============================================================================

# Regex to parse UE log lines.  Example:
#   [2026.03.22-04.24.14:497][  0]LogPython: [MCAEditor] Something
# Groups: timestamp, frame, category, verbosity (optional), message
_UE_LOG_RE = re.compile(
    r'^\[[\d.\-:]+\]\[\s*\d+\]'       # [timestamp][frame]
    r'(\w+):\s*'                        # LogCategory:
    r'(?:(Display|Warning|Error):\s*)?'  # Optional verbosity prefix
    r'(.*)$'                            # Message
)

# Categories to skip — too noisy or internal.
_SKIP_CATEGORIES = frozenset({
    'LogSlate', 'LogStreaming', 'LogPakFile', 'LogShaderCompilers',
    'LogRHI', 'LogD3D12RHI', 'LogHAL', 'LogConfig', 'LogInit',
    'LogLoad', 'LogUObjectBase', 'LogLinker', 'LogPackageName',
    'LogAssetRegistry', 'LogContentStreaming', 'LogDerivedDataCache',
    'LogEOSSDK', 'LogEOSAnalytics', 'LogCsvProfiler', 'LogStall',
    'LogSourceControl', 'LogPluginManager', 'LogCollectionManager',
    'LogPlacementMode', 'LogZenServiceInstance', 'LogFabLauncher',
    'LogFileCache', 'LogAudio', 'LogCook', 'LogSerialization',
    'LogNetVersion', 'LogSavePackage',
})


class UELogTailer:
    """
    Tails UE's log file and pipes lines to the MCA Editor output panel.

    On creation, loads the tail of the log (up to ``_MAX_HISTORY_BYTES``)
    and dumps it into the output panel with severity coloring. After the
    initial load, polls for new lines periodically.

    :param OutputWindow output: The MCA Editor output panel.
    :param str log_path: Path to UE's log file.
    :param int start_position: Byte offset to start reading from.
        0 = read from beginning (first launch), >0 = resume from saved
        position (reopen after close).
    """

    # Maximum bytes to read on initial history load. UE logs can be 50MB+;
    # reading the whole file blocks UE's main thread and floods the output
    # panel. 256KB gives ~2000 lines of recent context without freezing.
    _MAX_HISTORY_BYTES = 256 * 1024

    def __init__(self, output, log_path, start_position=0):
        self._output = output
        self._log_path = log_path
        self._file = None
        self._position = 0

        # Open the log file and seek to the start position.
        try:
            self._file = open(log_path, 'r', encoding='utf-8', errors='replace')

            # Determine the actual start position. If start_position is 0
            # (first launch / full reload), skip to the tail of the file so
            # we don't process hundreds of thousands of historical lines.
            # The user only needs recent context, not the full startup log.
            if start_position == 0:
                self._file.seek(0, 2)  # Seek to end.
                file_size = self._file.tell()
                if file_size > self._MAX_HISTORY_BYTES:
                    # Jump to near the end and skip the first partial line.
                    start_position = file_size - self._MAX_HISTORY_BYTES
                    self._file.seek(start_position)
                    self._file.readline()  # Discard partial first line.
                    start_position = self._file.tell()
                    _ue_log(f"Log file is {file_size / 1024:.0f}KB — "
                            f"loading last {self._MAX_HISTORY_BYTES / 1024:.0f}KB")
                else:
                    self._file.seek(0)
            else:
                self._file.seek(start_position)

            self._position = start_position
            _ue_log(f"Log tailer started: {log_path}")
            _ue_log(f"  Start position: {start_position} bytes")

            # Load existing log content from start_position to current EOF.
            self._load_history()

        except (OSError, IOError) as exc:
            _ue_log_warning(f"Could not open log file: {exc}")

    def _route_line(self, line):
        """
        Parse a single log line and write it to the output panel with
        the appropriate severity coloring.

        Handles both structured lines (with [timestamp][frame] prefix)
        and unstructured lines (early startup, stack traces). For
        unstructured lines, detects "Error" and "Warning" keywords
        to apply coloring.

        :param str line: A single stripped log line.
        :return: 'written', 'skipped_category', 'skipped_mca', or 'empty'.
        :rtype: str
        """
        # Strip any stray whitespace/CR/LF — the output panel appends its
        # own newline, so any leftover causes double-spacing.
        line = line.strip()
        if not line:
            return 'empty'

        # Skip our own log messages to avoid feedback loops.
        if '[MCAEditor]' in line:
            return 'skipped_mca'

        # Try to parse as a structured UE log line with timestamp.
        match = _UE_LOG_RE.match(line)
        if match:
            category = match.group(1)
            verbosity = match.group(2)  # Display, Warning, Error, or None.
            message = match.group(3)

            # Skip noisy internal categories.
            if category in _SKIP_CATEGORIES:
                return 'skipped_category'

            # Route to the appropriate output method for color formatting.
            label = f"[{category}] {message}"
            if verbosity == 'Error':
                self._output.write_error(label)
            elif verbosity == 'Warning':
                self._output.write_warning(label)
            else:
                self._output.write_output(label)
            return 'written'

        # Unstructured line (early startup, continuation, stack trace).
        # Detect severity keywords for coloring — case-insensitive since
        # UE uses "Warning:" / "Error:" but Python uses "WARNING:" / "ERROR:".
        line_upper = line.upper()
        if ': ERROR:' in line_upper or line_upper.startswith('ERROR:') or line_upper.startswith('ERROR '):
            self._output.write_error(line)
        elif ': WARNING:' in line_upper or line_upper.startswith('WARNING:') or line_upper.startswith('WARNING '):
            self._output.write_warning(line)
        else:
            self._output.write_output(line)
        return 'written'

    # Maximum lines to process during history load. Even with the byte cap,
    # dense log sections could have many short lines. This prevents the
    # output panel from being overloaded on initial load.
    _MAX_HISTORY_LINES = 3000

    def _load_history(self):
        """
        Read recent log content and write it to the output panel.

        Called once during __init__ to load recent log history. Capped at
        ``_MAX_HISTORY_LINES`` to avoid flooding the output panel and
        freezing UE's main thread.
        """
        if self._file is None:
            return

        data = self._file.read()
        if not data:
            _ue_log("  No historical log data to load")
            self._position = self._file.tell()
            return

        # Update position to current EOF.
        self._position = self._file.tell()

        # Parse and route each line with proper severity formatting.
        # Cap at _MAX_HISTORY_LINES to avoid flooding the output panel.
        lines = data.splitlines()
        if len(lines) > self._MAX_HISTORY_LINES:
            _ue_log(f"  Truncating history: {len(lines)} lines → last {self._MAX_HISTORY_LINES}")
            lines = lines[-self._MAX_HISTORY_LINES:]

        total_lines = 0
        written_lines = 0
        skipped_category = 0
        skipped_mca = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue
            total_lines += 1

            result = self._route_line(line)
            if result == 'written':
                written_lines += 1
            elif result == 'skipped_category':
                skipped_category += 1
            elif result == 'skipped_mca':
                skipped_mca += 1

        _ue_log(
            f"  History loaded: {written_lines} lines written, "
            f"{skipped_category} skipped (category), "
            f"{skipped_mca} skipped ([MCAEditor]), "
            f"{total_lines} total parsed"
        )

    def poll(self):
        """
        Read new lines from the log file and write them to the output panel.

        Called periodically from the Qt tick. Reads all new content since
        the last poll and routes each line based on its severity.
        """
        if self._file is None:
            return

        try:
            # On Windows, a file handle that has reached EOF won't see new
            # data appended by another process (UE) unless we re-check the
            # file size. Seek to our last known position to reset the EOF
            # flag, then read whatever UE has appended since.
            self._file.seek(self._position)
            new_data = self._file.read()
            if not new_data:
                return
            # Update our position to the new end.
            self._position = self._file.tell()

            written = 0
            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue

                result = self._route_line(line)
                if result == 'written':
                    written += 1

            # Log a summary when lines are actually processed.
            if written > 0:
                _ue_log(f"Log poll: {written} new lines written to output panel")

        except (OSError, IOError):
            # Log file may have been rotated or deleted.
            pass

    def get_position(self):
        """
        Return the current byte offset in the log file.

        Used to persist the read position across editor close/reopen
        so no log lines are lost.

        :return: Current byte offset.
        :rtype: int
        """
        return self._position

    def close(self):
        """Close the log file handle."""
        if self._file is not None:
            try:
                self._file.close()
            except (OSError, IOError):
                pass
            self._file = None


def _find_ue_log_path():
    """
    Find the current UE session's log file path.

    UE writes its log to Saved/Logs/<ProjectName>.log in the project
    directory. We find it via sys.argv or the known project path.

    :return: Path to the UE log file, or None if not found.
    :rtype: str or None
    """
    # Try to find the project directory from the UE log system.
    if _unreal is not None:
        try:
            # unreal.Paths.project_log_dir() returns the Saved/Logs/ directory.
            log_dir = _unreal.Paths.project_log_dir()
            # The main log file is named after the project target.
            # Find the most recent .log file in the directory.
            if os.path.isdir(log_dir):
                log_files = [
                    os.path.join(log_dir, f) for f in os.listdir(log_dir)
                    if f.endswith('.log') and not f.startswith('.')
                ]
                if log_files:
                    # Return the most recently modified log file.
                    log_files.sort(key=os.path.getmtime, reverse=True)
                    return log_files[0]
        except Exception as exc:
            _ue_log_warning(f"Could not find log via unreal.Paths: {exc}")

    return None


# ============================================================================
# Step 4: Win32 Owner-Window Helper
# ============================================================================

def _set_owner_window(qt_hwnd, owner_hwnd):
    """
    Set the Win32 owner-window relationship so the Qt window floats above
    UE's main window — but NOT above other applications.

    An owned WS_POPUP window always appears above its owner in z-order
    and minimizes/restores with it. This is the correct Win32 mechanism
    for tool windows that belong to a specific application.

    :param int qt_hwnd: The native HWND of the Qt editor window.
    :param int owner_hwnd: The native HWND of UE's main window.
    :return: True if ownership was established successfully.
    :rtype: bool
    """
    # Validate both HWNDs are still live windows.
    if not _user32.IsWindow(qt_hwnd):
        _ue_log_warning(f"_set_owner_window: Qt HWND {hex(qt_hwnd)} is not a valid window")
        return False
    if not _user32.IsWindow(owner_hwnd):
        _ue_log_warning(f"_set_owner_window: Owner HWND {hex(owner_hwnd)} is not a valid window")
        return False

    # Read the current owner before we change it (for logging).
    prev_owner = _user32.GetWindowLongPtrW(qt_hwnd, _GWLP_HWNDPARENT)
    _ue_log(f"  Previous owner HWND = {hex(prev_owner)}")

    # Set the owner via GWLP_HWNDPARENT. For a WS_POPUP window, this
    # establishes an owner relationship (z-ordering + minimize/restore),
    # NOT a parent-child relationship.
    prev = _user32.SetWindowLongPtrW(qt_hwnd, _GWLP_HWNDPARENT, owner_hwnd)
    _ue_log(f"  SetWindowLongPtrW returned prev = {hex(prev)}")

    # Apply the change with FRAMECHANGED so Windows re-evaluates the
    # window's frame and z-order relationship.
    swp_result = _user32.SetWindowPos(
        qt_hwnd, 0,  # hWndInsertAfter = 0 (ignored due to NOZORDER).
        0, 0, 0, 0,  # Position/size ignored due to NOMOVE | NOSIZE.
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
    )
    _ue_log(f"  SetWindowPos(FRAMECHANGED) returned {swp_result}")

    # Verify the owner was set correctly.
    current_owner = _user32.GetWindowLongPtrW(qt_hwnd, _GWLP_HWNDPARENT)
    _ue_log(f"  Current owner HWND = {hex(current_owner)}")

    if current_owner == owner_hwnd:
        _ue_log(f"Owner window set: Qt {hex(qt_hwnd)} owned by UE {hex(owner_hwnd)}")
        return True
    else:
        _ue_log_warning(
            f"Owner mismatch: expected {hex(owner_hwnd)}, got {hex(current_owner)}"
        )
        return False


# ============================================================================
# Step 5: Create the MCA Editor with UE as owner window
# ============================================================================

def _launch_editor(ue_hwnd=0):
    """
    Create the MCA Editor panel as a free-floating Qt window above UE.

    Uses Win32 owner-window relationship so the editor floats above UE
    only — not above every application on the desktop. Falls back to
    WindowStaysOnTopHint if no UE HWND is provided.

    :param int ue_hwnd: Native HWND of UE's main window (0 = fallback).
    :return: True if the editor was created successfully.
    :rtype: bool
    """
    global _mca_editor_window, _mca_app, _log_tailer, _last_qt_hwnd, _ue_owner_hwnd

    # If already open and visible, just raise it.
    if _mca_editor_window is not None:
        try:
            if _mca_editor_window.isVisible():
                _mca_editor_window.raise_()
                _mca_editor_window.activateWindow()
                _ue_log("Editor already open — raised to front")
                return True
            else:
                # Window exists but user closed it with X — clean up so we
                # can recreate fresh below.
                _ue_log("Editor was closed (not visible) — cleaning up for reopen")
                _close_editor()
        except RuntimeError:
            # C++ object deleted — recreate.
            _mca_editor_window = None

    _ue_log("=== Launching MCA Editor for UE ===")

    # --- Venv setup ---------------------------------------------------------
    _setup_venv()

    # --- QApplication -------------------------------------------------------
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    _mca_app = QApplication.instance()
    if _mca_app is None:
        _mca_app = QApplication(sys.argv)
        _ue_log("Created new QApplication")
    else:
        _ue_log("Reusing existing QApplication")

    # --- Create the editor panel --------------------------------------------
    _ue_log("Creating MCAEditorPanel...")
    from mca_core.config.settings import MCASettings
    from mca_qt.editor_panel import MCAEditorPanel

    # Pass dcc_version so QSettings is isolated from Maya's settings.
    # This gives UE its own window state, recent files, last project, etc.
    settings = MCASettings(dcc_version="UE5")

    # Create with dcc_version="UE5" for session isolation, no adapter
    # manager (execution goes through _execute_locally which uses exec()).
    from PySide6.QtWidgets import QVBoxLayout, QMenuBar, QWidget

    panel = MCAEditorPanel(
        settings=settings,
        adapter_manager=None,
        dcc_version="UE5",
    )
    _ue_log("MCAEditorPanel created successfully")

    # --- Wrap panel in a container with a VBoxLayout -------------------------
    # MCAEditorPanel's own layout is QHBoxLayout (stripe | splitter), so we
    # can't just append a status bar to it. Instead, create an outer QWidget
    # with a VBoxLayout: menu bar at top, panel in the middle, status bar at
    # the bottom. This outer widget becomes _mca_editor_window.
    _mca_editor_window = QWidget()
    _mca_editor_window.setWindowTitle("MCA Editor — Unreal Engine")
    outer_layout = QVBoxLayout(_mca_editor_window)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    # Menu bar at the top of the outer container.
    _menubar = QMenuBar(_mca_editor_window)
    outer_layout.setMenuBar(_menubar)
    panel.build_menus(_menubar)
    _ue_log("Menu bar created and populated")

    # Panel fills the middle.
    outer_layout.addWidget(panel, 1)

    # Status bar at the very bottom.
    _build_status_bar(panel, outer_layout)

    # Store a reference to the panel for accessing internal state.
    _mca_editor_window._panel = panel

    # Restore window geometry. Priority:
    #   1. In-memory cache (reopen within same UE session)
    #   2. QSettings (persisted from previous UE session)
    #   3. Default 1200x800
    if _window_geometry is not None:
        _mca_editor_window.restoreGeometry(_window_geometry)
        _ue_log("Restored window geometry from in-memory cache")
    else:
        _, saved_geometry = _load_persistent_state()
        if saved_geometry is not None:
            _mca_editor_window.restoreGeometry(saved_geometry)
            _ue_log("Restored window geometry from QSettings (previous UE session)")
        else:
            _mca_editor_window.resize(1200, 800)

    # Mark as embedded so the "No DCC" indicator and DCC menu are hidden.
    # In UE, execution goes through _execute_locally() — no adapter needed.
    panel._embedded_in_dcc = True
    panel._dcc_indicator.setVisible(False)

    # Remove all MEL/Maya-related UI elements and close MEL tabs.
    _strip_mel_from_ui(panel)

    # --- Start UE log tailer ------------------------------------------------
    # Pipe UE's Output Log into the MCA Editor output panel.
    # Pass start_position=0 — the tailer internally limits to the tail of
    # the file (last ~256KB) to avoid freezing UE on large logs.
    log_path = _find_ue_log_path()
    if log_path:
        _ue_log("Starting log tailer (recent history only)")
        _log_tailer = UELogTailer(
            _mca_editor_window._panel._output, log_path,
            start_position=0,
        )
    else:
        _ue_log_warning("Could not find UE log file — log tailing disabled")

    # --- Set up owner-window relationship with UE ----------------------------
    # Show the editor first so Qt creates the native HWND.
    _ue_log("Showing editor window (Qt will create native HWND)...")
    _mca_editor_window.show()

    # Grab the Qt window's native HWND and store UE's HWND for tick monitoring.
    _last_qt_hwnd = int(_mca_editor_window.winId())
    _ue_owner_hwnd = ue_hwnd
    _ue_log(f"Qt HWND = {hex(_last_qt_hwnd)}, UE HWND = {hex(ue_hwnd)}")

    # Log the Qt window's current Win32 style flags for debugging.
    qt_style = _user32.GetWindowLongPtrW(_last_qt_hwnd, -16)  # GWL_STYLE
    qt_ex_style = _user32.GetWindowLongPtrW(_last_qt_hwnd, -20)  # GWL_EXSTYLE
    _ue_log(f"Qt window style = {hex(qt_style)}, exStyle = {hex(qt_ex_style)}")
    _ue_log(f"  WS_POPUP = {bool(qt_style & 0x80000000)}")
    _ue_log(f"  WS_CHILD = {bool(qt_style & 0x40000000)}")
    _ue_log(f"  WS_EX_TOPMOST = {bool(qt_ex_style & 0x00000008)}")

    if ue_hwnd:
        # Validate UE's HWND is alive before attempting ownership.
        ue_valid = _user32.IsWindow(ue_hwnd)
        _ue_log(f"UE HWND IsWindow() = {bool(ue_valid)}")

        # Set UE's main window as the owner — editor floats above UE only,
        # not above every window on the desktop.
        success = _set_owner_window(_last_qt_hwnd, ue_hwnd)
        if success:
            _ue_log("Owner-window relationship established successfully")
        else:
            _ue_log_warning("Owner-window setup failed — editor may not stay above UE")
    else:
        # No HWND provided — fall back to global topmost as a last resort.
        _ue_log_warning("No UE HWND provided (ue_hwnd=0) — falling back to WindowStaysOnTopHint")
        _mca_editor_window.setWindowFlags(
            _mca_editor_window.windowFlags() | Qt.WindowStaysOnTopHint
        )
        # setWindowFlags hides the window, so show again.
        _mca_editor_window.show()

    # Mark the editor as open in persistent state so it auto-reopens
    # if UE is restarted. Geometry is saved on close, not here.
    _save_persistent_state(was_open=True)

    _ue_log("=== MCA Editor launched ===")
    return True


def _strip_mel_from_ui(panel):
    """
    Remove all MEL and Maya-specific items from the editor panel UI.

    Removes MEL from the language combo, hides Maya-specific menu actions
    (shelf, source, Maya help links), and closes any open MEL tabs.
    UE only supports Python — no MEL, no Maya shelf, no Maya docs.

    :param MCAEditorPanel panel: The editor panel instance.
    """
    # --- Remove MEL from the language combo ---------------------------------
    try:
        combo = panel._lang_combo
        for i in range(combo.count() - 1, -1, -1):
            if combo.itemText(i) == "MEL":
                combo.removeItem(i)
                _ue_log("Removed 'MEL' from language combo")
    except AttributeError:
        pass

    # --- Hide MEL and Maya-specific menu actions ----------------------------
    # Two approaches needed because some actions have explicit registry names
    # and some don't (help menu items use display text only).

    # Actions registered by name in _action_registry.
    _MAYA_REGISTRY_ACTIONS = (
        "New MEL Buffer",         # MEL language not available in UE.
        "Save Script to Shelf",   # Maya shelf system doesn't exist in UE.
        "Source Script",          # MEL source command.
    )
    try:
        for name in _MAYA_REGISTRY_ACTIONS:
            if name in panel._action_registry:
                action = panel._action_registry[name]
                action.setVisible(False)
                _ue_log(f"Hidden registry action: '{name}'")
    except AttributeError:
        pass

    # Actions NOT in the registry — find them by walking all menu actions
    # and matching on display text. These are help menu links to Maya docs.
    _MAYA_ACTION_TEXTS = (
        "MEL Command Reference",         # Autodesk Maya MEL docs.
        "Python Command Reference",      # Autodesk Maya Python docs.
        "Node and Attribute Reference",   # Autodesk Maya node docs.
    )
    try:
        # Walk all actions on the panel (they're parented to it).
        for action in panel.actions():
            if action.text() in _MAYA_ACTION_TEXTS:
                action.setVisible(False)
                _ue_log(f"Hidden action by text: '{action.text()}'")
    except (AttributeError, RuntimeError):
        pass

    # --- Add UE-specific help links -----------------------------------------
    # Replace the hidden Maya docs with relevant UE documentation links.
    try:
        import webbrowser
        from PySide6.QtWidgets import QMenuBar

        # Find the Help menu from the menu bar.
        help_menu = None
        menubar = panel.layout().menuBar()
        if menubar is not None:
            for action in menubar.actions():
                if action.text().replace("&", "") == "Help":
                    help_menu = action.menu()
                    break

        if help_menu is not None:
            # Insert UE doc links before the first visible action (separator).
            first_action = help_menu.actions()[0] if help_menu.actions() else None

            # UE Python API reference.
            ue_python_action = help_menu.addAction("UE Python API Reference")
            ue_python_action.triggered.connect(
                lambda: webbrowser.open("https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/")
            )

            # UE Blueprint visual scripting reference.
            ue_bp_action = help_menu.addAction("UE Blueprint Visual Scripting")
            ue_bp_action.triggered.connect(
                lambda: webbrowser.open("https://dev.epicgames.com/documentation/en-us/unreal-engine/blueprints-visual-scripting-in-unreal-engine/")
            )

            # UE scripting documentation.
            ue_scripting_action = help_menu.addAction("UE Scripting with Python")
            ue_scripting_action.triggered.connect(
                lambda: webbrowser.open("https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-the-unreal-editor-using-python/")
            )

            # UE Editor Scripting Utilities.
            ue_editor_utils_action = help_menu.addAction("UE Editor Scripting Utilities")
            ue_editor_utils_action.triggered.connect(
                lambda: webbrowser.open("https://dev.epicgames.com/documentation/en-us/unreal-engine/editor-scripting-utilities-in-unreal-engine/")
            )

            # Move UE links to the top of the menu (before the Maya ones / separator).
            if first_action is not None:
                help_menu.insertAction(first_action, ue_python_action)
                help_menu.insertAction(first_action, ue_bp_action)
                help_menu.insertAction(first_action, ue_scripting_action)
                help_menu.insertAction(first_action, ue_editor_utils_action)

            _ue_log("Added UE documentation links to Help menu")
        else:
            _ue_log_warning("Could not find Help menu to add UE docs")
    except Exception as exc:
        _ue_log_warning(f"Could not add UE help links: {exc}")

    # --- Close any open MEL tabs --------------------------------------------
    # Walk all editor groups and remove tabs whose editor language is "mel".
    # _editors is a list of (editor, tab_name, file_path) tuples.
    try:
        container = panel._group_container
        for group in container.groups():
            mel_indices = []
            for i, (editor, tab_name, file_path) in enumerate(group.editors()):
                if getattr(editor, 'language', '') == 'mel':
                    mel_indices.append(i)
            # Remove from end to start to avoid index shifting.
            for i in reversed(mel_indices):
                group.remove_editor(i)
                _ue_log(f"Closed MEL tab at index {i}")
    except (AttributeError, Exception) as exc:
        _ue_log_warning(f"Could not close MEL tabs: {exc}")

    # --- Override the New Tab dialog to exclude MEL -------------------------
    # The default dialog shows Python/MEL/Text. Replace the callback with
    # one that only offers Python and Text.
    try:
        from mca_qt.widgets.new_tab_dialog import NewTabDialog
        from PySide6.QtWidgets import QDialog

        _UE_LANGUAGES = [("Python", "python"), ("Text", "text")]

        def _ue_new_tab_dialog(self_ref=panel):
            """Show the New Tab dialog without MEL option."""
            dialog = NewTabDialog(self_ref, languages=_UE_LANGUAGES)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                language = dialog.get_language()
                if language == "python":
                    self_ref._new_python_buffer()
                elif language == "text":
                    self_ref._new_text_buffer()

        # Monkey-patch the panel's method.
        import types
        panel._show_new_tab_dialog = types.MethodType(lambda self: _ue_new_tab_dialog(), panel)
        _ue_log("Replaced New Tab dialog (no MEL option)")
    except Exception as exc:
        _ue_log_warning(f"Could not override New Tab dialog: {exc}")


def _build_status_bar(panel, outer_layout):
    """
    Add a blue status bar at the bottom of the outer window layout.

    Creates a QFrame with labels for Python version, error/warning counts,
    indexing progress, cursor position, language, encoding, and project name.
    Appended to the outer VBoxLayout so it spans the full window width.

    :param MCAEditorPanel panel: The editor panel (for signal connections).
    :param QVBoxLayout outer_layout: The outer window's vertical layout.
    """
    import struct
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

    bar = QFrame()
    bar.setFixedHeight(24)
    bar.setStyleSheet("QFrame { background-color: #007acc; }")

    bar_layout = QHBoxLayout(bar)
    bar_layout.setContentsMargins(8, 0, 8, 0)
    bar_layout.setSpacing(0)

    # Shared label style — white text on the blue bar.
    label_style = "color: white; padding: 0 8px; font-size: 11px;"

    # Python version (static) — left-aligned.
    bits = struct.calcsize("P") * 8
    py_ver = "Python {}.{}.{} ({}-bit)".format(*sys.version_info[:3], bits)
    py_label = QLabel(py_ver)
    py_label.setStyleSheet(label_style)
    bar_layout.addWidget(py_label)

    # Error count indicator — left-aligned.
    error_label = QLabel("\u2297 0")
    error_label.setStyleSheet(label_style)
    bar_layout.addWidget(error_label)

    # Warning count indicator — left-aligned.
    warning_label = QLabel("\u26a0 0")
    warning_label.setStyleSheet(label_style)
    bar_layout.addWidget(warning_label)

    # Symbol index status indicator — shows indexing progress or final count.
    index_label = QLabel("")
    index_label.setStyleSheet(label_style)
    bar_layout.addWidget(index_label)

    # Status message area (stretches to fill remaining space).
    status_msg_label = QLabel("")
    status_msg_label.setStyleSheet(label_style)
    bar_layout.addWidget(status_msg_label, 1)

    # Cursor position — right-aligned.
    pos_label = QLabel("Ln 1, Col 1")
    pos_label.setStyleSheet(label_style)
    bar_layout.addWidget(pos_label)

    # Current language.
    lang_label = QLabel("Python")
    lang_label.setStyleSheet(label_style)
    bar_layout.addWidget(lang_label)

    # Encoding (always UTF-8).
    encoding_label = QLabel("UTF-8")
    encoding_label.setStyleSheet(label_style)
    bar_layout.addWidget(encoding_label)

    # Project indicator.
    mode_label = QLabel("No Project")
    mode_label.setStyleSheet(label_style)
    bar_layout.addWidget(mode_label)

    # Add the status bar to the outer window layout (below the panel).
    outer_layout.addWidget(bar)

    # --- Connect panel signals to update the status bar labels ---
    panel.cursor_position_changed.connect(
        lambda line, col: pos_label.setText("Ln {}, Col {}".format(line, col))
    )
    panel.language_changed.connect(
        lambda lang: lang_label.setText(lang)
    )
    panel.mode_changed.connect(
        lambda mode: mode_label.setText(mode if mode else "No Project")
    )
    def _update_counts(errs, warns):
        error_label.setText("\u2297 {}".format(errs))
        warning_label.setText("\u26a0 {}".format(warns))
    panel.output_counts_changed.connect(_update_counts)
    panel.index_status_changed.connect(
        lambda text: index_label.setText(text)
    )

    # Wire the status callback for transient messages.
    def _status_callback(message, duration_ms=3000):
        status_msg_label.setText(message)
        if duration_ms > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(duration_ms, lambda: status_msg_label.setText(""))
    panel.set_status_callback(_status_callback)

    _ue_log("Status bar created")


def _close_editor(shutting_down=False):
    """
    Close the MCA Editor window cleanly.

    Called by the C++ plugin on shutdown (shutting_down=True), or by
    _pump_qt() when the user closes via the X button (shutting_down=False).

    Saves window geometry to both in-memory cache and QSettings. The
    ``was_open`` persistent flag is set based on context:
      - User X-close: was_open=False (user chose to close)
      - UE shutdown: was_open=True (auto-reopen next session)

    :param bool shutting_down: True if UE is shutting down.
    """
    global _mca_editor_window, _log_tailer, _last_qt_hwnd, _ue_owner_hwnd, _window_geometry

    # Close the log tailer. We intentionally do NOT save the tailer position
    # because the output panel is destroyed with the window — on reopen we
    # need to reload the FULL log from the beginning (position 0).
    if _log_tailer is not None:
        _ue_log("Closing log tailer (will reload full log on reopen)")
        _log_tailer.close()
        _log_tailer = None

    if _mca_editor_window is not None:
        try:
            # Save the panel's session state BEFORE closing the window.
            # This persists open tabs, buffer contents, tree expanded state,
            # splitter sizes, and output panel content so the editor can
            # restore them on next launch.
            panel = getattr(_mca_editor_window, "_panel", None)
            if panel is not None:
                from mca_core.config.settings import MCASettings
                settings = MCASettings(dcc_version="UE5")
                panel.save_window_state(settings)
                panel.cleanup()
                _ue_log("Saved session state (tabs, tree, splitters)")

                # cleanup() saves output panel text to output.log. In UE, the
                # log tailer reloads the FULL UE log on every launch, so we
                # don't want the saved output restored too (would duplicate).
                # Delete the output.log so _restore_output() finds nothing.
                import os
                output_log = os.path.join(
                    panel._session_manager._session_dir, "output.log"
                )
                if os.path.exists(output_log):
                    try:
                        os.remove(output_log)
                    except OSError:
                        pass

            # Save the window geometry so reopen restores size and position.
            _window_geometry = _mca_editor_window.saveGeometry()
            _ue_log("Saved window geometry for reopen")

            # Persist state to QSettings for cross-restart survival.
            # If UE is shutting down, the editor was open → auto-reopen next time.
            # If user closed with X, they chose to close → don't auto-reopen.
            _save_persistent_state(
                was_open=shutting_down,
                geometry=_window_geometry,
            )

            _mca_editor_window.close()
            _ue_log("MCA Editor closed")
        except RuntimeError:
            pass
        _mca_editor_window = None

    # Reset HWND tracking state.
    _last_qt_hwnd = 0
    _ue_owner_hwnd = 0


def _pump_qt():
    """
    Process pending Qt events and poll the UE log tailer.

    Called periodically by the C++ tick function to keep the Qt event loop
    alive while UE owns the main loop. Also reads new UE log lines and
    pipes them to the MCA Editor output panel.

    After processing events, checks whether Qt recreated the native HWND
    (this happens once after the first show). If so, re-applies the
    owner-window relationship with UE.
    """
    global _last_qt_hwnd

    # Detect if the user closed the editor via the X button while we were
    # ticking. Save the log position so reopen picks up where we left off.
    # Only check after the window has been shown at least once (_last_qt_hwnd != 0)
    # to avoid a false positive on the first tick before show() completes.
    if _mca_editor_window is not None and _last_qt_hwnd:
        try:
            if not _mca_editor_window.isVisible():
                _ue_log("Editor closed by user (X button) — saving state")
                _close_editor()
                return
        except RuntimeError:
            # C++ object already deleted.
            _close_editor()
            return

    # Poll the UE log tailer for new log lines.
    if _log_tailer is not None:
        _log_tailer.poll()

    # Process Qt events so the editor stays responsive.
    if _mca_app is not None:
        _mca_app.processEvents()

    # Check if Qt recreated the HWND (happens once after first show).
    # If so, the owner-window relationship was lost — re-apply it.
    if _mca_editor_window is not None and _ue_owner_hwnd:
        try:
            current_hwnd = int(_mca_editor_window.winId())
            if current_hwnd != _last_qt_hwnd:
                _ue_log(
                    f"HWND changed: {hex(_last_qt_hwnd)} -> {hex(current_hwnd)} "
                    f"— re-applying owner window"
                )
                _last_qt_hwnd = current_hwnd
                _set_owner_window(current_hwnd, _ue_owner_hwnd)
        except RuntimeError:
            # C++ object deleted — window is gone.
            pass


# ============================================================================
# Entry point — called by C++ via "py ue_editor_host.launch()"
# ============================================================================

def launch(ue_hwnd=0):
    """
    Public entry point for the C++ plugin.

    Creates the editor if it doesn't exist, or raises it if already open.
    The C++ side passes UE's main window HWND for proper z-ordering.

    :param int ue_hwnd: Native HWND of UE's main window (0 = fallback).
    """
    try:
        return _launch_editor(ue_hwnd=ue_hwnd)
    except Exception as exc:
        import traceback
        _ue_log_error(f"launch() failed: {exc}")
        _ue_log_error(traceback.format_exc())
        return False


def close():
    """Public entry point to close the editor (C++ shutdown)."""
    _close_editor(shutting_down=True)


def auto_launch(ue_hwnd=0):
    """
    Auto-open the editor if it was open when UE last closed.

    Called by C++ during startup (after a short delay to ensure Slate is
    ready). Checks the ``was_open`` flag in QSettings — if True, launches
    the editor automatically so the user doesn't have to click the button.

    :param int ue_hwnd: Native HWND of UE's main window (0 = fallback).
    """
    try:
        _setup_venv()
        was_open, _ = _load_persistent_state()
        if was_open:
            _ue_log("Auto-launching editor (was open in previous UE session)")
            return _launch_editor(ue_hwnd=ue_hwnd)
        else:
            _ue_log("Auto-launch skipped (editor was not open in previous session)")
            return False
    except Exception as exc:
        import traceback
        _ue_log_error(f"auto_launch() failed: {exc}")
        _ue_log_error(traceback.format_exc())
        return False


def tick():
    """Public entry point for the C++ tick — pumps Qt events."""
    _pump_qt()


# If this script is executed directly (e.g. via "py ue_editor_host"),
# launch the editor immediately.
if __name__ == "__main__":
    launch()
