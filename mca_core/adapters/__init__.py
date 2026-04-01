"""
MCA Core - Adapters sub-package.

Provides DCC adapter base classes, the Maya TCP adapter, the Blender
TCP adapter, internal adapters (for embedded plugin mode), and the
adapter manager for connection routing and lifecycle management.
"""

from .base_adapter import DCCAdapter, DCCType, ConnectionState
from .maya_adapter import MayaAdapter
from .blender_adapter import BlenderAdapter
from .adapter_manager import AdapterManager
