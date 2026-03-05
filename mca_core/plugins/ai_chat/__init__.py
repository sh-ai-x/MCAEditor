"""
MCA Core - Orange Slice AI Chat Plugin.

Bundled plugin that provides an AI assistant panel in the right sidebar.
Supports Claude (Anthropic), OpenAI, and Google Gemini through their
OpenAI-compatible endpoints.  The assistant has full tool use access
to read/write files, execute code in Maya, navigate, and inspect
the editor state.

Ships enabled by default.  Users configure their provider and API key
through the in-panel settings gear.

Dependencies:
    - openai >= 1.30.0 (from managed venv)
    - PySide6 (via qt_compat)
    - mca_core.plugins (MCAPlugin base class)
"""

import logging

from mca_core.plugins import MCAPlugin

# Module-level logger.
logger = logging.getLogger(__name__)


class AIChatPlugin(MCAPlugin):
    """
    Orange Slice AI Chat plugin for MCA Editor.

    Registers a right-panel chat widget and menu actions under
    Plugins > Orange Slice.
    """

    PLUGIN_ID = "com.mechart.ai-chat"
    PLUGIN_NAME = "Orange Slice AI"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_AUTHOR = "MechArt Studios"
    PLUGIN_DESCRIPTION = "AI assistant with full editor and Maya integration."

    def activate(self, api):
        """
        Activate the Orange Slice AI plugin.

        Creates the chat widget and registers it in the right panel.
        Adds menu actions under Plugins > Orange Slice.

        :param MCAPluginAPI api: The plugin API for editor interaction.
        """
        self._api = api
        self._widget = None

        # Lazy import the chat widget so this module doesn't fail if Qt
        # or openai aren't available during discovery/manifest scanning.
        try:
            from mca_core.plugins.ai_chat.chat_widget import AIChatWidget
        except ImportError as exc:
            logger.warning("AI Chat plugin import failed: %s", exc)
            return

        # Create the chat widget.
        self._widget = AIChatWidget(api)

        # Register the panel in the right sidebar.
        api.add_panel("ai-chat", "Orange Slice", self._widget)

        # Register menu actions under Plugins > Orange Slice.
        api.add_menu_action("Orange Slice", "New Chat", self._new_chat)
        api.add_menu_action("Orange Slice", "Settings", self._show_settings)

        logger.info("Orange Slice AI plugin activated")

    def deactivate(self):
        """
        Deactivate the Orange Slice AI plugin.

        Stops any active worker thread and removes the panel.
        """
        # Clean up the worker thread.
        if self._widget is not None:
            self._widget.cleanup()

        # Remove the panel from the sidebar.
        if hasattr(self, "_api") and self._api:
            self._api.remove_panel("ai-chat")

        self._widget = None
        self._api = None

        logger.info("Orange Slice AI plugin deactivated")

    def _new_chat(self):
        """
        Menu action callback — starts a new conversation.

        Connected to Plugins > Orange Slice > New Chat.
        """
        if self._widget:
            self._widget.new_chat()

    def _show_settings(self):
        """
        Menu action callback — toggles the settings overlay.

        Connected to Plugins > Orange Slice > Settings.
        """
        if self._widget:
            self._widget._toggle_settings()
