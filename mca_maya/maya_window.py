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

import struct
import sys

from mca_qt.qt_compat import QWidget, QVBoxLayout, QHBoxLayout, QMenuBar, QLabel, QFrame, Qt, QKeySequence
from mca_qt.editor_panel import MCAEditorPanel
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
        from mca_qt.widgets.terminal_native import TerminalWidget
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
            if isinstance(watched, _QWidget) and self._widget_in_editor(watched):
                # Activate the top-level window first — setFocus() has
                # no effect if the window isn't active (common when
                # clicking from Maya's viewport into a docked panel).
                top = self._target.window()
                if top:
                    top.activateWindow()

                # Find the appropriate focus target.
                focus_target = watched
                # Walk down to the actual focusable child if the clicked
                # widget doesn't accept focus (e.g. a QFrame layout).
                if focus_target.focusPolicy() == Qt.FocusPolicy.NoFocus:
                    child = focus_target.focusProxy()
                    if child:
                        focus_target = child
                    else:
                        # No focus proxy — walk children for the first
                        # widget that accepts focus (depth-first).
                        for c in focus_target.findChildren(_QWidget):
                            if c.focusPolicy() != Qt.FocusPolicy.NoFocus:
                                focus_target = c
                                break

                focus_target.setFocus(Qt.FocusReason.MouseFocusReason)
                # Mark that we forced focus so Phase 1 treats the very
                # next ShortcutOverride as ours even if focusWidget()
                # hasn't updated yet.
                self._focus_forced = True

        # --- Phase 1: Block Maya's hotkey system entirely ---
        if event.type() == QEvent.Type.ShortcutOverride:
            # Check both the regular focus test AND the forced-focus flag.
            # After Phase 0 forces focus via setFocus(), Qt may not have
            # updated focusWidget() yet when the very next ShortcutOverride
            # arrives in the same event loop iteration.
            if self._focus_in_editor() or getattr(self, "_focus_forced", False):
                self._focus_forced = False
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
                    # For regular text editors, call keyPressEvent directly
                    # so built-in shortcuts (Ctrl+Z/C/V/X/A/Y) still work.
                    focus = QApplication.instance().focusWidget()
                    if focus:
                        # Walk up the parent chain looking for a terminal.
                        terminal = self._find_parent_terminal(focus)
                        if terminal:
                            # Route through the terminal's eventFilter which
                            # handles Ctrl+V paste, Ctrl+C interrupt, etc.
                            terminal.eventFilter(focus, event)
                        elif hasattr(focus, "keyPressEvent"):
                            focus.keyPressEvent(event)
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

        # Build a QMenuBar embedded at the top of the dockable window so
        # all menu options (File, Edit, View, etc.) are accessible.
        self._menubar = QMenuBar(self)
        self._panel.build_menus(self._menubar)

        # Apply our dark stylesheet on top of Maya's theme.
        self.setStyleSheet(GLOBAL_STYLESHEET)

        # Set up the panel's status callback to print to Maya's script editor.
        self._panel.set_status_callback(self._maya_status_callback)

        # Build the blue status bar that mirrors the standalone window.
        self._status_bar = self._build_status_bar()

        # Layout: menu bar on top, panel fills the middle, status bar at bottom.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._menubar, 0)   # 0 stretch — stays at natural height.
        layout.addWidget(self._panel, 1)     # 1 stretch — expands to fill space.
        layout.addWidget(self._status_bar, 0)  # 0 stretch — stays at natural height.

        # Connect panel signals to the status bar labels.
        self._panel.cursor_position_changed.connect(self._on_cursor_pos)
        self._panel.language_changed.connect(self._on_language_changed)
        self._panel.mode_changed.connect(self._on_mode_changed)
        self._panel.status_message.connect(self._on_status_message)
        self._panel.output_counts_changed.connect(self._on_counts_changed)
        self._panel.activity_bar_toggled.connect(self._toggle_status_bar)

        # Install an application-level event filter to prevent Maya's
        # hotkeys from intercepting keystrokes while typing in our editor.
        # Without this, pressing 'S' triggers Maya's "Set Key" instead of
        # typing the letter, 'W' switches to Move Tool, Ctrl+D duplicates, etc.
        self._hotkey_filter = _MayaHotkeyFilter(self, self._panel)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self._hotkey_filter)

        # Hook into Maya's output system so ALL Maya messages (startup logs,
        # warnings, errors, command results) appear in our output window —
        # just like Maya's Script Editor and Charcoal Editor 2.
        self._output_callback_id = None
        self._install_output_hook()

        # Defer history loading so the window appears immediately. The
        # history can be large (hundreds of lines) and inserting it
        # synchronously in __init__ blocks the UI for several seconds.
        # QTimer.singleShot(0) queues it after the event loop processes
        # the pending show/paint events, so the window is visible first.
        from mca_qt.qt_compat import QTimer
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
            # If nothing in our tree currently has focus, give it to the
            # panel (which will forward to the active editor via Qt's
            # focus chain).
            if not self._hotkey_filter._focus_in_editor():
                self._panel.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
                self._hotkey_filter._focus_forced = True

        return super().event(event)

    # --- Maya Output Hook ---------------------------------------------------

    def _install_output_hook(self):
        """
        Register a callback with Maya's MCommandMessage system to capture
        all output that would normally appear in Maya's Script Editor.

        This includes startup logs, plugin load messages, warnings, errors,
        and command results — everything Maya routes to its output window.
        """
        try:
            self._output_callback_id = om2.MCommandMessage.addCommandOutputCallback(
                self._on_maya_output
            )
            logger.info("Maya output hook installed")
        except Exception as exc:
            logger.warning("Could not install Maya output hook: %s", exc)

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

        # Filter out blank lines and internal MCA log messages.  The raw
        # reporter text has empty lines between entries, and MCA's Python
        # loggers may have emitted INFO messages before setLevel(WARNING)
        # took effect (e.g., during initializePlugin).
        lines = []
        for line in history.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Skip internal MCA logger lines — they follow the pattern
            # "mca_core.module : ..." or "mca_qt.module : ..." etc.
            if stripped.startswith(("mca_core.", "mca_qt.", "mca_maya.", "mca_editor.")):
                continue
            lines.append(line)
        if not lines:
            return

        # Batch-insert the entire history in a single cursor operation.
        # This avoids hundreds of individual write_output() calls, each
        # of which triggers cursor movement + ensureCursorVisible + repaint.
        cleaned = "\n".join(lines) + "\n"
        self._panel._output.write_bulk(cleaned)
        logger.info("Loaded %d lines of Maya session history", len(lines))

    def _on_maya_output(self, message, message_type, client_data):
        """
        Callback fired by Maya for every line of output.

        Routes messages to the appropriate output window method based
        on the message type (display, error, warning, result, info).

        :param str message: The output text from Maya.
        :param int message_type: MCommandMessage message type constant.
        :param object client_data: Unused client data from Maya.
        """
        # Skip empty messages.
        if not message or not message.strip():
            return

        # Skip messages echoed by the internal adapter to Maya's script
        # editor.  The adapter sets this flag while calling displayInfo()
        # so we don't duplicate the output in MCA Editor's panel.
        from mca_core.adapters.internal_maya_adapter import _suppress_output_hook
        if _suppress_output_hook:
            return

        # Suppress the harmless "Nothing is selected" error from Maya's
        # cutCopyPaste.mel — this fires when Ctrl+C/X leaks to Maya
        # during focus transitions and nothing is selected in the viewport.
        if "cutCopyPaste.mel" in message and "Nothing is selected" in message:
            return

        # Suppress internal MCA log messages that leak through Maya's output
        # system.  Even though we set parent loggers to WARNING, Maya's root
        # logging handler or sys.stdout/stderr capture can still forward
        # messages from before the level was set, or from direct print calls.
        stripped = message.strip()
        if stripped.startswith(("mca_core.", "mca_qt.", "mca_maya.", "mca_editor.")):
            return

        text = message.rstrip()
        output = self._panel._output

        # Route to the appropriate output method based on message type.
        if message_type == om2.MCommandMessage.kError:
            output.write_error(text)
        elif message_type == om2.MCommandMessage.kWarning:
            output.write_warning(text)
        elif message_type == om2.MCommandMessage.kResult:
            output.write_result(text)
        elif message_type == om2.MCommandMessage.kInfo:
            output.write_info(text)
        else:
            # kDisplay and any other types — standard output.
            output.write_output(text)

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

        # Editor mode indicator.
        self._mode_label = QLabel("Simple")
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
        Update the mode label in the status bar.

        :param str mode_label: 'Simple' or 'Advanced'.
        """
        self._mode_label.setText(mode_label)

    def _on_status_message(self, message, duration_ms):
        """
        Show a temporary status message on the left side of the bar.

        The message auto-clears after *duration_ms* milliseconds.

        :param str message: The status message text.
        :param int duration_ms: How long to display before clearing.
        """
        self._status_message_label.setText(message)
        # Auto-clear after the specified duration.
        from mca_qt.qt_compat import QTimer
        QTimer.singleShot(duration_ms, lambda: self._status_message_label.setText(""))

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

    # --- Status Callback (prints to Maya's output) --------------------------

    def _maya_status_callback(self, message, duration_ms):
        """
        Show status messages in Maya's status line.

        Falls back to print() if the status line is unavailable.

        :param str message: The status message.
        :param int duration_ms: Display duration (used for logging context).
        """
        try:
            # Use Maya's inViewMessage for prominent feedback.
            cmds.inViewMessage(
                assistMessage=message,
                position="topCenter",
                fade=True,
            )
        except Exception:
            # Fallback: just print to Maya's script editor output.
            print("[MCA Editor] {}".format(message))

    # --- Cleanup ------------------------------------------------------------

    def dockCloseEventTriggered(self):
        """
        Called by Maya when the dockable window is closed.

        Removes the output hook, hotkey filter, saves state, and cleans up.
        """
        # Remove the Maya output hook so we stop receiving messages.
        if self._output_callback_id is not None:
            try:
                om2.MMessage.removeCallback(self._output_callback_id)
                logger.info("Maya output hook removed")
            except Exception:
                pass
            self._output_callback_id = None

        # Remove the hotkey filter so Maya's shortcuts work normally again.
        app = QApplication.instance()
        if app and self._hotkey_filter:
            app.removeEventFilter(self._hotkey_filter)

        self._panel.save_window_state(self._settings)
        self._panel.cleanup()
        logger.info("MCA Maya Editor window closed")


# --- Command Port Setup -----------------------------------------------------

def _ensure_command_ports():
    """
    Open Maya's MEL (7001) and Python (7002) command ports if not already open.

    The MCP server runs as a separate process and communicates with Maya
    over TCP on port 7002.  These ports must be open for Claude Code's
    MCP tools to work.  If a port is already open, the call is a no-op.
    """
    for port, src_type in [("7001", "mel"), ("7002", "python")]:
        port_name = ":{}".format(port)
        try:
            cmds.commandPort(name=port_name, sourceType=src_type, echoOutput=True)
            logger.info("Opened %s command port %s", src_type, port_name)
        except RuntimeError:
            # RuntimeError means the port is already open — that's fine.
            logger.debug("Command port %s already open", port_name)


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

    # If the workspace control already exists from a previous session,
    # delete it so we can create a fresh one. Maya keeps the control
    # alive even after the widget is closed, which causes a "name not
    # unique" error if we try to create another one.
    if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, exists=True):
        # If the control is still visible, just bring it to front.
        if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, query=True, visible=True):
            cmds.workspaceControl(WORKSPACE_CONTROL_NAME, edit=True, restore=True)
            logger.info("MCA Editor workspace control restored (already visible)")
            return

        # Clean up the old panel before destroying the workspace control.
        # deleteUI does NOT trigger dockCloseEventTriggered, so output
        # and session data would be lost without this explicit save.
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

        # Control exists but is not visible — delete it so we can
        # recreate cleanly with a new widget instance.
        cmds.deleteUI(WORKSPACE_CONTROL_NAME)
        logger.info("Deleted stale workspace control: %s", WORKSPACE_CONTROL_NAME)

    # Ensure command ports are open so the MCP server (a separate process)
    # can communicate with Maya.  Claude Code talks to the MCP server via
    # stdio, and the MCP server talks to Maya via TCP on port 7002.
    _ensure_command_ports()

    # Kick off MCP server deployment in the background (idempotent).
    # This is also done in plugin_main.initializePlugin(), but when the
    # editor is launched via show_mca_editor() directly (without the
    # plugin system), initializePlugin never runs.
    try:
        from mca_core import mcp_setup
        mcp_setup.ensure_maya_mcp(background=True)
    except Exception as exc:
        logger.warning("MCP setup trigger failed: %s", exc)

    # Create the window widget.
    _mca_editor_window = MCAMayaWindow()

    # Show as a dockable workspace control with persistence.
    # The uiScript is called by Maya when it needs to recreate the UI
    # (e.g., loading a saved layout).
    _mca_editor_window.show(
        dockable=True,
        area="right",
        floating=True,
        width=1200,
        height=800,
        label="MCA Editor",
        uiScript="from mca_maya.maya_window import _restore_mca_editor; _restore_mca_editor()",
    )

    logger.info("MCA Editor dockable window created")


def _restore_mca_editor():
    """
    Restore the MCA Editor panel inside an existing workspace control.

    Called by Maya's workspace control ``uiScript`` when restoring a
    saved layout. Creates a new MCAMayaWindow and parents it into the
    existing workspace control.
    """
    global _mca_editor_window

    # Create a fresh window widget.
    _mca_editor_window = MCAMayaWindow()

    # Use the mixin's helper to parent into the workspace control.
    # Maya already created the workspace control from the saved layout;
    # we just need to populate it with our widget.
    _mca_editor_window.show(
        dockable=True,
        uiScript="from mca_maya.maya_window import _restore_mca_editor; _restore_mca_editor()",
    )

    logger.info("MCA Editor workspace control restored via uiScript")
