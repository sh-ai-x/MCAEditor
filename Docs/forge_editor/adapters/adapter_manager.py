"""
Forge Editor - DCC Adapter Manager
Manages multiple DCC connections, auto-detection, and routing.
"""

import subprocess
import platform
from typing import List, Dict, Optional, Callable

from .base_adapter import DCCAdapter, DCCType, ConnectionState
from .maya_adapter import MayaAdapter
from .blender_adapter import BlenderAdapter


class AdapterManager:
    """
    Manages DCC adapter instances and connections.
    
    Features:
    - Auto-detect running DCC applications
    - Maintain multiple simultaneous connections
    - Route execution to active DCC
    - Plugin API for adding custom adapters
    """
    
    def __init__(self):
        self._adapters: Dict[DCCType, DCCAdapter] = {}
        self._active_dcc: Optional[DCCType] = None
        self._on_connection_changed: Optional[Callable] = None
        self._custom_adapter_classes: Dict[str, type] = {}
        
        # Register built-in adapters
        self._register_builtin_adapters()
    
    def _register_builtin_adapters(self):
        """Register all built-in DCC adapters."""
        self._adapters[DCCType.MAYA] = MayaAdapter()
        self._adapters[DCCType.BLENDER] = BlenderAdapter()
        # Future: Unreal, Unity, Houdini, Nuke
    
    def set_connection_callback(self, callback: Callable):
        """Set callback for when connection state changes."""
        self._on_connection_changed = callback
        for adapter in self._adapters.values():
            adapter.set_state_callback(lambda state, a=adapter: self._handle_state_change(a, state))
    
    def _handle_state_change(self, adapter: DCCAdapter, state: ConnectionState):
        """Handle adapter state changes."""
        if state == ConnectionState.CONNECTED and self._active_dcc is None:
            self._active_dcc = adapter.dcc_type
        elif state == ConnectionState.DISCONNECTED and adapter.dcc_type == self._active_dcc:
            self._active_dcc = None
            # Fall back to another connected adapter
            for dcc_type, a in self._adapters.items():
                if a.is_connected:
                    self._active_dcc = dcc_type
                    break
        
        if self._on_connection_changed:
            self._on_connection_changed()
    
    # ---- Adapter Access ----
    
    def get_adapter(self, dcc_type: DCCType) -> Optional[DCCAdapter]:
        """Get a specific DCC adapter."""
        return self._adapters.get(dcc_type)
    
    def get_active_adapter(self) -> Optional[DCCAdapter]:
        """Get the currently active (selected) adapter."""
        if self._active_dcc:
            return self._adapters.get(self._active_dcc)
        return None
    
    def get_all_adapters(self) -> Dict[DCCType, DCCAdapter]:
        """Get all registered adapters."""
        return dict(self._adapters)
    
    def get_connected_adapters(self) -> List[DCCAdapter]:
        """Get all currently connected adapters."""
        return [a for a in self._adapters.values() if a.is_connected]
    
    @property
    def active_dcc(self) -> Optional[DCCType]:
        return self._active_dcc
    
    @active_dcc.setter
    def active_dcc(self, dcc_type: DCCType):
        """Set the active DCC (for multi-connection scenarios)."""
        if dcc_type in self._adapters:
            self._active_dcc = dcc_type
            if self._on_connection_changed:
                self._on_connection_changed()
    
    # ---- Connection ----
    
    def connect(self, dcc_type: DCCType, host: str = "localhost", port: int = None) -> bool:
        """Connect to a specific DCC."""
        adapter = self._adapters.get(dcc_type)
        if adapter:
            return adapter.connect(host, port)
        return False
    
    def disconnect(self, dcc_type: DCCType):
        """Disconnect from a specific DCC."""
        adapter = self._adapters.get(dcc_type)
        if adapter:
            adapter.disconnect()
    
    def disconnect_all(self):
        """Disconnect from all DCCs."""
        for adapter in self._adapters.values():
            if adapter.is_connected:
                adapter.disconnect()
    
    # ---- Execution ----
    
    def execute(self, code: str, language: str = None, dcc_type: DCCType = None) -> str:
        """
        Execute code in a DCC.
        If dcc_type is None, uses the active adapter.
        """
        adapter = self._adapters.get(dcc_type) if dcc_type else self.get_active_adapter()
        if not adapter:
            return "Error: No DCC connected"
        if not adapter.is_connected:
            return f"Error: Not connected to {adapter.display_name}"
        return adapter.execute(code, language)
    
    def execute_file(self, filepath: str, dcc_type: DCCType = None) -> str:
        """Execute a file in a DCC."""
        adapter = self._adapters.get(dcc_type) if dcc_type else self.get_active_adapter()
        if not adapter:
            return "Error: No DCC connected"
        if not adapter.is_connected:
            return f"Error: Not connected to {adapter.display_name}"
        return adapter.execute_file(filepath)
    
    # ---- Auto-detection ----
    
    def detect_running_dccs(self) -> List[Dict]:
        """
        Detect running DCC applications by scanning for known processes.
        Returns list of detected DCCs with connection info.
        """
        detected = []
        
        process_names = {
            DCCType.MAYA: ["maya", "maya.exe", "Maya"],
            DCCType.BLENDER: ["blender", "blender.exe", "Blender"],
            DCCType.UNREAL: ["UE4Editor", "UnrealEditor", "UnrealEditor.exe"],
            DCCType.UNITY: ["Unity", "Unity.exe"],
            DCCType.HOUDINI: ["houdini", "houdinifx", "houdini.exe"],
            DCCType.NUKE: ["Nuke", "Nuke.exe"],
        }
        
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                running = result.stdout.lower()
            else:
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True, text=True, timeout=5
                )
                running = result.stdout.lower()
            
            for dcc_type, names in process_names.items():
                for name in names:
                    if name.lower() in running:
                        adapter = self._adapters.get(dcc_type)
                        detected.append({
                            "type": dcc_type,
                            "name": adapter.display_name if adapter else dcc_type.value,
                            "port": adapter.default_port if adapter else 0,
                            "connected": adapter.is_connected if adapter else False,
                        })
                        break
        except Exception:
            pass
        
        return detected
    
    # ---- Plugin API ----
    
    def register_adapter(self, name: str, adapter_class: type):
        """
        Register a custom DCC adapter from a plugin.
        The class must inherit from DCCAdapter.
        """
        if not issubclass(adapter_class, DCCAdapter):
            raise TypeError(f"{adapter_class.__name__} must inherit from DCCAdapter")
        
        adapter = adapter_class()
        self._adapters[adapter.dcc_type] = adapter
        self._custom_adapter_classes[name] = adapter_class
        
        # Set up state callback
        if self._on_connection_changed:
            adapter.set_state_callback(
                lambda state, a=adapter: self._handle_state_change(a, state)
            )
