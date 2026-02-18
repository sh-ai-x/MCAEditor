"""
Forge Editor - DCC Adapter Base
Abstract base class for all Digital Content Creation application adapters.
Each DCC (Maya, Blender, Unreal, Unity) implements this interface.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Callable
from enum import Enum


class DCCType(Enum):
    MAYA = "maya"
    BLENDER = "blender"
    UNREAL = "unreal"
    UNITY = "unity"
    HOUDINI = "houdini"
    NUKE = "nuke"
    CUSTOM = "custom"


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class DCCAdapter(ABC):
    """
    Abstract base class for DCC application adapters.
    
    Each adapter provides:
    - Connection management (connect/disconnect to running DCC instance)
    - Code execution (send code to the DCC's interpreter)
    - Auto-complete data (fetch available commands, objects, properties)
    - Scene info (for AI context injection)
    - Language support info (what languages the DCC supports)
    """
    
    def __init__(self):
        self._state = ConnectionState.DISCONNECTED
        self._on_output: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_state_changed: Optional[Callable] = None
    
    # ---- Properties ----
    
    @property
    @abstractmethod
    def dcc_type(self) -> DCCType:
        """Return the DCC type this adapter connects to."""
        pass
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for this DCC."""
        pass
    
    @property
    @abstractmethod
    def supported_languages(self) -> List[str]:
        """List of scripting languages supported by this DCC."""
        pass
    
    @property
    @abstractmethod
    def default_port(self) -> int:
        """Default connection port for this DCC."""
        pass
    
    @property
    def state(self) -> ConnectionState:
        return self._state
    
    @state.setter
    def state(self, new_state: ConnectionState):
        old_state = self._state
        self._state = new_state
        if self._on_state_changed and old_state != new_state:
            self._on_state_changed(new_state)
    
    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED
    
    # ---- Callbacks ----
    
    def set_output_callback(self, callback: Callable[[str], None]):
        """Set callback for execution output."""
        self._on_output = callback
    
    def set_error_callback(self, callback: Callable[[str], None]):
        """Set callback for errors."""
        self._on_error = callback
    
    def set_state_callback(self, callback: Callable[[ConnectionState], None]):
        """Set callback for connection state changes."""
        self._on_state_changed = callback
    
    # ---- Connection ----
    
    @abstractmethod
    def connect(self, host: str = "localhost", port: int = None) -> bool:
        """
        Connect to a running DCC instance.
        Returns True if connection was successful.
        """
        pass
    
    @abstractmethod
    def disconnect(self):
        """Disconnect from the DCC instance."""
        pass
    
    @abstractmethod
    def ping(self) -> bool:
        """Check if the connection is still alive."""
        pass
    
    # ---- Execution ----
    
    @abstractmethod
    def execute(self, code: str, language: str = None) -> str:
        """
        Execute code in the DCC's interpreter.
        Returns the output/result as a string.
        """
        pass
    
    @abstractmethod
    def execute_file(self, filepath: str) -> str:
        """Execute a script file in the DCC."""
        pass
    
    # ---- Auto-complete ----
    
    @abstractmethod
    def get_completions(self, partial: str, language: str = None) -> List[Dict[str, str]]:
        """
        Get auto-complete suggestions.
        Returns list of dicts with 'label', 'detail', 'insert_text'.
        """
        pass
    
    # ---- Scene Context (for AI) ----
    
    def get_scene_info(self) -> Dict[str, Any]:
        """
        Get current scene information for AI context injection.
        Override in subclasses for DCC-specific info.
        """
        return {
            "dcc": self.display_name,
            "connected": self.is_connected,
        }
    
    def get_api_documentation(self, symbol: str) -> Optional[str]:
        """Look up API documentation for a symbol. Override per DCC."""
        return None
    
    # ---- MCP ----
    
    def get_mcp_server_info(self) -> Optional[Dict[str, Any]]:
        """
        Return info about available MCP servers for this DCC.
        Override in subclasses that support MCP.
        """
        return None
