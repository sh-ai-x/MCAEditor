"""
Forge Editor - Output Window
Displays script execution output with syntax-highlighted errors, warnings, and results.
"""

from PySide6.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QFont, QTextCursor
from datetime import datetime


class OutputWindow(QWidget):
    """Output panel for script execution results."""
    
    line_clicked = Signal(str, int)  # filename, line_number (for error navigation)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_timestamps = False
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header bar
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
        
        # Clear button
        clear_btn = QPushButton("✕ Clear")
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
        
        # Text output area
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(10000)
        
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
        
        # Text formats
        self._fmt_normal = QTextCharFormat()
        self._fmt_normal.setForeground(QColor("#cccccc"))
        
        self._fmt_error = QTextCharFormat()
        self._fmt_error.setForeground(QColor("#f44747"))
        
        self._fmt_warning = QTextCharFormat()
        self._fmt_warning.setForeground(QColor("#cca700"))
        
        self._fmt_success = QTextCharFormat()
        self._fmt_success.setForeground(QColor("#4ec9b0"))
        
        self._fmt_info = QTextCharFormat()
        self._fmt_info.setForeground(QColor("#569cd6"))
        
        self._fmt_result = QTextCharFormat()
        self._fmt_result.setForeground(QColor("#dcdcaa"))
        
        self._fmt_timestamp = QTextCharFormat()
        self._fmt_timestamp.setForeground(QColor("#666666"))
    
    def _append_formatted(self, text: str, fmt: QTextCharFormat):
        """Append text with specific formatting."""
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if self._show_timestamps:
            ts = datetime.now().strftime("[%H:%M:%S] ")
            cursor.insertText(ts, self._fmt_timestamp)
        
        cursor.insertText(text + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()
    
    def write_output(self, text: str):
        """Write normal output text."""
        self._append_formatted(text, self._fmt_normal)
    
    def write_result(self, text: str):
        """Write a result/return value."""
        self._append_formatted(text, self._fmt_result)
    
    def write_error(self, text: str):
        """Write error text."""
        self._append_formatted(text, self._fmt_error)
    
    def write_warning(self, text: str):
        """Write warning text."""
        self._append_formatted(text, self._fmt_warning)
    
    def write_success(self, text: str):
        """Write success text."""
        self._append_formatted(text, self._fmt_success)
    
    def write_info(self, text: str):
        """Write informational text."""
        self._append_formatted(text, self._fmt_info)
    
    def write_execution_header(self, source: str, dcc_name: str = ""):
        """Write a separator line before execution output."""
        separator = "─" * 60
        label = f"Executing: {source}"
        if dcc_name:
            label += f" [{dcc_name}]"
        self._append_formatted(separator, self._fmt_info)
        self._append_formatted(label, self._fmt_info)
    
    def clear(self):
        """Clear all output."""
        self._output.clear()
    
    def set_show_timestamps(self, show: bool):
        """Toggle timestamp display."""
        self._show_timestamps = show
