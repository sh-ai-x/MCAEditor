"""
MCA Editor - DCC Adapter Manager.

Manages multiple DCC adapter instances, handles connection routing,
auto-detection of running DCC processes, and plugin registration.

Only Maya is registered in the initial release. The architecture
supports adding Blender, Unreal, Unity, etc. via plugins or
future built-in adapters.

Dependencies:
    - subprocess (stdlib) - for process detection
    - platform (stdlib) - for OS-specific process listing
"""

import logging
import platform
import subprocess

from .base_adapter import DCCAdapter, DCCType, ConnectionState
from .maya_adapter import MayaAdapter

# Module-level logger for adapter management operations.
logger = logging.getLogger(__name__)


# --- Process Detection Constants --------------------------------------------

# Map of DCC types to their known process names for auto-detection.
# All types are listed for detection, even if only Maya has an adapter.
PROCESS_NAMES = {
    DCCType.MAYA: ["maya", "maya.exe", "Maya"],
    DCCType.BLENDER: ["blender", "blender.exe", "Blender"],
    DCCType.UNREAL: ["UE4Editor", "UnrealEditor", "UnrealEditor.exe"],
    DCCType.UNITY: ["Unity", "Unity.exe"],
    DCCType.HOUDINI: ["houdini", "houdinifx", "houdini.exe"],
    DCCType.NUKE: ["Nuke", "Nuke.exe"],
}

PROCESS_DETECT_TIMEOUT_SECS = 5  # Timeout for tasklist/ps commands


# --- Adapter Manager --------------------------------------------------------

class AdapterManager:
    """
    Manages DCC adapter instances and connections.

    Responsibilities:
        - Register and store adapter instances (Maya-only for now)
        - Route execution to the active DCC adapter
        - Auto-detect running DCC applications
        - Provide plugin API for registering custom adapters
        - Handle fallback when the active adapter disconnects
    """

    def __init__(self):
        """Initialize the adapter manager with built-in adapters."""
        self._adapters = {}
        self._active_dcc = None
        self._on_connection_changed = None
        self._custom_adapter_classes = {}

        # Register only Maya for the initial release.
        self._register_builtin_adapters()

    def _register_builtin_adapters(self):
        """Register all built-in DCC adapters (Maya-only for now)."""
        self._adapters[DCCType.MAYA] = MayaAdapter()
        # Future: self._adapters[DCCType.BLENDER] = BlenderAdapter()
        logger.debug("Registered built-in adapter: Maya")

    # --- Connection Callbacks ------------------------------------------------

    def set_connection_callback(self, callback):
        """
        Set callback for when any connection state changes.

        The callback is invoked with no arguments; the caller
        should query get_active_adapter() for current state.

        :param callable callback: Zero-argument callback function.
        """
        self._on_connection_changed = callback
        # Wire up state callbacks on all existing adapters.
        for adapter in self._adapters.values():
            adapter.set_state_callback(
                lambda state, a=adapter: self._handle_state_change(a, state)
            )

    def _handle_state_change(self, adapter, state):
        """
        Handle adapter state changes.

        Automatically promotes a newly-connected adapter to active,
        and falls back to another connected adapter if the active
        one disconnects.

        :param DCCAdapter adapter: The adapter whose state changed.
        :param ConnectionState state: The new connection state.
        """
        if state == ConnectionState.CONNECTED and self._active_dcc is None:
            # First connection becomes active.
            self._active_dcc = adapter.dcc_type
            logger.info("Active DCC set to %s", adapter.display_name)

        elif state == ConnectionState.DISCONNECTED and adapter.dcc_type == self._active_dcc:
            # Active adapter disconnected - try to fall back.
            self._active_dcc = None
            for dcc_type, candidate in self._adapters.items():
                if candidate.is_connected:
                    self._active_dcc = dcc_type
                    logger.info("Fell back to %s", candidate.display_name)
                    break

        # Notify the UI about the change.
        if self._on_connection_changed:
            self._on_connection_changed()

    # --- Adapter Access ------------------------------------------------------

    def get_adapter(self, dcc_type):
        """
        Get a specific DCC adapter by type.

        :param DCCType dcc_type: The DCC type to look up.
        :return: The adapter instance, or None if not registered.
        :rtype: DCCAdapter or None
        """
        return self._adapters.get(dcc_type)

    def get_active_adapter(self):
        """
        Get the currently active (selected) adapter.

        :return: The active adapter, or None if nothing is connected.
        :rtype: DCCAdapter or None
        """
        if self._active_dcc:
            return self._adapters.get(self._active_dcc)
        return None

    def get_all_adapters(self):
        """
        Get all registered adapters.

        :return: Dictionary mapping DCCType to adapter instance.
        :rtype: dict
        """
        return dict(self._adapters)

    def get_connected_adapters(self):
        """
        Get all currently connected adapters.

        :return: List of connected adapter instances.
        :rtype: list
        """
        return [a for a in self._adapters.values() if a.is_connected]

    @property
    def active_dcc(self):
        """
        The currently active DCC type.

        :rtype: DCCType or None
        """
        return self._active_dcc

    @active_dcc.setter
    def active_dcc(self, dcc_type):
        """
        Set the active DCC (for multi-connection scenarios).

        :param DCCType dcc_type: The DCC type to make active.
        """
        if dcc_type in self._adapters:
            self._active_dcc = dcc_type
            if self._on_connection_changed:
                self._on_connection_changed()

    # --- Connection ----------------------------------------------------------

    def connect(self, dcc_type, host="localhost", port=None):
        """
        Connect to a specific DCC application.

        :param DCCType dcc_type: The DCC type to connect to.
        :param str host: Hostname or IP address.
        :param int port: TCP port number.
        :return: True if connection was successful.
        :rtype: bool
        """
        adapter = self._adapters.get(dcc_type)
        if adapter:
            return adapter.connect(host, port)
        logger.warning("No adapter registered for %s", dcc_type)
        return False

    def disconnect(self, dcc_type):
        """
        Disconnect from a specific DCC application.

        :param DCCType dcc_type: The DCC type to disconnect from.
        """
        adapter = self._adapters.get(dcc_type)
        if adapter:
            adapter.disconnect()

    def disconnect_all(self):
        """Disconnect from all connected DCC applications."""
        for adapter in self._adapters.values():
            if adapter.is_connected:
                adapter.disconnect()

    # --- Execution -----------------------------------------------------------

    def execute(self, code, language=None, dcc_type=None):
        """
        Execute code in a DCC application.

        If *dcc_type* is None, routes to the active adapter.

        :param str code: Source code to execute.
        :param str language: Target language ('python', 'mel', etc.).
        :param DCCType dcc_type: Specific DCC to target (optional).
        :return: Output from the DCC.
        :rtype: str
        """
        adapter = self._adapters.get(dcc_type) if dcc_type else self.get_active_adapter()
        if not adapter:
            return "Error: No DCC connected"
        if not adapter.is_connected:
            return "Error: Not connected to {}".format(adapter.display_name)
        return adapter.execute(code, language)

    def execute_file(self, filepath, dcc_type=None):
        """
        Execute a script file in a DCC application.

        :param str filepath: Path to the script file.
        :param DCCType dcc_type: Specific DCC to target (optional).
        :return: Output from the DCC.
        :rtype: str
        """
        adapter = self._adapters.get(dcc_type) if dcc_type else self.get_active_adapter()
        if not adapter:
            return "Error: No DCC connected"
        if not adapter.is_connected:
            return "Error: Not connected to {}".format(adapter.display_name)
        return adapter.execute_file(filepath)

    # --- Auto-detection ------------------------------------------------------

    def detect_running_dccs(self):
        """
        Detect running DCC applications by scanning process lists.

        Scans for all known DCC process names, even those without
        adapters (useful for informational display).

        :return: List of dicts with 'type', 'name', 'port', 'connected'.
        :rtype: list
        """
        detected = []

        try:
            # Use platform-appropriate process listing command.
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True,
                    timeout=PROCESS_DETECT_TIMEOUT_SECS
                )
                running = result.stdout.lower()
            else:
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True, text=True,
                    timeout=PROCESS_DETECT_TIMEOUT_SECS
                )
                running = result.stdout.lower()

            # Check each DCC type's known process names.
            for dcc_type, names in PROCESS_NAMES.items():
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

        except Exception as exc:
            logger.warning("DCC auto-detection failed: %s", exc)

        return detected

    # --- Plugin API ----------------------------------------------------------

    def register_adapter(self, name, adapter_class):
        """
        Register a custom DCC adapter from a plugin.

        The class must inherit from DCCAdapter.

        :param str name: Unique name for the adapter registration.
        :param type adapter_class: Class that inherits from DCCAdapter.
        :raises TypeError: If adapter_class does not inherit from DCCAdapter.
        """
        if not issubclass(adapter_class, DCCAdapter):
            raise TypeError("{} must inherit from DCCAdapter".format(adapter_class.__name__))

        adapter = adapter_class()
        self._adapters[adapter.dcc_type] = adapter
        self._custom_adapter_classes[name] = adapter_class
        logger.info("Registered custom adapter: %s (%s)", name, adapter.display_name)

        # Wire up state callback if the connection callback is already set.
        if self._on_connection_changed:
            adapter.set_state_callback(
                lambda state, a=adapter: self._handle_state_change(a, state)
            )
