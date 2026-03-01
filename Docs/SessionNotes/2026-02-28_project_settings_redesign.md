# Session: Project Settings Redesign + Smart Project Loading — 2026-02-28

## Summary

Redesigned the Project Settings dialog to use a left-nav + stacked pages
layout (matching the app Settings dialog pattern), added smart project
loading to prevent double-loading in Maya, and added auto-open and a
Load toolbar button.

## Feature 1: Smart Project Loading

### Problem
When Maya already has the user's codebase loaded (env vars set, sys.path
populated), opening a project in MCA Editor ran startup scripts again,
causing duplicate imports and errors.

### Solution
- **`_is_project_already_active()`** in `editor_panel.py` — checks that
  every project env var exists in `os.environ` with the correct value
  AND every resolved Python path is already in `sys.path`.
- **Conditional startup in `_apply_project_mode()`** — skips startup
  scripts if `project.load_immediately` is True or the environment is
  already active. Writes informative skip reason to output panel.
- UI setup (workspace tree, buttons, paths, env vars, terminal cwd)
  always runs regardless of skip.

## Feature 2: Load Toolbar Button

### Layout
`[Load] [Refresh] [Reload] [Shutdown]` — Load is new, appears first.

### Behavior
- Force-runs `_run_startup_script()` regardless of `load_immediately`
  flag or environment state.
- Use case: user opened project with `load_immediately` checked, now
  wants to manually trigger startup.
- Writes "Running project startup..." to output.

## Feature 3: Project Settings Dialog Redesign

### Old Layout
Single scrolling page with GroupBoxes and an internal Startup/Shutdown
QTabWidget.

### New Layout
Left-nav `QListWidget(fixedWidth=140)` + `QStackedWidget` with 3 pages:

- **General**: Project name, project root (read-only), two new
  checkboxes, Python source paths, excluded folders, environment
  variables.
- **Startup**: Script file path + Browse button, inline code editor.
- **Shutdown**: Script file path + Browse button, inline code editor.

### New Checkboxes
- **"Load project immediately"** — skip startup scripts on project open.
- **"Open project on editor open"** — auto-open this project when the
  editor launches.

## Feature 4: Auto-Open Project on Editor Open

- `_auto_open_last_project()` reads `last_project_path` from settings,
  loads the MCAProject, checks `open_on_editor_open`, and calls
  `_open_project()` if True.
- Fired via `QTimer.singleShot(200)` at end of `__init__` — the 200ms
  delay ensures it fires AFTER `showEvent`'s deferred
  `_restore_splitter_sizes` (singleShot(0)), preventing a race that
  collapsed sidebar/output on first open.
- After opening, re-applies `_restore_ui_state()` and defers another
  `_restore_splitter_sizes()` because the layout rebuild inside
  `_switch_to_manifest` can trigger Qt re-layout that collapses panels.

## Project Model Changes (`mca_core/project.py`)

- Bumped `CURRENT_SCHEMA_VERSION` from 2 to 3.
- Added `_load_immediately` and `_open_on_editor_open` instance vars
  (default False), with property getters/setters.
- Updated `load()` to read both keys with False defaults.
- Updated `to_dict()` to serialize both keys.

## Files Changed

| Action | File | Changes |
|--------|------|---------|
| MODIFY | `mca_core/project.py` | Schema v3, `load_immediately` + `open_on_editor_open` properties, serialization |
| REWRITE | `mca_qt/widgets/project_settings_dialog.py` | Left-nav layout, 3 pages, 2 new checkboxes, nav list styling |
| MODIFY | `mca_qt/editor_panel.py` | `_is_project_already_active()`, conditional startup, Load button, `_auto_open_last_project()`, timing fix |
| CREATE | `Docs/SessionNotes/2026-02-28_project_settings_redesign.md` | This file |
