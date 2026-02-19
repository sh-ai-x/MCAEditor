"""
MCA Editor - Output Window.

Displays script execution output with color-coded formatting for errors,
warnings, results, and informational messages.

Dependencies:
    - PySide6 (QPlainTextEdit, QWidget, QFont, etc.)
"""

import logging

from datetime import datetime

from mca_qt.qt_compat import (
    QPlainTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    Qt, Signal,
    QColor, QTextCharFormat, QFont, QTextCursor,
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

    Also sets ``TextSelectableByMouse | TextSelectableByKeyboard``
    interaction flags to ensure mouse selection always transfers
    keyboard focus to this widget.
    """

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

    def keyPressEvent(self, event):
        """
        Handle Ctrl+C (copy) and Ctrl+A (select all) explicitly.

        This ensures copy works even when Maya's hotkey system or the
        application-level event filter routes the event in an unexpected
        way. The event is accepted to prevent further propagation.

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

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the user clicks an error line (filename, line_number).
    line_clicked = Signal(str, int)

    # Emitted when error or warning counts change. Args: (error_count, warning_count).
    counts_changed = Signal(int, int)

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

        self._setup_ui()

    def _setup_ui(self):
        """Build the output window layout: header bar + text area."""
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

        # Clear button to wipe all output.
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(22)
        clear_btn.setStyleSheet("""
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
        """)
        clear_btn.clicked.connect(self.clear)
        header_layout.addWidget(clear_btn)

        layout.addWidget(header)

        # --- Text Output Area ---
        # _OutputTextEdit handles read-only mode and explicit Ctrl+C/Ctrl+A
        # to prevent Maya's hotkey system from intercepting copy operations.
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

        layout.addWidget(self._output)

        # --- Pre-build text formats for each message type ---
        self._fmt_normal = self._make_format(COLOR_NORMAL)
        self._fmt_error = self._make_format(COLOR_ERROR)
        self._fmt_warning = self._make_format(COLOR_WARNING)
        self._fmt_success = self._make_format(COLOR_SUCCESS)
        self._fmt_info = self._make_format(COLOR_INFO)
        self._fmt_result = self._make_format(COLOR_RESULT)
        self._fmt_timestamp = self._make_format(COLOR_TIMESTAMP)

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

    def set_show_timestamps(self, show):
        """
        Toggle timestamp display on output messages.

        :param bool show: True to show timestamps, False to hide.
        """
        self._show_timestamps = show
