"""
MCA Editor - Output Window.

Displays script execution output with color-coded formatting for errors,
warnings, results, and informational messages. Includes a collapsible
search bar (Ctrl+F) for incremental text search within the output.

Dependencies:
    - PySide6 (QPlainTextEdit, QWidget, QFont, etc.)
"""

import re
import logging

from datetime import datetime

from mca_qt.qt_compat import (
    QPlainTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    Qt, Signal, QEvent, QComboBox, QFileDialog, QMessageBox,
    QColor, QTextCharFormat, QFont, QTextCursor, QLineEdit, QTimer, QTextEdit,
)

# Module-level logger for output window operations.
logger = logging.getLogger(__name__)


# --- Output Color Constants -------------------------------------------------

# Hex color codes for each message type, matching the dark theme.
COLOR_NORMAL = "#cccccc"       # Default output text
COLOR_ERROR = "#f44747"        # Error messages (red)
COLOR_WARNING = "#cca700"      # Warning messages (orange)
COLOR_SUCCESS = "#4ec9b0"      # Success messages (green)
COLOR_INFO = "#569cd6"         # Informational messages (blue)
COLOR_RESULT = "#dcdcaa"       # Return values / results (yellow)
COLOR_TIMESTAMP = "#666666"    # Timestamp prefix (dim gray)

# --- Search Highlight Colors ------------------------------------------------

# Background color for all search matches in the output.
OUTPUT_MATCH_COLOR = QColor(80, 80, 40)

# Background color for the currently focused search match.
OUTPUT_CURRENT_MATCH_COLOR = QColor(120, 120, 50)


# =============================================================================
# Output Search Bar
# =============================================================================

# Stylesheet for the output search bar — matches the editor find bar aesthetic.
_OUTPUT_SEARCH_STYLE = """
    QWidget#OutputSearchBar {
        background-color: #2d2d30;
        border-bottom: 1px solid #3f3f46;
    }
    QLineEdit {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 3px 6px;
        font-size: 12px;
        min-width: 140px;
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


class OutputSearchBar(QWidget):
    """
    Compact search bar for the output panel (read-only, no replace).

    Provides incremental search with match highlighting using
    QPlainTextEdit ExtraSelections. Supports Match Case and Regex toggles.

    Layout:
        [Find: ________(x)] [Cc] [.*]  3/15  [^] [v] [X]

    :param QPlainTextEdit output_edit: The output text widget to search within.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, output_edit, parent=None):
        """
        Initialize the output search bar.

        :param QPlainTextEdit output_edit: The text widget to search.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("OutputSearchBar")

        self._output_edit = output_edit
        self._matches = []        # List of (start, length) tuples.
        self._current_index = -1  # Index of the currently focused match.

        self._setup_ui()
        self.setStyleSheet(_OUTPUT_SEARCH_STYLE)

        # Debounce timer — delays search by 150ms after typing stops.
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._do_search)

        # Start hidden.
        self.hide()

    def _setup_ui(self):
        """
        Build the search bar layout.

        Single row: [find_input(x)] [Cc] [.*] [counter] [up] [down] [close]
        """
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # Find input field with built-in clear button.
        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText("Find in Output")
        self._find_input.setClearButtonEnabled(True)
        self._find_input.textChanged.connect(self._on_text_changed)
        self._find_input.returnPressed.connect(self._find_next)
        layout.addWidget(self._find_input, 1)

        # Match Case toggle.
        self._case_btn = QPushButton("Cc")
        self._case_btn.setToolTip("Match Case")
        self._case_btn.setCheckable(True)
        self._case_btn.setFixedSize(28, 24)
        self._case_btn.toggled.connect(self._on_option_changed)
        layout.addWidget(self._case_btn)

        # Regex toggle.
        self._regex_btn = QPushButton(".*")
        self._regex_btn.setToolTip("Regex")
        self._regex_btn.setCheckable(True)
        self._regex_btn.setFixedSize(28, 24)
        self._regex_btn.toggled.connect(self._on_option_changed)
        layout.addWidget(self._regex_btn)

        # Results counter label ("3/15" format).
        self._counter_label = QLabel("")
        self._counter_label.setMinimumWidth(50)
        layout.addWidget(self._counter_label)

        # Previous match (up arrow).
        self._prev_btn = QPushButton("\u2191")
        self._prev_btn.setToolTip("Previous Match (Shift+Enter)")
        self._prev_btn.setFixedSize(28, 24)
        self._prev_btn.clicked.connect(self._find_prev)
        layout.addWidget(self._prev_btn)

        # Next match (down arrow).
        self._next_btn = QPushButton("\u2193")
        self._next_btn.setToolTip("Next Match (Enter)")
        self._next_btn.setFixedSize(28, 24)
        self._next_btn.clicked.connect(self._find_next)
        layout.addWidget(self._next_btn)

        # Close button.
        self._close_btn = QPushButton("\u2715")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setToolTip("Close (Escape)")
        self._close_btn.clicked.connect(self.dismiss)
        layout.addWidget(self._close_btn)

        # Install an event filter on the find input to intercept Escape.
        # QLineEdit with setClearButtonEnabled(True) can consume Escape
        # to clear text, preventing propagation to our keyPressEvent.
        self._find_input.installEventFilter(self)

    # --- Event Filter --------------------------------------------------------

    def eventFilter(self, obj, event):
        """
        Intercept Escape on the find QLineEdit to dismiss the bar.

        :param QObject obj: The watched object.
        :param QEvent event: The event.
        :return: True if the event was handled.
        :rtype: bool
        """
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return True
        return super().eventFilter(obj, event)

    # --- Public API ----------------------------------------------------------

    def show_bar(self):
        """Show the search bar and focus the input field."""
        self.show()
        self._find_input.setFocus()
        self._find_input.selectAll()
        # Kick off a search immediately if there's existing text.
        if self._find_input.text():
            self._do_search()

    def dismiss(self):
        """Hide the search bar and clear all highlights from the output."""
        self.hide()
        self._matches = []
        self._current_index = -1
        self._counter_label.setText("")
        # Clear highlights from the output text widget.
        self._output_edit.setExtraSelections([])

    # --- Key Handling --------------------------------------------------------

    def keyPressEvent(self, event):
        """
        Handle keyboard shortcuts within the output search bar.

        - Escape: dismiss the bar
        - Shift+Enter: find previous

        :param QKeyEvent event: The key event.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return

        # Shift+Enter -> find previous.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() == Qt.KeyboardModifier.ShiftModifier):
            self._find_prev()
            return

        super().keyPressEvent(event)

    # --- Search Logic --------------------------------------------------------

    def _on_text_changed(self, text):
        """
        Restart the debounce timer when the find text changes.

        :param str text: Current find field text (unused directly).
        """
        self._search_timer.start()

    def _on_option_changed(self, _checked):
        """
        Re-run the search when a toggle option changes.

        :param bool _checked: New checked state (unused).
        """
        self._do_search()

    def _build_pattern(self, search_text):
        """
        Compile a regex pattern from the search text and active options.

        :param str search_text: The raw search string from the find field.
        :return: Compiled regex pattern, or None if empty/invalid.
        :rtype: re.Pattern or None
        """
        if not search_text:
            return None

        # Regex mode uses the raw text; plain mode escapes special chars.
        if self._regex_btn.isChecked():
            pattern_str = search_text
        else:
            pattern_str = re.escape(search_text)

        # Case sensitivity flag.
        flags = 0
        if not self._case_btn.isChecked():
            flags |= re.IGNORECASE

        try:
            return re.compile(pattern_str, flags)
        except re.error as exc:
            logger.debug("Invalid regex in output search: %s", exc)
            return None

    def _do_search(self):
        """
        Run the search against the output text and apply highlights.

        Builds a list of (start, length) match positions and uses
        ExtraSelections to highlight them in the output widget.
        """
        self._matches = []
        self._current_index = -1

        search_text = self._find_input.text()
        pattern = self._build_pattern(search_text)

        if not pattern:
            self._update_counter()
            self._output_edit.setExtraSelections([])
            return

        # Search the full output text for all matches.
        doc_text = self._output_edit.toPlainText()
        for m in pattern.finditer(doc_text):
            self._matches.append((m.start(), m.end() - m.start()))

        # If there are matches, start at the one closest to the cursor.
        if self._matches:
            cursor_pos = self._output_edit.textCursor().position()
            self._current_index = self._find_nearest_match(cursor_pos)

        self._update_counter()
        self._apply_highlights()

    def _find_nearest_match(self, cursor_pos):
        """
        Find the match index closest to (at or after) *cursor_pos*.

        :param int cursor_pos: The current cursor position in the output.
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
        """Advance to the next match (wrapping at end)."""
        if not self._matches:
            return
        self._current_index = (self._current_index + 1) % len(self._matches)
        self._scroll_to_current()
        self._update_counter()
        self._apply_highlights()

    def _find_prev(self):
        """Go to the previous match (wrapping at start)."""
        if not self._matches:
            return
        self._current_index = (self._current_index - 1) % len(self._matches)
        self._scroll_to_current()
        self._update_counter()
        self._apply_highlights()

    def _scroll_to_current(self):
        """
        Scroll the output widget so the current match is visible.

        Moves the text cursor to the current match position so
        ensureCursorVisible brings it into the viewport.
        """
        if self._current_index < 0 or not self._matches:
            return

        start, length = self._matches[self._current_index]
        cursor = self._output_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        self._output_edit.setTextCursor(cursor)
        self._output_edit.ensureCursorVisible()

    # --- Highlight Application -----------------------------------------------

    def _apply_highlights(self):
        """
        Apply ExtraSelections to the output widget for all matches.

        The current match gets a brighter highlight than the rest.
        """
        selections = []
        doc = self._output_edit.document()

        for i, (start, length) in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()

            # Current match gets a brighter color.
            if i == self._current_index:
                sel.format.setBackground(OUTPUT_CURRENT_MATCH_COLOR)
            else:
                sel.format.setBackground(OUTPUT_MATCH_COLOR)

            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            selections.append(sel)

        self._output_edit.setExtraSelections(selections)

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

        self._counter_label.setText("{}/{}".format(
            self._current_index + 1, len(self._matches)
        ))


# --- Output Text Edit (Maya-safe) -------------------------------------------

class _OutputTextEdit(QPlainTextEdit):
    """
    Read-only text edit with explicit copy/select-all handling.

    Inside Maya, the standard Ctrl+C shortcut can be intercepted by
    Maya's ``cutCopyPaste.mel`` hotkey system before Qt processes it,
    resulting in a "Nothing is selected" MEL error instead of copying
    the selected output text. This subclass overrides ``keyPressEvent``
    to handle Ctrl+C and Ctrl+A explicitly, then accepts the event so
    it never propagates to Maya's hotkey layer.

    Also supports Ctrl+Scroll Wheel zoom to change the output font
    size, emitting ``zoom_requested`` so the parent can persist the
    new size.

    Also sets ``TextSelectableByMouse | TextSelectableByKeyboard``
    interaction flags to ensure mouse selection always transfers
    keyboard focus to this widget.
    """

    # Emitted when the user Ctrl+scrolls to zoom. +1 = zoom in, -1 = zoom out.
    zoom_requested = Signal(int)

    def __init__(self, parent=None):
        """
        Initialize with read-only mode and text selection flags.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setReadOnly(True)

        # Explicit interaction flags ensure that clicking to select text
        # also gives this widget keyboard focus, which is critical for
        # the Maya hotkey filter to recognize focus is inside our editor.
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

    def wheelEvent(self, event):
        """
        Handle Ctrl+scroll wheel for output font size zoom.

        Emits ``zoom_requested(+1)`` for scroll-up (zoom in) and
        ``zoom_requested(-1)`` for scroll-down (zoom out). Without
        Ctrl held, scrolling behaves normally.

        :param QWheelEvent event: The wheel event.
        """
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_requested.emit(1)
            elif delta < 0:
                self.zoom_requested.emit(-1)
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event):
        """
        Override top-level event handler to intercept ShortcutOverride.

        Maya's hotkey system intercepts keyboard events at the
        application level, before individual widgets see them.  By
        accepting ShortcutOverride for Ctrl+C, Ctrl+A, and Ctrl+F
        directly on this widget, we tell Qt to deliver them as
        normal KeyPress events to our keyPressEvent below — before
        Maya's MEL-based hotkey layer can steal them.

        :param QEvent event: The Qt event.
        :return: True if the event was consumed.
        :rtype: bool
        """
        if event.type() == QEvent.Type.ShortcutOverride:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                if event.key() in (Qt.Key.Key_C, Qt.Key.Key_A, Qt.Key.Key_F):
                    event.accept()
                    return True
        return super().event(event)

    def keyPressEvent(self, event):
        """
        Handle Ctrl+C (copy) and Ctrl+A (select all) explicitly.

        This ensures copy works even when Maya's hotkey system or the
        application-level event filter routes the event in an unexpected
        way. The event is accepted to prevent further propagation.

        Ctrl+F is handled by the MCAEditorPanel's shortcut system,
        which routes it to the output search bar when this widget
        has focus.

        :param QKeyEvent event: The key press event.
        """
        # Only intercept when Ctrl is the sole modifier.
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_C:
                # Copy selected text to clipboard (no-op if nothing selected).
                self.copy()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_A:
                # Select all output text.
                self.selectAll()
                event.accept()
                return

        # Everything else goes to the base implementation.
        super().keyPressEvent(event)


# --- Output Window Widget ---------------------------------------------------

class OutputWindow(QWidget):
    """
    Output panel for script execution results.

    Shows color-coded messages with optional timestamps.
    Supports error navigation by emitting clicked line info.
    Includes a collapsible search bar (Ctrl+F) for text search.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the user clicks an error line (filename, line_number).
    line_clicked = Signal(str, int)

    # Emitted when error or warning counts change. Args: (error_count, warning_count).
    counts_changed = Signal(int, int)

    # Emitted when the user changes the output verbosity combobox.
    verbosity_changed = Signal(str)

    # Emitted when the output font size changes (new_size).
    font_size_changed = Signal(int)

    def __init__(self, parent=None):
        """
        Initialize the output window.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._show_timestamps = False

        # Running tallies of errors and warnings since last clear.
        self._error_count = 0
        self._warning_count = 0

        # Current output font size (overridden by restore_font_size).
        self._font_size = 11

        self._setup_ui()

    def _setup_ui(self):
        """Build the output window layout: header bar + search bar + text area."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header Bar ---
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3f3f46;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        header_layout.setSpacing(4)

        title = QLabel("OUTPUT")
        title.setStyleSheet("color: #bbbbbb; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Shared style for small header buttons.
        _header_btn_style = """
            QPushButton {
                background: transparent;
                color: #969696;
                border: none;
                padding: 0 6px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #3e3e42;
            }
        """

        # Search icon button to toggle the search bar.
        search_btn = QPushButton("\U0001f50d")  # Magnifying glass icon
        search_btn.setFixedHeight(22)
        search_btn.setToolTip("Search Output (Ctrl+F)")
        search_btn.setStyleSheet(_header_btn_style)
        search_btn.clicked.connect(self.toggle_search_bar)
        header_layout.addWidget(search_btn)

        # Write to File button — exports output content to a text file.
        write_btn = QPushButton("\U0001f4be")  # Floppy disk icon
        write_btn.setFixedHeight(22)
        write_btn.setToolTip("Write output to file")
        write_btn.setStyleSheet(_header_btn_style)
        write_btn.clicked.connect(self._write_to_file)
        header_layout.addWidget(write_btn)

        # Output verbosity selector — controls how much detail is shown.
        self._verbosity_combo = QComboBox()
        self._verbosity_combo.addItems(["Echo All", "Normal", "Minimal"])
        self._verbosity_combo.setCurrentIndex(1)  # Default to Normal.
        self._verbosity_combo.setFixedHeight(22)
        self._verbosity_combo.setFixedWidth(90)
        self._verbosity_combo.setToolTip("Output verbosity level")
        self._verbosity_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555555;
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }
            QComboBox:hover {
                border-color: #007acc;
            }
            QComboBox::drop-down {
                border: none;
                width: 16px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #969696;
                margin-right: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d30;
                color: #cccccc;
                selection-background-color: #094771;
                border: 1px solid #555555;
            }
        """)
        self._verbosity_combo.currentTextChanged.connect(self._on_verbosity_changed)
        header_layout.addWidget(self._verbosity_combo)

        # Clear button to wipe all output.
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet(_header_btn_style)
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)

        layout.addWidget(header)

        # --- Text Output Area ---
        # _OutputTextEdit handles read-only mode and explicit Ctrl+C/Ctrl+A/Ctrl+F
        # to prevent Maya's hotkey system from intercepting these operations.
        self._output = _OutputTextEdit()
        self._output.setMaximumBlockCount(10000)  # Prevent unbounded memory growth

        # Monospace font for consistent output formatting.
        font = QFont("JetBrains Mono, Consolas, Courier New", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(font)

        self._output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                border: none;
                padding: 4px;
            }
        """)

        # Connect Ctrl+Scroll zoom signal from the text edit.
        self._output.zoom_requested.connect(self._on_zoom_requested)

        layout.addWidget(self._output)

        # --- Output Search Bar (hidden by default, sits between header and output) ---
        # Created after the output widget so we can pass it as a reference.
        self._search_bar = OutputSearchBar(self._output)
        # Insert the search bar at index 1 (between header and output).
        layout.insertWidget(1, self._search_bar)

        # --- Pre-build text formats for each message type ---
        self._fmt_normal = self._make_format(COLOR_NORMAL)
        self._fmt_error = self._make_format(COLOR_ERROR)
        self._fmt_warning = self._make_format(COLOR_WARNING)
        self._fmt_success = self._make_format(COLOR_SUCCESS)
        self._fmt_info = self._make_format(COLOR_INFO)
        self._fmt_result = self._make_format(COLOR_RESULT)
        self._fmt_timestamp = self._make_format(COLOR_TIMESTAMP)

    # --- Search Bar Toggle ---------------------------------------------------

    def toggle_search_bar(self):
        """Toggle the output search bar visibility."""
        if self._search_bar.isVisible():
            self._search_bar.dismiss()
        else:
            self._search_bar.show_bar()

    def _make_format(self, hex_color):
        """
        Create a QTextCharFormat with the given foreground color.

        :param str hex_color: Hex color string (e.g. '#ff0000').
        :return: Configured text format.
        :rtype: QTextCharFormat
        """
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(hex_color))
        return fmt

    def _append_formatted(self, text, fmt):
        """
        Append text with specific formatting to the output area.

        Automatically scrolls to the bottom so the latest output
        is always visible.

        :param str text: The text to append.
        :param QTextCharFormat fmt: The format to apply.
        """
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Optionally prepend a timestamp.
        if self._show_timestamps:
            ts = datetime.now().strftime("[%H:%M:%S] ")
            cursor.insertText(ts, self._fmt_timestamp)

        cursor.insertText(text + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    # --- Public Write Methods -----------------------------------------------

    def write_output(self, text):
        """
        Write normal output text.

        :param str text: The output message.
        """
        self._append_formatted(text, self._fmt_normal)

    def write_result(self, text):
        """
        Write a result/return value.

        :param str text: The result message.
        """
        self._append_formatted(text, self._fmt_result)

    def write_error(self, text):
        """
        Write error text in red.

        Increments the error counter and emits ``counts_changed``.

        :param str text: The error message.
        """
        self._error_count += 1
        self._append_formatted(text, self._fmt_error)
        self.counts_changed.emit(self._error_count, self._warning_count)

    def write_warning(self, text):
        """
        Write warning text in orange.

        Increments the warning counter and emits ``counts_changed``.

        :param str text: The warning message.
        """
        self._warning_count += 1
        self._append_formatted(text, self._fmt_warning)
        self.counts_changed.emit(self._error_count, self._warning_count)

    def write_success(self, text):
        """
        Write success text in green.

        :param str text: The success message.
        """
        self._append_formatted(text, self._fmt_success)

    def write_info(self, text):
        """
        Write informational text in blue.

        :param str text: The informational message.
        """
        self._append_formatted(text, self._fmt_info)

    def write_execution_header(self, source, dcc_name=""):
        """
        Write a visual separator before execution output.

        :param str source: Description of what is being executed
                           (e.g. 'Full Script', 'Selected Text').
        :param str dcc_name: Name of the target DCC, if any.
        """
        separator = "-" * 60
        label = "Executing: {}".format(source)
        if dcc_name:
            label += " [{}]".format(dcc_name)
        self._append_formatted(separator, self._fmt_info)
        self._append_formatted(label, self._fmt_info)

    def write_code_echo(self, code):
        """
        Echo executed code to the output window.

        Mirrors Charcoal Editor / Maya Script Editor behavior where
        the output shows the code that was executed rather than a
        generic "Executing: ..." header.

        :param str code: The code that is being executed.
        """
        self._append_formatted(code, self._fmt_info)

    # --- Bulk Write (for history loading) --------------------------------------

    def write_bulk(self, text):
        """
        Insert a large block of text in a single cursor operation.

        Used by ``_load_maya_history()`` to batch-insert the entire Maya
        session log without per-line repaints. Much faster than calling
        ``write_output()`` for each line — hundreds of lines insert in
        one paint cycle instead of hundreds of separate repaints.

        Disables widget updates during the insert, then scrolls to the
        bottom afterward.

        :param str text: The full text block to insert.
        """
        if not text:
            return

        # Suspend repaints while we do the bulk insert.
        self._output.setUpdatesEnabled(False)

        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, self._fmt_normal)
        self._output.setTextCursor(cursor)

        # Re-enable updates and scroll to the bottom.
        self._output.setUpdatesEnabled(True)
        self._output.ensureCursorVisible()

    # --- Clear & Configuration -----------------------------------------------

    def clear(self):
        """Clear all output text and reset error/warning counters."""
        self._output.clear()
        self._error_count = 0
        self._warning_count = 0
        self.counts_changed.emit(self._error_count, self._warning_count)
        # If search bar is open, dismiss it since content is gone.
        if self._search_bar.isVisible():
            self._search_bar.dismiss()

    def set_verbosity(self, level):
        """
        Set the verbosity combobox to the given level without emitting a signal.

        Used by the parent to restore a saved verbosity setting on startup.

        :param str level: One of "echo_all", "normal", or "minimal".
        """
        # Map internal setting keys to combobox display text.
        display_map = {"echo_all": "Echo All", "normal": "Normal", "minimal": "Minimal"}
        display_text = display_map.get(level, "Normal")
        # Block signals to avoid a feedback loop during initialization.
        self._verbosity_combo.blockSignals(True)
        self._verbosity_combo.setCurrentText(display_text)
        self._verbosity_combo.blockSignals(False)

    # --- Output Font Size Zoom -----------------------------------------------

    def _on_zoom_requested(self, direction):
        """
        Handle Ctrl+scroll wheel zoom on the output text area.

        :param int direction: +1 to zoom in, -1 to zoom out.
        """
        if direction > 0:
            self._font_size += 1
        elif direction < 0 and self._font_size > 6:
            self._font_size -= 1
        else:
            return

        # Apply the new font size to the output text area.
        font = self._output.font()
        font.setPointSize(self._font_size)
        self._output.setFont(font)

        # Notify the parent so it can persist the new size.
        self.font_size_changed.emit(self._font_size)

    def set_font_size(self, size):
        """
        Set the output font size (e.g. restoring from settings on startup).

        :param int size: The font point size to apply.
        """
        self._font_size = size
        font = self._output.font()
        font.setPointSize(size)
        self._output.setFont(font)

    def _on_verbosity_changed(self, text):
        """
        Handle verbosity combobox selection change.

        Converts the display text to a lowercase key and emits the
        ``verbosity_changed`` signal so the parent panel can apply it.

        :param str text: Display text from the combobox (e.g. "Echo All").
        """
        # Map combobox display text to internal setting keys.
        key_map = {"Echo All": "echo_all", "Normal": "normal", "Minimal": "minimal"}
        level = key_map.get(text, "normal")
        self.verbosity_changed.emit(level)

    def _write_to_file(self):
        """
        Export all output content to a user-selected text file.

        Opens a save dialog and writes the plain text contents of the
        output panel to the chosen file path.
        """
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Write Output to File", "",
            "Text Files (*.txt);;Log Files (*.log);;All Files (*.*)"
        )
        if not filepath:
            return
        try:
            text = self._output.toPlainText()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
            self.write_info("Output written to: {}".format(filepath))
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Could not write output:\n{}".format(str(exc))
            )

    def set_show_timestamps(self, show):
        """
        Toggle timestamp display on output messages.

        :param bool show: True to show timestamps, False to hide.
        """
        self._show_timestamps = show
