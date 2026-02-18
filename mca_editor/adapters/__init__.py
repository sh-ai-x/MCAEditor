"""
MCA Editor - Adapters sub-package.

Provides DCC adapter base classes, the Maya adapter, and the
adapter manager for connection routing and lifecycle management.
"""

from .base_adapter import DCCAdapter, DCCType, ConnectionState
from .maya_adapter import MayaAdapter
from .adapter_manager import AdapterManager
