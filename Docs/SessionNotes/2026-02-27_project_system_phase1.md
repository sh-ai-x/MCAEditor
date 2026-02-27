# Session: Project System Phase 1 — 2026-02-27

## Summary

Implemented the full Phase 1 (Foundation) of the Project System. Removed the
Simple/Advanced mode toggle entirely — the sidebar now always starts visible
and is controlled by the left tool stripe button. The old mode button is
repurposed as a Project button with a dropdown menu. Users can open any folder
as a project, with sys.path management, folder exclusion, startup scripts,
environment variables, and a full Project Settings dialog.

## Removed: Simple/Advanced Mode

- Deleted `_editor_mode`, `_apply_editor_mode()`, `_toggle_mode()`,
  `_set_editor_mode()` from `editor_panel.py`
- Removed Simple Mode / Advanced Mode checkable actions from View menu
- Deprecated `EditorMode` enum in `settings.py` (kept for import compat)
- Removed `get_editor_mode()` / `set_editor_mode()` from `MCASettings`
- Sidebar always starts visible; visibility controlled by left tool stripe

## New: Project System

### Core Model (`mca_core/project.py`) — NEW FILE
- `MCAProject` class — loads/saves `.mca-project` JSON files
- Properties: `name`, `project_root`, `python_paths`, `resolved_python_paths`,
  `excluded_folders`, `startup_script`, `resolved_startup_script`, `env_vars`
- Methods: `load()`, `save()`, `validate()`, `to_dict()`
- Helper functions: `has_project_file()`, `detect_python_paths()`,
  `create_default_project()`
- Constants: `PROJECT_FILENAME`, `DEFAULT_EXCLUDED_FOLDERS`, `PYTHON_PATH_HINTS`

### Settings Changes (`mca_core/config/settings.py`)
- Added defaults: `recent_projects` (list), `last_project_path` (string)
- Added methods: `get_recent_projects()`, `add_recent_project()`,
  `get_last_project_path()`, `set_last_project_path()`

### Adapter Changes
- **`base_adapter.py`**: Added `_project_paths` list, `set_project_paths()`,
  `clear_project_paths()`
- **`maya_adapter.py`**: Overrides store paths + inject into
  `_wrap_python_for_port()` wrapper; `clear_project_paths()` sends
  `sys.path.remove()` to Maya over TCP
- **`internal_maya_adapter.py`**: Overrides do direct `sys.path.insert()`
  / `sys.path.remove()` in Maya's process

### Sidebar Changes (`mca_qt/widgets/sidebar.py`)
- `WorkspacePanel`: stored `_header_title` label as instance var, added
  `_excluded_folders` set, `set_header_title()`, `set_excluded_folders()`
- `_populate_folder()` now skips directories in `_excluded_folders`
- `MCASidebar`: added `set_workspace_title()`, `set_excluded_folders()` forwarding

### Create Project Dialog (`mca_qt/widgets/create_project_dialog.py`) — NEW FILE
- `CreateProjectDialog` — shown when opening a folder without `.mca-project`
- Project name field (defaults to folder name)
- Checkable list of auto-detected Python paths
- OK / Cancel

### Project Settings Dialog (`mca_qt/widgets/project_settings_dialog.py`) — NEW FILE
- `ProjectSettingsDialog` — edits an active project's configuration
- Sections: General (name, root), Python Source Paths (add/remove),
  Excluded Folders (add/remove), Startup Script (text + browse),
  Environment Variables (add/edit/remove with Name/Value sub-dialog)
- `_EnvVarDialog` — separate Name and Value fields; Browse Path button;
  auto-normalizes values that look like filesystem paths

### Editor Panel Changes (`mca_qt/editor_panel.py`)
- Replaced mode button with Project button ("No Project" / project name)
- Added Refresh button (visible only when project active)
- Project button click opens dropdown: Open Project, Recent Projects,
  Project Settings, Close Project
- File menu: added "Open Project..." and "Recent Projects" submenu
- New methods: `_show_project_menu()`, `_open_project_dialog()`,
  `_open_project()`, `_close_project()`, `_apply_project_mode()`,
  `_inject_project_paths()`, `_remove_project_paths()`,
  `_apply_env_vars()`, `_remove_env_vars()`, `_run_startup_script()`,
  `_on_refresh_project()`, `_show_project_settings()`,
  `_build_recent_projects_menu()`, `_populate_recent_projects_submenu()`
- Env vars cleanly restored on close (original values saved/restored)
- Startup script runs after path injection via active adapter or locally
- Terminal cwd set to project root on open, scripts/ on close

### Host Window Changes
- **`standalone_window.py`**: Title bar shows "MCA Editor -- ProjectName",
  status bar shows project name or "No Project"
- **`maya_window.py`**: Same title/status bar changes

## Bugfix

- Fixed `triggered` signal lambda in recent projects menu — added
  `checked=False` default to handle PySide6's no-arg `triggered` overload

## .mca-project File Format

```json
{
    "schema_version": 1,
    "name": "MyProject",
    "python_paths": ["src", "."],
    "excluded_folders": ["__pycache__", ".git", "build"],
    "startup_script": "scripts/startup.py",
    "env_vars": {
        "PYTHONDONTWRITEBYTECODE": "1"
    }
}
```

## Files Changed

| Action | File |
|--------|------|
| CREATE | `mca_core/project.py` |
| CREATE | `mca_qt/widgets/create_project_dialog.py` |
| CREATE | `mca_qt/widgets/project_settings_dialog.py` |
| MODIFY | `mca_core/config/settings.py` |
| MODIFY | `mca_core/adapters/base_adapter.py` |
| MODIFY | `mca_core/adapters/maya_adapter.py` |
| MODIFY | `mca_core/adapters/internal_maya_adapter.py` |
| MODIFY | `mca_qt/widgets/sidebar.py` |
| MODIFY | `mca_qt/editor_panel.py` |
| MODIFY | `mca_standalone/standalone_window.py` |
| MODIFY | `mca_maya/maya_window.py` |
| CREATE | `Docs/SessionNotes/2026-02-27_project_system_phase1.md` |
