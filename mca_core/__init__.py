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
__version__ = "0.1.2"

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
