"""
MCA Qt - Terminal Widget Factory.

Selects the best available terminal widget for the current environment
at runtime.  Both frontends share the same ``TerminalBackend`` and
expose an identical public API, so the rest of the editor doesn't need
to know which one is active.

Selection order:
    1. **xterm.js** (``terminal_xterm.TerminalWidget``) — preferred when
       PySide6 QtWebEngine, xterm.js resources, AND pywinpty are all
       available (standalone mode with full PTY support).
    2. **Native** (``terminal_native.TerminalWidget``) — fallback for
       Maya or environments missing any xterm.js requirement.  Works
       with pywinpty (full PTY) or without it (subprocess pipe fallback).
    3. **None** — terminal feature disabled entirely (non-Windows).

Dependencies:
    - None (pure Python stdlib — import checks are done lazily)

Side Effects:
    - None. This module only imports; it doesn't create widgets on load.
"""

import logging
import os
import platform

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Public API ---------------------------------------------------------------

def create_terminal_widget(shell="", cwd="", font_size=12, parent=None):
    """
    Return the best available terminal widget for the current environment.

    Both widget classes (xterm.js and native) accept the same constructor
    arguments and expose the same public API (``start()``, ``terminate()``,
    ``is_alive()``, ``set_font_size()``, ``clear()``, ``restart()``,
    ``setFocus()``), and the same signals (``process_exited``,
    ``font_size_changed``, ``title_changed``).

    :param str shell: Path to the shell executable (auto-detected if empty).
    :param str cwd: Working directory for the shell process.
    :param int font_size: Initial terminal font size.
    :param QWidget parent: Optional parent widget.
    :return: A terminal widget instance, or *None* if no terminal backend
        is available.
    :rtype: TerminalWidget or None
    """
    # --- Try xterm.js first (standalone with PySide6 + QtWebEngine) ---
    widget = _try_xterm(shell, cwd, font_size, parent)
    if widget is not None:
        logger.info("Terminal frontend: xterm.js (QWebEngineView)")
        return widget

    # --- Fall back to native (Maya or minimal environments) ---
    widget = _try_native(shell, cwd, font_size, parent)
    if widget is not None:
        logger.info("Terminal frontend: native (QPlainTextEdit + AnsiParser)")
        return widget

    # --- No terminal available ---
    logger.info(
        "Terminal unavailable (no QtWebEngine and no pywinpty). "
        "Terminal feature will be disabled."
    )
    return None


def is_terminal_available():
    """
    Quick check if any terminal backend can work in this environment.

    Useful for deciding whether to show terminal-related menu items
    and shortcuts without actually creating a widget.

    :return: *True* if at least one terminal frontend is available.
    :rtype: bool
    """
    # Check xterm.js (PySide6 + QtWebEngine + resources + pywinpty).
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        resources_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "resources", "terminal"
        )
        if os.path.isfile(os.path.join(resources_dir, "index.html")):
            # Also need pywinpty for xterm.js.
            try:
                import winpty  # noqa: F401
                return True
            except ImportError:
                pass
    except ImportError:
        pass

    # Check native (Windows only — works with or without pywinpty
    # via the subprocess pipe fallback in terminal_backend.py).
    if platform.system() == "Windows":
        return True

    return False


# --- Internal: Frontend Probes ------------------------------------------------

def _try_xterm(shell, cwd, font_size, parent):
    """
    Attempt to create the xterm.js terminal widget.

    Requires ALL of:
        - PySide6 QtWebEngine (for QWebEngineView)
        - xterm.js resource files on disk (index.html)
        - pywinpty (xterm.js frontend has no subprocess fallback)

    If any requirement is missing, returns None so the factory can
    fall through to the native terminal.

    :param str shell: Shell path.
    :param str cwd: Working directory.
    :param int font_size: Font size.
    :param QWidget parent: Parent widget.
    :return: Widget instance, or *None* on failure.
    :rtype: TerminalWidget or None
    """
    # Skip xterm.js entirely when running inside Maya.  Maya 2025 ships
    # PySide6 with QtWebEngine, so the import check below would pass, but
    # Maya's embedded QWebEngineView doesn't reliably render xterm.js
    # (the user sees only a blinking cursor).  The native QPlainTextEdit
    # terminal works perfectly in Maya with pywinpty, so always use that.
    if _is_maya():
        logger.debug("xterm.js skipped — running inside Maya (native preferred)")
        return None

    try:
        # QtWebEngine is a separate optional package — test for it first
        # before importing the widget module (which would fail at the
        # top-level import of QWebEngineView).
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

        # Verify xterm.js resources exist on disk.  In Maya deployments,
        # the xterm.js HTML/JS assets may not be included in the distribution
        # (they're ~100MB with QtWebEngine and not needed when the native
        # terminal is available).  If the resources are missing, fall through
        # to the native terminal instead of silently showing a blank page.
        resources_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "resources", "terminal"
        )
        index_html = os.path.join(resources_dir, "index.html")
        if not os.path.isfile(index_html):
            logger.debug("xterm.js terminal not available (resources/terminal/"
                         "index.html not found at %s)", index_html)
            return None

        # pywinpty is required — the xterm.js frontend uses the PTY
        # backend exclusively (it has no subprocess pipe fallback because
        # xterm.js needs a real terminal with ANSI escape sequences).
        # Use the lazy check so it can recover from import-ordering issues.
        from mca_qt.widgets.terminal_backend import check_conpty
        if not check_conpty():
            logger.debug("xterm.js terminal not available (pywinpty not found "
                         "— falling through to native terminal)")
            return None

        from mca_qt.widgets.terminal_xterm import TerminalWidget
        return TerminalWidget(
            shell=shell, cwd=cwd, font_size=font_size, parent=parent,
        )
    except ImportError:
        logger.debug("xterm.js terminal not available (QtWebEngine not found)")
        return None
    except Exception as exc:
        logger.debug("xterm.js terminal failed to initialize: %s", exc)
        return None


def _try_native(shell, cwd, font_size, parent):
    """
    Attempt to create the native QPlainTextEdit terminal widget.

    Works on Windows with or without pywinpty:
        - **With pywinpty**: Full PTY support (ANSI colors, interactive programs).
        - **Without pywinpty**: Subprocess pipe fallback (line-oriented tools
          like pip, git, python, Claude Code work fine; no full-screen programs).

    :param str shell: Shell path.
    :param str cwd: Working directory.
    :param int font_size: Font size.
    :param QWidget parent: Parent widget.
    :return: Widget instance, or *None* on failure.
    :rtype: TerminalWidget or None
    """
    # Platform check — currently Windows-only (pywinpty is Windows-only,
    # and the subprocess fallback uses CREATE_NO_WINDOW).
    if platform.system() != "Windows":
        logger.debug("Native terminal not available (Windows-only, current: %s)",
                      platform.system())
        return None

    # Create the widget.  No pywinpty check here — the backend has a
    # subprocess pipe fallback that works without it (TERM=dumb mode).
    try:
        from mca_qt.widgets.terminal_native import TerminalWidget
        return TerminalWidget(
            shell=shell, cwd=cwd, font_size=font_size, parent=parent,
        )
    except Exception as exc:
        logger.debug("Native terminal failed to initialize: %s", exc)
        return None


# --- Internal: Environment Detection ------------------------------------------

def _is_maya():
    """
    Check whether we're running inside Autodesk Maya.

    Uses the ``maya.cmds`` import as the definitive signal — this module
    only exists in Maya's embedded Python interpreter.

    :return: *True* if running inside Maya.
    :rtype: bool
    """
    try:
        import maya.cmds  # noqa: F401
        return True
    except ImportError:
        return False
