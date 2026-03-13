"""
Platform Utilities — Cross-platform path helpers for MCA Editor.

Centralizes all platform-specific directory logic so that every module
in the project uses the same rules.  All functions return ``str`` (not
``pathlib.Path``) to match the rest of the codebase.

Getters are pure — they never create directories.  Call ``os.makedirs()``
at the point of use when you actually need the directory to exist.

Supported platforms:
    - Windows (``sys.platform == 'win32'``)
    - macOS   (``sys.platform == 'darwin'``)
    - Linux   (everything else)

Dependencies:
    - None (pure Python stdlib: ``os``, ``sys``, ``platform``)
"""

import os
import sys
import platform


# --- Platform Detection ----------------------------------------------------

def get_platform():
    """
    Return a normalized platform name.

    :return: ``'windows'``, ``'macos'``, or ``'linux'``.
    :rtype: str
    """
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    return "linux"


def is_windows():
    """
    Check if the current platform is Windows.

    :return: True on Windows.
    :rtype: bool
    """
    return sys.platform == "win32"


def is_macos():
    """
    Check if the current platform is macOS.

    :return: True on macOS.
    :rtype: bool
    """
    return sys.platform == "darwin"


def is_linux():
    """
    Check if the current platform is Linux (or any non-Windows, non-macOS POSIX).

    :return: True on Linux.
    :rtype: bool
    """
    return sys.platform not in ("win32", "darwin")


# --- MCA Editor Directories ------------------------------------------------

def get_preferences_dir():
    """
    Return the MCA Editor preferences directory path.

    All persistent user data — managed venv, session buffers, user plugins,
    MCP server deployments, API discovery files — lives under this directory.

    Platform paths:
        - Windows: ``~/Documents/mca_preferences/MCAEditor``
        - macOS:   ``~/Documents/mca_preferences/MCAEditor``
        - Linux:   ``~/.config/mca_preferences/MCAEditor``

    Does NOT create the directory — call ``os.makedirs()`` at point of use.

    :return: Absolute path to the preferences directory.
    :rtype: str
    """
    home = os.path.expanduser("~")

    if sys.platform in ("win32", "darwin"):
        # Windows and macOS both use ~/Documents.
        base = os.path.join(home, "Documents")
    else:
        # Linux follows XDG convention — ~/.config.
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))

    return os.path.join(base, "mca_preferences", "MCAEditor")


def get_cache_dir(maya_version, python_version):
    """
    Return the extraction-cache directory for the single-file distribution.

    Each Maya version and Python version pair gets its own isolated cache
    so compiled ``.pyd`` / ``.so`` files from different ABIs never collide.

    Platform paths:
        - Windows: ``%LOCALAPPDATA%/MCAEditor-Maya<ver>-py<pyver>``
        - macOS:   ``~/Library/Caches/MCAEditor-Maya<ver>-py<pyver>``
        - Linux:   ``$XDG_CACHE_HOME/MCAEditor-Maya<ver>-py<pyver>``
                   (falls back to ``~/.cache``)

    Does NOT create the directory.

    :param str maya_version: Maya year string, e.g. ``"2025"``.
    :param str python_version: Python major.minor string, e.g. ``"3.11"``.
    :return: Absolute path to the cache directory.
    :rtype: str
    """
    dir_name = "MCAEditor-Maya{}-py{}".format(maya_version, python_version)

    if sys.platform == "win32":
        # %LOCALAPPDATA% is always set on modern Windows.
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return os.path.join(local, dir_name)
        # Fallback: ~/MCAEditor-... (matches original behaviour).
        return os.path.join(os.path.expanduser("~"), dir_name)

    elif sys.platform == "darwin":
        # macOS caches live under ~/Library/Caches/.
        return os.path.join(os.path.expanduser("~"), "Library", "Caches", dir_name)

    else:
        # Linux: XDG_CACHE_HOME defaults to ~/.cache.
        cache_base = os.environ.get("XDG_CACHE_HOME",
                                    os.path.join(os.path.expanduser("~"), ".cache"))
        return os.path.join(cache_base, dir_name)


# --- Maya Directories ------------------------------------------------------

def get_maya_app_dir():
    """
    Return Maya's application preferences directory.

    This is the top-level ``maya/`` folder that contains version subdirectories,
    modules, etc.

    Platform paths:
        - Windows: ``~/Documents/maya``
        - macOS:   ``~/Library/Preferences/Autodesk/maya``
        - Linux:   ``~/maya``

    Does NOT create the directory.

    :return: Absolute path to the Maya application directory.
    :rtype: str
    """
    home = os.path.expanduser("~")

    if sys.platform == "win32":
        return os.path.join(home, "Documents", "maya")
    elif sys.platform == "darwin":
        return os.path.join(home, "Library", "Preferences", "Autodesk", "maya")
    else:
        # Linux.
        return os.path.join(home, "maya")


def get_maya_scripts_dir(version):
    """
    Return the Maya scripts directory for a specific version.

    This is where ``userSetup.py`` lives.

    :param str version: Maya version year, e.g. ``"2025"``.
    :return: Absolute path to ``<maya_app_dir>/<version>/scripts``.
    :rtype: str
    """
    return os.path.join(get_maya_app_dir(), version, "scripts")


def get_maya_plugins_dir(version):
    """
    Return the Maya plug-ins directory for a specific version.

    This is where ``.py`` / ``.mll`` plugin files are placed.

    :param str version: Maya version year, e.g. ``"2025"``.
    :return: Absolute path to ``<maya_app_dir>/<version>/plug-ins``.
    :rtype: str
    """
    return os.path.join(get_maya_app_dir(), version, "plug-ins")


# --- Maya Runtime Helpers --------------------------------------------------

def is_batch_mode():
    """
    Check if Maya is running in batch mode (``maya -batch``).

    Returns False if Maya is not importable (standalone or non-Maya context).

    :return: True if Maya is in batch mode.
    :rtype: bool
    """
    try:
        import maya.cmds as cmds
        return cmds.about(batch=True)
    except Exception:
        # maya.cmds not available — not in Maya at all.
        return False
