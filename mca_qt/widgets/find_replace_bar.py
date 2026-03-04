"""
MCA Editor - Find/Replace Bar Widget (PyCharm-Style).

Horizontal bar inserted between the toolbar and the editor/output splitter.
Provides incremental search with match highlighting, navigation, and
replace/replace-all operations. Supports match-case, whole-word, and
regex toggle modes.

Layout mirrors PyCharm's find/replace UX:
    [v] [Find: ________(x)] [Cc] [W] [.*]  3/15  [^] [v]  [X]
        [Replace: ____(x)]  [Replace] [Replace All]

Dependencies:
    - PySide6 (or PySide2 via qt_compat shim)
"""

import re
import logging

from mca_qt.qt_compat import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QLabel,
    Qt, Signal, QTimer, QColor, QTextCursor, QTextEdit,
    QEvent,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Highlight Colors -------------------------------------------------------

# Subtle background for all matches in the document.
MATCH_HIGHLIGHT_COLOR = QColor(80, 80, 40)

# Brighter background for the currently focused match.
CURRENT_MATCH_COLOR = QColor(120, 120, 50)


# =============================================================================
# Shared Stylesheet
# =============================================================================

# Dark-theme styles shared across all bar controls.
# The background must be fully opaque since this renders as an overlay
# on top of the editor content.
_BAR_STYLE = """
    QWidget#FindReplaceBar {
        background-color: #2d2d30;
        border: 1px solid #3f3f46;
        border-radius: 4px;
    }
    QLineEdit {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 3px 6px;
        font-size: 12px;
        min-width: 180px;
    }
    QLineEdit:focus {
        border: 1px solid #007acc;
    }
    QPushButton {
        background: transparent;
        color: #cccccc;
        border: none;
        border-radius: 3px;
        padding: 3px 8px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #3e3e42;
    }
    QPushButton:pressed {
        background-color: #094771;
    }
    QPushButton:checked {
        background-color: #094771;
        color: #ffffff;
    }
    QLabel {
        color: #969696;
        font-size: 11px;
    }
"""


# =============================================================================
# FindReplaceBar
# =============================================================================

class FindReplaceBar(QWidget):
    """
    Compact find/replace bar for the MCA Editor (PyCharm-style layout).

    Sits between the toolbar and the editor splitter. Hidden by default;
    shown via ``show_find()`` or ``show_replace()``.

    The expand/collapse arrow on the far left toggles the replace row.
    Toggle buttons (Cc, W, .*) sit after the find field, followed by
    a match counter and up/down navigation arrows.

    Signals:
        search_selections_changed(list): Emitted with a list of
            QTextEdit.ExtraSelection items whenever the match set changes.
            The editor panel merges these into the active editor's
            extra-selections.
        closed(): Emitted when the bar is dismissed so the panel can
            return focus to the editor.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when match highlights need to be applied to the active editor.
    search_selections_changed = Signal(list)

    # Emitted when the bar is closed (Escape or X button).
    closed = Signal()

    # Emitted when the bar's height changes (e.g. replace row toggled)
    # so the parent can reposition the overlay.
    geometry_changed = Signal()

    def __init__(self, parent=None):
        """
        Initialize the find/replace bar.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("FindReplaceBar")

        # Ensure the overlay paints an opaque background so editor text
        # underneath doesn't show through.
        self.setAutoFillBackground(True)

        # --- State ---
        self._replace_visible = False  # Whether the replace row is shown.
        self._matches = []             # List of (start, length) tuples in the document.
        self._current_index = -1       # Index into _matches for the focused match.
        self._editor = None            # The active MCACodeEditor to search within.

        # --- Build UI ---
        self._setup_ui()
        self.setStyleSheet(_BAR_STYLE)

        # --- Debounce timer for incremental search ---
        # Delays search by 150ms after typing stops to avoid hammering
        # the document on every keystroke in large files.
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._do_search)

        # Start hidden.
        self.hide()

    # --- UI Construction -----------------------------------------------------

    def _setup_ui(self):
        """
        Build the PyCharm-style two-row layout.

        Row 1 (find):
            [expand_toggle] [find_input(x)] [Cc] [W] [.*] [counter] [up] [down] [close]
        Row 2 (replace, toggled by expand arrow):
            [spacer]        [replace_input(x)] [Replace] [Replace All]
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        # --- Find Row ---
        find_row = QHBoxLayout()
        find_row.setSpacing(4)

        # Expand/collapse toggle arrow — controls replace row visibility.
        # Shows ">" when collapsed, "v" when expanded.
        self._expand_btn = QPushButton("\u25b6")  # Right-pointing triangle
        self._expand_btn.setFixedSize(20, 24)
        self._expand_btn.setToolTip("Toggle Replace (Ctrl+H)")
        self._expand_btn.clicked.connect(self._toggle_replace_row)
        find_row.addWidget(self._expand_btn)

        # Find input field with built-in clear button.
        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("Find")
        self._find_input.setClearButtonEnabled(True)
        self._find_input.textChanged.connect(self._on_find_text_changed)
        self._find_input.returnPressed.connect(self._find_next)
        find_row.addWidget(self._find_input, 1)

        # --- Toggle option buttons (checkable) — sit after the find field ---

        self._case_btn = QPushButton("Cc")
        self._case_btn.setToolTip("Match Case")
        self._case_btn.setCheckable(True)
        self._case_btn.setFixedSize(28, 24)
        self._case_btn.toggled.connect(self._on_option_changed)
        find_row.addWidget(self._case_btn)

        self._word_btn = QPushButton("W")
        self._word_btn.setToolTip("Whole Word")
        self._word_btn.setCheckable(True)
        self._word_btn.setFixedSize(28, 24)
        self._word_btn.toggled.connect(self._on_option_changed)
        find_row.addWidget(self._word_btn)

        self._regex_btn = QPushButton(".*")
        self._regex_btn.setToolTip("Regex")
        self._regex_btn.setCheckable(True)
        self._regex_btn.setFixedSize(28, 24)
        self._regex_btn.toggled.connect(self._on_option_changed)
        find_row.addWidget(self._regex_btn)

        # Results counter label ("3/15" format).
        self._counter_label = QLabel("")
        self._counter_label.setMinimumWidth(50)
        find_row.addWidget(self._counter_label)

        # Previous match (up arrow).
        self._prev_btn = QPushButton("\u2191")  # Up arrow
        self._prev_btn.setToolTip("Previous Match (Shift+Enter)")
        self._prev_btn.setFixedSize(28, 24)
        self._prev_btn.clicked.connect(self._find_prev)
        find_row.addWidget(self._prev_btn)

        # Next match (down arrow).
        self._next_btn = QPushButton("\u2193")  # Down arrow
        self._next_btn.setToolTip("Next Match (Enter)")
        self._next_btn.setFixedSize(28, 24)
        self._next_btn.clicked.connect(self._find_next)
        find_row.addWidget(self._next_btn)

        # Close button on the far right.
        self._close_btn = QPushButton("\u2715")  # Multiplication X
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setToolTip("Close (Escape)")
        self._close_btn.clicked.connect(self.dismiss)
        find_row.addWidget(self._close_btn)

        outer.addLayout(find_row)

        # --- Replace Row (hidden until toggled) ---
        self._replace_row_widget = QWidget()
        replace_row = QHBoxLayout(self._replace_row_widget)
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.setSpacing(4)

        # Spacer to align replace field under the find field.
        # Matches the width of the expand button.
        spacer = QWidget()
        spacer.setFixedWidth(24)
        replace_row.addWidget(spacer)

        # Replace input field with built-in clear button.
        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("Replace")
        self._replace_input.setClearButtonEnabled(True)
        replace_row.addWidget(self._replace_input, 1)

        # Replace / Replace All buttons.
        self._replace_btn = QPushButton("Replace")
        self._replace_btn.setToolTip("Replace current match")
        self._replace_btn.clicked.connect(self._replace_current)
        replace_row.addWidget(self._replace_btn)

        self._replace_all_btn = QPushButton("Replace All")
        self._replace_all_btn.setToolTip("Replace all matches")
        self._replace_all_btn.clicked.connect(self._replace_all)
        replace_row.addWidget(self._replace_all_btn)

        self._replace_row_widget.hide()
        outer.addWidget(self._replace_row_widget)

        # Install an event filter on both line edits to intercept Escape.
        # QLineEdit with setClearButtonEnabled(True) can consume Escape
        # to clear text, preventing it from propagating to our keyPressEvent.
        self._find_input.installEventFilter(self)
        self._replace_input.installEventFilter(self)

    # --- Event Filter --------------------------------------------------------

    def eventFilter(self, obj, event):
        """
        Intercept Escape on child QLineEdits to dismiss the bar.

        QLineEdit with clear-button-enabled may consume Escape internally
        to clear the text, preventing propagation to our keyPressEvent.
        This filter catches Escape before the QLineEdit processes it.

        :param QObject obj: The watched object.
        :param QEvent event: The event.
        :return: True if the event was handled.
        :rtype: bool
        """
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        return super().eventFilter(obj, event)

    # --- Replace Row Toggle --------------------------------------------------

    def _toggle_replace_row(self):
        """Toggle the replace row visibility and update the expand arrow."""
        self._replace_visible = not self._replace_visible
        self._replace_row_widget.setVisible(self._replace_visible)
        # Update arrow: down-pointing when expanded, right-pointing when collapsed.
        self._expand_btn.setText("\u25bc" if self._replace_visible else "\u25b6")
        # Notify the parent to reposition the overlay after height change.
        self.geometry_changed.emit()

    def _sync_expand_arrow(self):
        """
        Sync the expand arrow icon with the current replace-row visibility.

        Called when show_find/show_replace set the visibility directly.
        """
        self._expand_btn.setText("\u25bc" if self._replace_visible else "\u25b6")

    # --- Public API ----------------------------------------------------------

    def show_find(self, editor, selected_text=""):
        """
        Show the bar in find-only mode.

        Pre-fills the find field with *selected_text* if provided.

        :param MCACodeEditor editor: The editor to search within.
        :param str selected_text: Optional text to pre-fill the find field.
        """
        self._editor = editor
        self._replace_visible = False
        self._replace_row_widget.hide()
        self._sync_expand_arrow()
        self.show()
        # Ensure the overlay bar is above the editor content.
        self.raise_()
        if selected_text:
            self._find_input.setText(selected_text)
        self._find_input.setFocus()
        self._find_input.selectAll()
        # Kick off a search immediately if there's existing text.
        if self._find_input.text():
            self._do_search()

    def show_replace(self, editor, selected_text=""):
        """
        Show the bar in find+replace mode.

        Pre-fills the find field with *selected_text* if provided.

        :param MCACodeEditor editor: The editor to search within.
        :param str selected_text: Optional text to pre-fill the find field.
        """
        self._editor = editor
        self._replace_visible = True
        self._replace_row_widget.show()
        self._sync_expand_arrow()
        self.show()
        # Ensure the overlay bar is above the editor content.
        self.raise_()
        if selected_text:
            self._find_input.setText(selected_text)
        self._find_input.setFocus()
        self._find_input.selectAll()
        # Kick off a search immediately if there's existing text.
        if self._find_input.text():
            self._do_search()

    def set_editor(self, editor):
        """
        Switch the active editor (e.g. on tab change) and re-search.

        :param MCACodeEditor editor: The new active editor.
        """
        self._editor = editor
        # Re-run search against the new editor's content.
        if self.isVisible() and self._find_input.text():
            self._do_search()

    def dismiss(self):
        """
        Hide the bar, clear highlights, and return focus to the editor.
        """
        self.hide()
        self._matches = []
        self._current_index = -1
        self._counter_label.setText("")
        # Clear search highlights from the editor.
        self.search_selections_changed.emit([])
        self.closed.emit()

    # --- Key Handling --------------------------------------------------------

    def keyPressEvent(self, event):
        """
        Handle keyboard shortcuts within the find/replace bar.

        - Escape: dismiss the bar
        - Shift+Enter: find previous
        - Enter in replace field: replace current

        :param QKeyEvent event: The key event.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return

        # Shift+Enter in the find field -> find previous.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() == Qt.KeyboardModifier.ShiftModifier):
            self._find_prev()
            return

        # Enter in the replace field -> replace current.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and self._replace_input.hasFocus()):
            self._replace_current()
            return

        super().keyPressEvent(event)

    # --- Search Logic --------------------------------------------------------

    def _on_find_text_changed(self, text):
        """
        Restart the debounce timer whenever the find text changes.

        :param str text: The current find field text (unused directly).
        """
        self._search_timer.start()

    def _on_option_changed(self, _checked):
        """
        Re-run the search when a toggle option (case/word/regex) changes.

        :param bool _checked: The new checked state (unused).
        """
        self._do_search()

    def _build_pattern(self, search_text):
        """
        Compile a regex pattern from the search text and active options.

        :param str search_text: The raw search string from the find field.
        :return: Compiled regex pattern, or None if the text is empty
            or the regex is invalid.
        :rtype: re.Pattern or None
        """
        if not search_text:
            return None

        # Regex mode: use the raw text as a pattern.
        # Non-regex mode: escape so special chars are treated literally.
        if self._regex_btn.isChecked():
            pattern_str = search_text
        else:
            pattern_str = re.escape(search_text)

        # Whole-word mode: wrap in word boundaries.
        if self._word_btn.isChecked():
            pattern_str = r"\b" + pattern_str + r"\b"

        # Case sensitivity flag.
        flags = 0
        if not self._case_btn.isChecked():
            flags |= re.IGNORECASE

        try:
            return re.compile(pattern_str, flags)
        except re.error as exc:
            logger.debug("Invalid regex in find bar: %s", exc)
            return None

    def _do_search(self):
        """
        Run the search against the active editor's full document text.

        Builds a list of (start, length) match positions and emits
        highlight selections for the editor to display.
        """
        self._matches = []
        self._current_index = -1

        if not self._editor:
            self._update_counter()
            self.search_selections_changed.emit([])
            return

        search_text = self._find_input.text()
        pattern = self._build_pattern(search_text)

        if not pattern:
            self._update_counter()
            self.search_selections_changed.emit([])
            return

        # Search the full document text for all matches.
        doc_text = self._editor.toPlainText()
        for m in pattern.finditer(doc_text):
            self._matches.append((m.start(), m.end() - m.start()))

        # If there are matches, select the one closest to the cursor.
        if self._matches:
            cursor_pos = self._editor.textCursor().position()
            self._current_index = self._find_nearest_match(cursor_pos)

        self._update_counter()
        self._emit_highlights()

    def _find_nearest_match(self, cursor_pos):
        """
        Find the match index closest to (at or after) *cursor_pos*.

        :param int cursor_pos: The current cursor position in the document.
        :return: Index into self._matches for the nearest match.
        :rtype: int
        """
        for i, (start, _length) in enumerate(self._matches):
            if start >= cursor_pos:
                return i
        # Wrap around — all matches are before the cursor.
        return 0

    # --- Navigation ----------------------------------------------------------

    def _find_next(self):
        """Advance to the next match (wrapping at document end)."""
        if not self._matches:
            return
        self._current_index = (self._current_index + 1) % len(self._matches)
        self._select_current_match()
        self._update_counter()
        self._emit_highlights()

    def _find_prev(self):
        """Go to the previous match (wrapping at document start)."""
        if not self._matches:
            return
        self._current_index = (self._current_index - 1) % len(self._matches)
        self._select_current_match()
        self._update_counter()
        self._emit_highlights()

    def _select_current_match(self):
        """
        Move the editor cursor to select the current match.

        This makes the match visible in the viewport and allows the
        user to see exactly which occurrence is focused.
        """
        if not self._editor or self._current_index < 0:
            return

        start, length = self._matches[self._current_index]
        cursor = self._editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()

    # --- Replace -------------------------------------------------------------

    def _replace_current(self):
        """
        Replace the currently focused match and advance to the next one.
        """
        if not self._editor or not self._matches or self._current_index < 0:
            return

        start, length = self._matches[self._current_index]
        replacement = self._replace_input.text()

        # If regex mode is active and the pattern has capture groups,
        # allow backreferences (\1, \2, etc.) in the replacement string.
        if self._regex_btn.isChecked():
            search_text = self._find_input.text()
            pattern = self._build_pattern(search_text)
            if pattern:
                doc_text = self._editor.toPlainText()
                match = pattern.match(doc_text, start)
                if match:
                    replacement = match.expand(replacement)

        cursor = self._editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)

        # Re-search after replacement so all positions are recalculated.
        self._do_search()

        # If there are still matches, keep the current index in range.
        if self._matches:
            if self._current_index >= len(self._matches):
                self._current_index = 0
            self._select_current_match()

    def _replace_all(self):
        """
        Replace all matches in a single undo step.

        Uses beginEditBlock/endEditBlock so the user can revert
        everything with a single Ctrl+Z.
        """
        if not self._editor or not self._matches:
            return

        replacement = self._replace_input.text()
        search_text = self._find_input.text()
        pattern = self._build_pattern(search_text)

        cursor = self._editor.textCursor()
        cursor.beginEditBlock()

        # Replace in reverse order so earlier positions aren't shifted.
        for start, length in reversed(self._matches):
            # Resolve regex backreferences if applicable.
            actual_replacement = replacement
            if self._regex_btn.isChecked() and pattern:
                doc_text = self._editor.toPlainText()
                match = pattern.match(doc_text, start)
                if match:
                    actual_replacement = match.expand(replacement)

            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(actual_replacement)

        cursor.endEditBlock()

        count = len(self._matches)
        logger.info("Replace All: replaced %d occurrence(s)", count)

        # Re-search — should find zero matches now.
        self._do_search()

    # --- Highlight Emission --------------------------------------------------

    def _emit_highlights(self):
        """
        Build ExtraSelection items for all matches and emit the signal.

        The current match gets a brighter highlight than the rest.
        """
        if not self._editor:
            self.search_selections_changed.emit([])
            return

        selections = []
        doc = self._editor.document()

        for i, (start, length) in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()

            # Current match gets a brighter color.
            if i == self._current_index:
                sel.format.setBackground(CURRENT_MATCH_COLOR)
            else:
                sel.format.setBackground(MATCH_HIGHLIGHT_COLOR)

            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            selections.append(sel)

        self.search_selections_changed.emit(selections)

    # --- Counter Label -------------------------------------------------------

    def _update_counter(self):
        """Update the '3/15' results counter label."""
        if not self._matches:
            query = self._find_input.text()
            if query:
                self._counter_label.setText("No results")
            else:
                self._counter_label.setText("")
            return

        # PyCharm-style compact format: "3/15" instead of "3 of 15".
        self._counter_label.setText("{}/{}".format(
            self._current_index + 1, len(self._matches)
        ))
