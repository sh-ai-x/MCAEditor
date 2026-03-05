"""
MCA Core - Hello World Plugin.

A minimal test plugin that verifies the plugin system is working
correctly.  Registers a right-panel tab with a greeting message
and a Plugins menu action that writes to the output panel.

Ships disabled by default (listed in ``disabled_plugins`` setting
on first run).  Enable via Plugins > Plugin Settings to test.

Dependencies:
    - PySide6 (QWidget, QLabel, QVBoxLayout)
    - mca_core.plugins (MCAPlugin base class)
"""

import logging

from mca_core.plugins import MCAPlugin

# Module-level logger.
logger = logging.getLogger(__name__)


class HelloWorldPlugin(MCAPlugin):
    """
    Minimal test plugin for the MCA Editor plugin system.

    Adds a simple right-panel tab and a menu action under Plugins.
    """

    PLUGIN_ID = "com.mechart.hello-world"
    PLUGIN_NAME = "Hello World"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_AUTHOR = "MechArt Studios"
    PLUGIN_DESCRIPTION = "Test plugin to verify the plugin system is working."

    def activate(self, api):
        """
        Activate the Hello World plugin.

        Creates a simple panel widget and registers it in the right
        panel, plus adds a menu action under Plugins > Hello World.

        :param MCAPluginAPI api: The plugin API for editor interaction.
        """
        self._api = api

        # Lazy import Qt widgets so this module doesn't fail if Qt
        # isn't available during discovery/manifest scanning.
        from mca_qt.qt_compat import QWidget, QLabel, QVBoxLayout, Qt

        # --- Build the panel widget ---
        self._panel = QWidget()
        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(16, 16, 16, 16)

        # Greeting label centered in the panel.
        label = QLabel("Hello from the plugin system!")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("""
            QLabel {
                color: #4ec9b0;
                font-size: 16px;
                font-weight: bold;
                padding: 20px;
            }
        """)
        layout.addWidget(label)

        # Subtitle with plugin info.
        info_label = QLabel(
            "Plugin: {}\n"
            "Version: {}\n\n"
            "This panel was registered by the Hello World plugin\n"
            "to verify the plugin system is working correctly.".format(
                self.PLUGIN_NAME, self.PLUGIN_VERSION
            )
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("""
            QLabel {
                color: #999999;
                font-size: 12px;
            }
        """)
        layout.addWidget(info_label)

        layout.addStretch()

        # --- Register the panel in the right sidebar ---
        api.add_panel("hello-world", "Hello World", self._panel)

        # --- Add a menu action ---
        api.add_menu_action("Hello World", "Say Hello", self._say_hello)

        logger.info("Hello World plugin activated")

    def deactivate(self):
        """
        Deactivate the Hello World plugin.

        Removes the panel and cleans up resources.
        """
        if hasattr(self, "_api") and self._api:
            self._api.remove_panel("hello-world")
        self._panel = None
        self._api = None
        logger.info("Hello World plugin deactivated")

    def _say_hello(self):
        """
        Menu action callback — writes a greeting to the output panel.

        Connected to Plugins > Hello World > Say Hello.
        """
        if self._api:
            self._api.write_output(
                "Hello from the Hello World plugin! The plugin system is working.",
                level="success"
            )
