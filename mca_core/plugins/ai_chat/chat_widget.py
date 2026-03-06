"""
MCA Core - AI Chat Widget (Orange Slice Panel).

The main right-panel widget for the AI chat assistant.  Provides a
clean chat interface with streaming responses, tool use visualization,
code block detection, and provider settings.

Layout::

    +---------------------------------------+
    | [MCA logo] Orange Slice       [gear]  |
    +---------------------------------------+
    |                                       |
    |  Welcome / message area               |
    |                                       |
    +---------------------------------------+
    | Type a message...              [Send] |
    +---------------------------------------+

Build note:
    This file has ``keyPressEvent`` overrides (Enter to send) — must
    ship as ``.pyc`` (not ``.pyd``) due to the Shiboken enum crash.

Dependencies:
    - PySide6 (via qt_compat) — all Qt widgets
    - mca_qt.icons — MCA logo for Orange Slice branding
"""

import json
import logging
import os
import random
import re

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QScrollArea, QFrame, QComboBox, QLineEdit,
    Qt, Signal, QTimer, QSize, QMovie, QPixmap,
)

from mca_core.plugins.ai_chat.provider import (
    PROVIDERS, PROVIDER_IDS, create_client, get_provider_name, get_default_model,
)
from mca_core.plugins.ai_chat.system_prompt import build_system_prompt
from mca_core.plugins.ai_chat.chat_worker import ChatWorker
from mca_core.plugins.ai_chat.tool_handler import execute_tool

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Color Constants ---------------------------------------------------------

# Orange Slice brand color (matches MCA orange).
ORANGE_SLICE_COLOR = "#E8922A"

# User message accent color.
USER_COLOR = "#569cd6"

# Tool result background.
TOOL_BG = "#252526"

# Code block background.
CODE_BG = "#252526"

# --- Thinking GIF Paths ------------------------------------------------------
# Use mca_core's pre-computed package root — more reliable than __file__
# which can be wrong for .pyc files loaded from the extraction cache.
import mca_core
_GIFS_DIR = os.path.join(mca_core._package_root, "resources", "gifs")

# The two mascot GIFs — one is randomly chosen each time the AI starts thinking.
_THINKING_GIFS = [
    os.path.join(_GIFS_DIR, "Logo_InAndOut.gif"),
    os.path.join(_GIFS_DIR, "Logo_TailWaggle.gif"),
]

# Size for the thinking GIF (pixels).
_THINKING_GIF_SIZE = 48

# --- Bubble Style Constants --------------------------------------------------

# User bubble background — subtle dark blue tint.
USER_BUBBLE_BG = "#1a2332"

# Assistant bubble background — slightly lighter than main bg.
ASSISTANT_BUBBLE_BG = "#252526"

# Bubble border radius.
BUBBLE_RADIUS = 12

# Chat font — friendly and rounded, with fallbacks for all platforms.
CHAT_FONT = "Segoe UI, Helvetica Neue, Arial, sans-serif"

# Chat font size for prose text (px).
CHAT_FONT_SIZE = 13


# --- Markdown-to-HTML Helper ------------------------------------------------

def _markdown_to_html(text):
    """
    Convert lightweight Markdown to HTML for display in QLabel rich text.

    Handles the most common patterns the AI produces:
        - ``**bold**`` and ``__bold__``
        - ``*italic*`` and ``_italic_``
        - `` `inline code` ``
        - Unordered lists (``- item`` or ``* item``)
        - Numbered lists (``1. item``)
        - ``### headings``
        - Line breaks (double newline → paragraph, single → ``<br>``)

    Does NOT handle fenced code blocks — those are split out before
    this function is called.

    :param str text: Markdown-formatted prose text.
    :return: HTML string safe for QLabel rich text rendering.
    :rtype: str
    """
    import html as html_mod

    # Escape HTML entities first so user text can't inject tags.
    text = html_mod.escape(text)

    # --- Block-level processing (line by line) ---
    lines = text.split("\n")
    html_lines = []
    in_list = False  # Track whether we're inside a <ul> or <ol>.
    list_tag = ""

    for line in lines:
        stripped = line.strip()

        # Headings: ### Heading → <b style="...">Heading</b>
        heading_match = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            # Scale size by heading level.
            sizes = {1: 16, 2: 15, 3: 14, 4: 13}
            size = sizes.get(level, 13)
            # Close any open list before a heading.
            if in_list:
                html_lines.append("</{}>".format(list_tag))
                in_list = False
            html_lines.append(
                '<b style="font-size: {}px; color: #e0e0e0;">{}</b><br>'.format(
                    size, heading_text
                )
            )
            continue

        # Unordered list items: - item  or  * item
        ul_match = re.match(r"^[-*]\s+(.*)", stripped)
        if ul_match:
            if not in_list or list_tag != "ul":
                if in_list:
                    html_lines.append("</{}>".format(list_tag))
                html_lines.append("<ul style='margin: 2px 0; padding-left: 18px;'>")
                in_list = True
                list_tag = "ul"
            html_lines.append("<li>{}</li>".format(ul_match.group(1)))
            continue

        # Ordered list items: 1. item
        ol_match = re.match(r"^\d+\.\s+(.*)", stripped)
        if ol_match:
            if not in_list or list_tag != "ol":
                if in_list:
                    html_lines.append("</{}>".format(list_tag))
                html_lines.append("<ol style='margin: 2px 0; padding-left: 18px;'>")
                in_list = True
                list_tag = "ol"
            html_lines.append("<li>{}</li>".format(ol_match.group(1)))
            continue

        # Non-list line — close any open list.
        if in_list:
            html_lines.append("</{}>".format(list_tag))
            in_list = False

        # Empty line → paragraph break.
        if not stripped:
            html_lines.append("<br>")
        else:
            html_lines.append(stripped)

    # Close any trailing open list.
    if in_list:
        html_lines.append("</{}>".format(list_tag))

    result = "<br>".join(
        l for l in html_lines
        if not l.startswith(("<ul", "<ol", "<li", "</ul", "</ol"))
    )
    # Re-insert list blocks without <br> joining (they have their own spacing).
    # Simpler approach: just join all lines, lists already have block tags.
    result = "\n".join(html_lines)

    # --- Inline processing ---
    # Bold: **text** or __text__
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)
    result = re.sub(r"__(.+?)__", r"<b>\1</b>", result)

    # Italic: *text* or _text_ (but not inside words like file_name).
    result = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", result)
    result = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", result)

    # Inline code: `code`
    result = re.sub(
        r"`([^`]+?)`",
        r'<span style="background-color: #1e1e1e; color: #ce9178;'
        r' font-family: Consolas, monospace; font-size: 12px;'
        r' padding: 1px 4px; border-radius: 3px;">\1</span>',
        result,
    )

    return result


def _streaming_to_html(text):
    """
    Convert streaming text to HTML, handling partial code blocks.

    During streaming, a code block may be incomplete (opening ``` but no
    closing ```).  This function splits completed code blocks into styled
    ``<pre>`` tags and converts prose sections through ``_markdown_to_html``.
    An in-progress code block is rendered as a ``<pre>`` with a "..." hint.

    :param str text: The accumulated streaming text so far.
    :return: HTML string for QLabel rich text rendering.
    :rtype: str
    """
    # Split on complete fenced code blocks.
    parts = re.split(r"(```[\s\S]*?```)", text)

    # Check if there's an unclosed code block at the end.
    # If the number of ``` occurrences is odd, the last block is incomplete.
    fence_count = text.count("```")
    has_partial = (fence_count % 2 == 1)

    html_parts = []
    for i, part in enumerate(parts):
        if not part.strip():
            continue

        if part.startswith("```") and part.endswith("```") and len(part) > 6:
            # Complete fenced code block — render as styled <pre>.
            inner = part[3:-3]
            lines = inner.split("\n", 1)
            if len(lines) > 1 and lines[0].strip().isalpha():
                code = lines[1]
            else:
                code = inner

            import html as html_mod
            escaped = html_mod.escape(code.strip())
            html_parts.append(
                '<pre style="background-color: #1e1e1e; color: #d4d4d4;'
                ' font-family: Consolas, monospace; font-size: 12px;'
                ' padding: 8px; border-radius: 6px;'
                ' border: 1px solid #333333;">{}</pre>'.format(escaped)
            )
        elif has_partial and i == len(parts) - 1 and "```" in part:
            # Partial (unclosed) code block — show what we have so far.
            inner = part.split("```", 1)[1] if "```" in part else part
            import html as html_mod
            escaped = html_mod.escape(inner.strip())
            html_parts.append(
                '<pre style="background-color: #1e1e1e; color: #d4d4d4;'
                ' font-family: Consolas, monospace; font-size: 12px;'
                ' padding: 8px; border-radius: 6px;'
                ' border: 1px solid #333333;">{}</pre>'.format(escaped)
            )
        else:
            # Prose text — convert markdown to HTML.
            html_parts.append(_markdown_to_html(part.strip()))

    return "".join(html_parts)


# --- Stylesheet Fragments ---------------------------------------------------

_CHAT_AREA_STYLE = """
    QScrollArea {
        background-color: #1e1e1e;
        border: none;
    }
    QWidget#chatContainer {
        background-color: #1e1e1e;
    }
"""

_INPUT_STYLE = """
    QPlainTextEdit {{
        background-color: #252526;
        color: #cccccc;
        border: 1px solid #3e3e42;
        border-radius: 6px;
        padding: 8px;
        font-family: {font_family};
        font-size: {font_size}px;
    }}
    QPlainTextEdit:focus {{
        border-color: {accent};
    }}
"""

_SEND_BUTTON_STYLE = """
    QPushButton {{
        background-color: {accent};
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: bold;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: #d47f20;
    }}
    QPushButton:pressed {{
        background-color: #c07018;
    }}
    QPushButton:disabled {{
        background-color: #3e3e42;
        color: #666666;
    }}
"""

_SETTINGS_OVERLAY_STYLE = """
    QWidget#settingsOverlay {
        background-color: #1e1e1e;
        border: 1px solid #3e3e42;
        border-radius: 8px;
    }
    QLabel {
        color: #cccccc;
        font-size: 12px;
    }
    QComboBox {
        background-color: #252526;
        color: #cccccc;
        border: 1px solid #3e3e42;
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 24px;
    }
    QComboBox::drop-down {
        border: none;
    }
    QLineEdit {
        background-color: #252526;
        color: #cccccc;
        border: 1px solid #3e3e42;
        border-radius: 4px;
        padding: 4px 8px;
        min-height: 24px;
    }
    QPushButton {
        background-color: #333333;
        color: #cccccc;
        border: 1px solid #3e3e42;
        border-radius: 4px;
        padding: 6px 16px;
    }
    QPushButton:hover {
        background-color: #3e3e42;
    }
"""

# --- Suggestion Chip Lists ---------------------------------------------------
# Default chips shown when no Maya DCC is connected.
_DEFAULT_CHIPS = [
    "How do I select all meshes in Maya?",
    "Explain the current file",
    "Fix the error in the output panel",
]

# Maya helpdesk chips — 4 random picks shown when Maya is connected.
_MAYA_HELPDESK_CHIPS = [
    "How do I bind skin to a skeleton?",
    "Where is Paint Skin Weights?",
    "How do I set up an IK spine rig?",
    "What does the skinCluster node do?",
    "How do I bake animation to keyframes?",
    "Where are blend shape controls?",
]


_SUGGESTION_STYLE = """
    QPushButton {{
        background-color: #252526;
        color: #aaaaaa;
        border: 1px solid #3e3e42;
        border-radius: 12px;
        padding: 6px 14px;
        font-family: {font};
        font-size: 12px;
        text-align: left;
    }}
    QPushButton:hover {{
        background-color: #2d2d30;
        border-color: {accent};
        color: #cccccc;
    }}
"""


# =============================================================================
# Message Bubble Widgets
# =============================================================================

class MessageBubble(QFrame):
    """
    A messenger-style chat bubble for user or assistant messages.

    User bubbles are right-aligned with a blue tint.  Assistant bubbles
    are left-aligned with a neutral dark background.  Code blocks get
    monospace styling inside the bubble.

    :param str sender: Display name ("You" or "Orange Slice").
    :param str text: The message text (may contain ``` code blocks).
    :param str role: "user" or "assistant" for styling.
    """

    def __init__(self, sender, text, role="user", parent=None):
        """
        Initialize the message bubble.

        :param str sender: Sender display name.
        :param str text: Message content.
        :param str role: "user" or "assistant".
        :param QWidget parent: Parent widget.
        """
        super().__init__(parent)

        # Transparent outer frame — the bubble background is on the inner widget.
        self.setStyleSheet("MessageBubble { background: transparent; border: none; }")

        # Outer layout provides horizontal padding and alignment.
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(8, 4, 8, 4)
        outer_layout.setSpacing(0)

        # Choose alignment and colors based on role.
        if role == "user":
            bubble_bg = USER_BUBBLE_BG
            sender_color = USER_COLOR
            # Push bubble to the right with a left spacer.
            outer_layout.addSpacing(40)
        else:
            bubble_bg = ASSISTANT_BUBBLE_BG
            sender_color = ORANGE_SLICE_COLOR

        # The actual bubble container with rounded corners.
        bubble = QFrame()
        bubble.setStyleSheet(
            "QFrame {{"
            "  background-color: {bg};"
            "  border-radius: {r}px;"
            "  border: 1px solid #2d2d30;"
            "}}".format(bg=bubble_bg, r=BUBBLE_RADIUS)
        )

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        # Sender label with role-specific color.
        sender_label = QLabel(sender)
        sender_label.setStyleSheet(
            "QLabel {{ color: {c}; font-weight: bold; font-size: 11px;"
            " font-family: {font};"
            " background: transparent; border: none; }}".format(
                c=sender_color, font=CHAT_FONT
            )
        )
        bubble_layout.addWidget(sender_label)

        # Message content — parse code blocks for special styling.
        content_widget = self._build_content(text)
        bubble_layout.addWidget(content_widget)

        outer_layout.addWidget(bubble, 1)

        # User messages get right alignment via a spacer on the left (added above).
        # Assistant messages get a right spacer to push bubble left.
        if role != "user":
            outer_layout.addSpacing(40)

    def _build_content(self, text):
        """
        Build the content widget, splitting code blocks from prose.

        Fenced code blocks (```) get monospace styling with a dark
        background.  Prose text is converted from Markdown to HTML
        so bold, italic, inline code, and lists render properly.

        :param str text: Raw message text (may contain Markdown).
        :return: Widget containing the formatted message.
        :rtype: QWidget
        """
        container = QWidget()
        container.setStyleSheet("QWidget { background: transparent; border: none; }")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        # Split on fenced code blocks: ```lang\ncode\n```
        parts = re.split(r"(```[\s\S]*?```)", text)

        for part in parts:
            if not part.strip():
                continue

            if part.startswith("```") and part.endswith("```"):
                # Code block — strip the fences and optional language tag.
                inner = part[3:-3]
                # Remove leading language tag if present.
                lines = inner.split("\n", 1)
                if len(lines) > 1 and lines[0].strip().isalpha():
                    code = lines[1]
                else:
                    code = inner

                code_label = QLabel(code.strip())
                code_label.setWordWrap(True)
                code_label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                code_label.setStyleSheet(
                    "QLabel {{"
                    "  background-color: #1e1e1e;"
                    "  color: #d4d4d4;"
                    "  font-family: Consolas, monospace;"
                    "  font-size: 12px;"
                    "  padding: 8px;"
                    "  border-radius: 6px;"
                    "  border: 1px solid #333333;"
                    "}}"
                )
                layout.addWidget(code_label)
            else:
                # Prose text — convert Markdown to HTML for rich rendering.
                html_content = _markdown_to_html(part.strip())
                text_label = QLabel(html_content)
                text_label.setTextFormat(Qt.TextFormat.RichText)
                text_label.setWordWrap(True)
                text_label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                text_label.setStyleSheet(
                    "QLabel {{ color: #cccccc; font-size: {sz}px;"
                    " font-family: {font};"
                    " background: transparent; border: none; }}".format(
                        sz=CHAT_FONT_SIZE, font=CHAT_FONT
                    )
                )
                layout.addWidget(text_label)

        return container


class ToolCallBubble(QFrame):
    """
    A collapsed display for a tool call result in the message area.

    Shows the tool name and a truncated preview of the result.
    Clicking expands to show the full result.

    :param str tool_name: The name of the tool that was called.
    :param str result: The JSON result string.
    """

    def __init__(self, tool_name, result, parent=None):
        """
        Initialize the tool call bubble.

        :param str tool_name: Tool name.
        :param str result: JSON result string.
        :param QWidget parent: Parent widget.
        """
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(2)

        # Tool name label with icon indicator.
        header = QLabel("[tool: {}]".format(tool_name))
        header.setStyleSheet(
            "QLabel {{"
            "  color: #888888;"
            "  font-size: 11px;"
            "  font-style: italic;"
            "  background-color: %s;"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "}}" % TOOL_BG
        )
        layout.addWidget(header)

        # Truncated result preview.
        preview = result[:200] + "..." if len(result) > 200 else result
        result_label = QLabel(preview)
        result_label.setWordWrap(True)
        result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        result_label.setStyleSheet(
            "QLabel {{"
            "  color: #777777;"
            "  font-family: Consolas, monospace;"
            "  font-size: 11px;"
            "  background-color: %s;"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "}}" % TOOL_BG
        )
        result_label.setVisible(False)
        layout.addWidget(result_label)

        # Store for toggle.
        self._result_label = result_label
        self._header = header

        # Click header to toggle result visibility.
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda e: self._toggle_result()

    def _toggle_result(self):
        """Toggle the visibility of the full result text."""
        visible = self._result_label.isVisible()
        self._result_label.setVisible(not visible)


# =============================================================================
# Chat Input Widget (with Enter-to-send)
# =============================================================================

class ChatInput(QPlainTextEdit):
    """
    Text input for chat messages with Enter-to-send behavior.

    Enter sends the message, Shift+Enter inserts a newline.
    This class overrides ``keyPressEvent`` — must ship as ``.pyc``.

    Signals:
        send_requested(str): Emitted when the user presses Enter.
    """

    send_requested = Signal(str)

    def __init__(self, parent=None):
        """
        Initialize the chat input.

        :param QWidget parent: Parent widget.
        """
        super().__init__(parent)
        self.setPlaceholderText("Type a message...")
        # Enable word wrap so long lines don't scroll horizontally.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # Start at a single-line height, grow up to ~8 lines as the user types.
        self._min_height = 36
        self._max_height = 200
        self.setFixedHeight(self._min_height)
        self.textChanged.connect(self._adjust_height)

    def keyPressEvent(self, event):
        """
        Handle Enter key to send messages.

        Enter alone sends the message.  Shift+Enter inserts a newline.

        :param QKeyEvent event: The key press event.
        """
        # Enter without Shift sends the message.
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            text = self.toPlainText().strip()
            if text:
                self.send_requested.emit(text)
                self.clear()
                self.setFixedHeight(self._min_height)
            return

        # All other keys (including Shift+Enter) go through normal handling.
        super().keyPressEvent(event)

    def _adjust_height(self):
        """Auto-resize height based on content, up to max."""
        doc_height = self.document().size().height()
        # Add padding for the widget frame.
        new_height = int(min(max(doc_height + 16, self._min_height), self._max_height))
        self.setFixedHeight(new_height)


# =============================================================================
# Settings Overlay
# =============================================================================

class SettingsOverlay(QFrame):
    """
    Slide-in settings panel for provider/API key/model configuration.

    Shown when the user clicks the gear button in the header.
    Changes are applied immediately and persisted via settings.
    """

    # Emitted when the user changes provider settings.
    settings_changed = Signal()

    def __init__(self, api, parent=None):
        """
        Initialize the settings overlay.

        :param MCAPluginAPI api: Plugin API for reading/writing settings.
        :param QWidget parent: Parent widget.
        """
        super().__init__(parent)
        self._api = api
        self.setObjectName("settingsOverlay")
        self.setStyleSheet(_SETTINGS_OVERLAY_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # --- Title ---
        title = QLabel("AI Settings")
        title.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; color: #cccccc; }"
        )
        layout.addWidget(title)

        # --- Provider Picker ---
        layout.addWidget(QLabel("Provider:"))
        self._provider_combo = QComboBox()
        for pid in PROVIDER_IDS:
            self._provider_combo.addItem(get_provider_name(pid), pid)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self._provider_combo)

        # --- API Key ---
        layout.addWidget(QLabel("API Key:"))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("Enter your API key...")
        layout.addWidget(self._key_input)

        # --- Model ---
        layout.addWidget(QLabel("Model (optional override):"))
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("Leave blank for default")
        layout.addWidget(self._model_input)

        # --- Save Button ---
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_settings)
        save_btn.setStyleSheet(
            "QPushButton {{"
            "  background-color: {c}; color: #ffffff;"
            "  font-weight: bold; border-radius: 6px; padding: 8px;"
            "}} QPushButton:hover {{ background-color: #d47f20; }}".format(
                c=ORANGE_SLICE_COLOR
            )
        )
        layout.addWidget(save_btn)

        layout.addStretch()

        # Load current settings.
        self._load_settings()

    def _load_settings(self):
        """Load current AI settings into the UI controls."""
        provider = self._api.get_setting("ai_provider", "none")
        api_key = self._api.get_setting("ai_api_key", "")
        model = self._api.get_setting("ai_model", "")

        # Select the current provider in the combo box.
        for i in range(self._provider_combo.count()):
            if self._provider_combo.itemData(i) == provider:
                self._provider_combo.setCurrentIndex(i)
                break

        self._key_input.setText(api_key)
        self._model_input.setText(model)

    def _on_provider_changed(self, index):
        """
        Update the model placeholder when the provider changes.

        :param int index: New combo box index.
        """
        pid = self._provider_combo.itemData(index)
        if pid:
            default_model = get_default_model(pid)
            self._model_input.setPlaceholderText(
                "Default: {}".format(default_model) if default_model else "Enter model name"
            )

    def _save_settings(self):
        """Save the current settings and emit the changed signal."""
        pid = self._provider_combo.currentData()
        api_key = self._key_input.text().strip()
        model = self._model_input.text().strip()

        self._api.set_setting("ai_provider", pid)
        self._api.set_setting("ai_api_key", api_key)
        self._api.set_setting("ai_model", model)

        logger.info("AI settings saved: provider=%s, model=%s", pid, model or "(default)")
        self.settings_changed.emit()

        # Hide the overlay after saving.
        self.setVisible(False)


# =============================================================================
# Main Chat Widget
# =============================================================================

class AIChatWidget(QWidget):
    """
    Main chat panel widget for the Orange Slice AI assistant.

    Manages the full chat lifecycle: welcome screen, message display,
    streaming responses, tool call execution, and settings overlay.

    The widget layout:
        - Header with logo, title, and gear button
        - Scrollable message area (welcome screen or messages)
        - Input bar with text input and send button
    """

    def __init__(self, api, parent=None):
        """
        Initialize the chat widget.

        :param MCAPluginAPI api: Plugin API for editor interaction.
        :param QWidget parent: Parent widget.
        """
        super().__init__(parent)
        self._api = api
        self._worker = None       # Active ChatWorker thread.
        self._messages = []       # Conversation history for the API.
        self._current_text = ""   # Accumulator for streaming response.
        self._streaming_label = None  # Label being updated during streaming.
        self._pending_tool_calls = {}  # call_id -> (tool_name, args_json)
        self._thinking_gif_widget = None  # QLabel showing the animated mascot.
        self._thinking_movie = None       # QMovie driving the thinking GIF.

        self._setup_ui()

    def _setup_ui(self):
        """Build the complete widget layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        self._build_header(layout)

        # --- Chat Area (scroll area containing messages) ---
        self._build_chat_area(layout)

        # --- Welcome Screen (shown before first message) ---
        self._build_welcome_screen()

        # --- Input Bar ---
        self._build_input_bar(layout)

        # --- Settings Overlay (hidden by default) ---
        self._settings_overlay = SettingsOverlay(self._api, self)
        self._settings_overlay.setVisible(False)
        self._settings_overlay.settings_changed.connect(self._on_settings_changed)

    def _build_header(self, parent_layout):
        """
        Build the header bar with logo, title, and gear button.

        :param QVBoxLayout parent_layout: Layout to add the header to.
        """
        header = QFrame()
        header.setStyleSheet(
            "QFrame {{ background-color: #1e1e1e; border-bottom: 1px solid #2d2d30; }}"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)

        # MCA logo (small).
        try:
            from mca_qt.icons import mca_logo
            logo_icon = mca_logo(size=24)
            logo_label = QLabel()
            logo_label.setPixmap(logo_icon.pixmap(QSize(24, 24)))
            header_layout.addWidget(logo_label)
        except Exception:
            # Gracefully degrade if logo not available.
            pass

        # Title label.
        title = QLabel("Orange Slice")
        title.setStyleSheet(
            "QLabel {{ color: {}; font-size: 14px; font-weight: bold; }}".format(
                ORANGE_SLICE_COLOR
            )
        )
        header_layout.addWidget(title)

        header_layout.addStretch()

        # New chat button.
        new_chat_btn = QPushButton("New")
        new_chat_btn.setToolTip("Start a new conversation")
        new_chat_btn.setFixedSize(QSize(40, 28))
        new_chat_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #333333; color: #aaaaaa;"
            "  border: 1px solid #3e3e42; border-radius: 4px;"
            "  font-size: 11px;"
            "}"
            "QPushButton:hover { background-color: #3e3e42; }"
        )
        new_chat_btn.clicked.connect(self.new_chat)
        header_layout.addWidget(new_chat_btn)

        # Gear button for settings.
        gear_btn = QPushButton("⚙")
        gear_btn.setToolTip("AI Settings")
        gear_btn.setFixedSize(QSize(28, 28))
        gear_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: transparent; color: #888888;"
            "  border: none; font-size: 16px;"
            "}"
            "QPushButton:hover { color: #cccccc; }"
        )
        gear_btn.clicked.connect(self._toggle_settings)
        header_layout.addWidget(gear_btn)

        parent_layout.addWidget(header)

    def _build_chat_area(self, parent_layout):
        """
        Build the scrollable message area.

        :param QVBoxLayout parent_layout: Layout to add the area to.
        """
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet(_CHAT_AREA_STYLE)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Container widget inside the scroll area.
        self._chat_container = QWidget()
        self._chat_container.setObjectName("chatContainer")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(0, 0, 0, 0)
        self._chat_layout.setSpacing(0)
        self._chat_layout.addStretch()  # Push messages to the top initially.

        self._scroll_area.setWidget(self._chat_container)
        parent_layout.addWidget(self._scroll_area, 1)  # Stretch factor 1.

    def _build_welcome_screen(self):
        """Build the welcome screen with greeting and suggestion chips."""
        self._welcome_widget = QWidget()
        welcome_layout = QVBoxLayout(self._welcome_widget)
        welcome_layout.setContentsMargins(24, 40, 24, 24)
        welcome_layout.setSpacing(16)

        # Greeting text.
        greeting = QLabel(
            "Welcome! I'm Orange Slice,\n"
            "your MCA Editor assistant."
        )
        greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        greeting.setStyleSheet(
            "QLabel {{ color: {}; font-size: 16px; font-weight: bold;"
            " font-family: {}; }}".format(ORANGE_SLICE_COLOR, CHAT_FONT)
        )
        welcome_layout.addWidget(greeting)

        subtitle = QLabel(
            "I can help with scripting, code editing,\n"
            "and interacting with Maya."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            "QLabel {{ color: #888888; font-size: 12px; font-family: {}; }}".format(CHAT_FONT)
        )
        welcome_layout.addWidget(subtitle)

        welcome_layout.addSpacing(16)

        # Suggestion chips — pick helpdesk-flavored chips when Maya is connected.
        suggestions = self._pick_suggestion_chips()

        for suggestion in suggestions:
            btn = QPushButton(suggestion)
            btn.setStyleSheet(
                _SUGGESTION_STYLE.format(accent=ORANGE_SLICE_COLOR, font=CHAT_FONT)
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # Capture suggestion text in the lambda closure.
            btn.clicked.connect(
                lambda checked=False, s=suggestion: self._send_message(s)
            )
            welcome_layout.addWidget(btn)

        welcome_layout.addStretch()

        # Insert welcome screen before the stretch in the chat layout.
        self._chat_layout.insertWidget(0, self._welcome_widget)

    def _pick_suggestion_chips(self):
        """
        Choose suggestion chips based on the current DCC connection.

        When Maya is the connected DCC, picks 4 random helpdesk chips
        plus 2 default chips for variety.  Otherwise returns the 3
        default scripting-focused chips.

        :return: List of suggestion strings.
        :rtype: list
        """
        try:
            state = self._api.get_state()
            dcc_info = state.get("dcc", {}) or {}
            is_maya = (
                dcc_info.get("connected")
                and dcc_info.get("type", "").lower() == "maya"
            )
        except Exception:
            is_maya = False

        if is_maya:
            # Pick 4 random helpdesk chips + 2 random defaults for variety.
            helpdesk = random.sample(
                _MAYA_HELPDESK_CHIPS, min(4, len(_MAYA_HELPDESK_CHIPS))
            )
            defaults = random.sample(
                _DEFAULT_CHIPS, min(2, len(_DEFAULT_CHIPS))
            )
            return helpdesk + defaults

        return list(_DEFAULT_CHIPS)

    def _build_input_bar(self, parent_layout):
        """
        Build the input bar with text input and send button.

        :param QVBoxLayout parent_layout: Layout to add the bar to.
        """
        input_bar = QFrame()
        input_bar.setStyleSheet(
            "QFrame { background-color: #1e1e1e; border-top: 1px solid #2d2d30; }"
        )
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setSpacing(8)

        # Chat text input.
        self._input = ChatInput()
        self._input.setStyleSheet(
            _INPUT_STYLE.format(
                font_family=CHAT_FONT,
                font_size=CHAT_FONT_SIZE,
                accent=ORANGE_SLICE_COLOR,
            )
        )
        self._input.send_requested.connect(self._send_message)
        input_layout.addWidget(self._input, 1)

        # Send button.
        self._send_btn = QPushButton("Send")
        self._send_btn.setStyleSheet(
            _SEND_BUTTON_STYLE.format(accent=ORANGE_SLICE_COLOR)
        )
        self._send_btn.setFixedSize(QSize(60, 36))
        self._send_btn.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self._send_btn)

        parent_layout.addWidget(input_bar)

    # =========================================================================
    # Chat Actions
    # =========================================================================

    def new_chat(self):
        """Start a new conversation, clearing all messages."""
        # Stop any active worker.
        if self._worker is not None:
            self._worker.request_stop()
            self._worker = None

        # Clear conversation history and thinking state.
        self._messages = []
        self._current_text = ""
        self._streaming_label = None
        self._pending_tool_calls = {}
        self._thinking_gif_widget = None
        if self._thinking_movie is not None:
            self._thinking_movie.stop()
            self._thinking_movie = None

        # Clear all message widgets from the chat layout.
        # Keep the stretch at the end.
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Re-add the welcome screen.
        self._build_welcome_screen()

        # Re-enable input.
        self._set_input_enabled(True)
        self._input.setFocus()

        logger.info("Started new chat conversation")

    def _send_message(self, text):
        """
        Send a user message and start the AI response.

        :param str text: The user's message text.
        """
        if not text.strip():
            return

        # Hide welcome screen on first message.
        if self._welcome_widget is not None and self._welcome_widget.isVisible():
            self._welcome_widget.setVisible(False)

        # Add user message to the UI.
        self._add_message_bubble("You", text, "user")

        # Add to conversation history.
        self._messages.append({"role": "user", "content": text})

        # Disable input while processing.
        self._set_input_enabled(False)

        # Start the AI response.
        self._start_ai_response()

    def _on_send_clicked(self):
        """Handle send button click — extract text and send."""
        text = self._input.toPlainText().strip()
        if text:
            self._input.clear()
            self._input.setFixedHeight(36)
            self._send_message(text)

    def _start_ai_response(self):
        """
        Create and start the ChatWorker for an AI response.

        Builds the system prompt, creates the client, and launches
        the background thread.
        """
        # Get provider settings.
        provider_id = self._api.get_setting("ai_provider", "none")
        api_key = self._api.get_setting("ai_api_key", "")
        model_override = self._api.get_setting("ai_model", "")

        # Check that we have a valid provider and key.
        if provider_id == "none" or not api_key:
            self._add_message_bubble(
                "Orange Slice",
                "I need an API key to work! Click the gear icon above to "
                "configure your AI provider and API key.",
                "assistant",
            )
            self._set_input_enabled(True)
            return

        # Build system prompt with current editor context.
        system_prompt = build_system_prompt(self._api)

        # Prepare messages with system prompt.
        api_messages = [{"role": "system", "content": system_prompt}] + self._messages

        # Create the client.
        try:
            client, resolved_model = create_client(
                provider_id, api_key, model=model_override or None
            )
        except Exception as exc:
            self._add_message_bubble(
                "Orange Slice",
                "Failed to create AI client: {}".format(str(exc)),
                "assistant",
            )
            self._set_input_enabled(True)
            return

        # Prepare the streaming label for the response.
        self._current_text = ""
        self._streaming_label = self._add_streaming_bubble()

        # Create and connect the worker.
        self._worker = ChatWorker(client, resolved_model, api_messages, parent=self)
        self._worker.token_received.connect(self._on_token)
        self._worker.tool_call_requested.connect(self._on_tool_call)
        self._worker.response_complete.connect(self._on_response_complete)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    # =========================================================================
    # Worker Signal Handlers
    # =========================================================================

    def _on_token(self, token):
        """
        Handle a streaming text token from the worker.

        On the first token, hides the thinking GIF and reveals the
        streaming text label.  Converts accumulated text through the
        markdown-to-HTML pipeline so formatting renders live.

        :param str token: The text token to append.
        """
        self._current_text += token

        # On first token, swap the thinking GIF for the text label.
        if self._thinking_gif_widget is not None and self._thinking_gif_widget.isVisible():
            self._thinking_gif_widget.setVisible(False)
            # Stop the movie to free resources.
            if self._thinking_movie is not None:
                self._thinking_movie.stop()
                self._thinking_movie = None
            # Reveal the streaming text label.
            if self._streaming_label is not None:
                self._streaming_label.setVisible(True)

        # Update the streaming label with formatted HTML.
        if self._streaming_label is not None:
            html = _streaming_to_html(self._current_text)
            self._streaming_label.setText(html)
            self._streaming_label.adjustSize()

        # Auto-scroll to the bottom.
        self._scroll_to_bottom()

    def _on_tool_call(self, call_id, tool_name, arguments_json):
        """
        Handle a tool call request from the worker.

        Executes the tool on the main thread and provides the result
        back to the worker.

        :param str call_id: The tool call ID.
        :param str tool_name: The tool to execute.
        :param str arguments_json: JSON string of arguments.
        """
        logger.info("Tool call: %s (id=%s)", tool_name, call_id)

        # Show a tool call indicator in the UI.
        tool_bubble = ToolCallBubble(tool_name, "Executing...", parent=self._chat_container)
        self._chat_layout.insertWidget(
            self._chat_layout.count() - 1, tool_bubble
        )

        # Execute the tool on the main thread (safe for EditorAPI).
        result_json = execute_tool(self._api, tool_name, arguments_json)

        # Update the tool bubble with the result.
        tool_bubble._result_label.setText(result_json[:500])
        tool_bubble._header.setText("[tool: {} - done]".format(tool_name))

        # Provide the result back to the worker thread.
        if self._worker is not None:
            self._worker.provide_tool_result(call_id, result_json)

        self._scroll_to_bottom()

    def _on_response_complete(self, final_text):
        """
        Handle completion of the AI response.

        Finalizes the streaming message and re-enables input.

        :param str final_text: The complete assistant message text.
        """
        # Stop the thinking GIF if it's still running.
        if self._thinking_movie is not None:
            self._thinking_movie.stop()
            self._thinking_movie = None
        self._thinking_gif_widget = None

        # Replace the streaming label with a proper message bubble.
        if self._streaming_label is not None:
            # Remove the streaming container (walk up to the outermost frame).
            # The streaming label is inside bubble -> outer container.
            widget = self._streaming_label
            while widget and widget.parent() != self._chat_container:
                widget = widget.parent()
            if widget:
                idx = self._chat_layout.indexOf(widget)
                if idx >= 0:
                    item = self._chat_layout.takeAt(idx)
                    if item and item.widget():
                        item.widget().deleteLater()

        # Use the accumulated text (may differ from final_text if tools were used).
        display_text = self._current_text if self._current_text else final_text

        if display_text.strip():
            self._add_message_bubble("Orange Slice", display_text, "assistant")

            # Add assistant message to conversation history.
            self._messages.append({"role": "assistant", "content": display_text})

        # Reset streaming state.
        self._streaming_label = None
        self._current_text = ""
        self._set_input_enabled(True)
        self._input.setFocus()
        self._scroll_to_bottom()

    def _on_error(self, error_msg):
        """
        Handle an error from the worker.

        :param str error_msg: The error message.
        """
        logger.error("AI chat error: %s", error_msg)

        # Stop the thinking GIF if still running.
        if self._thinking_movie is not None:
            self._thinking_movie.stop()
            self._thinking_movie = None
        self._thinking_gif_widget = None

        # Remove the streaming bubble (it has the thinking GIF in it).
        if self._streaming_label is not None:
            widget = self._streaming_label
            while widget and widget.parent() != self._chat_container:
                widget = widget.parent()
            if widget:
                idx = self._chat_layout.indexOf(widget)
                if idx >= 0:
                    item = self._chat_layout.takeAt(idx)
                    if item and item.widget():
                        item.widget().deleteLater()
            self._streaming_label = None

        # Show the error in the chat.
        self._add_message_bubble(
            "Orange Slice",
            "An error occurred: {}".format(error_msg),
            "assistant",
        )
        self._set_input_enabled(True)
        self._input.setFocus()

    def _on_worker_finished(self):
        """Clean up worker reference when the thread finishes."""
        self._worker = None

    # =========================================================================
    # UI Helpers
    # =========================================================================

    def _add_message_bubble(self, sender, text, role):
        """
        Add a message bubble to the chat area.

        :param str sender: Sender display name.
        :param str text: Message text.
        :param str role: "user" or "assistant".
        """
        bubble = MessageBubble(sender, text, role, parent=self._chat_container)
        # Insert before the stretch at the end.
        self._chat_layout.insertWidget(
            self._chat_layout.count() - 1, bubble
        )
        self._scroll_to_bottom()

    def _add_streaming_bubble(self):
        """
        Add a streaming response placeholder with a thinking GIF.

        Shows an animated mascot GIF while waiting for the first token,
        then hides it once text starts arriving.  Returns the QLabel
        that will be updated with streaming tokens.

        :return: The label widget for streaming text updates.
        :rtype: QLabel
        """
        # Outer frame — transparent, provides alignment spacing.
        container = QFrame(parent=self._chat_container)
        container.setStyleSheet("QFrame { background: transparent; border: none; }")
        outer_layout = QHBoxLayout(container)
        outer_layout.setContentsMargins(8, 4, 8, 4)
        outer_layout.setSpacing(0)

        # Inner bubble with rounded corners (assistant style).
        bubble = QFrame()
        bubble.setStyleSheet(
            "QFrame {{"
            "  background-color: {bg};"
            "  border-radius: {r}px;"
            "  border: 1px solid #2d2d30;"
            "}}".format(bg=ASSISTANT_BUBBLE_BG, r=BUBBLE_RADIUS)
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        # Sender label.
        sender_label = QLabel("Orange Slice")
        sender_label.setStyleSheet(
            "QLabel {{ color: {c}; font-weight: bold; font-size: 11px;"
            " font-family: {font};"
            " background: transparent; border: none; }}".format(
                c=ORANGE_SLICE_COLOR, font=CHAT_FONT
            )
        )
        bubble_layout.addWidget(sender_label)

        # --- Thinking GIF indicator ---
        # Pick a random mascot GIF and display it while waiting for tokens.
        gif_widget = QLabel()
        gif_widget.setFixedSize(QSize(_THINKING_GIF_SIZE, _THINKING_GIF_SIZE))
        gif_widget.setStyleSheet("QLabel { background: transparent; border: none; }")

        # Try to load a random thinking GIF.
        gif_path = random.choice(_THINKING_GIFS)
        logger.debug("Thinking GIF path: %s (exists=%s)", gif_path, os.path.exists(gif_path))
        self._thinking_movie = None
        if os.path.exists(gif_path):
            movie = QMovie(gif_path)
            movie.setScaledSize(QSize(_THINKING_GIF_SIZE, _THINKING_GIF_SIZE))
            gif_widget.setMovie(movie)
            movie.start()
            # Keep a reference so we can stop it later.
            self._thinking_movie = movie
        else:
            # Fallback — just show a text indicator.
            gif_widget.setText("...")
            gif_widget.setStyleSheet(
                "QLabel {{ color: {}; font-size: 18px;"
                " background: transparent; border: none; }}".format(ORANGE_SLICE_COLOR)
            )

        bubble_layout.addWidget(gif_widget)
        self._thinking_gif_widget = gif_widget

        # Streaming text label (updated incrementally, hidden until first token).
        # Uses RichText so markdown formatting renders live during streaming.
        text_label = QLabel("")
        text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text_label.setStyleSheet(
            "QLabel {{ color: #cccccc; font-size: {sz}px;"
            " font-family: {font};"
            " background: transparent; border: none; }}".format(
                sz=CHAT_FONT_SIZE, font=CHAT_FONT
            )
        )
        text_label.setVisible(False)
        bubble_layout.addWidget(text_label)

        outer_layout.addWidget(bubble, 1)
        # Right spacer to push bubble left (assistant alignment).
        outer_layout.addSpacing(40)

        # Insert before the stretch.
        self._chat_layout.insertWidget(
            self._chat_layout.count() - 1, container
        )
        self._scroll_to_bottom()

        return text_label

    def _set_input_enabled(self, enabled):
        """
        Enable or disable the input controls.

        :param bool enabled: Whether input should be enabled.
        """
        self._input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)

        if not enabled:
            self._input.setPlaceholderText("Orange Slice is thinking...")
        else:
            self._input.setPlaceholderText("Type a message...")

    def _scroll_to_bottom(self):
        """Scroll the chat area to the bottom after adding content."""
        # Use a timer to let the layout settle before scrolling.
        QTimer.singleShot(10, self._do_scroll)

    def _do_scroll(self):
        """Perform the actual scroll (called from timer)."""
        vbar = self._scroll_area.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def _toggle_settings(self):
        """Toggle the settings overlay visibility."""
        visible = self._settings_overlay.isVisible()
        self._settings_overlay.setVisible(not visible)

        if not visible:
            # Position the overlay to fill the chat area.
            self._settings_overlay.setGeometry(self._scroll_area.geometry())
            self._settings_overlay.raise_()

    def _on_settings_changed(self):
        """Handle settings changes — could refresh provider info, etc."""
        logger.info("AI settings changed, ready for next conversation")

    def resizeEvent(self, event):
        """
        Handle widget resize to reposition the settings overlay.

        :param QResizeEvent event: The resize event.
        """
        super().resizeEvent(event)
        # Keep settings overlay aligned with the chat area.
        if self._settings_overlay.isVisible():
            self._settings_overlay.setGeometry(self._scroll_area.geometry())

    def cleanup(self):
        """
        Stop any active worker thread and release GIF resources.

        Called during plugin deactivation.
        """
        # Stop the thinking GIF animation.
        if self._thinking_movie is not None:
            self._thinking_movie.stop()
            self._thinking_movie = None

        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait(3000)  # Wait up to 3 seconds.
            self._worker = None
