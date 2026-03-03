# Session: Tree State Persistence, Shortcut Persistence & Stability — 2026-03-03

## Summary

Added workspace tree state persistence (expanded folders survive refreshes and
sessions), keyboard shortcut persistence (custom shortcuts survive restarts),
and fixed several crash/stability issues (output window QTimer crash, reload
crash, shutdown script edge case). Also added symbol indexing, color scheme
application on startup, and auto-reload for modules executed in Maya.

---

## What Was Completed

### 1. Workspace Tree State Persistence

The sidebar file tree previously rebuilt from scratch on every refresh (file
watcher, project open, etc.), collapsing all folders back to defaults. Now the
expanded/collapsed state is tracked live and restored after rebuilds and across
sessions.

**Changes in `mca_qt/widgets/sidebar.py`:**
- Added `_expanded_paths` set and `_selected_path` to `WorkspacePanel.__init__`
- Modified `_on_item_expanded`/`_on_item_collapsed` to track paths in the set
- Modified `_refresh_tree` to re-expand tracked paths after rebuilding
- Added `_iter_all_items()` generator for tree traversal
- Added `save_tree_state_to_settings()` / `restore_tree_state_from_settings()`
  for QSettings persistence
- Added `_tree_settings_key()` static method to build safe settings keys
  (avoids QSettings treating backslashes as group separators)
- Modified `set_locked_folder()` to clear expanded paths when switching roots

**Per-project storage:** Each project's tree state is stored under a key
suffixed with the project folder name (e.g., `workspace_tree_expanded_MyProject`),
so switching between projects restores each project's own tree layout.

**Hook points in `mca_qt/editor_panel.py`:**
- `_close_project()` — saves tree state before teardown
- `_apply_project_mode()` — restores tree state after project load
- `save_window_state()` — saves tree state on editor close
- `_restore_ui_state()` — restores tree state on editor open
- `cleanup()` — saves tree state on shutdown

### 2. Keyboard Shortcut Persistence

Custom keyboard shortcuts set in Settings > Keyboard were not being saved or
restored across sessions.

**Root cause:** `_save_settings()` in `settings_dialog.py` never wrote shortcuts,
and no restore logic existed on startup.

**Fix:**
- Added shortcut persistence to `settings_dialog.py:_save_settings()` — compares
  current shortcuts against defaults, saves a `custom_shortcuts` dict
- Added `_restore_custom_shortcuts()` to `editor_panel.py` — reads the dict from
  settings and applies overrides to registered actions
- **Critical subtlety:** `_default_shortcuts` must be snapshotted in `build_menus()`
  BEFORE restoring customs, otherwise restored customs appear as "defaults" and
  changes aren't detected on the next save
- Passed `default_shortcuts` to `SettingsDialog` constructor

### 3. Output Window QTimer Crash Fix

**Symptom:** After project reload or shutdown, saving a file would crash Maya
with `RuntimeError: Internal C++ object (PySide6.QtCore.QTimer) already deleted`.

**Fix in `mca_qt/widgets/output_window.py`:** Wrapped `_flush_timer.isActive()`
in `_append_formatted` with `try/except RuntimeError`.

### 4. Maya Output Callback Crash Guard

**Fix in `mca_maya/maya_window.py`:** Wrapped the entire `_on_maya_output`
callback body with `try/except RuntimeError` to prevent unhandled exceptions in
the output callback from cascading into a workspace control destruction
(Shiboken tears down the widget tree on unhandled Python errors in signal
dispatch).

### 5. Project Reload / Close Crash Guard

Wrapped `_close_project()` and `_on_reload_project()` bodies in `try/except`
so that any error during project teardown doesn't propagate into Maya's signal
dispatch and destroy the workspace control.

### 6. Symbol Indexing (New Feature)

Added `mca_core/symbol_index.py` — background threaded symbol indexer for
instant Go To Declaration lookups within projects.

### 7. Color Scheme Applied on Startup

Added `_apply_settings_to_editors()` call after session restore so editors
use the saved color scheme immediately instead of hardcoded defaults.

### 8. Auto-Reload Modules on Execute

When executing code in Maya, modules imported from the project are now
auto-reloaded so changes are picked up without restarting Maya.

---

## Debugging: Shutdown Closing the Editor

Extensive debugging session to find why clicking "Shutdown" closed the entire
editor instead of just returning to the default workspace.

**Debugging approach:**
- Added numbered `print()` statements at each step of `_close_project()`
- All 15 steps completed successfully (confirmed via Maya output)
- Added `dockCloseEventTriggered` trace — NOT called (workspace control not
  formally closed)
- Switched to file-based debug logging (temp files) since print output was lost
  when the editor disappeared
- Added per-step visibility checks (`panel_vis`, `window_vis`) between steps

**Finding:** Step 4 (`_run_shutdown_script()`) caused `window_vis` to drop from
True to False. All subsequent steps ran with the editor already invisible.

**Root cause:** The user's project shutdown script called `get_all_mca_windows()`
which found all open windows with "MCA" in the title — including the MCA Editor
itself — and closed them. Not a bug in the editor code.

---

## Files Modified

| File | Change |
|------|--------|
| `mca_qt/widgets/sidebar.py` | Tree state persistence (expanded paths, settings save/restore) |
| `mca_qt/editor_panel.py` | Tree state hooks, shortcut persistence, symbol indexing, color scheme, auto-reload, crash guards |
| `mca_qt/widgets/settings_dialog.py` | Shortcut persistence in `_save_settings()`, accepts `default_shortcuts` |
| `mca_qt/widgets/output_window.py` | QTimer RuntimeError guard in `_append_formatted` |
| `mca_maya/maya_window.py` | `_on_maya_output` RuntimeError guard |
| `mca_core/__init__.py` | New exports for symbol index |
| `mca_core/symbol_index.py` | **New file** — background symbol indexer |
| `mca_core/adapters/internal_maya_adapter.py` | Minor adapter changes |
| `mca_core/config/settings.py` | New settings keys |
| `mca_maya/plugin_main.py` | Plugin lifecycle updates |
| `mca_qt/widgets/code_editor.py` | Minor editor changes |
| `mca_qt/widgets/editor_group.py` | Minor group changes |

## Key Takeaway

When debugging UI visibility issues in Maya workspace controls:
1. `dockCloseEventTriggered` not firing means the control isn't formally closed
2. File-based debug logging (write to `%TEMP%`) captures output even after the
   UI disappears — `print()` output is lost when the editor window hides
3. Binary search with per-step visibility checks pinpoints the exact operation
4. Always check what the project's startup/shutdown scripts do!
