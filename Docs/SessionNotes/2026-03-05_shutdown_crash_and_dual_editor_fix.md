# Session Notes — 2026-03-05: Shiboken Shutdown Fix & Stderr Output Capture

## Problems
1. **Shiboken shutdown crash** (~9% of Maya closes) — `ACCESS_VIOLATION`
   at offset `0002272C` in `shiboken6.abi3.dll` during Maya's atexit phase.
2. **Plugin name mismatch** — `userSetup.py` hardcoded `mcaEditor` (old
   single-file build) but actual plugin is `mca_editor_plugin` (module-based).
3. **Missing output** — Python `logging` output (e.g. `[MCA - Module:...]`
   lines from the MCA framework) did not appear in our output panel, even
   though Maya's Script Editor showed them.

## Root Causes

### Shiboken Crash
Two categories of Qt objects survived `shiboken6.delete(_mca_editor_window)`
because they were registered on **QApplication**, not as children of the
editor window:

- **`app.focusChanged` signal** — connected in `MCAMayaWindow.__init__` but
  never disconnected. After shiboken deletes the window, the callback wrapper
  dangles on QApplication → atexit crash.
- **CodeCompleter event filters** — each completer is `parent=None` and calls
  `app.installEventFilter(self)`. Never removed on tab close or panel shutdown.
  Orphaned completers accumulate and crash shiboken during atexit.

### Plugin Name Mismatch
The `_ensure_auto_load()` function in `plugin_main.py` wrote a `userSetup.py`
block that hardcoded `mcaEditor` as the plugin name. After switching to the
module-based install (`install_maya.py`), the actual plugin stub is
`mca_editor_plugin.py`. The old stale `mcaEditor.py` was also left in the
plug-ins folder.

### Missing Logging Output
`MCommandMessage.addCommandOutputCallback` only captures Maya's native output
system (MEL echo, `print()`, `cmds.warning()`). Python's `logging` module
writes to `sys.stderr`, which Maya's Script Editor captures via its own stderr
wrapper — but our callback never saw those writes.

## Fixes

### Shiboken Crash
- **`completer.py`** — `cleanup()` now calls `app.removeEventFilter(self)`
- **`editor_panel.py`** — Panel `cleanup()` iterates all editors and calls
  `completer.cleanup()`; `_close_tab_in_group()` also cleans up completer
- **`maya_window.py`** — `cleanup_editor()` and `dockCloseEventTriggered()`
  both disconnect `app.focusChanged` and remove hotkey filter before
  destroying the window

### Plugin Name
- **`plugin_main.py`** — `_ensure_auto_load()` now detects whether `mcaEditor`
  or `mca_editor_plugin` is loaded and writes the correct name into
  `userSetup.py`
- Removed stale `mcaEditor.py` from plug-ins folder
- Updated `userSetup.py` on disk to use `mca_editor_plugin`

### Stderr Output Capture
- **`maya_window.py`** — Added `_StderrTee` class that wraps `sys.stderr` and
  tees writes to the MCA output panel. Installed alongside the
  `MCommandMessage` callback in `_install_output_hook()`. Properly removed on
  close (`dockCloseEventTriggered`) and unload (`cleanup_editor`).
- Routes `ERROR:`/`Warning:` patterns to colored output methods
- Forwards all writes to the original stderr so Maya's Script Editor still works

## Important Lessons (This Session)
- **Dual editor and blank editor bugs** were introduced by overly aggressive
  changes to `show_mca_editor()` and `_do_auto_open_editor()`. These were
  reverted to v0.1.8 behavior — the original startup flow works correctly.
- **NEVER use `deleteLater()` + `cmds.deleteUI()` on the same widget** —
  double-free crash.
- **Keep changes minimal** — the shiboken fix only needed 4 surgical edits
  (completer cleanup, focusChanged disconnect). Attempting to also "fix" the
  startup flow caused cascading regressions.

### Version
v0.1.9

## Files Changed
| Action | File |
|--------|------|
| EDIT | `mca_qt/widgets/completer.py` (cleanup removes event filter) |
| EDIT | `mca_qt/editor_panel.py` (cleanup all completers at shutdown + tab close) |
| EDIT | `mca_maya/maya_window.py` (disconnect focusChanged, stderr tee) |
| EDIT | `mca_maya/plugin_main.py` (detect plugin name for userSetup.py) |
| EDIT | `mca_core/__init__.py` (version 0.1.8 → 0.1.9) |
| EDIT | `tools/maya_editor_test.py` (plugin name update) |
| EDIT | `tools/maya_plugin_test.py` (plugin name update) |
| NEW | `tools/maya_shutdown_test.py` |
| NEW | `tools/maya_reopen_test.py` |
| NEW | `tools/maya_startup_diag.py` |
