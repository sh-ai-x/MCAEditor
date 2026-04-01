"""
MCA Editor — Blender Window Host.

Launches the PySide6 MCA Editor as a free-floating Qt window that floats
above Blender's main window via Win32 owner-window relationship. Same editor
as Maya and UE — same codebase, same features, same theme — but configured
for Blender:

    - No MEL language option (Python + Text only)
    - Stdout/stderr tees route print() output to MCA Editor output panel
    - Separate session workspace (blender_scripts/)
    - dcc_version="Blender" for session isolation

The Qt event loop is pumped via ``bpy.app.timers.register()`` at ~120Hz.
This runs on Blender's main thread during idle time without blocking
Blender's input processing.

Win32 owner-window relationship:
    SetWindowLongPtrW(qt_hwnd, GWLP_HWNDPARENT, blender_hwnd)
    Makes the editor float above Blender only (not above other apps),
    minimize/restore together with Blender.

Dependencies:
    - bpy (Blender Python API)
    - PySide6 (installed via managed venv)
    - mca_core, mca_qt packages (from MCA Editor source)
"""

import sys
import os
import logging
import platform

# Module-level logger for Blender host operations.
logger = logging.getLogger("mca_editor.blender_host")


# --- Blender logging helper -------------------------------------------------
# Route important messages through Blender's logging so they appear
# in Blender's system console.

def _bl_log(msg):
    """Log an info-level message to both Python logger and print."""
    logger.info(msg)
    print("[MCAEditor] {}".format(msg))

def _bl_log_warning(msg):
    """Log a warning to both Python logger and print."""
    logger.warning(msg)
    print("[MCAEditor] WARNING: {}".format(msg))

def _bl_log_error(msg):
    """Log an error to both Python logger and print."""
    logger.error(msg)
    print("[MCAEditor] ERROR: {}".format(msg))


# --- Win32 Owner-Window Setup (Windows only) --------------------------------

# GWLP_HWNDPARENT (-8) sets the OWNER of a WS_POPUP window.
_GWLP_HWNDPARENT = -8

# SetWindowPos flags — apply style changes without moving/resizing.
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020

# ctypes setup is deferred until actually needed (import guard for non-Windows).
_user32 = None


def _init_win32():
    """
    Initialize ctypes user32 function signatures for Win32 API calls.

    Only runs on Windows — no-op on other platforms.
    """
    global _user32

    if platform.system() != "Windows" or _user32 is not None:
        return

    import ctypes
    import ctypes.wintypes

    _user32 = ctypes.windll.user32

    # SetWindowLongPtrW: sets window attributes. On x64, LONG_PTR is 8 bytes.
    _user32.SetWindowLongPtrW.argtypes = [
        ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_longlong
    ]
    _user32.SetWindowLongPtrW.restype = ctypes.c_longlong

    # GetWindowLongPtrW: retrieves window attributes.
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

    # EnumWindows + GetWindowThreadProcessId for HWND discovery.
    _user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    ), ctypes.wintypes.LPARAM]
    _user32.EnumWindows.restype = ctypes.wintypes.BOOL

    _user32.GetWindowThreadProcessId.argtypes = [
        ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)
    ]
    _user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

    _user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
    _user32.IsWindowVisible.restype = ctypes.wintypes.BOOL

    _user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int

    _user32.GetWindowTextW.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int
    ]
    _user32.GetWindowTextW.restype = ctypes.c_int


# --- Module-level state (survives across Blender script re-runs) ------------

_mca_editor_window = None     # The outer QWidget holding MCAEditorPanel.
_mca_app = None               # QApplication instance.
_blender_hwnd = 0             # Blender's main window HWND (Win32 only).
_last_qt_hwnd = 0             # Last known HWND of the Qt editor window.
_window_geometry = None        # In-memory geometry cache for within-session reopen.
_qt_timer_registered = False   # Whether the bpy.app.timers callback is active.
_original_stdout = None        # Original sys.stdout before tee installation.
_original_stderr = None        # Original sys.stderr before tee installation.

# QSettings key names for cross-restart persistence.
_QSETTINGS_ORG = "MCAEditor"
_QSETTINGS_APP = "BlenderPlugin"
_KEY_WAS_OPEN = "blender_editor/was_open"
_KEY_GEOMETRY = "blender_editor/geometry"


# --- Persistent state helpers (QSettings — survives Blender restarts) -------

def _save_persistent_state(was_open, geometry=None):
    """
    Save editor state to QSettings so it persists across Blender restarts.

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
        _bl_log("Saved persistent state: was_open={}, geometry={}".format(
            was_open, "yes" if geometry else "no"
        ))
    except Exception as exc:
        _bl_log_warning("Could not save persistent state: {}".format(exc))


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
        _bl_log("Loaded persistent state: was_open={}, geometry={}".format(
            was_open, "yes" if geometry else "no"
        ))
        return was_open, geometry
    except Exception as exc:
        _bl_log_warning("Could not load persistent state: {}".format(exc))
        return False, None


# ============================================================================
# Step 1: Locate MCA Editor source packages
# ============================================================================

# Resolution order:
# 1. Bundled packages alongside this file (addon zip distribution).
# 2. MCA_EDITOR_SOURCE environment variable — for custom installs or CI.
# 3. Hardcoded dev path — for development from the repo checkout.

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLED_DIR = _SCRIPT_DIR
_DEV_DIR = os.environ.get("MCA_EDITOR_SOURCE", r"E:\Projects\MCAEditor")

# Prefer bundled packages (distribution), fall back to dev checkout.
if os.path.isdir(os.path.join(_BUNDLED_DIR, "mca_core")):
    _MCA_SOURCE_DIR = _BUNDLED_DIR
elif os.path.isdir(_DEV_DIR):
    _MCA_SOURCE_DIR = _DEV_DIR
else:
    _MCA_SOURCE_DIR = None
    _bl_log_error("Cannot find MCA Editor packages (checked bundled + dev paths)")

if _MCA_SOURCE_DIR and _MCA_SOURCE_DIR not in sys.path:
    sys.path.insert(0, _MCA_SOURCE_DIR)
    logger.info("Added MCA source to path: %s", _MCA_SOURCE_DIR)


# ============================================================================
# Step 2: Set up managed venv for PySide6
# ============================================================================

def _setup_venv():
    """
    Ensure PySide6 and other deps are available via the managed venv.

    Blender's Python doesn't include PySide6 — we install it into a
    versioned venv at ~/Documents/mca_preferences/.venv-X.Y/.
    """
    try:
        from mca_core.venv_manager import setup_venv, REQUIRED_PACKAGES

        # Add PySide6 to the requirements since Blender doesn't ship it.
        blender_requirements = dict(REQUIRED_PACKAGES)
        blender_requirements["PySide6>=6.5.0"] = "PySide6"

        setup_venv(requirements=blender_requirements)
        _bl_log("Venv setup complete — PySide6 available")
    except Exception as exc:
        _bl_log_warning("Venv setup failed: {} — checking if PySide6 is importable".format(exc))
        try:
            import PySide6
            _bl_log("PySide6 already importable: {}".format(PySide6.__file__))
        except ImportError:
            _bl_log_error("PySide6 not available and venv setup failed — cannot launch editor")
            raise


# ============================================================================
# Step 3: Stdout/Stderr Tee Writers
# ============================================================================

class _BlenderStdoutTee:
    """
    Transparent stdout wrapper that copies print() output to the output panel.

    Blender has no MCommandMessage equivalent — stdout tees are the sole
    mechanism for routing print() output from user scripts to the editor's
    output panel.

    :param original: The original sys.stdout being wrapped.
    :param OutputWindow output_widget: The MCA Editor output panel widget.
    """

    def __init__(self, original, output_widget):
        self._original = original
        self._output = output_widget

    def write(self, text):
        """
        Write to both the original stdout and the output panel.

        :param str text: The text to write.
        """
        # Always write to the original stdout first (Blender's console).
        if self._original:
            self._original.write(text)

        # Route non-empty text to the MCA Editor output panel.
        if text.strip() and self._output:
            try:
                # Check for the "# Result: ... #" format for special coloring.
                stripped = text.strip()
                if stripped.startswith("# Result:") and stripped.endswith("#"):
                    self._output.write_result(stripped)
                else:
                    self._output.write_output(stripped)
            except (RuntimeError, AttributeError):
                # Widget may have been deleted — ignore silently.
                pass

    def flush(self):
        """Flush the original stdout."""
        if self._original:
            self._original.flush()

    def __getattr__(self, name):
        """Proxy all other attributes to the original stdout."""
        return getattr(self._original, name)


class _BlenderStderrTee:
    """
    Transparent stderr wrapper that copies error output to the output panel.

    Routes error/warning text to the output panel with error coloring.

    :param original: The original sys.stderr being wrapped.
    :param OutputWindow output_widget: The MCA Editor output panel widget.
    """

    def __init__(self, original, output_widget):
        self._original = original
        self._output = output_widget

    def write(self, text):
        """
        Write to both the original stderr and the output panel as an error.

        :param str text: The text to write.
        """
        # Always write to the original stderr first (Blender's console).
        if self._original:
            self._original.write(text)

        # Route non-empty text to the output panel as error.
        if text.strip() and self._output:
            try:
                self._output.write_error(text.strip())
            except (RuntimeError, AttributeError):
                pass

    def flush(self):
        """Flush the original stderr."""
        if self._original:
            self._original.flush()

    def __getattr__(self, name):
        """Proxy all other attributes to the original stderr."""
        return getattr(self._original, name)


# ============================================================================
# Step 4: Win32 Owner-Window Helpers
# ============================================================================

def _find_blender_hwnd():
    """
    Find Blender's main window HWND by enumerating visible windows.

    Searches for windows belonging to the current process (os.getpid())
    that have "Blender" in the title. Returns the first match.

    :return: HWND of Blender's main window, or 0 if not found.
    :rtype: int
    """
    if platform.system() != "Windows":
        return 0

    import ctypes
    import ctypes.wintypes

    _init_win32()

    blender_pid = os.getpid()
    found_hwnd = [0]

    # Callback for EnumWindows — checks each window against our PID.
    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _enum_callback(hwnd, lparam):
        # Only check visible windows.
        if not _user32.IsWindowVisible(hwnd):
            return True  # Continue enumeration.

        # Check if window belongs to our process.
        pid = ctypes.wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != blender_pid:
            return True

        # Skip our own Qt window — its title contains "Blender" too.
        if _last_qt_hwnd and hwnd == _last_qt_hwnd:
            return True

        # Check if window title contains "Blender" but NOT "MCA Editor".
        # Blender's main window title is like "Blender 4.5.3 - filename.blend".
        title_len = _user32.GetWindowTextLengthW(hwnd)
        if title_len > 0:
            title_buf = ctypes.create_unicode_buffer(title_len + 1)
            _user32.GetWindowTextW(hwnd, title_buf, title_len + 1)
            title = title_buf.value
            if ("Blender" in title or "blender" in title) and "MCA Editor" not in title:
                found_hwnd[0] = hwnd
                return False  # Stop enumeration — found it.

        return True  # Continue enumeration.

    _user32.EnumWindows(_enum_callback, 0)

    if found_hwnd[0]:
        _bl_log("Found Blender HWND: {}".format(hex(found_hwnd[0])))
    else:
        _bl_log_warning("Could not find Blender's main window HWND")

    return found_hwnd[0]


def _set_owner_window(qt_hwnd, owner_hwnd):
    """
    Set the Win32 owner-window relationship so the Qt window floats above
    Blender's main window — but NOT above other applications.

    :param int qt_hwnd: The native HWND of the Qt editor window.
    :param int owner_hwnd: The native HWND of Blender's main window.
    :return: True if ownership was established successfully.
    :rtype: bool
    """
    if _user32 is None:
        return False

    # Validate both HWNDs are still live windows.
    if not _user32.IsWindow(qt_hwnd):
        _bl_log_warning("_set_owner_window: Qt HWND {} is not a valid window".format(hex(qt_hwnd)))
        return False
    if not _user32.IsWindow(owner_hwnd):
        _bl_log_warning("_set_owner_window: Owner HWND {} is not a valid window".format(hex(owner_hwnd)))
        return False

    # Set the owner via GWLP_HWNDPARENT.
    _user32.SetWindowLongPtrW(qt_hwnd, _GWLP_HWNDPARENT, owner_hwnd)

    # Apply the change with FRAMECHANGED so Windows re-evaluates z-order.
    _user32.SetWindowPos(
        qt_hwnd, 0,
        0, 0, 0, 0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED,
    )

    # Verify the owner was set correctly.
    current_owner = _user32.GetWindowLongPtrW(qt_hwnd, _GWLP_HWNDPARENT)
    if current_owner == owner_hwnd:
        _bl_log("Owner window set: Qt {} owned by Blender {}".format(
            hex(qt_hwnd), hex(owner_hwnd)
        ))
        return True
    else:
        _bl_log_warning("Owner mismatch: expected {}, got {}".format(
            hex(owner_hwnd), hex(current_owner)
        ))
        return False


# ============================================================================
# Step 5: Create the MCA Editor with Blender as owner window
# ============================================================================

def _launch_editor(show_license_dialog=True):
    """
    Create the MCA Editor panel as a free-floating Qt window above Blender.

    Uses Win32 owner-window relationship so the editor floats above Blender
    only — not above every application on the desktop. Falls back to
    WindowStaysOnTopHint if no Blender HWND can be found.

    :param bool show_license_dialog: If True, show the licensing dialog
        when the license is expired. Set to False for auto_launch so that
        an expired license silently skips instead of popping up a dialog
        during Blender startup.
    :return: True if the editor was created successfully.
    :rtype: bool
    """
    global _mca_editor_window, _mca_app, _last_qt_hwnd, _blender_hwnd
    global _original_stdout, _original_stderr, _qt_timer_registered

    # If already open and visible, just raise it.
    if _mca_editor_window is not None:
        try:
            if _mca_editor_window.isVisible():
                _mca_editor_window.raise_()
                _mca_editor_window.activateWindow()
                _bl_log("Editor already open — raised to front")
                return True
            else:
                # Window exists but user closed it with X — clean up for reopen.
                _bl_log("Editor was closed (not visible) — cleaning up for reopen")
                _close_editor_internal()
        except RuntimeError:
            # C++ object deleted — recreate.
            _mca_editor_window = None

    _bl_log("=== Launching MCA Editor for Blender ===")

    # --- Venv setup ---------------------------------------------------------
    _setup_venv()

    # --- QApplication -------------------------------------------------------
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    _mca_app = QApplication.instance()
    if _mca_app is None:
        _mca_app = QApplication(sys.argv)
        _bl_log("Created new QApplication")
    else:
        _bl_log("Reusing existing QApplication")

    # --- Create the editor panel --------------------------------------------
    _bl_log("Creating MCAEditorPanel...")
    from mca_core.config.settings import MCASettings
    from mca_qt.editor_panel import MCAEditorPanel
    from mca_core.adapters.adapter_manager import AdapterManager
    from mca_core.adapters.internal_blender_adapter import InternalBlenderAdapter

    # Pass dcc_version so QSettings is isolated from Maya's / UE's settings.
    settings = MCASettings(dcc_version="Blender")

    # --- License gate -------------------------------------------------------
    _license_message = ""
    _has_activation = False

    try:
        from mca_core.activation import (
            validate_on_launch,
            get_trial_status as activation_trial_status,
        )
        _has_activation = True
    except ImportError:
        _bl_log("activation module not available — using offline license check")

    if _has_activation:
        # Server-based activation path.
        from mca_core import __version__ as _plugin_version
        _bl_log("Running activation check (product=blender)...")
        result = validate_on_launch(_plugin_version, product="blender")

        if result.success:
            _bl_log("License valid: {} (status={})".format(result.message, result.status))
        else:
            trial = activation_trial_status(product="blender")
            if trial["active"]:
                _license_message = "Trial ({} days remaining)".format(trial["days_remaining"])
                _bl_log("Trial mode: {}".format(_license_message))
            else:
                if not show_license_dialog:
                    _bl_log("License expired — skipping auto-launch (no dialog)")
                    return False
                from mca_qt.widgets.licensing_dialog import LicensingDialog
                _bl_log("Trial expired — showing licensing dialog")
                dlg = LicensingDialog(
                    parent=None, modal=True,
                    reason=result.status, message=result.message,
                    settings=settings,
                )
                dlg.exec()
                from mca_core.license import check_license
                license_status = check_license(settings)
                if license_status["needs_key"]:
                    _bl_log_warning("No valid license after dialog — aborting")
                    return False
                _bl_log("License activated via dialog")
    else:
        # Offline-only fallback.
        from mca_core.license import check_license
        license_status = check_license(settings)

        if license_status["needs_key"]:
            if not show_license_dialog:
                _bl_log("License expired — skipping auto-launch (no dialog)")
                return False
            from mca_qt.widgets.licensing_dialog import LicensingDialog
            _bl_log("Trial expired — showing licensing dialog")
            dlg = LicensingDialog(
                parent=None, modal=True,
                reason="not_activated",
                message=license_status["message"],
                settings=settings,
            )
            dlg.exec()
            license_status = check_license(settings)
            if license_status["needs_key"]:
                _bl_log_warning("No valid license after dialog — aborting")
                return False

        if license_status["trial"]:
            _license_message = license_status["message"]
            _bl_log("Trial mode: {}".format(_license_message))
        elif license_status["licensed"]:
            _bl_log("License valid: {}".format(license_status["message"]))

    # --- Create adapter manager with internal Blender adapter ---------------
    adapter_manager = AdapterManager(register_builtin=False)
    internal_adapter = InternalBlenderAdapter()
    adapter_manager.register_adapter_instance("blender_internal", internal_adapter)
    _bl_log("Internal Blender adapter registered")

    # Create with dcc_version="Blender" for session isolation.
    from PySide6.QtWidgets import QVBoxLayout, QMenuBar, QWidget

    panel = MCAEditorPanel(
        settings=settings,
        adapter_manager=adapter_manager,
        dcc_version="Blender",
    )
    _bl_log("MCAEditorPanel created successfully")

    # --- Wrap panel in a container with a VBoxLayout -------------------------
    _mca_editor_window = QWidget()
    _mca_editor_window.setWindowTitle("MCA Editor — Blender")
    outer_layout = QVBoxLayout(_mca_editor_window)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    # Menu bar at the top.
    _menubar = QMenuBar(_mca_editor_window)
    outer_layout.setMenuBar(_menubar)
    panel.build_menus(_menubar)
    _bl_log("Menu bar created and populated")

    # Panel fills the middle.
    outer_layout.addWidget(panel, 1)

    # Status bar at the bottom.
    _build_status_bar(panel, outer_layout)

    # Store references for state management.
    _mca_editor_window._panel = panel

    # Restore window geometry from in-memory cache or QSettings.
    if _window_geometry is not None:
        _mca_editor_window.restoreGeometry(_window_geometry)
        _bl_log("Restored window geometry from in-memory cache")
    else:
        _, saved_geometry = _load_persistent_state()
        if saved_geometry is not None:
            _mca_editor_window.restoreGeometry(saved_geometry)
            _bl_log("Restored window geometry from QSettings")
        else:
            _mca_editor_window.resize(1200, 800)

    # Mark as embedded so the "No DCC" indicator is hidden.
    panel._embedded_in_dcc = True
    panel._dcc_indicator.setVisible(False)

    # Remove MEL-related UI elements and add Blender doc links.
    _strip_mel_from_ui(panel, _menubar)

    # --- Show license/trial notice on the status bar -------------------------
    if _license_message:
        from PySide6.QtCore import QTimer
        _msg = _license_message
        QTimer.singleShot(500, lambda: panel._show_status(_msg, 10000))

    # --- Install stdout/stderr tees -----------------------------------------
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr
    sys.stdout = _BlenderStdoutTee(_original_stdout, panel._output)
    sys.stderr = _BlenderStderrTee(_original_stderr, panel._output)
    _bl_log("Stdout/stderr tees installed")

    # --- Set up owner-window relationship with Blender ----------------------
    _bl_log("Showing editor window...")
    _mca_editor_window.show()

    # Grab the Qt window's native HWND.
    _last_qt_hwnd = int(_mca_editor_window.winId())
    _bl_log("Qt HWND = {}".format(hex(_last_qt_hwnd)))

    # Find Blender's main window HWND and establish ownership.
    if platform.system() == "Windows":
        _init_win32()
        _blender_hwnd = _find_blender_hwnd()
        if _blender_hwnd:
            success = _set_owner_window(_last_qt_hwnd, _blender_hwnd)
            if success:
                _bl_log("Owner-window relationship established")
            else:
                _bl_log_warning("Owner-window setup failed — editor may not stay above Blender")
        else:
            _bl_log_warning("No Blender HWND — falling back to WindowStaysOnTopHint")
            _mca_editor_window.setWindowFlags(
                _mca_editor_window.windowFlags() | Qt.WindowStaysOnTopHint
            )
            _mca_editor_window.show()

    # Mark the editor as open for auto-reopen on next Blender startup.
    _save_persistent_state(was_open=True)

    # --- Start the Qt event pump timer --------------------------------------
    _start_qt_timer()

    # --- Deploy and register the Blender MCP server -------------------------
    try:
        from mca_core import mcp_setup
        if hasattr(mcp_setup, "ensure_blender_mcp"):
            mcp_setup.ensure_blender_mcp(background=True)
            _bl_log("Blender MCP setup triggered (background)")
    except Exception as exc:
        _bl_log_warning("Blender MCP setup failed: {}".format(exc))

    _bl_log("=== MCA Editor launched ===")
    return True


def _strip_mel_from_ui(panel, menubar):
    """
    Remove all MEL and Maya-specific items from the editor panel UI.

    Removes MEL from the language combo, hides Maya-specific menu actions,
    closes any open MEL tabs, and adds Blender doc links to the Help menu.

    :param MCAEditorPanel panel: The editor panel instance.
    :param QMenuBar menubar: The outer window's menu bar.
    """
    # --- Remove MEL from the language combo ---------------------------------
    try:
        combo = panel._lang_combo
        for i in range(combo.count() - 1, -1, -1):
            if combo.itemText(i) == "MEL":
                combo.removeItem(i)
                _bl_log("Removed 'MEL' from language combo")
    except AttributeError:
        pass

    # --- Hide MEL and Maya-specific menu actions ----------------------------
    _MAYA_REGISTRY_ACTIONS = (
        "New MEL Buffer",
        "Save Script to Shelf",
        "Source Script",
    )
    try:
        for name in _MAYA_REGISTRY_ACTIONS:
            if name in panel._action_registry:
                action = panel._action_registry[name]
                action.setVisible(False)
                _bl_log("Hidden registry action: '{}'".format(name))
    except AttributeError:
        pass

    # Hide Maya-specific help menu links.
    _MAYA_ACTION_TEXTS = (
        "MEL Command Reference",
        "Python Command Reference",
        "Node and Attribute Reference",
    )
    try:
        for action in panel.actions():
            if action.text() in _MAYA_ACTION_TEXTS:
                action.setVisible(False)
                _bl_log("Hidden action by text: '{}'".format(action.text()))
    except (AttributeError, RuntimeError):
        pass

    # --- Add Blender-specific help links ------------------------------------
    try:
        import webbrowser

        # Find the Help menu from the passed menubar reference.
        help_menu = None
        if menubar is not None:
            for action in menubar.actions():
                if action.text().replace("&", "") == "Help":
                    help_menu = action.menu()
                    break

        if help_menu is not None:
            first_action = help_menu.actions()[0] if help_menu.actions() else None

            # Blender Python API reference.
            bpy_api_action = help_menu.addAction("Blender Python API Reference")
            bpy_api_action.triggered.connect(
                lambda: webbrowser.open("https://docs.blender.org/api/current/")
            )

            # Blender scripting documentation.
            bpy_scripting_action = help_menu.addAction("Blender Scripting Guide")
            bpy_scripting_action.triggered.connect(
                lambda: webbrowser.open("https://docs.blender.org/manual/en/latest/advanced/scripting/index.html")
            )

            # Blender Developer docs.
            bpy_dev_action = help_menu.addAction("Blender Developer Documentation")
            bpy_dev_action.triggered.connect(
                lambda: webbrowser.open("https://developer.blender.org/docs/")
            )

            # Move Blender links to the top of the Help menu.
            if first_action is not None:
                help_menu.insertAction(first_action, bpy_api_action)
                help_menu.insertAction(first_action, bpy_scripting_action)
                help_menu.insertAction(first_action, bpy_dev_action)

            _bl_log("Added Blender documentation links to Help menu")
        else:
            _bl_log_warning("Could not find Help menu to add Blender docs")
    except Exception as exc:
        _bl_log_warning("Could not add Blender help links: {}".format(exc))

    # --- Close any open MEL tabs --------------------------------------------
    try:
        container = panel._group_container
        for group in container.groups():
            mel_indices = []
            for i, (editor, tab_name, file_path) in enumerate(group.editors()):
                if getattr(editor, 'language', '') == 'mel':
                    mel_indices.append(i)
            for i in reversed(mel_indices):
                group.remove_editor(i)
                _bl_log("Closed MEL tab at index {}".format(i))
    except (AttributeError, Exception) as exc:
        _bl_log_warning("Could not close MEL tabs: {}".format(exc))

    # --- Override the New Tab dialog to exclude MEL -------------------------
    try:
        from mca_qt.widgets.new_tab_dialog import NewTabDialog
        from PySide6.QtWidgets import QDialog

        _BLENDER_LANGUAGES = [("Python", "python"), ("Text", "text")]

        def _blender_new_tab_dialog(self_ref=panel):
            """Show the New Tab dialog without MEL option."""
            dialog = NewTabDialog(self_ref, languages=_BLENDER_LANGUAGES)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                language = dialog.get_language()
                if language == "python":
                    self_ref._new_python_buffer()
                elif language == "text":
                    self_ref._new_text_buffer()

        import types
        panel._show_new_tab_dialog = types.MethodType(
            lambda self: _blender_new_tab_dialog(), panel
        )
        _bl_log("Replaced New Tab dialog (no MEL option)")
    except Exception as exc:
        _bl_log_warning("Could not override New Tab dialog: {}".format(exc))


def _build_status_bar(panel, outer_layout):
    """
    Add a blue status bar at the bottom of the outer window layout.

    Creates a QFrame with labels for Python version, error/warning counts,
    indexing progress, cursor position, language, encoding, and project name.

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

    # Error count indicator.
    error_label = QLabel("\u2297 0")
    error_label.setStyleSheet(label_style)
    bar_layout.addWidget(error_label)

    # Warning count indicator.
    warning_label = QLabel("\u26a0 0")
    warning_label.setStyleSheet(label_style)
    bar_layout.addWidget(warning_label)

    # Symbol index status indicator.
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

    # Add the status bar to the outer layout.
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

    _bl_log("Status bar created")


# ============================================================================
# Step 6: Qt Event Pump via bpy.app.timers
# ============================================================================

def _qt_tick():
    """
    Timer callback for pumping the Qt event loop from Blender.

    Registered with ``bpy.app.timers.register()`` at ~120Hz. Processes
    all pending Qt events so the editor window stays responsive while
    Blender owns the main loop.

    Also monitors whether the user closed the window via the X button.

    :return: Interval until next call (seconds), or None to unregister.
    :rtype: float or None
    """
    global _last_qt_hwnd

    # Check if the user closed the editor via the X button.
    if _mca_editor_window is not None and _last_qt_hwnd:
        try:
            if not _mca_editor_window.isVisible():
                _bl_log("Editor closed by user (X button) — saving state")
                _close_editor_internal()
                return None  # Unregister timer.
        except RuntimeError:
            _close_editor_internal()
            return None

    # Process pending Qt events so the editor stays responsive.
    if _mca_app is not None:
        _mca_app.processEvents()

    # Check if Qt recreated the HWND (happens once after first show).
    if _mca_editor_window is not None and _blender_hwnd:
        try:
            current_hwnd = int(_mca_editor_window.winId())
            if current_hwnd != _last_qt_hwnd:
                _bl_log("HWND changed: {} -> {} — re-applying owner window".format(
                    hex(_last_qt_hwnd), hex(current_hwnd)
                ))
                _last_qt_hwnd = current_hwnd
                _set_owner_window(current_hwnd, _blender_hwnd)
        except RuntimeError:
            pass

    # Return interval for next call (~120Hz).
    return 1.0 / 120.0


def _start_qt_timer():
    """
    Register the Qt event pump timer with Blender.

    Uses ``bpy.app.timers.register()`` to pump Qt events at ~120Hz.
    The timer runs on Blender's main thread during idle time.
    """
    global _qt_timer_registered
    import bpy

    if not _qt_timer_registered:
        bpy.app.timers.register(_qt_tick, first_interval=0.0, persistent=True)
        _qt_timer_registered = True
        _bl_log("Qt event pump timer registered (~120Hz)")


def _stop_qt_timer():
    """
    Unregister the Qt event pump timer from Blender.
    """
    global _qt_timer_registered
    import bpy

    if _qt_timer_registered:
        try:
            if bpy.app.timers.is_registered(_qt_tick):
                bpy.app.timers.unregister(_qt_tick)
        except Exception:
            pass
        _qt_timer_registered = False
        _bl_log("Qt event pump timer unregistered")


# ============================================================================
# Step 7: Close and Cleanup
# ============================================================================

def _close_editor_internal(shutting_down=False):
    """
    Close the MCA Editor window cleanly (internal implementation).

    Saves window geometry, restores stdout/stderr, and cleans up Qt state.

    :param bool shutting_down: True if Blender is shutting down.
    """
    global _mca_editor_window, _last_qt_hwnd, _blender_hwnd
    global _window_geometry, _original_stdout, _original_stderr

    # Restore original stdout/stderr before anything else.
    if _original_stdout is not None:
        sys.stdout = _original_stdout
        _original_stdout = None
    if _original_stderr is not None:
        sys.stderr = _original_stderr
        _original_stderr = None

    if _mca_editor_window is not None:
        try:
            # Save the panel's session state BEFORE closing the window.
            panel = getattr(_mca_editor_window, "_panel", None)
            if panel is not None:
                from mca_core.config.settings import MCASettings
                settings = MCASettings(dcc_version="Blender")
                panel.save_window_state(settings)
                panel.cleanup()
                _bl_log("Saved session state (tabs, tree, splitters)")

            # Save the window geometry for reopen.
            _window_geometry = _mca_editor_window.saveGeometry()

            # Persist state to QSettings.
            # If Blender is shutting down → was_open=True (auto-reopen).
            # If user closed with X → was_open=False (don't auto-reopen).
            _save_persistent_state(
                was_open=shutting_down,
                geometry=_window_geometry,
            )

            _mca_editor_window.close()
            _bl_log("MCA Editor closed")
        except RuntimeError:
            pass
        _mca_editor_window = None

    # Reset HWND tracking.
    _last_qt_hwnd = 0
    _blender_hwnd = 0


# ============================================================================
# Public API — called by __init__.py operators
# ============================================================================

def launch_editor():
    """
    Public entry point to launch the MCA Editor.

    Creates the editor if it doesn't exist, or raises it if already open.

    :return: True if the editor was created/raised successfully.
    :rtype: bool
    """
    try:
        return _launch_editor()
    except Exception as exc:
        import traceback
        _bl_log_error("launch_editor() failed: {}".format(exc))
        _bl_log_error(traceback.format_exc())
        return False


def close_editor(shutting_down=False):
    """
    Public entry point to close the MCA Editor.

    :param bool shutting_down: True if Blender is shutting down.
    """
    _stop_qt_timer()
    _close_editor_internal(shutting_down=shutting_down)


def auto_launch():
    """
    Auto-open the editor if it was open when Blender last closed.

    Checks the ``was_open`` flag in QSettings — if True, launches
    the editor automatically.
    """
    try:
        _setup_venv()
        was_open, _ = _load_persistent_state()
        if was_open:
            _bl_log("Auto-launching editor (was open in previous Blender session)")
            return _launch_editor(show_license_dialog=False)
        else:
            _bl_log("Auto-launch skipped (editor was not open in previous session)")
            return False
    except Exception as exc:
        import traceback
        _bl_log_error("auto_launch() failed: {}".format(exc))
        _bl_log_error(traceback.format_exc())
        return False
