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

# --- Version & App Metadata -----------------------------------------------

# Semantic version for the application.
__version__ = "0.1.0"

# Display name shown in title bars and dialogs.
__app_name__ = "MCA Editor"

# Organization name used by QSettings for persistent storage.
__org_name__ = "MCATools"

# Organization domain used by QSettings.
__org_domain__ = "mcatools.dev"
