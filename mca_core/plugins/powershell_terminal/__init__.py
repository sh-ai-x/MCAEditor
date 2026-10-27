"""
MCA Core - PowerShell Terminal Plugin.

Bundled plugin that provides a minimal PowerShell panel in the right
sidebar: QProcess-backed, plain text in/out, no PTY or ANSI parsing.
See terminal_widget.py for why this stays deliberately simple.

Dependencies:
    - PySide6/PySide2 (via qt_compat)
    - mca_core.plugins (MCAPlugin base class)
"""

import logging

from mca_core.plugins import MCAPlugin

# Module-level logger.
logger = logging.getLogger(__name__)


class PowerShellTerminalPlugin(MCAPlugin):
    """
    PowerShell Terminal plugin for MCA Editor.

    Registers a right-panel PowerShell widget.
    """

    PLUGIN_ID = "com.mechart.powershell-terminal"
    PLUGIN_NAME = "PowerShell Terminal"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_AUTHOR = "MechArt Studios"
    PLUGIN_DESCRIPTION = "Run PowerShell commands from a right-sidebar panel."

    def activate(self, api):
        """
        Activate the PowerShell Terminal plugin.

        Creates the terminal widget and registers it in the right panel.

        :param MCAPluginAPI api: The plugin API for editor interaction.
        """
        self._api = api
        self._widget = None

        # Lazy import so this module doesn't fail if Qt isn't available
        # during plugin discovery/manifest scanning.
        try:
            from mca_core.plugins.powershell_terminal.terminal_widget import (
                PowerShellTerminalWidget,
            )
        except ImportError as exc:
            logger.warning("PowerShell Terminal plugin import failed: %s", exc)
            return

        self._widget = PowerShellTerminalWidget()
        api.add_panel("powershell-terminal", "PowerShell", self._widget)

        logger.info("PowerShell Terminal plugin activated")

    def deactivate(self):
        """
        Deactivate the PowerShell Terminal plugin.

        Kills the PowerShell child process and removes the panel.
        """
        if self._widget is not None:
            self._widget.cleanup()

        if hasattr(self, "_api") and self._api:
            self._api.remove_panel("powershell-terminal")

        self._widget = None
        self._api = None

        logger.info("PowerShell Terminal plugin deactivated")
