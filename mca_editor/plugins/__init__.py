"""
MCA Editor - Plugin System.

Base classes and manager for third-party plugin extensions.

Plugins can:
    - Add new DCC adapters (connect to new applications)
    - Add new language support (syntax highlighting, completions)
    - Add sidebar panels
    - Add toolbar buttons and menu items
    - Hook into the AI layer
    - Add code snippets and templates

Plugin structure::

    my_plugin/
        plugin.json         # Manifest with metadata
        __init__.py         # Entry point (contains MCAPlugin subclass)
        ...

    plugin.json:
    {
        "name": "My Plugin",
        "id": "com.example.myplugin",
        "version": "1.0.0",
        "author": "Your Name",
        "description": "Does something cool",
        "entry_point": "__init__.py",
        "min_mca_version": "0.1.0",
        "plugin_type": "adapter|language|panel|general",
        "permissions": ["execute", "file_access", "network"]
    }

Dependencies:
    - importlib.util (stdlib) - for dynamic module loading
    - json (stdlib) - for manifest parsing

NOTE: Future tier/licensing hooks would gate plugin loading behind
      Standard+ tier.
"""

import os
import json
import logging
import importlib.util

from abc import ABC, abstractmethod

# Module-level logger for plugin operations.
logger = logging.getLogger(__name__)


# =============================================================================
# Plugin Base Class
# =============================================================================

class MCAPlugin(ABC):
    """
    Abstract base class for all MCA Editor plugins.

    Subclasses must implement name, plugin_id, version, activate,
    and deactivate. The activate method receives an MCAPluginAPI
    instance for interacting with the editor.
    """

    @property
    @abstractmethod
    def name(self):
        """
        Plugin display name.

        :rtype: str
        """
        pass

    @property
    @abstractmethod
    def plugin_id(self):
        """
        Unique plugin identifier (reverse domain notation).

        :rtype: str
        """
        pass

    @property
    @abstractmethod
    def version(self):
        """
        Plugin version string.

        :rtype: str
        """
        pass

    @abstractmethod
    def activate(self, api):
        """
        Called when the plugin is loaded.

        Register adapters, panels, menu items, and toolbar buttons here.

        :param MCAPluginAPI api: The plugin API for editor interaction.
        """
        pass

    @abstractmethod
    def deactivate(self):
        """
        Called when the plugin is unloaded.

        Clean up any resources, remove registrations, etc.
        """
        pass


# =============================================================================
# Plugin API (Sandbox)
# =============================================================================

class MCAPluginAPI:
    """
    API exposed to plugins for interacting with MCA Editor.

    This is the sandbox through which plugins extend the editor.
    All access to editor internals goes through this API to
    maintain encapsulation and prevent unsafe operations.

    :param MCAMainWindow main_window: The main application window.
    """

    def __init__(self, main_window):
        """
        Initialize the plugin API.

        :param MCAMainWindow main_window: The main window instance.
        """
        self._main_window = main_window

    def register_adapter(self, name, adapter_class):
        """
        Register a new DCC adapter.

        :param str name: Unique name for the adapter.
        :param type adapter_class: Class inheriting from DCCAdapter.
        """
        self._main_window._adapter_manager.register_adapter(name, adapter_class)

    def add_sidebar_panel(self, title, widget):
        """
        Add a custom panel to the sidebar.

        :param str title: Display title for the panel.
        :param QWidget widget: The panel widget.
        """
        # TODO: implement dynamic sidebar panel registration
        logger.info("Plugin requested sidebar panel: %s (not yet implemented)", title)

    def add_menu_action(self, menu_path, label, callback):
        """
        Add a menu item.

        :param str menu_path: Menu path (e.g. 'Tools/My Plugin').
        :param str label: Display label for the action.
        :param callable callback: Function to call when activated.
        """
        # TODO: implement dynamic menu registration
        logger.info("Plugin requested menu action: %s/%s (not yet implemented)", menu_path, label)

    def add_toolbar_action(self, label, callback, tooltip=""):
        """
        Add a toolbar button.

        :param str label: Display label for the button.
        :param callable callback: Function to call when clicked.
        :param str tooltip: Tooltip text.
        """
        # TODO: implement dynamic toolbar registration
        logger.info("Plugin requested toolbar action: %s (not yet implemented)", label)

    def get_active_editor(self):
        """
        Get the currently active code editor.

        :return: The active MCACodeEditor, or None.
        :rtype: MCACodeEditor or None
        """
        return self._main_window._current_editor()

    def get_output_window(self):
        """
        Get the output window for writing messages.

        :return: The output window instance.
        :rtype: OutputWindow
        """
        return self._main_window._output

    def get_adapter_manager(self):
        """
        Get the DCC adapter manager.

        :return: The adapter manager instance.
        :rtype: AdapterManager
        """
        return self._main_window._adapter_manager

    def execute_in_dcc(self, code, language=None):
        """
        Execute code in the active DCC application.

        :param str code: Source code to execute.
        :param str language: Target language.
        :return: Output from the DCC.
        :rtype: str
        """
        return self._main_window._adapter_manager.execute(code, language)

    def show_notification(self, message, duration_ms=5000):
        """
        Show a status bar notification.

        :param str message: The notification message.
        :param int duration_ms: How long to display it (milliseconds).
        """
        self._main_window.statusBar().showMessage(message, duration_ms)


# =============================================================================
# Plugin Manager
# =============================================================================

class PluginManager:
    """
    Discovers, loads, and manages plugins.

    Scans designated plugin directories for subdirectories containing
    a ``plugin.json`` manifest, and dynamically loads matching modules.

    :param list plugin_dirs: List of directory paths to scan for plugins.
    """

    def __init__(self, plugin_dirs=None):
        """
        Initialize the plugin manager.

        :param list plugin_dirs: Directories to scan for plugins.
        """
        self._plugin_dirs = plugin_dirs or []
        self._loaded_plugins = {}
        self._api = None

    def set_api(self, api):
        """
        Set the plugin API instance.

        Must be called before loading any plugins.

        :param MCAPluginAPI api: The API to expose to plugins.
        """
        self._api = api

    def discover_plugins(self):
        """
        Scan plugin directories for available plugins.

        Looks for subdirectories containing a ``plugin.json`` manifest
        file. Returns the parsed manifests with their filesystem paths.

        :return: List of manifest dicts (each includes '_path' key).
        :rtype: list
        """
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
                    except Exception as exc:
                        logger.warning("Failed to read plugin manifest: %s (%s)", manifest_path, exc)

        logger.info("Discovered %d plugins", len(discovered))
        return discovered

    def load_plugin(self, plugin_path):
        """
        Load and activate a plugin from its directory.

        Reads the manifest, imports the entry point module, finds the
        MCAPlugin subclass, instantiates it, and calls activate().

        :param str plugin_path: Path to the plugin directory.
        :return: True if the plugin was loaded successfully.
        :rtype: bool
        """
        manifest_path = os.path.join(plugin_path, "plugin.json")

        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            entry_point = manifest.get("entry_point", "__init__.py")
            entry_path = os.path.join(plugin_path, entry_point)

            # Dynamically load the plugin module.
            spec = importlib.util.spec_from_file_location(manifest["id"], entry_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the MCAPlugin subclass in the module.
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, MCAPlugin)
                        and attr is not MCAPlugin):
                    plugin_class = attr
                    break

            if not plugin_class:
                logger.warning("No MCAPlugin subclass found in %s", entry_path)
                return False

            # Instantiate and activate the plugin.
            plugin = plugin_class()
            if self._api:
                plugin.activate(self._api)

            self._loaded_plugins[manifest["id"]] = plugin
            logger.info("Loaded plugin: %s v%s", manifest.get("name"), manifest.get("version"))
            return True

        except Exception as exc:
            logger.error("Failed to load plugin from %s: %s", plugin_path, exc)
            return False

    def unload_plugin(self, plugin_id):
        """
        Deactivate and unload a plugin.

        :param str plugin_id: The plugin identifier to unload.
        """
        plugin = self._loaded_plugins.pop(plugin_id, None)
        if plugin:
            try:
                plugin.deactivate()
                logger.info("Unloaded plugin: %s", plugin_id)
            except Exception as exc:
                logger.error("Error deactivating plugin %s: %s", plugin_id, exc)

    def get_loaded_plugins(self):
        """
        Get all loaded plugins.

        :return: Dictionary mapping plugin ID to plugin instance.
        :rtype: dict
        """
        return dict(self._loaded_plugins)
