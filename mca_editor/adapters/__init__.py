"""
MCA Editor - Adapters sub-package (backward-compat re-exports).

All adapter functionality has moved to ``mca_core.adapters``.
This module re-exports for backward compatibility.
"""

from mca_core.adapters.base_adapter import DCCAdapter, DCCType, ConnectionState
from mca_core.adapters.maya_adapter import MayaAdapter
from mca_core.adapters.adapter_manager import AdapterManager
