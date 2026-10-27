"""
MCA Core - Terminal Plugin (PowerShell + WSL, native console embedding).

Bundled plugin that provides a single right-sidebar panel: a
PowerShell/WSL picker that swaps in a REAL Windows console window
reparented into the panel once a shell is chosen -- see
native_console_widget.py for why this is preferred over a custom
terminal emulator, and terminal_panel.py for why the console is only
created once the user picks a shell (not eagerly on activation).

Dependencies:
    - mca_core.plugins (MCAPlugin base class)
    - mca_core.plugins.powershell_terminal.terminal_panel
"""

import logging

from mca_core.plugins import MCAPlugin

# Module-level logger.
logger = logging.getLogger(__name__)


class TerminalPlugin(MCAPlugin):
    """
    Terminal plugin for MCA Editor: a PowerShell/WSL picker panel.
    """

    PLUGIN_ID = "com.mechart.powershell-terminal"
    PLUGIN_NAME = "Terminal"
    PLUGIN_VERSION = "2.1.0"
    PLUGIN_AUTHOR = "MechArt Studios"
    PLUGIN_DESCRIPTION = "Embedded PowerShell/WSL console, rooted at the editor's scripts folder."

    _PANEL_ID = "terminal"

    def activate(self, api):
        """
        Activate the Terminal plugin.

        Creates the picker panel and registers it as a right-panel tab.
        No shell process is started here -- that happens when the user
        picks one from the panel.

        :param MCAPluginAPI api: The plugin API for editor interaction.
        """
        self._api = api
        self._widget = None

        try:
            from mca_core.plugins.powershell_terminal.terminal_panel import (
                TerminalPanel,
            )
        except ImportError as exc:
            logger.warning("Terminal plugin import failed: %s", exc)
            return

        self._widget = TerminalPanel()
        api.add_panel(self._PANEL_ID, "Terminal", self._widget)

        logger.info("Terminal plugin activated")

    def deactivate(self):
        """
        Deactivate the Terminal plugin.

        Terminates the active console process (if any) and removes the panel.
        """
        if self._widget is not None:
            self._widget.cleanup()

        if hasattr(self, "_api") and self._api:
            self._api.remove_panel(self._PANEL_ID)

        self._widget = None
        self._api = None

        logger.info("Terminal plugin deactivated")
