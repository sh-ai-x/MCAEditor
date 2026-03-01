# Session: UI State Fixes, Reload Fix, Auto-Reload Modules — 2026-03-01

## Summary

Fixed persistent UI state bugs where sidebar/output panels collapsed or hid
on editor reopen, fixed the Reload button skipping startup scripts, added
auto-reload of Python modules on save/execute, and improved the Recent
Projects menu to show project names instead of folder names.

## Fix 1: Auto-Open Collapsing Splitters

### Problem
`_auto_open_last_project()` ran via `QTimer.singleShot(200)` AFTER the
widget was shown. The layout rebuild inside `_switch_to_manifest()` →
`restore_layout_state()` collapsed all splitter panes to 0.

### Solution
- Moved auto-open from `QTimer.singleShot(200)` to a synchronous call at
  the end of `__init__`, before `show()` is called by the host window.
- Added `_restore_splitter_sizes()` call after `_open_project()` returns
  to re-apply saved sizes after the layout rebuild.
- Deleted `_force_restore_ui_state()` — no longer needed since the timing
  race it tried to solve no longer exists.

## Fix 2: Sidebar/Output Hidden on Reopen

### Root Cause
`save_window_state()` used `self._output.isVisible()` and
`self._sidebar.isVisible()` to persist panel visibility. But in both Maya
(`dockCloseEventTriggered`) and standalone (`closeEvent`), the parent
window is already hiding when this runs. Qt's `isVisible()` returns False
for all children when any ancestor is hidden — so every close saved
`sidebar_visible=False` and `output_visible=False`.

### Solution
- Added `self._sidebar_visible` and `self._output_visible` tracking booleans
  in `__init__` (default True).
- Updated `_restore_ui_state()` to set them when reading from settings.
- Updated `_toggle_sidebar()` / `_toggle_output()` to flip the tracked var.
- Updated `save_window_state()` to save the tracked vars instead of calling
  `isVisible()`.

## Fix 3: Reload Button Not Working

### Problem
`_on_reload_project()` called `_close_project()` then `_open_project()`.
The close removed env vars/paths, but `_open_project()` → `_apply_project_mode()`
→ `_is_project_already_active()` found the environment still matched (or the
`skip_startup` logic triggered), printing "skipping startup (environment
already active)" and never running startup scripts.

### Solution
Rewrote `_on_reload_project()` to do a targeted shutdown/startup cycle:
1. Run shutdown script
2. Remove env vars and sys.path entries
3. Re-read `.mca-project` file from disk
4. Re-inject paths and env vars
5. Run startup script

No more close/open cycle — tabs stay untouched, startup always runs.

## Feature 1: Auto-Reload Modules on Save/Execute

### Behavior
When saving or executing a `.py` file that has already been imported
(`sys.modules`), automatically calls `importlib.reload()`:
- Locally in the editor's Python environment
- In the connected DCC (Maya) via the adapter

### Implementation
- `_auto_reload_module(filepath)` in `editor_panel.py`:
  - Resolves file path to dotted module name via sys.path lookup
  - Skips if module not in `sys.modules` (never imported)
  - Reloads locally with `importlib.reload()`
  - Sends `importlib.reload()` command to DCC adapter
- Hooked into `_save_file()` (Ctrl+S) and `_save_on_execute()` (before execute)

### Project Setting
- Added `auto_reload_modules` property to `MCAProject` (default True)
- Added checkbox in Project Settings dialog: "Auto-reload modules on save/execute"
- `_auto_reload_module()` checks the flag and skips if disabled

## Feature 2: Recent Projects Shows Project Names

### Problem
Recent Projects menu showed `os.path.basename(project_path)` — confusing
when multiple projects live in folders with the same name (e.g. "packages").

### Solution
Reads the project name from the `.mca-project` file for each entry. Falls
back to folder name if the project file is missing.

## Files Changed

| Action | File | Changes |
|--------|------|---------|
| MODIFY | `mca_core/project.py` | `auto_reload_modules` property, serialization in load/save |
| MODIFY | `mca_qt/editor_panel.py` | Sync auto-open, visibility tracking, reload fix, `_auto_reload_module()`, recent projects names |
| MODIFY | `mca_qt/widgets/project_settings_dialog.py` | Auto-reload checkbox on General page |
| CREATE | `Docs/SessionNotes/2026-03-01_ui_fixes_and_auto_reload.md` | This file |
