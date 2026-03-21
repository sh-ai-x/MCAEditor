"""
MCA Editor — Unreal Engine Qt Host Script.

Creates the PySide6-based MCA Editor panel and embeds it inside the
Unreal Editor's native window via Win32 SetParent. Called by
SMCANativeHost on first tick.

Expects ``_mca_ue_parent_hwnd`` to be set before execution (set by C++).

Embedding uses WS_CHILD style (not WS_POPUP) so the Qt widget is a true
child of the UE window: clipped to the parent's client area, with
parent-relative coordinates for MoveWindow.  The WS_CHILD style is set
via SetWindowLongW before calling SetParent, and Qt does NOT override it
on subsequent processEvents() calls.

When the user docks/undocks a tab, UE destroys the floating window,
which also destroys our Win32 child HWND. The ``_mca_reparent()``
function detects this via ``IsWindow()`` and forces Qt to recreate
the native handle (``destroy()`` + ``create()`` rebuilds the HWND)
while preserving all widget state.

UE engine log output (LogPython, LogMCAEditor, errors, warnings) is
piped into the MCA Editor's output panel via log file tailing, so
users see relevant UE messages without switching to the Output Log.

This gives UE users the EXACT same editor as Maya — same codebase,
same features, same theme, same workflow.

Dependencies:
    - PySide6 (installed via managed venv or manually)
    - mca_core, mca_qt packages (from MCA Editor source)
"""

import sys
import os
import ctypes
import logging

# Module-level logger (fallback for non-UE contexts).
logger = logging.getLogger("mca_editor.ue_host")


# =============================================================================
# Win32 constants and ctypes setup
# =============================================================================

# ShowWindow commands.
_SW_HIDE = 0
_SW_SHOWNOACTIVATE = 8

# Window style constants for true child-window embedding.
_GWL_STYLE = -16
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_WS_CLIPCHILDREN = 0x02000000
_WS_CLIPSIBLINGS = 0x04000000

# SetWindowPos flags for applying style changes.
_SWP_FRAMECHANGED = 0x0020
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004

# Configure ctypes for Get/SetWindowLongW so Python doesn't overflow
# on 32-bit signed style values.  Without argtypes, ctypes tries to
# convert large Python ints (e.g. 0xD6CF0000 from bitwise OR) into
# a default C int, causing "OverflowError: int too long to convert".
_user32 = ctypes.windll.user32
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]


# =============================================================================
# Step 1: Locate MCA Editor packages
# =============================================================================

# In development, use the source directory directly.
# In production, packages would be bundled with the UE plugin.
_MCA_SOURCE_DIR = os.environ.get("MCA_EDITOR_SOURCE", r"E:\Projects\MCAEditor")
if os.path.isdir(_MCA_SOURCE_DIR) and _MCA_SOURCE_DIR not in sys.path:
    sys.path.insert(0, _MCA_SOURCE_DIR)
    logger.info("Added MCA Editor source to path: %s", _MCA_SOURCE_DIR)


# =============================================================================
# Step 2: Set up managed venv for PySide6
# =============================================================================

# The venv manager handles dependency installation into a versioned venv
# at ~/Documents/mca_preferences/.venv-X.Y/. UE doesn't bundle PySide6
# like Maya does, so we include it as an additional requirement.
# If venv setup fails, we fall back to checking if PySide6 is already importable.
try:
    from mca_core.venv_manager import setup_venv, REQUIRED_PACKAGES

    # Extend the default requirements with PySide6 for UE.
    # Maya ships its own PySide2/6, but UE's Python doesn't include it.
    _ue_requirements = dict(REQUIRED_PACKAGES)
    _ue_requirements["PySide6"] = "PySide6"

    setup_venv(requirements=_ue_requirements)
    logger.info("Managed venv setup complete")
except Exception as e:
    logger.warning("Venv setup failed (PySide6 must be pre-installed): %s", e)


# =============================================================================
# Step 3: Import PySide6
# =============================================================================

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
except ImportError as e:
    raise RuntimeError(
        "MCA Editor requires PySide6.\n\n"
        "Install it by running this in UE's Python console:\n"
        "  import subprocess, sys\n"
        "  subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'PySide6'])\n\n"
        f"Import error: {e}"
    )


# =============================================================================
# Step 4: Create QApplication
# =============================================================================

# Reuse existing QApplication if one exists (e.g. from a previous tab open).
_mca_app = QApplication.instance()
if _mca_app is None:
    _mca_app = QApplication(sys.argv)
    logger.info("Created new QApplication")
else:
    logger.info("Reusing existing QApplication")


# =============================================================================
# Step 5: Create the MCA Editor panel
# =============================================================================

from mca_core.config.settings import MCASettings
from mca_core.adapters import AdapterManager
from mca_qt.editor_panel import MCAEditorPanel

_mca_settings = MCASettings()

# Pass an empty AdapterManager to indicate we're embedded in a DCC.
# This hides DCC-specific toolbar elements (like Maya connection buttons)
# and uses local Python execution — which is UE's Python interpreter,
# so `import unreal` works out of the box.
_mca_adapter_manager = AdapterManager()

_mca_editor = MCAEditorPanel(
    _mca_settings,
    adapter_manager=_mca_adapter_manager,
    dcc_version="UE5",
)

# Make the widget frameless — no title bar, no window border.
# It will be positioned precisely over the Slate tab area.
_mca_editor.setWindowFlags(Qt.WindowType.FramelessWindowHint)


# =============================================================================
# Step 6: Embed into UE's native window (WS_CHILD approach)
# =============================================================================


def _apply_child_style(hwnd, parent_hwnd):
    """
    Apply WS_CHILD style and reparent a Qt HWND into a UE window.

    Qt creates windows with WS_POPUP by default. With WS_POPUP, Win32's
    SetParent() only sets an "owner" relationship — z-ordering only, no
    clipping, and MoveWindow uses screen coordinates. GetParent() returns 0.

    With WS_CHILD, SetParent() creates a TRUE parent-child relationship:
    the widget is clipped to the parent's client area, MoveWindow uses
    parent-relative coordinates, and GetParent() returns the actual parent.

    This must be re-applied whenever Qt recreates the HWND (which can
    happen during the first processEvents() after show, or after
    destroy()+create() during dock/undock transitions).

    :param int hwnd: The Qt widget's native window handle.
    :param int parent_hwnd: The UE window to embed into.
    """
    # Clear WS_POPUP, set WS_CHILD + clipping flags.
    old_style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
    new_style = (old_style & ~_WS_POPUP) | _WS_CHILD | _WS_CLIPCHILDREN | _WS_CLIPSIBLINGS
    _user32.SetWindowLongW(hwnd, _GWL_STYLE, new_style)

    # Reparent as a true child of the UE window.
    ctypes.windll.user32.SetParent(hwnd, parent_hwnd)

    # SWP_FRAMECHANGED is required for the WS_CHILD change to take
    # full effect (recomputes the window frame geometry).
    _user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER
    )


# Get the Qt widget's native window handle.
# winId() forces native window creation even before show().
_mca_qt_hwnd = int(_mca_editor.winId())

# Apply WS_CHILD embedding.
_apply_child_style(_mca_qt_hwnd, _mca_ue_parent_hwnd)

# Show the widget so Qt initializes layout and paint state internally,
# then immediately hide at the OS level. The first _mca_tick() call
# will MoveWindow to the correct position THEN ShowWindow — so the
# widget appears at the right location on the first frame, no flash.
_mca_editor.show()
ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_HIDE)

# Pump events to let Qt finalize the native window. This may trigger
# the one-time HWND recreation that Qt does after first show().
if _mca_app:
    _mca_app.processEvents()

# Check if the HWND was recreated during processEvents (Qt does this
# once after the first show). If so, re-embed and re-hide.
_new_hwnd = int(_mca_editor.winId())
if _new_hwnd != _mca_qt_hwnd:
    _mca_qt_hwnd = _new_hwnd
    _apply_child_style(_mca_qt_hwnd, _mca_ue_parent_hwnd)
    ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_HIDE)

# Log via unreal for visibility in UE's Output Log.
try:
    import unreal
    _parent_check = ctypes.windll.user32.GetParent(_mca_qt_hwnd)
    unreal.log(
        "MCA Editor embedded: Qt HWND={}, Parent={}, UE HWND={}".format(
            hex(_mca_qt_hwnd), hex(_parent_check), hex(_mca_ue_parent_hwnd)
        )
    )
except ImportError:
    logger.info(
        "MCA Editor embedded: Qt HWND=%s, UE parent HWND=%s",
        hex(_mca_qt_hwnd), hex(_mca_ue_parent_hwnd)
    )


# =============================================================================
# Step 7: UE Log Tailing — pipe engine output to MCA panel
# =============================================================================

# Capture UE's log output and route it to the MCA Editor's output panel.
# This gives users visibility into UE engine messages (Python output,
# compilation results, errors, warnings) without switching to UE's
# Output Log panel.

# Path to UE's active log file, set by _init_log_tailer().
_log_file_path = None

# Current read position in the log file (seek offset).
_log_file_pos = 0

# Frame counter for throttling log reads (~2 seconds at 30fps).
_log_tail_counter = 0

# Exclude extremely noisy per-frame categories that would flood the panel.
# Everything else is shown (including errors/warnings from all categories).
_LOG_EXCLUDE = {
    "LogD3D11RHI", "LogVulkanRHI", "LogRHI",
    "LogRendererCore", "LogRenderer",
    "LogShaders", "LogMaterial",
    "LogStreaming", "LogLinker",
}


def _init_log_tailer():
    """
    Initialize the UE log file tailer.

    Finds the most recent log file in the project's Saved/Logs/ directory
    and seeks to the end so we only capture NEW output going forward.
    """
    global _log_file_path, _log_file_pos
    try:
        import unreal
        saved_dir = unreal.Paths.project_saved_dir()
        log_dir = os.path.normpath(os.path.join(saved_dir, "Logs"))

        if os.path.isdir(log_dir):
            # Find log files sorted by modification time (most recent first).
            log_files = sorted(
                [f for f in os.listdir(log_dir) if f.endswith(".log")],
                key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
                reverse=True,
            )
            if log_files:
                _log_file_path = os.path.join(log_dir, log_files[0])
                # Seek to end — only capture new output from this point.
                _log_file_pos = os.path.getsize(_log_file_path)
                unreal.log("MCA: Log tailer watching {}".format(_log_file_path))
    except Exception as e:
        logger.warning("Could not init log tailer: %s", e)


# Initialize the tailer on load.
_init_log_tailer()


def _tail_ue_log():
    """
    Read new lines from UE's log file and pipe to MCA output panel.

    Filters to relevant log categories (LogPython, LogMCAEditor, etc.)
    plus any errors/warnings from all categories. Throttled to run
    approximately every 2 seconds to minimize file I/O overhead.
    """
    global _log_file_pos, _log_tail_counter

    # Throttle: only check every 60 ticks (~2 seconds at 30fps).
    _log_tail_counter += 1
    if _log_tail_counter < 60:
        return
    _log_tail_counter = 0

    if not _log_file_path or not _mca_editor:
        return

    try:
        current_size = os.path.getsize(_log_file_path)
        if current_size <= _log_file_pos:
            return  # No new content.

        with open(_log_file_path, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(_log_file_pos)
            new_text = f.read()
            _log_file_pos = f.tell()

        if not new_text.strip():
            return

        output = _mca_editor._output
        if not output:
            return

        for line in new_text.splitlines():
            line = line.strip()
            if not line:
                continue

            # --- Parse UE log format ---
            # Format: [YYYY.MM.DD-HH.MM.SS:mmm][frame]Category: Level: Message
            display = line

            # Strip timestamp prefix [YYYY.MM.DD-HH.MM.SS:mmm].
            if display.startswith('['):
                idx = display.find(']')
                if idx > 0:
                    display = display[idx + 1:].strip()
                    # Strip frame counter [NNN].
                    if display.startswith('['):
                        idx2 = display.find(']')
                        if idx2 > 0:
                            display = display[idx2 + 1:].strip()

            # Extract the log category (text before first colon).
            category = ""
            colon_idx = display.find(':')
            if colon_idx > 0:
                category = display[:colon_idx].strip()

            # --- Filter: exclude known noisy per-frame categories ---
            if category in _LOG_EXCLUDE:
                continue

            is_error = 'Error' in display
            is_warning = 'Warning' in display and 'Error' not in display

            # --- Route to the appropriate output method ---
            if is_error:
                output.write_error(display)
            elif is_warning:
                output.write_warning(display)
            else:
                # Strip "Display: " prefix for cleaner output.
                display = display.replace(': Display: ', ': ', 1)
                output.write_output(display)

    except Exception:
        # Never crash the tick loop for log tailing errors.
        pass


# =============================================================================
# Step 8: Helper functions called by C++ on every tick
# =============================================================================

def _ensure_embedded():
    """
    Verify the Qt HWND is still embedded as WS_CHILD.

    Qt may recreate the native window handle once after the first show
    (typically on tick 2). When the HWND is recreated, the WS_CHILD
    style and parent relationship are lost. This function detects the
    change via GetParent (fast single Win32 call — no winId() overhead)
    and re-applies the embedding.
    """
    global _mca_qt_hwnd

    if not _mca_editor:
        return

    # Fast path: if GetParent still returns our UE window, all is well.
    # GetParent returns 0 for WS_POPUP windows (Qt's default after HWND
    # recreation), so this also detects HWND recreation.
    if ctypes.windll.user32.GetParent(_mca_qt_hwnd) == _mca_ue_parent_hwnd:
        return

    # HWND was recreated or parent lost — get the new HWND and re-embed.
    _mca_qt_hwnd = int(_mca_editor.winId())
    _apply_child_style(_mca_qt_hwnd, _mca_ue_parent_hwnd)
    _mca_editor.show()
    _mca_editor.update()
    try:
        import unreal
        unreal.log("MCA: Re-embedded after HWND change: {}".format(hex(_mca_qt_hwnd)))
    except ImportError:
        pass


# Track visibility to avoid calling ShowWindow every tick.
_qt_visible = False


# =============================================================================
# Keyboard focus — post-processEvents sync
# =============================================================================
#
# With WS_CHILD, Win32 delivers keyboard events to whichever HWND has
# Win32 focus. Qt child widgets (like the code editor) have their OWN
# native HWNDs, so Win32 focus must be on the SPECIFIC widget's HWND —
# not just the panel's top-level HWND.
#
# Strategy: after every processEvents() call, check which widget Qt has
# focused (via mouse clicks, tab key, etc.) and sync Win32 focus to
# that widget's native HWND. This runs AFTER Qt processes click events,
# so Qt has already set internal focus on the correct child widget.

# Track the last HWND we set Win32 focus on, to avoid redundant calls.
_last_focus_hwnd = 0


def _sync_win32_focus():
    """
    Sync Win32 keyboard focus to match Qt's focused widget.

    Called after processEvents() so Qt has already processed any mouse
    clicks and set internal focus on the correct child widget. We then
    call Win32 SetFocus on that widget's native HWND so keyboard events
    reach it through Win32's message dispatch.
    """
    global _last_focus_hwnd

    if not _mca_app:
        return

    focus_widget = _mca_app.focusWidget()
    if not focus_widget:
        return

    # Get the native HWND of the Qt-focused widget.
    target_hwnd = int(focus_widget.winId())
    if not target_hwnd or target_hwnd == _last_focus_hwnd:
        return

    # Only set focus if Win32 focus isn't already on the target.
    current_focus = ctypes.windll.user32.GetFocus()
    if current_focus != target_hwnd:
        ctypes.windll.user32.SetFocus(target_hwnd)

    _last_focus_hwnd = target_hwnd


def _mca_tick(x, y, w, h):
    """
    Update Qt widget position and pump events.

    Called by SMCANativeHost::Tick when geometry changes.
    Coordinates are relative to the parent UE window's client area
    (correct because we use WS_CHILD style).

    :param int x: X position relative to UE window client area.
    :param int y: Y position relative to UE window client area.
    :param int w: Widget width in pixels.
    :param int h: Widget height in pixels.
    """
    global _qt_visible

    # Ensure WS_CHILD embedding is intact (Qt may recreate the HWND).
    _ensure_embedded()

    # Position the widget. bRepaint=True so Windows invalidates the
    # new region — without this, resized areas render as black.
    ctypes.windll.user32.MoveWindow(_mca_qt_hwnd, int(x), int(y), int(w), int(h), True)

    # Only call ShowWindow on visibility transitions (not every tick).
    if not _qt_visible:
        ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_SHOWNOACTIVATE)
        _qt_visible = True

    # Check for new UE log output.
    _tail_ue_log()
    if _mca_app:
        # Activate Qt's window state so setFocus/focusWidget work correctly.
        # Without this, Qt doesn't consider our WS_CHILD panel "active" and
        # silently ignores focus changes from mouse clicks. This does NOT
        # steal UE's foreground window — it only sets Qt's internal state.
        _mca_editor.activateWindow()
        _mca_app.processEvents()
        # Sync Win32 focus to whichever widget Qt focused (e.g. after click).
        _sync_win32_focus()


def _mca_reparent(new_parent_hwnd):
    """
    Reparent the Qt widget into a new UE window.

    Called by SMCANativeHost when the tab is docked/undocked, which
    changes the containing native window. During this transition,
    the old parent window may be destroyed by UE, which also destroys
    our Win32 child HWND.

    If the HWND was destroyed, we force Qt to recreate it by calling
    ``destroy()`` then ``create()`` (which rebuilds the native window
    handle) then re-apply WS_CHILD + SetParent. All widget state
    (children, layout, signals, editor content) is preserved —
    only the native handle changes.

    :param int new_parent_hwnd: New parent window handle (HWND).
    """
    global _mca_ue_parent_hwnd, _mca_qt_hwnd
    _mca_ue_parent_hwnd = new_parent_hwnd

    # Check if the Qt HWND was destroyed when the old parent window
    # was destroyed during the dock/undock transition.
    if not ctypes.windll.user32.IsWindow(_mca_qt_hwnd):
        # Force Qt to recreate the native window handle.
        # destroy() tears down the native resources, create() rebuilds them.
        # This gives us a fresh, valid HWND while preserving all widget state
        # (children, layout, signals, editor content).
        _mca_editor.destroy()
        _mca_editor.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        _mca_editor.create()
        _mca_editor.show()
        _mca_qt_hwnd = int(_mca_editor.winId())
        logger.info("Recreated Qt HWND: %s", hex(_mca_qt_hwnd))

    # Apply WS_CHILD embedding into the new parent.
    _apply_child_style(_mca_qt_hwnd, new_parent_hwnd)
    _mca_editor.show()
    logger.info("Reparented Qt widget to HWND=%s", hex(new_parent_hwnd))


def _mca_pump_qt():
    """
    Pump Qt events without geometry change.

    Called by SMCANativeHost::Tick when the geometry hasn't changed
    but Qt events still need processing (keyboard input, timers, etc.).
    Also checks embedding state and UE log output.
    """
    _ensure_embedded()
    _tail_ue_log()
    if _mca_app:
        _mca_editor.activateWindow()
        _mca_app.processEvents()
        # Sync Win32 focus to whichever widget Qt focused (e.g. after click).
        _sync_win32_focus()


def _mca_hide_qt():
    """
    Hide the Qt widget when the tab is backgrounded.

    Called by SMCANativeHost when the Slate geometry shrinks to zero
    (another tab is selected in the same dock area).
    """
    global _qt_visible
    ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_HIDE)
    _qt_visible = False


def _mca_cleanup_qt():
    """
    Clean up the Qt editor on tab close.

    Called by SMCANativeHost destructor. Hides the HWND immediately
    to prevent visual artifacts, then closes the widget and clears
    references. QApplication persists for potential reuse.
    """
    global _mca_editor, _mca_qt_hwnd
    if _mca_editor:
        # Hide the HWND immediately so it doesn't linger on screen
        # while Qt processes the close event.
        ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_HIDE)

        _mca_editor.close()

        # Pump events once so Qt fully processes the close.
        if _mca_app:
            _mca_app.processEvents()

        _mca_editor = None
        _mca_qt_hwnd = 0
        logger.info("MCA Editor cleaned up")
