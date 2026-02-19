"""
MCA Qt - Widget sub-package.

Provides all reusable UI widgets: code editor, output window,
sidebar panels, AI panel, and settings dialog.
"""

from .code_editor import MCACodeEditor
from .output_window import OutputWindow
from .sidebar import MCASidebar
from .ai_panel import AIPanel
from .settings_dialog import SettingsDialog
from .completer import CodeCompleter, CompletionProvider
