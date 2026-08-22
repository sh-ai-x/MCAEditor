"""
MCA Core - Settings Management.

Handles persistent configuration, preferences, and workspace state.
Supports pluggable backends:
    - QSettings (default when Qt is available — Windows registry, macOS plist, Linux ini)
    - Dictionary-backed fallback (for environments without Qt)

Dependencies:
    - PySide6 or PySide2 (optional — for QSettings backend)
"""

import logging

from enum import Enum

# Module-level logger for settings operations.
logger = logging.getLogger(__name__)


# --- Editor Mode Enum (DEPRECATED) ------------------------------------------
# Kept for import compatibility during migration. The Simple/Advanced mode
# toggle has been removed — the editor always starts with sidebar visible
# and users toggle it via the left tool stripe button.

class EditorMode(Enum):
    """DEPRECATED — retained for import compatibility only."""
    SIMPLE = "simple"
    ADVANCED = "advanced"


# --- Settings Manager -------------------------------------------------------

class MCASettings:
    """
    Centralized settings manager with pluggable persistence backend.

    Wraps a backend (QSettings or dict) to provide typed access with
    sensible defaults. All editor preferences, DCC ports, AI
    configuration, and window state are managed through this class.

    :param str org_name: Organization name for QSettings grouping.
    :param str app_name: Application name for QSettings grouping.
    :param backend: Optional pre-created backend. If None, attempts
        to create a QSettings backend, falling back to a dict backend.
    """

    # Default values for every known setting key.
    _DEFAULTS = {
        # --- General (Main Window) ---
        "last_workspace": "",              # Reserved for future use.
        "recent_files": [],
        "recent_workspaces": [],          # Reserved for future use.
        "workspace_folders": [],          # Active workspace folders.
        "recent_projects": [],            # MRU list of project root paths.
        "last_project_path": "",          # Last opened project root for auto-reopen.
        "auto_save_on_execute": True,        # Save all files before executing.
        "save_all_on_exit": True,            # Save all open files when closing.
        "check_modified_files": True,        # Warn if files changed on disk.
        "override_script_editor": True,      # Replace Maya's built-in Script Editor button.
        "always_show_editor_output": True,   # Force editor+output visible on startup.
        "confirm_close_buffer": True,        # Ask before closing an internal buffer.
        "confirm_unsaved_on_exit": True,     # Show unsaved-files dialog on exit.
        "restore_session": True,

        # --- Autosave / Crash Recovery ---
        # Recovery snapshots are shadow copies of modified tabs kept in
        # mca_preferences/<dcc>/recovery/.  They never touch the user's real
        # file, so they are safe to leave on by default; on the next launch a
        # snapshot that differs from its file is restored into the tab as
        # unsaved work rather than being silently discarded.
        "autosave_enabled": True,            # Write crash-recovery snapshots.
        "autosave_interval_secs": 15,        # Seconds between autosave passes.
        # Opt-in: also write modified tabs straight to their real file on the
        # same timer.  Off by default because it silently overwrites source
        # files and re-triggers module auto-reload.
        "autosave_to_file": False,

        # --- General (Tab Bar) ---
        "show_tab_bar": True,                # Display the tab bar above the editor.
        "show_close_button_on_tab": True,    # Show per-tab close buttons.
        "show_mini_toolbar": False,          # Show compact toolbar in tab bar area.
        "mouse_wheel_changes_tab": False,    # Scroll wheel cycles tabs.
        "lock_tabs": False,                  # Prevent tab reordering.

        # --- Appearance ---
        "theme": "dark",
        "font_family": "Consolas",
        "font_size": 12,
        "show_line_numbers": True,
        "show_indent_guides": True,
        "show_whitespace": False,
        "word_wrap": False,
        "minimap_visible": False,
        "show_matching_brackets": True,
        "highlight_current_line": True,
        "show_fixed_width_only": True,       # Only show monospaced fonts in picker.

        # --- Fonts and Colors (per-item theming) ---
        "output_font_family": "Consolas",    # Separate font for the output window.
        "output_font_size_setting": 9,       # Separate font size for the output window.

        # --- Tabs and Indentation ---
        "use_spaces": True,
        "tab_size": 4,
        "auto_indent": True,
        "smart_indent": True,

        # --- Code Editor ---
        "auto_complete": True,
        "auto_complete_delay_ms": 150,
        "auto_close_brackets": True,
        "auto_close_quotes": True,
        "matching_word_highlight": True,
        "backspace_to_tab_stop": True,       # Backspace removes to previous tab stop.
        "ctrl_wheel_font_size": True,        # Ctrl+Mouse Wheel changes font size.
        "limit_match_highlight": False,      # Limit matching selection highlight to words.

        # --- Output ---
        "output_font_size": 11,
        "output_word_wrap": False,
        "output_show_timestamps": False,
        "output_max_lines": 10000,
        "output_buffer_size": 3000,          # Max number of output blocks to keep.
        "output_ctrl_wheel_font": True,      # Ctrl+Mouse Wheel changes output font.
        "output_limit_match_highlight": False,  # Limit matching selection to words in output.
        "output_double_click_dollar": True,  # Double-click includes leading $ (MEL vars).
        "output_disable_echo_all": False,    # Disable Echo All Commands on startup.
        "output_enable_highlighting": True,  # Enable syntax highlighting in output.
        "output_highlight_errors_py": True,  # Highlight Python errors in output.
        "output_highlight_errors_mel": True, # Highlight MEL errors in output.
        "output_highlight_warnings_py": True,  # Highlight Python warnings.
        "output_highlight_warnings_mel": True, # Highlight MEL warnings.
        "output_highlight_results_py": True,   # Highlight Python results.
        "output_highlight_results_mel": True,  # Highlight MEL results.

        # --- MEL Language ---
        "mel_display_errors": True,          # Show errors and warnings for MEL.
        "mel_smart_indent": True,            # Smart indent (requires auto-indent).
        "mel_indent_to_bracket": False,      # Indent to bracket level.
        "mel_close_bracket": True,           # Auto-insert closing bracket.
        "mel_close_quotes": True,            # Auto-insert closing quotes.
        "mel_trim_whitespace": False,        # Trim trailing whitespace on save.
        "mel_ensure_newline": False,         # Ensure newline at end of file on save.
        "mel_double_click_dollar": True,     # Double-click selection includes $.
        "mel_autocomplete_quickhelp": True,  # Auto-complete updates Quick Help.
        "mel_autocomplete_ctrlspace": True,  # Ctrl+Space triggers auto-complete.
        "mel_autocomplete_on_letters": True, # Auto-complete triggers on letter keys.

        # --- Python Language ---
        "py_display_errors": True,           # Show errors and warnings for Python.
        "py_smart_indent": True,             # Smart indent (requires auto-indent).
        "py_indent_to_bracket": False,       # Indent to bracket level.
        "py_close_bracket": True,            # Auto-insert closing bracket.
        "py_close_quotes": True,             # Auto-insert closing quotes.
        "py_trim_whitespace": False,         # Trim trailing whitespace on save.
        "py_ensure_newline": False,          # Ensure newline at end of file on save.
        "py_hide_pyc": True,                 # Hide .pyc files in workspace.
        "py_import_pymel": False,            # Import PyMEL on load.
        "py_autocomplete_quickhelp": True,   # Auto-complete updates Quick Help.
        "py_confirm_overwrite_module": True, # Confirm before overwriting module state.
        "py_disable_revert_module": True,    # Disable revert module state on execute.
        "py_autocomplete_ctrlspace": True,   # Ctrl+Space triggers auto-complete.
        "py_autocomplete_on_letters": True,  # Auto-complete triggers on letter keys.
        "py_autocomplete_on_dot": True,      # Auto-complete triggers on '.' access.
        "py_autocomplete_keywords": True,    # Include Python keywords in auto-complete.
        "py_autocomplete_builtins": True,    # Include built-in names in auto-complete.
        "py_native_maya_fallback": False,    # Fall back to native Maya auto-complete.
        "py_forced_imports": "",             # Comma-separated forced import modules.

        # --- DCC Connection ---
        "dcc_auto_detect": True,
        "dcc_maya_port": 7001,            # Maya MEL command port
        "dcc_blender_port": 8400,         # Blender socket server port
        "dcc_unreal_port": 7003,          # Reserved for future Unreal support
        "dcc_unity_port": 7004,           # Reserved for future Unity support
        "last_connected_dcc": "",

        # --- AI ---
        "ai_enabled": False,
        "ai_provider": "none",            # none, anthropic, openai, gemini
        "ai_api_key": "",                 # Stored via QSettings (platform-secure)
        "ai_api_endpoint": "",            # For custom/local endpoints
        "ai_model": "",
        "ai_panel_visible": False,
        "ai_context_include_scene": True,
        "ai_context_include_output": True,
        "ai_auto_complete": False,

        # --- Terminal ---
        "terminal_shell": "",                # Custom shell path (empty = system default).
        "terminal_font_family": "Consolas",  # Terminal font family.
        "terminal_font_size": 12,            # Terminal font size.
        "terminal_scrollback_lines": 5000,   # Max scrollback buffer.

        # --- Window State ---
        "window_geometry": None,
        "window_state": None,
        "splitter_sizes": None,
        "center_splitter_sizes": None,   # Vertical splitter between output and editor.
        "output_visible": True,          # Whether the output panel is shown.
        "terminal_visible": False,       # Whether the terminal panel is shown.
        "sidebar_visible": True,         # Whether the sidebar is shown (Advanced mode).

        # --- Plugins ---
        "disabled_plugins": [],  # Plugin IDs to skip on load.
        "plugin_license_server_url": "https://activate.mcaeditor.com",  # Activation server for paid plugins.

        # --- Licensing ---
        "license_key": "",               # Stored license key string (MCA-XXXX-XXXX-XXXX-XXXX).
        "first_launch_date": "",         # ISO datetime of first launch (trial start).
        "trial_version": "",             # Version that started the current trial period.

        # --- Session Persistence ---
        "editor_was_open": False,        # Whether the editor was open when Maya last shut down.
    }

    def __init__(self, org_name="MCATools", app_name="MCAEditor",
                 backend=None, dcc_version=None):
        """
        Initialize the settings manager.

        If *backend* is not provided, tries to create a QSettings backend.
        Falls back to a plain dictionary if Qt is not available.

        When *dcc_version* is provided (e.g. ``"UE5"``), the QSettings
        app name is suffixed so each DCC gets its own settings store.
        This isolates window state, recent files, last project, and all
        other preferences per-DCC — UE won't restore Maya's layout.

        :param str org_name: Organization identifier for QSettings.
        :param str app_name: Application identifier for QSettings.
        :param backend: Optional pre-created backend (QSettings or dict-like).
        :param str dcc_version: Optional DCC version tag (e.g. ``"UE5"``)
            for per-DCC settings isolation.
        """
        # Append the DCC version to the app name so each DCC gets its
        # own QSettings store (separate Windows registry key / plist).
        if dcc_version:
            app_name = "{}-{}".format(app_name, dcc_version)

        if backend is not None:
            self._settings = backend
            self._use_qsettings = hasattr(backend, "setValue")
        else:
            # Try QSettings first, fall back to dict.
            try:
                from PySide6.QtCore import QSettings
                self._settings = QSettings(org_name, app_name)
                self._use_qsettings = True
            except ImportError:
                try:
                    from PySide2.QtCore import QSettings
                    self._settings = QSettings(org_name, app_name)
                    self._use_qsettings = True
                except ImportError:
                    # No Qt available — use plain dictionary backend.
                    self._settings = {}
                    self._use_qsettings = False
                    logger.info("QSettings unavailable, using dict backend")

        logger.debug("MCASettings initialized (org=%s, app=%s, qsettings=%s)",
                      org_name, app_name, self._use_qsettings)

    def get(self, key, default=None):
        """
        Get a setting value with fallback to built-in defaults.

        QSettings stores everything as strings on some platforms,
        so this method converts booleans and integers back to their
        expected Python types.

        :param str key: The setting key to retrieve.
        :param default: Override for the built-in default value.
        :return: The setting value in its correct type.
        :rtype: object
        """
        if default is None:
            default = self._DEFAULTS.get(key)

        if self._use_qsettings:
            value = self._settings.value(key, default)
        else:
            value = self._settings.get(key, default)

        # QSettings may return "true"/"false" strings for booleans.
        if isinstance(default, bool) and isinstance(value, str):
            return value.lower() == "true"

        # QSettings may return numeric strings for integers.
        if isinstance(default, int) and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default

        return value

    def set(self, key, value):
        """
        Set a setting value and write it to persistent storage.

        :param str key: The setting key to store.
        :param value: The value to persist.
        """
        if self._use_qsettings:
            self._settings.setValue(key, value)
        else:
            self._settings[key] = value

    # --- Project Settings ---------------------------------------------------

    def get_recent_projects(self):
        """
        Get the list of recently opened project root paths.

        :return: Project paths ordered most-recent-first.
        :rtype: list
        """
        projects = self.get("recent_projects", [])
        # Guard against QSettings returning a single string instead of list.
        return projects if isinstance(projects, list) else []

    def add_recent_project(self, project_path, max_entries=10):
        """
        Add a project to the recent projects list.

        Moves the path to the front if it already exists, and trims
        the list to *max_entries*.

        :param str project_path: Absolute path to the project root.
        :param int max_entries: Maximum number of entries to keep.
        """
        recent = self.get_recent_projects()
        # Remove duplicates so the path always lands at the front.
        if project_path in recent:
            recent.remove(project_path)
        recent.insert(0, project_path)
        self.set("recent_projects", recent[:max_entries])

    def get_last_project_path(self):
        """
        Get the last opened project path (for auto-reopen on startup).

        :return: Absolute path to the last project root, or empty string.
        :rtype: str
        """
        return self.get("last_project_path", "")

    def set_last_project_path(self, path):
        """
        Set the last opened project path.

        :param str path: Absolute path to the project root, or empty string.
        """
        self.set("last_project_path", path)

    def get_recent_files(self):
        """
        Get the list of recently opened file paths.

        :return: File paths ordered most-recent-first.
        :rtype: list
        """
        files = self.get("recent_files", [])
        # Guard against QSettings returning a single string instead of list.
        return files if isinstance(files, list) else []

    def add_recent_file(self, filepath, max_entries=20):
        """
        Add a file to the recent files list.

        Moves the file to the front if it already exists, and trims
        the list to *max_entries*.

        :param str filepath: Absolute path to the file.
        :param int max_entries: Maximum number of entries to keep.
        """
        recent = self.get_recent_files()
        # Remove duplicates so the file always lands at the front.
        if filepath in recent:
            recent.remove(filepath)
        recent.insert(0, filepath)
        self.set("recent_files", recent[:max_entries])

    def sync(self):
        """
        Force-write all pending settings to disk.

        Called on application close to ensure nothing is lost.
        """
        if self._use_qsettings:
            self._settings.sync()
        logger.debug("Settings synced to disk")
