# 2026-03-18 — MCP Server Registration: Global to Project Scope

## Summary
Moved MCA MCP server registrations from global scope to project scope in
Claude Code's config.  Previously, MCAMayaMCP and MCAEditorMCP appeared in
every project opened in Claude Code.  Now they only load when working in the
MCAEditor project directory.

## Problem
- `mcp_setup.py` registered both MCP servers with `--scope user` (global)
- The direct-write fallback wrote to the top-level `mcpServers` in `~/.claude.json`
- This caused every project (ShmaCollective, ComesAI, Wayward, etc.) to see
  and attempt to connect to the MCA MCP servers

## Changes

### `mca_core/mcp_setup.py`
- `_register_server_with_claude_code()` — changed `--scope user` to `--scope project`
- `_register_direct()` — now writes into `projects["E:/Projects/MCAEditor"].mcpServers`
  instead of the top-level `mcpServers` section
- `_is_registered()` — checks project scope first, falls back to global scope for
  backwards compatibility (won't re-register if old global entry still exists)
- Added `_get_repo_root()` — resolves repo root from file location
- Added `_get_project_key()` — finds matching project key in claude.json
  (handles forward-slash / backslash variants)

### `~/.claude.json`
- Moved `MCAMayaMCP` and `MCAEditorMCP` entries from global `mcpServers` into
  `projects["E:/Projects/MCAEditor"].mcpServers`
- Global `mcpServers` section is now empty `{}`

## No Breaking Changes
- The MCP servers themselves are unchanged — same commands, same venv, same paths
- `_is_registered()` still detects legacy global entries, so no duplicate registration
- `get_mcp_server_status()` works the same (calls `_is_registered()` internally)
