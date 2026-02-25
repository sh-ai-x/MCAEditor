# Session: 2026-02-25 — Workspace & Buffer Unification

## Summary
Unified the workspace tree sidebar with the buffer/tab system. The workspace
is now locked to `mca_preferences/scripts/`, buffer files are stored there
(visible in the tree), and the directory is added to `sys.path` for imports.
Also renamed buffer files from `buffer_N.ext` to `Language_N.ext` so tab
names match filenames, added file rename propagation to open tabs, and made
the sidebar panels resizable with a vertical splitter.

## Key Changes

### Buffer Storage Moved to scripts/ (`mca_core/session_manager.py`)
- `_buffers_dir` now points to `scripts/` instead of the old `buffers/`
- `_ensure_dirs()` also creates `site-packages/` inside scripts
- Added `migrate_buffers_to_scripts()` — one-time migration moves
  `buffer_*.{py,mel,txt}` files from legacy `buffers/` to `scripts/`,
  then removes the empty `buffers/` directory
- Buffer filenames changed: `buffer_1.py` → `Python_1.py`, `MEL_2.mel`, etc.
- Added `LANGUAGE_PREFIXES` map alongside existing `LANGUAGE_EXTENSIONS`

### Workspace Locked to scripts/ (`mca_qt/editor_panel.py`)
- Rewrote `_init_default_workspace()` to call `set_locked_folder(scripts_dir)`
  instead of restoring user-selected folders from settings
- Added `scripts/` to `sys.path` (not just `site-packages/`)
- Terminal widget now starts in `scripts/` directory via `cwd` param
- Maya adapter configured with workspace paths for `sys.path` injection
- Migration called before session restore so buffer files are in place

### sys.path Injection for Imports
- **Local execution** (`_execute_locally()`): ensures both `scripts/` and
  `site-packages/` are on `sys.path` before `exec()`
- **Maya TCP** (`maya_adapter.py`): `set_workspace_paths()` stores paths,
  `_wrap_python_for_port()` injects `sys.path.insert()` into the wrapper
- **Maya Internal** (`internal_maya_adapter.py`): `set_workspace_paths()`
  adds paths directly to `sys.path` (no wrapper needed, same process)

### Sidebar Changes (`mca_qt/widgets/sidebar.py`)
- Removed "+" add-folder button, replaced with "R" refresh button
- Added `set_locked_folder(folder_path)` method on `WorkspacePanel`
- Updated empty state label text
- Added `file_renamed` signal (str, str) — emitted after successful rename
- Replaced `QVBoxLayout` with `QSplitter` for the three sidebar panels
  (Workspace, Open Editors, Outline) so they can be dragged to resize

### Tab Naming (`Python_1`, `MEL_2`, etc.)
- Buffer IDs allocated eagerly in `_new_buffer()` (not lazily on first save)
- Tab name format: `{Language}_{id}` matching the on-disk filename stem
- `_new_python_buffer()`, `_new_mel_buffer()`, `_new_text_buffer()` all
  use the new naming
- `_on_language_changed()` includes buffer ID when renaming via combo box
- Session restore parses IDs with `rsplit("_", 1)` for both old/new formats

### File Rename → Tab Update
- `WorkspacePanel._rename_path()` emits `file_renamed(old_path, new_path)`
- Signal forwarded through `MCASidebar` to `MCAEditorPanel`
- `_on_file_renamed()` handler updates:
  - File-backed tabs: `editor.file_path`, tab text, icon, tracking entry
  - Buffer tabs: `_buffer_filename`, tab text, tracking entry
  - Session manifest saved after rename

### First Launch Defaults
- Fresh install (no session) now opens with two tabs: Python_1 and MEL_1
  (previously just a single Python tab)

### Settings Comments (`mca_core/config/settings.py`)
- `workspace_folders`, `last_workspace`, `recent_workspaces` marked as
  reserved for future Project mode

## Files Modified
| File | Changes |
|------|---------|
| `mca_core/session_manager.py` | Buffer dir → scripts/, migration, new naming |
| `mca_qt/editor_panel.py` | Lock workspace, sys.path, migration, rename handler, starter tabs |
| `mca_qt/widgets/sidebar.py` | Remove "+", add refresh, locked folder, rename signal, splitter |
| `mca_core/adapters/maya_adapter.py` | `set_workspace_paths()`, sys.path wrapper injection |
| `mca_core/adapters/internal_maya_adapter.py` | `set_workspace_paths()` for in-process mode |
| `mca_core/config/settings.py` | Comment updates for reserved keys |

## Testing Notes
- Verified 5 existing buffers migrated from `buffers/` to `scripts/`
- Legacy `buffers/` directory cleaned up automatically
- Session restore works with both old `buffer_*` and new `Language_*` filenames
- App launches cleanly with no errors
- pywinpty terminal note: won't work inside Maya (needs alternative approach)
