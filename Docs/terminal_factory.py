"""
MCA Editor — Terminal Widget Factory
=====================================

Selects the best available terminal widget for the current environment at
runtime. The selection order is:

1. **xterm.js** (QWebEngineView) — Full-featured terminal with GPU-
   accelerated rendering. Requires QtWebEngine, which is available in
   PySide6 standalone but NOT in Maya's Qt.

2. **Native** (QPlainTextEdit + AnsiParser) — Pure-Qt terminal using a
   custom VT100/ANSI parser and QPlainTextEdit for rendering. Works
   anywhere Qt works, including Maya. Requires pywinpty for the PTY
   backend.

3. **None** — Terminal feature is disabled. The editor still works, but
   the terminal toggle is hidden and Ctrl+` does nothing.

Both terminal widgets expose the same public API so the editor panel
doesn't need to know which one it got.

Dependencies:
    - mca_qt.qt_compat (for Qt imports)
    - pywinpty (checked at runtime, not at import time)

Side Effects:
    - None. This module only imports; it doesn't create widgets.
"""

import logging
import platform

logger = logging.getLogger(__name__)


def create_terminal_widget(parent=None):
    """
    Create and return the best available terminal widget.

    Tries xterm.js first (requires QtWebEngine), falls back to the
    native QPlainTextEdit version (requires pywinpty), returns None
    if neither is available.

    :param QWidget parent: Parent widget for the terminal.
    :return: A terminal widget instance, or None if unavailable.
    :rtype: TerminalWidget or None
    """
    # --- Try xterm.js (standalone PySide6 environments) ---
    widget = _try_xterm(parent)
    if widget is not None:
        logger.info("Terminal: using xterm.js backend (QWebEngineView)")
        return widget

    # --- Try native (Maya and minimal environments) ---
    widget = _try_native(parent)
    if widget is not None:
        logger.info("Terminal: using native backend (QPlainTextEdit + AnsiParser)")
        return widget

    # --- Nothing available ---
    logger.info(
        "Terminal: unavailable (no QtWebEngine and no pywinpty). "
        "Terminal feature will be disabled."
    )
    return None


def _try_xterm(parent):
    """
    Attempt to create the xterm.js terminal widget.

    Fails if QtWebEngineWidgets is not importable (Maya, PySide2
    environments, or PySide6 installed without WebEngine).

    :param QWidget parent: Parent widget.
    :rtype: TerminalWidget or None
    """
    try:
        # QtWebEngine is a separate optional package — test for it first
        # before importing the widget module (which would fail at the
        # top-level import of QWebEngineView).
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        from mca_qt.widgets.terminal_xterm import TerminalWidget
        return TerminalWidget(parent)
    except ImportError:
        logger.debug("xterm.js terminal not available (QtWebEngine not found)")
        return None
    except Exception as exc:
        logger.debug("xterm.js terminal failed to initialize: %s", exc)
        return None


def _try_native(parent):
    """
    Attempt to create the native QPlainTextEdit terminal widget.

    Fails if pywinpty is not installed. On non-Windows platforms, this
    always fails because pywinpty is Windows-only (a Unix PTY backend
    could be added later using the pty stdlib module).

    :param QWidget parent: Parent widget.
    :rtype: TerminalWidget or None
    """
    # --- Platform check ---
    if platform.system() != "Windows":
        logger.debug("Native terminal not available (Windows-only, current: %s)", platform.system())
        return None

    # --- Check pywinpty availability ---
    try:
        import winpty  # noqa: F401
    except ImportError:
        logger.debug("Native terminal not available (pywinpty not installed)")
        return None

    # --- Create the widget ---
    try:
        from mca_qt.widgets.terminal_native import TerminalWidget
        return TerminalWidget(parent)
    except Exception as exc:
        logger.debug("Native terminal failed to initialize: %s", exc)
        return None


def is_terminal_available():
    """
    Quick check if any terminal backend can work in this environment.

    Useful for deciding whether to show terminal-related menu items
    and shortcuts without actually creating a widget.

    :rtype: bool
    """
    # Check xterm.js
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except ImportError:
        pass

    # Check native (Windows + pywinpty)
    if platform.system() == "Windows":
        try:
            import winpty  # noqa: F401
            return True
        except ImportError:
            pass

    return False
