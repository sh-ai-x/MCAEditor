"""
MCA Qt - Terminal Widget.

User-facing terminal emulator widget that combines the ConPTY backend
and ANSI parser into an interactive terminal experience. Renders the
parsed character grid into a styled QPlainTextEdit and translates Qt
key events into ANSI escape sequences for the PTY.

Uses the Windows ConPTY API via ctypes — no external packages needed.
Works in any Python on Windows 10 1809+ (standalone and Maya).

Dependencies:
    - PySide6 or PySide2 (QWidget, QPlainTextEdit, QFont, etc.)
    - Windows 10 version 1809+ (for ConPTY)
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QPlainTextEdit, QApplication,
    Qt, Signal, QTimer, QFont, QFontMetricsF, QColor,
    QTextCharFormat, QTextCursor, QMenu,
)

from mca_qt.widgets.terminal_backend import TerminalBackend, HAS_CONPTY
from mca_qt.widgets.ansi_parser import AnsiParser, DEFAULT_FG, DEFAULT_BG

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Terminal Display Stylesheet ---------------------------------------------

_TERMINAL_STYLE = """
    QPlainTextEdit {{
        background-color: {bg};
        color: {fg};
        border: none;
        selection-background-color: #264f78;
        selection-color: #ffffff;
    }}
"""


# =============================================================================
# Terminal Widget
# =============================================================================

class TerminalWidget(QWidget):
    """
    Embeddable terminal emulator widget.

    Combines a PTY backend (for process I/O), an ANSI parser (for
    escape sequence interpretation), and a QPlainTextEdit (for
    display) into a working terminal.

    The display is rebuilt from the parser's character grid at ~60fps
    using a batched QTimer to avoid excessive repaints.

    :param str shell: Path to the shell executable (auto-detected if empty).
    :param str cwd: Working directory for the shell process.
    :param int font_size: Initial terminal font size.
    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the terminal title changes (via OSC escape sequence).
    title_changed = Signal(str)

    # Emitted when the PTY process exits.
    process_exited = Signal(int)

    # Emitted when the font size changes (for persistence).
    font_size_changed = Signal(int)

    def __init__(self, shell="", cwd="", font_size=12, parent=None):
        """
        Initialize the terminal widget.

        :param str shell: Shell path (auto-detected if empty).
        :param str cwd: Working directory for the shell.
        :param int font_size: Initial font size.
        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)

        self._shell = shell
        self._cwd = cwd
        self._font_size = font_size

        # Terminal dimensions (calculated from widget size and font metrics).
        self._rows = 24
        self._cols = 80

        # Track whether the terminal process is alive.
        self._alive = False

        # Dirty flag for batched rendering.
        self._dirty = False

        # Last known title for change detection.
        self._last_title = ""

        # Build the UI.
        self._setup_ui()

        # Create the ANSI parser.
        self._parser = AnsiParser(self._rows, self._cols)

        # Create the PTY backend (but don't start it yet).
        self._backend = None

        # Render timer — batches updates at ~60fps.
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(16)  # ~60fps.
        self._render_timer.timeout.connect(self._render)
        self._render_timer.start()

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the terminal display widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The display area — a read-only QPlainTextEdit with monospace font.
        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        self._display.setUndoRedoEnabled(False)
        self._display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        # Monospace font for terminal rendering.
        font = QFont("Consolas", self._font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._display.setFont(font)

        # Apply terminal styling.
        self._display.setStyleSheet(_TERMINAL_STYLE.format(
            bg=DEFAULT_BG, fg=DEFAULT_FG
        ))

        # Intercept key events on the display so we can forward to PTY.
        self._display.installEventFilter(self)
        # Also make it focusable and accept focus on click.
        self._display.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Set a custom context menu.
        self._display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._display.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self._display)

    # --- Process Lifecycle ---------------------------------------------------

    def start(self):
        """
        Start the terminal by spawning the PTY process.

        Calculates the initial terminal dimensions from the widget size,
        creates the backend thread, and starts reading output.  If the
        ConPTY API is not available (pre-1809 Windows), shows a
        user-friendly placeholder message instead.
        """
        if self._alive:
            return

        # Guard: ConPTY must be available for terminal functionality.
        if not HAS_CONPTY:
            self._show_unavailable_message()
            return

        # Calculate dimensions from current widget size.
        self._calculate_dimensions()

        # Create and wire up the backend.
        self._backend = TerminalBackend(
            shell=self._shell,
            cwd=self._cwd,
            rows=self._rows,
            cols=self._cols,
            parent=self,
        )
        self._backend.data_received.connect(self._on_data_received)
        self._backend.process_exited.connect(self._on_process_exited)

        # Resize the parser to match.
        self._parser.resize(self._rows, self._cols)

        # Start the backend thread.
        self._backend.start()
        self._alive = True

        logger.info("Terminal started: %dx%d", self._cols, self._rows)

    def _show_unavailable_message(self):
        """
        Show a placeholder message when ConPTY is not available.

        This should only happen on very old Windows versions (pre-1809).
        """
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#969696"))

        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        cursor.insertText("Terminal is not available.\n\n", fmt)
        cursor.insertText("The integrated terminal requires Windows 10\n", fmt)
        cursor.insertText("version 1809 or later (ConPTY API).\n", fmt)

        logger.info("Terminal unavailable — ConPTY not supported")

    def terminate(self):
        """
        Stop the PTY process and clean up.

        Safe to call multiple times.
        """
        if self._backend:
            self._backend.terminate()
            self._backend = None
        self._alive = False

    def is_alive(self):
        """
        Check whether the PTY process is still running.

        :return: True if the terminal process is active.
        :rtype: bool
        """
        return self._alive

    def restart(self):
        """Terminate the current session and start a new one."""
        self.terminate()
        self._parser.clear()
        self._dirty = True
        # Small delay to let the old process clean up.
        QTimer.singleShot(100, self.start)

    # --- Data Flow -----------------------------------------------------------

    def _on_data_received(self, data):
        """
        Handle raw bytes from the PTY backend.

        Feeds the data through the ANSI parser and marks the display
        as dirty for the next render cycle.

        :param bytes data: Raw bytes from the PTY.
        """
        self._parser.feed(data)
        self._dirty = True

    def _on_process_exited(self, exit_code):
        """
        Handle PTY process exit.

        :param int exit_code: The child process exit code.
        """
        self._alive = False
        self.process_exited.emit(exit_code)
        logger.info("Terminal process exited with code %d", exit_code)

    # --- Rendering -----------------------------------------------------------

    def _render(self):
        """
        Rebuild the display from the ANSI parser's character grid.

        Called by the render timer at ~60fps. Polls the backend's
        thread-safe buffer directly (bypassing cross-thread Signal
        delivery issues) and feeds any new data to the parser before
        repainting.
        """
        # Poll the backend's thread-safe buffer for new data.
        # This is more reliable than the cross-thread Signal(bytes)
        # which can silently fail on some PySide6/Qt builds.
        if self._backend:
            chunks = self._backend.drain_buffer()
            for chunk in chunks:
                self._parser.feed(chunk)
                self._dirty = True

        if not self._dirty:
            return
        self._dirty = False

        # Get the visible lines from the parser.
        lines = self._parser.get_visible_lines()
        cursor_row, cursor_col = self._parser.get_cursor_position()

        # Build the display content using rich text formatting.
        # We use QTextCursor operations for efficient updates.
        self._display.setUpdatesEnabled(False)

        cursor = self._display.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        for row_idx, line in enumerate(lines):
            if row_idx > 0:
                cursor.insertText("\n")

            # Group consecutive cells with the same formatting for efficiency.
            i = 0
            while i < len(line):
                char, fg, bg, bold, underline, italic = line[i]

                # Collect a run of identically-formatted characters.
                run = [char]
                j = i + 1
                while j < len(line):
                    c2, fg2, bg2, b2, u2, it2 = line[j]
                    if fg2 == fg and bg2 == bg and b2 == bold and u2 == underline and it2 == italic:
                        run.append(c2)
                        j += 1
                    else:
                        break

                # Create the text format for this run.
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(fg))
                if bg != DEFAULT_BG:
                    fmt.setBackground(QColor(bg))
                if bold:
                    fmt.setFontWeight(QFont.Weight.Bold)
                if underline:
                    fmt.setFontUnderline(True)
                if italic:
                    fmt.setFontItalic(True)

                # Insert the run.
                cursor.insertText("".join(run), fmt)
                i = j

        # Position the visible cursor.
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(cursor_row):
            cursor.movePosition(QTextCursor.MoveOperation.Down)
        for _ in range(cursor_col):
            cursor.movePosition(QTextCursor.MoveOperation.Right)
        self._display.setTextCursor(cursor)

        # Ensure the cursor line is visible.
        self._display.ensureCursorVisible()
        self._display.setUpdatesEnabled(True)

        # Check for title changes.
        new_title = self._parser.get_title()
        if new_title != self._last_title:
            self._last_title = new_title
            self.title_changed.emit(new_title)

    # --- Keyboard Input ------------------------------------------------------

    def eventFilter(self, obj, event):
        """
        Intercept key events on the display widget and forward to PTY.

        Translates Qt key events into ANSI escape sequences that the
        shell process can understand.

        :param QObject obj: The watched object.
        :param QEvent event: The event to filter.
        :return: True if the event was consumed.
        :rtype: bool
        """
        from mca_qt.qt_compat import QEvent as QEventType

        if obj is self._display and event.type() == QEventType.Type.KeyPress:
            # Handle Ctrl+Scroll for font zoom.
            # (Wheel events are handled separately in _display's wheelEvent)
            return self._handle_key_press(event)

        if obj is self._display and event.type() == QEventType.Type.Wheel:
            return self._handle_wheel(event)

        return super().eventFilter(obj, event)

    def _handle_key_press(self, event):
        """
        Translate a Qt key press event into PTY input.

        :param QKeyEvent event: The key press event.
        :return: True if the event was consumed.
        :rtype: bool
        """
        if not self._alive or not self._backend:
            return False

        key = event.key()
        modifiers = event.modifiers()
        text = event.text()

        # Ctrl+C — send interrupt signal.
        if key == Qt.Key.Key_C and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._backend.write(b"\x03")
            return True

        # Ctrl+D — send EOF.
        if key == Qt.Key.Key_D and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._backend.write(b"\x04")
            return True

        # Ctrl+Z — suspend (SIGTSTP).
        if key == Qt.Key.Key_Z and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._backend.write(b"\x1a")
            return True

        # Ctrl+L — clear screen.
        if key == Qt.Key.Key_L and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._backend.write(b"\x0c")
            return True

        # Ctrl+Shift+C — copy selection.
        if (key == Qt.Key.Key_C and
            modifiers & Qt.KeyboardModifier.ControlModifier and
            modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.copy_selection()
            return True

        # Ctrl+Shift+V — paste clipboard.
        if (key == Qt.Key.Key_V and
            modifiers & Qt.KeyboardModifier.ControlModifier and
            modifiers & Qt.KeyboardModifier.ShiftModifier):
            self.paste_clipboard()
            return True

        # Arrow keys — send ANSI cursor movement sequences.
        if key == Qt.Key.Key_Up:
            self._backend.write(b"\x1b[A")
            return True
        if key == Qt.Key.Key_Down:
            self._backend.write(b"\x1b[B")
            return True
        if key == Qt.Key.Key_Right:
            self._backend.write(b"\x1b[C")
            return True
        if key == Qt.Key.Key_Left:
            self._backend.write(b"\x1b[D")
            return True

        # Home / End.
        if key == Qt.Key.Key_Home:
            self._backend.write(b"\x1b[H")
            return True
        if key == Qt.Key.Key_End:
            self._backend.write(b"\x1b[F")
            return True

        # Page Up / Page Down.
        if key == Qt.Key.Key_PageUp:
            self._backend.write(b"\x1b[5~")
            return True
        if key == Qt.Key.Key_PageDown:
            self._backend.write(b"\x1b[6~")
            return True

        # Insert / Delete.
        if key == Qt.Key.Key_Insert:
            self._backend.write(b"\x1b[2~")
            return True
        if key == Qt.Key.Key_Delete:
            self._backend.write(b"\x1b[3~")
            return True

        # Function keys F1-F12.
        fkey_map = {
            Qt.Key.Key_F1: b"\x1bOP", Qt.Key.Key_F2: b"\x1bOQ",
            Qt.Key.Key_F3: b"\x1bOR", Qt.Key.Key_F4: b"\x1bOS",
            Qt.Key.Key_F5: b"\x1b[15~", Qt.Key.Key_F6: b"\x1b[17~",
            Qt.Key.Key_F7: b"\x1b[18~", Qt.Key.Key_F8: b"\x1b[19~",
            Qt.Key.Key_F9: b"\x1b[20~", Qt.Key.Key_F10: b"\x1b[21~",
            Qt.Key.Key_F11: b"\x1b[23~", Qt.Key.Key_F12: b"\x1b[24~",
        }
        if key in fkey_map:
            self._backend.write(fkey_map[key])
            return True

        # Enter / Return.
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._backend.write(b"\r")
            return True

        # Tab.
        if key == Qt.Key.Key_Tab:
            self._backend.write(b"\t")
            return True

        # Backspace.
        if key == Qt.Key.Key_Backspace:
            self._backend.write(b"\x7f")
            return True

        # Escape.
        if key == Qt.Key.Key_Escape:
            self._backend.write(b"\x1b")
            return True

        # Regular text input — forward as UTF-8.
        if text:
            self._backend.write(text.encode("utf-8"))
            return True

        return False

    def _handle_wheel(self, event):
        """
        Handle mouse wheel events for Ctrl+Scroll font zoom.

        :param QWheelEvent event: The wheel event.
        :return: True if the event was consumed.
        :rtype: bool
        """
        modifiers = event.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Scroll — zoom font size.
            delta = event.angleDelta().y()
            if delta > 0:
                self._font_size = min(48, self._font_size + 1)
            elif delta < 0:
                self._font_size = max(6, self._font_size - 1)

            font = self._display.font()
            font.setPointSize(self._font_size)
            self._display.setFont(font)

            # Recalculate terminal dimensions for the new font size.
            self._calculate_dimensions()
            self.font_size_changed.emit(self._font_size)
            return True

        # Normal scroll — let the default handler manage scrollback.
        return False

    # --- Clipboard -----------------------------------------------------------

    def copy_selection(self):
        """Copy the current text selection to the system clipboard."""
        selected = self._display.textCursor().selectedText()
        if selected:
            clipboard = QApplication.clipboard()
            # QPlainTextEdit uses Unicode paragraph separators — replace with newlines.
            clipboard.setText(selected.replace("\u2029", "\n"))

    def paste_clipboard(self):
        """Paste the system clipboard content into the terminal."""
        if not self._alive or not self._backend:
            return
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            # Send clipboard content to the PTY as keystrokes.
            self._backend.write(text.encode("utf-8"))

    # --- Context Menu --------------------------------------------------------

    def _show_context_menu(self, pos):
        """
        Show the terminal right-click context menu.

        :param QPoint pos: Position where the menu was requested.
        """
        menu = QMenu(self)

        # Copy action.
        copy_action = menu.addAction("Copy")
        copy_action.setShortcut("Ctrl+Shift+C")
        copy_action.triggered.connect(self.copy_selection)
        copy_action.setEnabled(self._display.textCursor().hasSelection())

        # Paste action.
        paste_action = menu.addAction("Paste")
        paste_action.setShortcut("Ctrl+Shift+V")
        paste_action.triggered.connect(self.paste_clipboard)

        menu.addSeparator()

        # Clear action.
        clear_action = menu.addAction("Clear")
        clear_action.triggered.connect(self.clear)

        # Select All action.
        select_all = menu.addAction("Select All")
        select_all.triggered.connect(self._display.selectAll)

        menu.exec(self._display.mapToGlobal(pos))

    # --- Resize Handling -----------------------------------------------------

    def resizeEvent(self, event):
        """
        Handle widget resize — recalculate terminal dimensions.

        :param QResizeEvent event: The resize event.
        """
        super().resizeEvent(event)
        self._calculate_dimensions()

    def _calculate_dimensions(self):
        """
        Calculate terminal rows and columns from widget size and font metrics.

        Notifies the backend and parser of the new dimensions.
        Uses sensible minimums so the PTY never spawns too small.
        """
        font = self._display.font()
        metrics = QFontMetricsF(font)

        # Use the advance width of a space character for column calculation.
        char_width = metrics.averageCharWidth()
        char_height = metrics.height()

        if char_width <= 0 or char_height <= 0:
            return

        # Get the viewport dimensions (inside scrollbar/margins).
        viewport = self._display.viewport()
        width = viewport.width()
        height = viewport.height()

        # If the viewport is too small (widget not yet laid out), keep defaults.
        if width < 50 or height < 50:
            return

        new_cols = max(20, int(width / char_width))
        new_rows = max(5, int(height / char_height))

        if new_cols != self._cols or new_rows != self._rows:
            self._cols = new_cols
            self._rows = new_rows

            # Update the parser grid.
            self._parser.resize(new_rows, new_cols)

            # Notify the backend to resize the PTY.
            if self._backend and self._alive:
                self._backend.resize(new_rows, new_cols)

            self._dirty = True
            logger.debug("Terminal resized to %dx%d", new_cols, new_rows)

    # --- Font Size -----------------------------------------------------------

    def set_font_size(self, size):
        """
        Set the terminal font size.

        :param int size: Font point size.
        """
        self._font_size = max(6, min(48, size))
        font = self._display.font()
        font.setPointSize(self._font_size)
        self._display.setFont(font)
        self._calculate_dimensions()

    def get_font_size(self):
        """
        Get the current terminal font size.

        :return: Font point size.
        :rtype: int
        """
        return self._font_size

    # --- Clear ---------------------------------------------------------------

    def clear(self):
        """Clear the terminal screen and scrollback."""
        self._parser.clear()
        self._dirty = True
        # Also send Ctrl+L to the shell so it redraws its prompt.
        if self._alive and self._backend:
            self._backend.write(b"\x0c")

    # --- Focus ---------------------------------------------------------------

    def setFocus(self, reason=None):
        """
        Override setFocus to direct focus to the display widget.

        :param reason: Focus reason (optional).
        """
        self._display.setFocus()
