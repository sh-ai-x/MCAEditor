"""
MCA Editor - Cross-DCC Script IDE.

Supports Maya (with future expansion to Blender, Unreal, Unity, and more).

This is the top-level package. Import version and app metadata from here.
All core functionality has been moved to ``mca_core``; this package
re-exports for backward compatibility.

Dependencies:
    - PySide6 >= 6.5.0
"""

# --- Version & App Metadata -----------------------------------------------
# Re-export from mca_core so existing imports still work.

from mca_core import __version__, __app_name__, __org_name__, __org_domain__
