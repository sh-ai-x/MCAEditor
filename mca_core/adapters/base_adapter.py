"""
MCA Core - DCC Adapter Base.

Abstract base class for all Digital Content Creation application adapters.
Each DCC (Maya, Blender, Unreal, Unity, etc.) implements this interface
to provide connection management, code execution, and scene queries.

Dependencies:
    - None (pure Python ABC)
"""

import logging

from abc import ABC, abstractmethod
from enum import Enum

# Module-level logger for adapter operations.
logger = logging.getLogger(__name__)


# --- DCC Type Enum ----------------------------------------------------------

class DCCType(Enum):
    """
    Enumeration of supported DCC applications.

    All known DCC types are listed for extensibility, even though
    only MAYA has a concrete adapter in the initial release.
    """
    MAYA = "maya"
    BLENDER = "blender"        # Reserved for future support
    UNREAL = "unreal"          # Reserved for future support
    UNITY = "unity"            # Reserved for future support
    HOUDINI = "houdini"        # Reserved for future support
    NUKE = "nuke"              # Reserved for future support
    CUSTOM = "custom"          # For plugin-provided adapters


# --- Connection State Enum --------------------------------------------------

class ConnectionState(Enum):
    """
    Represents the lifecycle states of a DCC connection.

    DISCONNECTED -> CONNECTING -> CONNECTED
                                    |
                                  ERROR
    """
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# --- Abstract DCC Adapter ---------------------------------------------------

class DCCAdapter(ABC):
    """
    Abstract base class for DCC application adapters.

    Each adapter provides:
        - Connection management (connect/disconnect to a running DCC instance)
        - Code execution (send code to the DCC's interpreter)
        - Auto-complete data (fetch available commands, objects, properties)
        - Scene info (for AI context injection)
        - Language support info (what languages the DCC supports)

    Subclasses must implement all abstract properties and methods.
    """

    def __init__(self):
        """Initialize base adapter state and callback slots."""
        self._state = ConnectionState.DISCONNECTED
        # Optional callbacks for output, errors, and state changes.
        self._on_output = None
        self._on_error = None
        self._on_state_changed = None
        # Project paths injected separately from workspace paths.
        # These are added to sys.path with higher priority so project
        # modules take precedence over workspace site-packages.
        self._project_paths = []

    # --- Abstract Properties ------------------------------------------------

    @property
    @abstractmethod
    def dcc_type(self):
        """
        Return the DCC type this adapter connects to.

        :rtype: DCCType
        """
        pass

    @property
    @abstractmethod
    def display_name(self):
        """
        Human-readable name for this DCC application.

        :rtype: str
        """
        pass

    @property
    @abstractmethod
    def supported_languages(self):
        """
        List of scripting languages supported by this DCC.

        :rtype: list
        """
        pass

    @property
    @abstractmethod
    def default_port(self):
        """
        Default TCP port for connecting to this DCC.

        :rtype: int
        """
        pass

    # --- Connection State ---------------------------------------------------

    @property
    def state(self):
        """
        Current connection state.

        :rtype: ConnectionState
        """
        return self._state

    @state.setter
    def state(self, new_state):
        """
        Set the connection state and fire the callback if it changed.

        :param ConnectionState new_state: The new state to transition to.
        """
        old_state = self._state
        self._state = new_state
        if self._on_state_changed and old_state != new_state:
            logger.debug("%s state: %s -> %s", self.display_name, old_state.value, new_state.value)
            self._on_state_changed(new_state)

    @property
    def is_connected(self):
        """
        Check whether this adapter is currently connected.

        :rtype: bool
        """
        return self._state == ConnectionState.CONNECTED

    # --- Callbacks ----------------------------------------------------------

    def set_output_callback(self, callback):
        """
        Set callback for execution output messages.

        :param callable callback: Function accepting a single str argument.
        """
        self._on_output = callback

    def set_error_callback(self, callback):
        """
        Set callback for error messages.

        :param callable callback: Function accepting a single str argument.
        """
        self._on_error = callback

    def set_state_callback(self, callback):
        """
        Set callback for connection state changes.

        :param callable callback: Function accepting a ConnectionState argument.
        """
        self._on_state_changed = callback

    # --- Connection ---------------------------------------------------------

    @abstractmethod
    def connect(self, host="localhost", port=None):
        """
        Connect to a running DCC instance.

        :param str host: Hostname or IP address.
        :param int port: TCP port (uses default_port if None).
        :return: True if connection was successful.
        :rtype: bool
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from the DCC instance."""
        pass

    @abstractmethod
    def ping(self):
        """
        Check if the connection is still alive.

        :return: True if the DCC is responding.
        :rtype: bool
        """
        pass

    # --- Execution ----------------------------------------------------------

    @abstractmethod
    def execute(self, code, language=None):
        """
        Execute code in the DCC's interpreter.

        :param str code: The source code to execute.
        :param str language: Target language ('python', 'mel', etc.).
        :return: The output/result as a string.
        :rtype: str
        """
        pass

    @abstractmethod
    def execute_file(self, filepath):
        """
        Execute a script file in the DCC.

        :param str filepath: Absolute path to the script file.
        :return: The output/result as a string.
        :rtype: str
        """
        pass

    # --- Auto-complete ------------------------------------------------------

    @abstractmethod
    def get_completions(self, partial, language=None):
        """
        Get auto-complete suggestions from the DCC.

        :param str partial: Partial text to complete.
        :param str language: Target language for completions.
        :return: List of dicts with 'label', 'detail', 'insert_text'.
        :rtype: list
        """
        pass

    # --- Scene Context (for AI) ---------------------------------------------

    def get_scene_info(self):
        """
        Get current scene information for AI context injection.

        Override in subclasses for DCC-specific information (scene file,
        selected objects, active camera, etc.).

        :return: Dictionary of scene metadata.
        :rtype: dict
        """
        return {
            "dcc": self.display_name,
            "connected": self.is_connected,
        }

    def get_api_documentation(self, symbol):
        """
        Look up API documentation for a symbol in the DCC.

        Override in subclasses that support documentation lookup.

        :param str symbol: The API symbol to look up.
        :return: Documentation string, or None if unavailable.
        :rtype: str or None
        """
        return None

    # --- Project Paths ------------------------------------------------------

    def set_project_paths(self, paths):
        """
        Set project-specific paths to inject into ``sys.path``.

        These paths are added with higher priority than workspace paths
        so that project modules are importable from both the editor and
        the connected DCC application.

        :param list paths: List of absolute directory path strings.
        """
        self._project_paths = list(paths)
        logger.debug("Project paths set: %s", paths)

    def clear_project_paths(self):
        """
        Remove all project-specific paths.

        Subclasses that modify ``sys.path`` directly (e.g. the internal
        Maya adapter) should also remove the paths from ``sys.path``.
        """
        self._project_paths = []
        logger.debug("Project paths cleared")

    # --- MCP ----------------------------------------------------------------

    def get_mcp_server_info(self):
        """
        Return info about available MCP servers for this DCC.

        Override in subclasses that support Model Context Protocol servers.

        :return: Dictionary of MCP server metadata, or None.
        :rtype: dict or None
        """
        return None
