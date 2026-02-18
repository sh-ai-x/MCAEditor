"""
MCA Editor - AI Panel.

Chat interface for AI assistant integration.
Supports BYOK (Bring Your Own Key) and managed AI connections.

This is a placeholder UI in the initial release. No real API calls
are made; the chat interface returns a stub response.

Dependencies:
    - PySide6 (QWidget, QStackedWidget, QScrollArea, etc.)

NOTE: Future tier/licensing hooks would gate managed AI behind
      a Pro subscription and limit BYOK to Standard+ tier.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QComboBox, QLineEdit, QStackedWidget,
    QScrollArea, QFrame, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QTimer

# Module-level logger for AI panel operations.
logger = logging.getLogger(__name__)


# =============================================================================
# Chat Message Widget
# =============================================================================

class AIChatMessage(QFrame):
    """
    Single chat message bubble in the AI panel.

    User messages get a dark gray background; assistant messages
    get a dark green background for visual distinction.

    :param str role: Either 'user' or 'assistant'.
    :param str content: The message text.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, role, content, parent=None):
        """
        Initialize the chat message widget.

        :param str role: Message role ('user' or 'assistant').
        :param str content: The message text to display.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._role = role

        # User messages are darker; assistant messages have a green tint.
        is_user = role == "user"
        bg_color = "#2d2d30" if is_user else "#1e3a1e"

        self.setStyleSheet(
            "QFrame {{ background-color: {}; border-radius: 8px;"
            " padding: 2px; margin: 2px 4px; }}".format(bg_color)
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        # Role label (You / AI Assistant).
        role_label = QLabel("You" if is_user else "AI Assistant")
        role_color = "#569cd6" if is_user else "#4ec9b0"
        role_label.setStyleSheet(
            "color: {}; font-size: 10px; font-weight: bold;".format(role_color)
        )
        layout.addWidget(role_label)

        # Message content.
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_label.setStyleSheet("color: #d4d4d4; font-size: 12px; padding: 2px 0px;")
        layout.addWidget(content_label)


# =============================================================================
# AI Panel
# =============================================================================

class AIPanel(QWidget):
    """
    AI integration panel with chat interface and configuration.

    Supports provider configuration (BYOK and managed), context
    injection toggles, and a placeholder chat interface.

    :param MCASettings settings: Application settings instance.
    :param QWidget parent: Optional parent widget.
    """

    # Emitted when AI generates code that should be inserted/executed.
    execute_code_requested = Signal(str)

    def __init__(self, settings, parent=None):
        """
        Initialize the AI panel.

        :param MCASettings settings: Application settings instance.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._settings = settings
        self._messages = []
        self._connected = False
        self._context = {}
        self._setup_ui()

    def _setup_ui(self):
        """Build the AI panel layout: header + stacked (settings/chat)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3f3f46;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)

        title = QLabel("AI ASSISTANT")
        title.setStyleSheet("color: #bbbbbb; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Connection status indicator.
        self._status_dot = QLabel("*")
        self._status_dot.setStyleSheet("color: #666666; font-size: 10px;")
        header_layout.addWidget(self._status_dot)

        self._status_label = QLabel("Not Connected")
        self._status_label.setStyleSheet("color: #666666; font-size: 10px;")
        header_layout.addWidget(self._status_label)

        # Settings toggle button.
        settings_btn = QPushButton("[=]")
        settings_btn.setFixedSize(26, 26)
        settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #969696; border: none; font-size: 14px;
            }
            QPushButton:hover { color: #ffffff; background-color: #3e3e42; }
        """)
        settings_btn.clicked.connect(self._toggle_settings)
        header_layout.addWidget(settings_btn)

        layout.addWidget(header)

        # Stacked widget: page 0 = settings, page 1 = chat.
        self._stack = QStackedWidget()

        self._settings_page = self._build_settings_page()
        self._stack.addWidget(self._settings_page)

        self._chat_page = self._build_chat_page()
        self._stack.addWidget(self._chat_page)

        # Start on the settings page so the user can configure first.
        self._stack.setCurrentIndex(0)
        layout.addWidget(self._stack)

    # --- Settings Page -------------------------------------------------------

    def _build_settings_page(self):
        """
        Build the AI configuration page.

        Contains provider selection, API key input, endpoint URL,
        model selection, context injection toggles, and MCP info.

        :return: The settings page widget.
        :rtype: QWidget
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --- Provider selection ---
        provider_label = QLabel("AI Provider")
        provider_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold;")
        layout.addWidget(provider_label)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems([
            "None (AI Disabled)",
            "BYOK: Anthropic (Claude)",
            "BYOK: OpenAI (GPT)",
            "BYOK: Local (Ollama / LM Studio)",
            "BYOK: Custom Endpoint",
            "MCA Pro AI (Subscription)",
        ])
        self._provider_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QComboBox:hover { border-color: #007acc; }
            QComboBox::drop-down { border: none; }
        """)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self._provider_combo)

        # --- API Key ---
        self._key_label = QLabel("API Key")
        self._key_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold;")
        layout.addWidget(self._key_label)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("Enter your API key...")
        self._key_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 12px;
            }
            QLineEdit:focus { border-color: #007acc; }
        """)
        layout.addWidget(self._key_input)

        # --- Endpoint URL (for custom/local providers) ---
        self._endpoint_label = QLabel("Endpoint URL")
        self._endpoint_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold;")
        layout.addWidget(self._endpoint_label)

        self._endpoint_input = QLineEdit()
        self._endpoint_input.setPlaceholderText("http://localhost:11434/v1")
        self._endpoint_input.setStyleSheet(self._key_input.styleSheet())
        layout.addWidget(self._endpoint_input)

        # --- Model selection ---
        self._model_label = QLabel("Model")
        self._model_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold;")
        layout.addWidget(self._model_label)

        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("claude-sonnet-4-5-20250514")
        self._model_input.setStyleSheet(self._key_input.styleSheet())
        layout.addWidget(self._model_input)

        # --- Context injection toggles ---
        context_label = QLabel("Context Injection")
        context_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold; margin-top: 8px;")
        layout.addWidget(context_label)

        self._ctx_scene = QCheckBox("Include DCC scene info")
        self._ctx_scene.setChecked(True)
        self._ctx_scene.setStyleSheet("color: #d4d4d4; font-size: 11px;")
        layout.addWidget(self._ctx_scene)

        self._ctx_output = QCheckBox("Include output/error context")
        self._ctx_output.setChecked(True)
        self._ctx_output.setStyleSheet("color: #d4d4d4; font-size: 11px;")
        layout.addWidget(self._ctx_output)

        self._ctx_file = QCheckBox("Include current file content")
        self._ctx_file.setChecked(True)
        self._ctx_file.setStyleSheet("color: #d4d4d4; font-size: 11px;")
        layout.addWidget(self._ctx_file)

        # --- MCP Connection info ---
        mcp_label = QLabel("MCP Connections")
        mcp_label.setStyleSheet("color: #cccccc; font-size: 12px; font-weight: bold; margin-top: 8px;")
        layout.addWidget(mcp_label)

        mcp_info = QLabel(
            "MCP servers provide AI with direct DCC scene access.\n"
            "Detected servers will appear here when connected."
        )
        mcp_info.setWordWrap(True)
        mcp_info.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(mcp_info)

        layout.addStretch()

        # --- Connect button ---
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedHeight(32)
        self._connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1a8ad4; }
            QPushButton:pressed { background-color: #005a9e; }
        """)
        self._connect_btn.clicked.connect(self._connect_ai)
        layout.addWidget(self._connect_btn)

        # Set initial visibility based on the default provider (None).
        self._on_provider_changed(0)
        return page

    # --- Chat Page -----------------------------------------------------------

    def _build_chat_page(self):
        """
        Build the chat interface page.

        Contains a scrollable message area, a text input, and send/insert
        buttons.

        :return: The chat page widget.
        :rtype: QWidget
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Chat messages area ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: #1e1e1e; border: none; }")

        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(4, 4, 4, 4)
        self._chat_layout.setSpacing(4)
        self._chat_layout.addStretch()

        scroll.setWidget(self._chat_container)
        self._chat_scroll = scroll
        layout.addWidget(scroll, stretch=1)

        # --- Input area ---
        input_container = QWidget()
        input_container.setStyleSheet("background-color: #252526; border-top: 1px solid #3f3f46;")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setSpacing(4)

        self._chat_input = QPlainTextEdit()
        self._chat_input.setMaximumHeight(80)
        self._chat_input.setPlaceholderText(
            "Ask AI about your code or DCC scene... (Enter to send, Shift+Enter for newline)"
        )
        self._chat_input.setStyleSheet("""
            QPlainTextEdit {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
            }
            QPlainTextEdit:focus { border-color: #007acc; }
        """)
        input_layout.addWidget(self._chat_input)

        # Button row: Insert Code + Send.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._insert_btn = QPushButton("Insert Code")
        self._insert_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #569cd6; border: 1px solid #569cd6;
                border-radius: 3px; padding: 3px 8px; font-size: 11px;
            }
            QPushButton:hover { background-color: #264f78; }
        """)
        btn_row.addWidget(self._insert_btn)

        btn_row.addStretch()

        send_btn = QPushButton("Send")
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc; color: white; border: none;
                border-radius: 3px; padding: 4px 12px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1a8ad4; }
        """)
        send_btn.clicked.connect(self._send_message)
        btn_row.addWidget(send_btn)

        input_layout.addLayout(btn_row)
        layout.addWidget(input_container)

        return page

    # --- Provider Change Handler ---------------------------------------------

    def _on_provider_changed(self, index):
        """
        Update UI visibility based on selected provider.

        Index mapping:
            0 = None, 1 = Claude, 2 = OpenAI, 3 = Local, 4 = Custom, 5 = Managed

        :param int index: The selected provider index.
        """
        is_none = index == 0
        needs_key = index in (1, 2)
        needs_endpoint = index in (3, 4)
        is_managed = index == 5

        self._key_label.setVisible(needs_key or is_managed)
        self._key_input.setVisible(needs_key or is_managed)
        self._endpoint_label.setVisible(needs_endpoint)
        self._endpoint_input.setVisible(needs_endpoint)
        self._model_label.setVisible(not is_none)
        self._model_input.setVisible(not is_none)
        self._connect_btn.setVisible(not is_none)

        # Update placeholder text based on provider.
        if is_managed:
            self._key_input.setPlaceholderText("Enter your MCA Pro subscription key...")
        elif index == 1:
            self._key_input.setPlaceholderText("sk-ant-...")
            self._model_input.setPlaceholderText("claude-sonnet-4-5-20250514")
        elif index == 2:
            self._key_input.setPlaceholderText("sk-...")
            self._model_input.setPlaceholderText("gpt-4o")
        elif index == 3:
            self._model_input.setPlaceholderText("codellama:13b")

    # --- AI Connection (Placeholder) -----------------------------------------

    def _connect_ai(self):
        """
        Attempt to connect to the selected AI provider.

        NOTE: This is a placeholder. In the real implementation, this
        would validate the API key and establish a connection.
        """
        self._connected = True
        self._status_dot.setStyleSheet("color: #4ec9b0; font-size: 10px;")
        self._status_label.setText("Connected")
        self._status_label.setStyleSheet("color: #4ec9b0; font-size: 10px;")
        # Switch to the chat view.
        self._stack.setCurrentIndex(1)
        logger.info("AI provider connected (placeholder)")

    def _toggle_settings(self):
        """Toggle between the settings and chat views."""
        current = self._stack.currentIndex()
        self._stack.setCurrentIndex(1 - current)

    # --- Chat Messaging (Placeholder) ----------------------------------------

    def _send_message(self):
        """
        Send a message to the AI.

        NOTE: This is a placeholder. The response is a stub message
        describing what the AI panel will do in the future.
        """
        text = self._chat_input.toPlainText().strip()
        if not text:
            return

        self._chat_input.clear()
        self._add_chat_message("user", text)

        # Placeholder response (real implementation would call AI API).
        QTimer.singleShot(500, lambda: self._add_chat_message(
            "assistant",
            "AI integration ready. Connect an API key to enable responses.\n\n"
            "This panel will provide:\n"
            "- Code generation & explanation\n"
            "- DCC scene queries via MCP\n"
            "- Error diagnosis from output\n"
            "- API documentation lookup"
        ))

    def _add_chat_message(self, role, content):
        """
        Add a message to the chat display.

        :param str role: Message role ('user' or 'assistant').
        :param str content: The message text.
        """
        self._messages.append({"role": role, "content": content})

        msg_widget = AIChatMessage(role, content)
        # Insert before the stretch at the bottom.
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, msg_widget)

        # Scroll to the bottom after a short delay to let layout settle.
        QTimer.singleShot(50, lambda: self._chat_scroll.verticalScrollBar().setValue(
            self._chat_scroll.verticalScrollBar().maximum()
        ))

    # --- Context Update ------------------------------------------------------

    def set_context(self, code="", output="", scene_info=None):
        """
        Update the context that will be sent with AI requests.

        :param str code: Current editor content.
        :param str output: Recent output window content.
        :param dict scene_info: DCC scene metadata.
        """
        self._context = {
            "code": code,
            "output": output,
            "scene_info": scene_info or {},
        }
