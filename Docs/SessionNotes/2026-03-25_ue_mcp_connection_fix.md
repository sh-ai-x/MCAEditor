# Session Notes — 2026-03-25: UE MCP Connection Fix (Remote Execution Protocol)

## Summary

Fixed the MCA Unreal MCP server so Claude Code can actually communicate with
Unreal Engine. The server was using the completely wrong protocol (direct TCP
to port 6776). UE's Remote Execution protocol is UDP multicast discovery +
reverse TCP — the client listens, UE connects to us.

End-to-end connection verified: Claude Code -> MCAUnrealMCP -> UDP discovery
-> reverse TCP -> UE Python interpreter -> structured results.

## Root Cause

The original `mcp_unreal_server.py` tried to connect via TCP to port 6776.
UE's Remote Execution protocol (documented in
`PythonScriptPlugin/Content/Python/remote_execution.py`) works like this:

1. **Discovery**: UDP multicast ping/pong on `239.0.0.1:6766`
2. **Open**: UDP multicast `open_connection` with our TCP endpoint
3. **Accept**: UE connects TO our TCP listen socket (reverse connection)
4. **Command**: TCP send `command`, receive `command_result`
5. **Close**: UDP multicast `close_connection`

Messages are plain UTF-8 JSON (no binary framing), protocol version 1.

## Changes

### `mca_core/mcp_unreal_server.py` — Complete rewrite of UnrealConnection

- Removed dead binary framing code (`_build_ue_message`, `_parse_ue_message`)
- Removed old constants (`PROTOCOL_MAGIC = b"ue_py"`, `PROTOCOL_VERSION = 2`)
- Added `DEFAULT_MULTICAST_TTL = 0` (was referenced but never defined — crash)
- Added `_ue_msg()` — builds plain UTF-8 JSON messages matching UE's protocol
- Added `_parse_ue_json()` — parses plain JSON messages
- Added `_create_broadcast_socket()` — UDP multicast with loopback, TTL 0
- Added `_discover_ue_node()` — sends pings, waits for pongs, returns node ID
- Rewrote `_execute()` — full protocol flow: discover -> listen -> open -> command -> result -> close
- TCP listen uses port 0 (OS-assigned) — avoids port conflicts
- `RECV_BUFFER_SIZE` changed from 65536 to 8192 (matches UE's default)
- Fixed result parsing: UE returns `output` as a list, not a string

### `mca_unreal/Content/Python/ue_editor_host.py` (from prior session)

- `_ensure_remote_execution()` — auto-enables Remote Execution on UE startup
- `ensure_unreal_mcp(background=True)` — deploys/registers MCP server on launch

### `mca_core/editor_api.py` (from prior session, deployed as .pyc)

- Added UE embedded mode detection to `get_state()` — reports connected DCC

### `mca_core/plugins/ai_chat/system_prompt.py` (from prior session, deployed as .pyc)

- Added `_UNREAL_CONTEXT_BLOCK` — tells Orange Slice AI about UE Python APIs

### `E:/Rascal/depot/Wayward/Config/DefaultEngine.ini`

- Changed `bRemoteExecution=False` to `bRemoteExecution=True`

## Deployment

- `mca_preferences/MCAEditor/mcp_servers/mca_unreal_server.py` — fixed server
- `mca_preferences/MCAEditor/mcp_servers/unreal_tools/` — all 51 tools (was only 27)
- Wayward plugin location — server + tools synced
- `~/.claude.json` — MCAUnrealMCP registered at both global and project scope

## Tool Count

51 total MCP tools across 10 categories:
- actor (7), asset (3), blueprint (12), control_rig (9), execution (2),
  level (3), material (3), project (1), python (6), viewport (3)
- Plus 2 extra: list_objects_by_type, select_actors

## Verification

Confirmed working via Claude Code MCP:
- `get_project_info` returned: Wayward project, UE 5.6.1, path E:/Rascal/depot/Wayward/
- UDP discovery found UE node instantly
- TCP reverse connection established on dynamic port
- Command executed and result returned as structured JSON

## Key Learnings

- UE's Remote Execution is NOT a simple TCP server. It's a multicast discovery
  protocol with reverse TCP. Always read UE's own `remote_execution.py` source.
- Port 6776 is not a listen port — it's a convention for the CLIENT's listen
  port that UE connects TO.
- UE returns `output` and `result` fields in `command_result` — `output` can
  be a list of strings (captured stdout lines), not always a single string.
- `DefaultEngine.ini` is the correct place for `bRemoteExecution=True`, and
  the `PythonScriptPluginSettings` property name in Python is `remote_execution`.
