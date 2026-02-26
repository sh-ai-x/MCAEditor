# Session: MCP Integration Implementation — 2026-02-26

## Summary

Implemented the Maya MCP integration that allows Claude Code (running in MCA Editor's terminal) to automatically interact with the live Maya scene via MCP tools. Uses Patrick Palmer's MayaMCP (MIT) for tool files, but replaces the communication layer with our own battle-tested adapter patterns.

## Files Created

### `mca_core/mcp_maya_server.py` — Self-contained MCP server
- Standalone Python script (zero imports from mca_core)
- Runs in MayaMCP's venv (which provides the `mcp` package)
- **MayaConnection**: base64-encoded Python to port 7002, two-phase timeout recv
- **OperationsManager**: walks mayatools/ dirs, loads .py files, builds MCP Tool schemas
- **load_maya_tool_source()**: fixed arg serialization (repr/json.dumps instead of f-strings)
- **wrap_script_in_scoped_function()**: isolates tool execution with exception handling
- MCP server handlers: list_tools, call_tool via mcp.server.lowlevel.Server
- CLI: --port, --tool-dir args; MAYA_MEL_PORT env var fallback
- Skips generate_scene tool by name

### `mca_core/mcp_setup.py` — Setup orchestrator
- Public API: `ensure_maya_mcp(background, status_callback)`, `get_mcp_server_status()`
- Idempotent 4-step sequence: clone MayaMCP, apply patches, create venv, register with Claude Code
- Finds system Python 3.10+ (excludes mayapy), finds git, finds claude CLI
- Registration via `claude mcp add-json` with fallback to direct ~/.claude.json write
- All failures logged, never blocks the editor

## Files Modified

### `mca_maya/plugin_main.py`
- Added `mcp_setup.ensure_maya_mcp(background=True)` after `setup_venv()` in `initializePlugin()`

### `mca_qt/editor_panel.py`
- Added MCP setup trigger in `_show_connect_dialog()` after successful Maya connection
- Uses status_callback with QTimer.singleShot for thread-safe UI updates

### `mca_core/adapters/maya_adapter.py`
- Replaced hardcoded `get_mcp_server_info()` stub with `mcp_setup.get_mcp_server_status()` call

### `mca_core/adapters/internal_maya_adapter.py`
- Same get_mcp_server_info() update as maya_adapter.py

## Architecture

```
Claude Code <-> Our MCP Server (stdio) <-> Maya Python port 7002 (base64)
                     |
               Tool discovery from
               MayaMCP/src/mayatools/*.py
```

### Deployed Layout

```
~/Documents/mca_preferences/mcp_servers/
├── MayaMCP/                     # Git clone (untouched)
│   ├── src/mayatools/           # Tool .py files
│   ├── .venv/                   # Venv with mcp package
│   └── requirements.txt
├── mca_maya_server.py           # Our server (copied from repo)
└── mca_maya_server.log          # Server log
```

## Bugs Found and Fixed During Testing

### MCP Tool Results Not Returning
- **Symptom:** All tools returned `{"success": true}` with no data
- **Root cause 1:** `print()` inside `exec()` on Maya's commandPort goes to Maya's Script Editor, NOT back through the TCP socket
- **Fix:** Adopted maya_adapter.py's proven double-base64 stdout-redirect wrapper pattern. Inner exec redirects stdout to StringIO buffer, outer exec re-prints captured output at top level where commandPort returns it through the socket
- **Root cause 2:** When Maya's command port wasn't open, `_send_command` returned None, `convert_to_content(None)` returned `[]`, falling through to generic `{"success": true}` — masking the real error
- **Fix:** Explicit None check in `handle_call_tool()` that returns a clear error message with the exact `cmds.commandPort()` commands to run

### Terminal Paste Not Working
- **Symptom:** Ctrl+V did nothing in both terminal frontends
- **Root cause (xterm.js):** QWebEngineView's embedded Chromium doesn't have clipboard API permissions, so xterm.js native Ctrl+V paste fails silently. No Python-side paste handler existed.
- **Fix:** Added `paste_clipboard()` method that reads system clipboard from Python and pushes into xterm.js via `pasteText()` JS function. Added `eventFilter()` on Chromium's focus proxy widget to intercept Ctrl+V before it reaches the browser.
- **Root cause (native):** Only Ctrl+Shift+V was wired to paste. Plain Ctrl+V sent raw `\x16` (ASCII "literal next" control char) to the PTY.
- **Fix:** Changed the key check to match Ctrl+V with or without Shift.

## Known Issues / Next Steps
- Maya's command ports (7001/7002) must be open for MCP tools to work. The MCA Editor adapter opens them on connect, but if Claude is launched before connecting, the ports aren't available yet.
- Paste fix needs verification after MCA Editor restart (changes were made this session but not tested live yet)

## Key Design Decisions

1. **Double base64 + stdout redirect** — matches maya_adapter.py's proven pattern for getting exec() results back through Maya's commandPort socket
2. **Untouched MayaMCP clone** — can git pull for tool updates without conflicts
3. **generate_scene.py deleted during setup** — broken tool with syntax errors and undefined variables
4. **System Python for venv** — MCP server runs as standalone process, not inside Maya
5. **Clear error messages** — connection failures tell Claude exactly what commands to run in Maya
