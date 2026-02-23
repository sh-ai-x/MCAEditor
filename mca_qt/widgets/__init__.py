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
from .find_replace_bar import FindReplaceBar
from .quick_open import GoToFilePopup, GoToSymbolPopup
from .editor_group import EditorGroup, SplittableTabBar
from .editor_group_container import EditorGroupContainer
from .drop_zone_overlay import DropZoneOverlay, DropZone
from .drag_tab_manager import DragTabManager
