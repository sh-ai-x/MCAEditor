"""
MCA Editor - Code Editor Widget.

Custom code editor with syntax highlighting, line numbers, auto-complete,
brace matching, and other IDE features. Inspired by Charcoal Editor 2.

Dependencies:
    - PySide6 (QPlainTextEdit, QSyntaxHighlighter, QPainter, etc.)
"""

import re
import logging

from mca_qt.qt_compat import (
    QPlainTextEdit, QWidget, QTextEdit,
    Qt, QRect, QSize, Signal, QTimer, QEvent,
    QColor, QPainter, QTextFormat, QFont, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QToolTip,
)

# Module-level logger for editor operations.
logger = logging.getLogger(__name__)


# =============================================================================
# Syntax Highlighting
# =============================================================================

class PythonHighlighter(QSyntaxHighlighter):
    """
    Python syntax highlighter matching the dark theme style.

    Highlights keywords, builtins, decorators, numbers, strings,
    function/class definitions, function calls, operators, and comments.

    An optional ``color_scheme`` dict allows external customization of
    token colors and styles.  Keys are ``("python", token_key)`` tuples;
    values are ``{"fg": str, "bold": bool, "italic": bool}``.

    :param QTextDocument parent: The document to highlight.
    :param dict color_scheme: Optional color scheme override dict.
    """

    def __init__(self, parent=None, color_scheme=None):
        """
        Initialize the highlighter and build all rules.

        :param QTextDocument parent: The document to highlight.
        :param dict color_scheme: Optional color scheme override dict.
        """
        super().__init__(parent)
        # Store the color scheme for rule building and multiline strings.
        self._color_scheme = color_scheme or {}
        self._rules = []
        self._build_rules()

    def _make_format(self, color, bold=False, italic=False):
        """
        Create a QTextCharFormat with the given style.

        :param str color: Hex color string.
        :param bool bold: Whether the text should be bold.
        :param bool italic: Whether the text should be italic.
        :return: Configured text format.
        :rtype: QTextCharFormat
        """
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _token_style(self, token_key, default_fg, default_bold=False, default_italic=False):
        """
        Look up a token's style from the color scheme with hardcoded fallback.

        :param str token_key: Token identifier (e.g. ``"keyword"``).
        :param str default_fg: Default foreground hex color.
        :param bool default_bold: Default bold flag.
        :param bool default_italic: Default italic flag.
        :return: Tuple of (fg, bold, italic).
        :rtype: tuple
        """
        style = self._color_scheme.get(("python", token_key), {})
        fg = style.get("fg", default_fg)
        bold = style.get("bold", default_bold)
        italic = style.get("italic", default_italic)
        return fg, bold, italic

    def _build_rules(self):
        """Build all syntax highlighting rules as (regex, format) pairs."""
        # --- Keywords ---
        fg, bold, italic = self._token_style("keyword", "#569cd6", True)
        keyword_fmt = self._make_format(fg, bold, italic)
        keywords = [
            "and", "as", "assert", "async", "await", "break", "class",
            "continue", "def", "del", "elif", "else", "except", "finally",
            "for", "from", "global", "if", "import", "in", "is", "lambda",
            "nonlocal", "not", "or", "pass", "raise", "return", "try",
            "while", "with", "yield"
        ]
        for kw in keywords:
            self._rules.append((re.compile(r"\b{}\b".format(kw)), keyword_fmt))

        # --- Builtins ---
        fg, bold, italic = self._token_style("builtin", "#4ec9b0")
        builtin_fmt = self._make_format(fg, bold, italic)
        builtins = [
            "True", "False", "None", "self", "cls",
            "print", "range", "len", "type", "int", "float", "str",
            "list", "dict", "tuple", "set", "bool", "bytes",
            "isinstance", "issubclass", "hasattr", "getattr", "setattr",
            "super", "property", "staticmethod", "classmethod",
            "enumerate", "zip", "map", "filter", "sorted", "reversed",
            "open", "input", "abs", "all", "any", "min", "max", "sum",
        ]
        for b in builtins:
            self._rules.append((re.compile(r"\b{}\b".format(b)), builtin_fmt))

        # --- Decorators ---
        fg, bold, italic = self._token_style("decorator", "#d7ba7d")
        decorator_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"@\w+"), decorator_fmt))

        # --- Numbers (decimal and hex) ---
        fg, bold, italic = self._token_style("number", "#b5cea8")
        number_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\b\d+\.?\d*([eE][+-]?\d+)?\b"), number_fmt))
        self._rules.append((re.compile(r"\b0[xX][0-9a-fA-F]+\b"), number_fmt))

        # --- Function definitions (highlight the name after 'def') ---
        fg, bold, italic = self._token_style("funcdef", "#dcdcaa")
        func_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\bdef\s+(\w+)"), func_fmt))

        # --- Class definitions (highlight the name after 'class') ---
        fg, bold, italic = self._token_style("classdef", "#4ec9b0", True)
        class_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\bclass\s+(\w+)"), class_fmt))

        # --- Function calls (word followed by opening paren) ---
        fg, bold, italic = self._token_style("funccall", "#dcdcaa")
        call_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\b(\w+)\s*\("), call_fmt))

        # --- Operators ---
        fg, bold, italic = self._token_style("operator", "#d4d4d4")
        operator_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"[+\-*/%=<>!&|^~]"), operator_fmt))

        # --- Single-line strings (double and single quoted, with f-string support) ---
        fg, bold, italic = self._token_style("string", "#ce9178")
        string_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r'f?"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))
        self._rules.append((re.compile(r"f?'[^'\\]*(\\.[^'\\]*)*'"), string_fmt))

        # --- Comments (must be last to override other rules) ---
        fg, bold, italic = self._token_style("comment", "#6a9955", False, True)
        comment_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"#[^\n]*"), comment_fmt))

    def highlightBlock(self, text):
        """
        Apply highlighting rules to a single block of text.

        :param str text: The text content of the block.
        """
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                # For patterns with capture groups (def name, class name),
                # highlight the captured group instead of the full match.
                if match.lastindex and match.lastindex >= 1:
                    start = match.start(1)
                    length = match.end(1) - start
                else:
                    start = match.start()
                    length = match.end() - start
                self.setFormat(start, length, fmt)

        # Handle multi-line triple-quoted strings separately.
        self._highlight_multiline_strings(text)

    def _highlight_multiline_strings(self, text):
        """
        Handle triple-quote string highlighting across multiple blocks.

        Uses block state to track whether we are inside a triple-quoted
        string from a previous line.

        :param str text: The text content of the current block.
        """
        # Use the color scheme for multi-line string color.
        fg, bold, italic = self._token_style("multiline_string", "#ce9178")
        string_fmt = self._make_format(fg, bold, italic)

        # State: 0 = normal, 1 = in triple double-quote, 2 = in triple single-quote
        state = self.previousBlockState()
        if state == -1:
            state = 0

        i = 0
        start = 0
        while i < len(text):
            if state == 0:
                # Look for opening triple quotes.
                if text[i:i + 3] == '"""':
                    state = 1
                    start = i
                    i += 3
                elif text[i:i + 3] == "'''":
                    state = 2
                    start = i
                    i += 3
                else:
                    i += 1
            elif state == 1:
                # Inside triple double-quote, look for closing.
                if text[i:i + 3] == '"""':
                    self.setFormat(start, i + 3 - start, string_fmt)
                    state = 0
                    i += 3
                else:
                    i += 1
            elif state == 2:
                # Inside triple single-quote, look for closing.
                if text[i:i + 3] == "'''":
                    self.setFormat(start, i + 3 - start, string_fmt)
                    state = 0
                    i += 3
                else:
                    i += 1

        # If we ended still inside a triple-quote, highlight to end of line.
        if state != 0:
            self.setFormat(start, len(text) - start, string_fmt)

        self.setCurrentBlockState(state)


class MELHighlighter(QSyntaxHighlighter):
    """
    MEL (Maya Embedded Language) syntax highlighter.

    Highlights keywords, variables, numbers, strings, proc definitions,
    and comments.

    An optional ``color_scheme`` dict allows external customization of
    token colors and styles.  Keys are ``("mel", token_key)`` tuples;
    values are ``{"fg": str, "bold": bool, "italic": bool}``.

    :param QTextDocument parent: The document to highlight.
    :param dict color_scheme: Optional color scheme override dict.
    """

    def __init__(self, parent=None, color_scheme=None):
        """
        Initialize the MEL highlighter.

        :param QTextDocument parent: The document to highlight.
        :param dict color_scheme: Optional color scheme override dict.
        """
        super().__init__(parent)
        # Store the color scheme for rule building.
        self._color_scheme = color_scheme or {}
        self._rules = []
        self._build_rules()

    def _make_format(self, color, bold=False, italic=False):
        """
        Create a QTextCharFormat with the given style.

        :param str color: Hex color string.
        :param bool bold: Whether the text should be bold.
        :param bool italic: Whether the text should be italic.
        :return: Configured text format.
        :rtype: QTextCharFormat
        """
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _token_style(self, token_key, default_fg, default_bold=False, default_italic=False):
        """
        Look up a token's style from the color scheme with hardcoded fallback.

        :param str token_key: Token identifier (e.g. ``"keyword"``).
        :param str default_fg: Default foreground hex color.
        :param bool default_bold: Default bold flag.
        :param bool default_italic: Default italic flag.
        :return: Tuple of (fg, bold, italic).
        :rtype: tuple
        """
        style = self._color_scheme.get(("mel", token_key), {})
        fg = style.get("fg", default_fg)
        bold = style.get("bold", default_bold)
        italic = style.get("italic", default_italic)
        return fg, bold, italic

    def _build_rules(self):
        """Build MEL-specific syntax highlighting rules."""
        # --- Keywords ---
        fg, bold, italic = self._token_style("keyword", "#569cd6", True)
        keyword_fmt = self._make_format(fg, bold, italic)
        keywords = [
            "if", "else", "for", "while", "do", "in", "break", "continue",
            "return", "switch", "case", "default", "proc", "global", "local",
            "string", "int", "float", "vector", "matrix", "source", "catch",
            "true", "false", "yes", "no", "on", "off"
        ]
        for kw in keywords:
            self._rules.append((re.compile(r"\b{}\b".format(kw)), keyword_fmt))

        # --- MEL variables ($ prefix) ---
        fg, bold, italic = self._token_style("variable", "#9cdcfe")
        var_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\$\w+"), var_fmt))

        # --- Numbers ---
        fg, bold, italic = self._token_style("number", "#b5cea8")
        number_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\b\d+\.?\d*\b"), number_fmt))

        # --- Strings ---
        fg, bold, italic = self._token_style("string", "#ce9178")
        string_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))

        # --- Proc definitions (highlight the procedure name) ---
        fg, bold, italic = self._token_style("procdef", "#dcdcaa")
        proc_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"\bproc\s+\w*\s*(\w+)"), proc_fmt))

        # --- Comments (// style) ---
        fg, bold, italic = self._token_style("comment", "#6a9955", False, True)
        comment_fmt = self._make_format(fg, bold, italic)
        self._rules.append((re.compile(r"//[^\n]*"), comment_fmt))

    def highlightBlock(self, text):
        """
        Apply MEL highlighting rules to a single block.

        :param str text: The text content of the block.
        """
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                if match.lastindex and match.lastindex >= 1:
                    start = match.start(1)
                    length = match.end(1) - start
                else:
                    start = match.start()
                    length = match.end() - start
                self.setFormat(start, length, fmt)


# =============================================================================
# Line Number Area
# =============================================================================

class LineNumberArea(QWidget):
    """
    Line number gutter widget for the code editor.

    Delegates all painting to the parent editor's paint_line_numbers method.

    :param MCACodeEditor editor: The parent code editor widget.
    """

    def __init__(self, editor):
        """
        Initialize the line number area.

        :param MCACodeEditor editor: The parent code editor.
        """
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        """
        Return the preferred width based on the editor's line count.

        :return: Size hint for the gutter.
        :rtype: QSize
        """
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        """
        Delegate painting to the editor.

        :param QPaintEvent event: The paint event.
        """
        self._editor.paint_line_numbers(event)


# =============================================================================
# Code Editor
# =============================================================================

# Bracket pairs for matching.
MATCHING_BRACKETS = {
    "(": ")", ")": "(",
    "[": "]", "]": "[",
    "{": "}", "}": "{",
}


class MCACodeEditor(QPlainTextEdit):
    """
    Full-featured code editor widget.

    Mirrors Charcoal Editor 2 capabilities:
        - Line numbers with current line highlight
        - Syntax highlighting (Python, MEL, extensible)
        - Brace matching
        - Auto-indent and smart indent
        - Word/brace matching highlights
        - Auto-close brackets and quotes
        - Tab/space handling
        - Toggle comment (Ctrl+/)

    :param QWidget parent: Optional parent widget.
    """

    # --- Signals ---
    execute_requested = Signal()           # Execute full script
    execute_selected_requested = Signal()  # Execute selected text
    execute_line_requested = Signal()      # Execute current line
    file_modified = Signal(bool)           # Document modified state changed
    cursor_position_changed_info = Signal(int, int)  # line, column
    completion_requested = Signal(bool)    # Auto-complete trigger (arg = is_manual)
    zoom_requested = Signal(int)           # Ctrl+scroll zoom: +1 (in) or -1 (out)

    def __init__(self, parent=None):
        """
        Initialize the code editor with all features.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)

        # --- Configuration ---
        self._language = "python"
        self._color_scheme = None
        self._file_path = None
        self._is_temporary = True
        self._tab_size = 4
        self._use_spaces = True
        self._auto_close_brackets = True
        self._auto_close_quotes = True
        self._show_indent_guides = True
        self._highlight_matching_words = True

        # Completer reference — set by the panel via set_completer().
        self._completer = None
        # Settings reference — set by the panel so the editor can check
        # per-language auto-complete toggles during key handling.
        self._settings = None

        # --- Diagnostics (inline error/warning markers) ---
        # Populated by set_diagnostics() after the analyzer runs.
        self._diagnostics = []       # Full list of diagnostic dicts from analyzer.
        self._diagnostic_lines = {}  # {line_number: severity} for fast gutter lookup.

        # --- Search highlights (from FindReplaceBar) ---
        # Stored separately so they can be merged into ExtraSelections
        # alongside bracket-matching, word-matching, and diagnostics.
        self._search_selections = []

        # Setup monospace font for code editing.
        font = QFont("JetBrains Mono, Consolas, Courier New", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self._tab_size)

        # Line number gutter.
        self._line_number_area = LineNumberArea(self)

        # Syntax highlighter (set based on language).
        self._highlighter = None
        self.set_language("python")

        # Connect internal signals for UI updates.
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.modificationChanged.connect(self.file_modified.emit)

        # --- Debounced analysis timer ---
        # Runs code analysis 500ms after the user stops typing to avoid
        # burning CPU on every keystroke in large files.
        self._analysis_timer = QTimer()
        self._analysis_timer.setSingleShot(True)
        self._analysis_timer.setInterval(500)  # 500ms debounce.
        self._analysis_timer.timeout.connect(self._run_analysis)
        self.textChanged.connect(self._analysis_timer.start)

        # Initial gutter width calculation.
        self._update_line_number_area_width(0)
        self._setup_editor_style()

    def _setup_editor_style(self):
        """Configure editor appearance to match the dark theme."""
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                selection-background-color: #264f78;
                selection-color: #ffffff;
                border: none;
            }
        """)
        # Wider cursor for visibility on dark backgrounds.
        self.setCursorWidth(2)

    # --- Language / Highlighter ----------------------------------------------

    def set_language(self, language):
        """
        Set the editor language and swap the syntax highlighter.

        :param str language: Language identifier ('python', 'mel', etc.).
        """
        self._language = language.lower()

        # Detach the old highlighter before creating a new one.
        if self._highlighter:
            self._highlighter.setDocument(None)

        if self._language == "python":
            self._highlighter = PythonHighlighter(
                self.document(), color_scheme=self._color_scheme
            )
        elif self._language == "mel":
            self._highlighter = MELHighlighter(
                self.document(), color_scheme=self._color_scheme
            )
        elif self._language == "text":
            # Plain text mode — no syntax highlighting.
            self._highlighter = None
        else:
            self._highlighter = None

    def set_color_scheme(self, scheme_dict):
        """
        Set the color scheme and rebuild the syntax highlighter.

        :param dict scheme_dict: Color scheme keyed by ``(lang, token)``
            with ``{fg, bold, italic}`` values.
        """
        self._color_scheme = scheme_dict
        self.rebuild_highlighter()

    def rebuild_highlighter(self):
        """
        Detach the current highlighter and create a new one with the
        current language and color scheme.  Used after color scheme changes.
        """
        # Re-use set_language which already handles detach + create.
        self.set_language(self._language)

    @property
    def language(self):
        """
        The current language mode.

        :rtype: str
        """
        return self._language

    @property
    def file_path(self):
        """
        The file path associated with this editor, or None for temp buffers.

        :rtype: str or None
        """
        return self._file_path

    @file_path.setter
    def file_path(self, path):
        """
        Set the file path and auto-detect language from extension.

        :param str path: Absolute file path, or None for temp buffers.
        """
        self._file_path = path
        self._is_temporary = path is None

        # Auto-detect language from file extension.
        if path:
            if path.endswith(".py"):
                self.set_language("python")
            elif path.endswith(".mel"):
                self.set_language("mel")
            elif path.endswith(".txt"):
                self.set_language("text")
            elif path.endswith(".cs"):
                self.set_language("csharp")
            elif path.endswith(".lua"):
                self.set_language("lua")

    @property
    def is_temporary(self):
        """
        Whether this editor is a temporary buffer (not backed by a file).

        :rtype: bool
        """
        return self._is_temporary

    # --- Completer -----------------------------------------------------------

    def set_completer(self, completer):
        """
        Attach a CodeCompleter popup to this editor.

        :param CodeCompleter completer: The completer widget to attach,
            or None to detach.
        """
        self._completer = completer

    def focusOutEvent(self, event):
        """
        Dismiss the completer popup when the editor loses focus.

        Covers clicking the sidebar, output panel, another tab, or
        switching to a different application entirely.

        :param QFocusEvent event: The focus-out event.
        """
        if self._completer and self._completer.is_active:
            self._completer.dismiss()
        super().focusOutEvent(event)

    # --- Search Highlights ---------------------------------------------------

    def set_search_selections(self, selections):
        """
        Set search-match highlights from the FindReplaceBar.

        These are merged into the extra-selections alongside bracket
        matching, word highlights, and diagnostic underlines on the
        next cursor-position update.

        :param list selections: List of QTextEdit.ExtraSelection items
            representing search matches.
        """
        self._search_selections = selections
        # Refresh extra selections immediately so highlights appear
        # even if the cursor hasn't moved.
        self._on_cursor_position_changed()

    # --- Whitespace Rendering ------------------------------------------------

    def set_show_whitespace(self, enabled):
        """
        Toggle visible whitespace characters (dots for spaces, arrows for tabs).

        Uses QTextOption.ShowTabsAndSpaces to render whitespace glyphs
        directly in the editor viewport.

        :param bool enabled: True to show whitespace, False to hide.
        """
        from mca_qt.qt_compat import QTextOption
        option = self.document().defaultTextOption()
        flags = option.flags()
        if enabled:
            flags |= QTextOption.Flag.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.Flag.ShowTabsAndSpaces
        option.setFlags(flags)
        self.document().setDefaultTextOption(option)

    # --- Line Numbers --------------------------------------------------------

    def line_number_area_width(self):
        """
        Calculate the required width for the line number gutter.

        Width adapts to the number of digits in the highest line number.

        :return: Pixel width for the gutter.
        :rtype: int
        """
        digits = max(1, len(str(self.blockCount())))
        # 8px left padding + digit width + 12px right padding.
        space = 8 + self.fontMetrics().horizontalAdvance("9") * (digits + 1) + 12
        return space

    def _update_line_number_area_width(self, _):
        """Adjust viewport margins to make room for the gutter."""
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        """
        Update the line number area when the editor scrolls or resizes.

        :param QRect rect: The area that needs updating.
        :param int dy: Vertical scroll delta.
        """
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(),
                self._line_number_area.width(),
                rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def paint_line_numbers(self, event):
        """
        Paint line numbers in the gutter area.

        The current line number is highlighted brighter than the rest.

        :param QPaintEvent event: The paint event from the gutter widget.
        """
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor(30, 30, 30))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                # Highlight the current line number brighter.
                if block_number == current_line:
                    painter.setPen(QColor(200, 200, 200))
                else:
                    painter.setPen(QColor(90, 90, 90))
                painter.drawText(
                    0, top,
                    self._line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number
                )

                # --- Diagnostic gutter dot ---
                # Draw a smooth colored circle in the left margin if this
                # line has a diagnostic (red for errors, yellow for warnings).
                line_1based = block_number + 1
                if line_1based in self._diagnostic_lines:
                    severity = self._diagnostic_lines[line_1based]
                    dot_color = QColor("#f44747") if severity == "error" else QColor("#cca700")
                    # Enable anti-aliasing so the circle looks smooth.
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(dot_color)
                    # 10px dot centered vertically in the line, 1px from left edge.
                    dot_size = 10
                    dot_y = top + (self.fontMetrics().height() - dot_size) // 2
                    painter.drawEllipse(1, int(dot_y), dot_size, dot_size)
                    # Restore default rendering for text drawing.
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

        painter.end()

    def resizeEvent(self, event):
        """
        Reposition the line number area on editor resize.

        :param QResizeEvent event: The resize event.
        """
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    # --- Cursor Position & Highlights ----------------------------------------

    def _on_cursor_position_changed(self):
        """Update cursor info, current line highlight, and bracket matching."""
        # Emit position info for the status bar.
        cursor = self.textCursor()
        self.cursor_position_changed_info.emit(
            cursor.blockNumber() + 1,
            cursor.columnNumber() + 1
        )

        # Build the list of extra selections (highlights).
        extra_selections = []

        # Current line highlight (subtle background change).
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(40, 40, 40))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)

        # Matching bracket highlights.
        extra_selections.extend(self._find_matching_bracket())

        # Matching word highlights (all occurrences of word under cursor).
        if self._highlight_matching_words:
            extra_selections.extend(self._find_matching_words())

        # Diagnostic underlines (wavy red/yellow lines under errors/warnings).
        extra_selections.extend(self._build_diagnostic_selections())

        # Search-match highlights from the FindReplaceBar.
        extra_selections.extend(self._search_selections)

        self.setExtraSelections(extra_selections)

    def _find_matching_bracket(self):
        """
        Find and highlight matching bracket pair at cursor position.

        :return: List of ExtraSelection items for the bracket pair.
        :rtype: list
        """
        selections = []
        cursor = self.textCursor()
        text = cursor.block().text()
        pos = cursor.positionInBlock()

        # Check character at cursor or just before cursor.
        char = None
        if pos < len(text) and text[pos] in MATCHING_BRACKETS:
            char = text[pos]
            search_pos = cursor.position()
        elif pos > 0 and text[pos - 1] in MATCHING_BRACKETS:
            char = text[pos - 1]
            search_pos = cursor.position() - 1

        if char:
            match_char = MATCHING_BRACKETS[char]
            is_forward = char in "([{"
            match_pos = self._find_bracket_match(search_pos, char, match_char, is_forward)

            if match_pos >= 0:
                # Highlight both the bracket and its match.
                bracket_bg = QColor(100, 100, 60)
                for bp in [search_pos, match_pos]:
                    sel = QTextEdit.ExtraSelection()
                    sel.format.setBackground(bracket_bg)
                    sel.cursor = self.textCursor()
                    sel.cursor.setPosition(bp)
                    sel.cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor
                    )
                    selections.append(sel)

        return selections

    def _find_bracket_match(self, pos, open_char, close_char, forward):
        """
        Search the document for a matching bracket.

        :param int pos: Position of the bracket to match.
        :param str open_char: The opening bracket character.
        :param str close_char: The closing bracket character.
        :param bool forward: True to search forward, False for backward.
        :return: Position of the matching bracket, or -1 if not found.
        :rtype: int
        """
        doc = self.document()
        depth = 0

        if forward:
            i = pos + 1
            end = doc.characterCount()
            while i < end:
                cursor = QTextCursor(doc)
                cursor.setPosition(i)
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor
                )
                ch = cursor.selectedText()
                if ch == open_char:
                    depth += 1
                elif ch == close_char:
                    if depth == 0:
                        return i
                    depth -= 1
                i += 1
        else:
            i = pos - 1
            while i >= 0:
                cursor = QTextCursor(doc)
                cursor.setPosition(i)
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor
                )
                ch = cursor.selectedText()
                if ch == close_char:
                    depth += 1
                elif ch == open_char:
                    if depth == 0:
                        return i
                    depth -= 1
                i -= 1

        return -1

    def _find_matching_words(self):
        """
        Highlight all occurrences of the word under the cursor.

        :return: List of ExtraSelection items for matching words.
        :rtype: list
        """
        selections = []
        cursor = self.textCursor()

        # Get word under cursor.
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()

        # Skip very short words to avoid noisy highlighting.
        if not word or len(word) < 2:
            return selections

        doc = self.document()
        highlight_color = QColor(55, 55, 45)

        # Find all occurrences of the word in the document.
        search_cursor = QTextCursor(doc)
        while True:
            search_cursor = doc.find(word, search_cursor)
            if search_cursor.isNull():
                break
            # Only match whole words (not substrings).
            found_cursor = QTextCursor(search_cursor)
            found_cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            if found_cursor.selectedText() == word:
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(highlight_color)
                sel.cursor = search_cursor
                selections.append(sel)

        return selections

    # --- Diagnostics (Inline Error/Warning Markers) -------------------------

    def set_diagnostics(self, diagnostics):
        """
        Set the current list of diagnostics and refresh all visual markers.

        Called by ``_run_analysis()`` after the analyzer finishes. Rebuilds
        the per-line severity lookup, repaints gutter dots, and refreshes
        wavy underlines.

        :param list diagnostics: List of diagnostic dicts from the analyzer.
            Each dict has keys: line, col, end_col, severity, message.
        """
        self._diagnostics = diagnostics

        # Build a fast lookup: {line_number: highest_severity}.
        # "error" takes priority over "warning" if both exist on the same line.
        self._diagnostic_lines = {}
        for diag in diagnostics:
            line = diag["line"]
            severity = diag["severity"]
            existing = self._diagnostic_lines.get(line)
            # Only upgrade — never downgrade from error to warning.
            if existing != "error":
                self._diagnostic_lines[line] = severity

        # Repaint the gutter so dots appear/disappear.
        self._line_number_area.update()

        # Rebuild extra selections to include/remove wavy underlines.
        self._on_cursor_position_changed()

    def _build_diagnostic_selections(self):
        """
        Build extra-selection items for wavy underlines on diagnostic lines.

        For each diagnostic, creates a QTextEdit.ExtraSelection with a
        wave underline in the appropriate color (red for errors, yellow
        for warnings). If column info is available, underlines only the
        affected span; otherwise underlines the whole line's text.

        :return: List of ExtraSelection items for diagnostic underlines.
        :rtype: list
        """
        selections = []
        doc = self.document()

        for diag in self._diagnostics:
            line = diag["line"]
            col = diag.get("col", 0)
            end_col = diag.get("end_col")
            severity = diag["severity"]

            # Find the text block for this line (1-based -> 0-based).
            block = doc.findBlockByNumber(line - 1)
            if not block.isValid():
                continue

            block_text = block.text()
            if not block_text.strip():
                # Skip blank lines — nothing visible to underline.
                continue

            sel = QTextEdit.ExtraSelection()

            # Set underline color based on severity.
            if severity == "error":
                underline_color = QColor("#f44747")
            else:
                underline_color = QColor("#cca700")

            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            fmt.setUnderlineColor(underline_color)
            sel.format = fmt

            # Position the cursor to select the diagnostic span.
            cursor = QTextCursor(block)
            if end_col is not None and col < end_col:
                # Column range available — underline just that span.
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.MoveAnchor, col
                )
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor, end_col - col
                )
            else:
                # No column range — underline the entire non-whitespace text.
                leading_spaces = len(block_text) - len(block_text.lstrip())
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.MoveAnchor, leading_spaces
                )
                cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock,
                    QTextCursor.MoveMode.KeepAnchor
                )

            sel.cursor = cursor
            selections.append(sel)

        return selections

    def _run_analysis(self):
        """
        Run code analysis on the current editor content.

        Only analyzes Python files; clears diagnostics for other languages.
        Called by the debounced ``_analysis_timer`` after 500ms of idle time.
        """
        if self._language != "python":
            self.set_diagnostics([])
            return

        try:
            from mca_core.analyzer import analyze_python
        except ImportError:
            # Package root may have fallen off sys.path (Maya does this
            # occasionally).  Re-add it manually — we can't call
            # mca_core.ensure_on_path() because mca_core itself is the
            # module we can't find.  Walk up from this file's directory
            # to find the package root (the dir containing mca_core/).
            import os, sys
            _pkg_root = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            ))
            if _pkg_root not in sys.path:
                sys.path.insert(0, _pkg_root)
            try:
                from mca_core.analyzer import analyze_python
            except ImportError:
                return

        code = self.toPlainText()
        diagnostics = analyze_python(code)
        self.set_diagnostics(diagnostics)

    def event(self, evt):
        """
        Intercept ToolTip events to show diagnostic messages on hover.

        When the mouse hovers over a line that has diagnostics, shows
        a tooltip with all diagnostic messages for that line.

        :param QEvent evt: The event to handle.
        :return: True if the event was handled, False to pass through.
        :rtype: bool
        """
        if evt.type() == QEvent.Type.ToolTip:
            pos = evt.pos()
            cursor = self.cursorForPosition(pos)
            line = cursor.blockNumber() + 1

            # Collect all diagnostic messages for this line.
            msgs = [d["message"] for d in self._diagnostics if d["line"] == line]
            if msgs:
                QToolTip.showText(evt.globalPos(), "\n".join(msgs), self)
            else:
                QToolTip.hideText()
            return True

        return super().event(evt)

    # --- Key Handling --------------------------------------------------------

    def wheelEvent(self, event):
        """
        Handle Ctrl+scroll wheel for font size zoom.

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

    def keyPressEvent(self, event):
        """
        Handle key presses for completions, execution shortcuts, auto-close,
        and indentation.

        Key bindings mirror Charcoal Editor 2:
            - Ctrl+Space: Trigger auto-complete
            - Ctrl+Shift+Enter: Execute full script
            - Ctrl+Enter: Execute selected text
            - Ctrl+Alt+Enter: Execute current line
            - Ctrl+/: Toggle comment
            - Tab: Accept completion (when popup active) or indent
            - Shift+Tab: Unindent

        :param QKeyEvent event: The key press event.
        """
        # --- Completer key forwarding ---
        # When the popup is active, navigation keys (Up/Down/Tab/Enter/Escape)
        # are consumed by the completer instead of the editor.
        if self._completer and self._completer.is_active:
            if self._completer.handle_key_event(event):
                return

        # --- Execute shortcuts (like Charcoal Editor 2) ---
        # Key_Return = main Enter, Key_Enter = numpad Enter.
        # Numpad keys carry KeypadModifier on Windows; strip it for clean
        # modifier comparison but remember it so bare numpad Enter executes.
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        is_numpad = bool(event.modifiers() & Qt.KeyboardModifier.KeypadModifier)
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier

        if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if is_enter:
                self.execute_requested.emit()
                return

        if mods == Qt.KeyboardModifier.ControlModifier:
            if is_enter:
                self.execute_selected_requested.emit()
                return

        if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            if is_enter:
                self.execute_line_requested.emit()
                return

        # --- Numpad Enter (no Ctrl/Shift/Alt): execute selected text or all ---
        if is_numpad and is_enter and mods == Qt.KeyboardModifier.NoModifier:
            self.execute_selected_requested.emit()
            return

        # --- Ctrl+Space: manual auto-complete trigger ---
        if (event.key() == Qt.Key.Key_Space
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.completion_requested.emit(True)
            return

        # --- Toggle comment (Ctrl+/) ---
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Slash:
            self._toggle_comment()
            return

        # --- Tab handling ---
        if event.key() == Qt.Key.Key_Tab:
            if self.textCursor().hasSelection():
                self._indent_selection()
            else:
                # Insert spaces instead of a tab character.
                if self._use_spaces:
                    spaces = self._tab_size - (self.textCursor().columnNumber() % self._tab_size)
                    self.insertPlainText(" " * spaces)
                else:
                    super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Backtab:
            self._unindent_selection()
            return

        # --- Auto-close brackets ---
        # Guard: event.text() is empty for non-printable keys (arrows, etc.)
        # and "" in "([{" is True in Python, which would cause a KeyError.
        if self._auto_close_brackets and event.text() and event.text() in "([{":
            closing = {"(": ")", "[": "]", "{": "}"}[event.text()]

            # Only auto-pair when the next character is "safe" — whitespace,
            # closing bracket, comma, semicolon, colon, or end of line.
            # If an alphanumeric character or other content follows, the user
            # is likely wrapping existing text, so just insert the opening
            # bracket without a closing pair (matches VS Code behavior).
            cursor = self.textCursor()
            should_pair = True
            if not cursor.atEnd():
                peek = QTextCursor(cursor)
                peek.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor
                )
                next_char = peek.selectedText()
                if next_char and next_char not in " \t\r\n)]},:;>":
                    should_pair = False

            super().keyPressEvent(event)

            if should_pair:
                self.insertPlainText(closing)
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Left)
                self.setTextCursor(cursor)

            # Dismiss completer on bracket — not a continuation of typing.
            if self._completer and self._completer.is_active:
                self._completer.dismiss()
            return

        # --- Skip over auto-closed brackets ---
        # If the user types a closing bracket and the character immediately
        # to the right of the cursor is that same bracket (from auto-close),
        # just move the cursor over it instead of inserting a duplicate.
        if self._auto_close_brackets and event.text() and event.text() in ")]}":
            cursor = self.textCursor()
            if not cursor.atEnd():
                peek = QTextCursor(cursor)
                peek.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor
                )
                if peek.selectedText() == event.text():
                    # Skip over the existing closing bracket.
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
                    self.setTextCursor(cursor)
                    # Dismiss completer on close-bracket.
                    if self._completer and self._completer.is_active:
                        self._completer.dismiss()
                    return

        # --- Auto-close quotes ---
        # Guard: same empty-string-in-string check as brackets above.
        if self._auto_close_quotes and event.text() and event.text() in "'\"":
            cursor = self.textCursor()
            # Check if we're closing an existing quote (skip over it instead).
            if not cursor.atEnd():
                next_cursor = QTextCursor(cursor)
                next_cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor
                )
                next_char = next_cursor.selectedText()
                if next_char == event.text():
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
                    self.setTextCursor(cursor)
                    return

                # Only auto-pair when the next character is "safe" — whitespace,
                # closing bracket, comma, semicolon, colon, or end of line.
                # If an alphanumeric character or underscore follows, the user
                # is likely adding quotes around existing text, so just insert
                # the single quote without a closing pair (matches VS Code /
                # PyCharm behavior).
                if next_char and next_char not in " \t\r\n)]},:;>":
                    super().keyPressEvent(event)
                    return

            # Insert the quote and its closing pair.
            super().keyPressEvent(event)
            self.insertPlainText(event.text())
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return

        # --- Enter key with auto-indent (main keyboard only) ---
        # Numpad Enter is handled above as "execute"; only main Enter inserts newlines.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not is_numpad:
            self._handle_newline()
            return

        # Default key handling for everything else.
        super().keyPressEvent(event)

        # --- Post-keystroke: check whether to trigger or update completions ---
        self._check_completion_trigger(event)

    def _check_completion_trigger(self, event):
        """
        After a key is processed, decide whether to trigger, update, or
        dismiss the auto-complete popup.

        Called at the end of keyPressEvent for non-shortcut keys that
        were passed through to the editor.

        :param QKeyEvent event: The key press event that was just processed.
        """
        if not self._completer:
            return

        text = event.text()
        key = event.key()

        # --- If the completer is already showing, update the filter ---
        if self._completer.is_active:
            # Typing letters/digits/underscore: narrow the visible items.
            if text and (text.isalnum() or text == "_"):
                self._completer.update_filter()
                return

            # Backspace: re-filter with shorter prefix.
            if key == Qt.Key.Key_Backspace:
                self._completer.update_filter()
                return

            # Dot in Python: re-trigger (new scope).
            if text == "." and self._language == "python":
                self.completion_requested.emit(False)
                return

            # Any other printable character that isn't an identifier char
            # (e.g. space, parenthesis, operator): dismiss.
            if text and not text.isalnum() and text not in "_.":
                self._completer.dismiss()
                return

            return

        # --- Completer is NOT active: decide whether to auto-trigger ---
        # Skip if no printable text was produced (arrows, modifiers, etc.).
        if not text:
            return

        # Letter or underscore typed: auto-trigger on letters if setting allows.
        if text.isalpha() or text == "_":
            if self._language == "python":
                if self._settings and self._settings.get("py_autocomplete_on_letters"):
                    self.completion_requested.emit(False)
            elif self._language == "mel":
                if self._settings and self._settings.get("mel_autocomplete_on_letters"):
                    self.completion_requested.emit(False)
            return

        # Dot typed in Python: auto-trigger on dot if setting allows.
        if text == "." and self._language == "python":
            if self._settings and self._settings.get("py_autocomplete_on_dot"):
                self.completion_requested.emit(False)
            return

    def _handle_newline(self):
        """
        Handle Enter key with smart indentation.

        Preserves the current line's indentation and adds an extra
        indent level after colons (Python) or opening braces (MEL).
        """
        cursor = self.textCursor()
        block_text = cursor.block().text()

        # Capture current indentation.
        indent = ""
        for ch in block_text:
            if ch in " \t":
                indent += ch
            else:
                break

        # Check if we need to increase indent after a block opener.
        stripped = block_text.rstrip()
        if self._language == "python" and stripped.endswith(":"):
            # Python: increase indent after colon.
            if self._use_spaces:
                indent += " " * self._tab_size
            else:
                indent += "\t"
        elif self._language == "mel" and stripped.endswith("{"):
            # MEL: increase indent after opening brace.
            if self._use_spaces:
                indent += " " * self._tab_size
            else:
                indent += "\t"

        # Insert newline with preserved/increased indent.
        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)

    def _toggle_comment(self):
        """
        Toggle line comment for selected lines.

        Uses '#' for Python and '//' for MEL.
        Determines whether to comment or uncomment based on the first
        selected line.
        """
        cursor = self.textCursor()

        # Choose comment style based on language.
        if self._language == "python":
            comment_str = "# "
        elif self._language == "mel":
            comment_str = "// "
        else:
            comment_str = "# "

        cursor.beginEditBlock()

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        # Determine if we're commenting or uncommenting based on first line.
        first_line = cursor.block().text()
        stripped = first_line.lstrip()
        is_commenting = not stripped.startswith(comment_str.rstrip())

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        # Process each line in the selection.
        while cursor.position() <= end and cursor.position() < self.document().characterCount() - 1:
            line_text = cursor.block().text()

            if is_commenting:
                # Insert comment after the existing indentation.
                indent_len = len(line_text) - len(line_text.lstrip())
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.MoveAnchor, indent_len
                )
                cursor.insertText(comment_str)
                end += len(comment_str)
            else:
                # Remove comment prefix.
                idx = line_text.find(comment_str)
                if idx < 0:
                    # Try without trailing space.
                    idx = line_text.find(comment_str.rstrip())
                    if idx >= 0:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        cursor.movePosition(
                            QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.MoveAnchor, idx
                        )
                        cursor.movePosition(
                            QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.KeepAnchor,
                            len(comment_str.rstrip())
                        )
                        cursor.removeSelectedText()
                        end -= len(comment_str.rstrip())
                else:
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.MoveAnchor, idx
                    )
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor,
                        len(comment_str)
                    )
                    cursor.removeSelectedText()
                    end -= len(comment_str)

            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break

        cursor.endEditBlock()

    def _indent_selection(self):
        """Indent all selected lines by one level."""
        cursor = self.textCursor()
        cursor.beginEditBlock()

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        indent = " " * self._tab_size if self._use_spaces else "\t"

        while cursor.position() <= end:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.insertText(indent)
            end += len(indent)
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break

        cursor.endEditBlock()

    def _unindent_selection(self):
        """Unindent all selected lines by one level (Shift+Tab)."""
        cursor = self.textCursor()
        cursor.beginEditBlock()

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

        while cursor.position() <= end:
            line_text = cursor.block().text()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)

            if self._use_spaces:
                # Remove up to tab_size leading spaces.
                remove = min(self._tab_size, len(line_text) - len(line_text.lstrip(" ")))
                if remove > 0:
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor, remove
                    )
                    cursor.removeSelectedText()
                    end -= remove
            else:
                # Remove a single leading tab.
                if line_text.startswith("\t"):
                    cursor.movePosition(
                        QTextCursor.MoveOperation.Right,
                        QTextCursor.MoveMode.KeepAnchor, 1
                    )
                    cursor.removeSelectedText()
                    end -= 1

            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break

        cursor.endEditBlock()

    # --- Code Outline --------------------------------------------------------

    def get_code_outline(self):
        """
        Parse the current document for an outline of classes, functions,
        and methods (Python) or procs (MEL).

        :return: List of outline items, each a dict with 'type', 'name',
                 'line', and 'indent'.
        :rtype: list
        """
        outline = []
        doc = self.document()

        if self._language == "python":
            class_re = re.compile(r"^(\s*)class\s+(\w+)")
            func_re = re.compile(r"^(\s*)def\s+(\w+)")

            for i in range(doc.blockCount()):
                block = doc.findBlockByNumber(i)
                text = block.text()

                class_match = class_re.match(text)
                if class_match:
                    indent = len(class_match.group(1))
                    outline.append({
                        "type": "class",
                        "name": class_match.group(2),
                        "line": i + 1,
                        "indent": indent,
                    })
                    continue

                func_match = func_re.match(text)
                if func_match:
                    indent = len(func_match.group(1))
                    outline.append({
                        "type": "method" if indent > 0 else "function",
                        "name": func_match.group(2),
                        "line": i + 1,
                        "indent": indent,
                    })

        elif self._language == "mel":
            proc_re = re.compile(r"^\s*(?:global\s+)?proc\s+\w*\s*(\w+)")

            for i in range(doc.blockCount()):
                block = doc.findBlockByNumber(i)
                text = block.text()
                match = proc_re.match(text)
                if match:
                    outline.append({
                        "type": "proc",
                        "name": match.group(1),
                        "line": i + 1,
                        "indent": 0,
                    })

        return outline

    # --- Execution Helpers ---------------------------------------------------

    def get_all_text(self):
        """
        Get all text in the editor.

        :return: Full editor content.
        :rtype: str
        """
        return self.toPlainText()

    def get_selected_text(self):
        """
        Get selected text, or all text if nothing is selected.

        :return: Selected or full text.
        :rtype: str
        """
        cursor = self.textCursor()
        if cursor.hasSelection():
            # Replace paragraph separators with newlines.
            return cursor.selectedText().replace("\u2029", "\n")
        return self.toPlainText()

    def get_current_line_text(self):
        """
        Get the text of the current line (for single-line execution).

        :return: Stripped text of the current line.
        :rtype: str
        """
        cursor = self.textCursor()
        return cursor.block().text().strip()

    def go_to_line(self, line_number):
        """
        Move the cursor to a specific line number and center it.

        :param int line_number: 1-based line number.
        """
        block = self.document().findBlockByNumber(line_number - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()
