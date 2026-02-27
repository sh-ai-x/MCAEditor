# Session: UI Fixes, MCP Command Ports, and Layout Cleanup — 2026-02-26

## Summary

Fixed several issues from the previous MCP integration session: command ports
not opening automatically, terminal paste not working in Maya, and cleaned up
the right panel UI (removed double tab layers, AI panel, added sidebar toggle).

## Bugs Fixed

### MCP Command Ports Not Opening Automatically
- **Symptom:** Claude Code's MCP tools couldn't reach Maya — port 7002 was closed
- **Root cause 1:** `initializePlugin()` never opened command ports because the
  editor is launched via `show_mca_editor()` directly, not through the plugin system
- **Root cause 2:** Even after adding to `initializePlugin()`, `cmds.commandPort()`
  failed silently during early plugin init (Maya's networking not ready yet)
- **Fix (plugin_main.py):** Use `maya.utils.executeDeferred()` to open ports after
  Maya is fully initialized
- **Fix (maya_window.py):** Added `_ensure_command_ports()` in `show_mca_editor()`
  so ports open regardless of launch method (plugin or direct call)
- **Gotcha:** `.pyc` bytecode cache prevented code changes from being picked up —
  had to delete `__pycache__/*.pyc` files after edits

### Terminal Paste (Ctrl+V) Not Working in Maya
- **Symptom:** Ctrl+V did nothing in the terminal when running inside Maya
- **Root cause:** `_MayaHotkeyFilter` intercepted Ctrl+V, found no matching action
  in the editor's registry, then called `focus.keyPressEvent()` on the focused
  widget — which was the terminal's inner `QPlainTextEdit` (read-only), not the
  `NativeTerminalWidget` that has the paste logic in its `eventFilter()`
- **Fix:** Added `_find_parent_terminal()` to `_MayaHotkeyFilter`. When a Ctrl+key
  event fires and the focused widget is inside a terminal, route through the
  terminal's `eventFilter()` instead of calling `keyPressEvent()` on the child

## UI Changes

### Removed Double Tab Layer on Right Panel
- **Before:** Right panel was a QTabWidget ("AI" | "Terminal") containing a
  TerminalTabPanel (another QTabWidget with individual terminal tabs)
- **After:** TerminalTabPanel sits directly in the main splitter — one tab bar
- Removed `AIPanel` import, creation, toggle action, settings save/restore
- Removed `_right_panel` QTabWidget wrapper entirely

### Removed "+" Button from Terminal Tab Panel
- The corner "+" button overlapped with the right stripe's terminal button
- Removed from `terminal_tab_panel.py` — new terminals created via stripe button

### Added Sidebar Toggle Button (Left Stripe)
- New `sidebar_icon()` in `icons.py` — panel layout with highlighted left sidebar
- Button added at top of left stripe, terminal button stays at bottom
- Active state (blue highlight) tracks sidebar visibility
- State saved/restored with session

### Tool Stripe Padding
- Added 4px horizontal margins to both tool stripes (28px buttons + 8px padding = 36px)
- Buttons no longer look squashed against the window edges

### Sidebar Splitter Sizes Now Saved
- The internal splitter between Workspace, Open Editors, and Outline panels
  was not being saved — always reset to defaults on restart
- Added `splitter_sizes()` / `set_splitter_sizes()` to `MCASidebar`
- Added `sidebar_splitter_sizes` setting key to save/restore cycle

## Files Modified

| File | Changes |
|------|---------|
| `mca_maya/plugin_main.py` | Added deferred command port opening (7001/7002) |
| `mca_maya/maya_window.py` | Added `_ensure_command_ports()`, MCP setup trigger, terminal paste fix in hotkey filter |
| `mca_qt/editor_panel.py` | Removed AI panel + outer tab wrapper, added sidebar toggle button, save/restore sidebar splitter |
| `mca_qt/icons.py` | Added `sidebar_icon()` |
| `mca_qt/widgets/sidebar.py` | Added `splitter_sizes()` / `set_splitter_sizes()` |
| `mca_qt/widgets/terminal_tab_panel.py` | Removed "+" corner button |
| `mca_qt/widgets/tool_stripe.py` | Added 4px horizontal margins |

## Key Learnings

- **`.pyc` cache is persistent in Maya** — editing `.py` source doesn't always
  take effect because Python uses cached bytecode. Delete `__pycache__/*.pyc`
  after modifying files that Maya has already imported.
- **`cmds.commandPort()` fails during `initializePlugin()`** — Maya's networking
  isn't ready yet. Use `maya.utils.executeDeferred()` for anything that needs
  Maya to be fully initialized.
- **Maya hotkey filter must know about terminal widgets** — the terminal's key
  handling lives in `eventFilter()`, not `keyPressEvent()`, because the actual
  focused widget is the inner QPlainTextEdit, not the terminal container.
