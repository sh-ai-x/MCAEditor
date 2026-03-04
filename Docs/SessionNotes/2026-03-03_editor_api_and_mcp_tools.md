# Session Notes — 2026-03-03: Editor API, JSON-RPC Server & MCP Tools

## Summary
Implemented a three-phase system to give Claude Code native control of the MCA
Editor through MCP tools.  Phase 1 built the EditorAPI (28 methods), Phase 2
added a TCP JSON-RPC server for cross-process access, and Phase 3 created an
MCP server (`MCAEditorMCP`) so Claude Code can open files, edit buffers,
execute code in Maya, and manage projects — all through its standard tool
interface.

Also fixed a `RuntimeError: Internal C++ object already deleted` crash in
`maya_window.py`'s eventFilter when copying text from the terminal.

---

## Phase 1 — EditorAPI (`mca_core/editor_api.py`)

New module providing a pure-Python wrapper around the editor panel.  28 public
methods across 7 categories:

- **File operations**: `open_file`, `save_file`, `save_all`, `close_tab`,
  `list_open_files`, `get_active_file_path`, `read_disk_file`, `write_disk_file`
- **Editor content**: `get_text`, `set_text`, `get_selected_text`, `insert_text`,
  `replace_range`, `get_cursor_position`, `get_language`
- **Navigation**: `navigate_to`, `go_to_line`
- **Output panel**: `write_output`, `get_output_text`, `clear_output`
- **Project**: `open_project`, `close_project`, `get_project`
- **Execution**: `execute_in_dcc`, `execute_locally`
- **Settings / State**: `get_setting`, `set_setting`, `get_state`

Design:
- Zero Qt imports — all Qt interaction delegated to registered panel reference
- Module-level singleton via `register_panel()` / `get_api()`
- `@_require_main_thread` decorator asserts Qt main thread (safety net)
- Mutating ops return `ApiResult` dicts (`{success, result/error}`)

## Phase 2 — JSON-RPC Server (`mca_core/editor_api_server.py`)

TCP server on `localhost:7003` (or next available port) using JSON-RPC 2.0
(newline-delimited).

Architecture:
- Asyncio TCP server in a daemon thread (doesn't block Qt event loop)
- Thread-safe bridge: server enqueues requests, QTimer (50ms) drains them
  on the main thread, executes EditorAPI methods, sets Futures
- `ALLOWED_METHODS` whitelist prevents arbitrary attribute access
- Port discovery file at `~/Documents/mca_preferences/api_port.json`
  (port, PID, start time)
- Multiple simultaneous clients supported

Integration in `editor_panel.py`:
- `register_panel(self)` called during `__init__`
- `start_server()` starts the daemon thread
- `QTimer` calls `drain_queue()` every 50ms
- `stop_server()` on panel close removes discovery file

## Phase 3 — MCP Editor Server (`mca_core/mcp_editor_server.py`)

Standalone MCP server (17 tools) registered as `MCAEditorMCP` alongside the
existing `MCAMayaMCP`.  Runs in MayaMCP's venv via stdio.

Tools exposed:
- `editor_get_state`, `editor_open_file`, `editor_save_file`,
  `editor_list_open_files`, `editor_get_text`, `editor_set_text`,
  `editor_insert_text`, `editor_replace_range`, `editor_navigate_to`,
  `editor_execute_in_dcc`, `editor_execute_locally`, `editor_write_output`,
  `editor_get_output`, `editor_read_disk_file`, `editor_write_disk_file`,
  `editor_open_project`, `editor_close_project`

Design:
- Reads `api_port.json` on each call (handles editor restart/port change)
- PID staleness check before TCP connect (fast error if editor crashed)
- Maps MCP tool names to JSON-RPC method names (e.g. `editor_get_state` -> `get_state`)
- All errors surface as MCP TextContent with clear messages

### `mca_core/mcp_setup.py` changes
- Now deploys and registers **both** servers (MCAMayaMCP + MCAEditorMCP)
- `_is_registered(server_name)` — parameterized to check either server
- `_register_server_with_claude_code(name, path)` — parameterized registration
- `_apply_patches()` copies both server files to deploy dir
- `get_mcp_server_status()` reports status of both servers

### `build_maya.py` changes
- Added `mca_core/mcp_editor_server.py` to `DIST_PURE_PYTHON`

---

## Bug Fix — eventFilter C++ Object Crash

**File**: `mca_maya/maya_window.py` line 341
**Symptom**: `RuntimeError: Internal C++ object (PySide6.QtWidgets.QWidget)
already deleted` when pressing Ctrl+C in the terminal.
**Cause**: The focused widget's C++ object gets deleted between the
`focusWidget()` call and the `keyPressEvent()` dispatch (tab close or
widget rebuild mid-event).
**Fix**: Wrapped the dispatch block in `try/except RuntimeError`.

---

## Files Changed

| Action | File | What |
|--------|------|------|
| NEW | `mca_core/editor_api.py` | EditorAPI — 28-method public API |
| NEW | `mca_core/editor_api_server.py` | TCP JSON-RPC server on port 7003 |
| NEW | `mca_core/mcp_editor_server.py` | MCP server for editor tools (17 tools) |
| EDIT | `mca_qt/editor_panel.py` | API registration, server startup, QTimer drain |
| EDIT | `mca_qt/widgets/output_window.py` | Added `get_recent_text()` for API |
| EDIT | `mca_core/mcp_setup.py` | Deploy + register both MCP servers |
| EDIT | `build_maya.py` | Added `mcp_editor_server.py` to DIST_PURE_PYTHON |
| EDIT | `mca_maya/maya_window.py` | Fix eventFilter C++ crash |

## Testing Notes
- Verified in Maya: editor opens, API server starts, `api_port.json` written
- Verified Claude Code MCP: `editor_get_state` returns editor state
- Verified Claude Code MCP: `editor_open_file` opens tabs in the editor
- `open_project` / `close_project` added after initial testing showed they
  were needed (excluded in original plan but `get_state` only reads, doesn't set)
