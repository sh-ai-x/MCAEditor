"""
Regression test for Ctrl+V routing in the Maya hotkey filter.

This test exercises the paste-routing logic that governs where Ctrl+V
lands when the MCA Editor is running inside Maya.  It has regressed
multiple times — specifically after Claude Code chats where focus
drifts away from the terminal, paste starts going to the code editor
instead of the terminal the user actually clicked.

The test does NOT run Maya.  It builds a minimal Qt widget tree that
mimics the panel structure (terminal display inside a TerminalWidget
inside a target window, plus a separate code-editor widget), then
drives the hotkey filter through every known regression scenario:

    1. Click terminal → Ctrl+V goes to terminal.
    2. Click terminal, focus drifts to code editor programmatically
       (as happens when MCP tools call setFocus) → Ctrl+V still goes
       to the terminal.
    3. Click terminal, then click code editor → Ctrl+V goes to code
       editor (user moved on).
    4. Click terminal, terminal becomes hidden → Ctrl+V does NOT route
       to a hidden terminal.
    5. Focus is on a non-text widget (sidebar) with `_last_terminal_widget`
       tracked — Ctrl+V still reaches the tracked terminal.

Run with::

    python tools/test_ctrl_v_routing.py

Dependencies:
    - PySide6 (or PySide2) — the qt_compat layer resolves which.

:author: MCA Editor maintainers
"""

import sys
import os

# Make repo imports work when executed directly.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from PySide6.QtCore import QEvent, Qt, QPoint
    from PySide6.QtGui import QMouseEvent, QKeyEvent
    from PySide6.QtWidgets import QApplication, QWidget, QPlainTextEdit, QVBoxLayout
except ImportError:
    from PySide2.QtCore import QEvent, Qt, QPoint
    from PySide2.QtGui import QMouseEvent, QKeyEvent
    from PySide2.QtWidgets import QApplication, QWidget, QPlainTextEdit, QVBoxLayout


# --- Fake TerminalWidget ----------------------------------------------------

# NOTE: The class name must match "TerminalWidget" because the hotkey
# filter's _find_parent_terminal() falls back to a class-name check
# when isinstance() misses (dual-import hardening).  We want the test
# to exercise the name-based path anyway, so naming this exactly
# `TerminalWidget` ensures the match succeeds.
class TerminalWidget(QWidget):
    """
    Minimal stand-in for ``mca_qt.widgets.terminal_native.TerminalWidget``.

    The real class imports Maya-side modules; we reproduce only the
    attributes the hotkey filter interacts with so we can assert paste
    routing without spinning up a real shell.

    :ivar bool _alive: Liveness flag (mirrors TerminalWidget._alive).
    :ivar int paste_calls: Count of ``paste_clipboard()`` invocations.
    :ivar QPlainTextEdit _display: The "display" widget focus lands on.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alive = True
        self.paste_calls = 0
        # Build a QPlainTextEdit as the focus target, mirroring the
        # real terminal widget's internal structure.
        layout = QVBoxLayout(self)
        self._display = QPlainTextEdit(self)
        self._display.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self._display)

    def paste_clipboard(self):
        """
        Record that paste was dispatched to this terminal.

        :return: True (success).
        :rtype: bool
        """
        self.paste_calls += 1
        return True

    def eventFilter(self, obj, event):
        """
        Stub eventFilter. Returns True for Ctrl+V to simulate a successful
        paste handled at the display level.  Matches the real terminal's
        eventFilter contract.

        :param QObject obj: Source object.
        :param QEvent event: Event to filter.
        :return: True if the event was consumed.
        :rtype: bool
        """
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_V and (
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                return bool(self.paste_clipboard())
        return False


# --- Test harness -----------------------------------------------------------

def _build_filter_with_tree():
    """
    Construct a widget tree and a _MayaHotkeyFilter instance bound to it.

    We must import maya_window in a way that doesn't drag in real Maya
    modules.  The module top-level imports ``maya.cmds`` so we stub it
    first.  The ``_MayaHotkeyFilter`` class itself only touches
    QWidget / QApplication / our target / a tiny panel shim.

    :return: Tuple of (app, target_window, terminal, code_editor, filt, panel_shim).
    :rtype: tuple
    """
    # Stub Maya modules before importing maya_window.
    import types
    for name in ("maya", "maya.cmds", "maya.api", "maya.api.OpenMaya",
                 "maya.app", "maya.app.general", "maya.app.general.mayaMixin"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    # Use a plain object as the dockable mixin stub — QWidget would
    # cause a duplicate-base-class TypeError in MCAMayaWindow's MRO.
    class _DockableMixin:
        pass
    sys.modules["maya.app.general.mayaMixin"].MayaQWidgetDockableMixin = _DockableMixin

    # Stub the other heavy imports from maya_window too.
    # The filter class doesn't touch these, but module top-level does.
    for modname, attrs in [
        ("mca_qt.editor_panel", {"MCAEditorPanel": QWidget}),
        ("mca_qt.icons", {"mca_logo": lambda: None}),
        ("mca_qt.theme", {"GLOBAL_STYLESHEET": ""}),
        ("mca_core.adapters.adapter_manager", {"AdapterManager": object}),
        ("mca_core.adapters.internal_maya_adapter", {"InternalMayaAdapter": object}),
        ("mca_core.config.settings", {"MCASettings": object}),
    ]:
        if modname not in sys.modules:
            m = types.ModuleType(modname)
            for k, v in attrs.items():
                setattr(m, k, v)
            sys.modules[modname] = m

    from mca_maya.maya_window import _MayaHotkeyFilter  # noqa: E402

    # Ensure a QApplication exists.
    app = QApplication.instance() or QApplication(sys.argv)

    # Build the widget tree.
    target = QWidget()
    target_layout = QVBoxLayout(target)

    terminal = TerminalWidget(target)
    target_layout.addWidget(terminal)

    code_editor = QPlainTextEdit(target)
    code_editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    target_layout.addWidget(code_editor)

    # A non-text widget to stand in for a sidebar / tab bar / etc.
    sidebar = QWidget(target)
    sidebar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    target_layout.addWidget(sidebar)

    target.show()
    QApplication.processEvents()

    # Minimal panel shim: the filter calls panel._current_editor()
    # and panel._action_registry in various places.
    class _PanelShim:
        _action_registry = {}
        def _current_editor(self_):
            return code_editor

    panel = _PanelShim()
    filt = _MayaHotkeyFilter(target, panel)

    return app, target, terminal, code_editor, sidebar, filt


def _send_click(widget):
    """
    Simulate a left mouse button press on *widget* by invoking the
    filter's eventFilter directly with a synthetic QMouseEvent.  This
    bypasses the whole Qt event-loop indirection so tests stay fast
    and deterministic.

    :param QWidget widget: The widget to "click".
    """
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPoint(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    # The filter is installed on target; we simulate by calling
    # eventFilter with watched=widget.
    return event


def _send_ctrl_v():
    """
    Build a Ctrl+V QKeyEvent for driving the filter.

    :return: The key press event.
    :rtype: QKeyEvent
    """
    return QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier,
        "v",
    )


# --- Individual test cases --------------------------------------------------

def test_click_terminal_then_paste():
    """Baseline: click terminal, press Ctrl+V, expect paste to terminal."""
    app, target, terminal, editor, sidebar, filt = _build_filter_with_tree()
    # Simulate the click on the terminal's display.
    filt.eventFilter(terminal._display, _send_click(terminal._display))
    assert filt._last_terminal_widget is terminal._display, (
        "Expected _last_terminal_widget to track the terminal click"
    )
    terminal._display.setFocus()
    QApplication.processEvents()
    filt.eventFilter(terminal._display, _send_ctrl_v())
    assert terminal.paste_calls >= 1, (
        "Expected paste to reach terminal after direct click + focus"
    )


def test_focus_drifts_to_editor_after_terminal_click():
    """
    Regression: user clicks terminal, then an MCP tool programmatically
    focuses the code editor.  Ctrl+V must still route to the terminal.
    """
    app, target, terminal, editor, sidebar, filt = _build_filter_with_tree()
    filt.eventFilter(terminal._display, _send_click(terminal._display))
    # Simulate programmatic focus transfer (what editor_open_file does).
    editor.setFocus()
    QApplication.processEvents()
    before = terminal.paste_calls
    filt.eventFilter(editor, _send_ctrl_v())
    assert terminal.paste_calls > before, (
        "Expected paste to reach terminal even though focus drifted to "
        "the code editor — this is the Claude-Code regression path"
    )


def test_click_editor_after_terminal_stomps_tracker():
    """
    If the user clicks a code editor after clicking the terminal,
    Ctrl+V should paste into the editor — they've moved on.
    """
    app, target, terminal, editor, sidebar, filt = _build_filter_with_tree()
    filt.eventFilter(terminal._display, _send_click(terminal._display))
    filt.eventFilter(editor, _send_click(editor))
    assert filt._last_terminal_widget is None, (
        "Expected _last_terminal_widget to clear after non-terminal click"
    )
    editor.setFocus()
    QApplication.processEvents()
    before = terminal.paste_calls
    filt.eventFilter(editor, _send_ctrl_v())
    assert terminal.paste_calls == before, (
        "Ctrl+V should NOT route to the terminal after the user clicks "
        "into the code editor"
    )


def test_hidden_terminal_is_ignored():
    """
    If the tracked terminal was hidden (e.g. terminal panel collapsed),
    Ctrl+V should NOT route to it.
    """
    app, target, terminal, editor, sidebar, filt = _build_filter_with_tree()
    filt.eventFilter(terminal._display, _send_click(terminal._display))
    terminal.setVisible(False)
    QApplication.processEvents()
    editor.setFocus()
    QApplication.processEvents()
    before = terminal.paste_calls
    filt.eventFilter(editor, _send_ctrl_v())
    assert terminal.paste_calls == before, (
        "Hidden terminal must not steal paste events"
    )


def test_backstop_routes_from_non_text_focus():
    """
    Focus on a sidebar (non-text widget), `_last_terminal_widget` still
    tracked — Ctrl+V must reach the tracked terminal via the backstop.
    """
    app, target, terminal, editor, sidebar, filt = _build_filter_with_tree()
    filt.eventFilter(terminal._display, _send_click(terminal._display))
    sidebar.setFocus()
    QApplication.processEvents()
    before = terminal.paste_calls
    filt.eventFilter(sidebar, _send_ctrl_v())
    assert terminal.paste_calls > before, (
        "Expected backstop to route Ctrl+V to the tracked terminal when "
        "focus is on a non-text widget"
    )


# --- Runner -----------------------------------------------------------------

def _run():
    """
    Execute all tests, printing PASS/FAIL for each.

    :return: Exit code (0 on success, 1 on any failure).
    :rtype: int
    """
    tests = [
        test_click_terminal_then_paste,
        test_focus_drifts_to_editor_after_terminal_click,
        test_click_editor_after_terminal_stomps_tracker,
        test_hidden_terminal_is_ignored,
        test_backstop_routes_from_non_text_focus,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS:", t.__name__)
        except AssertionError as exc:
            print("FAIL:", t.__name__, "-", exc)
            failed += 1
        except Exception as exc:
            print("ERROR:", t.__name__, "-", type(exc).__name__, exc)
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run())
