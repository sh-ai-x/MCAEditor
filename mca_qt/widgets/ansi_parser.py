"""
MCA Qt - ANSI/VT100 Escape Sequence Parser.

Minimal terminal emulator parser that maintains a 2D character grid
with color and style attributes. Handles the most common ANSI escape
sequences needed for interactive shell use (colors, cursor movement,
screen/line clearing, scrolling).

Does NOT implement the full VT100 spec — only enough for PowerShell,
cmd.exe, and typical CLI tool output (Claude Code, git, etc.).

Dependencies:
    - None (pure Python)
"""

import re
import logging

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Default Terminal Colors -------------------------------------------------

# Standard 16-color ANSI palette (indices 0-15).
ANSI_COLORS_16 = [
    "#000000",  # 0  Black
    "#cd3131",  # 1  Red
    "#0dbc79",  # 2  Green
    "#e5e510",  # 3  Yellow
    "#2472c8",  # 4  Blue
    "#bc3fbc",  # 5  Magenta
    "#11a8cd",  # 6  Cyan
    "#e5e5e5",  # 7  White
    "#666666",  # 8  Bright Black (Gray)
    "#f14c4c",  # 9  Bright Red
    "#23d18b",  # 10 Bright Green
    "#f5f543",  # 11 Bright Yellow
    "#3b8eea",  # 12 Bright Blue
    "#d670d6",  # 13 Bright Magenta
    "#29b8db",  # 14 Bright Cyan
    "#e5e5e5",  # 15 Bright White
]

# Default foreground and background for the terminal.
DEFAULT_FG = "#cccccc"
DEFAULT_BG = "#1e1e1e"


# =============================================================================
# Cell — Single Character with Attributes
# =============================================================================

class Cell:
    """
    Represents a single character cell in the terminal grid.

    Stores the character glyph along with foreground/background colors
    and text style flags (bold, underline, italic).

    :param str char: The character to display (single character).
    :param str fg_color: Foreground color as hex string.
    :param str bg_color: Background color as hex string.
    :param bool bold: Whether the character is bold.
    :param bool underline: Whether the character is underlined.
    :param bool italic: Whether the character is italic.
    """

    __slots__ = ("char", "fg_color", "bg_color", "bold", "underline", "italic")

    def __init__(self, char=" ", fg_color=DEFAULT_FG, bg_color=DEFAULT_BG,
                 bold=False, underline=False, italic=False):
        self.char = char
        self.fg_color = fg_color
        self.bg_color = bg_color
        self.bold = bold
        self.underline = underline
        self.italic = italic

    def reset(self):
        """Reset cell to defaults (blank space, default colors, no style)."""
        self.char = " "
        self.fg_color = DEFAULT_FG
        self.bg_color = DEFAULT_BG
        self.bold = False
        self.underline = False
        self.italic = False


# =============================================================================
# ANSI Parser — Terminal Grid Manager
# =============================================================================

# Regex to match CSI (Control Sequence Introducer) escape sequences.
# Format: ESC [ <private-prefix?> <params> <intermediate> <final>
# Private prefixes: ? (DEC), > (XTMODKEYS), = (Kitty keyboard), < and !.
# Modern terminal programs (Claude Code, vim, etc.) use these extensively.
_CSI_RE = re.compile(r"\x1b\[([><=!]?[0-9;?]*)([A-Za-z@`])")

# Regex to match OSC (Operating System Command) sequences.
# Format: ESC ] <command> ; <text> (BEL | ESC \)
_OSC_RE = re.compile(r"\x1b\]([^\x07\x1b]*)(?:\x07|\x1b\\)")

# Regex to match any escape sequence (for skipping unsupported ones).
_ESC_RE = re.compile(r"\x1b(?:\[[><=!]?[0-9;?]*[A-Za-z@`]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-B]|[78DEHM=>])")


class AnsiParser:
    """
    ANSI/VT100 escape sequence parser with a 2D character grid.

    Maintains a grid of ``Cell`` objects representing the visible
    terminal screen. Processes raw output bytes from a PTY and
    updates the grid accordingly.

    Supports:
        - SGR color codes (16 colors, 256 colors, truecolor/24-bit)
        - Cursor movement (CSI A/B/C/D/H/f/G)
        - Screen clear (CSI 2J, CSI 3J)
        - Line clear (CSI K, CSI 0K, CSI 1K, CSI 2K)
        - Scroll up/down
        - Line feed, carriage return, backspace, tab
        - OSC title changes (OSC 0 and OSC 2)

    :param int rows: Number of visible rows.
    :param int cols: Number of visible columns.
    :param int scrollback_max: Maximum lines in the scrollback buffer.
    """

    def __init__(self, rows=24, cols=80, scrollback_max=5000):
        """
        Initialize the parser with an empty grid.

        :param int rows: Number of visible rows.
        :param int cols: Number of visible columns.
        :param int scrollback_max: Maximum scrollback lines.
        """
        self._rows = rows
        self._cols = cols
        self._scrollback_max = scrollback_max

        # The visible screen grid — list of rows, each row is a list of Cells.
        self._grid = self._make_grid(rows, cols)

        # Scrollback buffer — list of row data that scrolled off the top.
        self._scrollback = []

        # Cursor position (0-based).
        self._cursor_row = 0
        self._cursor_col = 0

        # Current text attributes (applied to new characters).
        self._fg = DEFAULT_FG
        self._bg = DEFAULT_BG
        self._bold = False
        self._underline = False
        self._italic = False
        self._reverse = False
        self._dim = False

        # Terminal title (set via OSC sequences).
        self._title = ""

        # Partial escape sequence buffer (for sequences split across reads).
        self._partial = ""

        # Scroll region (top and bottom row, 0-based, inclusive).
        self._scroll_top = 0
        self._scroll_bottom = rows - 1

        # Alternate screen buffer — TUI programs (Claude Code, vim, etc.)
        # switch to an alternate screen on startup and restore the original
        # screen on exit.  We save/restore the grid, cursor, scrollback,
        # and DEC private modes so the shell prompt reappears cleanly
        # after the TUI exits.
        self._alt_grid = None
        self._alt_cursor = None
        self._alt_scrollback = None
        self._alt_scroll_region = None
        self._alt_bracketed_paste = None
        self._in_alt_screen = False

        # Bracketed paste mode (DEC private mode 2004).
        # When enabled, terminal emulators must wrap pasted text in
        # ESC[200~ ... ESC[201~ so the running program (Claude Code,
        # vim, etc.) can distinguish pasted text from typed keystrokes.
        self._bracketed_paste = False

        # Cursor visibility (DEC private mode 25 — DECTCEM).
        # TUI apps (Claude Code, vim, etc.) send ESC[?25l to hide the
        # hardware cursor and render their own cursor via ANSI escape
        # sequences (inverse video, underline, etc.).  When hidden, the
        # terminal frontend should NOT draw its own block cursor —
        # otherwise both cursors are visible simultaneously.
        self._cursor_visible = True

    # --- Grid Construction ---------------------------------------------------

    def _make_grid(self, rows, cols):
        """
        Create a fresh grid of blank cells.

        :param int rows: Number of rows.
        :param int cols: Number of columns.
        :return: 2D list of Cell objects.
        :rtype: list
        """
        return [[Cell() for _ in range(cols)] for _ in range(rows)]

    def _make_row(self):
        """
        Create a single blank row.

        :return: List of blank Cell objects.
        :rtype: list
        """
        return [Cell() for _ in range(self._cols)]

    # --- Public API ----------------------------------------------------------

    def feed(self, data):
        """
        Process raw bytes from the PTY and update the grid.

        Handles printable characters, control characters (LF, CR, BS,
        TAB), and ANSI escape sequences.

        :param bytes data: Raw bytes from the PTY.
        """
        # Decode bytes to string.
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data

        # Prepend any partial escape sequence from the previous call.
        if self._partial:
            text = self._partial + text
            self._partial = ""

        i = 0
        length = len(text)

        while i < length:
            ch = text[i]

            if ch == "\x1b":
                # Start of an escape sequence.
                remaining = text[i:]

                # Check for CSI sequence.
                m = _CSI_RE.match(remaining)
                if m:
                    self._handle_csi(m.group(1), m.group(2))
                    i += m.end()
                    continue

                # Check for OSC sequence.
                m = _OSC_RE.match(remaining)
                if m:
                    self._handle_osc(m.group(1))
                    i += m.end()
                    continue

                # Check for any other escape sequence (skip it).
                m = _ESC_RE.match(remaining)
                if m:
                    i += m.end()
                    continue

                # Incomplete escape — save for next feed() call.
                if len(remaining) < 20:
                    self._partial = remaining
                    break
                else:
                    # Probably not a valid escape — skip the ESC char.
                    i += 1
                    continue

            elif ch == "\n":
                # Line feed — move cursor down, scroll if needed.
                self._linefeed()
                i += 1

            elif ch == "\r":
                # Carriage return — move cursor to column 0.
                self._cursor_col = 0
                i += 1

            elif ch == "\x08":
                # Backspace — move cursor left by one.
                if self._cursor_col > 0:
                    self._cursor_col -= 1
                i += 1

            elif ch == "\t":
                # Tab — advance to next tab stop (every 8 columns).
                next_tab = ((self._cursor_col // 8) + 1) * 8
                self._cursor_col = min(next_tab, self._cols - 1)
                i += 1

            elif ch == "\x07":
                # Bell — ignore (no audible bell in our terminal).
                i += 1

            elif ch == "\x00":
                # Null — ignore.
                i += 1

            else:
                # Printable character — write it to the grid.
                self._put_char(ch)
                i += 1

    def resize(self, rows, cols):
        """
        Resize the grid, preserving existing content where possible.

        :param int rows: New row count.
        :param int cols: New column count.
        """
        old_rows = self._rows
        old_cols = self._cols

        # Build new grid.
        new_grid = self._make_grid(rows, cols)

        # Copy existing content.
        for r in range(min(old_rows, rows)):
            for c in range(min(old_cols, cols)):
                old_cell = self._grid[r][c]
                new_cell = new_grid[r][c]
                new_cell.char = old_cell.char
                new_cell.fg_color = old_cell.fg_color
                new_cell.bg_color = old_cell.bg_color
                new_cell.bold = old_cell.bold
                new_cell.underline = old_cell.underline
                new_cell.italic = old_cell.italic

        self._grid = new_grid
        self._rows = rows
        self._cols = cols

        # Clamp cursor position to new bounds.
        self._cursor_row = min(self._cursor_row, rows - 1)
        self._cursor_col = min(self._cursor_col, cols - 1)

        # Update scroll region to match new dimensions.
        self._scroll_top = 0
        self._scroll_bottom = rows - 1

    def get_lines(self):
        """
        Return the current grid as a list of styled line data.

        Each line is a list of (char, fg_color, bg_color, bold, underline, italic)
        tuples. Includes scrollback lines above the visible grid.

        :return: List of lines, each line is a list of cell tuples.
        :rtype: list
        """
        lines = []

        # Add scrollback lines.
        for row in self._scrollback:
            line = []
            for cell in row:
                line.append((cell.char, cell.fg_color, cell.bg_color,
                             cell.bold, cell.underline, cell.italic))
            lines.append(line)

        # Add visible grid lines.
        for row in self._grid:
            line = []
            for cell in row:
                line.append((cell.char, cell.fg_color, cell.bg_color,
                             cell.bold, cell.underline, cell.italic))
            lines.append(line)

        return lines

    def get_visible_lines(self):
        """
        Return only the visible grid as styled line data (no scrollback).

        Each line is a list of (char, fg_color, bg_color, bold, underline, italic)
        tuples.

        :return: List of visible lines.
        :rtype: list
        """
        lines = []
        for row in self._grid:
            line = []
            for cell in row:
                line.append((cell.char, cell.fg_color, cell.bg_color,
                             cell.bold, cell.underline, cell.italic))
            lines.append(line)
        return lines

    def get_scrollback_lines(self, max_lines=0):
        """
        Return scrollback buffer as styled line data.

        Same tuple format as ``get_visible_lines()``.  Use ``max_lines``
        to cap the number of returned lines for performance — only the
        most recent scrollback lines are returned.

        :param int max_lines: Maximum lines to return (0 = all).
        :return: List of styled scrollback lines.
        :rtype: list
        """
        source = self._scrollback
        if max_lines > 0 and len(source) > max_lines:
            source = source[-max_lines:]

        lines = []
        for row in source:
            line = []
            for cell in row:
                line.append((cell.char, cell.fg_color, cell.bg_color,
                             cell.bold, cell.underline, cell.italic))
            lines.append(line)
        return lines

    def get_cursor_position(self):
        """
        Return the current cursor position.

        :return: (row, col) tuple, 0-based.
        :rtype: tuple
        """
        return (self._cursor_row, self._cursor_col)

    def is_cursor_visible(self):
        """
        Return whether the cursor should be drawn by the frontend.

        TUI apps send ESC[?25l to hide the cursor and render their own
        via ANSI escape sequences.  When False, the frontend must NOT
        draw its own block cursor to avoid a double-cursor artifact.

        :return: True if the cursor should be drawn.
        :rtype: bool
        """
        return self._cursor_visible

    def get_title(self):
        """
        Return the terminal title (set via OSC escape sequences).

        :return: The current terminal title.
        :rtype: str
        """
        return self._title

    def get_scrollback_length(self):
        """
        Return the number of lines in the scrollback buffer.

        :return: Number of scrollback lines.
        :rtype: int
        """
        return len(self._scrollback)

    def clear(self):
        """Clear the entire grid and scrollback buffer."""
        self._grid = self._make_grid(self._rows, self._cols)
        self._scrollback = []
        self._cursor_row = 0
        self._cursor_col = 0

    # --- Character Output ----------------------------------------------------

    def _put_char(self, ch):
        """
        Write a single character at the cursor position and advance.

        Handles line wrapping when the cursor reaches the right edge.

        :param str ch: Single character to write.
        """
        # Wrap to next line if we're past the right edge.
        if self._cursor_col >= self._cols:
            self._cursor_col = 0
            self._linefeed()

        # Write the character with current attributes.
        # Reverse video swaps fg/bg at write time so that SGR 27 (reverse
        # off) cleanly restores the original colors without tracking history.
        cell = self._grid[self._cursor_row][self._cursor_col]
        cell.char = ch
        if self._reverse:
            cell.fg_color = self._bg
            cell.bg_color = self._fg
        else:
            cell.fg_color = self._fg
            cell.bg_color = self._bg
        cell.bold = self._bold
        cell.underline = self._underline
        cell.italic = self._italic

        # Advance cursor.
        self._cursor_col += 1

    def _linefeed(self):
        """
        Move the cursor down one line, scrolling if necessary.

        When the cursor is at the bottom of the scroll region,
        the top line is moved to the scrollback buffer and all
        lines shift up.
        """
        if self._cursor_row < self._scroll_bottom:
            # Still within the scroll region — just move down.
            self._cursor_row += 1
        else:
            # At the bottom of the scroll region — scroll up.
            self._scroll_up()

    def _scroll_up(self):
        """
        Scroll the scroll region up by one line.

        The top line of the scroll region is moved to the scrollback
        buffer (if the scroll region starts at row 0), and a blank
        line is inserted at the bottom.
        """
        # Move the top line to scrollback (only if full-screen scroll region).
        if self._scroll_top == 0:
            self._scrollback.append(self._grid[self._scroll_top])
            # Trim scrollback to max size.
            if len(self._scrollback) > self._scrollback_max:
                self._scrollback = self._scrollback[-self._scrollback_max:]

        # Shift lines up within the scroll region.
        for r in range(self._scroll_top, self._scroll_bottom):
            self._grid[r] = self._grid[r + 1]

        # Insert blank line at the bottom of the scroll region.
        self._grid[self._scroll_bottom] = self._make_row()

    def _scroll_down(self):
        """
        Scroll the scroll region down by one line.

        A blank line is inserted at the top of the scroll region,
        and the bottom line is discarded.
        """
        # Shift lines down within the scroll region.
        for r in range(self._scroll_bottom, self._scroll_top, -1):
            self._grid[r] = self._grid[r - 1]

        # Insert blank line at the top of the scroll region.
        self._grid[self._scroll_top] = self._make_row()

    # --- CSI Sequence Handlers -----------------------------------------------

    def _handle_csi(self, params_str, cmd):
        """
        Handle a CSI (Control Sequence Introducer) escape sequence.

        :param str params_str: The parameter string (e.g., "1;31" or "2").
        :param str cmd: The final command character (e.g., "m", "H", "J").
        """
        # Private mode indicator — DEC private modes (?), XTMODKEYS (>),
        # Kitty keyboard protocol (=, >), and other private prefixes (<, !).
        is_private = params_str[:1] in ("?", ">", "=", "<", "!")

        # For non-DEC private prefixes (>, =, <, !), silently ignore the
        # entire sequence.  These are modern terminal protocol extensions
        # (XTMODKEYS, Kitty keyboard protocol, etc.) that our parser does
        # not need to implement — we just need to consume them so they
        # don't leak through as visible text.
        if is_private and params_str[:1] != "?":
            return

        # Parse parameters into a list of integers.
        # Skip parsing for DEC private mode sequences (? prefix) —
        # those are handled separately in the h/l command section.
        params = []
        if params_str and not is_private:
            for p in params_str.split(";"):
                try:
                    params.append(int(p))
                except ValueError:
                    params.append(0)

        if cmd == "m":
            # SGR — Select Graphic Rendition (colors and text style).
            self._handle_sgr(params)

        elif cmd == "H" or cmd == "f":
            # CUP — Cursor Position / HVP — Horizontal Vertical Position.
            row = (params[0] if params else 1) - 1
            col = (params[1] if len(params) > 1 else 1) - 1
            self._cursor_row = max(0, min(row, self._rows - 1))
            self._cursor_col = max(0, min(col, self._cols - 1))

        elif cmd == "A":
            # CUU — Cursor Up.
            n = params[0] if params else 1
            self._cursor_row = max(0, self._cursor_row - n)

        elif cmd == "B":
            # CUD — Cursor Down.
            n = params[0] if params else 1
            self._cursor_row = min(self._rows - 1, self._cursor_row + n)

        elif cmd == "C":
            # CUF — Cursor Forward (right).
            n = params[0] if params else 1
            self._cursor_col = min(self._cols - 1, self._cursor_col + n)

        elif cmd == "D":
            # CUB — Cursor Back (left).
            n = params[0] if params else 1
            self._cursor_col = max(0, self._cursor_col - n)

        elif cmd == "G":
            # CHA — Cursor Horizontal Absolute (move to column).
            col = (params[0] if params else 1) - 1
            self._cursor_col = max(0, min(col, self._cols - 1))

        elif cmd == "J":
            # ED — Erase in Display.
            mode = params[0] if params else 0
            self._erase_display(mode)

        elif cmd == "K":
            # EL — Erase in Line.
            mode = params[0] if params else 0
            self._erase_line(mode)

        elif cmd == "S":
            # SU — Scroll Up (scroll content up, new blank lines at bottom).
            n = params[0] if params else 1
            for _ in range(n):
                self._scroll_up()

        elif cmd == "T":
            # SD — Scroll Down (scroll content down, new blank lines at top).
            n = params[0] if params else 1
            for _ in range(n):
                self._scroll_down()

        elif cmd == "r":
            # DECSTBM — Set Scrolling Region.
            top = (params[0] if params else 1) - 1
            bottom = (params[1] if len(params) > 1 else self._rows) - 1
            self._scroll_top = max(0, min(top, self._rows - 1))
            self._scroll_bottom = max(0, min(bottom, self._rows - 1))

        elif cmd == "d":
            # VPA — Line Position Absolute (move to row).
            row = (params[0] if params else 1) - 1
            self._cursor_row = max(0, min(row, self._rows - 1))

        elif cmd == "h" or cmd == "l":
            # SM/RM — Set/Reset Mode.
            if is_private:
                # Parse ALL private mode numbers from the params string.
                # Programs can combine modes in one sequence, e.g.
                # ESC[?1049;2004h sets alt screen AND bracketed paste.
                # We must process every mode, not just the first.
                mode_str = params_str.lstrip("?")
                for mode_part in mode_str.split(";"):
                    try:
                        mode = int(mode_part) if mode_part else 0
                    except ValueError:
                        continue

                    if mode in (1049, 47):
                        # Alternate screen buffer — used by TUI programs
                        # (Claude Code, vim, less) to draw their UI
                        # without overwriting the shell session.
                        if cmd == "h":
                            self._enter_alt_screen()
                        else:
                            self._leave_alt_screen()
                    elif mode == 25:
                        # DECTCEM — cursor visibility.  TUI apps send
                        # ?25l to hide the hardware cursor and render
                        # their own.  ?25h restores it on exit.
                        self._cursor_visible = (cmd == "h")
                    elif mode == 2004:
                        # Bracketed paste mode — when enabled, pasted
                        # text must be wrapped in ESC[200~ ... ESC[201~
                        # so the running program can distinguish pastes
                        # from typing.
                        self._bracketed_paste = (cmd == "h")
                        logger.debug("Bracketed paste mode %s (alt_screen=%s)",
                                     "ENABLED" if self._bracketed_paste else "DISABLED",
                                     self._in_alt_screen)

        elif cmd == "X":
            # ECH — Erase Character (blank N chars at cursor).
            # Uses current background color per VT100 spec.
            n = params[0] if params else 1
            for j in range(n):
                c = self._cursor_col + j
                if c < self._cols:
                    self._erase_cell(self._cursor_row, c)

        elif cmd == "P":
            # DCH — Delete Character (shift left).
            n = params[0] if params else 1
            row = self._grid[self._cursor_row]
            for _ in range(n):
                if self._cursor_col < len(row):
                    row.pop(self._cursor_col)
                    row.append(Cell())

        elif cmd == "L":
            # IL — Insert Line.
            n = params[0] if params else 1
            for _ in range(n):
                if self._cursor_row <= self._scroll_bottom:
                    self._grid.insert(self._cursor_row, self._make_row())
                    if self._scroll_bottom < len(self._grid):
                        self._grid.pop(self._scroll_bottom + 1)

        elif cmd == "M":
            # DL — Delete Line.
            n = params[0] if params else 1
            for _ in range(n):
                if self._cursor_row <= self._scroll_bottom:
                    self._grid.pop(self._cursor_row)
                    self._grid.insert(self._scroll_bottom, self._make_row())

        elif cmd == "@":
            # ICH — Insert Character (shift right).
            n = params[0] if params else 1
            row = self._grid[self._cursor_row]
            for _ in range(n):
                row.insert(self._cursor_col, Cell())
                if len(row) > self._cols:
                    row.pop()

        # Other CSI commands are silently ignored.

    def _handle_sgr(self, params):
        """
        Handle SGR (Select Graphic Rendition) parameters.

        Processes color and style escape sequences to update the
        current text attributes.

        :param list params: List of integer SGR parameters.
        """
        if not params:
            params = [0]

        i = 0
        while i < len(params):
            p = params[i]

            if p == 0:
                # Reset all attributes.
                self._fg = DEFAULT_FG
                self._bg = DEFAULT_BG
                self._bold = False
                self._underline = False
                self._italic = False
                self._reverse = False
                self._dim = False

            elif p == 1:
                self._bold = True
            elif p == 2:
                # Dim/faint text — reduce intensity.
                self._dim = True
            elif p == 3:
                self._italic = True
            elif p == 4:
                self._underline = True
            elif p == 22:
                # Normal intensity — turns off both bold and dim.
                self._bold = False
                self._dim = False
            elif p == 23:
                self._italic = False
            elif p == 24:
                self._underline = False

            # Standard foreground colors (30-37).
            elif 30 <= p <= 37:
                idx = p - 30
                # Bold shifts to bright colors (8-15).
                if self._bold and idx < 8:
                    self._fg = ANSI_COLORS_16[idx + 8]
                else:
                    self._fg = ANSI_COLORS_16[idx]

            # Standard background colors (40-47).
            elif 40 <= p <= 47:
                self._bg = ANSI_COLORS_16[p - 40]

            # Bright foreground colors (90-97).
            elif 90 <= p <= 97:
                self._fg = ANSI_COLORS_16[p - 90 + 8]

            # Bright background colors (100-107).
            elif 100 <= p <= 107:
                self._bg = ANSI_COLORS_16[p - 100 + 8]

            # Default foreground.
            elif p == 39:
                self._fg = DEFAULT_FG

            # Default background.
            elif p == 49:
                self._bg = DEFAULT_BG

            # Extended color: 38;5;n (256-color) or 38;2;r;g;b (truecolor).
            elif p == 38:
                color, consumed = self._parse_extended_color(params, i)
                if color:
                    self._fg = color
                i += consumed

            # Extended background: 48;5;n or 48;2;r;g;b.
            elif p == 48:
                color, consumed = self._parse_extended_color(params, i)
                if color:
                    self._bg = color
                i += consumed

            # Reverse video — colors are swapped at write time in _put_char().
            # Tracked as a flag so SGR 27 can cleanly turn it off.
            elif p == 7:
                self._reverse = True

            # Reverse video off.
            elif p == 27:
                self._reverse = False

            # Other SGR params are ignored silently.

            i += 1

    def _parse_extended_color(self, params, i):
        """
        Parse 256-color or truecolor extended color sequences.

        :param list params: Full SGR parameter list.
        :param int i: Current index (pointing to 38 or 48).
        :return: (hex_color, params_consumed) tuple.
        :rtype: tuple
        """
        if i + 1 < len(params):
            mode = params[i + 1]

            if mode == 5 and i + 2 < len(params):
                # 256-color mode: 38;5;n
                n = params[i + 2]
                return (self._color_256(n), 2)

            elif mode == 2 and i + 4 < len(params):
                # Truecolor mode: 38;2;r;g;b
                r = max(0, min(255, params[i + 2]))
                g = max(0, min(255, params[i + 3]))
                b = max(0, min(255, params[i + 4]))
                return ("#{:02x}{:02x}{:02x}".format(r, g, b), 4)

        return (None, 0)

    def _color_256(self, n):
        """
        Convert a 256-color index to a hex color string.

        Indices 0-15 use the standard ANSI palette.
        Indices 16-231 use a 6x6x6 color cube.
        Indices 232-255 use a grayscale ramp.

        :param int n: Color index (0-255).
        :return: Hex color string.
        :rtype: str
        """
        n = max(0, min(255, n))

        if n < 16:
            return ANSI_COLORS_16[n]

        if n < 232:
            # 6x6x6 color cube.
            n -= 16
            b = (n % 6) * 51
            g = ((n // 6) % 6) * 51
            r = (n // 36) * 51
            return "#{:02x}{:02x}{:02x}".format(r, g, b)

        # Grayscale ramp (232-255).
        gray = (n - 232) * 10 + 8
        return "#{:02x}{:02x}{:02x}".format(gray, gray, gray)

    # --- Erase Operations ----------------------------------------------------

    def _erase_display(self, mode):
        """
        Erase part or all of the display.

        Per VT100 spec, erased cells use the current background color
        (not always the default).  TUI programs use "set bg then erase"
        to paint colored regions.

        :param int mode: 0 = cursor to end, 1 = start to cursor,
            2 = entire screen, 3 = entire screen + scrollback.
        """
        if mode == 0:
            # Erase from cursor to end of screen.
            for c in range(self._cursor_col, self._cols):
                self._erase_cell(self._cursor_row, c)
            for r in range(self._cursor_row + 1, self._rows):
                for c in range(self._cols):
                    self._erase_cell(r, c)

        elif mode == 1:
            # Erase from start of screen to cursor.
            for r in range(self._cursor_row):
                for c in range(self._cols):
                    self._erase_cell(r, c)
            for c in range(self._cursor_col + 1):
                self._erase_cell(self._cursor_row, c)

        elif mode == 2:
            # Erase entire screen (keep scrollback).
            for r in range(self._rows):
                for c in range(self._cols):
                    self._erase_cell(r, c)

        elif mode == 3:
            # Erase entire screen AND scrollback.
            self.clear()

    def _erase_line(self, mode):
        """
        Erase part or all of the current line.

        Erased cells use the current background color per VT100 spec.

        :param int mode: 0 = cursor to end, 1 = start to cursor,
            2 = entire line.
        """
        row = self._cursor_row

        if mode == 0:
            # Erase from cursor to end of line.
            for c in range(self._cursor_col, self._cols):
                self._erase_cell(row, c)

        elif mode == 1:
            # Erase from start of line to cursor.
            for c in range(self._cursor_col + 1):
                self._erase_cell(row, c)

        elif mode == 2:
            # Erase entire line.
            for c in range(self._cols):
                self._erase_cell(row, c)

    def _erase_cell(self, row, col):
        """
        Erase a single cell, filling it with the current background color.

        Per VT100 spec, erase operations use the current SGR background,
        not the default.  This allows TUI programs to paint colored
        regions by setting a bg color and then erasing.

        :param int row: Row index (0-based).
        :param int col: Column index (0-based).
        """
        cell = self._grid[row][col]
        cell.char = " "
        cell.fg_color = DEFAULT_FG
        cell.bg_color = self._bg
        cell.bold = False
        cell.underline = False
        cell.italic = False

    # --- Alternate Screen Buffer ---------------------------------------------

    def _enter_alt_screen(self):
        """
        Switch to the alternate screen buffer.

        Saves the current grid, cursor position, scrollback, scroll
        region, and DEC private mode state (bracketed paste), then
        clears the screen.  TUI programs (Claude Code, vim, less) use
        this so their UI doesn't overwrite the shell session.  When the
        program exits, ``_leave_alt_screen()`` restores the original
        content and mode state.
        """
        if self._in_alt_screen:
            return

        # Save the main screen state (including DEC private modes).
        self._alt_grid = self._grid
        self._alt_cursor = (self._cursor_row, self._cursor_col)
        self._alt_scrollback = self._scrollback
        self._alt_scroll_region = (self._scroll_top, self._scroll_bottom)
        self._alt_bracketed_paste = self._bracketed_paste
        self._alt_cursor_visible = self._cursor_visible

        # Switch to a fresh screen.
        self._grid = self._make_grid(self._rows, self._cols)
        self._scrollback = []
        self._cursor_row = 0
        self._cursor_col = 0
        self._scroll_top = 0
        self._scroll_bottom = self._rows - 1
        self._cursor_visible = True
        self._in_alt_screen = True

        logger.debug("Entered alternate screen buffer")

    def _leave_alt_screen(self):
        """
        Switch back to the main screen buffer.

        Restores the grid, cursor, scrollback, scroll region, and DEC
        private mode state that were saved when entering the alternate
        screen.  If we were never in alt screen, this is a no-op.
        """
        if not self._in_alt_screen:
            return

        # Restore the main screen state (including DEC private modes).
        if self._alt_grid is not None:
            self._grid = self._alt_grid
            self._cursor_row, self._cursor_col = self._alt_cursor
            self._scrollback = self._alt_scrollback
            self._scroll_top, self._scroll_bottom = self._alt_scroll_region
            self._bracketed_paste = self._alt_bracketed_paste
            self._cursor_visible = getattr(self, "_alt_cursor_visible", True)

        # Clear saved state.
        self._alt_grid = None
        self._alt_cursor = None
        self._alt_scrollback = None
        self._alt_scroll_region = None
        self._alt_bracketed_paste = None
        self._in_alt_screen = False

        logger.debug("Left alternate screen buffer — main screen restored")

    # --- OSC Sequence Handlers -----------------------------------------------

    def _handle_osc(self, payload):
        """
        Handle an OSC (Operating System Command) sequence.

        Currently only supports title changes (OSC 0 and OSC 2).

        :param str payload: The OSC payload string.
        """
        # OSC format: "command;text"
        if ";" in payload:
            cmd, text = payload.split(";", 1)
            try:
                cmd_num = int(cmd)
            except ValueError:
                return

            if cmd_num in (0, 2):
                # Set window title.
                self._title = text
