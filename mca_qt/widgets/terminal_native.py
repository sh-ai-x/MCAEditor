"""
MCA Qt - Native Terminal Widget (QPlainTextEdit frontend).

User-facing terminal emulator widget that combines the PTY backend
and ANSI parser into an interactive terminal experience. Renders the
parsed character grid into a styled QPlainTextEdit and translates Qt
key events into ANSI escape sequences for the PTY.

This is the fallback frontend used inside Maya (where QtWebEngine is
not available).  The xterm.js frontend (``terminal_xterm.py``) is
preferred in standalone mode.  Both share the same ``TerminalBackend``.

The ``terminal_factory.py`` module selects the correct widget at runtime.

Dependencies:
    - PySide6 or PySide2 (QWidget, QPlainTextEdit, QFont, etc.)
    - pywinpty >= 2.0.0 (Windows, via managed venv) OR
    - stdlib ``pty`` module (macOS/Linux, built-in)
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QPlainTextEdit, QApplication,
    Qt, Signal, QTimer, QFont, QFontMetricsF, QColor,
    QTextCharFormat, QTextCursor, QMenu,
)

from mca_qt.widgets.terminal_backend import TerminalBackend, check_conpty, check_unix_pty
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

        # First-data flag for diagnostic logging — logs once when data
        # first arrives so we can confirm the data pipeline is working.
        self._first_data_logged = False

        # Scrollback rendering state — tracks how many scrollback lines
        # have already been inserted into the QPlainTextEdit.  New lines
        # are appended incrementally (once) so we never re-render old
        # scrollback.  The visible grid (last _rows lines) is rebuilt
        # every frame but is small (~24 lines).
        self._scrollback_rendered = 0

        # Local echo mode — enabled when running with the subprocess pipe
        # fallback (no PTY).  Without a PTY, the shell doesn't echo typed
        # characters or handle backspace visually, so the terminal must do
        # it locally.  Characters are displayed immediately and buffered
        # until Enter sends the complete line to the shell's stdin.
        self._local_echo = False
        self._echo_buffer = ""

        # Mouse selection state — when the user is click-dragging to
        # select text, we pause the display rebuild so the selection
        # isn't destroyed by the 60fps render timer.
        self._mouse_selecting = False

        # Build the UI.
        self._setup_ui()

        # Create the ANSI parser.
        self._parser = AnsiParser(self._rows, self._cols)

        # Create the PTY backend (but don't start it yet).
        self._backend = None

        # Render timer — batches updates at ~60fps.
        # Created here but NOT started until start() is called.  Running
        # a 60fps timer with no active process causes repaint cascades
        # that can crash Maya (ACCESS_VIOLATION in QRasterPaintEngine).
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(16)  # ~60fps.
        self._render_timer.timeout.connect(self._render)

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the terminal display widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The display area — a read-only QPlainTextEdit with monospace font.
        # We render our own block cursor (inverted colors) in _render(),
        # so the native Qt text cursor must be fully hidden.
        self._display = QPlainTextEdit()
        self._display.setReadOnly(True)
        self._display.setUndoRedoEnabled(False)
        self._display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._display.setCursorWidth(0)

        # Hide the horizontal scrollbar — terminal lines should never
        # exceed the widget width because the PTY column count matches
        # the viewport.  A visible scrollbar wastes space and signals
        # a mismatch between PTY cols and widget width.
        self._display.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

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
        Start the terminal by spawning the shell process.

        Calculates the initial terminal dimensions from the widget size,
        creates the backend thread, and starts reading output.  The
        backend automatically selects the best available driver
        (pywinpty PTY or subprocess pipe fallback).
        """
        if self._alive:
            return

        # Determine if we have a real PTY backend available.
        # pywinpty (Windows) or Unix PTY (macOS/Linux) both provide a real
        # pseudo-terminal — the shell handles echo, line editing, etc.
        # Only the subprocess pipe fallback needs local echo mode.
        has_real_pty = check_conpty() or check_unix_pty()
        if not has_real_pty:
            logger.warning("Terminal start: no PTY available — "
                           "using subprocess pipe with local echo")
            self._local_echo = True
            self._echo_buffer = ""
        else:
            self._local_echo = False

        # Reset first-data flag and scrollback state for this session.
        self._first_data_logged = False
        self._scrollback_rendered = 0

        # Calculate dimensions from current widget size.
        # If the widget hasn't been laid out yet (common in Maya docked
        # panels), _calculate_dimensions() may silently keep defaults.
        self._calculate_dimensions()

        logger.info("Native terminal starting: shell=%s, cwd=%s, size=%dx%d",
                     self._shell or "(auto)", self._cwd or "(home)",
                     self._cols, self._rows)

        # Create and wire up the backend.
        self._backend = TerminalBackend(
            shell=self._shell,
            cwd=self._cwd,
            rows=self._rows,
            cols=self._cols,
            parent=self,
        )
        # NOTE: We do NOT connect data_received here.  The render timer
        # polls drain_buffer() directly, which is the reliable data path.
        # Connecting the signal too would double-feed the ANSI parser.
        self._backend.process_exited.connect(self._on_process_exited)

        # Resize the parser to match.
        self._parser.resize(self._rows, self._cols)

        # Start the backend thread.
        self._backend.start()
        self._alive = True

        # Start the render timer now that we have an active process.
        if not self._render_timer.isActive():
            self._render_timer.start()

        logger.info("Terminal started: %dx%d", self._cols, self._rows)

        # Schedule a deferred dimension recalculation after 200ms.
        # In docked environments (Maya), the widget viewport may not have
        # its final size yet when start() is called.  This ensures the PTY
        # gets resized to the correct terminal dimensions once layout settles.
        QTimer.singleShot(200, self._deferred_resize)

    def terminate(self):
        """
        Stop the PTY process and clean up.

        Safe to call multiple times.
        """
        self._render_timer.stop()
        if self._backend:
            self._backend.terminate()
            # Do NOT set self._backend = None here.  The QThread may
            # still be running if wait() timed out.  Dropping the last
            # reference causes Python to GC the QThread while its thread
            # is active → ACCESS_VIOLATION crash.  The backend is a child
            # of this widget, so Qt will destroy it when the widget dies
            # (after the thread has had time to finish).
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
        # Clear the document too — otherwise old scrollback blocks
        # remain in the QPlainTextEdit and appear as blank lines.
        self._display.clear()
        self._scrollback_rendered = 0
        self._dirty = True
        # Small delay to let the old process clean up.
        QTimer.singleShot(100, self.start)

    # --- Data Flow -----------------------------------------------------------

    def _on_process_exited(self, exit_code):
        """
        Handle PTY process exit.

        :param int exit_code: The child process exit code.
        """
        # Flush remaining data, then stop the render timer.
        if self._dirty:
            self._render()
        self._render_timer.stop()

        self._alive = False
        self.process_exited.emit(exit_code)
        logger.info("Terminal process exited with code %d", exit_code)

    def _deferred_resize(self):
        """
        Recalculate terminal dimensions after a short delay.

        Called via QTimer.singleShot() after start() to handle cases
        where the widget viewport didn't have its final size at start
        time (common in Maya docked panels).  This sends a resize to
        the PTY so the shell knows the correct terminal dimensions.
        """
        if not self._alive or not self._backend:
            return

        # Force recalculate — _calculate_dimensions() will resize the
        # parser and backend if the size has changed.
        old_cols, old_rows = self._cols, self._rows
        self._calculate_dimensions()

        if self._cols != old_cols or self._rows != old_rows:
            logger.info("Deferred resize corrected terminal: %dx%d -> %dx%d",
                         old_cols, old_rows, self._cols, self._rows)

    # --- Rendering -----------------------------------------------------------

    def _render(self):
        """
        Rebuild the display from the ANSI parser's character grid.

        Called by the render timer at ~60fps.  Uses a two-phase approach
        for efficient rendering:

        **Phase 1 — Scrollback (incremental):**
            New scrollback lines are inserted into the QPlainTextEdit
            once, as they appear.  Old scrollback is never re-rendered,
            keeping the cost proportional to new output only.

        **Phase 2 — Visible grid (per-frame):**
            The last ``_rows`` lines of the document are replaced with
            the current parser grid on every dirty frame.  This is the
            only section that changes frequently (~24 lines).

        This gives the user scrollable history while keeping per-frame
        work minimal (just the visible grid, not the full scrollback).
        """
        # Poll the backend's thread-safe buffer for new data.
        if self._backend:
            chunks = self._backend.drain_buffer()
            if chunks:
                total_bytes = sum(len(c) for c in chunks)

                if not self._first_data_logged:
                    self._first_data_logged = True
                    logger.info("Terminal: first data received — %d chunk(s), "
                                "%d bytes (pipeline OK)", len(chunks), total_bytes)

            for chunk in chunks:
                self._parser.feed(chunk)
                self._dirty = True

        # Check for new scrollback lines.
        current_sb_len = self._parser.get_scrollback_length()
        new_scrollback_count = current_sb_len - self._scrollback_rendered

        # If scrollback shrank (alt screen enter/exit, scrollback trim),
        # the document contains stale blocks from the old scrollback that
        # will never be updated.  Clear the entire document and rebuild
        # from scratch so no orphaned content remains.  Without this,
        # alt-screen transitions leave hundreds of blank lines in the
        # document from the previous screen's scrollback.
        if new_scrollback_count < 0:
            self._display.clear()
            self._scrollback_rendered = 0
            new_scrollback_count = current_sb_len
            self._dirty = True

        if not self._dirty and new_scrollback_count == 0:
            return

        # If the user is actively click-dragging to select text, defer
        # the visual update so the 60fps rebuild doesn't destroy their
        # selection mid-drag.  Data has already been drained and fed to
        # the parser above, so nothing is lost — we just skip the
        # display rebuild this frame.  The _dirty flag stays True, so
        # the next frame after they release the mouse will catch up.
        #
        # NOTE: We only check _mouse_selecting (mouse held down), NOT
        # hasSelection().  The old code also checked hasSelection() which
        # stays True indefinitely after any selection, permanently
        # blocking the render loop and making the cursor appear frozen.
        if self._mouse_selecting:
            return

        # Also pause while the user has a text selection so they can
        # press Ctrl+C to copy without the 60fps grid rebuild destroying
        # their selection.  The copy_selection() method clears the
        # selection after copying, which resumes rendering.  Any other
        # key press also clears the selection (see _handle_key_press).
        if self._display.textCursor().hasSelection():
            return

        # Get the visible grid and cursor position.
        grid_lines = self._parser.get_visible_lines()
        cursor_row, cursor_col = self._parser.get_cursor_position()

        # Only draw our block cursor when the parser reports it visible.
        # TUI apps (Claude Code, vim) send ESC[?25l to hide the hardware
        # cursor and render their own — drawing ours too causes double cursors.
        if not self._parser.is_cursor_visible():
            cursor_row, cursor_col = -1, -1

        # Check if the user has scrolled into the scrollback (history)
        # area above the live grid.  If they're reading history, don't
        # auto-scroll.  If they're anywhere near the live grid area,
        # always auto-scroll so active output stays visible.
        scrollbar = self._display.verticalScrollBar()
        viewport_height = self._display.viewport().height()
        is_in_scrollback = (scrollbar.value() < scrollbar.maximum() - viewport_height)

        self._display.setUpdatesEnabled(False)
        try:
            doc = self._display.document()

            # --- Phase 1: Insert new scrollback lines (incremental) ---
            if new_scrollback_count > 0:
                # Only convert the new scrollback lines to styled tuples
                # (not the entire scrollback buffer — much faster).
                new_sb_lines = self._parser.get_scrollback_lines(
                    max_lines=new_scrollback_count
                )

                # Insert before the grid section.  The grid section starts
                # at: (total blocks) - _rows.
                grid_start = max(0, doc.blockCount() - self._rows)
                block = doc.findBlockByNumber(grid_start)
                cursor = self._display.textCursor()
                cursor.setPosition(block.position())

                for sb_line in new_sb_lines:
                    self._render_line(cursor, sb_line)
                    cursor.insertText("\n")

                self._scrollback_rendered = current_sb_len

            # --- Phase 2: Replace the visible grid section ---
            if self._dirty:
                self._dirty = False

                # The grid section is always the last _rows lines.
                grid_start = max(0, doc.blockCount() - self._rows)
                block = doc.findBlockByNumber(grid_start)
                cursor = self._display.textCursor()
                cursor.setPosition(block.position())

                # Select from grid start to end of document.
                cursor.movePosition(
                    QTextCursor.MoveOperation.End,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.removeSelectedText()

                # Render each grid line with cursor indication.
                for row_idx, line in enumerate(grid_lines):
                    if row_idx > 0 or grid_start > 0:
                        cursor.insertText("\n")
                    self._render_line(
                        cursor, line,
                        cursor_row=cursor_row, cursor_col=cursor_col,
                        line_row=row_idx,
                    )

                # Position Qt's text cursor near the terminal cursor so
                # ensureCursorVisible scrolls to the right place.
                target_block = grid_start + cursor_row
                if target_block >= doc.blockCount():
                    target_block = doc.blockCount() - 1
                block = doc.findBlockByNumber(target_block)

                pos_cursor = self._display.textCursor()
                target_pos = block.position() + min(cursor_col, max(0, block.length() - 1))
                pos_cursor.setPosition(target_pos)
                self._display.setTextCursor(pos_cursor)

        except Exception as exc:
            logger.error("Terminal render error: %s", exc, exc_info=True)
        finally:
            self._display.setUpdatesEnabled(True)

        # Auto-scroll AFTER re-enabling updates so Qt can actually
        # calculate layout and move the viewport.  Snap to the very
        # bottom rather than using ensureCursorVisible() which only
        # scrolls the minimum amount and can leave the input line
        # barely visible at the viewport edge.
        if not is_in_scrollback:
            scrollbar.setValue(scrollbar.maximum())

        # Check for title changes.
        new_title = self._parser.get_title()
        if new_title != self._last_title:
            self._last_title = new_title
            self.title_changed.emit(new_title)

    def _render_line(self, cursor, line, cursor_row=-1, cursor_col=-1, line_row=-1):
        """
        Render a single styled line into the QTextCursor.

        Groups consecutive cells with identical formatting into runs
        for efficiency.  Optionally draws a block cursor (inverted
        colors) at the terminal cursor position.

        :param QTextCursor cursor: The cursor to insert text at.
        :param list line: List of (char, fg, bg, bold, underline, italic) tuples.
        :param int cursor_row: Terminal cursor row (-1 to skip cursor drawing).
        :param int cursor_col: Terminal cursor column.
        :param int line_row: This line's row index in the grid (for cursor matching).
        """
        i = 0
        while i < len(line):
            char, fg, bg, bold, underline, italic = line[i]

            # Check if this cell is the cursor position — if so,
            # invert fg/bg to draw a visible block cursor.
            is_cursor = (line_row == cursor_row and i == cursor_col)
            if is_cursor:
                # Use high-contrast inversion so the cursor is always
                # clearly visible regardless of the cell's own colors.
                cell_fg = DEFAULT_BG
                cell_bg = "#ffffff"
            else:
                cell_fg = fg
                cell_bg = bg

            # Collect a run of identically-formatted characters.
            # The cursor cell always breaks the run (it has unique colors).
            run = [char]
            j = i + 1
            if not is_cursor:
                while j < len(line):
                    if line_row == cursor_row and j == cursor_col:
                        break
                    c2, fg2, bg2, b2, u2, it2 = line[j]
                    if (fg2 == fg and bg2 == bg and b2 == bold
                            and u2 == underline and it2 == italic):
                        run.append(c2)
                        j += 1
                    else:
                        break

            # Create the text format for this run.
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(cell_fg))
            # Always set background for cursor cells; for normal cells
            # only set it when different from terminal default.
            if is_cursor or cell_bg != DEFAULT_BG:
                fmt.setBackground(QColor(cell_bg))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if underline:
                fmt.setFontUnderline(True)
            if italic:
                fmt.setFontItalic(True)

            cursor.insertText("".join(run), fmt)
            i = j

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

        if obj is self._display:
            etype = event.type()

            if etype == QEventType.Type.KeyPress:
                return self._handle_key_press(event)

            # Accept ShortcutOverride for all keys so the QPlainTextEdit
            # never claims navigation keys (arrows, Home, End, etc.) for
            # its own cursor movement.  Our KeyPress handler is the sole
            # consumer of keyboard input.
            if etype == QEventType.Type.ShortcutOverride:
                event.accept()
                return True

            if etype == QEventType.Type.Wheel:
                return self._handle_wheel(event)

        # Track mouse-down state for text selection.  While the left
        # button is held, we pause the 60fps display rebuild so the
        # user's click-drag selection isn't destroyed mid-frame.
        if obj is self._display:
            etype = event.type()
            if etype == QEventType.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._mouse_selecting = True
                    self._display.setFocus()
                    # Fall through to default handler for selection support.
            elif etype == QEventType.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._mouse_selecting = False

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

        # Ctrl+C — smart behavior like Windows Terminal and GNOME Terminal:
        # if the user has selected text, copy it; otherwise send interrupt
        # (SIGINT / \x03).  Ctrl+Shift+C always copies regardless.
        if key == Qt.Key.Key_C and modifiers & Qt.KeyboardModifier.ControlModifier:
            has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            has_selection = self._display.textCursor().hasSelection()

            if has_shift or has_selection:
                # Copy the selection to the clipboard.
                self.copy_selection()
            else:
                # No selection — send interrupt to the shell.
                if self._local_echo:
                    self._echo_buffer = ""
                self._backend.write(b"\x03")
            return True

        # Any key other than copy clears the text selection so the
        # render loop resumes.  Without this, hasSelection() stays True
        # indefinitely after a selection and the display appears frozen.
        cursor = self._display.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self._display.setTextCursor(cursor)

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

        # Ctrl+V or Ctrl+Shift+V — paste clipboard.
        if (key == Qt.Key.Key_V and
            modifiers & Qt.KeyboardModifier.ControlModifier):
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
            if self._local_echo:
                # In local echo mode, send the buffered line to the shell
                # and echo a newline locally so the cursor moves down.
                line = self._echo_buffer + "\r\n"
                self._backend.write(line.encode("utf-8"))
                self._parser.feed(b"\r\n")
                self._echo_buffer = ""
                self._dirty = True
            else:
                self._backend.write(b"\r")
            return True

        # Tab.
        if key == Qt.Key.Key_Tab:
            if self._local_echo:
                # No tab-completion in subprocess mode — echo a tab locally.
                self._parser.feed(b"\t")
                self._echo_buffer += "\t"
                self._dirty = True
            else:
                self._backend.write(b"\t")
            return True

        # Shift+Tab (backtab) — send CSI Z so CLI tools (Claude Code's
        # plan mode toggle, etc.) receive the keystroke instead of Qt
        # stealing it for focus navigation.
        if key == Qt.Key.Key_Backtab:
            self._backend.write(b"\x1b[Z")
            return True

        # Backspace.
        if key == Qt.Key.Key_Backspace:
            if self._local_echo:
                # Erase locally: move cursor left, overwrite with space,
                # move cursor left again (the classic \b \b sequence).
                if self._echo_buffer:
                    self._echo_buffer = self._echo_buffer[:-1]
                    self._parser.feed(b"\x08 \x08")
                    self._dirty = True
            else:
                self._backend.write(b"\x7f")
            return True

        # Escape.
        if key == Qt.Key.Key_Escape:
            self._backend.write(b"\x1b")
            return True

        # Regular text input — forward as UTF-8.
        if text:
            if self._local_echo:
                # Echo locally and buffer for line-mode send on Enter.
                self._parser.feed(text.encode("utf-8"))
                self._echo_buffer += text
                self._dirty = True
            else:
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

            # Clear the selection so the render loop resumes immediately.
            # Without this the cursor appears frozen until the next click.
            cursor = self._display.textCursor()
            cursor.clearSelection()
            self._display.setTextCursor(cursor)

    def paste_clipboard(self):
        """
        Paste the system clipboard content into the terminal.

        When the running program has enabled bracketed paste mode
        (DEC private mode 2004), wraps the pasted text in the
        standard bracket sequences so the program can distinguish
        pasted text from typed keystrokes.  Programs like Claude
        Code, vim, and fish rely on this to handle pastes correctly.
        """
        if not self._alive or not self._backend:
            logger.warning("paste_clipboard: terminal not alive or no backend "
                           "(alive=%s, backend=%s)", self._alive, self._backend)
            return
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            payload = text.encode("utf-8")
            # Wrap in bracketed paste sequences when the running program
            # has enabled mode 2004 (e.g. Claude Code, vim, fish shell).
            bracketed = self._parser._bracketed_paste
            in_alt = self._parser._in_alt_screen
            if bracketed:
                logger.info("paste_clipboard: bracketed paste ON (alt_screen=%s), "
                            "wrapping %d bytes", in_alt, len(payload))
                payload = b"\x1b[200~" + payload + b"\x1b[201~"
            else:
                logger.info("paste_clipboard: bracketed paste OFF (alt_screen=%s), "
                            "sending %d bytes raw", in_alt, len(payload))
            self._backend.write(payload)
        else:
            logger.warning("paste_clipboard: clipboard is empty")

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

        # Use the advance width of a representative character.  For monospace
        # fonts (Consolas), horizontalAdvance("M") gives the exact cell width.
        # averageCharWidth() can be slightly smaller, leading to column counts
        # that exceed the actual number of characters that fit in the viewport.
        char_width = metrics.horizontalAdvance("M")
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

        # Subtract the document margin (default 4px per side) so terminal
        # lines fit inside the viewport without triggering overflow.
        doc_margin = self._display.document().documentMargin()
        usable_width = width - (doc_margin * 2)

        new_cols = max(20, int(usable_width / char_width))
        new_rows = max(5, int(height / char_height))

        if new_cols != self._cols or new_rows != self._rows:
            self._cols = new_cols
            self._rows = new_rows

            # Update the parser grid.
            self._parser.resize(new_rows, new_cols)

            # Notify the backend to resize the PTY.
            if self._backend and self._alive:
                self._backend.resize(new_rows, new_cols)

            # Clear the document and reset scrollback tracking so the
            # next render frame rebuilds from scratch.  Without this,
            # a row-count change leaves stale blocks in the document
            # that get mistaken for scrollback (blank lines at the top).
            self._display.clear()
            self._scrollback_rendered = 0

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
        """Clear the terminal screen, scrollback, and document history."""
        self._parser.clear()
        # Clear the entire QPlainTextEdit (removes rendered scrollback too).
        self._display.clear()
        self._scrollback_rendered = 0
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
