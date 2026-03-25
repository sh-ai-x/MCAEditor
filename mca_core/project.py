"""
MCA Core - Project File Model.

Pure data model for ``.mca-project`` project files. Handles loading,
saving, validation, and auto-detection of Python source paths within
a project folder.

A project file is a JSON document with two layers:

    **Shared settings** (top-level, same across all DCC/versions):
        - Project name (display label)
        - Python source paths (relative to project root, added to sys.path)
        - Excluded folders (hidden in the workspace tree)
        - Open on editor open flag
        - Auto-reload modules flag

    **Profile-specific settings** (under ``"profiles"`` key, per DCC/version):
        - Startup script (relative path to a .py file run on project open)
        - Startup inline code (Python code run after the script file)
        - Shutdown script (relative path to a .py file run on project close)
        - Shutdown inline code (Python code run before teardown on close)
        - Environment variables (key-value pairs set in os.environ)
        - Load immediately flag (skip startup scripts on open)

    Profiles are keyed by DCC tag (e.g. ``"Maya2025"``, ``"Maya2024"``,
    ``"Unreal"``).  A ``"default"`` profile is used as fallback when no
    DCC-specific profile matches.

    Schema version 3 (flat) is auto-migrated to version 4 (profiles)
    on load — the flat DCC-specific fields are moved into a ``"default"``
    profile.

Dependencies:
    - json (stdlib)
    - os (stdlib)
    - logging (stdlib)
"""

import json
import logging
import os

# Module-level logger for project operations.
logger = logging.getLogger(__name__)


# --- Constants ---------------------------------------------------------------

PROJECT_FILENAME = ".mca-project"              # Name of the project config file.
SESSION_FILENAME = ".mca-session.json"          # Per-project session manifest file.
CURRENT_SCHEMA_VERSION = 4                      # Bump when the JSON schema changes.

# Keys that live inside each profile (DCC-specific settings).
PROFILE_KEYS = (
    "startup_script",
    "startup_code",
    "startup_language",
    "shutdown_script",
    "shutdown_code",
    "shutdown_language",
    "env_vars",
    "load_immediately",
)

# Default values for profile-specific keys (used when a key is missing).
PROFILE_DEFAULTS = {
    "startup_script": "",
    "startup_code": "",
    "startup_language": "python",
    "shutdown_script": "",
    "shutdown_code": "",
    "shutdown_language": "python",
    "env_vars": {},
    "load_immediately": False,
}

# Folders excluded from the workspace tree by default.
DEFAULT_EXCLUDED_FOLDERS = {
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
    ".vscode",
    ".idea",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "*.egg-info",
    "build",
    "dist",
}

# Common directory names that suggest Python source lives here.
# detect_python_paths() checks for these relative to the project root.
PYTHON_PATH_HINTS = [
    "src",
    "lib",
    "python",
    "scripts",
    "source",
    "packages",
]


# --- MCAProject Model -------------------------------------------------------

class MCAProject:
    """
    In-memory representation of a ``.mca-project`` file.

    Loads from and saves to a JSON file at the project root. All paths
    stored in the file are relative to the project root; resolved paths
    are computed on the fly via ``resolved_python_paths``.

    DCC-specific settings (startup/shutdown code, env vars, load_immediately)
    are stored in **profiles** keyed by DCC tag (e.g. ``"Maya2025"``).
    When a ``dcc_tag`` is provided, that profile's values are used.
    Falls back to ``"default"`` when the exact tag has no profile.

    :param str project_root: Absolute path to the project root directory.
    :param str dcc_tag: Optional DCC version tag (e.g. ``"Maya2025"``).
    """

    def __init__(self, project_root, dcc_tag=None):
        """
        Initialize from a project root directory.

        If a ``.mca-project`` file exists, it is loaded immediately.
        Otherwise the project starts with default values and must be
        saved explicitly via ``save()``.

        :param str project_root: Absolute path to the project root.
        :param str dcc_tag: Optional DCC version tag for profile selection.
        """
        self._project_root = os.path.normpath(project_root)
        self._name = os.path.basename(self._project_root)

        # --- Shared settings (not profile-specific) ---
        self._python_paths = []          # Relative paths (e.g. ["src", "lib"]).
        self._excluded_folders = list(DEFAULT_EXCLUDED_FOLDERS)
        self._open_on_editor_open = False  # Auto-open this project when editor launches.
        self._auto_reload_modules = True   # Auto-reload modules on save/execute.
        self._schema_version = CURRENT_SCHEMA_VERSION

        # --- Profile system ---
        # Profiles dict: {"Maya2025": {...}, "Maya2024": {...}, "default": {...}}
        # Each profile contains the keys listed in PROFILE_KEYS.
        self._dcc_tag = dcc_tag          # e.g. "Maya2025", "Unreal", or None.
        self._profiles = {}              # All profiles loaded from the file.
        self._active_profile_name = "default"  # Resolved after load.

        # Auto-load if the project file already exists.
        if os.path.isfile(self.project_file_path):
            self.load()

        # Resolve which profile is active (even if load() wasn't called,
        # so new projects get a sensible active profile).
        self._resolve_active_profile()

    # --- Profile Helpers (private) --------------------------------------------

    def _resolve_active_profile(self):
        """
        Determine which profile is active based on ``_dcc_tag``.

        Resolution order:
            1. Exact match on ``_dcc_tag`` (e.g. ``"Maya2025"``)
            2. ``"default"`` profile
            3. Use ``_dcc_tag`` as name (will be created on first write),
               or ``"default"`` if no dcc_tag was provided.
        """
        if self._dcc_tag and self._dcc_tag in self._profiles:
            # Exact match — use the DCC-specific profile.
            self._active_profile_name = self._dcc_tag
        elif "default" in self._profiles:
            # No DCC-specific profile — fall back to default.
            self._active_profile_name = "default"
        else:
            # No matching profile exists yet — use dcc_tag name so it
            # gets created when the user saves, or "default" if standalone.
            self._active_profile_name = self._dcc_tag or "default"

    def _get_profile_value(self, key):
        """
        Read a value from the active profile.

        Falls back to ``PROFILE_DEFAULTS`` if the key is missing.

        :param str key: Profile key (must be one of ``PROFILE_KEYS``).
        :return: The value from the active profile.
        """
        profile = self._profiles.get(self._active_profile_name, {})
        return profile.get(key, PROFILE_DEFAULTS.get(key))

    def _set_profile_value(self, key, value):
        """
        Write a value to the active profile.

        Creates the profile dict if it doesn't exist yet.

        :param str key: Profile key (must be one of ``PROFILE_KEYS``).
        :param value: The value to store.
        """
        if self._active_profile_name not in self._profiles:
            # Lazy-create the profile with all defaults.
            self._profiles[self._active_profile_name] = dict(PROFILE_DEFAULTS)
        self._profiles[self._active_profile_name][key] = value

    # --- Shared Properties (not profile-specific) ----------------------------

    @property
    def name(self):
        """
        Human-readable project name.

        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, value):
        """
        Set the project name.

        :param str value: New project name.
        """
        self._name = value

    @property
    def project_root(self):
        """
        Absolute path to the project root directory.

        :rtype: str
        """
        return self._project_root

    @property
    def project_file_path(self):
        """
        Absolute path to the ``.mca-project`` JSON file.

        :rtype: str
        """
        return os.path.join(self._project_root, PROJECT_FILENAME)

    @property
    def session_file_path(self):
        """
        Absolute path to the per-project session manifest file.

        When a ``dcc_tag`` is set (e.g. ``"UE5"``, ``"Maya2025"``),
        returns a DCC-specific filename so different DCCs don't
        overwrite each other's tab layouts within the same project.

        - UE5:      ``.mca-session-UE5.json``
        - Maya2025: ``.mca-session-Maya2025.json``
        - None:     ``.mca-session.json`` (default / standalone)

        :rtype: str
        """
        # Use a DCC-specific session file when running inside a DCC
        # so Maya and UE can open the same project with independent
        # tab layouts.
        if self._dcc_tag:
            name = ".mca-session-{}.json".format(self._dcc_tag)
        else:
            name = SESSION_FILENAME
        return os.path.join(self._project_root, name)

    @property
    def python_paths(self):
        """
        Relative Python source paths stored in the project file.

        :rtype: list
        """
        return list(self._python_paths)

    @python_paths.setter
    def python_paths(self, paths):
        """
        Set the relative Python source paths.

        :param list paths: List of relative directory path strings.
        """
        self._python_paths = list(paths)

    @property
    def resolved_python_paths(self):
        """
        Absolute Python source paths (project root joined with each relative path).

        If the list is empty, the project root itself is included so that
        top-level modules are importable.

        :rtype: list
        """
        if not self._python_paths:
            return [self._project_root]
        return [os.path.normpath(os.path.join(self._project_root, p))
                for p in self._python_paths]

    @property
    def excluded_folders(self):
        """
        Folder names excluded from the workspace tree.

        :rtype: list
        """
        return list(self._excluded_folders)

    @excluded_folders.setter
    def excluded_folders(self, folders):
        """
        Set the excluded folder names.

        :param list folders: List of folder name strings.
        """
        self._excluded_folders = list(folders)

    @property
    def open_on_editor_open(self):
        """
        Whether this project should auto-open when the editor launches.

        :rtype: bool
        """
        return self._open_on_editor_open

    @open_on_editor_open.setter
    def open_on_editor_open(self, value):
        """
        Set the open_on_editor_open flag.

        :param bool value: True to auto-open on editor launch.
        """
        self._open_on_editor_open = bool(value)

    @property
    def auto_reload_modules(self):
        """
        Whether modules should auto-reload on save/execute.

        When True, saving or executing a ``.py`` file that has already
        been imported will trigger ``importlib.reload()`` both locally
        and in the connected DCC.

        :rtype: bool
        """
        return self._auto_reload_modules

    @auto_reload_modules.setter
    def auto_reload_modules(self, value):
        """
        Set the auto_reload_modules flag.

        :param bool value: True to auto-reload on save/execute.
        """
        self._auto_reload_modules = bool(value)

    # --- Profile-Specific Properties -----------------------------------------
    # These read/write from the active profile (selected by dcc_tag).

    @property
    def startup_script(self):
        """
        Relative path to a Python script that runs when the project opens.

        Empty string means no startup script. Reads from the active profile.

        :rtype: str
        """
        return self._get_profile_value("startup_script")

    @startup_script.setter
    def startup_script(self, path):
        """
        Set the startup script path (relative to project root).

        :param str path: Relative path to a .py file, or empty string.
        """
        self._set_profile_value("startup_script", path)

    @property
    def startup_code(self):
        """
        Inline Python code that runs when the project opens.

        Executed after the startup script file (if any). Empty string
        means no inline code. Reads from the active profile.

        :rtype: str
        """
        return self._get_profile_value("startup_code")

    @startup_code.setter
    def startup_code(self, code):
        """
        Set the inline startup code.

        :param str code: Python code string, or empty string.
        """
        self._set_profile_value("startup_code", code)

    @property
    def startup_language(self):
        """
        Language for the inline startup code ('python' or 'mel').

        :rtype: str
        """
        return self._get_profile_value("startup_language") or "python"

    @startup_language.setter
    def startup_language(self, lang):
        """
        Set the language for inline startup code.

        :param str lang: Language identifier ('python' or 'mel').
        """
        self._set_profile_value("startup_language", lang)

    @property
    def resolved_startup_script(self):
        """
        Absolute path to the startup script, or empty string if not set.

        :rtype: str
        """
        script = self.startup_script
        if not script:
            return ""
        return os.path.normpath(
            os.path.join(self._project_root, script)
        )

    @property
    def shutdown_script(self):
        """
        Relative path to a Python script that runs when the project closes.

        Empty string means no shutdown script. Reads from the active profile.

        :rtype: str
        """
        return self._get_profile_value("shutdown_script")

    @shutdown_script.setter
    def shutdown_script(self, path):
        """
        Set the shutdown script path (relative to project root).

        :param str path: Relative path to a .py file, or empty string.
        """
        self._set_profile_value("shutdown_script", path)

    @property
    def shutdown_code(self):
        """
        Inline Python code that runs when the project closes.

        Executed after the shutdown script file (if any), but before
        environment variables and paths are torn down. Empty string
        means no inline code. Reads from the active profile.

        :rtype: str
        """
        return self._get_profile_value("shutdown_code")

    @shutdown_code.setter
    def shutdown_code(self, code):
        """
        Set the inline shutdown code.

        :param str code: Python code string, or empty string.
        """
        self._set_profile_value("shutdown_code", code)

    @property
    def shutdown_language(self):
        """
        Language for the inline shutdown code ('python' or 'mel').

        :rtype: str
        """
        return self._get_profile_value("shutdown_language") or "python"

    @shutdown_language.setter
    def shutdown_language(self, lang):
        """
        Set the language for inline shutdown code.

        :param str lang: Language identifier ('python' or 'mel').
        """
        self._set_profile_value("shutdown_language", lang)

    @property
    def resolved_shutdown_script(self):
        """
        Absolute path to the shutdown script, or empty string if not set.

        :rtype: str
        """
        script = self.shutdown_script
        if not script:
            return ""
        return os.path.normpath(
            os.path.join(self._project_root, script)
        )

    @property
    def env_vars(self):
        """
        Environment variables to set when the project is opened.

        Returns a copy of the active profile's env vars dict.

        :rtype: dict
        """
        return dict(self._get_profile_value("env_vars") or {})

    @env_vars.setter
    def env_vars(self, variables):
        """
        Set the environment variables dictionary on the active profile.

        :param dict variables: Key-value string pairs.
        """
        self._set_profile_value("env_vars", dict(variables))

    @property
    def load_immediately(self):
        """
        Whether to skip startup scripts when the project is opened.

        When True, opening the project only sets up paths, env vars,
        and UI — startup scripts are deferred until the user clicks
        the Load button. Reads from the active profile.

        :rtype: bool
        """
        return self._get_profile_value("load_immediately")

    @load_immediately.setter
    def load_immediately(self, value):
        """
        Set the load_immediately flag on the active profile.

        :param bool value: True to skip startup on open.
        """
        self._set_profile_value("load_immediately", bool(value))

    # --- Profile Management (public) -----------------------------------------

    @property
    def dcc_tag(self):
        """
        The DCC version tag used to select the active profile.

        :rtype: str or None
        """
        return self._dcc_tag

    @property
    def active_profile_name(self):
        """
        Name of the currently active profile.

        :rtype: str
        """
        return self._active_profile_name

    @property
    def profile_names(self):
        """
        Sorted list of all profile names in this project.

        :rtype: list
        """
        return sorted(self._profiles.keys())

    @property
    def profiles(self):
        """
        All profiles as a dict of dicts (deep copy).

        :rtype: dict
        """
        import copy
        return copy.deepcopy(self._profiles)

    def set_profiles(self, profiles):
        """
        Replace all profiles with a new dict.

        Used by the settings dialog to apply edits across all profiles
        at once. Re-resolves the active profile after replacement.

        :param dict profiles: Dict of profile dicts keyed by name.
        """
        import copy
        self._profiles = copy.deepcopy(profiles)
        self._resolve_active_profile()

    def get_profile_data(self, profile_name):
        """
        Return a copy of a specific profile's data.

        Returns ``PROFILE_DEFAULTS`` if the profile doesn't exist.

        :param str profile_name: Profile name (e.g. ``"Maya2025"``).
        :return: Profile settings dict.
        :rtype: dict
        """
        if profile_name in self._profiles:
            return dict(self._profiles[profile_name])
        return dict(PROFILE_DEFAULTS)

    def add_profile(self, profile_name, data=None):
        """
        Add a new profile with default values (or provided data).

        :param str profile_name: Profile name to create.
        :param dict data: Optional initial data (merged over defaults).
        """
        new_profile = dict(PROFILE_DEFAULTS)
        if data:
            new_profile.update(data)
        self._profiles[profile_name] = new_profile
        logger.info("Added profile '%s' to project '%s'", profile_name, self._name)

    def remove_profile(self, profile_name):
        """
        Remove a profile by name.

        Cannot remove the active profile — switch to a different one first.

        :param str profile_name: Profile name to remove.
        :return: True if removed, False if not found or is active.
        :rtype: bool
        """
        if profile_name == self._active_profile_name:
            logger.warning("Cannot remove the active profile '%s'", profile_name)
            return False
        if profile_name in self._profiles:
            del self._profiles[profile_name]
            logger.info("Removed profile '%s' from project '%s'",
                        profile_name, self._name)
            return True
        return False

    # --- Load / Save ----------------------------------------------------------

    def load(self):
        """
        Load project settings from the ``.mca-project`` JSON file.

        Handles both schema v3 (flat format) and v4+ (profiles).
        v3 files are auto-migrated: DCC-specific fields are moved into
        a ``"default"`` profile.

        Silently falls back to defaults if the file is missing or corrupt.

        :return: True if the file was loaded successfully.
        :rtype: bool
        """
        try:
            with open(self.project_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load project file %s: %s",
                           self.project_file_path, exc)
            return False

        # --- Shared fields (same in v3 and v4) ---
        self._name = data.get("name", os.path.basename(self._project_root))
        self._python_paths = data.get("python_paths", [])
        self._excluded_folders = data.get("excluded_folders",
                                          list(DEFAULT_EXCLUDED_FOLDERS))
        self._open_on_editor_open = data.get("open_on_editor_open", False)
        self._auto_reload_modules = data.get("auto_reload_modules", True)
        self._schema_version = data.get("schema_version", 3)

        # --- Profile-specific fields ---
        if "profiles" in data:
            # v4+ format: profiles dict already present.
            self._profiles = data["profiles"]
        else:
            # v3 migration: move flat DCC-specific fields into a "default" profile.
            default_profile = {}
            for key in PROFILE_KEYS:
                if key in data:
                    default_profile[key] = data[key]
                else:
                    default_profile[key] = PROFILE_DEFAULTS[key]
            self._profiles = {"default": default_profile}
            logger.info("Migrated v3 project '%s' to v4 profile format", self._name)

        # Resolve which profile is active after loading.
        self._resolve_active_profile()

        logger.info("Loaded project '%s' from %s (profile: %s)",
                     self._name, self.project_file_path,
                     self._active_profile_name)
        return True

    def save(self):
        """
        Write the current project settings to the ``.mca-project`` JSON file.

        Always writes v4 format with profiles, even if the file was
        originally v3.

        :return: True if the file was written successfully.
        :rtype: bool
        """
        data = self.to_dict()
        try:
            with open(self.project_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, sort_keys=False)
            logger.info("Saved project '%s' to %s", self._name, self.project_file_path)
            return True
        except OSError as exc:
            logger.error("Could not save project file %s: %s",
                         self.project_file_path, exc)
            return False

    def to_dict(self):
        """
        Serialize project settings to a plain dictionary.

        Always outputs v4 format with ``"profiles"`` dict.

        :return: Dictionary suitable for JSON serialization.
        :rtype: dict
        """
        return {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "name": self._name,
            "python_paths": self._python_paths,
            "excluded_folders": self._excluded_folders,
            "open_on_editor_open": self._open_on_editor_open,
            "auto_reload_modules": self._auto_reload_modules,
            "profiles": self._profiles,
        }

    def validate(self):
        """
        Check that the project root exists, all Python paths resolve
        to real directories, and the active profile's scripts exist.

        :return: List of warning strings (empty if everything is valid).
        :rtype: list
        """
        warnings = []

        if not os.path.isdir(self._project_root):
            warnings.append("Project root does not exist: {}".format(self._project_root))

        for rel_path in self._python_paths:
            abs_path = os.path.join(self._project_root, rel_path)
            if not os.path.isdir(abs_path):
                warnings.append("Python path does not exist: {}".format(rel_path))

        # Validate startup script exists if specified (active profile).
        startup_script = self.startup_script
        if startup_script:
            script_path = self.resolved_startup_script
            if not os.path.isfile(script_path):
                warnings.append("[{}] Startup script not found: {}".format(
                    self._active_profile_name, startup_script))

        # Validate shutdown script exists if specified (active profile).
        shutdown_script = self.shutdown_script
        if shutdown_script:
            script_path = self.resolved_shutdown_script
            if not os.path.isfile(script_path):
                warnings.append("[{}] Shutdown script not found: {}".format(
                    self._active_profile_name, shutdown_script))

        return warnings


# --- Module-Level Helper Functions -------------------------------------------

def has_project_file(folder_path):
    """
    Check whether a ``.mca-project`` file exists in the given folder.

    :param str folder_path: Absolute path to check.
    :return: True if the project file exists.
    :rtype: bool
    """
    return os.path.isfile(os.path.join(folder_path, PROJECT_FILENAME))


def detect_python_paths(folder_path):
    """
    Auto-detect likely Python source directories in a folder.

    Scans top-level subdirectories for common names (``src``, ``lib``,
    ``python``, etc.) and directories containing ``__init__.py``.
    Returns relative paths suitable for ``MCAProject.python_paths``.

    :param str folder_path: Absolute path to the project root.
    :return: List of relative directory paths that likely contain Python code.
    :rtype: list
    """
    detected = []

    try:
        entries = os.listdir(folder_path)
    except OSError:
        return detected

    for entry in sorted(entries):
        full_path = os.path.join(folder_path, entry)
        if not os.path.isdir(full_path):
            continue

        # Skip hidden and excluded directories.
        if entry.startswith(".") or entry in DEFAULT_EXCLUDED_FOLDERS:
            continue

        # Check for well-known source directory names.
        if entry.lower() in PYTHON_PATH_HINTS:
            detected.append(entry)
            continue

        # Check for Python packages (directories with __init__.py).
        init_file = os.path.join(full_path, "__init__.py")
        if os.path.isfile(init_file):
            # The parent (project root) should be on sys.path, not the
            # package dir itself. Only add "." if not already implied.
            if "." not in detected:
                detected.append(".")
            continue

    # Also check if there are .py files directly in the root.
    has_root_py = any(
        e.endswith(".py") for e in entries
        if os.path.isfile(os.path.join(folder_path, e))
    )
    if has_root_py and "." not in detected:
        detected.append(".")

    return detected


def create_default_project(folder_path, name=None, python_paths=None,
                           excluded_folders=None, dcc_tag=None):
    """
    Create a new ``.mca-project`` file with sensible defaults.

    :param str folder_path: Absolute path to the project root.
    :param str name: Project display name (defaults to folder basename).
    :param list python_paths: Relative Python paths (auto-detected if None).
    :param list excluded_folders: Excluded folder names (uses defaults if None).
    :param str dcc_tag: Optional DCC version tag (e.g. ``"Maya2025"``).
    :return: The newly created MCAProject instance.
    :rtype: MCAProject
    """
    project = MCAProject(folder_path, dcc_tag=dcc_tag)

    if name:
        project.name = name
    if python_paths is not None:
        project.python_paths = python_paths
    else:
        project.python_paths = detect_python_paths(folder_path)
    if excluded_folders is not None:
        project.excluded_folders = excluded_folders

    project.save()
    logger.info("Created new project '%s' at %s", project.name, folder_path)
    return project
