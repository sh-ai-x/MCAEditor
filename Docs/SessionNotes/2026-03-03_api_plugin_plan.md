# MCA Editor API & Plugin System — Implementation Plan

**Date:** 2026-03-03
**Status:** Approved, not yet started

## Context
The MCA Editor needs a public API layer so that:
1. **AI agents** (Claude Code via MCP) can read/write files, see output, access settings, and control the editor
2. **Third-party developers** can create plugins that extend the editor with custom panels, menu items, adapters, and tools

An existing plugin system (`mca_editor/plugins/__init__.py`) has `MCAPlugin`, `MCAPluginAPI`, and `PluginManager` — fully written but never wired into the app. The `MCAPluginAPI` points to the old prototype `MCAMainWindow` instead of the current `MCAEditorPanel`.

The MCP server (`mca_core/mcp_maya_server.py`) runs as a separate process and currently only has Maya scene tools — no editor tools. IPC between the MCP server and the editor will use TCP JSON-RPC on localhost port 7003 (same pattern as Maya command ports 7001/7002).

---

## Phase 1: EditorAPI Core
**Goal:** Create the public API class that wraps the panel's private methods.

**New file:** `mca_core/editor_api.py`
- Pure Python, zero Qt imports — delegates everything to the panel
- Module-level `register_panel(panel)` / `get_api()` singleton pattern
- `EditorAPI` class with methods grouped by domain:

**File Operations:**
- `open_file(filepath)` — open a file in the editor
- `save_current_file()` — save the active tab
- `save_all_files()` — save all open tabs
- `close_current_tab()` — close the active tab
- `list_open_files()` — returns list of dicts `{path, name, language, modified}`
- `get_active_file_path()` — returns str or None
- `read_file(filepath)` — read any file from disk
- `write_file(filepath, content)` — write content to disk

**Editor Content:**
- `get_editor_text()` — full text of active editor
- `set_editor_text(text)` — replace active editor content
- `get_selected_text()` — current selection
- `get_cursor_position()` — returns `{line, col}`
- `get_language()` — returns "python", "mel", "text"

**Navigation:**
- `navigate_to(filepath, line_number)` — jump to file+line

**Settings:**
- `get_setting(key, default=None)` — read any setting
- `set_setting(key, value)` — write any setting
- `list_settings()` — returns dict of all keys + current values

**Output:**
- `write_output(text, level="info")` — write to output panel (info/warning/error/success/result)
- `read_output(max_lines=100)` — read recent output as plain text
- `clear_output()` — clear the output panel

**Project:**
- `open_project(folder_path)` — open a folder as project
- `close_project()` — close active project
- `get_active_project()` — returns dict `{name, root, paths, ...}` or None

**Execution:**
- `execute_in_dcc(code, language="python")` — run code in connected DCC
- `execute_locally(code)` — run in local Python namespace

**Status:**
- `get_editor_state()` — returns combined status dict (file, cursor, language, project, dcc)

**Panel wiring** (`mca_qt/editor_panel.py`):
- Call `register_panel(self)` at end of `__init__`
- Add `get_recent_text(max_lines)` to `OutputWindow`

**Files to modify:**
- NEW: `mca_core/editor_api.py`
- EDIT: `mca_qt/editor_panel.py` — register panel
- EDIT: `mca_qt/widgets/output_window.py` — add `get_recent_text()`

---

## Phase 2: TCP JSON-RPC Server (IPC Bridge)
**Goal:** Let external processes (MCP server) call EditorAPI methods over a local socket.

**New file:** `mca_core/editor_api_server.py`
- Asyncio TCP server on localhost:7003
- Runs in a daemon thread (doesn't block Qt event loop)
- JSON-RPC protocol:
  ```
  Request:  {"method": "open_file", "params": {"filepath": "/path"}, "id": 1}
  Response: {"result": true, "error": null, "id": 1}
  ```

**Thread safety:** The server thread can't touch Qt widgets directly. Solution:
- Server enqueues `(method, params, result_future)` into a `queue.Queue`
- A 50ms `QTimer` in the Qt main thread drains the queue and executes methods
- The future is set when done, unblocking the server thread

**Panel wiring:**
- Call `start_server()` after `register_panel()` in `__init__`
- Add `_api_dispatch_timer` QTimer to drain the cross-thread queue
- Call `stop_server()` in `cleanup()`

**Files to modify:**
- NEW: `mca_core/editor_api_server.py`
- EDIT: `mca_qt/editor_panel.py` — start/stop server, dispatch timer

---

## Phase 3: MCP Editor Tools
**Goal:** Add editor-specific MCP tools so Claude Code can interact with the editor.

**New file:** `mca_core/mcp_editor_tools.py`
- Standalone tool functions (same pattern as MayaMCP tool files)
- Each function uses an `EditorConnection` helper (socket client to port 7003)
- Deployed as `.py` (runs in MCP venv, not compiled)

**Tools:**
- `editor_get_state` — active file, cursor, language, project, DCC
- `editor_open_file(filepath)` — open a file
- `editor_save_file` / `editor_save_all` — save files
- `editor_list_open_files` — list open tabs
- `editor_get_text` / `editor_set_text(text)` — read/write active editor
- `editor_get_selection` — selected text
- `editor_navigate_to(filepath, line)` — go to location
- `editor_get_setting(key)` / `editor_set_setting(key, value)` / `editor_list_settings`
- `editor_write_output(text, level)` / `editor_read_output` / `editor_clear_output`
- `editor_get_project` / `editor_open_project(path)` / `editor_close_project`
- `editor_execute(code, language)` — run code in DCC
- `editor_read_file(filepath)` / `editor_write_file(filepath, content)` — disk I/O

**MCP server changes:**
- Add `--editor-port` CLI arg (default 7003) to `mca_maya_server.py`
- Scan deployment directory for editor tool files alongside MayaMCP tools

**Setup changes:**
- `mcp_setup.py` deploys `mcp_editor_tools.py` to `mcp_servers/` directory
- Update server registration to pass `--editor-port`

**Files to modify:**
- NEW: `mca_core/mcp_editor_tools.py`
- EDIT: `mca_core/mcp_maya_server.py` — editor-port arg, tool discovery
- EDIT: `mca_core/mcp_setup.py` — deploy editor tools
- EDIT: `build_maya.py` — add `mcp_editor_tools.py` to `DIST_PURE_PYTHON`

---

## Phase 4: Plugin System Wiring
**Goal:** Activate the dormant plugin system and implement the stub methods.

**Fix `MCAPluginAPI`** (`mca_editor/plugins/__init__.py`):
- Accept `EditorAPI` instead of `MCAMainWindow`
- Implement `add_sidebar_panel(title, widget)` — add panel to sidebar splitter
- Implement `add_menu_action(menu_path, label, callback)` — add to "Plugins" menu
- Implement `add_toolbar_action(label, callback, tooltip)` — add to toolbar
- Fix `execute_in_dcc()`, `show_notification()`, `register_adapter()` to use EditorAPI
- Add new methods from EditorAPI: `open_file()`, `save_file()`, `get_text()`, `navigate_to()`, etc.

**Wire `PluginManager`** in `MCAEditorPanel.__init__()`:
- Plugin directory: `~/Documents/mca_preferences/plugins/`
- Create `MCAPluginAPI(get_api())`
- Instantiate `PluginManager`, discover, and load plugins
- Unload all plugins in `cleanup()`

**Sidebar extension** (`mca_qt/widgets/sidebar.py`):
- Add `add_plugin_panel(title, widget)` method to `MCASidebar`

**Menu extension** (`mca_qt/editor_panel.py`):
- Add `_plugin_menu` submenu in Help or as top-level "Plugins" menu
- `_plugin_menu_actions` list for dynamic registration

**Files to modify:**
- EDIT: `mca_editor/plugins/__init__.py` — fix API class, implement stubs
- EDIT: `mca_qt/editor_panel.py` — instantiate PluginManager, add Plugins menu
- EDIT: `mca_qt/widgets/sidebar.py` — add `add_plugin_panel()`

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code (MCP Client)                                │
│  Calls: editor_open_file, editor_get_text, etc.          │
└───────────────────────┬─────────────────────────────────┘
                        │ stdio (MCP protocol)
┌───────────────────────▼─────────────────────────────────┐
│  MCP Server Process (mca_maya_server.py)                 │
│  ├── Maya tools (port 7001/7002)                         │
│  └── Editor tools (mcp_editor_tools.py → port 7003)     │
└───────────────────────┬─────────────────────────────────┘
                        │ TCP JSON-RPC (localhost:7003)
┌───────────────────────▼─────────────────────────────────┐
│  Editor Process (Maya or Standalone)                     │
│  ├── editor_api_server.py (TCP listener, daemon thread)  │
│  ├── EditorAPI (mca_core/editor_api.py)                  │
│  ├── MCAEditorPanel (mca_qt/editor_panel.py)             │
│  ├── PluginManager + MCAPluginAPI                        │
│  └── OutputWindow, Sidebar, CodeEditor, etc.             │
└─────────────────────────────────────────────────────────┘
```

## Build & Distribution Notes
- `mca_core/editor_api.py` — no Qt, compiles to `.pyd`
- `mca_core/editor_api_server.py` — no Qt, compiles to `.pyd`
- `mca_core/mcp_editor_tools.py` — ships as `.py` (DIST_PURE_PYTHON, runs in MCP venv)
- `mca_editor/plugins/__init__.py` — no Qt virtual overrides, compiles to `.pyd`
- Settings key `api_port` (default 7003) stored in MCASettings for configurability

## Verification (per phase)
- **Phase 1:** `python -c "from mca_core.editor_api import EditorAPI; print(dir(EditorAPI))"` + launch editor, verify `register_panel` called
- **Phase 2:** Launch editor → `python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1',7003)); ..."` to confirm server responds
- **Phase 3:** Launch editor + MCP server → Claude Code can call `editor_get_state` tool
- **Phase 4:** Drop a test plugin in `~/Documents/mca_preferences/plugins/` → verify it loads and its menu item appears
