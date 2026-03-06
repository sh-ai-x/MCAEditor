# Session Notes — 2026-03-05: Maya Helpdesk, UI Polish, Workspace Fix

## Overview

Major Orange Slice upgrade: Maya helpdesk (3-tier knowledge system), messenger-style chat bubbles with live markdown rendering, thinking GIF animation, and extensive Maya workspace control fixes.

## Version

`0.1.9` → `0.2.0`

---

## Changes

### 1. Orange Slice Maya Helpdesk (3-Tier System)

**Tier 1 — Embedded Knowledge** (`system_prompt.py`):
- Added `_MAYA_HELPDESK_BLOCK` (~90 lines) covering menu sets, key panels, workflow locations, selection modes, hotkeys, and answering strategy.
- Injected conditionally when `dcc_info["type"].lower() == "maya"` and connected.

**Tier 2 — Live `cmds.help()` Lookup** (`tools.py`, `tool_handler.py`):
- New `get_maya_command_help` tool schema and handler.
- Captures `cmds.help()` output via StringIO redirect in the live Maya session.
- Uses `repr()` for safe quoting of command names (prevents injection).

**Tier 3 — Web Search** (`tools.py`, `tool_handler.py`):
- New `search_maya_docs` tool schema and handler.
- DuckDuckGo Instant Answer API (zero dependencies, no API key).
- Scopes queries to `help.autodesk.com` and `area.autodesk.com`.

**Suggestion Chips** (`chat_widget.py`):
- `_DEFAULT_CHIPS` (3 scripting-focused) and `_MAYA_HELPDESK_CHIPS` (6 helpdesk-flavored).
- `_pick_suggestion_chips()` checks DCC state; Maya connected → 4 random helpdesk + 2 defaults.

### 2. Chat UI Overhaul (`chat_widget.py`)

**Messenger-Style Bubbles**:
- `MessageBubble` rewritten with rounded corners, alignment (user=right/blue, assistant=left/neutral).
- Outer transparent frame + inner styled bubble with sender label and content.

**Markdown Rendering**:
- `_markdown_to_html()` converts `**bold**`, `*italic*`, `` `inline code` ``, headings, bullet/numbered lists.
- `_streaming_to_html()` handles partial code blocks during streaming.
- Streaming label uses `Qt.TextFormat.RichText` so formatting renders live (not just on completion).
- Inline code gets orange syntax color (`#ce9178`) with dark background pill.

**Thinking GIF Animation**:
- Two mascot GIFs (`Logo_InAndOut.gif`, `Logo_TailWaggle.gif`) randomly chosen per response.
- `QMovie` drives animation at 48px; hidden on first token, replaced by streaming text.
- GIF path resolved via `mca_core._package_root` (more reliable than `__file__` for `.pyc`).

**Font & Colors**:
- Switched from Consolas to `Segoe UI` across entire chat panel (bubbles, input, welcome, chips).
- All purple-tinted colors replaced with VS Code dark palette (`#1e1e1e`, `#252526`, `#2d2d30`, `#333333`, `#3e3e42`).

**Input Box Growth**:
- Input box now grows from 36px to 200px (~8 lines) as user types.
- Word wrap enabled (`QPlainTextEdit.LineWrapMode.WidgetWidth`).

### 3. QMenu Crash Fix (`editor_panel.py`)

- `_is_menu_alive()` static method probes QMenu validity via `objectName()`.
- `_rebuild_plugins_menu()` walks parent chain to find valid QMenuBar, recreates Plugins menu.
- `_register_plugin_menu_action()` checks menu validity and rebuilds if dead.

### 4. Maya Workspace Control Fixes (`maya_window.py`)

**Problem**: Editor always opened docked right, ignored user's preferred position.

**Root cause journey**: Tried `floating=True`, `retain=False`, `evalDeferred(lowestPriority=True)`, deleting workspace control on exit — none worked because Maya's workspace system has multiple layers of state caching.

**Final solution**: Stop fighting Maya's workspace system.
- `show_mca_editor()`: If control exists and visible, just `restore` it (Maya remembers position). Otherwise create fresh with no `area=` or `floating=` (mixin defaults to floating).
- `_restore_mca_editor()`: Populate widget into whatever control Maya restored (docked, floating, wherever user left it).
- `cleanup_editor(maya_is_exiting=True)`: Hide + shiboken delete, but do NOT deleteUI — let Maya save the state.
- `cleanup_editor(maya_is_exiting=False)`: deleteUI for manual unload.
- `retain=True` (default) so Maya remembers position/size/dock state across sessions.

**Close flash fix**: `cmds.workspaceControl(name, e=True, visible=False)` before shiboken delete hides the control before the widget is destroyed.

### 5. Build & Resources

- `build_maya.py`: Added `resources/gifs` to `RESOURCE_DIRS`.
- `qt_compat.py`: Added `QMovie` import, `Qt.TextFormat` enum patch for PySide2.

---

## Files Modified

| File | Change |
|------|--------|
| `mca_core/__init__.py` | Version 0.1.9 → 0.2.0 |
| `mca_core/plugins/ai_chat/system_prompt.py` | Maya helpdesk knowledge block |
| `mca_core/plugins/ai_chat/tools.py` | 2 new tool schemas (16 → 18 tools) |
| `mca_core/plugins/ai_chat/tool_handler.py` | Handlers for maya help + web search |
| `mca_core/plugins/ai_chat/chat_widget.py` | Bubbles, markdown, GIF, font, input growth |
| `mca_qt/editor_panel.py` | QMenu crash recovery |
| `mca_qt/qt_compat.py` | QMovie import, TextFormat enum patch |
| `mca_maya/maya_window.py` | Workspace control: position memory, close flash |
| `build_maya.py` | GIF resources bundled |

## Key Lessons

- Maya's `workspaceControl` with `retain=True` caches dock state by control name. Setting `retain=False` prevents remembering. The right approach: leave `retain=True` and let Maya's system work.
- `_restore_mca_editor()` (uiScript) is the primary path for workspace restore on startup — it must cooperate with Maya's layout system, not fight it.
- Don't delete the workspace control on Maya exit if you want Maya to remember position.
- `QMovie` for GIF animation works well in QLabel; must keep reference alive.
- `.pyc` files' `__file__` can be unreliable in extraction caches; use `mca_core._package_root` instead.
