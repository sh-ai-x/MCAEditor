"""
MCA Core - Pure Python foundation for MCA Editor.

DCC-agnostic, zero-Qt core package that provides:
    - Adapter base classes and manager for DCC connections
    - Settings abstraction with pluggable backends
    - Internal Maya adapter for embedded plugin mode

This package has NO Qt dependency so it can be imported in any
Python environment (standalone, Maya, Blender, etc.).

Dependencies:
    - None (pure Python stdlib)
"""

import os
import sys

# --- Version & App Metadata -----------------------------------------------

# Semantic version for the application.
__version__ = "0.3.6"

# Display name shown in title bars and dialogs.
__app_name__ = "MCA Editor"

# Organization name used by QSettings for persistent storage.
__org_name__ = "MCATools"

# Organization domain used by QSettings.
__org_domain__ = "mcatools.dev"

# --- Package Root Tracking ------------------------------------------------
# The directory that contains mca_core/, mca_qt/, mca_maya/ — either the
# extraction cache or the source project root.  Computed once at import
# time so it can be re-added to sys.path if something removes it.

_package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Preferences Directory ------------------------------------------------
# All MCA Editor user data lives under ~/Documents/mca_preferences/MCAEditor/.
# The parent "mca_preferences" folder is shared with other MCA tools (the MCA
# codebase), so MCA Editor keeps its own files in a dedicated subfolder.
# Computed once at import time and used by all modules that need persistent
# storage (venv, session manager, plugins, MCP servers, API discovery, etc.).

_prefs_dir = os.path.join(
    os.path.expanduser("~/Documents"), "mca_preferences", "MCAEditor"
)


def get_prefs_dir():
    """
    Return the MCA Editor preferences directory path.

    All persistent user data — managed venv, session buffers, user plugins,
    MCP server deployments, API discovery files — lives under this directory.

    On first call, migrates any existing files from the old flat layout
    (``mca_preferences/``) to the new subfolder (``mca_preferences/MCAEditor/``).

    :return: Absolute path to ``~/Documents/mca_preferences/MCAEditor/``.
    :rtype: str
    """
    return _prefs_dir


# --- One-Time Migration from Flat Layout -----------------------------------
# MCA Editor files used to live directly in ~/Documents/mca_preferences/.
# Now they live in the MCAEditor/ subfolder so other MCA tools can coexist.
# This runs once at import time — moves known MCA Editor items if the new
# directory doesn't exist yet but the old flat layout does.

def _migrate_prefs_if_needed():
    """
    Migrate MCA Editor files from flat ``mca_preferences/`` to the new
    ``mca_preferences/MCAEditor/`` subfolder.

    Only runs if the new directory does NOT exist and the old layout DOES
    contain known MCA Editor files (``scripts/``, ``session.json``, etc.).
    Moves only MCA Editor items, leaving other MCA codebase files in place.
    """
    parent = os.path.dirname(_prefs_dir)  # ~/Documents/mca_preferences/

    # Skip if the new directory already exists — migration already done.
    if os.path.isdir(_prefs_dir):
        return

    # Skip if the parent doesn't exist — fresh install, nothing to migrate.
    if not os.path.isdir(parent):
        return

    # Known MCA Editor items in the old flat layout.
    # Directories and files that belong to MCA Editor (not the MCA codebase).
    _EDITOR_ITEMS = [
        "scripts",          # Session buffers and user scripts
        "plugins",          # User plugins
        "mcp_servers",      # MCP server deployment
        "session.json",     # Session state
        "output.log",       # Output panel log
        "api_port.json",    # Editor API discovery file
    ]

    # Also migrate versioned venv directories (.venv-3.10, .venv-3.11, etc.)
    venv_dirs = [
        d for d in os.listdir(parent)
        if d.startswith(".venv-") and os.path.isdir(os.path.join(parent, d))
    ]

    items_to_move = _EDITOR_ITEMS + venv_dirs

    # Check if ANY of our items exist in the old location.
    existing = [i for i in items_to_move if os.path.exists(os.path.join(parent, i))]
    if not existing:
        return

    # Create the new directory and move items.
    os.makedirs(_prefs_dir, exist_ok=True)

    import shutil
    for item in existing:
        src = os.path.join(parent, item)
        dst = os.path.join(_prefs_dir, item)
        try:
            shutil.move(src, dst)
        except Exception:
            # Non-fatal — file may be locked (e.g. venv in use).
            pass


# Run migration at import time (before any module reads from _prefs_dir).
_migrate_prefs_if_needed()


def ensure_on_path():
    """
    Ensure the MCA package root directory is on ``sys.path``.

    Something in the Maya environment occasionally removes the extraction
    directory from ``sys.path``, causing deferred imports of ``mca_core``
    and ``mca_qt`` to fail with ``ModuleNotFoundError``.  This function
    detects and re-adds the directory when needed.

    Safe to call repeatedly — no-ops if the path is already present.

    :return: True if the path was re-added, False if it was already present.
    :rtype: bool
    """
    if _package_root not in sys.path:
        sys.path.insert(0, _package_root)
        return True
    return False
