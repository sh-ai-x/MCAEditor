"""
MCA Maya - Dockable Maya Window.

Hosts the MCAEditorPanel inside a Maya-native dockable window using
``MayaQWidgetDockableMixin``. Survives Maya layout save/restore via
the ``uiScript`` workspace control pattern.

When opened, the InternalMayaAdapter is pre-connected (always alive),
so code execution goes directly through maya.cmds / maya.mel without
TCP sockets.

Dependencies:
    - maya.cmds (workspace control management)
    - maya.app.general.mayaMixin (MayaQWidgetDockableMixin)
    - PySide6 or PySide2 (Qt bindings, provided by Maya)
    - mca_qt.qt_compat (widget imports)
    - mca_qt.editor_panel (MCAEditorPanel)
    - mca_qt.theme (dark stylesheet)
    - mca_core.config.settings (MCASettings)
    - mca_core.adapters (AdapterManager, InternalMayaAdapter)
"""

import logging
import struct
import sys
import traceback

import maya.cmds as cmds
import maya.api.OpenMaya as om2
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

# QObject/QEvent/QApplication imported directly from PySide rather than
# qt_compat — avoids stale module cache issues when reloading inside Maya.
try:
    from PySide6.QtCore import QObject, QEvent
    from PySide6.QtWidgets import QApplication, QWidget as _QWidget
except ImportError:
    from PySide2.QtCore import QObject, QEvent
    from PySide2.QtWidgets import QApplication, QWidget as _QWidget

from mca_qt.qt_compat import QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QLabel, QFrame, QDialog, Qt, QTimer, QKeySequence, QPixmap
from mca_qt.editor_panel import MCAEditorPanel
from mca_qt.icons import mca_logo
from mca_qt.theme import GLOBAL_STYLESHEET
from mca_core.config.settings import MCASettings
from mca_core.adapters.adapter_manager import AdapterManager
from mca_core.adapters.internal_maya_adapter import InternalMayaAdapter

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Silence MCA INFO/DEBUG Logging in Maya ---------------------------------
# Every mca_* module uses logging.getLogger(__name__), so their loggers are
# children of "mca_core", "mca_qt", and "mca_maya".  Setting these parent
# loggers to WARNING suppresses all routine INFO/DEBUG messages (window opened,
# terminal started, session restored, etc.) that would otherwise flood the
# output panel via Maya's output hook.  Warnings and errors still come through.
#
# This must live here (not just in plugin_main.py) because the user may launch
# the editor directly via  show_mca_editor()  without going through the plugin
# system, in which case plugin_main.py is never imported.
#
# To re-enable verbose output for debugging, run in Maya's script editor:
#     import logging; logging.getLogger("mca_core").setLevel(logging.DEBUG)
#     import logging; logging.getLogger("mca_qt").setLevel(logging.DEBUG)
#     import logging; logging.getLogger("mca_maya").setLevel(logging.DEBUG)
for _pkg in ("mca_core", "mca_qt", "mca_maya"):
    logging.getLogger(_pkg).setLevel(logging.WARNING)

# Widget object name — Maya appends "WorkspaceControl" to derive the
# workspace control name, so the control becomes "MCAEditorWorkspaceControl".
WINDOW_OBJECT_NAME = "MCAEditor"

# Maya auto-generates this from WINDOW_OBJECT_NAME + "WorkspaceControl".
WORKSPACE_CONTROL_NAME = WINDOW_OBJECT_NAME + "WorkspaceControl"

# Module-level reference to keep the window alive (prevent GC).
_mca_editor_window = None

# Module-level Maya output callback ID.  Stored here (not on the window
# instance) so it survives window recreation.  When Maya calls the
# uiScript repeatedly during layout restore, the old window is
# overwritten — if the callback ID were on the instance, we'd lose the
# handle and could never remove the stale callback.
_output_callback_id = None

# Module-level reference to the stderr tee wrapper.  Stored at module
# level so it survives window recreation (same reason as the callback ID).
_stderr_tee = None

# Module-level reference to the stdout tee wrapper.  Captures ALL
# Python print() output for the output panel — including output from
# deferred callbacks, framework startup, and module imports that run
# outside of the adapter's exec() call.  MCommandMessage does NOT fire
# kDisplay for print() from directly exec'd Python code, so this tee
# is the sole capture mechanism for Python stdout.
_stdout_tee = None

# Module-level output target — the OutputWindow widget that all three
# capture mechanisms (MCommandMessage, _StdoutTee, _StderrTee) write to.
# Updated by _install_output_hook() when a new window is created, and
# cleared by dockCloseEventTriggered() / cleanup_editor() when the window
# is destroyed.  When None, the tees silently no-op instead of crashing
# on a dead C++ widget reference.
_output_target = None

class _StderrTee:
    """
    Wrapper around sys.stderr that tees writes to the MCA output panel.

    Python's ``logging`` module writes to sys.stderr by default.  Maya's
    ``MCommandMessage.addCommandOutputCallback`` only captures Maya's own
    output system (MEL echo, print(), cmds warnings) — it never sees
    raw stderr writes.  This tee bridges the gap so logging output from
    other frameworks (e.g. the MCA framework's ``[MCA - Module:...]``
    lines) appears in our editor's output window alongside Maya's output.

    The original stderr object is preserved and all writes are forwarded
    to it first, so Maya's Script Editor and console still work normally.

    :param object original: The original sys.stderr object to wrap.
    """

    def __init__(self, original):
        """
        Initialize the tee with the original stderr.

        The output target is read from the module-level ``_output_target``
        on each write, so the tee survives window recreation without
        needing to be reinstalled.

        :param object original: The original sys.stderr.
        """
        self._original = original

    def write(self, text):
        """
        Write to both the original stderr and our output panel.

        :param str text: Text to write.
        """
        # Always forward to the original so Maya's own stderr handling works.
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass

        # Skip empty or whitespace-only writes.
        if not text or not text.strip():
            return

        # Route to our output panel via the module-level target.
        # When the target is None (editor closed but tee still installed),
        # the write silently no-ops instead of crashing on a dead widget.
        target = _output_target
        if target is None:
            return
        try:
            stripped = text.rstrip()
            # Detect error/warning patterns from logging output.
            if "ERROR:" in stripped or "Error:" in stripped:
                target.write_error(stripped)
            elif "WARNING:" in stripped or "Warning:" in stripped:
                target.write_warning(stripped)
            else:
                target.write_output(stripped)
        except (RuntimeError, AttributeError):
            # Output widget already deleted — ignore silently.
            pass

    def flush(self):
        """Flush the original stderr."""
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def __getattr__(self, name):
        """
        Forward any attribute access to the original stderr.

        Ensures compatibility with code that checks stderr attributes
        (e.g. ``encoding``, ``fileno()``, ``isatty()``).

        :param str name: Attribute name.
        :return: The attribute from the original stderr.
        """
        return getattr(self._original, name)


class _StdoutTee:
    """
    Wrapper around sys.stdout that tees writes to the MCA output panel.

    MCommandMessage does NOT capture Python ``print()`` output from
    directly ``exec()``'d code — it only fires for Maya's C++ command
    system output (MEL echo, ``cmds.warning()``, etc.).  This tee
    bridges the gap so ALL Python stdout output (``print()`` calls,
    framework startup logs, deferred callbacks) appears in our editor's
    output window alongside Maya's native output.

    The original stdout object (Maya's ``OutputRedirector``) is preserved
    and all writes are forwarded to it first, so Maya's Script Editor
    and console still work normally.

    :param object original: The original sys.stdout object to wrap.
    """

    def __init__(self, original):
        """
        Initialize the tee with the original stdout.

        The output target is read from the module-level ``_output_target``
        on each write, so the tee survives window recreation without
        needing to be reinstalled.

        :param object original: The original sys.stdout.
        """
        self._original = original

    def write(self, text):
        """
        Write to both the original stdout and our output panel.

        :param str text: Text to write.
        """
        # Always forward to the original so Maya's Script Editor works.
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass

        # Skip empty or whitespace-only writes.
        if not text or not text.strip():
            return

        # Route to our output panel via the module-level target.
        # When the target is None (editor closed but tee still installed),
        # the write silently no-ops instead of crashing on a dead widget.
        target = _output_target
        if target is None:
            return
        try:
            stripped = text.rstrip()
            # Detect result-formatted output from the internal adapter.
            # "# Result: <value> #" is printed for eval'd expressions.
            if stripped.startswith("# Result:") and stripped.endswith("#"):
                target.write_result(stripped)
            else:
                target.write_output(stripped)
        except (RuntimeError, AttributeError):
            # Output widget already deleted — ignore silently.
            pass

    def flush(self):
        """Flush the original stdout."""
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                pass

    def __getattr__(self, name):
        """
        Forward any attribute access to the original stdout.

        Ensures compatibility with code that checks stdout attributes
        (e.g. ``encoding``, ``fileno()``, ``isatty()``).

        :param str name: Attribute name.
        :return: The attribute from the original stdout.
        """
        return getattr(self._original, name)


# --- Maya Output Callback (module-level) ------------------------------------

def _on_maya_output(message, message_type, client_data):
    """
    Callback fired by Maya for every line of command output.

    Registered via ``MCommandMessage.addCommandOutputCallback`` and called
    at module level (not as an instance method) so it survives window
    recreation.  Writes to the module-level ``_output_target`` which is
    updated whenever a new editor window is created.

    Routes messages to the appropriate output window method based
    on the message type, with color coding for errors, warnings,
    results, and info.

    NO content filtering is applied — every message that appears
    in Maya's Script Editor also appears here.  The only exception
    is the ``cutCopyPaste.mel`` artifact which is caused by MCA
    Editor's hotkey handling, not by user code.

    :param str message: The output text from Maya.
    :param int message_type: MCommandMessage message type constant.
    :param object client_data: Unused client data from Maya.
    """
    # Skip empty messages.
    if not message or not message.strip():
        return

    # Bail early if there's no output target (editor closed).
    target = _output_target
    if target is None:
        return

    # Suppress the harmless "Nothing is selected" error from Maya's
    # cutCopyPaste.mel — this fires when Ctrl+C/X leaks to Maya
    # during focus transitions and nothing is selected in the viewport.
    # This is an MCA Editor artifact, not real Maya output.
    if "cutCopyPaste.mel" in message and "Nothing is selected" in message:
        return

    # Guard against the output widget being destroyed (C++ side)
    # while this callback is still registered.  Happens when the
    # editor window is torn down but Maya output keeps firing.
    # An unhandled RuntimeError here cascades through Maya's callback
    # dispatch and can crash the entire session.
    try:
        text = message.rstrip()

        # Route to the appropriate output method based on message type.
        # Color coding: red for errors, orange for warnings, yellow for
        # results, blue for info, white for display (print output).
        if message_type == om2.MCommandMessage.kError:
            target.write_error(text)

        elif message_type == om2.MCommandMessage.kWarning:
            target.write_warning(text)

        elif message_type == om2.MCommandMessage.kResult:
            target.write_result(text)

        elif message_type == om2.MCommandMessage.kInfo:
            target.write_info(text)

        else:
            # kDisplay — MEL echo and Maya C++ output.
            #
            # Python print() output is captured separately by the
            # permanent _StdoutTee (MCommandMessage does NOT fire
            # kDisplay for print() from exec'd Python code).  So
            # kDisplay here only contains MEL echo, command output,
            # and other Maya C++ system messages — no dedup needed.
            #
            # Detect result-formatted output from our internal adapter.
            # Maya's C++ displayResult (kResult) is not exposed in
            # Python API 2.0, so the adapter prints results as
            # "# Result: <value> #" via print().  Detect that pattern
            # and route to write_result() for proper result coloring.
            stripped = text.strip()
            if stripped.startswith("# Result:") and stripped.endswith("#"):
                target.write_result(text)
            else:
                target.write_output(text)

        # Force-flush and repaint immediately so output appears in
        # real-time during code execution.  Without this, the 16ms
        # QTimer can't fire while exec() blocks the event loop, and
        # all output would dump at once when execution finishes.
        target.flush()

    except Exception:
        # Widget already deleted or other error — silently ignore.
        # Must catch broadly: RuntimeError from shiboken (dead C++ object),
        # AttributeError if panel is partially torn down, etc.
        # An unhandled exception here cascades through Maya's callback
        # dispatcher and can crash the session or silently remove
        # the callback, killing all future output capture.
        pass


# --- Hotkey Suppression Filter ----------------------------------------------

class _MayaHotkeyFilter(QObject):
    """
    Application-level event filter that completely isolates the MCA
    Editor's keyboard input from Maya's hotkey system.

    Maya's hotkeys bypass Qt's shortcut matching entirely — they use a
    custom MEL-based system that intercepts events before Qt's QAction
    shortcuts can fire. Neither ``ShortcutOverride`` acceptance alone
    nor ``WidgetWithChildrenShortcut`` context is enough to beat them.

    Strategy (two-phase interception):

    **Phase 1 — ShortcutOverride**: Accept ALL override events when our
    editor has focus. This tells Qt to deliver a normal ``KeyPress``
    instead of a shortcut, completely blocking Maya's hotkey system.

    **Phase 2 — KeyPress**: Since we blocked all shortcuts in phase 1,
    modifier combos (Ctrl+D, Ctrl+N, etc.) arrive as regular KeyPress
    events. We match them against the panel's action registry and
    trigger the matching action manually. Plain keys (typing) pass
    through to the focused widget's ``keyPressEvent`` normally.

    Built-in text editing shortcuts (Ctrl+Z, Ctrl+C, Ctrl+V, Ctrl+X,
    Ctrl+A) are handled by QPlainTextEdit's ``keyPressEvent``, so they
    still work even though we blocked the shortcut system.

    :param QWidget target: The MCAMayaWindow instance.
    :param MCAEditorPanel panel: The editor panel with the action registry.
    """

    def __init__(self, target, panel):
        """
        Initialize the filter.

        :param QWidget target: The MCAMayaWindow instance.
        :param MCAEditorPanel panel: The editor panel containing the
            action registry used for manual shortcut dispatch.
        """
        super().__init__(target)
        self._target = target
        self._panel = panel

    def _focus_in_editor(self):
        """
        Check if the currently focused widget belongs to our editor.

        Uses QApplication.focusWidget() instead of the event's watched
        object because the app-level filter sees events for QWindows
        and other non-QWidget objects.

        :return: True if focus is in our editor widget tree.
        :rtype: bool
        """
        app = QApplication.instance()
        if not app:
            return False
        focus = app.focusWidget()
        if not focus or not isinstance(focus, _QWidget):
            return False
        return focus is self._target or self._target.isAncestorOf(focus)

    def _widget_in_editor(self, widget):
        """
        Check whether *widget* belongs to our editor's widget tree.

        Unlike ``_focus_in_editor()`` (which relies on the global focus
        widget), this tests a specific widget directly. Useful for mouse
        events where the click target is known but Qt focus has not yet
        transferred.

        :param QObject widget: The widget to test.
        :return: True if *widget* is our target or a descendant of it.
        :rtype: bool
        """
        if not widget or not isinstance(widget, _QWidget):
            return False
        return widget is self._target or self._target.isAncestorOf(widget)

    def _find_matching_action(self, key_event):
        """
        Find a panel action whose shortcut matches the given key event.

        Builds a QKeySequence from the event and compares its string
        representation against each registered action's shortcut.
        String comparison is portable across PySide2 and PySide6.

        :param QKeyEvent key_event: The key press event to match.
        :return: The matching QAction, or None if no match.
        :rtype: QAction or None
        """
        # Build a QKeySequence from the key event.
        # PySide6 has keyCombination(), PySide2 needs int(modifiers)|key.
        try:
            key_seq = QKeySequence(key_event.keyCombination())
        except AttributeError:
            key_seq = QKeySequence(int(key_event.modifiers()) | key_event.key())

        seq_str = key_seq.toString()

        # Check all registered actions for a matching shortcut.
        for action in self._panel._action_registry.values():
            shortcut = action.shortcut()
            if not shortcut.isEmpty() and shortcut.toString() == seq_str:
                return action

        return None

    def _find_parent_terminal(self, widget):
        """
        Walk up the widget parent chain looking for a TerminalWidget.

        :param QWidget widget: The starting widget (usually the focused child).
        :return: The TerminalWidget ancestor, or None.
        :rtype: QWidget or None
        """
        try:
            from mca_qt.widgets.terminal_native import TerminalWidget
        except ImportError:
            return None
        parent = widget
        while parent:
            if isinstance(parent, TerminalWidget):
                return parent
            parent = parent.parent() if hasattr(parent, "parent") else None
        return None

    def eventFilter(self, watched, event):
        """
        Two-phase keyboard interception for Maya hotkey suppression.

        Phase 1: Accept all ShortcutOverride events (blocks Maya).
        Phase 2: Dispatch modifier-key KeyPress events to our actions.

        :param QObject watched: The object receiving the event.
        :param QEvent event: The Qt event.
        :return: True if the event was consumed, False otherwise.
        :rtype: bool
        """
        # --- Phase 0: Force focus on first click into our editor -----------
        # When the user clicks into our editor from Maya's viewport, Qt
        # does not always transfer keyboard focus immediately — the click
        # registers on the child widget, but focusWidget() still returns
        # the previous Maya widget.  Any keyboard shortcut fired in that
        # gap (e.g. Ctrl+C from Maya's cutCopyPaste.mel) will bypass our
        # filter because _focus_in_editor() returns False.
        #
        # Fix: intercept MouseButtonPress events targeting any widget in
        # our tree.  First activate the top-level window so Qt considers
        # it the active window, then setFocus() on the clicked child so
        # focus is transferred BEFORE any subsequent key events arrive.
        if event.type() == QEvent.Type.MouseButtonPress:
            if isinstance(watched, _QWidget):
                if self._widget_in_editor(watched):
                    # Click inside our editor — claim keyboard ownership.
                    # Activate the top-level window first — setFocus() has
                    # no effect if the window isn't active (common when
                    # clicking from Maya's viewport into a docked panel).
                    top = self._target.window()
                    if top:
                        top.activateWindow()

                    # Find the appropriate focus target.
                    focus_target = watched
                    # Walk to a focusable widget if the clicked widget doesn't
                    # accept focus (e.g. a QFrame layout or a viewport).
                    # QAbstractScrollArea viewports (QPlainTextEdit, QScrollArea)
                    # are QWidgets with NoFocus policy — the focusable widget
                    # is the PARENT scroll area.  Try parent first, then proxy,
                    # then children.
                    if focus_target.focusPolicy() == Qt.FocusPolicy.NoFocus:
                        # Try the parent widget first — handles viewports of
                        # QPlainTextEdit / QScrollArea / QAbstractScrollArea.
                        parent_w = focus_target.parentWidget()
                        if parent_w and parent_w.focusPolicy() != Qt.FocusPolicy.NoFocus:
                            focus_target = parent_w
                        elif focus_target.focusProxy():
                            focus_target = focus_target.focusProxy()
                        else:
                            # Last resort — walk children for the first
                            # widget that accepts focus (depth-first).
                            for c in focus_target.findChildren(_QWidget):
                                if c.focusPolicy() != Qt.FocusPolicy.NoFocus:
                                    focus_target = c
                                    break

                    focus_target.setFocus(Qt.FocusReason.MouseFocusReason)
                    # Mark that we own keyboard focus.  Only cleared by
                    # an explicit click OUTSIDE our tree (below).
                    self._focus_forced = True
                    # Store the widget we set focus on so Phase 2 can
                    # use it as a fallback if focusWidget() hasn't
                    # caught up yet (activateWindow is async on Win11).
                    self._focus_forced_widget = focus_target
                else:
                    # Click outside our editor — release keyboard ownership.
                    self._focus_forced = False

        # --- Phase 1: Block Maya's hotkey system entirely ---
        if event.type() == QEvent.Type.ShortcutOverride:
            # Check the regular focus test AND the forced-focus flag.
            # _focus_forced is managed by focusChanged (set when focus
            # enters our editor tree, cleared when it leaves).  We do
            # NOT clear it here — that caused a first-press bug where
            # Ctrl+C in the output window leaked to Maya because the
            # flag was consumed before Phase 2 could use it.
            if self._focus_in_editor() or getattr(self, "_focus_forced", False):
                # Accept ALL shortcut overrides. This prevents Maya's
                # hotkey system from seeing any key while our editor
                # has focus. The key will arrive as a normal KeyPress.
                event.accept()
                return True

        # --- Phase 2: Manually dispatch modifier combos to our actions ---
        if event.type() == QEvent.Type.KeyPress:
            if self._focus_in_editor() or getattr(self, "_focus_forced", False):
                key = event.key()

                # Skip pure modifier key presses (Ctrl, Shift, Alt, Meta
                # pressed alone — no actual key to match).
                if key in (
                    Qt.Key.Key_Control, Qt.Key.Key_Shift,
                    Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                ):
                    return super().eventFilter(watched, event)

                # Only try action matching for keys with Ctrl/Alt/Meta.
                # Plain keys and Shift+key are regular typing and should
                # pass through to the text editor's keyPressEvent.
                modifiers = event.modifiers()
                has_action_modifier = modifiers & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )

                if has_action_modifier:
                    action = self._find_matching_action(event)
                    if action and action.isEnabled():
                        action.trigger()
                        return True

                    # No matching editor action, but we MUST still consume
                    # the event to prevent it from propagating up the widget
                    # tree to Maya's main window (where Maya would process
                    # it as a hotkey like Ctrl+G = Group, etc.).
                    #
                    # For terminal widgets, the key handling lives in the
                    # TerminalWidget's eventFilter (not in the
                    # QPlainTextEdit's keyPressEvent), so we need to find
                    # the terminal parent and route through its eventFilter.
                    # For regular text editors, invoke standard clipboard /
                    # undo methods directly rather than routing through
                    # keyPressEvent — this avoids issues where focusWidget()
                    # hasn't caught up after activateWindow() on Win11.
                    focus = QApplication.instance().focusWidget()

                    # Fallback: if focusWidget() returns None or a widget
                    # outside our editor (focus hasn't transferred yet),
                    # use the widget we tried to focus in Phase 0.
                    if not focus or not self._widget_in_editor(focus):
                        focus = getattr(self, "_focus_forced_widget", None)

                    if focus:
                        # Walk up the parent chain looking for a terminal.
                        terminal = self._find_parent_terminal(focus)
                        try:
                            if terminal:
                                # Route through the terminal's eventFilter which
                                # handles Ctrl+V paste, Ctrl+C interrupt, etc.
                                # Pass terminal._display (not `focus`) because
                                # the eventFilter checks `if obj is self._display:`
                                # and rejects any other object.
                                terminal.eventFilter(terminal._display, event)
                            else:
                                # Standard text editing shortcuts — call the
                                # method directly for maximum reliability.
                                # Going through keyPressEvent can fail if focus
                                # hasn't fully transferred on the first click.
                                method_name = None
                                ctrl_only = (modifiers == Qt.KeyboardModifier.ControlModifier)
                                ctrl_shift = (modifiers == (
                                    Qt.KeyboardModifier.ControlModifier
                                    | Qt.KeyboardModifier.ShiftModifier
                                ))
                                if ctrl_only:
                                    method_name = {
                                        Qt.Key.Key_C: "copy",
                                        Qt.Key.Key_V: "paste",
                                        Qt.Key.Key_X: "cut",
                                        Qt.Key.Key_A: "selectAll",
                                        Qt.Key.Key_Z: "undo",
                                        Qt.Key.Key_Y: "redo",
                                    }.get(key)
                                elif ctrl_shift and key == Qt.Key.Key_Z:
                                    # Ctrl+Shift+Z = redo on most platforms.
                                    method_name = "redo"
                                if method_name and hasattr(focus, method_name):
                                    getattr(focus, method_name)()
                                elif hasattr(focus, "keyPressEvent"):
                                    # Not a standard text op — fall back to
                                    # keyPressEvent for everything else.
                                    focus.keyPressEvent(event)
                        except RuntimeError:
                            # The focused widget's C++ object was deleted between
                            # the focusWidget() call and the dispatch.  This
                            # happens when tabs close or widgets rebuild mid-event.
                            pass
                    return True

        return super().eventFilter(watched, event)


# --- MCA Maya Window --------------------------------------------------------

class MCAMayaWindow(MayaQWidgetDockableMixin, QWidget):
    """
    Maya-native dockable window wrapping MCAEditorPanel.

    Uses ``MayaQWidgetDockableMixin`` so the editor can be docked into
    Maya's layout like any built-in panel. Implements the ``uiScript``
    pattern for workspace control persistence -- Maya can recreate this
    panel on layout restore.

    The InternalMayaAdapter is pre-registered and active, so code runs
    directly in Maya's interpreter without needing a TCP connection.

    :param QWidget parent: Optional parent widget (usually None for Maya).
    """

    def __init__(self, parent=None):
        """
        Initialize the dockable MCA Editor window.

        Sets up the InternalMayaAdapter (direct maya.cmds execution),
        creates the MCAEditorPanel, builds menus, and applies styling.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)

        # Object name must match WINDOW_OBJECT_NAME so Maya derives the
        # correct workspace control name (WINDOW_OBJECT_NAME + "WorkspaceControl").
        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle("MCA Editor")
        self.setWindowIcon(mca_logo(size=32))

        # Load settings (QSettings-backed inside Maya).
        self._settings = MCASettings()

        # Create an adapter manager without the built-in TCP adapter, since
        # we're running inside Maya and don't need socket communication.
        self._adapter_manager = AdapterManager(register_builtin=False)

        # Register the internal adapter (direct maya.cmds calls).
        # This adapter is always connected — we ARE Maya.
        internal_adapter = InternalMayaAdapter()
        self._adapter_manager.register_adapter_instance("maya_internal", internal_adapter)

        # Create the editor panel with the pre-connected adapter manager.
        self._panel = MCAEditorPanel(
            self._settings,
            adapter_manager=self._adapter_manager,
            parent=self,
        )

        # Build a title bar with the MCA logo, title text, and menu bar.
        self._title_bar = QWidget(self)
        self._title_bar.setFixedHeight(26)
        self._title_bar.setStyleSheet("background-color: #252526;")
        title_bar_layout = QHBoxLayout(self._title_bar)
        title_bar_layout.setContentsMargins(6, 0, 0, 0)
        title_bar_layout.setSpacing(4)

        # Logo icon (20x20 scaled from mca.png).
        logo_label = QLabel()
        logo_pixmap = mca_logo(size=20).pixmap(20, 20)
        logo_label.setPixmap(logo_pixmap)
        logo_label.setFixedSize(20, 20)
        title_bar_layout.addWidget(logo_label)

        # "MCA Editor" title text next to the logo.
        title_label = QLabel("MCA Editor")
        title_label.setStyleSheet(
            "color: #cccccc; font-size: 12px; font-weight: bold; padding-left: 2px;"
        )
        title_bar_layout.addWidget(title_label)

        # Menu bar fills the remaining space.
        self._menubar = QMenuBar(self)
        self._panel.build_menus(self._menubar)
        title_bar_layout.addWidget(self._menubar, 1)

        # Apply our dark stylesheet on top of Maya's theme.
        self.setStyleSheet(GLOBAL_STYLESHEET)

        # Set up the panel's status callback to print to Maya's script editor.
        self._panel.set_status_callback(self._maya_status_callback)

        # Build the blue status bar that mirrors the standalone window.
        self._status_bar = self._build_status_bar()

        # Layout: title bar on top, panel fills the middle, status bar at bottom.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title_bar, 0)  # 0 stretch — stays at natural height.
        layout.addWidget(self._panel, 1)       # 1 stretch — expands to fill space.
        layout.addWidget(self._status_bar, 0)  # 0 stretch — stays at natural height.

        # Connect panel signals to the status bar labels.
        self._panel.cursor_position_changed.connect(self._on_cursor_pos)
        self._panel.language_changed.connect(self._on_language_changed)
        self._panel.mode_changed.connect(self._on_mode_changed)
        self._panel.status_message.connect(self._on_status_message)
        self._panel.output_counts_changed.connect(self._on_counts_changed)
        self._panel.index_status_changed.connect(self._on_index_status)
        self._panel.activity_bar_toggled.connect(self._toggle_status_bar)

        # Install an application-level event filter to prevent Maya's
        # hotkeys from intercepting keystrokes while typing in our editor.
        # Without this, pressing 'S' triggers Maya's "Set Key" instead of
        # typing the letter, 'W' switches to Move Tool, Ctrl+D duplicates, etc.
        self._hotkey_filter = _MayaHotkeyFilter(self, self._panel)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self._hotkey_filter)

            # Listen for global focus changes so we can set _focus_forced
            # whenever focus enters our editor tree.  On the very first
            # interaction (clicking into the docked panel from Maya's
            # viewport), Qt may not update focusWidget() fast enough for
            # Phase 1 to detect it.  The focusChanged signal fires
            # reliably, giving us a safety net so Phase 1 always accepts
            # ShortcutOverride and Maya's hotkeys don't steal the key.
            app.focusChanged.connect(self._on_app_focus_changed)

        # Hook into Maya's output system so ALL Maya messages (startup logs,
        # warnings, errors, command results) appear in our output window —
        # just like Maya's Script Editor and Charcoal Editor 2.
        self._install_output_hook()

        # Load Maya's session history (startup logs, plugin loads, etc.)
        # into our output panel.  This captures everything Maya printed
        # BEFORE the output hook was installed.
        #
        # IMPORTANT: _restore_output() (which loads saved output.log
        # from previous sessions) is SKIPPED in Maya mode to prevent
        # duplication.  Maya's session buffer IS the authoritative
        # history — loading an old output.log on top of it caused the
        # output to grow exponentially with each editor open.
        #
        # Deferred via QTimer.singleShot(0) so the window paints first.
        QTimer.singleShot(0, self._load_maya_history)

        logger.info("MCA Maya Editor window initialized")

    # --- Focus Handling (Maya transition) ------------------------------------

    def event(self, event):
        """
        Catch WindowActivate to ensure keyboard focus lands inside our editor.

        When the user clicks into our docked panel from Maya's viewport, Qt
        fires a WindowActivate event on our top-level window.  At this point
        ``focusWidget()`` may still point to a Maya widget, so keyboard events
        (including plain typing) would be intercepted by Maya's hotkey system.

        By forcing focus into our last-focused child widget on activation, we
        guarantee the hotkey filter's ``_focus_in_editor()`` test passes
        immediately for the very first keystroke.

        :param QEvent event: The Qt event.
        :return: True if consumed.
        :rtype: bool
        """
        if event.type() == QEvent.Type.WindowActivate:
            # Always mark focus as forced when our window activates.
            # If nothing in our tree currently has focus, also push it
            # to the panel (which will forward to the active editor
            # via Qt's focus chain).
            self._hotkey_filter._focus_forced = True
            if not self._hotkey_filter._focus_in_editor():
                self._panel.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        return super().event(event)

    def _on_app_focus_changed(self, old, new):
        """
        Reinforce the hotkey filter's ``_focus_forced`` flag on focus changes.

        Qt's ``QApplication.focusChanged`` signal fires whenever keyboard
        focus moves between widgets.  When focus enters our editor tree,
        we set ``_focus_forced = True`` so Phase 1 accepts ShortcutOverride
        even if ``focusWidget()`` hasn't settled yet.

        We intentionally do NOT clear the flag here.  During Maya's
        workspace control activation (especially on the very first click
        into a docked panel), ``focusChanged`` fires multiple times with
        transient intermediate widgets that are outside our tree.  Clearing
        the flag on those transients caused the first-click hotkey leak
        (Ctrl+C/S leaked to Maya on the initial interaction).

        The flag is only cleared by an explicit ``MouseButtonPress`` outside
        our editor tree (handled in the event filter's Phase 0).

        :param QWidget old: The widget that lost focus (may be None).
        :param QWidget new: The widget that gained focus (may be None).
        """
        if new and self._hotkey_filter._widget_in_editor(new):
            self._hotkey_filter._focus_forced = True

    # --- Maya Output Hook ---------------------------------------------------

    def _install_output_hook(self):
        """
        Register callbacks to capture ALL Maya output.

        Three capture mechanisms work together:

        1. ``MCommandMessage.addCommandOutputCallback`` — captures Maya's
           C++ command system output: MEL echo, ``cmds.warning()``,
           ``cmds.error()``, command results, and ``MGlobal.displayInfo()``.
           This does NOT capture Python ``print()`` output from directly
           ``exec()``'d code — only from code run through Maya's command
           system (command port, Script Editor Execute button).

        2. ``_StdoutTee`` on ``sys.stdout`` — captures ALL Python
           ``print()`` output, including from deferred callbacks,
           framework startup, and module imports.  This is the sole
           capture mechanism for Python stdout since MCommandMessage
           does not fire ``kDisplay`` for ``exec()``'d code.

        3. ``_StderrTee`` on ``sys.stderr`` — captures Python logging
           output (e.g. ``[MCA - Module:...]`` lines from other
           frameworks) which writes to stderr by default.

        The output target (``_output_target``) is always updated to
        this window's output widget.  The tees and MCommandMessage
        callback all read from ``_output_target``, so switching
        windows is just a pointer swap — no tee reinstallation needed.
        Tees are installed once and stay until ``cleanup_editor()``
        (plugin unload).  On dock close they just no-op via the
        ``_output_target is None`` guard.

        Uses module-level references so handles survive window recreation.
        """
        global _output_callback_id, _stderr_tee, _stdout_tee, _output_target

        # Point all capture mechanisms at this window's output widget.
        # This is the ONLY per-window update — everything else is once-only.
        _output_target = self._panel._output

        # Remove any stale callback from a previous window instance before
        # registering a new one.  Without this, Maya keeps calling the old
        # callback (which references a dead widget) alongside the new one.
        if _output_callback_id is not None:
            try:
                om2.MMessage.removeCallback(_output_callback_id)
                logger.info("Removed stale Maya output callback before re-install")
            except Exception:
                pass
            _output_callback_id = None

        # Register the module-level _on_maya_output function (not an
        # instance method) so the callback survives window recreation.
        try:
            _output_callback_id = om2.MCommandMessage.addCommandOutputCallback(
                _on_maya_output
            )
            logger.info("Maya output hook installed")
        except Exception as exc:
            logger.warning("Could not install Maya output hook: %s", exc)

        # Install stdout tee ONCE — it reads _output_target on each write,
        # so it doesn't need to be recreated when windows change.
        if _stdout_tee is None:
            try:
                _stdout_tee = _StdoutTee(sys.stdout)
                sys.stdout = _stdout_tee
                logger.info("Stdout tee installed for print() capture")
            except Exception as exc:
                logger.warning("Could not install stdout tee: %s", exc)

        # Install stderr tee ONCE — same pattern as stdout.
        if _stderr_tee is None:
            try:
                _stderr_tee = _StderrTee(sys.stderr)
                sys.stderr = _stderr_tee
                logger.info("Stderr tee installed for logging capture")
            except Exception as exc:
                logger.warning("Could not install stderr tee: %s", exc)

    def _load_maya_history(self):
        """
        Load Maya's session output history into our output window.

        Uses a temporary ``cmdScrollFieldReporter`` — the same widget
        Maya's own Script Editor uses. When created, it automatically
        receives all output from the current Maya session (startup logs,
        plugin loads, warnings, errors, etc.). We read its text, display
        it in our output window, then delete the temporary widget.

        Uses ``write_bulk()`` for a single batched insert instead of
        per-line ``write_output()`` calls — this is orders of magnitude
        faster for large histories (hundreds of lines in one paint cycle
        instead of one repaint per line).

        This method is called via ``QTimer.singleShot(0, ...)`` so the
        window appears instantly and history loads after the first paint.
        """
        try:
            # Create an invisible window with a cmdScrollFieldReporter.
            # Maya auto-populates reporters with the session's output buffer.
            temp_win = cmds.window(visible=False)
            temp_layout = cmds.columnLayout(parent=temp_win)
            temp_reporter = cmds.cmdScrollFieldReporter(parent=temp_layout)

            # Read all session output from the reporter.
            history = cmds.cmdScrollFieldReporter(
                temp_reporter, query=True, text=True
            )

            # Clean up the temporary UI elements.
            cmds.deleteUI(temp_win)
        except Exception as exc:
            logger.warning("Could not load Maya session history: %s", exc)
            return

        if not history or not history.strip():
            return

        # The cmdScrollFieldReporter stores entries separated by blank
        # lines internally, but Maya's Script Editor renders them packed
        # tightly (no gaps).  Strip blank lines to match the display,
        # but keep ALL content lines — no content filtering.
        lines = [line for line in history.splitlines() if line.strip()]
        if not lines:
            return

        # Route each history line through the appropriate colored write
        # method so errors show red, warnings show orange, etc. — matching
        # Charcoal and the Script Editor's color coding.  The batch buffer
        # accumulates all lines and flushes them in one paint cycle.
        output = self._panel._output
        for line in lines:
            stripped = line.strip()

            # Detect message type from the prefix that Maya's output
            # system embedded in the reporter text.
            # MEL format:   // Error: message //
            # Python format: # Error: message #
            if "Error:" in stripped and (stripped.startswith("//") or stripped.startswith("#")):
                output.write_error(line)
            elif "Warning:" in stripped and (stripped.startswith("//") or stripped.startswith("#")):
                output.write_warning(line)
            elif stripped.startswith("// Result:") or stripped.startswith("# Result:"):
                output.write_result(line)
            else:
                output.write_output(line)

        logger.info("Loaded %d lines of Maya session history", len(lines))

    # --- Status Bar ----------------------------------------------------------

    def _build_status_bar(self):
        """
        Build a blue status bar matching the standalone window's QStatusBar.

        Since MCAMayaWindow is a QWidget (not QMainWindow), we use a
        simple QFrame with an HBoxLayout instead of QStatusBar.

        :return: The status bar frame widget.
        :rtype: QFrame
        """
        bar = QFrame(self)
        bar.setFixedHeight(24)
        bar.setStyleSheet(
            "QFrame { background-color: #007acc; }"
        )

        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 0, 8, 0)
        bar_layout.setSpacing(0)

        # Shared label style — white text on the blue bar.
        label_style = "color: white; padding: 0 8px; font-size: 11px;"

        # Python version (static, set once at startup) — left-aligned.
        bits = struct.calcsize("P") * 8
        py_ver = "Python {}.{}.{} ({}-bit)".format(*sys.version_info[:3], bits)
        py_label = QLabel(py_ver)
        py_label.setStyleSheet(label_style)
        bar_layout.addWidget(py_label)

        # Error count indicator (circled-X symbol) — left-aligned.
        self._error_label = QLabel("\u2297 0")
        self._error_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._error_label)

        # Warning count indicator (warning triangle symbol) — left-aligned.
        self._warning_label = QLabel("\u26a0 0")
        self._warning_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._warning_label)

        # Symbol index status indicator — shows indexing progress or final count.
        self._index_label = QLabel("")
        self._index_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._index_label)

        # Status message area (stretches to fill remaining space between
        # the left-side info labels and the right-side position/lang labels).
        self._status_message_label = QLabel("")
        self._status_message_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._status_message_label, 1)

        # Cursor position (right side, permanent).
        self._pos_label = QLabel("Ln 1, Col 1")
        self._pos_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._pos_label)

        # Current language.
        self._lang_label = QLabel("Python")
        self._lang_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._lang_label)

        # Encoding (always UTF-8 for now).
        encoding_label = QLabel("UTF-8")
        encoding_label.setStyleSheet(label_style)
        bar_layout.addWidget(encoding_label)

        # Project indicator (shows project name or "No Project").
        self._mode_label = QLabel("No Project")
        self._mode_label.setStyleSheet(label_style)
        bar_layout.addWidget(self._mode_label)

        return bar

    def _on_cursor_pos(self, line, col):
        """
        Update the cursor position label.

        :param int line: Current line number (1-based).
        :param int col: Current column number (1-based).
        """
        self._pos_label.setText("Ln {}, Col {}".format(line, col))

    def _on_language_changed(self, language):
        """
        Update the language label in the status bar.

        :param str language: The display name of the current language.
        """
        self._lang_label.setText(language)

    def _on_mode_changed(self, mode_label):
        """
        Update the title bar and status bar project indicator.

        :param str mode_label: Project name when active, empty string when idle.
        """
        if mode_label:
            self.setWindowTitle("MCA Editor -- {}".format(mode_label))
            self._mode_label.setText(mode_label)
        else:
            self.setWindowTitle("MCA Editor")
            self._mode_label.setText("No Project")

    def _on_status_message(self, message, duration_ms):
        """
        Show a temporary status message on the left side of the bar.

        The message auto-clears after *duration_ms* milliseconds.

        :param str message: The status message text.
        :param int duration_ms: How long to display before clearing.
        """
        try:
            self._status_message_label.setText(message)
        except RuntimeError:
            return
        # Auto-clear after the specified duration.  Guard the lambda
        # against the C++ label being deleted before the timer fires
        # (happens when the editor is closed while a timer is pending).
        label = self._status_message_label
        QTimer.singleShot(duration_ms, lambda: _safe_clear_label(label))

    def _toggle_status_bar(self):
        """Toggle visibility of the bottom blue status bar."""
        self._status_bar.setVisible(not self._status_bar.isVisible())

    def _on_counts_changed(self, errors, warnings):
        """
        Update the error and warning count labels in the status bar.

        :param int errors: Current error count.
        :param int warnings: Current warning count.
        """
        self._error_label.setText("\u2297 {}".format(errors))
        self._warning_label.setText("\u26a0 {}".format(warnings))

    def _on_index_status(self, text):
        """
        Update the symbol index indicator in the action bar.

        :param str text: Status text (e.g. "Indexing 45%", "Indexed 120 files", or "" to clear).
        """
        self._index_label.setText(text)

    # --- Status Callback (prints to Maya's output) --------------------------

    def _maya_status_callback(self, message, duration_ms):
        """
        Show status messages in Maya's status line.

        Falls back to print() if the status line is unavailable.

        :param str message: The status message.
        :param int duration_ms: Display duration (used for logging context).
        """
        # Print to Maya's script editor output (non-intrusive).
        print("[MCA Editor] {}".format(message))

    # --- Cleanup ------------------------------------------------------------

    def dockCloseEventTriggered(self):
        """
        Called by Maya when the dockable window is closed.

        Clears the output target (tees and MCommandMessage no-op when
        it's None), removes the MCommandMessage callback, hotkey filter,
        saves state, and cleans up.  Tees stay installed — they just
        silently discard writes until a new window sets ``_output_target``.

        Sets ``editor_was_open`` to False so the editor stays closed on
        next Maya launch (user explicitly closed it).
        """
        global _output_callback_id, _output_target

        # Record that the user explicitly closed the editor — don't auto-open
        # on next Maya launch.
        self._settings.set("editor_was_open", False)

        # Disconnect the output target FIRST so any output that fires
        # during cleanup below doesn't hit a partially-torn-down widget.
        _output_target = None

        # Remove the Maya output hook so we stop receiving messages.
        if _output_callback_id is not None:
            try:
                om2.MMessage.removeCallback(_output_callback_id)
                logger.info("Maya output hook removed")
            except Exception:
                pass
            _output_callback_id = None

        # NOTE: Tees (_stdout_tee / _stderr_tee) are NOT removed here.
        # They stay installed and silently no-op when _output_target is
        # None.  This avoids breaking the stdout/stderr chain on
        # close/reopen — _install_output_hook() just sets _output_target
        # on the next window creation and everything resumes.

        # Remove the hotkey filter and disconnect focusChanged so no
        # dangling callbacks remain on QApplication after the window closes.
        app = QApplication.instance()
        if app:
            if self._hotkey_filter:
                app.removeEventFilter(self._hotkey_filter)
            try:
                app.focusChanged.disconnect(self._on_app_focus_changed)
            except (TypeError, RuntimeError):
                pass

        self._panel.save_window_state(self._settings)
        self._panel.cleanup()
        logger.info("MCA Maya Editor window closed")


# --- Helpers ----------------------------------------------------------------

def _safe_clear_label(label):
    """
    Clear a QLabel's text, silently ignoring if the C++ object is already deleted.

    Used by QTimer.singleShot callbacks that may fire after the editor is closed.

    :param QLabel label: The label to clear.
    """
    try:
        label.setText("")
    except RuntimeError:
        pass


# --- Command Port Setup -----------------------------------------------------

def _open_command_ports_now():
    """
    Attempt to open Maya's MEL (7001) and Python (7002) command ports.

    :return: True if port 7002 is confirmed open after the attempt.
    :rtype: bool
    """
    for port, src_type in [("7001", "mel"), ("7002", "python")]:
        port_name = ":{}".format(port)
        try:
            cmds.commandPort(name=port_name, sourceType=src_type, echoOutput=True)
            logger.info("Opened %s command port %s", src_type, port_name)
        except RuntimeError:
            # RuntimeError means the port is already open — that's fine.
            pass
        except Exception as exc:
            logger.warning("Failed to open command port %s: %s", port_name, exc)

    # Verify port 7002 is actually open.
    try:
        return cmds.commandPort(":7002", query=True)
    except Exception:
        return False


_command_port_retries_scheduled = False


def _ensure_command_ports():
    """
    Open Maya's MEL (7001) and Python (7002) command ports if not already open.

    The MCP server runs as a separate process and communicates with Maya
    over TCP on port 7002.  These ports must be open for Claude Code's
    MCP tools to work.  If a port is already open, the call is a no-op.

    Maya's networking may not be ready during early startup (plugin init,
    layout restore).  If the ports fail to open on the first attempt,
    staggered retries are scheduled via QTimer.  A module-level flag
    prevents duplicate retry chains when called from both
    ``show_mca_editor()`` and ``_restore_mca_editor()`` during the
    same startup cycle.
    """
    global _command_port_retries_scheduled

    if _open_command_ports_now():
        return

    # Only schedule retries once — both show_mca_editor() and
    # _restore_mca_editor() call this during startup.
    if _command_port_retries_scheduled:
        return
    _command_port_retries_scheduled = True

    # Maya's networking likely isn't ready yet.  Schedule staggered
    # retries at 3s, 6s, and 10s to cover slow startup scenarios.
    def _make_retry(attempt, delay):
        """Create a retry closure for the given attempt number."""
        def _retry():
            if not _open_command_ports_now():
                if attempt >= 3:
                    logger.warning("Command ports not open after %d retries", attempt)
        QTimer.singleShot(delay, _retry)

    _make_retry(1, 3000)
    _make_retry(2, 6000)
    _make_retry(3, 10000)


# --- Public API (called from plugin_main and MEL override) ------------------

def show_mca_editor():
    """
    Show or create the MCA Editor dockable window in Maya.

    If the workspace control already exists, it is restored. Otherwise,
    a new one is created and shown. The ``uiScript`` ensures Maya can
    recreate the panel when restoring a saved layout.

    This function is the single entry point called by:
        - The Maya plugin command (``mcaEditor``)
        - The overridden ScriptEditor MEL procedure
        - Direct Python calls from Maya's script editor
    """
    global _mca_editor_window
    global _output_callback_id
    global _output_target

    # Ensure command ports are open FIRST — before any early return.
    # When Maya restores a saved layout, the workspace control is already
    # visible, so show_mca_editor() returns early below.  Without this,
    # the MCP server (a separate process) can never connect to Maya.
    _ensure_command_ports()

    # If the workspace control already exists (Maya restored it from
    # saved layout, or it was left over), just bring it to front.
    # Maya's workspace system remembers docked/floating, position, size.
    if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, exists=True):
        if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, query=True, visible=True):
            cmds.workspaceControl(WORKSPACE_CONTROL_NAME, edit=True, restore=True)
            logger.info("MCA Editor workspace control restored (already visible)")
            return

        # Control exists but is not visible — clean up and delete so
        # we can recreate it fresh.
        _output_target = None
        if _mca_editor_window is not None:
            try:
                _mca_editor_window._panel.save_window_state(
                    _mca_editor_window._settings
                )
                _mca_editor_window._panel.cleanup()
                logger.info("Cleaned up previous editor panel before reload")
            except Exception as exc:
                logger.warning("Pre-reload cleanup failed: %s", exc)
            _mca_editor_window = None

        if _output_callback_id is not None:
            try:
                om2.MMessage.removeCallback(_output_callback_id)
            except Exception:
                pass
            _output_callback_id = None

        cmds.deleteUI(WORKSPACE_CONTROL_NAME)
        logger.info("Deleted stale workspace control: %s", WORKSPACE_CONTROL_NAME)

    # --- License gate ---
    # Check license status before creating the editor.  If the trial has
    # expired and no valid key exists, show the license dialog.  If the
    # user cancels, abort opening — don't kill Maya, just don't show the
    # editor.
    from mca_core.license import check_license
    from mca_qt.widgets.license_dialog import LicenseDialog

    _license_settings = MCASettings()
    license_status = check_license(_license_settings)

    if license_status["needs_key"]:
        # Trial expired, no valid key — must enter one to proceed.
        dialog = LicenseDialog(_license_settings)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            # User cancelled — don't open the editor, but don't kill Maya.
            logger.info("License dialog cancelled — editor not opened")
            return
        # Re-check after dialog in case they entered a valid key.
        license_status = check_license(_license_settings)

    # Capture the license message for the status bar (trial or licensed).
    _license_message = license_status.get("message", "")
    _show_license_notice = license_status.get("trial", False)

    # Kick off MCP server deployment in the background (idempotent).
    # This is also done in plugin_main.initializePlugin(), but when the
    # editor is launched via show_mca_editor() directly (without the
    # plugin system), initializePlugin never runs.
    try:
        from mca_core import mcp_setup
        mcp_setup.ensure_maya_mcp(background=True)
    except Exception as exc:
        logger.warning("MCP setup trigger failed: %s", exc)

    # Create the window widget.  Wrapped in try/except so a failure in
    # the editor panel doesn't take down all of Maya with a hard crash.
    try:
        _mca_editor_window = MCAMayaWindow()
    except Exception as exc:
        om2.MGlobal.displayError("MCA Editor failed to create window: {}".format(exc))
        logger.exception("MCA Editor failed to create window")
        return

    # Show as a dockable workspace control with full Maya persistence.
    # retain=True (default) lets Maya remember position/size/dock state.
    # The uiScript lets Maya recreate the widget when restoring layouts.
    #
    # We don't pass area= or floating= — the mixin defaults to floating
    # when area is None.  On subsequent opens, Maya's retain system
    # restores whatever state the user left it in (docked, floating, etc).
    #
    # The widget starts hidden (via the window's WA_DontShowOnScreen flag)
    # so the initial show(dockable=True) doesn't flash a floating window
    # in the center of the screen while Maya sets up the workspace control.
    # A deferred QTimer reveals it once the parenting is complete.
    _mca_editor_window.setAttribute(Qt.WA_DontShowOnScreen, True)
    try:
        _mca_editor_window.show(
            dockable=True,
            width=1200,
            height=800,
            label="MCA Editor",
            uiScript=(
                "exec('try:\\n"
                " from mca_maya.maya_window import _restore_mca_editor;"
                " _restore_mca_editor()\\n"
                "except: pass')"
            ),
        )
    except Exception as exc:
        om2.MGlobal.displayError("MCA Editor failed to show window: {}".format(exc))
        logger.exception("MCA Editor failed to show window")
        return

    # Reveal the window now that the workspace control parenting is set up.
    # The WA_DontShowOnScreen flag prevented the initial floating flash;
    # clearing it and making the workspace control visible shows the widget
    # in its final docked position without any visual pop.
    def _reveal_first_show():
        try:
            _mca_editor_window.setAttribute(Qt.WA_DontShowOnScreen, False)
            if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, q=True, exists=True):
                cmds.workspaceControl(WORKSPACE_CONTROL_NAME, e=True, visible=True)
        except Exception:
            pass
    QTimer.singleShot(0, _reveal_first_show)

    # Record that the editor is now open so it auto-opens on next Maya launch.
    MCASettings().set("editor_was_open", True)

    # Show trial notice on the Maya status bar if in trial mode.
    if _show_license_notice and _license_message:
        _mca_editor_window._on_status_message(_license_message, 10000)

    logger.info("MCA Editor dockable window created")


def _restore_mca_editor():
    """
    Restore the MCA Editor panel inside an existing workspace control.

    Called by Maya's workspace control ``uiScript`` when restoring a
    saved layout.  Maya already created the workspace control in
    whatever state the user left it (docked, floating, position, size).
    We just need to populate it with our widget.

    To prevent the visual flash where the widget briefly appears
    floating in the center of the screen before Maya docks it, the
    workspace control is hidden BEFORE the widget is created.  After
    the mixin parents the widget into the control, a deferred call
    reveals it — by then the widget is already in its final docked
    position.

    Maya may call this multiple times during a single layout restore
    cycle, so we guard against redundant recreation.
    """
    global _mca_editor_window

    # Ensure command ports are open so the MCP server can connect.
    _ensure_command_ports()

    # Guard: if a valid window already exists, skip recreation.
    if _mca_editor_window is not None:
        try:
            _mca_editor_window.objectName()
            logger.info("MCA Editor already exists — skipping uiScript re-creation")
            return
        except RuntimeError:
            _mca_editor_window = None

    # Hide the workspace control BEFORE creating the widget to prevent
    # the visual flash.  The mixin's show() creates the widget and
    # parents it into the control — if the control is visible during
    # this process, the widget briefly appears floating at the center
    # of the screen before Maya repositions it.  Hiding first ensures
    # the user never sees the intermediate state.
    try:
        if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, q=True, exists=True):
            cmds.workspaceControl(WORKSPACE_CONTROL_NAME, e=True, visible=False)
    except Exception:
        pass

    # Create a fresh window widget and parent it into the workspace control.
    _mca_editor_window = MCAMayaWindow()
    _mca_editor_window.show(
        dockable=True,
        uiScript=(
            "exec('try:\\n"
            " from mca_maya.maya_window import _restore_mca_editor;"
            " _restore_mca_editor()\\n"
            "except: pass')"
        ),
    )

    # Reveal the workspace control after the widget is parented.
    # Deferred via QTimer.singleShot(0) so the event loop processes
    # the parenting before the control becomes visible — the widget
    # appears in its final docked position without any flash.
    def _reveal():
        try:
            if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, q=True, exists=True):
                cmds.workspaceControl(WORKSPACE_CONTROL_NAME, e=True, visible=True)
        except Exception:
            pass
    QTimer.singleShot(0, _reveal)

    logger.info("MCA Editor workspace control restored via uiScript")


# --- Plugin Cleanup ---------------------------------------------------------

def cleanup_editor(maya_is_exiting=False):
    """
    Clean up the MCA Editor window and all child resources.

    Called by ``uninitializePlugin()`` to ensure terminal processes,
    adapters, and callbacks are properly shut down when the plugin is
    unloaded or Maya exits.  Without this, ConPTY shell processes
    survive Maya shutdown and prevent the process from exiting cleanly.

    When *maya_is_exiting* is True, the window widget is explicitly
    destroyed via ``shiboken6.delete()`` after saving state and
    terminating child processes.  This is critical: our widget tree is
    parented to Maya's workspace control.  During Maya's later Qt
    teardown, the C++ side destroys the workspace control and all
    children.  If Python shiboken wrappers still reference those
    freed C++ objects, shiboken's destructor hits an ACCESS_VIOLATION.
    By deleting the widget through shiboken first, both the C++ and
    Python sides are cleaned up in sync, leaving no dangling wrappers.

    :param bool maya_is_exiting: True when called during Maya shutdown
        (kMayaExiting callback fired), False for user-initiated unload.
    """
    global _mca_editor_window
    global _output_callback_id
    global _output_target
    global _stderr_tee
    global _stdout_tee

    # Clear the output target FIRST — all three capture mechanisms
    # (MCommandMessage, _StdoutTee, _StderrTee) check this before
    # writing, so any output that fires during cleanup below is
    # silently discarded instead of hitting a dead widget.
    _output_target = None

    # Remove Maya output hook — this is an OpenMaya callback, safe
    # to remove during shutdown (not a Qt operation).
    if _output_callback_id is not None:
        try:
            om2.MMessage.removeCallback(_output_callback_id)
        except Exception:
            pass
        _output_callback_id = None

    # Restore original stdout (remove the tee wrapper).
    # Full teardown — this is plugin unload, not just dock close.
    if _stdout_tee is not None:
        sys.stdout = _stdout_tee._original
        _stdout_tee = None

    # Restore original stderr (remove the tee wrapper).
    if _stderr_tee is not None:
        sys.stderr = _stderr_tee._original
        _stderr_tee = None

    # Clean up the editor window if it exists.
    if _mca_editor_window is not None:
        try:
            # Remove hotkey filter and disconnect focusChanged signal.
            # The focusChanged connection survives widget destruction and
            # leaves a dangling callback on QApplication — during Python's
            # atexit phase, shiboken tries to destruct the callback wrapper
            # which references the freed window → ACCESS_VIOLATION.
            app = QApplication.instance()
            if app:
                if hasattr(_mca_editor_window, '_hotkey_filter') and _mca_editor_window._hotkey_filter:
                    app.removeEventFilter(_mca_editor_window._hotkey_filter)

                # Disconnect focusChanged — connected in __init__ at line 524.
                try:
                    app.focusChanged.disconnect(_mca_editor_window._on_app_focus_changed)
                except (TypeError, RuntimeError):
                    # Already disconnected or object invalidated — safe to ignore.
                    pass

            # Save state and terminate terminals/adapters.
            _mca_editor_window._panel.save_window_state(_mca_editor_window._settings)
            _mca_editor_window._panel.cleanup()
            logger.info("MCA Editor cleanup completed (terminals terminated)")
        except Exception as exc:
            logger.warning("Error during MCA Editor cleanup: %s", exc)

        if maya_is_exiting:
            # Maya is shutting down.  Hide the workspace control to prevent
            # the close flash, then destroy the widget via shiboken so no
            # dangling Python wrappers exist during Maya's C++ teardown.
            # Do NOT deleteUI — let Maya save the workspace state so the
            # editor remembers its position/dock state on next launch.
            try:
                if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, q=True, exists=True):
                    cmds.workspaceControl(WORKSPACE_CONTROL_NAME, e=True, visible=False)
            except Exception:
                pass

            # Process events so the hide takes visual effect before we
            # destroy the widget.  Without this, the widget briefly
            # undocks and appears floating in the center of the screen
            # before shiboken tears it down.
            try:
                app = QApplication.instance()
                if app:
                    app.processEvents()
            except Exception:
                pass

            try:
                import shiboken6
                if shiboken6.isValid(_mca_editor_window):
                    shiboken6.delete(_mca_editor_window)
                    logger.info("Destroyed editor widget via shiboken6.delete()")
            except Exception as exc:
                logger.warning("shiboken6.delete() failed: %s", exc)
        else:
            # Manual plugin unload — delete the workspace control so it
            # doesn't linger as an empty shell.
            try:
                if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, exists=True):
                    cmds.deleteUI(WORKSPACE_CONTROL_NAME)
                    logger.info("Deleted workspace control (manual unload)")
            except Exception:
                pass

        _mca_editor_window = None
