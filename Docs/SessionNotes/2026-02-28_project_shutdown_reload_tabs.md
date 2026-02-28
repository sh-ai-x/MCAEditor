# Session Notes — 2026-02-28: Project Shutdown, Reload & Tab Context-Switching

## Summary

Added project shutdown scripts, reload/shutdown toolbar buttons, duplicate-open guard,
and tab context-switching (save/restore tabs when opening/closing projects).

## Changes

### `mca_core/project.py`
- Added `shutdown_script` and `shutdown_code` fields (mirroring startup)
- Added `resolved_shutdown_script` read-only property
- Updated `load()`, `to_dict()`, `validate()` to include shutdown fields
- Bumped `CURRENT_SCHEMA_VERSION` from 1 to 2 (backward-compatible via `.get()` defaults)

### `mca_qt/widgets/project_settings_dialog.py`
- Replaced separate Startup/Shutdown group boxes with a tabbed "Scripts" QGroupBox
- `QTabWidget` with "Startup" and "Shutdown" tabs, each with script path + inline code
- Added `_browse_shutdown_script()` method
- Updated `_on_save()` to include `shutdown_script` and `shutdown_code` in result dict

### `mca_qt/editor_panel.py`
- **Toolbar buttons**: Added Reload and Shutdown `QAction` buttons (visible when project active)
- **Duplicate-open guard**: `_open_project()` early-returns if the same project is already open
- **`_run_shutdown_script()`**: Mirrors `_run_startup_script()` — runs script file then inline code
- **`_on_reload_project()`**: Remembers project root, closes, re-opens
- **Tab context-switching**:
  - `_open_project()`: calls `_save_context_session()` before switching, then loads project manifest via `_switch_to_manifest()`
  - `_close_project()`: saves project tabs, then restores default workspace tabs
  - `_switch_to_manifest()`: re-syncs active group index and sets editor focus after rebuild
- **`_show_project_settings()`**: Applies shutdown fields from dialog result

### `mca_qt/widgets/editor_group.py`
- Changed `current_editor()` from `isinstance(widget, MCACodeEditor)` to
  `type(widget).__name__ == "MCACodeEditor"` — survives plugin reloads where
  class identity changes

### `mca_core/session_manager.py`
- Added `save_manifest_to(filepath, ...)` for writing per-project session files
- Added `load_manifest_from(filepath)` for reading per-project session files

## Bugs Encountered & Fixed

### QAction ownership crash
- `toolbar.addAction("text")` returns QAction with weak PySide6 ownership — GC deletes the C++ object
- Fix: `QAction("text", self)` with explicit parent, then `toolbar.addAction(action)`

### Session file corruption
- QAction crash aborted `_open_project` mid-flight, causing default tabs to be written into
  the project's `.mca-session.json`
- Fix: manually restored file; understood failure mode

### isinstance fails after plugin reload
- `isinstance(widget, MCACodeEditor)` returns False when the class has been re-defined by a
  module reload — the old instance's class object differs from the newly imported one
- Fix: use `type(widget).__name__ == "MCACodeEditor"` instead

### Tab switching appeared broken (was actually working)
- Both session files (default `session.json` and project `.mca-session.json`) contained
  identical tab lists due to earlier corruption, making it look like tabs weren't switching
- Fix: cleared the project session file to prove switching worked, then let normal save
  operations populate it correctly

## Key Lessons

- **PySide6 QAction**: Always create with explicit parent (`QAction("text", parent_widget)`)
  to prevent premature GC
- **Plugin reload + isinstance**: Class identity changes across reloads; use name-based checks
  for cross-reload compatibility
- **Debug with output panel**: Writing diagnostic `[tag]` messages to the editor's output panel
  is the fastest way to debug issues in Maya-hosted plugins
- **Session file identity**: When tab switching "doesn't work", verify the two manifest files
  actually contain different content

## Execution Order

**Startup** (unchanged): inject paths -> apply env vars -> run startup script -> run inline code

**Shutdown** (new): save project tabs -> run shutdown script -> run inline code -> remove env vars -> remove paths -> restore default tabs -> reset UI

**Reload**: full shutdown -> full startup
