# Integration Guide — Venv Manager & Dual Terminal
# =================================================
#
# This guide tells you exactly what to change in the existing MCA Editor
# codebase to wire up the new venv_manager.py and terminal_factory.py.
#
# New files to add (already written):
#   mca_core/venv_manager.py
#   mca_qt/widgets/terminal_factory.py
#
# Existing files to modify (6 files):
#   mca_maya/plugin_main.py
#   mca_standalone/main.py
#   mca_qt/editor_panel.py
#   mca_qt/widgets/terminal_widget.py  (rename to terminal_native.py)
#   mca_qt/widgets/xterm_widget.py     (rename to terminal_xterm.py)
#   build_maya.py


# =====================================================================
# 1. FILE RENAMES
# =====================================================================
#
# Rename these two files. No content changes needed for the rename itself,
# but import paths inside them need updating (see section 4 below).
#
#   mca_qt/widgets/terminal_widget.py  →  mca_qt/widgets/terminal_native.py
#   mca_qt/widgets/xterm_widget.py     →  mca_qt/widgets/terminal_xterm.py


# =====================================================================
# 2. mca_maya/plugin_main.py — Add venv setup to initializePlugin
# =====================================================================
#
# Add venv setup as the FIRST thing in initializePlugin(), before any
# other MCA imports that might need third-party packages.
#
# At the top of the file, add this import:

#   from mca_core import venv_manager

# Then at the start of initializePlugin(), before the existing code:

#   def initializePlugin(plugin):
#       # --- Set up managed venv (installs dependencies on first run) ---
#       venv_ok = venv_manager.setup()
#       if not venv_ok:
#           logger.warning(
#               "MCA Editor venv setup incomplete — some features may be "
#               "unavailable. Use Help > Repair Installation to fix."
#           )
#
#       # ... existing plugin initialization code follows ...


# =====================================================================
# 3. mca_standalone/main.py — Add venv setup before QApplication
# =====================================================================
#
# Add venv setup early in the main() function, BEFORE creating the
# QApplication. This ensures packages like pyflakes are available
# when the editor panel initializes.
#
# At the top of the file, add:

#   from mca_core import venv_manager

# Then early in main(), before `app = QApplication(sys.argv)`:

#   def main():
#       # --- Set up managed venv ---
#       venv_manager.setup()
#
#       app = QApplication(sys.argv)
#       # ... rest of existing code ...


# =====================================================================
# 4. mca_qt/editor_panel.py — Use terminal factory instead of direct import
# =====================================================================
#
# REMOVE the existing terminal import. It currently looks like one of:
#
#   from mca_qt.widgets.xterm_widget import TerminalWidget
#   or
#   from .widgets.xterm_widget import TerminalWidget
#
# REPLACE with:
#
#   from mca_qt.widgets.terminal_factory import create_terminal_widget
#
# Then in __init__(), where the terminal widget is created (somewhere
# near the center_splitter setup), REPLACE:
#
#   self._terminal = TerminalWidget(self)
#
# WITH:
#
#   self._terminal = create_terminal_widget(parent=self)
#
# And everywhere that references self._terminal, add a None guard.
# The key places are:
#
# a) Where terminal is added to the center_splitter:
#
#   if self._terminal is not None:
#       self._center_splitter.addWidget(self._terminal)
#       self._terminal.hide()
#
# b) In _toggle_terminal():
#
#   def _toggle_terminal(self):
#       if self._terminal is None:
#           return
#       # ... existing toggle logic ...
#
# c) In cleanup() / save_window_state():
#
#   if self._terminal is not None:
#       self._terminal.terminate()
#
# d) In the View menu builder, conditionally hide the terminal entry:
#
#   terminal_action = self._create_action("Toggle Terminal", ...)
#   if self._terminal is None:
#       terminal_action.setEnabled(False)
#       terminal_action.setText("Terminal (unavailable)")
#
# e) Where terminal visibility is restored from settings:
#
#   if self._terminal is not None:
#       if settings.get("terminal_visible", False):
#           # ... existing restore logic ...


# =====================================================================
# 5. terminal_native.py — Update imports after rename
# =====================================================================
#
# After renaming terminal_widget.py → terminal_native.py, check that
# the internal imports use the correct paths:
#
# - Import from terminal_backend.py should use relative import:
#     from .terminal_backend import TerminalBackend
#
# - Import from ansi_parser.py should use relative import:
#     from .ansi_parser import AnsiParser
#
# - Qt imports should come from mca_qt.qt_compat (they may already,
#   but verify):
#     from mca_qt.qt_compat import (
#         QPlainTextEdit, QWidget, QVBoxLayout, QTimer, QFont,
#         QFontMetricsF, QMenu, QApplication, Qt, Signal
#     )
#
# - The class should still be named TerminalWidget (the factory imports
#   it by that name):
#     class TerminalWidget(QWidget):
#
# Also add a fallback message when the backend fails to start. In the
# start() method (or wherever the PTY is spawned), if the backend raises
# an exception, show a message in the widget:
#
#   def start(self, shell=None, cwd=None, env=None, cols=80, rows=24):
#       try:
#           self._backend.start(shell, cols, rows, cwd, env)
#       except Exception as exc:
#           logger.error("Terminal backend failed to start: %s", exc)
#           self._show_error_message(
#               "Terminal unavailable.\n\n"
#               "The terminal backend failed to start. This usually means\n"
#               "pywinpty is not installed correctly.\n\n"
#               "Try: Help > Repair Installation"
#           )
#           return
#
#   def _show_error_message(self, text):
#       """Display an error message in the terminal area instead of a blank widget."""
#       self._display.setPlainText(text)
#       self._display.setReadOnly(True)


# =====================================================================
# 6. terminal_xterm.py — Update imports after rename
# =====================================================================
#
# After renaming xterm_widget.py → terminal_xterm.py, the internal
# imports should already be correct (they reference terminal_backend.py
# by relative import). Just verify:
#
#   from .terminal_backend import TerminalBackend
#
# The HAS_WEBENGINE flag and conditional import at the top of the file
# can be simplified since the factory already handles the ImportError.
# But it's not strictly necessary to change — leaving it is fine.


# =====================================================================
# 7. build_maya.py — Include native terminal, exclude xterm assets
# =====================================================================
#
# In the packaging step where files are copied to dist/, ensure:
#
# INCLUDE in Maya dist:
#   mca_qt/widgets/terminal_backend.py
#   mca_qt/widgets/terminal_native.py     (was terminal_widget.py)
#   mca_qt/widgets/ansi_parser.py
#   mca_qt/widgets/terminal_factory.py
#   mca_core/venv_manager.py
#
# EXCLUDE from Maya dist (not usable without QtWebEngine):
#   mca_qt/widgets/terminal_xterm.py      (was xterm_widget.py)
#   resources/terminal/                    (xterm.js assets)
#
# Also add venv_manager.py to the Cython compilation list in setup.py
# if it's not auto-discovered.


# =====================================================================
# 8. mca_qt/widgets/__init__.py — Update exports
# =====================================================================
#
# Replace any existing terminal imports with the factory:
#
#   from .terminal_factory import create_terminal_widget, is_terminal_available
#
# Remove direct imports of TerminalWidget (the factory handles selection).


# =====================================================================
# 9. requirements.txt — pywinpty is now managed by venv
# =====================================================================
#
# pywinpty can be removed from the top-level requirements.txt since it's
# now installed into the managed venv by venv_manager.py. The standalone
# app's own venv will also get it through venv_manager.setup().
#
# Keep PySide6 and PySide6-WebEngine in requirements.txt since those are
# needed by the standalone app itself (not managed by our venv).


# =====================================================================
# TESTING CHECKLIST
# =====================================================================
#
# Standalone:
#   [ ] python run.py — launches without errors
#   [ ] Ctrl+` — opens xterm.js terminal (QtWebEngine available)
#   [ ] Terminal shows shell prompt, accepts input
#   [ ] Close and reopen — terminal visibility persists
#
# Maya:
#   [ ] Load plugin — venv created at ~/mca_preferences/.venv/
#   [ ] pywinpty installed in venv (check .venv/Lib/site-packages/winpty/)
#   [ ] Ctrl+` — opens native terminal (QPlainTextEdit)
#   [ ] Terminal shows shell prompt after ~3-4 second startup delay
#   [ ] Keyboard input works (type commands, arrow keys, Ctrl+C, Tab)
#   [ ] No dead cursor / blank widget like before
#   [ ] Close Maya, reopen, load plugin — no reinstall, fast startup
#
# Missing dependencies:
#   [ ] Delete .venv, remove pywinpty, open in Maya
#   [ ] Terminal menu entry shows "Terminal (unavailable)"
#   [ ] Ctrl+` does nothing (no crash, no blank widget)
#   [ ] Help > Repair Installation recreates venv and restores terminal
#
# Edge cases:
#   [ ] No internet during first launch — venv created but pip fails gracefully
#   [ ] Corrupted venv — Repair Installation recovers cleanly
#   [ ] Multiple Maya versions — each creates its own compatible venv
#       Maya 2024 (Python 3.10) → .venv-3.10/
#       Maya 2025 (Python 3.11) → .venv-3.11/
#       Standalone (Python 3.12) → .venv-3.12/
#       (This is handled automatically by venv_manager.get_venv_dir())
