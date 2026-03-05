# Plan: Plugin System, AI Chat Panel & Marketplace Foundation

## Context

The MCA Editor has a working EditorAPI (28 methods), TCP JSON-RPC server
(localhost:7003+), and MCP integration. An existing plugin system skeleton
(`mca_editor/plugins/__init__.py`) has `MCAPlugin`, `MCAPluginAPI`, and
`PluginManager` — fully written but never wired into the app. The old AI
panel placeholder was removed from the right panel in a prior session.

This plan builds three things:

1. **Plugin System** — Wire up the dormant plugin infrastructure, update
   `MCAPluginAPI` to use the new `EditorAPI`, add panel hosting for plugins
2. **AI Chat Panel** — The first bundled plugin. Full chat UI with Anthropic
   API integration, tool use loop, Orange Slice mascot, dual auth model
   (own API key or MCA subscription)
3. **Marketplace Foundation** — Plugin manifest format, plugin settings UI,
   and the registry infrastructure for future third-party plugins

---

## Phase 1: Plugin System Wiring

### Goal

Activate the dormant plugin system so plugins can register panels, menu
items, and use the EditorAPI.

### Fix MCAPluginAPI (mca_editor/plugins/__init__.py)

The existing `MCAPluginAPI` points to the old `MCAMainWindow`. Rewrite to
wrap `EditorAPI`:

```
class MCAPluginAPI:
    def __init__(self, editor_api):
        self._api = editor_api
        self._panels = []       # track registered panels for cleanup
        self._menu_actions = []  # track registered menu actions
        self._panel_host = None  # set by editor_panel after init
```

**Plugin-specific methods (not on EditorAPI):**

- `add_panel(panel_id, title, widget, icon=None, location="right")` —
  Register a QWidget as a dockable panel. Location is "right", "bottom",
  or "sidebar". Returns bool.
- `remove_panel(panel_id)` — Remove a previously registered panel
- `add_menu_action(menu_path, label, callback, shortcut=None)` — Add item
  to the "Plugins" menu. menu_path supports submenus: "MyPlugin/Settings"
- `show_notification(message, level="info", duration=5000)` — Show a
  temporary notification in the status bar or output panel

**Delegated methods (pass through to EditorAPI):**

- `open_file(filepath)` → `self._api.open_file(filepath)`
- `save_file()` → `self._api.save_file()`
- `get_text()` → `self._api.get_text()`
- `set_text(text)` → `self._api.set_text(text)`
- `insert_text(text, line, col)` → `self._api.insert_text(text, line, col)`
- `replace_range(...)` → `self._api.replace_range(...)`
- `navigate_to(filepath, line)` → `self._api.navigate_to(filepath, line)`
- `execute_in_dcc(code, language)` → `self._api.execute_in_dcc(code, language)`
- `get_state()` → `self._api.get_state()`
- `get_output_text(max_lines)` → `self._api.get_output_text(max_lines)`
- `write_output(text, level)` → `self._api.write_output(text, level)`
- `get_setting(key, default)` → `self._api.get_setting(key, default)`
- `set_setting(key, value)` → `self._api.set_setting(key, value)`
- `get_project()` → `self._api.get_project()`
- `list_open_files()` → `self._api.list_open_files()`

**What plugins do NOT get access to:**

- No direct panel reference (no `self._panel`)
- No Qt internals (no splitter manipulation, no widget tree access)
- No settings that affect core editor behavior (font, theme, etc.)
- No filesystem operations outside the EditorAPI's read/write_disk_file

### MCAPlugin Base Class Update

Keep the existing ABC but clarify the interface:

```
class MCAPlugin(ABC):
    # --- Required ---
    PLUGIN_ID = ""       # unique identifier, e.g. "com.mechart.ai-chat"
    PLUGIN_NAME = ""     # display name
    PLUGIN_VERSION = ""  # semver string

    # --- Optional metadata ---
    PLUGIN_AUTHOR = ""
    PLUGIN_DESCRIPTION = ""
    PLUGIN_URL = ""

    @abstractmethod
    def activate(self, api):
        """Called when plugin loads. api is MCAPluginAPI instance."""

    @abstractmethod
    def deactivate(self):
        """Called when plugin unloads. Clean up panels, timers, etc."""
```

### PluginManager Update

- Discovery directory: `~/Documents/mca_preferences/plugins/`
- Each plugin is a folder with a `plugin.json` manifest + Python files
- Bundled plugins (AI Chat) live in `mca_core/plugins/` and are loaded first
- Load order: bundled plugins → user plugins (alphabetical)
- `PluginManager.load_all(api)` — discover, validate, instantiate, activate
- `PluginManager.unload_all()` — deactivate all in reverse order
- `PluginManager.get_plugin(plugin_id)` — return plugin instance or None
- `PluginManager.list_plugins()` — return list of {id, name, version, active, bundled}

### Plugin Manifest Format (plugin.json)

```json
{
    "id": "com.example.my-plugin",
    "name": "My Plugin",
    "version": "1.0.0",
    "author": "Developer Name",
    "description": "What this plugin does",
    "url": "https://example.com",
    "entry_point": "main.py",
    "min_editor_version": "0.1.0",
    "permissions": ["execute_in_dcc", "write_disk_file"],
    "dcc": ["maya", "all"]
}
```

The `permissions` field is informational for now (shown to user in plugin
settings). Enforcement can come later. The `dcc` field controls which
DCC environments the plugin appears in.

### Panel Host System (mca_qt/editor_panel.py)

Plugins need somewhere to put their panels. The layout needs to support
plugin panels without disrupting the existing UI.

**Right panel area** — Restore a right-side container for plugin panels:

```
_main_splitter
  |-- _sidebar
  |-- center_widget
  |     |-- _toolbar
  |     +-- _center_splitter (V)
  |           |-- _output
  |           |-- _group_container
  |           +-- _bottom_terminal_panel
  +-- _right_panel_container (NEW — QWidget with QVBoxLayout)
        |-- _right_tab_widget (QTabWidget — holds plugin panels + terminal)
```

The `_right_panel_container` replaces the old direct terminal placement.
The terminal panel moves into this tabbed container as one tab. Plugin
panels (like AI Chat) get their own tabs.

**Panel registration flow:**

1. Plugin calls `api.add_panel("ai-chat", "AI Chat", widget, icon, "right")`
2. MCAPluginAPI forwards to editor_panel's `_register_plugin_panel()`
3. Panel is added as a tab in `_right_tab_widget`
4. Right stripe gets a button for toggling the panel
5. Visibility state saved/restored per panel_id

**Bottom panel area** — Same pattern but for the bottom:

- `api.add_panel("my-panel", "Results", widget, icon, "bottom")` adds
  a tab alongside the terminal in the bottom area

**Sidebar panels:**

- `api.add_panel("my-tree", "Assets", widget, icon, "sidebar")` adds
  a collapsible section in the sidebar below existing panels

### Right Tool Stripe Updates (mca_qt/widgets/tool_stripe.py)

- AI Chat button added to right stripe (sparkle icon, already exists in icons.py)
- Terminal button stays at bottom of right stripe
- Plugin panels can register additional stripe buttons via `add_panel()`
- Active state highlight tracks which panel is currently visible

### Plugins Menu (mca_qt/editor_panel.py)

- Add "Plugins" top-level menu between "View" and "Help"
- Default items: "Plugin Settings..." (opens plugin manager dialog)
- Plugins can add items via `api.add_menu_action("Plugins/MyPlugin/...", ...)`

### Settings Keys

- `plugin_panel_{id}_visible` — per-plugin panel visibility (default False)
- `right_panel_active_tab` — which tab is active in right panel
- `disabled_plugins` — list of plugin IDs the user has disabled

### Panel Wiring (mca_qt/editor_panel.py)

At end of `__init__`, after register_panel and start_server:

```python
from mca_core.editor_api import get_api
from mca_editor.plugins import PluginManager, MCAPluginAPI

self._plugin_api = MCAPluginAPI(get_api())
self._plugin_api._panel_host = self  # for panel registration callbacks
self._plugin_manager = PluginManager()
self._plugin_manager.load_all(self._plugin_api)
```

In `cleanup()`:

```python
self._plugin_manager.unload_all()
```

### Files

| Action | File | What |
|--------|------|------|
| EDIT | mca_editor/plugins/__init__.py | Rewrite MCAPluginAPI, update PluginManager |
| EDIT | mca_qt/editor_panel.py | Add right panel container, plugin panel hosting, Plugins menu, PluginManager init |
| EDIT | mca_qt/widgets/tool_stripe.py | Support dynamic button registration from plugins |
| EDIT | mca_qt/widgets/sidebar.py | Add `add_plugin_panel(title, widget)` for sidebar-docked plugins |
| NEW | mca_qt/widgets/plugin_settings_dialog.py | Dialog to view/enable/disable plugins |

### Compilation Notes

- `mca_editor/plugins/__init__.py` has no Qt virtual method overrides → compiles to `.pyd`
- `plugin_settings_dialog.py` will have `keyPressEvent` override → add to `DIST_PYC_FILES`
- All other edits are to files already in the build pipeline

---

## Phase 2: AI Chat Panel (Bundled Plugin)

### Goal

Build the AI Chat as the first bundled plugin using only the public plugin
API. This validates the plugin system and becomes the subscription-tier
feature.

### Plugin Structure

```
mca_core/plugins/ai_chat/
    __init__.py          — MCAPlugin subclass
    plugin.json          — manifest
    chat_widget.py       — main chat panel QWidget
    chat_models.py       — message data models, conversation state
    api_client.py        — Anthropic API client (streaming)
    tool_handler.py      — maps tool calls to EditorAPI
    auth_manager.py      — API key / subscription auth
    system_prompt.py     — context-aware system prompt builder
    welcome_screen.py    — Orange Slice greeting widget
    message_renderer.py  — renders messages (markdown, code blocks, tool results)
```

### Plugin Entry Point (__init__.py)

```python
class AIChatPlugin(MCAPlugin):
    PLUGIN_ID = "com.mechart.ai-chat"
    PLUGIN_NAME = "MCA AI Chat"
    PLUGIN_VERSION = "0.1.0"
    PLUGIN_AUTHOR = "MeChart"
    PLUGIN_DESCRIPTION = "AI assistant for code editing and DCC interaction"

    def activate(self, api):
        self._api = api
        self._chat_widget = ChatWidget(api)
        api.add_panel("ai-chat", "AI Chat", self._chat_widget,
                      icon=None, location="right")

    def deactivate(self):
        if self._chat_widget:
            self._chat_widget.shutdown()
            self._chat_widget = None
```

### Orange Slice Welcome Screen (welcome_screen.py)

When the user first opens the AI Chat panel (or has no conversation
history), they see Orange Slice — the MCA mascot.

**Layout:**

```
┌─────────────────────────────────┐
│                                 │
│      [Orange Slice mascot]      │  ← mascot image (from resources/)
│                                 │
│   "Hi! I'm Orange Slice,       │
│    your MCA Editor assistant.   │
│    I can help you with:"        │
│                                 │
│   ┌───────────────────────┐     │
│   │ Write & debug code    │     │  ← clickable suggestion chips
│   └───────────────────────┘     │
│   ┌───────────────────────┐     │
│   │ Execute in Maya       │     │
│   └───────────────────────┘     │
│   ┌───────────────────────┐     │
│   │ Explain this file     │     │
│   └───────────────────────┘     │
│   ┌───────────────────────┐     │
│   │ Help with my project  │     │
│   └───────────────────────┘     │
│                                 │
│   ┌─────────────────────────┐   │
│   │ Set up API key...       │   │  ← if not authenticated
│   └─────────────────────────┘   │
│                                 │
└─────────────────────────────────┘
```

**Suggestion chips** — Clicking one populates the chat input with a
starter prompt. For example:

- "Write & debug code" → "Help me write a script that..."
- "Execute in Maya" → "Run this code in Maya: "
- "Explain this file" → sends get_text() content with "Explain this code"
- "Help with my project" → sends get_state() with "Here's my current project..."

**Mascot image** — User will provide the Orange Slice image. Store in
`resources/images/orange_slice.png`. The welcome screen scales it to
fit within 200x200px, centered.

### Chat Widget (chat_widget.py)

**Layout:**

```
┌─────────────────────────────────┐
│ [≡ Menu] MCA AI Chat  [⚙ Gear] │  ← header bar
├─────────────────────────────────┤
│                                 │
│  [message history - scrollable] │  ← QScrollArea with message bubbles
│                                 │
│  ┌─ Orange Slice ──────────┐    │
│  │ Here's the explanation  │    │
│  │ of your code...         │    │
│  │ ```python               │    │
│  │ def example():          │    │
│  │     pass                │    │
│  │ ```                     │    │
│  └─────────────────────────┘    │
│                                 │
│  ┌─ You ───────────────────┐    │
│  │ Explain the active file │    │
│  └─────────────────────────┘    │
│                                 │
├─────────────────────────────────┤
│ [+ Context] Type a message...   │  ← input area
│                             [→] │  ← send button
└─────────────────────────────────┘
```

**Header bar:**
- Hamburger menu: New Chat, Chat History, Clear Chat
- Gear icon: Opens auth/settings dialog

**Message area:**
- QScrollArea with vertical QVBoxLayout
- Auto-scroll to bottom on new messages
- User messages: right-aligned, subtle background
- Assistant messages: left-aligned, with Orange Slice mini avatar
- Tool use results: collapsible, showing what action was taken
- Code blocks: syntax highlighted (reuse existing PythonHighlighter),
  with "Copy" and "Insert in Editor" buttons
- Streaming: assistant messages render incrementally as tokens arrive

**Input area:**
- QPlainTextEdit (multi-line, grows up to 5 lines, then scrolls)
- Enter sends, Shift+Enter for newline
- "+" Context button: popup menu to attach context:
  - "Active file" — attaches full editor content
  - "Selected text" — attaches selection
  - "Output panel" — attaches recent output
  - "Editor state" — attaches get_state() snapshot
  - "File from disk..." — file picker to attach a file

**Keyboard shortcuts:**
- Ctrl+Shift+A — Toggle AI Chat panel visibility (global shortcut)
- Ctrl+L — Focus chat input (when panel is visible)
- Escape — Close chat panel

### Message Data Models (chat_models.py)

```python
class ChatMessage:
    role = ""        # "user", "assistant", "system"
    content = ""     # text content
    tool_calls = []  # list of ToolCall for assistant messages
    tool_results = []  # list of ToolResult for tool response messages
    timestamp = None
    tokens_used = 0  # track usage

class ToolCall:
    tool_name = ""
    arguments = {}
    call_id = ""

class ToolResult:
    call_id = ""
    result = None
    error = None

class Conversation:
    messages = []
    model = ""
    created_at = None
    title = ""       # auto-generated from first user message
```

### Anthropic API Client (api_client.py)

**Streaming client using the Anthropic Python SDK:**

- `anthropic` package installed in the MCA venv (via venv_manager)
- Streaming via `client.messages.stream()` (yields deltas)
- Runs in a QThread to avoid blocking the UI
- Emits signals: `token_received(str)`, `tool_use_requested(ToolCall)`,
  `message_complete(ChatMessage)`, `error_occurred(str)`

**API call flow:**

1. User sends a message
2. `system_prompt.py` builds the system prompt with current editor context
3. Messages list + tools definition sent to Anthropic API
4. Streaming response renders tokens as they arrive
5. If tool_use block received → pause streaming display, execute tool,
   append tool_result, resume with continuation request
6. Loop until assistant responds with no more tool calls

**Model selection:**

- Default: `claude-sonnet-4-5-20250929` (good balance of speed/quality)
- Setting: `ai_chat_model` — configurable in chat settings
- Show model name in header bar for transparency

**Error handling:**

- Rate limit → show "Rate limited, retrying in X seconds..."
- Auth error → show "Invalid API key" with link to settings
- Network error → show "Connection failed" with retry button
- Timeout → show "Request timed out" with retry button

### Tool Handler (tool_handler.py)

Maps Anthropic tool calls to EditorAPI methods. The tool definitions
sent to the API mirror the 15 MCP tools but execute in-process via
the plugin API (no TCP round-trip needed).

**Tool definitions (sent to Anthropic API):**

```python
TOOLS = [
    {
        "name": "get_editor_state",
        "description": "Get the current state of the MCA Editor including "
                       "active file, open tabs, cursor position, language, "
                       "project info, and connected DCC.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "open_file",
        "description": "Open a file in the editor or switch to its tab.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Absolute path to file"}
            },
            "required": ["filepath"]
        }
    },
    {
        "name": "get_editor_text",
        "description": "Get the full text content of the currently active "
                       "editor buffer.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "set_editor_text",
        "description": "Replace the entire content of the active editor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "New content"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "insert_text",
        "description": "Insert text at a specific line and column position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "line": {"type": "integer", "description": "1-based line number"},
                "col": {"type": "integer", "description": "1-based column"}
            },
            "required": ["text", "line", "col"]
        }
    },
    {
        "name": "replace_range",
        "description": "Replace text in a specific range (for surgical edits).",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_line": {"type": "integer"},
                "start_col": {"type": "integer"},
                "end_line": {"type": "integer"},
                "end_col": {"type": "integer"},
                "text": {"type": "string"}
            },
            "required": ["start_line", "start_col", "end_line", "end_col", "text"]
        }
    },
    {
        "name": "execute_in_dcc",
        "description": "Execute code in the connected DCC application (Maya). "
                       "Returns execution result with stdout capture.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {"type": "string", "enum": ["python", "mel"],
                             "description": "Language (default: python)"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "navigate_to",
        "description": "Open a file and jump to a specific line.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "line": {"type": "integer"}
            },
            "required": ["filepath", "line"]
        }
    },
    {
        "name": "list_open_files",
        "description": "List all open tabs in the editor with name, path, "
                       "language, and modified status.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "save_file",
        "description": "Save the currently active file.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "read_disk_file",
        "description": "Read a file from disk (bypasses editor buffer).",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"}
            },
            "required": ["filepath"]
        }
    },
    {
        "name": "write_disk_file",
        "description": "Write content to a file on disk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["filepath", "content"]
        }
    },
    {
        "name": "write_output",
        "description": "Write a message to the editor's output panel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "level": {"type": "string", "enum": ["info", "warning", "error", "success"]}
            },
            "required": ["text"]
        }
    },
    {
        "name": "get_output",
        "description": "Get recent text from the editor's output panel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_lines": {"type": "integer", "description": "Max lines (default 50)"}
            }
        }
    }
]
```

**Tool execution:**

```python
def execute_tool(api, tool_name, arguments):
    """
    Execute a tool call and return the result.
    Maps tool names to MCAPluginAPI methods.
    """
    dispatch = {
        "get_editor_state": lambda: api.get_state(),
        "open_file": lambda: api.open_file(arguments["filepath"]),
        "get_editor_text": lambda: api.get_text(),
        "set_editor_text": lambda: api.set_text(arguments["text"]),
        "insert_text": lambda: api.insert_text(
            arguments["text"], arguments["line"], arguments["col"]),
        "replace_range": lambda: api.replace_range(
            arguments["start_line"], arguments["start_col"],
            arguments["end_line"], arguments["end_col"],
            arguments["text"]),
        "execute_in_dcc": lambda: api.execute_in_dcc(
            arguments["code"], arguments.get("language", "python")),
        "navigate_to": lambda: api.navigate_to(
            arguments["filepath"], arguments["line"]),
        "list_open_files": lambda: api.list_open_files(),
        "save_file": lambda: api.save_file(),
        "read_disk_file": lambda: api.open_file(arguments["filepath"]),
        "write_disk_file": lambda: api.write_disk_file(
            arguments["filepath"], arguments["content"]),
        "write_output": lambda: api.write_output(
            arguments["text"], arguments.get("level", "info")),
        "get_output": lambda: api.get_output_text(
            arguments.get("max_lines", 50)),
    }
    handler = dispatch.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        result = handler()
        return result
    except Exception as e:
        return {"error": str(e)}
```

### Auth Manager (auth_manager.py)

Two authentication modes:

**Mode 1: Own API Key**
- User enters their Anthropic API key in the chat settings dialog
- Stored in MCASettings as `ai_api_key` (encrypted at rest — use the
  same approach as license key storage, or a simple keyring integration)
- API calls go directly to api.anthropic.com
- No MCA subscription required — this is free with the editor license
- Usage and billing is between the user and Anthropic

**Mode 2: MCA Subscription (Future)**
- User logs in with their MeChart account
- API calls proxy through your backend (api.mechart.org)
- Backend validates subscription status, forwards to Anthropic
- Usage limits based on subscription tier
- This requires the auth backend — leave as a UI option that says
  "Coming soon" until the backend is built

**Auth flow in chat_widget:**

1. User opens AI Chat for the first time → Welcome screen with
   "Set up API key..." button
2. Click opens AuthSettingsDialog:
   - Tab 1: "API Key" — paste your Anthropic key, test button
   - Tab 2: "MCA Subscription" — login fields (disabled/coming soon)
3. On successful auth, welcome screen transitions to chat interface
4. Key validation: make a minimal API call (list models or send a
   tiny message) to verify the key works

**Settings keys:**
- `ai_auth_mode` — "api_key" or "subscription" (default "api_key")
- `ai_api_key` — encrypted Anthropic API key
- `ai_subscription_token` — JWT token for MCA subscription (future)

### System Prompt Builder (system_prompt.py)

The system prompt is what makes this AI Chat valuable beyond generic
Claude. It automatically includes editor context so the AI knows what
the user is working on.

**System prompt structure:**

```
You are Orange Slice, the MCA Editor AI assistant. You help users write,
debug, and execute code in DCC applications like Maya.

You have access to tools that let you interact with the editor directly —
you can read files, make edits, execute code in Maya, and inspect the
editor state. Use these tools proactively when they would help the user.

## Current Context

{auto-injected from get_state()}

Active file: {path} ({language})
Cursor: line {line}, col {col}
Open files: {list}
Project: {name} at {root}
Connected DCC: {dcc_type} ({status})

## Guidelines

- When the user asks to edit code, use replace_range for surgical edits
  rather than replacing the entire file with set_editor_text
- When executing code in Maya, always use execute_in_dcc with the
  appropriate language
- If the user asks about their code, use get_editor_text to read it
  first — don't assume what's in the editor
- Show code changes clearly before applying them
- Be concise but thorough in explanations
```

**Context injection happens on every message send** — not once per
conversation. This ensures the AI always knows the current state.

### Message Renderer (message_renderer.py)

Renders message content as rich QWidgets within the scroll area.

**Supported content types:**

- Plain text → QLabel with word wrap
- Markdown paragraphs → QLabel with basic HTML rendering
- Code blocks → QPlainTextEdit (read-only) with syntax highlighting,
  "Copy" button, "Insert in Editor" button, "Run in DCC" button
  (for Python/MEL blocks)
- Tool use indicators → collapsible QFrame showing tool name, arguments,
  and result summary. Default collapsed. Color-coded: green for success,
  red for errors.
- Inline code → QLabel with monospace font and subtle background

**Streaming rendering:**
- Create the message widget on first token
- Append text as tokens arrive (update QLabel text)
- When a code block opens (```), switch to code block widget
- When a code block closes, switch back to text widget
- Finalize formatting on message_complete signal

### Chat History Persistence

Conversations saved to `~/Documents/mca_preferences/ai_chat/`:

```
ai_chat/
    conversations/
        {uuid}.json     — serialized Conversation objects
    index.json          — list of {id, title, date, message_count}
```

- Auto-save after each assistant response
- "Chat History" in hamburger menu shows a searchable list
- Clicking a conversation loads it into the chat
- "New Chat" starts fresh (keeps history)

### Anthropic SDK Dependency

The `anthropic` Python package needs to be installed in the MCA venv.

- Add to `venv_manager.py` requirements: `anthropic>=0.40.0`
- The venv is already set up for MCP dependencies — this piggybacks
- Import happens inside the ai_chat plugin, not at editor startup
- If import fails (venv not ready), show error in chat panel with
  "Install dependencies" button

### Compilation Notes

All files in `mca_core/plugins/ai_chat/` should compile to `.pyd`:
- `chat_widget.py` — has no Qt virtual overrides (uses composed widgets,
  not subclassed). If it needs eventFilter/keyPressEvent, add to PYC list.
- `welcome_screen.py` — pure layout, no overrides → `.pyd`
- `api_client.py` — QThread subclass with `run()` override → add to
  `DIST_PYC_FILES`
- `message_renderer.py` — may have paintEvent for custom rendering →
  evaluate during implementation, add to PYC if needed
- `tool_handler.py`, `auth_manager.py`, `system_prompt.py`,
  `chat_models.py` — pure Python, no Qt → `.pyd`

### Files

| Action | File | What |
|--------|------|------|
| NEW | mca_core/plugins/__init__.py | Package init |
| NEW | mca_core/plugins/ai_chat/__init__.py | AIChatPlugin class |
| NEW | mca_core/plugins/ai_chat/plugin.json | Plugin manifest |
| NEW | mca_core/plugins/ai_chat/chat_widget.py | Main chat panel UI |
| NEW | mca_core/plugins/ai_chat/chat_models.py | Message/Conversation models |
| NEW | mca_core/plugins/ai_chat/api_client.py | Anthropic streaming client |
| NEW | mca_core/plugins/ai_chat/tool_handler.py | Tool call → EditorAPI dispatch |
| NEW | mca_core/plugins/ai_chat/auth_manager.py | API key / subscription auth |
| NEW | mca_core/plugins/ai_chat/system_prompt.py | Context-aware prompt builder |
| NEW | mca_core/plugins/ai_chat/welcome_screen.py | Orange Slice greeting |
| NEW | mca_core/plugins/ai_chat/message_renderer.py | Rich message rendering |
| NEW | resources/images/orange_slice.png | Mascot image (provided by user) |
| EDIT | mca_core/venv_manager.py | Add anthropic to requirements |
| EDIT | build_maya.py | Add ai_chat files, handle PYC for api_client.py |

---

## Phase 3: Marketplace Foundation

### Goal

Build the infrastructure for third-party plugin distribution. This phase
is about the format, discovery, and management — not a full web store yet.

### Plugin Settings Dialog (mca_qt/widgets/plugin_settings_dialog.py)

Accessed via Plugins → Plugin Settings:

```
┌─────────────────────────────────────────────────┐
│ Plugin Settings                           [X]   │
├──────────────┬──────────────────────────────────┤
│              │                                  │
│ Bundled      │ MCA AI Chat           v0.1.0     │
│  ■ AI Chat   │ by MeChart                       │
│              │                                  │
│ Installed    │ AI assistant for code editing     │
│  (none)      │ and DCC interaction.              │
│              │                                  │
│              │ Status: Active ●                  │
│              │                                  │
│              │ [Disable]  [Settings]             │
│              │                                  │
│              ├──────────────────────────────────┤
│              │ Plugin Directory:                 │
│              │ ~/Documents/mca_preferences/      │
│              │ plugins/                           │
│              │ [Open Folder]  [Refresh]           │
│              │                                  │
│              │ ──────────────────────────────    │
│              │ Install from folder: [Browse...]  │
│              │                                  │
└──────────────┴──────────────────────────────────┘
```

**Left panel:** List of plugins grouped by Bundled / Installed
**Right panel:** Selected plugin details, enable/disable toggle, settings
**Bottom:** Plugin directory path, open folder button, manual install

### Plugin Install Flow (Local)

For now, plugins are installed by copying a folder into the plugins
directory. The dialog provides a "Browse..." button that copies a
selected folder into `~/Documents/mca_preferences/plugins/` and
triggers a reload.

Future: download from marketplace URL, verify signature, install.

### Plugin Developer Documentation

Create `docs/plugin_development.md` in the project:

- Plugin manifest format reference
- MCAPluginAPI method reference (auto-generated from docstrings)
- Panel registration guide with examples
- Tool integration guide (how to add AI tools)
- Sample plugin: a simple "word count" plugin that adds a sidebar
  panel showing stats about the current file
- Build and distribution guide

### Sample Plugin

Include a minimal sample plugin for developers:

```
mca_core/plugins/sample_word_count/
    __init__.py
    plugin.json
    word_count_panel.py
```

This ships disabled by default but shows up in Plugin Settings as
an example. Developers can use it as a template.

### Marketplace Website (Future — Not This Phase)

The eventual marketplace needs:
- Plugin listing page (name, description, author, price, screenshots)
- Developer portal (submit plugins, manage listings, view revenue)
- Download/install integration (editor calls marketplace API)
- Payment processing (Stripe Connect for developer payouts)
- Review/rating system
- Plugin signing (verify authenticity)

This is out of scope for the current implementation but the plugin
manifest format and local install flow are designed to be forward-
compatible with a web marketplace.

### Files

| Action | File | What |
|--------|------|------|
| NEW | mca_qt/widgets/plugin_settings_dialog.py | Plugin management UI |
| NEW | mca_core/plugins/sample_word_count/__init__.py | Sample plugin |
| NEW | mca_core/plugins/sample_word_count/plugin.json | Sample manifest |
| NEW | mca_core/plugins/sample_word_count/word_count_panel.py | Sample panel |
| NEW | docs/plugin_development.md | Developer documentation |

---

## Implementation Order

1. **Phase 1: Plugin System** — must be done first, AI Chat depends on it
2. **Phase 2: AI Chat Panel** — the main deliverable, validates Phase 1
3. **Phase 3: Marketplace Foundation** — settings UI and documentation

Within Phase 2, the implementation order should be:

1. chat_models.py — data structures first
2. auth_manager.py — needed before API calls work
3. api_client.py — Anthropic API integration
4. tool_handler.py — tool dispatch
5. system_prompt.py — context injection
6. welcome_screen.py — Orange Slice greeting
7. message_renderer.py — message display
8. chat_widget.py — ties everything together
9. __init__.py — plugin entry point (last, wires it all up)

---

## Verification

### Phase 1

1. Drop a test plugin folder into `~/Documents/mca_preferences/plugins/`
2. Restart editor — verify plugin appears in Plugins → Plugin Settings
3. Verify plugin's panel appears in the right panel area
4. Verify plugin's menu items appear under Plugins menu
5. Disable plugin in settings — verify panel and menu items removed

### Phase 2

1. Open AI Chat panel via right stripe button or Ctrl+Shift+A
2. See Orange Slice welcome screen with suggestion chips
3. Click gear → enter Anthropic API key → test succeeds
4. Type "What file am I editing?" → AI uses get_editor_state tool
5. Type "Add a print statement at line 5" → AI uses insert_text tool
6. Type "Run this in Maya: cmds.polySphere()" → AI uses execute_in_dcc
7. Verify streaming renders tokens incrementally
8. Verify tool use results are collapsible
9. Close and reopen editor — verify chat history persists
10. Verify the chat works with no API key set (shows auth prompt)

### Phase 3

1. Plugins → Plugin Settings shows all plugins
2. Disable AI Chat → panel disappears, re-enable → panel returns
3. "Open Folder" opens the plugins directory
4. Sample word count plugin can be enabled and shows its panel

---

## Build Notes

- All `mca_core/plugins/` files compile to `.pyd` except those with Qt
  virtual method overrides (add to `DIST_PYC_FILES` as identified)
- `plugin.json` manifests must be included in dist as-is (not compiled)
- `resources/images/orange_slice.png` added to resource copy in build_maya.py
- `anthropic` package is a venv dependency, not compiled into the editor
- The sample plugin ships as `.pyd`/`.pyc` + `plugin.json` in the dist
