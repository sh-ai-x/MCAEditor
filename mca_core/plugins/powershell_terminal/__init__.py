"""
MCA Core - Terminal Plugin (PowerShell + WSL, native console embedding).

Bundled plugin that provides two right-sidebar panels, each hosting a
REAL Windows console window reparented into the panel -- see
native_console_widget.py for why this is preferred over a custom
terminal emulator. Both start in the editor's scripts/ workspace
directory so the shell opens already "in" the editor's project.

Dependencies:
    - mca_core.plugins (MCAPlugin base class)
    - mca_core.plugins.powershell_terminal.native_console_widget
"""

import logging
import os

from mca_core import get_prefs_dir
from mca_core.plugins import MCAPlugin

# Module-level logger.
logger = logging.getLogger(__name__)


class TerminalPlugin(MCAPlugin):
    """
    Terminal plugin for MCA Editor: PowerShell and WSL panels.

    Registers two right-panel widgets, each a real embedded console.
    """

    PLUGIN_ID = "com.mechart.powershell-terminal"
    PLUGIN_NAME = "Terminal"
    PLUGIN_VERSION = "2.0.0"
    PLUGIN_AUTHOR = "MechArt Studios"
    PLUGIN_DESCRIPTION = "Embedded PowerShell and WSL consoles, rooted at the editor's scripts folder."

    # Panel ids, kept together so activate()/deactivate() stay in sync.
    _PANEL_IDS = ("powershell-terminal", "wsl-terminal")

    def activate(self, api):
        """
        Activate the Terminal plugin.

        Creates the PowerShell and WSL console widgets and registers
        them as right-panel tabs.

        :param MCAPluginAPI api: The plugin API for editor interaction.
        """
        self._api = api
        self._widgets = {}

        try:
            from mca_core.plugins.powershell_terminal.native_console_widget import (
                EmbeddedConsoleWidget,
            )
        except ImportError as exc:
            logger.warning("Terminal plugin import failed: %s", exc)
            return

        scripts_dir = os.path.join(get_prefs_dir(), "scripts")

        powershell_widget = EmbeddedConsoleWidget(
            ["powershell.exe", "-NoLogo", "-NoExit"],
            cwd=scripts_dir,
        )
        api.add_panel("powershell-terminal", "PowerShell", powershell_widget)
        self._widgets["powershell-terminal"] = powershell_widget

        wsl_widget = EmbeddedConsoleWidget(
            ["wsl.exe", "--cd", scripts_dir],
            cwd=scripts_dir,
        )
        api.add_panel("wsl-terminal", "WSL", wsl_widget)
        self._widgets["wsl-terminal"] = wsl_widget

        logger.info("Terminal plugin activated (PowerShell + WSL)")

    def deactivate(self):
        """
        Deactivate the Terminal plugin.

        Terminates both console child processes and removes the panels.
        """
        for panel_id, widget in self._widgets.items():
            widget.cleanup()
            if hasattr(self, "_api") and self._api:
                self._api.remove_panel(panel_id)

        self._widgets = {}
        self._api = None

        logger.info("Terminal plugin deactivated")
