"""
Forge Editor - Settings Management
Handles persistent configuration, preferences, and workspace state.
"""

from PySide6.QtCore import QSettings
from enum import Enum
from typing import Optional


class EditorMode(Enum):
    SIMPLE = "simple"       # Charcoal-style minimal UI
    ADVANCED = "advanced"   # Full IDE with project folders


class ForgeSettings:
    """Centralized settings manager using QSettings for persistence."""
    
    def __init__(self):
        self._settings = QSettings("ForgeTools", "ForgeEditor")
        self._defaults = {
            # General
            "editor_mode": EditorMode.SIMPLE.value,
            "last_workspace": "",
            "recent_files": [],
            "recent_workspaces": [],
            "auto_save_on_execute": True,
            "restore_session": True,
            
            # Appearance
            "theme": "dark",
            "font_family": "JetBrains Mono, Consolas, Courier New",
            "font_size": 12,
            "show_line_numbers": True,
            "show_indent_guides": True,
            "show_whitespace": False,
            "word_wrap": False,
            "minimap_visible": False,
            "show_matching_brackets": True,
            "highlight_current_line": True,
            
            # Tabs and Indentation
            "use_spaces": True,
            "tab_size": 4,
            "auto_indent": True,
            "smart_indent": True,
            
            # Code Editor
            "auto_complete": True,
            "auto_complete_delay_ms": 300,
            "auto_close_brackets": True,
            "auto_close_quotes": True,
            "matching_word_highlight": True,
            
            # Output
            "output_font_size": 11,
            "output_word_wrap": True,
            "output_show_timestamps": False,
            "output_max_lines": 10000,
            
            # DCC Connection
            "dcc_auto_detect": True,
            "dcc_maya_port": 7001,
            "dcc_blender_port": 7002,
            "dcc_unreal_port": 7003,
            "dcc_unity_port": 7004,
            "last_connected_dcc": "",
            
            # AI
            "ai_enabled": False,
            "ai_provider": "none",   # none, byok_claude, byok_openai, byok_local, managed
            "ai_api_key": "",        # Stored securely
            "ai_api_endpoint": "",   # For custom/local endpoints
            "ai_model": "",
            "ai_panel_visible": False,
            "ai_context_include_scene": True,
            "ai_context_include_output": True,
            "ai_auto_complete": False,
            
            # Window State
            "window_geometry": None,
            "window_state": None,
            "splitter_sizes": None,
        }
    
    def get(self, key: str, default=None):
        """Get a setting value with fallback to defaults."""
        if default is None:
            default = self._defaults.get(key)
        value = self._settings.value(key, default)
        # QSettings returns strings for stored values, convert booleans
        if isinstance(default, bool) and isinstance(value, str):
            return value.lower() == "true"
        if isinstance(default, int) and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return value
    
    def set(self, key: str, value):
        """Set a setting value."""
        self._settings.setValue(key, value)
    
    def get_editor_mode(self) -> EditorMode:
        """Get current editor mode."""
        mode_str = self.get("editor_mode", EditorMode.SIMPLE.value)
        try:
            return EditorMode(mode_str)
        except ValueError:
            return EditorMode.SIMPLE
    
    def set_editor_mode(self, mode: EditorMode):
        """Set editor mode."""
        self.set("editor_mode", mode.value)
    
    def get_recent_files(self) -> list:
        """Get list of recently opened files."""
        files = self.get("recent_files", [])
        return files if isinstance(files, list) else []
    
    def add_recent_file(self, filepath: str, max_entries: int = 20):
        """Add a file to the recent files list."""
        recent = self.get_recent_files()
        if filepath in recent:
            recent.remove(filepath)
        recent.insert(0, filepath)
        self.set("recent_files", recent[:max_entries])
    
    def sync(self):
        """Force write settings to disk."""
        self._settings.sync()
