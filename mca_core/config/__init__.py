"""
MCA Core - Configuration sub-package.

Provides persistent settings management with a pluggable backend.
The default backend uses QSettings (via mca_qt), but in pure-Python
contexts (e.g. inside Maya without Qt), a dictionary-backed fallback
is available.
"""

from .settings import MCASettings, EditorMode
