"""
MCA Editor — Unreal Engine Qt Host Script.

Creates the PySide6-based MCA Editor panel and embeds it inside the
Unreal Editor's native window via Win32 SetParent. Called by
SMCANativeHost on first tick.

Expects ``_mca_ue_parent_hwnd`` to be set before execution (set by C++).

When the user docks/undocks a tab, UE destroys the floating window,
which also destroys our Win32 child HWND. The ``_mca_reparent()``
function detects this via ``IsWindow()`` and forces Qt to recreate
the native handle (``destroy()`` + ``create()`` rebuilds the HWND)
while preserving all widget state.

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

# Module-level logger.
logger = logging.getLogger("mca_editor.ue_host")


# =============================================================================
# Win32 constants
# =============================================================================

# ShowWindow commands.
_SW_HIDE = 0
_SW_SHOWNOACTIVATE = 8


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
# Step 6: Reparent into UE's native window
# =============================================================================

# Get the Qt widget's native window handle.
_mca_qt_hwnd = int(_mca_editor.winId())

# Reparent the Qt widget as a child of the UE editor window.
# This makes it move and clip with the UE window automatically.
ctypes.windll.user32.SetParent(_mca_qt_hwnd, _mca_ue_parent_hwnd)

# Show the widget (now renders inside UE's window).
_mca_editor.show()

logger.info(
    "MCA Editor embedded: Qt HWND=%s, UE parent HWND=%s",
    hex(_mca_qt_hwnd), hex(_mca_ue_parent_hwnd)
)


# =============================================================================
# Step 7: Helper functions called by C++ on every tick
# =============================================================================

def _mca_tick(x, y, w, h):
    """
    Update Qt widget position and pump events.

    Called by SMCANativeHost::Tick when geometry changes.
    Coordinates are relative to the parent UE window's client area.

    :param int x: X position relative to UE window client area.
    :param int y: Y position relative to UE window client area.
    :param int w: Widget width in pixels.
    :param int h: Widget height in pixels.
    """
    ctypes.windll.user32.MoveWindow(_mca_qt_hwnd, int(x), int(y), int(w), int(h), True)
    # Ensure the widget is visible (may have been hidden for backgrounded tab).
    ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_SHOWNOACTIVATE)
    if _mca_app:
        _mca_app.processEvents()


def _mca_reparent(new_parent_hwnd):
    """
    Reparent the Qt widget into a new UE window.

    Called by SMCANativeHost when the tab is docked/undocked, which
    changes the containing native window. During this transition,
    the old parent window may be destroyed by UE, which also destroys
    our Win32 child HWND.

    If the HWND was destroyed, we force Qt to recreate it by calling
    ``destroy()`` then ``create()`` (which rebuilds the native window
    handle) then ``SetParent()`` it into the new UE window. All widget
    state (children, layout, signals, editor content) is preserved —
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
        # Tested: setWindowFlags() does NOT work here — Qt caches the dead HWND.
        _mca_editor.destroy()
        _mca_editor.create()
        _mca_qt_hwnd = int(_mca_editor.winId())
        logger.info("Recreated Qt HWND: %s", hex(_mca_qt_hwnd))

    # Reparent into the new UE window as a child.
    ctypes.windll.user32.SetParent(_mca_qt_hwnd, new_parent_hwnd)
    _mca_editor.show()
    logger.info("Reparented Qt widget to HWND=%s", hex(new_parent_hwnd))


def _mca_pump_qt():
    """
    Pump Qt events without geometry change.

    Called by SMCANativeHost::Tick when the geometry hasn't changed
    but Qt events still need processing (keyboard input, timers, etc.).
    """
    if _mca_app:
        _mca_app.processEvents()


def _mca_hide_qt():
    """
    Hide the Qt widget when the tab is backgrounded.

    Called by SMCANativeHost when the Slate geometry shrinks to zero
    (another tab is selected in the same dock area).
    """
    ctypes.windll.user32.ShowWindow(_mca_qt_hwnd, _SW_HIDE)


def _mca_cleanup_qt():
    """
    Clean up the Qt editor on tab close.

    Called by SMCANativeHost destructor. Closes the editor widget
    and clears references. QApplication persists for potential reuse.
    """
    global _mca_editor
    if _mca_editor:
        _mca_editor.close()
        _mca_editor = None
        logger.info("MCA Editor cleaned up")
