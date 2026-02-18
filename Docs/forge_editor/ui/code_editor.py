"""
Forge Editor - Code Editor Widget
Custom code editor with syntax highlighting, line numbers, auto-complete,
brace matching, and other IDE features. Inspired by Charcoal Editor 2.
"""

import re
from PySide6.QtWidgets import (
    QPlainTextEdit, QWidget, QTextEdit, QCompleter, QToolTip
)
from PySide6.QtCore import (
    Qt, QRect, QSize, Signal, QStringListModel, QTimer, QPoint
)
from PySide6.QtGui import (
    QColor, QPainter, QTextFormat, QFont, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QKeySequence, QShortcut, QPen
)


# =============================================================================
# Syntax Highlighting
# =============================================================================

class PythonHighlighter(QSyntaxHighlighter):
    """Python syntax highlighter matching Charcoal Editor's dark theme style."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        self._build_rules()
    
    def _make_format(self, color: str, bold=False, italic=False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt
    
    def _build_rules(self):
        # Keywords
        keyword_fmt = self._make_format("#569cd6", bold=True)
        keywords = [
            "and", "as", "assert", "async", "await", "break", "class",
            "continue", "def", "del", "elif", "else", "except", "finally",
            "for", "from", "global", "if", "import", "in", "is", "lambda",
            "nonlocal", "not", "or", "pass", "raise", "return", "try",
            "while", "with", "yield"
        ]
        for kw in keywords:
            self._rules.append((re.compile(rf"\b{kw}\b"), keyword_fmt))
        
        # Builtins
        builtin_fmt = self._make_format("#4ec9b0")
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
            self._rules.append((re.compile(rf"\b{b}\b"), builtin_fmt))
        
        # Decorators
        decorator_fmt = self._make_format("#d7ba7d")
        self._rules.append((re.compile(r"@\w+"), decorator_fmt))
        
        # Numbers
        number_fmt = self._make_format("#b5cea8")
        self._rules.append((re.compile(r"\b\d+\.?\d*([eE][+-]?\d+)?\b"), number_fmt))
        self._rules.append((re.compile(r"\b0[xX][0-9a-fA-F]+\b"), number_fmt))
        
        # Function/method definitions
        func_fmt = self._make_format("#dcdcaa")
        self._rules.append((re.compile(r"\bdef\s+(\w+)"), func_fmt))
        
        # Class definitions
        class_fmt = self._make_format("#4ec9b0", bold=True)
        self._rules.append((re.compile(r"\bclass\s+(\w+)"), class_fmt))
        
        # Function calls
        call_fmt = self._make_format("#dcdcaa")
        self._rules.append((re.compile(r"\b(\w+)\s*\("), call_fmt))
        
        # Operators
        operator_fmt = self._make_format("#d4d4d4")
        self._rules.append((re.compile(r"[+\-*/%=<>!&|^~]"), operator_fmt))
        
        # Strings (single-line)
        string_fmt = self._make_format("#ce9178")
        self._rules.append((re.compile(r'f?"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))
        self._rules.append((re.compile(r"f?'[^'\\]*(\\.[^'\\]*)*'"), string_fmt))
        
        # Comments (must be last to override)
        comment_fmt = self._make_format("#6a9955", italic=True)
        self._rules.append((re.compile(r"#[^\n]*"), comment_fmt))
    
    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                # For patterns with groups (def name, class name), highlight group 1
                if match.lastindex and match.lastindex >= 1:
                    start = match.start(1)
                    length = match.end(1) - start
                else:
                    start = match.start()
                    length = match.end() - start
                self.setFormat(start, length, fmt)
        
        # Handle multi-line strings (triple quotes)
        self._highlight_multiline_strings(text)
    
    def _highlight_multiline_strings(self, text):
        string_fmt = self._make_format("#ce9178")
        
        # State: 0 = normal, 1 = in triple double-quote, 2 = in triple single-quote
        state = self.previousBlockState()
        if state == -1:
            state = 0
        
        i = 0
        while i < len(text):
            if state == 0:
                if text[i:i+3] == '"""':
                    state = 1
                    start = i
                    i += 3
                elif text[i:i+3] == "'''":
                    state = 2
                    start = i
                    i += 3
                else:
                    i += 1
            elif state == 1:
                if text[i:i+3] == '"""':
                    self.setFormat(start, i + 3 - start, string_fmt)
                    state = 0
                    i += 3
                else:
                    i += 1
            elif state == 2:
                if text[i:i+3] == "'''":
                    self.setFormat(start, i + 3 - start, string_fmt)
                    state = 0
                    i += 3
                else:
                    i += 1
        
        if state != 0:
            self.setFormat(start, len(text) - start, string_fmt)
        
        self.setCurrentBlockState(state)


class MELHighlighter(QSyntaxHighlighter):
    """MEL (Maya Embedded Language) syntax highlighter."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        self._build_rules()
    
    def _make_format(self, color: str, bold=False, italic=False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt
    
    def _build_rules(self):
        keyword_fmt = self._make_format("#569cd6", bold=True)
        keywords = [
            "if", "else", "for", "while", "do", "in", "break", "continue",
            "return", "switch", "case", "default", "proc", "global", "local",
            "string", "int", "float", "vector", "matrix", "source", "catch",
            "true", "false", "yes", "no", "on", "off"
        ]
        for kw in keywords:
            self._rules.append((re.compile(rf"\b{kw}\b"), keyword_fmt))
        
        # MEL variables
        var_fmt = self._make_format("#9cdcfe")
        self._rules.append((re.compile(r"\$\w+"), var_fmt))
        
        # Numbers
        number_fmt = self._make_format("#b5cea8")
        self._rules.append((re.compile(r"\b\d+\.?\d*\b"), number_fmt))
        
        # Strings
        string_fmt = self._make_format("#ce9178")
        self._rules.append((re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'), string_fmt))
        
        # Proc definitions
        proc_fmt = self._make_format("#dcdcaa")
        self._rules.append((re.compile(r"\bproc\s+\w*\s*(\w+)"), proc_fmt))
        
        # Comments
        comment_fmt = self._make_format("#6a9955", italic=True)
        self._rules.append((re.compile(r"//[^\n]*"), comment_fmt))
    
    def highlightBlock(self, text):
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
    """Line number gutter widget for the code editor."""
    
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor
    
    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)
    
    def paintEvent(self, event):
        self._editor.paint_line_numbers(event)


# =============================================================================
# Code Editor
# =============================================================================

class ForgeCodeEditor(QPlainTextEdit):
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
    """
    
    # Signals
    execute_requested = Signal()          # Execute full script
    execute_selected_requested = Signal()  # Execute selected text
    execute_line_requested = Signal()      # Execute current line
    file_modified = Signal(bool)           # Document modified state changed
    cursor_position_changed_info = Signal(int, int)  # line, column
    
    MATCHING_BRACKETS = {
        "(": ")", ")": "(",
        "[": "]", "]": "[",
        "{": "}", "}": "{",
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Configuration
        self._language = "python"
        self._file_path = None
        self._is_temporary = True
        self._tab_size = 4
        self._use_spaces = True
        self._auto_close_brackets = True
        self._auto_close_quotes = True
        self._show_indent_guides = True
        self._highlight_matching_words = True
        
        # Setup font
        font = QFont("JetBrains Mono, Consolas, Courier New", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self._tab_size)
        
        # Line number area
        self._line_number_area = LineNumberArea(self)
        
        # Syntax highlighter
        self._highlighter = None
        self.set_language("python")
        
        # Matching bracket extra selections
        self._bracket_selections = []
        self._matching_word_selections = []
        
        # Connect signals
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.modificationChanged.connect(self.file_modified.emit)
        
        # Initial setup
        self._update_line_number_area_width(0)
        self._setup_editor_style()
    
    def _setup_editor_style(self):
        """Configure editor appearance."""
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                selection-background-color: #264f78;
                selection-color: #ffffff;
                border: none;
            }
        """)
        # Cursor
        self.setCursorWidth(2)
    
    # ---- Language / Highlighter ----
    
    def set_language(self, language: str):
        """Set the editor language (python, mel, etc.)."""
        self._language = language.lower()
        
        if self._highlighter:
            self._highlighter.setDocument(None)
        
        if self._language == "python":
            self._highlighter = PythonHighlighter(self.document())
        elif self._language == "mel":
            self._highlighter = MELHighlighter(self.document())
        else:
            self._highlighter = None
    
    @property
    def language(self):
        return self._language
    
    @property
    def file_path(self):
        return self._file_path
    
    @file_path.setter
    def file_path(self, path):
        self._file_path = path
        self._is_temporary = path is None
        # Auto-detect language from extension
        if path:
            if path.endswith(".py"):
                self.set_language("python")
            elif path.endswith(".mel"):
                self.set_language("mel")
            elif path.endswith(".cs"):
                self.set_language("csharp")
            elif path.endswith(".lua"):
                self.set_language("lua")
    
    @property
    def is_temporary(self):
        return self._is_temporary
    
    # ---- Line Numbers ----
    
    def line_number_area_width(self):
        digits = max(1, len(str(self.blockCount())))
        space = 8 + self.fontMetrics().horizontalAdvance("9") * (digits + 1) + 12
        return space
    
    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
    
    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(),
                                          self._line_number_area.width(),
                                          rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)
    
    def paint_line_numbers(self, event):
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
            
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1
        
        painter.end()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )
    
    # ---- Cursor Position & Highlights ----
    
    def _on_cursor_position_changed(self):
        # Emit position info
        cursor = self.textCursor()
        self.cursor_position_changed_info.emit(
            cursor.blockNumber() + 1,
            cursor.columnNumber() + 1
        )
        
        # Update highlights
        extra_selections = []
        
        # Current line highlight
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(40, 40, 40))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        
        # Matching brackets
        extra_selections.extend(self._find_matching_bracket())
        
        # Matching words
        if self._highlight_matching_words:
            extra_selections.extend(self._find_matching_words())
        
        self.setExtraSelections(extra_selections)
    
    def _find_matching_bracket(self):
        """Find and highlight matching bracket pair."""
        selections = []
        cursor = self.textCursor()
        text = cursor.block().text()
        pos = cursor.positionInBlock()
        
        char = None
        if pos < len(text) and text[pos] in self.MATCHING_BRACKETS:
            char = text[pos]
            search_pos = cursor.position()
        elif pos > 0 and text[pos-1] in self.MATCHING_BRACKETS:
            char = text[pos-1]
            search_pos = cursor.position() - 1
        
        if char:
            match_char = self.MATCHING_BRACKETS[char]
            is_forward = char in "([{"
            match_pos = self._find_bracket_match(search_pos, char, match_char, is_forward)
            
            if match_pos >= 0:
                bracket_fmt = QColor(100, 100, 60)
                for bp in [search_pos, match_pos]:
                    sel = QTextEdit.ExtraSelection()
                    sel.format.setBackground(bracket_fmt)
                    sel.cursor = self.textCursor()
                    sel.cursor.setPosition(bp)
                    sel.cursor.movePosition(QTextCursor.MoveOperation.Right,
                                           QTextCursor.MoveMode.KeepAnchor)
                    selections.append(sel)
        
        return selections
    
    def _find_bracket_match(self, pos, open_char, close_char, forward):
        """Search for matching bracket in the document."""
        doc = self.document()
        depth = 0
        
        if forward:
            i = pos + 1
            end = doc.characterCount()
            while i < end:
                cursor = QTextCursor(doc)
                cursor.setPosition(i)
                cursor.movePosition(QTextCursor.MoveOperation.Right,
                                   QTextCursor.MoveMode.KeepAnchor)
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
                cursor.movePosition(QTextCursor.MoveOperation.Right,
                                   QTextCursor.MoveMode.KeepAnchor)
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
        """Highlight all occurrences of the selected word."""
        selections = []
        cursor = self.textCursor()
        
        # Get word under cursor
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()
        
        if not word or len(word) < 2:
            return selections
        
        # Don't highlight if it's a common single word
        doc = self.document()
        highlight_color = QColor(55, 55, 45)
        
        # Find all occurrences
        search_cursor = QTextCursor(doc)
        while True:
            search_cursor = doc.find(word, search_cursor)
            if search_cursor.isNull():
                break
            # Only match whole words
            found_cursor = QTextCursor(search_cursor)
            found_cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            if found_cursor.selectedText() == word:
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(highlight_color)
                sel.cursor = search_cursor
                selections.append(sel)
        
        return selections
    
    # ---- Key Handling ----
    
    def keyPressEvent(self, event):
        # Execute shortcuts (like Charcoal Editor 2)
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Return:
                self.execute_requested.emit()
                return
        
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Return:
                self.execute_selected_requested.emit()
                return
        
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            if event.key() == Qt.Key.Key_Return:
                self.execute_line_requested.emit()
                return
        
        # Toggle comment (Ctrl+/)
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Slash:
            self._toggle_comment()
            return
        
        # Tab handling
        if event.key() == Qt.Key.Key_Tab:
            if self.textCursor().hasSelection():
                self._indent_selection()
            else:
                if self._use_spaces:
                    spaces = self._tab_size - (self.textCursor().columnNumber() % self._tab_size)
                    self.insertPlainText(" " * spaces)
                else:
                    super().keyPressEvent(event)
            return
        
        if event.key() == Qt.Key.Key_Backtab:
            self._unindent_selection()
            return
        
        # Auto-close brackets
        if self._auto_close_brackets and event.text() in "([{":
            closing = {"(": ")", "[": "]", "{": "}"}[event.text()]
            super().keyPressEvent(event)
            self.insertPlainText(closing)
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return
        
        # Auto-close quotes
        if self._auto_close_quotes and event.text() in "'\"":
            cursor = self.textCursor()
            # Check if we're closing an existing quote
            if not cursor.atEnd():
                next_cursor = QTextCursor(cursor)
                next_cursor.movePosition(QTextCursor.MoveOperation.Right,
                                        QTextCursor.MoveMode.KeepAnchor)
                if next_cursor.selectedText() == event.text():
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
                    self.setTextCursor(cursor)
                    return
            super().keyPressEvent(event)
            self.insertPlainText(event.text())
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return
        
        # Enter key with auto-indent
        if event.key() == Qt.Key.Key_Return:
            self._handle_newline()
            return
        
        # Default handling
        super().keyPressEvent(event)
    
    def _handle_newline(self):
        """Handle Enter key with smart indentation."""
        cursor = self.textCursor()
        block_text = cursor.block().text()
        
        # Get current indentation
        indent = ""
        for ch in block_text:
            if ch in " \t":
                indent += ch
            else:
                break
        
        # Check if we need to increase indent (colon at end for Python)
        stripped = block_text.rstrip()
        if self._language == "python" and stripped.endswith(":"):
            if self._use_spaces:
                indent += " " * self._tab_size
            else:
                indent += "\t"
        elif self._language == "mel" and stripped.endswith("{"):
            if self._use_spaces:
                indent += " " * self._tab_size
            else:
                indent += "\t"
        
        # Insert newline with indent
        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)
    
    def _toggle_comment(self):
        """Toggle line comment for selected lines."""
        cursor = self.textCursor()
        
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
        
        # Determine if we're commenting or uncommenting
        first_line = cursor.block().text()
        stripped = first_line.lstrip()
        is_commenting = not stripped.startswith(comment_str.rstrip())
        
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        
        while cursor.position() <= end and cursor.position() < self.document().characterCount() - 1:
            line_text = cursor.block().text()
            
            if is_commenting:
                # Find the indentation and insert comment after it
                indent_len = len(line_text) - len(line_text.lstrip())
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.movePosition(QTextCursor.MoveOperation.Right,
                                   QTextCursor.MoveMode.MoveAnchor, indent_len)
                cursor.insertText(comment_str)
                end += len(comment_str)
            else:
                # Remove comment
                idx = line_text.find(comment_str)
                if idx < 0:
                    idx = line_text.find(comment_str.rstrip())
                    if idx >= 0:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        cursor.movePosition(QTextCursor.MoveOperation.Right,
                                           QTextCursor.MoveMode.MoveAnchor, idx)
                        cursor.movePosition(QTextCursor.MoveOperation.Right,
                                           QTextCursor.MoveMode.KeepAnchor,
                                           len(comment_str.rstrip()))
                        cursor.removeSelectedText()
                        end -= len(comment_str.rstrip())
                else:
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.Right,
                                       QTextCursor.MoveMode.MoveAnchor, idx)
                    cursor.movePosition(QTextCursor.MoveOperation.Right,
                                       QTextCursor.MoveMode.KeepAnchor,
                                       len(comment_str))
                    cursor.removeSelectedText()
                    end -= len(comment_str)
            
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        
        cursor.endEditBlock()
    
    def _indent_selection(self):
        """Indent selected lines."""
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
        """Unindent selected lines (Shift+Tab)."""
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
                remove = min(self._tab_size, len(line_text) - len(line_text.lstrip(" ")))
                if remove > 0:
                    cursor.movePosition(QTextCursor.MoveOperation.Right,
                                       QTextCursor.MoveMode.KeepAnchor, remove)
                    cursor.removeSelectedText()
                    end -= remove
            else:
                if line_text.startswith("\t"):
                    cursor.movePosition(QTextCursor.MoveOperation.Right,
                                       QTextCursor.MoveMode.KeepAnchor, 1)
                    cursor.removeSelectedText()
                    end -= 1
            
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        
        cursor.endEditBlock()
    
    # ---- Code Outline ----
    
    def get_code_outline(self):
        """Parse current document for outline (classes, functions, methods)."""
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
    
    # ---- Execution Helpers ----
    
    def get_all_text(self):
        """Get all text in the editor."""
        return self.toPlainText()
    
    def get_selected_text(self):
        """Get selected text, or all text if nothing selected."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace("\u2029", "\n")
        return self.toPlainText()
    
    def get_current_line_text(self):
        """Get text of the current line (for single-line execution)."""
        cursor = self.textCursor()
        return cursor.block().text().strip()
    
    def go_to_line(self, line_number: int):
        """Move cursor to a specific line number."""
        block = self.document().findBlockByNumber(line_number - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self.setTextCursor(cursor)
            self.centerCursor()
