"""
MCA Core - Plugin System.

Base classes and manager for third-party plugin extensions.

Plugins can:
    - Register right-panel tabs (QWidget panels)
    - Add menu items under the Plugins menu
    - Access the editor via the MCAPluginAPI (wraps EditorAPI)
    - Show status bar notifications

Plugin structure::

    my_plugin/
        plugin.json         # Manifest with metadata
        __init__.py         # Entry point (contains MCAPlugin subclass)
        ...

    plugin.json:
    {
        "id": "com.example.my-plugin",
        "name": "My Plugin",
        "version": "1.0.0",
        "author": "Developer Name",
        "description": "What this plugin does",
        "entry_point": "__init__.py",
        "min_editor_version": "0.1.0"
    }

Dependencies:
    - importlib.util (stdlib) - for dynamic module loading
    - json (stdlib) - for manifest parsing
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

    Subclasses set class-level attributes for metadata and implement
    ``activate()`` and ``deactivate()``.  The ``activate()`` method
    receives an ``MCAPluginAPI`` instance for interacting with the editor.

    Example::

        class MyPlugin(MCAPlugin):
            PLUGIN_ID = "com.example.my-plugin"
            PLUGIN_NAME = "My Plugin"
            PLUGIN_VERSION = "1.0.0"
            PLUGIN_AUTHOR = "Developer"
            PLUGIN_DESCRIPTION = "Does something cool"

            def activate(self, api):
                api.add_panel("my-panel", "My Panel", MyWidget())

            def deactivate(self):
                pass
    """

    # --- Class-level metadata (override in subclasses) ---
    PLUGIN_ID = ""           # Unique ID, e.g. "com.mechart.ai-chat"
    PLUGIN_NAME = ""         # Human-readable display name
    PLUGIN_VERSION = ""      # Semantic version string
    PLUGIN_AUTHOR = ""       # Author name
    PLUGIN_DESCRIPTION = ""  # Short description

    @abstractmethod
    def activate(self, api):
        """
        Called when the plugin is loaded and activated.

        Register panels, menu items, and other extensions here.

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
# Plugin API (Sandbox wrapping EditorAPI)
# =============================================================================

class MCAPluginAPI:
    """
    API exposed to plugins for interacting with MCA Editor.

    Wraps the ``EditorAPI`` singleton and adds plugin-specific methods
    for registering panels, menu items, and notifications.  All editor
    access goes through this API to maintain encapsulation.

    :param EditorAPI editor_api: The editor API singleton.
    """

    def __init__(self, editor_api):
        """
        Initialize the plugin API.

        :param EditorAPI editor_api: The editor API singleton.
        """
        self._api = editor_api

        # Set by editor_panel after construction so plugins can register
        # panels and menu actions.  None until the panel wires itself in.
        self._panel_host = None

        # Track registered panels and menu actions for cleanup.
        self._panels = []        # list of panel_id strings
        self._menu_actions = []  # list of QAction references

    # --- Plugin-Specific Methods (NOT on EditorAPI) --------------------------

    def add_panel(self, panel_id, title, widget, icon=None, location="right"):
        """
        Register a QWidget as a panel tab in the editor.

        The widget is added to the right-side QStackedWidget and a
        corresponding tool stripe button is created.

        :param str panel_id: Unique identifier for this panel.
        :param str title: Display title for the panel tab / tooltip.
        :param QWidget widget: The panel widget to show.
        :param QIcon icon: Optional icon for the stripe button.
        :param str location: Panel location — currently only "right".
        """
        if self._panel_host is None:
            logger.warning("Cannot add panel '%s' — panel host not set", panel_id)
            return

        # Delegate to the editor panel's registration method.
        self._panel_host._register_plugin_panel(panel_id, title, widget, icon, location)
        self._panels.append(panel_id)
        logger.info("Plugin registered panel: %s (%s)", panel_id, title)

    def remove_panel(self, panel_id):
        """
        Remove a previously registered panel.

        :param str panel_id: The panel identifier to remove.
        """
        if self._panel_host is None:
            logger.warning("Cannot remove panel '%s' — panel host not set", panel_id)
            return

        self._panel_host._unregister_plugin_panel(panel_id)
        if panel_id in self._panels:
            self._panels.remove(panel_id)
        logger.info("Plugin removed panel: %s", panel_id)

    def add_menu_action(self, menu_path, label, callback, shortcut=None):
        """
        Add an item to the Plugins menu.

        :param str menu_path: Submenu path (e.g. "Hello World" creates
            Plugins > Hello World submenu).  Use None or "" for top-level.
        :param str label: Display label for the action.
        :param callable callback: Function to call when activated.
        :param str shortcut: Optional keyboard shortcut string.
        :return: The created QAction, or None on failure.
        :rtype: QAction or None
        """
        if self._panel_host is None:
            logger.warning("Cannot add menu action '%s' — panel host not set", label)
            return None

        action = self._panel_host._register_plugin_menu_action(
            menu_path, label, callback, shortcut
        )
        if action is not None:
            self._menu_actions.append(action)
        return action

    def show_notification(self, message, level="info", duration=5000):
        """
        Show a status bar notification.

        Also writes the message to the output panel at the given level.

        :param str message: The notification message.
        :param str level: One of 'info', 'warning', 'error', 'success'.
        :param int duration: How long to display in status bar (ms).
        """
        # Write to the output panel for persistence.
        if self._api is not None:
            self._api.write_output(message, level)

    # --- Delegated EditorAPI Methods -----------------------------------------
    # Each method below is a 1:1 passthrough to the underlying EditorAPI.
    # If EditorAPI gains new methods, add a passthrough here.

    # -- File Operations --

    def open_file(self, filepath):
        """
        Open a file in the editor.

        :param str filepath: Absolute path to the file.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.open_file(filepath)

    def save_file(self):
        """
        Save the currently active file.

        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.save_file()

    def save_all(self):
        """
        Save all modified file-backed tabs.

        :return: List of result dicts per file.
        :rtype: list
        """
        return self._api.save_all()

    def close_tab(self):
        """
        Close the currently active tab.

        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.close_tab()

    def list_open_files(self):
        """
        List all open tabs across editor groups.

        :return: List of dicts with name, path, language, modified.
        :rtype: list
        """
        return self._api.list_open_files()

    def get_active_file_path(self):
        """
        Get the file path of the active editor tab.

        :return: Absolute file path, or None.
        :rtype: str or None
        """
        return self._api.get_active_file_path()

    def read_disk_file(self, filepath):
        """
        Read a file directly from disk (bypasses editor buffers).

        :param str filepath: Absolute path to the file.
        :return: ApiResult dict with file content.
        :rtype: dict
        """
        return self._api.read_disk_file(filepath)

    def write_disk_file(self, filepath, content):
        """
        Write content directly to disk.

        :param str filepath: Absolute path to the file.
        :param str content: The content to write.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.write_disk_file(filepath, content)

    # -- Editor Content --

    def get_text(self):
        """
        Get the full text content of the active editor.

        :return: Editor content, or None.
        :rtype: str or None
        """
        return self._api.get_text()

    def set_text(self, text):
        """
        Replace the entire content of the active editor.

        :param str text: The new content.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.set_text(text)

    def get_selected_text(self):
        """
        Get the currently selected text.

        :return: Selected text, or None.
        :rtype: str or None
        """
        return self._api.get_selected_text()

    def insert_text(self, text, line=None, col=None):
        """
        Insert text at a specific position or at the cursor.

        :param str text: The text to insert.
        :param int line: 1-based line number (optional).
        :param int col: 1-based column number (optional).
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.insert_text(text, line=line, col=col)

    def replace_range(self, start_line, start_col, end_line, end_col, text):
        """
        Replace a range of text in the active editor.

        :param int start_line: 1-based start line.
        :param int start_col: 1-based start column.
        :param int end_line: 1-based end line.
        :param int end_col: 1-based end column.
        :param str text: Replacement text.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.replace_range(start_line, start_col, end_line, end_col, text)

    def get_cursor_position(self):
        """
        Get the current cursor position.

        :return: Dict with line and col (1-based), or None.
        :rtype: dict or None
        """
        return self._api.get_cursor_position()

    def get_language(self):
        """
        Get the language of the active editor.

        :return: Language string, or None.
        :rtype: str or None
        """
        return self._api.get_language()

    # -- Navigation --

    def navigate_to(self, filepath, line=1):
        """
        Open a file and jump to a specific line.

        :param str filepath: Absolute path to the file.
        :param int line: 1-based line number.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.navigate_to(filepath, line=line)

    def go_to_line(self, line):
        """
        Jump to a line in the active editor.

        :param int line: 1-based line number.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.go_to_line(line)

    # -- Output Panel --

    def write_output(self, text, level="info"):
        """
        Write a message to the output panel.

        :param str text: The message text.
        :param str level: One of 'output', 'info', 'warning', 'error', 'success'.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.write_output(text, level=level)

    def get_output_text(self, max_lines=100):
        """
        Get recent output panel text.

        :param int max_lines: Maximum number of lines to return.
        :return: Output text.
        :rtype: str
        """
        return self._api.get_output_text(max_lines=max_lines)

    def clear_output(self):
        """
        Clear the output panel.

        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.clear_output()

    # -- Project --

    def open_project(self, path):
        """
        Open a folder as a project.

        :param str path: Absolute path to the project root.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.open_project(path)

    def close_project(self):
        """
        Close the active project.

        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.close_project()

    def get_project(self):
        """
        Get information about the active project.

        :return: Project info dict, or None.
        :rtype: dict or None
        """
        return self._api.get_project()

    # -- Execution --

    def execute_in_dcc(self, code, language="python"):
        """
        Execute code in the connected DCC application.

        :param str code: Source code to execute.
        :param str language: 'python' or 'mel'.
        :return: Dict with success, output, error.
        :rtype: dict
        """
        return self._api.execute_in_dcc(code, language=language)

    def execute_locally(self, code):
        """
        Execute Python code locally with stdout capture.

        :param str code: Python source code to execute.
        :return: Dict with success, output, error.
        :rtype: dict
        """
        return self._api.execute_locally(code)

    # -- Settings --

    def get_setting(self, key, default=None):
        """
        Get a setting value.

        :param str key: The setting key.
        :param default: Default value if key is not set.
        :return: The setting value.
        """
        return self._api.get_setting(key, default=default)

    def set_setting(self, key, value):
        """
        Set a setting value.

        :param str key: The setting key.
        :param value: The value to set.
        :return: ApiResult dict.
        :rtype: dict
        """
        return self._api.set_setting(key, value)

    # -- State --

    def get_state(self):
        """
        Get a comprehensive snapshot of the editor's current state.

        :return: State dict.
        :rtype: dict
        """
        return self._api.get_state()


# =============================================================================
# Plugin Manager
# =============================================================================

class PluginManager:
    """
    Discovers, loads, and manages plugins.

    Scans bundled and user plugin directories for subdirectories
    containing a ``plugin.json`` manifest, and dynamically loads
    matching modules.

    Bundled plugins live in ``mca_core/plugins/`` (subpackages).
    User plugins live in ``~/Documents/mca_preferences/plugins/``.

    Disabled plugins are tracked via the ``disabled_plugins`` setting
    (a list of plugin IDs).
    """

    def __init__(self):
        """Initialize the plugin manager with empty state."""
        self._loaded_plugins = {}   # plugin_id -> MCAPlugin instance
        self._manifests = {}        # plugin_id -> manifest dict
        self._api = None            # MCAPluginAPI instance

    def load_all(self, api):
        """
        Discover and load all plugins (bundled first, then user plugins).

        Skips plugins whose ID is in the ``disabled_plugins`` setting.

        :param MCAPluginAPI api: The plugin API to pass to each plugin.
        """
        self._api = api

        # Build the list of plugin directories.
        bundled_dir = os.path.dirname(__file__)
        user_dir = self._get_user_plugin_dir()

        # Discover all available plugins from both directories.
        bundled_plugins = self._discover_plugins(bundled_dir, bundled=True)
        user_plugins = self._discover_plugins(user_dir, bundled=False)

        # Get the disabled plugins list from settings.
        disabled = self._get_disabled_list()

        # Load bundled plugins first, then user plugins.
        for manifest in bundled_plugins + user_plugins:
            plugin_id = manifest.get("id", "")
            if not plugin_id:
                logger.warning("Plugin manifest missing 'id' field: %s", manifest.get("_path"))
                continue

            # Skip disabled plugins.
            if plugin_id in disabled:
                logger.info("Skipping disabled plugin: %s", plugin_id)
                self._manifests[plugin_id] = manifest
                continue

            self._load_plugin(manifest)

    def unload_all(self):
        """Deactivate all loaded plugins in reverse load order."""
        # Reverse so plugins loaded last are unloaded first.
        plugin_ids = list(reversed(self._loaded_plugins.keys()))
        for plugin_id in plugin_ids:
            self._unload_plugin(plugin_id)

    def list_plugins(self):
        """
        Return information about all discovered plugins.

        :return: List of dicts with id, name, version, author,
            description, active, bundled.
        :rtype: list
        """
        result = []
        for plugin_id, manifest in self._manifests.items():
            result.append({
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "version": manifest.get("version", ""),
                "author": manifest.get("author", ""),
                "description": manifest.get("description", ""),
                "active": plugin_id in self._loaded_plugins,
                "bundled": manifest.get("_bundled", False),
            })
        return result

    def enable_plugin(self, plugin_id):
        """
        Enable a disabled plugin and activate it.

        Removes the plugin ID from the disabled_plugins setting
        and loads the plugin if it has a known manifest.

        :param str plugin_id: The plugin ID to enable.
        :return: True if the plugin was successfully enabled and loaded.
        :rtype: bool
        """
        # Remove from disabled list.
        disabled = self._get_disabled_list()
        if plugin_id in disabled:
            disabled.remove(plugin_id)
            self._set_disabled_list(disabled)

        # Load the plugin if it's known but not yet loaded.
        manifest = self._manifests.get(plugin_id)
        if manifest and plugin_id not in self._loaded_plugins:
            return self._load_plugin(manifest)
        return False

    def disable_plugin(self, plugin_id):
        """
        Disable an active plugin and deactivate it.

        Adds the plugin ID to the disabled_plugins setting and
        unloads the plugin if it's currently active.

        :param str plugin_id: The plugin ID to disable.
        """
        # Add to disabled list.
        disabled = self._get_disabled_list()
        if plugin_id not in disabled:
            disabled.append(plugin_id)
            self._set_disabled_list(disabled)

        # Unload the plugin if it's currently loaded.
        if plugin_id in self._loaded_plugins:
            self._unload_plugin(plugin_id)

    # --- Internal Methods ----------------------------------------------------

    def _discover_plugins(self, plugin_dir, bundled=False):
        """
        Scan a directory for plugin subdirectories with plugin.json manifests.

        :param str plugin_dir: Directory to scan.
        :param bool bundled: Whether these are bundled (built-in) plugins.
        :return: List of manifest dicts (each includes _path and _bundled keys).
        :rtype: list
        """
        discovered = []

        if not plugin_dir or not os.path.isdir(plugin_dir):
            return discovered

        for entry in os.listdir(plugin_dir):
            plugin_path = os.path.join(plugin_dir, entry)
            manifest_path = os.path.join(plugin_path, "plugin.json")

            # Skip non-directories and the __pycache__ folder.
            if not os.path.isdir(plugin_path) or entry == "__pycache__":
                continue

            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    manifest["_path"] = plugin_path
                    manifest["_bundled"] = bundled
                    discovered.append(manifest)
                    # Also store in the manifests dict for later lookup.
                    if manifest.get("id"):
                        self._manifests[manifest["id"]] = manifest
                except Exception as exc:
                    logger.warning("Failed to read plugin manifest: %s (%s)", manifest_path, exc)

        logger.info("Discovered %d %s plugins in %s",
                     len(discovered), "bundled" if bundled else "user", plugin_dir)
        return discovered

    def _load_plugin(self, manifest):
        """
        Load and activate a single plugin from its manifest.

        :param dict manifest: The plugin manifest (must include _path).
        :return: True if the plugin was loaded successfully.
        :rtype: bool
        """
        plugin_id = manifest.get("id", "unknown")
        plugin_path = manifest.get("_path", "")
        entry_point = manifest.get("entry_point", "__init__.py")
        entry_path = os.path.join(plugin_path, entry_point)

        # Handle compiled entry points (.pyc or .pyd).
        if not os.path.exists(entry_path):
            # Try compiled variants.
            base = os.path.splitext(entry_point)[0]
            for ext in (".pyc", ".pyd"):
                alt_path = os.path.join(plugin_path, base + ext)
                if os.path.exists(alt_path):
                    entry_path = alt_path
                    break

        if not os.path.exists(entry_path):
            logger.warning("Plugin entry point not found: %s", entry_path)
            return False

        try:
            # Dynamically load the plugin module.
            spec = importlib.util.spec_from_file_location(plugin_id, entry_path)
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

            self._loaded_plugins[plugin_id] = plugin
            self._manifests[plugin_id] = manifest
            logger.info("Loaded plugin: %s v%s", manifest.get("name"), manifest.get("version"))
            return True

        except Exception as exc:
            logger.error("Failed to load plugin '%s': %s", plugin_id, exc, exc_info=True)
            return False

    def _unload_plugin(self, plugin_id):
        """
        Deactivate and unload a single plugin.

        :param str plugin_id: The plugin identifier to unload.
        """
        plugin = self._loaded_plugins.pop(plugin_id, None)
        if plugin:
            try:
                plugin.deactivate()
                logger.info("Unloaded plugin: %s", plugin_id)
            except Exception as exc:
                logger.error("Error deactivating plugin %s: %s", plugin_id, exc)

    def _get_user_plugin_dir(self):
        """
        Get the user plugin directory path.

        Creates the directory if it doesn't exist.

        :return: Absolute path to the user plugins directory.
        :rtype: str
        """
        # User plugins live alongside other MCA preferences.
        prefs_dir = os.path.join(os.path.expanduser("~"), "Documents", "mca_preferences")
        user_dir = os.path.join(prefs_dir, "plugins")

        if not os.path.isdir(user_dir):
            try:
                os.makedirs(user_dir, exist_ok=True)
                logger.info("Created user plugins directory: %s", user_dir)
            except Exception as exc:
                logger.warning("Failed to create user plugins dir: %s", exc)

        return user_dir

    def _get_disabled_list(self):
        """
        Get the list of disabled plugin IDs from settings.

        :return: List of disabled plugin ID strings.
        :rtype: list
        """
        if self._api is None:
            return []
        disabled = self._api.get_setting("disabled_plugins", [])
        # QSettings may return a string instead of a list for single items.
        if isinstance(disabled, str):
            return [disabled] if disabled else []
        return list(disabled) if disabled else []

    def _set_disabled_list(self, disabled):
        """
        Save the list of disabled plugin IDs to settings.

        :param list disabled: List of disabled plugin ID strings.
        """
        if self._api is not None:
            self._api.set_setting("disabled_plugins", disabled)
