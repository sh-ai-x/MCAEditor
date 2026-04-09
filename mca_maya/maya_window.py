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


# Tee class names used for cross-module isinstance checks.  The dual
# module import problem means isinstance() fails across module copies
# (different class objects).  Checking type().__name__ is immune to this.
_TEE_CLASS_NAMES = ("_StdoutTee", "_StderrTee")


def _unwrap_all_tees(stream):
    """
    Unwrap ALL nested tee layers and return the original non-tee stream.

    The dual module import problem causes tee chains to stack: each
    ``_install_output_hook`` call wraps the current ``sys.stdout`` in
    a new tee.  If the current ``sys.stdout`` is already a tee from a
    different module copy, ``isinstance()`` fails and the old tee is
    never unwound — it just gets wrapped again.

    This function walks the ``_original`` chain by checking the class
    name (string comparison, not ``isinstance``), which works across
    module copies.  It returns the deepest non-tee object (Maya's raw
    ``Output`` redirector).

    Safety: caps at 20 iterations to prevent infinite loops if the
    chain is somehow circular.

    :param object stream: A stream that may be a tee (or chain of tees).
    :return: The original non-tee stream at the bottom of the chain.
    :rtype: object
    """
    depth = 0
    while type(stream).__name__ in _TEE_CLASS_NAMES and depth < 20:
        orig = getattr(stream, "_original", None)
        if orig is None:
            break
        stream = orig
        depth += 1
    return stream


class _StderrTee:
    """
    Wrapper around sys.stderr that tees writes to the MCA output panel.

    Python's ``logging`` module writes to sys.stderr by default.  Maya's
    ``MCommandMessage.addCommandOutputCallback`` only captures Maya's own
    output system (MEL echo, print(), cmds warnings) — it never sees
    raw stderr writes.  This tee bridges the gap so logging output from
    other frameworks (e.g. the MCA framework's ``[MCA - Module:...]``
    lines) appears in our editor's output window alongside Maya's output.

    Line-buffered: Python's traceback formatter writes the exception line
    in multiple write() calls (e.g. ``AttributeError``, ``:``,
    `` 'NoneType' ...``).  Buffering until ``\\n`` recombines them into
    a single output line and avoids stray ``:`` noise.

    Tracks traceback context so all lines between "Traceback (...)" and
    the final exception line are colored as errors (red), not white.

    The original stderr object is preserved and all writes are forwarded
    to it first, so Maya's Script Editor and console still work normally.

    :param object original: The original sys.stderr object to wrap.
    :param OutputWindow output_widget: Our output panel widget.
    """

    def __init__(self, original, output_widget):
        """
        Initialize the tee with the original stderr and our output panel.

        :param object original: The original sys.stderr.
        :param OutputWindow output_widget: MCA Editor output window.
        """
        self._original = original
        self._output = output_widget
        # Line buffer — accumulates partial write() calls until a newline.
        self._buffer = ""
        # Traceback context flag — set True when we see "Traceback (...)"
        # and cleared after the final exception line, so every line in
        # between is routed to write_error() for red coloring.
        self._in_traceback = False

    def write(self, text):
        """
        Write to both the original stderr and our output panel.

        Accumulates text in a line buffer and flushes complete lines.
        This recombines split writes (e.g. ``AttributeError`` + ``:`` +
        `` message``) into a single output line.

        :param str text: Text to write.
        """
        # Always forward to the original so Maya's own stderr handling works.
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass

        if not text:
            return

        # Accumulate into the line buffer.
        self._buffer += text

        # Process every complete line (terminated by newline).
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write_line(line)

    def _write_line(self, line):
        """
        Route a single complete line to the output panel with proper
        color based on content and traceback context.

        :param str line: One line of stderr text (no trailing newline).
        """
        stripped = line.rstrip()

        # Skip empty lines.
        if not stripped:
            return

        # Skip Python 3.11+ traceback caret indicator lines ("^^^^...").
        stripped_check = stripped.strip()
        if stripped_check and all(c in "^~" for c in stripped_check):
            return

        # Route to our output panel with appropriate coloring.
        try:
            # Detect error/warning patterns from logging output.
            if "ERROR:" in stripped or "Error:" in stripped:
                self._output.write_error(stripped)
            elif "WARNING:" in stripped or "Warning:" in stripped:
                self._output.write_warning(stripped)

            # Detect start of a Python traceback.
            elif "Traceback (most recent call last)" in stripped:
                self._in_traceback = True
                self._output.write_error(stripped)

            # Inside a traceback — color everything red.
            elif self._in_traceback:
                self._output.write_error(stripped)
                # The final line of a traceback is the exception itself,
                # which is not indented and typically contains "Error" or
                # "Exception".  Reset the flag after writing it.
                if not stripped.startswith(" ") and (
                    "Error" in stripped or "Exception" in stripped
                ):
                    self._in_traceback = False

            else:
                self._output.write_output(stripped)
        except (RuntimeError, AttributeError):
            # Output widget already deleted — ignore silently.
            pass

    def flush(self):
        """Flush any remaining buffered text and the original stderr."""
        # Write out any partial line remaining in the buffer.
        if self._buffer and self._buffer.strip():
            self._write_line(self._buffer)
        self._buffer = ""

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
    Transparent wrapper around sys.stdout for safe tee unwrapping.

    Maya's ``MCommandMessage.addCommandOutputCallback`` captures ALL
    stdout output — including Python ``print()`` from exec'd code,
    deferred callbacks, and framework startup logs.  The output panel
    is written to solely by ``_on_maya_output()``, NOT here.

    This wrapper exists so that ``_unwrap_all_tees()`` can strip it
    during adapter execution (replaced with ``_TeeWriter`` for
    StringIO capture) and restore it afterward, without losing the
    reference to Maya's original ``OutputRedirector``.

    :param object original: The original sys.stdout object to wrap.
    :param OutputWindow output_widget: Our output panel widget (unused,
        kept for API compatibility with ``_StderrTee``).
    """

    def __init__(self, original, output_widget):
        """
        Initialize the tee with the original stdout and our output panel.

        :param object original: The original sys.stdout.
        :param OutputWindow output_widget: MCA Editor output window.
        """
        self._original = original
        self._output = output_widget

    def write(self, text):
        """
        Forward writes to Maya's original stdout.

        The output panel is NOT written to here — MCommandMessage's
        addCommandOutputCallback already captures all print() output
        and routes it through ``_on_maya_output()``.  Writing here
        too would cause every print() to appear twice in the panel.

        :param str text: Text to write.
        """
        # Forward to the original so Maya's Script Editor works.
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
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
        # Individual actions are guarded with try/except because a stale
        # QAction whose C++ object was garbage-collected will raise
        # RuntimeError on any attribute access.  Skip the dead action
        # instead of aborting the entire search.
        for action in list(self._panel._action_registry.values()):
            try:
                shortcut = action.shortcut()
                if not shortcut.isEmpty() and shortcut.toString() == seq_str:
                    return action
            except RuntimeError:
                # C++ QAction already deleted — skip it.
                continue

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
                    # Try registered editor actions first (Find, Save, etc.).
                    # Wrapped in try/except because stale QActions whose C++
                    # objects were deleted will raise RuntimeError when we
                    # call .shortcut() or .isEnabled().  Without this guard,
                    # a single stale action crashes the entire dispatch and
                    # all modifier shortcuts (including paste) silently stop.
                    action = None
                    try:
                        action = self._find_matching_action(event)
                    except RuntimeError:
                        logger.debug("Stale action in registry during "
                                     "shortcut match — skipping action dispatch")
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
                        old_focus = focus
                        focus = getattr(self, "_focus_forced_widget", None)
                        if key == Qt.Key.Key_V:
                            logger.debug(
                                "Ctrl+V: focusWidget=%s not in editor, "
                                "using _focus_forced_widget=%s",
                                type(old_focus).__name__ if old_focus else None,
                                type(focus).__name__ if focus else None
                            )

                    if not focus:
                        if key == Qt.Key.Key_V:
                            logger.warning(
                                "Ctrl+V: no focus widget and no "
                                "_focus_forced_widget — paste dropped"
                            )
                    if focus:
                        # Walk up the parent chain looking for a terminal.
                        terminal = self._find_parent_terminal(focus)
                        try:
                            if terminal:
                                # Route through the terminal's eventFilter
                                # which handles Ctrl+V paste, Ctrl+C
                                # interrupt, etc.  Check liveness first —
                                # a dead terminal's eventFilter returns
                                # False (unhandled), and we must NOT fall
                                # through to the direct-method path because
                                # calling _display.paste() would inject raw
                                # text into the terminal's visual display.
                                alive = getattr(terminal, "_alive", False)
                                if alive:
                                    # Pass terminal._display (not `focus`)
                                    # because the eventFilter checks
                                    # `if obj is self._display:` and rejects
                                    # any other object.
                                    handled = terminal.eventFilter(
                                        terminal._display, event
                                    )
                                    if not handled:
                                        logger.debug(
                                            "Terminal eventFilter returned "
                                            "False for key=%s — event "
                                            "consumed to block Maya", key
                                        )
                                else:
                                    logger.debug(
                                        "Terminal is dead (alive=%s) — "
                                        "key=%s consumed to block Maya",
                                        alive, key
                                    )
                            else:
                                # Standard text editing shortcuts — call the
                                # method directly for maximum reliability.
                                # Going through keyPressEvent can fail if
                                # focus hasn't fully transferred on the first
                                # click after activateWindow() on Win11.
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
                                # Check if the focused widget can actually
                                # accept the text operation.  Read-only
                                # widgets (output panel) have paste()/cut()
                                # methods that silently do nothing.  When
                                # the focus is on a read-only widget or one
                                # that lacks the method entirely, redirect
                                # the operation to the active code editor.
                                focus_is_readonly = (
                                    hasattr(focus, "isReadOnly")
                                    and focus.isReadOnly()
                                )
                                # Paste and cut modify the document — redirect
                                # if the target is read-only.  Copy and
                                # selectAll are fine on read-only widgets.
                                needs_writable = method_name in ("paste", "cut")
                                can_use_focus = (
                                    method_name
                                    and hasattr(focus, method_name)
                                    and not (needs_writable and focus_is_readonly)
                                )

                                if can_use_focus:
                                    if key == Qt.Key.Key_V:
                                        logger.debug(
                                            "Ctrl+V: calling %s.%s()",
                                            type(focus).__name__, method_name
                                        )
                                    getattr(focus, method_name)()
                                elif method_name:
                                    # The focused widget is read-only or
                                    # doesn't support this text operation
                                    # (e.g. file tree, output panel).  Try
                                    # the panel's active code editor as a
                                    # last resort — the user likely expects
                                    # paste to go there.
                                    editor = self._panel._current_editor()
                                    if editor and hasattr(editor, method_name):
                                        if key == Qt.Key.Key_V:
                                            logger.debug(
                                                "Ctrl+V: focus=%s can't %s "
                                                "(readonly=%s), redirecting "
                                                "to active editor %s",
                                                type(focus).__name__,
                                                method_name,
                                                focus_is_readonly,
                                                type(editor).__name__
                                            )
                                        getattr(editor, method_name)()
                                    elif hasattr(focus, "keyPressEvent"):
                                        focus.keyPressEvent(event)
                                elif hasattr(focus, "keyPressEvent"):
                                    # Not a standard text op — fall back to
                                    # keyPressEvent for everything else.
                                    focus.keyPressEvent(event)
                        except RuntimeError:
                            # The focused widget's C++ object was deleted
                            # between the focusWidget() call and the dispatch.
                            # This happens when tabs close or widgets rebuild
                            # mid-event.
                            logger.debug("Widget deleted during key dispatch "
                                         "(key=%s) — event dropped", key)
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

        # Load version-specific settings so Maya 2024 and 2025 don't
        # share QSettings (splitter sizes, editor_was_open, etc.).
        from mca_maya.plugin_main import _maya_version
        _dcc_tag = "Maya{}".format(_maya_version) if _maya_version else None
        _app_name = "MCAEditor-{}".format(_dcc_tag) if _dcc_tag else "MCAEditor"
        self._settings = MCASettings(app_name=_app_name)

        # Create an adapter manager without the built-in TCP adapter, since
        # we're running inside Maya and don't need socket communication.
        self._adapter_manager = AdapterManager(register_builtin=False)

        # Register the internal adapter (direct maya.cmds calls).
        # This adapter is always connected — we ARE Maya.
        internal_adapter = InternalMayaAdapter()
        self._adapter_manager.register_adapter_instance("maya_internal", internal_adapter)

        # Create the editor panel with the pre-connected adapter manager.
        # Pass the DCC version tag so session/output are stored per-version.
        self._panel = MCAEditorPanel(
            self._settings,
            adapter_manager=self._adapter_manager,
            dcc_version=_dcc_tag,
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

    # Traceback echo suppression flag.  When True, kDisplay messages that
    # look like traceback content are suppressed — _StderrTee handles them
    # with proper error coloring.  Set True when "Traceback (...)" is seen
    # in a kDisplay message; reset after the final exception line.
    _in_traceback_echo = False

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

        Uses module-level references so handles survive window recreation.
        Any previous callback/tee is removed first to prevent stale refs.
        """
        global _output_callback_id, _stderr_tee, _stdout_tee

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

        # Remove orphaned callbacks from OTHER module copies.  The dual
        # module import problem creates separate globals in each copy —
        # our _output_callback_id only tracks THIS copy's callback.  Scan
        # sys.modules for any other maya_window modules and clean their
        # callback IDs too.
        for mod_name, mod_obj in list(sys.modules.items()):
            if mod_obj is None:
                continue
            # Match any module that looks like our maya_window (could be
            # under a different sys.modules key due to import aliasing).
            if not hasattr(mod_obj, "_output_callback_id"):
                continue
            if not hasattr(mod_obj, "WORKSPACE_CONTROL_NAME"):
                continue
            # Skip our own module — already handled above.
            if mod_obj is sys.modules.get(__name__):
                continue
            other_cb_id = getattr(mod_obj, "_output_callback_id", None)
            if other_cb_id is not None:
                try:
                    om2.MMessage.removeCallback(other_cb_id)
                except Exception:
                    pass
                mod_obj._output_callback_id = None

        try:
            _output_callback_id = om2.MCommandMessage.addCommandOutputCallback(
                self._on_maya_output
            )
            logger.info("Maya output hook installed")
        except Exception as exc:
            logger.warning("Could not install Maya output hook: %s", exc)

        # Install stdout tee to capture Python print() output.
        # MCommandMessage does NOT fire kDisplay for print() from exec'd
        # Python code, so this tee is the sole capture mechanism for
        # stdout.
        #
        # Unwrap ALL tee layers first — not just one.  The dual module
        # import problem causes tee chains to stack (each module copy
        # wraps the other's tee).  _unwrap_all_tees() walks the chain
        # by class name (immune to cross-module isinstance failure) and
        # returns Maya's raw Output redirector at the bottom.
        if _stdout_tee is not None:
            _stdout_tee = None

        # Unwrap any stale tees on sys.stdout (from this or other module copies).
        raw_stdout = _unwrap_all_tees(sys.stdout)
        sys.stdout = raw_stdout

        try:
            _stdout_tee = _StdoutTee(sys.stdout, self._panel._output)
            sys.stdout = _stdout_tee
            logger.info("Stdout tee installed for print() capture")
        except Exception as exc:
            logger.warning("Could not install stdout tee: %s", exc)

        # Install stderr tee to capture Python logging output.
        # Same unwrap-all treatment as stdout above.
        if _stderr_tee is not None:
            _stderr_tee = None

        # Unwrap any stale tees on sys.stderr (from this or other module copies).
        raw_stderr = _unwrap_all_tees(sys.stderr)
        sys.stderr = raw_stderr

        try:
            _stderr_tee = _StderrTee(sys.stderr, self._panel._output)
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

            # Skip Python 3.11+ traceback caret indicator lines.
            # The session history buffer contains the raw "^" / "~" lines
            # that the live callback (_on_maya_output) filters out.  Strip
            # the optional Maya echo prefix ("# ") before checking so we
            # also catch "# ^^^^" style echo lines.
            clean = stripped
            if clean.startswith("#"):
                clean = clean[1:].strip()
            if clean and all(c in "^~" for c in clean):
                continue

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

    def _on_maya_output(self, message, message_type, client_data):
        """
        Callback fired by Maya for every line of command output.

        This is the sole source of stdout-related output for the MCA
        Editor output panel.  ``MCommandMessage.addCommandOutputCallback``
        captures everything Maya's Script Editor shows: ``print()``
        output, MEL echo, ``cmds.warning()``, ``cmds.error()``, command
        results, and ``MGlobal.displayInfo()``.

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

        # Skip Python 3.11+ traceback caret indicator lines.
        # Maya fires one callback per character for the "^^^^..." underline
        # lines in modern tracebacks, producing dozens of single-character
        # "^" or "~" messages that clutter the output as blank-looking lines.
        stripped_check = message.strip()
        if stripped_check and all(c in "^~" for c in stripped_check):
            return

        # Skip bare "#" echo lines — these are the Maya echo of caret
        # indicator lines that we already filtered above.  A standalone
        # "#" with no text after it is never meaningful user output.
        if stripped_check == "#":
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
            output = self._panel._output

            # Route to the appropriate output method based on message type.
            # Color coding: red for errors, orange for warnings, yellow for
            # results, blue for info, white for display (print output).
            if message_type == om2.MCommandMessage.kError:
                output.write_error(text)

            elif message_type == om2.MCommandMessage.kWarning:
                output.write_warning(text)

            elif message_type == om2.MCommandMessage.kResult:
                output.write_result(text)

            elif message_type == om2.MCommandMessage.kInfo:
                output.write_info(text)

            else:
                # kDisplay — all print() output, MEL echo, and Maya
                # C++ system messages.  This is the sole path to the
                # output panel for stdout content; _StdoutTee only
                # forwards to Maya's original OutputRedirector.
                stripped = text.strip()

                # Strip leading "# " echo prefix so content detection
                # works on both echo lines and non-echo lines.
                clean = stripped
                if clean.startswith("#"):
                    clean = clean[1:].lstrip()

                # --- Traceback echo suppression ---
                # When a traceback is active, _StderrTee handles the
                # properly formatted + colored version.  Suppress the
                # kDisplay duplicate (both echo and non-echo copies)
                # to avoid doubled output in the panel.
                if "Traceback (most recent call last)" in stripped:
                    self._in_traceback_echo = True
                    return
                if self._in_traceback_echo:
                    # Detect the end of the traceback: the exception line
                    # (non-empty, non-indented, contains Error/Exception).
                    if clean and not clean.startswith(("File ", " ")):
                        if "Error" in clean or "Exception" in clean:
                            self._in_traceback_echo = False
                    # Suppress this line — stderr tee has it covered.
                    return

                # --- Content-based routing for kDisplay ---
                # Detect result-formatted output from our internal adapter.
                # Maya's C++ displayResult (kResult) is not exposed in
                # Python API 2.0, so the adapter prints results as
                # "# Result: <value> #" via print().
                if stripped.startswith("# Result:") and stripped.endswith("#"):
                    output.write_result(text)
                # Detect warnings printed via print() or framework loggers
                # that Maya routes through kDisplay instead of kWarning.
                elif "WARNING:" in clean or "Warning:" in clean:
                    output.write_warning(text)
                # Detect errors printed via print() or framework loggers
                # that Maya routes through kDisplay instead of kError.
                elif "ERROR:" in clean or "Error:" in clean:
                    output.write_error(text)
                else:
                    output.write_output(text)

            # Force-flush and repaint immediately so output appears in
            # real-time during code execution.  Without this, the 16ms
            # QTimer can't fire while exec() blocks the event loop, and
            # all output would dump at once when execution finishes.
            output.flush()

        except Exception:
            # Widget already deleted or other error — silently ignore.
            # Must catch broadly: RuntimeError from shiboken (dead C++ object),
            # AttributeError if panel is partially torn down, etc.
            # An unhandled exception here cascades through Maya's callback
            # dispatcher and can crash the session or silently remove
            # the callback, killing all future output capture.
            pass

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

        # Trial days remaining indicator — checks license status at build
        # time and shows the indicator if the user is on a trial (no key).
        # Yellow for > 5 days, red for <= 5 days.
        self._trial_indicator = QLabel("")
        self._trial_indicator.setVisible(False)
        bar_layout.addWidget(self._trial_indicator)

        # Check trial status now and show indicator if applicable.
        self._check_trial_for_status_bar()

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

    def show_trial_indicator(self, days_remaining):
        """
        Show the trial days-remaining indicator in the status bar.

        Uses yellow text for > 5 days remaining and red for <= 5 days
        to create urgency as the trial nears expiration.

        :param int days_remaining: Days left in the trial period.
        """
        if days_remaining <= 5:
            color = "#ff4444"
        else:
            color = "#ffcc00"

        self._trial_indicator.setText(
            "TRIAL: {} days left".format(days_remaining)
        )
        self._trial_indicator.setStyleSheet(
            "color: {}; padding: 0 8px; font-size: 11px; font-weight: bold;"
            .format(color)
        )
        self._trial_indicator.setVisible(True)

    def _check_trial_for_status_bar(self):
        """
        Check license/trial status and show the trial indicator if needed.

        Called once during ``_build_status_bar()``.  If the user has a
        valid license key, the indicator stays hidden.  If on trial,
        shows the days remaining with urgency-based coloring.
        """
        try:
            from mca_core.license import check_license
            from mca_core.config.settings import MCASettings
            import maya.cmds as _cmds

            # Get Maya version directly — avoids cross-module global import
            # issues with compiled .pyd modules.
            maya_ver = _cmds.about(version=True)
            _app = "MCAEditor-Maya{}".format(maya_ver) if maya_ver else "MCAEditor"
            settings = MCASettings(app_name=_app)
            status = check_license(settings)

            # Show indicator when on trial OR when trial expired (no license).
            # Hide it when the user is licensed (e.g. after mid-session activation).
            if status["licensed"]:
                self._trial_indicator.setVisible(False)
            elif status["trial"]:
                self.show_trial_indicator(status["days_remaining"])
            elif status["needs_key"]:
                # Trial expired — show 0 days to make it obvious.
                self.show_trial_indicator(0)
        except Exception as exc:
            logger.warning("Trial status bar check failed: %s", exc)

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

        Removes the output hook, stderr tee, hotkey filter, saves state,
        and cleans up.  Sets ``editor_was_open`` to False so the editor
        stays closed on next Maya launch (user explicitly closed it).
        """
        global _output_callback_id, _stderr_tee, _stdout_tee

        # Block close events while a project shutdown script is running.
        # Some frameworks (e.g. MCACloud) call close_all_mca_windows()
        # during shutdown, which matches "MCA" in the window title and
        # tries to destroy the editor mid-teardown.  Ignore the close
        # and let _close_project finish cleanly.
        if getattr(self, "_shutdown_script_running", False):
            logger.info("dockCloseEventTriggered blocked — shutdown script running")
            return

        # Record that the user explicitly closed the editor — don't auto-open
        # on next Maya launch.
        self._settings.set("editor_was_open", False)

        # Remove the Maya output hook so we stop receiving messages.
        if _output_callback_id is not None:
            try:
                om2.MMessage.removeCallback(_output_callback_id)
                logger.info("Maya output hook removed")
            except Exception:
                pass
            _output_callback_id = None

        # Restore original stdout — unwrap ALL tee layers (not just one).
        # The dual module import problem can leave stale tees from other
        # module copies in the chain.  _unwrap_all_tees() walks the full
        # chain by class name and returns Maya's raw Output at the bottom.
        if _stdout_tee is not None:
            _stdout_tee = None
        raw_stdout = _unwrap_all_tees(sys.stdout)
        sys.stdout = raw_stdout

        # Restore original stderr — same unwrap-all treatment.
        if _stderr_tee is not None:
            _stderr_tee = None
        raw_stderr = _unwrap_all_tees(sys.stderr)
        sys.stderr = raw_stderr

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

def _open_command_ports():
    """
    Open Maya's MEL (7001) and Python (7002) command ports.

    Called once during editor startup.  ``RuntimeError`` from
    ``commandPort`` means the port is already open — that is fine.
    Any other exception is logged as a debug-level message because
    some Maya versions silently refuse ports during early startup.
    """
    for port, src_type in [("7001", "mel"), ("7002", "python")]:
        port_name = ":{}".format(port)
        try:
            cmds.commandPort(name=port_name, sourceType=src_type, echoOutput=True)
            logger.info("Opened %s command port %s", src_type, port_name)
        except RuntimeError:
            # RuntimeError means the port is already open — that's fine.
            logger.debug("Command port %s already open", port_name)
        except Exception as exc:
            logger.debug("Command port %s not ready yet: %s", port_name, exc)


_command_ports_opened = False


def _ensure_command_ports():
    """
    Open Maya's MEL (7001) and Python (7002) command ports if not already done.

    The MCP server runs as a separate process and communicates with Maya
    over TCP on port 7002.  These ports must be open for Claude Code's
    MCP tools to work.

    Maya's networking may not be ready during early startup (plugin init,
    layout restore).  A single deferred retry at 5 s covers slow starts.
    A module-level flag prevents duplicate attempts when called from both
    ``show_mca_editor()`` and ``_restore_mca_editor()``.
    """
    global _command_ports_opened

    if _command_ports_opened:
        return
    _command_ports_opened = True

    # Try immediately — works most of the time.
    _open_command_ports()

    # One deferred retry for slow Maya startups where networking
    # is not ready yet during plugin init.
    QTimer.singleShot(5000, _open_command_ports)


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

    # Use version-specific settings for the license check too.
    from mca_maya.plugin_main import _maya_version as _mv
    _lc_tag = "Maya{}".format(_mv) if _mv else None
    _lc_app = "MCAEditor-{}".format(_lc_tag) if _lc_tag else "MCAEditor"
    _license_settings = MCASettings(app_name=_lc_app)
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
    MCASettings(app_name=_lc_app).set("editor_was_open", True)

    # Show trial notice on the Maya status bar if in trial mode.
    if _show_license_notice and _license_message:
        _mca_editor_window._on_status_message(_license_message, 10000)

    # --- One-time update check -----------------------------------------------
    # Check if a newer version is available (background thread, non-blocking).
    # If online and an update exists, show a yellow warning in the output panel.
    # If offline or up-to-date, nothing is printed.
    try:
        from mca_core.version_check import check_for_update

        # Capture the window ref for the closure — the global may change.
        _update_win = _mca_editor_window

        def _on_update_available(version, url):
            """Write update notification to the output panel from the main thread."""
            QTimer.singleShot(0, lambda: _update_win._panel._output.write_warning(
                "MCA Editor v{} is available.  Download at: {}".format(version, url)
            ))

        check_for_update(_on_update_available)
    except Exception as exc:
        logger.debug("Update check setup failed: %s", exc)

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

    # If the user explicitly closed the editor last session, don't
    # re-create it just because Maya's workspace layout still has the
    # control.  Delete the stale workspace control and bail out.
    from mca_core.config.settings import MCASettings
    from mca_maya.plugin_main import _maya_version
    _app = "MCAEditor-Maya{}".format(_maya_version) if _maya_version else "MCAEditor"
    if not MCASettings(app_name=_app).get("editor_was_open", False):
        logger.info("editor_was_open is False — skipping uiScript restore")
        try:
            if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, q=True, exists=True):
                cmds.workspaceControl(WORKSPACE_CONTROL_NAME, e=True, visible=False)
        except Exception:
            pass
        return

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
    global _stderr_tee
    global _stdout_tee

    # Remove Maya output hook — this is an OpenMaya callback, safe
    # to remove during shutdown (not a Qt operation).
    if _output_callback_id is not None:
        try:
            om2.MMessage.removeCallback(_output_callback_id)
        except Exception:
            pass
        _output_callback_id = None

    # Restore original stdout — unwrap ALL tee layers (not just one).
    # The dual module import problem can leave stale tees from other
    # module copies in the chain.  _unwrap_all_tees() walks the full
    # chain by class name and returns Maya's raw Output at the bottom.
    if _stdout_tee is not None:
        _stdout_tee = None
    raw_stdout = _unwrap_all_tees(sys.stdout)
    sys.stdout = raw_stdout

    # Restore original stderr — same unwrap-all treatment.
    if _stderr_tee is not None:
        _stderr_tee = None
    raw_stderr = _unwrap_all_tees(sys.stderr)
    sys.stderr = raw_stderr

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
