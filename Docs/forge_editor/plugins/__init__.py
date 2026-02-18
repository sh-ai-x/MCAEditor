"""
Forge Editor - Plugin System
Base classes and manager for third-party plugin extensions.

Plugins can:
- Add new DCC adapters (connect to new applications)
- Add new language support (syntax highlighting, completions)
- Add sidebar panels
- Add toolbar buttons and menu items
- Hook into the AI layer
- Add code snippets and templates

Plugin structure:
    my_plugin/
        plugin.json         # Manifest with metadata
        __init__.py         # Entry point
        ...
    
    plugin.json:
    {
        "name": "My Plugin",
        "id": "com.example.myplugin",
        "version": "1.0.0",
        "author": "Your Name",
        "description": "Does something cool",
        "entry_point": "__init__.py",
        "min_forge_version": "0.1.0",
        "plugin_type": "adapter|language|panel|general",
        "permissions": ["execute", "file_access", "network"]
    }
"""

import os
import json
import importlib.util
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class ForgePlugin(ABC):
    """Base class for all Forge Editor plugins."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin display name."""
        pass
    
    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique plugin identifier (reverse domain notation)."""
        pass
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version string."""
        pass
    
    @abstractmethod
    def activate(self, api: 'ForgePluginAPI'):
        """Called when the plugin is loaded. Register everything here."""
        pass
    
    @abstractmethod
    def deactivate(self):
        """Called when the plugin is unloaded. Clean up here."""
        pass


class ForgePluginAPI:
    """
    API exposed to plugins for interacting with Forge Editor.
    This is the sandbox through which plugins extend the editor.
    """
    
    def __init__(self, main_window):
        self._main_window = main_window
    
    def register_adapter(self, name: str, adapter_class):
        """Register a new DCC adapter."""
        self._main_window._adapter_manager.register_adapter(name, adapter_class)
    
    def add_sidebar_panel(self, title: str, widget):
        """Add a custom panel to the sidebar."""
        pass  # TODO: implement dynamic sidebar panel registration
    
    def add_menu_action(self, menu_path: str, label: str, callback):
        """Add a menu item. menu_path like 'Tools/My Plugin'."""
        pass  # TODO: implement dynamic menu registration
    
    def add_toolbar_action(self, label: str, callback, tooltip: str = ""):
        """Add a toolbar button."""
        pass  # TODO: implement dynamic toolbar registration
    
    def get_active_editor(self):
        """Get the currently active code editor."""
        return self._main_window._current_editor()
    
    def get_output_window(self):
        """Get the output window for writing messages."""
        return self._main_window._output
    
    def get_adapter_manager(self):
        """Get the DCC adapter manager."""
        return self._main_window._adapter_manager
    
    def execute_in_dcc(self, code: str, language: str = None):
        """Execute code in the active DCC."""
        return self._main_window._adapter_manager.execute(code, language)
    
    def show_notification(self, message: str, duration_ms: int = 5000):
        """Show a status bar notification."""
        self._main_window.statusBar().showMessage(message, duration_ms)


class PluginManager:
    """
    Discovers, loads, and manages plugins.
    """
    
    def __init__(self, plugin_dirs: List[str] = None):
        self._plugin_dirs = plugin_dirs or []
        self._loaded_plugins: Dict[str, ForgePlugin] = {}
        self._api: Optional[ForgePluginAPI] = None
    
    def set_api(self, api: ForgePluginAPI):
        """Set the plugin API instance."""
        self._api = api
    
    def discover_plugins(self) -> List[Dict[str, Any]]:
        """Scan plugin directories for available plugins."""
        discovered = []
        
        for plugin_dir in self._plugin_dirs:
            if not os.path.isdir(plugin_dir):
                continue
            
            for entry in os.listdir(plugin_dir):
                plugin_path = os.path.join(plugin_dir, entry)
                manifest_path = os.path.join(plugin_path, "plugin.json")
                
                if os.path.isdir(plugin_path) and os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                        manifest["_path"] = plugin_path
                        discovered.append(manifest)
                    except Exception:
                        pass
        
        return discovered
    
    def load_plugin(self, plugin_path: str) -> bool:
        """Load and activate a plugin from its directory."""
        manifest_path = os.path.join(plugin_path, "plugin.json")
        
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            
            entry_point = manifest.get("entry_point", "__init__.py")
            entry_path = os.path.join(plugin_path, entry_point)
            
            # Load the module
            spec = importlib.util.spec_from_file_location(
                manifest["id"], entry_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find the plugin class
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, ForgePlugin) and 
                    attr is not ForgePlugin):
                    plugin_class = attr
                    break
            
            if not plugin_class:
                return False
            
            # Instantiate and activate
            plugin = plugin_class()
            if self._api:
                plugin.activate(self._api)
            
            self._loaded_plugins[manifest["id"]] = plugin
            return True
            
        except Exception as e:
            print(f"Failed to load plugin from {plugin_path}: {e}")
            return False
    
    def unload_plugin(self, plugin_id: str):
        """Deactivate and unload a plugin."""
        plugin = self._loaded_plugins.pop(plugin_id, None)
        if plugin:
            plugin.deactivate()
    
    def get_loaded_plugins(self) -> Dict[str, ForgePlugin]:
        """Get all loaded plugins."""
        return dict(self._loaded_plugins)
