# Session Notes — 2026-03-26

## PyUnreal Deployment to Wayward

- Deployed PyUnrealBridge plugin + pyunreal Python library to `E:\Rascal\depot\Wayward\`
- Replaced MCA Editor UE 5.5 build with 5.6 build (`MCAEditor-UE5.6-v1.0.5`)
- PyUnrealBridge auto-enables Remote Execution on startup via CDO reflection
- MCA Unreal MCP server is registered in global `~/.claude.json`, connects via UDP multicast discovery

## Terminal ANSI Parser Fix

**Problem:** Modern terminal programs (Claude Code) send CSI sequences with private parameter
prefixes (`>`, `=`, `<`, `!`) like `\x1b[>4;2m` (XTMODKEYS) and `\x1b[>1u` (Kitty keyboard
protocol). The ANSI parser regex only accepted `[0-9;?]*` in the parameter area, so these
sequences failed to match and leaked through as visible text like `[>4;2m` and `1u`.

**Fix (ansi_parser.py):**
- Updated `_CSI_RE` and `_ESC_RE` regexes to accept `[><=!]?` private parameter prefixes
- Added early return in `_handle_csi()` for non-DEC private prefixes (only `?` has specific handlers)
- Prevents `\x1b[>4;2m` from being misinterpreted as SGR `m` (which would reset text attributes)

## Terminal Shift+Tab Fix

**Problem:** Shift+Tab (Key_Backtab) wasn't handled by the terminal widget. Qt intercepted it
for focus navigation, so Claude Code's plan mode toggle (Shift+Tab) didn't work.

**Fix (terminal_native.py):** Added `Key_Backtab` handler that sends `\x1b[Z` (standard backtab
escape sequence) to the PTY.

## Terminal Cursor Visibility

**Problem:** Block cursor was rendered via fg/bg color inversion, which could be subtle or
invisible depending on cell colors.

**Fix (terminal_native.py):** Cursor now always renders as bright white (`#ffffff`) background
with dark text (`DEFAULT_BG`), regardless of the cell's own colors. Background is always set
for cursor cells (removed the `cell_bg != DEFAULT_BG` optimization for cursor).

## Terminal Auto-Scroll Fix

**Problem:** Terminal would scroll up when typing or receiving output, leaving the input line
barely visible or off-screen. Two causes:
1. `ensureCursorVisible()` was called inside `setUpdatesEnabled(False)`, preventing Qt from
   actually performing the scroll
2. `ensureCursorVisible()` only scrolls the minimum amount to show the cursor, which could
   leave it at the very bottom edge of the viewport

**Fix (terminal_native.py):**
- Moved auto-scroll to AFTER `setUpdatesEnabled(True)` so Qt can calculate layout
- Replaced `ensureCursorVisible()` with `scrollbar.setValue(scrollbar.maximum())` which always
  snaps to the very bottom of the document
- Changed `was_at_bottom` check to `is_in_scrollback` — only suppresses auto-scroll when the
  user has scrolled more than a viewport height from the bottom (reading history), not when
  they're anywhere near the live grid area

## Terminal Size Persistence

**Problem:** Right terminal panel and bottom terminal panel always opened at hardcoded default
sizes (300px width / 200px height) regardless of how the user had previously resized them.

**Fix (editor_panel.py):**
- `_show_right_panel()` reads `right_panel_width` from settings instead of hardcoding 300
- `_hide_right_panel()` saves current width to `right_panel_width` before hiding
- Bottom terminal uses `bottom_terminal_height` setting similarly
- `save_window_state()` also saves both values on app close (covers the case where panels
  are still open at shutdown)

## New File Default Extension

**Problem:** Creating a new file from the workspace tree prompted with no default, so users
had to manually type `.py` every time.

**Fix (sidebar.py):** `QInputDialog.getText()` now pre-fills `untitled.py` as the default
filename.

## Files Changed

- `mca_qt/widgets/ansi_parser.py` — CSI/ESC regex + private prefix handling
- `mca_qt/widgets/terminal_native.py` — Shift+Tab, cursor, auto-scroll
- `mca_qt/editor_panel.py` — Terminal size persistence
- `mca_qt/widgets/sidebar.py` — Default .py extension for new files

## Builds Deployed

- Maya 2024, 2025, 2026 — all rebuilt and deployed to plug-ins folders
- UE 5.6 — rebuilt (Python only, --skip-cpp) and deployed to Wayward
