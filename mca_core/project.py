"""
MCA Core - Project File Model.

Pure data model for ``.mca-project`` project files. Handles loading,
saving, validation, and auto-detection of Python source paths within
a project folder.

A project file is a simple JSON document that tracks:
    - Project name (display label)
    - Python source paths (relative to project root, added to sys.path)
    - Excluded folders (hidden in the workspace tree)
    - Startup script (relative path to a .py file run on project open)
    - Startup inline code (Python code run after the script file)
    - Shutdown script (relative path to a .py file run on project close)
    - Shutdown inline code (Python code run before teardown on close)
    - Environment variables (key-value pairs set in os.environ on open)
    - Schema version (for future migration)

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
CURRENT_SCHEMA_VERSION = 3                      # Bump when the JSON schema changes.

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

    :param str project_root: Absolute path to the project root directory.
    """

    def __init__(self, project_root):
        """
        Initialize from a project root directory.

        If a ``.mca-project`` file exists, it is loaded immediately.
        Otherwise the project starts with default values and must be
        saved explicitly via ``save()``.

        :param str project_root: Absolute path to the project root.
        """
        self._project_root = os.path.normpath(project_root)
        self._name = os.path.basename(self._project_root)
        self._python_paths = []          # Relative paths (e.g. ["src", "lib"]).
        self._excluded_folders = list(DEFAULT_EXCLUDED_FOLDERS)
        self._startup_script = ""        # Relative path to a .py startup script.
        self._startup_code = ""          # Inline Python code run after the script.
        self._shutdown_script = ""       # Relative path to a .py shutdown script.
        self._shutdown_code = ""         # Inline Python code run before teardown.
        self._env_vars = {}              # Key-value pairs set in os.environ.
        self._load_immediately = False   # Skip startup scripts on project open.
        self._open_on_editor_open = False  # Auto-open this project when editor launches.
        self._schema_version = CURRENT_SCHEMA_VERSION

        # Auto-load if the project file already exists.
        if os.path.isfile(self.project_file_path):
            self.load()

    # --- Properties -----------------------------------------------------------

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

        Used to save/restore the tab layout when switching between
        the default workspace and this project.

        :rtype: str
        """
        return os.path.join(self._project_root, SESSION_FILENAME)

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
    def startup_script(self):
        """
        Relative path to a Python script that runs when the project opens.

        Empty string means no startup script.

        :rtype: str
        """
        return self._startup_script

    @startup_script.setter
    def startup_script(self, path):
        """
        Set the startup script path (relative to project root).

        :param str path: Relative path to a .py file, or empty string.
        """
        self._startup_script = path

    @property
    def startup_code(self):
        """
        Inline Python code that runs when the project opens.

        Executed after the startup script file (if any). Empty string
        means no inline code.

        :rtype: str
        """
        return self._startup_code

    @startup_code.setter
    def startup_code(self, code):
        """
        Set the inline startup code.

        :param str code: Python code string, or empty string.
        """
        self._startup_code = code

    @property
    def resolved_startup_script(self):
        """
        Absolute path to the startup script, or empty string if not set.

        :rtype: str
        """
        if not self._startup_script:
            return ""
        return os.path.normpath(
            os.path.join(self._project_root, self._startup_script)
        )

    @property
    def shutdown_script(self):
        """
        Relative path to a Python script that runs when the project closes.

        Empty string means no shutdown script.

        :rtype: str
        """
        return self._shutdown_script

    @shutdown_script.setter
    def shutdown_script(self, path):
        """
        Set the shutdown script path (relative to project root).

        :param str path: Relative path to a .py file, or empty string.
        """
        self._shutdown_script = path

    @property
    def shutdown_code(self):
        """
        Inline Python code that runs when the project closes.

        Executed after the shutdown script file (if any), but before
        environment variables and paths are torn down. Empty string
        means no inline code.

        :rtype: str
        """
        return self._shutdown_code

    @shutdown_code.setter
    def shutdown_code(self, code):
        """
        Set the inline shutdown code.

        :param str code: Python code string, or empty string.
        """
        self._shutdown_code = code

    @property
    def resolved_shutdown_script(self):
        """
        Absolute path to the shutdown script, or empty string if not set.

        :rtype: str
        """
        if not self._shutdown_script:
            return ""
        return os.path.normpath(
            os.path.join(self._project_root, self._shutdown_script)
        )

    @property
    def env_vars(self):
        """
        Environment variables to set when the project is opened.

        Returns a copy of the internal dict.

        :rtype: dict
        """
        return dict(self._env_vars)

    @env_vars.setter
    def env_vars(self, variables):
        """
        Set the environment variables dictionary.

        :param dict variables: Key-value string pairs.
        """
        self._env_vars = dict(variables)

    @property
    def load_immediately(self):
        """
        Whether to skip startup scripts when the project is opened.

        When True, opening the project only sets up paths, env vars,
        and UI — startup scripts are deferred until the user clicks
        the Load button.

        :rtype: bool
        """
        return self._load_immediately

    @load_immediately.setter
    def load_immediately(self, value):
        """
        Set the load_immediately flag.

        :param bool value: True to skip startup on open.
        """
        self._load_immediately = bool(value)

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

    # --- Load / Save ----------------------------------------------------------

    def load(self):
        """
        Load project settings from the ``.mca-project`` JSON file.

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

        # Extract fields with safe defaults.
        self._name = data.get("name", os.path.basename(self._project_root))
        self._python_paths = data.get("python_paths", [])
        self._excluded_folders = data.get("excluded_folders",
                                          list(DEFAULT_EXCLUDED_FOLDERS))
        self._startup_script = data.get("startup_script", "")
        self._startup_code = data.get("startup_code", "")
        self._shutdown_script = data.get("shutdown_script", "")
        self._shutdown_code = data.get("shutdown_code", "")
        self._env_vars = data.get("env_vars", {})
        self._load_immediately = data.get("load_immediately", False)
        self._open_on_editor_open = data.get("open_on_editor_open", False)
        self._schema_version = data.get("schema_version", CURRENT_SCHEMA_VERSION)

        logger.info("Loaded project '%s' from %s", self._name, self.project_file_path)
        return True

    def save(self):
        """
        Write the current project settings to the ``.mca-project`` JSON file.

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

        :return: Dictionary suitable for JSON serialization.
        :rtype: dict
        """
        return {
            "schema_version": self._schema_version,
            "name": self._name,
            "python_paths": self._python_paths,
            "excluded_folders": self._excluded_folders,
            "startup_script": self._startup_script,
            "startup_code": self._startup_code,
            "shutdown_script": self._shutdown_script,
            "shutdown_code": self._shutdown_code,
            "env_vars": self._env_vars,
            "load_immediately": self._load_immediately,
            "open_on_editor_open": self._open_on_editor_open,
        }

    def validate(self):
        """
        Check that the project root exists and all Python paths resolve
        to real directories.

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

        # Validate startup script exists if specified.
        if self._startup_script:
            script_path = self.resolved_startup_script
            if not os.path.isfile(script_path):
                warnings.append("Startup script not found: {}".format(
                    self._startup_script))

        # Validate shutdown script exists if specified.
        if self._shutdown_script:
            script_path = self.resolved_shutdown_script
            if not os.path.isfile(script_path):
                warnings.append("Shutdown script not found: {}".format(
                    self._shutdown_script))

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
                           excluded_folders=None):
    """
    Create a new ``.mca-project`` file with sensible defaults.

    :param str folder_path: Absolute path to the project root.
    :param str name: Project display name (defaults to folder basename).
    :param list python_paths: Relative Python paths (auto-detected if None).
    :param list excluded_folders: Excluded folder names (uses defaults if None).
    :return: The newly created MCAProject instance.
    :rtype: MCAProject
    """
    project = MCAProject(folder_path)

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
