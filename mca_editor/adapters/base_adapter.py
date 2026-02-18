"""
MCA Editor - DCC Adapter Base (backward-compat re-export).

All adapter functionality has moved to ``mca_core.adapters.base_adapter``.
This module re-exports for backward compatibility.
"""

from mca_core.adapters.base_adapter import DCCAdapter, DCCType, ConnectionState
