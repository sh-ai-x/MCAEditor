"""
Enter-key auto-indent behaviour for ``MCACodeEditor``.

Drives a real editor widget offscreen, places the cursor at specific
positions, presses Enter, and asserts on the resulting buffer.

The regression this guards: ``_handle_newline`` used to derive both the
indentation and the "is this a block opener" check from the *whole* line
rather than the text left of the cursor.  Pressing Enter at the start of
a ``def`` or ``class`` line therefore saw the trailing colon and indented
the definition itself, so inserting a blank line above a function shoved
the function one level to the right.

Runs headless -- no DCC, no user settings touched.

Usage:
    python tests/test_editor_indent.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Run from anywhere -- resolve the project root relative to this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mca_qt.qt_compat import QApplication, QTextCursor
from mca_qt.widgets.code_editor import MCACodeEditor

# A single QApplication serves every check.
_app = QApplication.instance() or QApplication(sys.argv)

# Labels of checks that did not match, reported together at the end.
FAILURES = []


def press_enter(text, line, column, language="python",
                use_spaces=True, select_to=None):
    """
    Load *text* into a fresh editor, position the cursor, press Enter.

    :param str text: Initial buffer contents.
    :param int line: Zero-based block index to place the cursor on.
    :param int column: Column within that block.
    :param str language: Editor language mode (``"python"`` or ``"mel"``).
    :param bool use_spaces: Indent with spaces (True) or a tab (False).
    :param tuple select_to: Optional ``(line, column)`` to extend the
        selection to, so the Enter replaces the selected text.
    :return: Buffer contents after the keypress.
    :rtype: str
    """
    editor = MCACodeEditor()
    editor.set_language(language)
    editor._use_spaces = use_spaces
    editor.setPlainText(text)

    document = editor.document()
    cursor = editor.textCursor()
    cursor.setPosition(document.findBlockByNumber(line).position() + column)

    # Extend the selection when the caller wants the Enter to replace text.
    if select_to is not None:
        end_line, end_column = select_to
        end_block = document.findBlockByNumber(end_line)
        cursor.setPosition(
            end_block.position() + end_column, QTextCursor.MoveMode.KeepAnchor
        )

    editor.setTextCursor(cursor)
    editor._handle_newline()
    return editor.toPlainText()


def check(label, got, want):
    """
    Compare *got* against *want* and record the outcome.

    :param str label: Human-readable description of the check.
    :param str got: Actual buffer contents.
    :param str want: Expected buffer contents.
    """
    if got == want:
        print("PASS   %s" % label)
        return
    print("FAIL   %s" % label)
    print("         want: %r" % want)
    print("         got : %r" % got)
    FAILURES.append(label)


def run():
    """Execute every auto-indent check and exit non-zero on failure."""

    # --- the reported bug -------------------------------------------------
    check(
        "Enter at col 0 of a def does not indent the def",
        press_enter("def foo():\n    pass\n", 0, 0),
        "\ndef foo():\n    pass\n",
    )
    check(
        "Enter at col 0 of a class does not indent the class",
        press_enter("class Foo:\n    pass\n", 0, 0),
        "\nclass Foo:\n    pass\n",
    )
    check(
        "Enter at start of an indented def keeps its indent",
        press_enter("class Foo:\n    def bar(self):\n        pass\n", 1, 4),
        "class Foo:\n    \n    def bar(self):\n        pass\n",
    )
    check(
        "Enter at col 0 of an indented statement keeps its indent",
        press_enter("def foo():\n    x = 1\n", 1, 0),
        "def foo():\n\n    x = 1\n",
    )

    # --- behaviour that must not regress ----------------------------------
    check(
        "Enter at end of a def still indents the new line",
        press_enter("def foo():", 0, 10),
        "def foo():\n    ",
    )
    check(
        "Enter at end of a class still indents the new line",
        press_enter("class Foo:", 0, 10),
        "class Foo:\n    ",
    )
    check(
        "Enter at end of an indented body preserves indent",
        press_enter("def foo():\n    x = 1", 1, 9),
        "def foo():\n    x = 1\n    ",
    )
    check(
        "Enter mid-line before the colon does not add a level",
        press_enter("def foo():", 0, 8),
        "def foo(\n):",
    )
    check(
        "Enter mid-body splits at the current indent",
        press_enter("    x = 1 + 2", 0, 9),
        "    x = 1\n     + 2",
    )
    check(
        "Enter on an empty line inserts an empty line",
        press_enter("", 0, 0),
        "\n",
    )

    # --- tab-indent mode --------------------------------------------------
    check(
        "tabs: Enter at end of a def indents with a tab",
        press_enter("def foo():", 0, 10, use_spaces=False),
        "def foo():\n\t",
    )
    check(
        "tabs: Enter at col 0 of a def does not indent it",
        press_enter("def foo():", 0, 0, use_spaces=False),
        "\ndef foo():",
    )

    # --- MEL braces -------------------------------------------------------
    check(
        "MEL: Enter at end of a brace line indents",
        press_enter("global proc foo() {", 0, 19, language="mel"),
        "global proc foo() {\n    ",
    )
    check(
        "MEL: Enter at col 0 of a brace line does not indent it",
        press_enter("global proc foo() {", 0, 0, language="mel"),
        "\nglobal proc foo() {",
    )

    # --- Enter over a selection -------------------------------------------
    # The selection is replaced, so the new line begins where the
    # selection *starts*.  A forward selection leaves the cursor position
    # at the far end, so reading the block under the cursor would look at
    # the wrong line entirely.
    #
    # Here the selection ends on "def foo():" while starting on "x = 1".
    # Keying off the cursor would see the trailing colon and indent; the
    # selection start correctly says no indent.
    check(
        "Enter over a selection ending on a def does not add an indent",
        press_enter("x = 1\ndef foo():\n", 0, 5, select_to=(1, 10)),
        "x = 1\n\n",
    )
    check(
        "Enter over a selection keeps the selection-start line's indent",
        press_enter("    x = 1\n    y = 2\n", 0, 8, select_to=(1, 8)),
        "    x = \n    2\n",
    )

    print()
    if FAILURES:
        print("%d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("=" * 60)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    run()
