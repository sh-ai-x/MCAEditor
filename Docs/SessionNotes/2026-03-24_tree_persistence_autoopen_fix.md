# 2026-03-24 — File Tree Persistence, Auto-Open Fix, Symbol Completion

## Summary

Three major fixes this session:

1. **File tree lazy loading** — Replaced 5-level depth limit with unlimited on-demand loading
2. **Tree state persistence** — Workspace folders and expanded paths now survive Maya restarts
3. **Editor auto-open fix** — Editor no longer reopens when user explicitly closed it
4. **Code completion** — Project-wide symbol index wired into completion provider

---

## 1. File Tree — Lazy On-Demand Loading

### Problem
File trees were capped at `MAX_TREE_DEPTH = 5`. Deep folder structures (e.g., `rigging/flags/`, `rigging/frag/`) were inaccessible.

### Fix
- Removed `MAX_TREE_DEPTH` constant
- `_populate_folder()` now loads ONE level only, with a `__MCA_PLACEHOLDER__` sentinel child
- `_ensure_populated()` replaces the placeholder with real children on first expand
- `setChildIndicatorPolicy(ShowIndicator)` forces expand arrows on all folders
- Added `ChildIndicatorPolicy` enum patch to `qt_compat.py` for PySide2 (Maya 2024)

### Files Changed
- `mca_qt/widgets/sidebar.py` — lazy loading, `_ensure_populated`, `_is_placeholder`
- `mca_editor/ui/sidebar.py` — same lazy loading pattern for standalone/UE editor
- `mca_qt/qt_compat.py` — `QTreeWidgetItem.ChildIndicatorPolicy` enum patch

---

## 2. Tree State Persistence

### Problem
Expanded folders reset to defaults on Maya restart. Two root causes:

1. **`set_locked_folder()` wiped workspace folders** — User-added folders beyond the project root were lost on every project reopen
2. **Lazy loading broke the restore loop** — `_iter_all_items()` only saw first-level items; deeper folders hadn't been populated yet

### Root Cause Discovery
Debug logging in `_refresh_tree()` (writing to `~/tree_restore_log.txt`) revealed:
- 5 calls to `_refresh_tree()` during startup (3 redundant)
- Final call had 16 saved expanded paths but only 1 workspace folder (project root)
- 13 of 16 paths were under `E:\MCA\...` (user-added folder), not the project root
- Only 3 paths matched items in the tree

### Fix
- **Workspace folders saved per-project** in QSettings via `tree_folders_<project>` key
- **Fallback** to global `workspace_folders` key for backward compatibility (first run)
- **`restore_tree_state_from_settings()`** merges saved folders back into `_workspace_folders`
- **`_set_locked_folder_no_refresh()`** new method that sets workspace without rebuilding
- **`_apply_project_mode()`** reduced from 3 tree rebuilds to 1: sets locked folder, excluded folders, and expanded paths, then single `_refresh_tree()`
- **`_refresh_tree()` restore loop** calls `_ensure_populated()` explicitly before `setExpanded(True)` — doesn't rely on `itemExpanded` signal (which may not fire during `__init__` when widget isn't visible)

### Files Changed
- `mca_qt/widgets/sidebar.py` — `save_tree_state_to_settings`, `restore_tree_state_from_settings`, `_set_locked_folder_no_refresh`, `_refresh_tree`
- `mca_qt/editor_panel.py` — `_apply_project_mode` refactored

---

## 3. Editor Auto-Open Fix

### Problem
User closes editor, closes Maya, reopens Maya — editor opens anyway.

### Root Cause
Maya's workspace control `uiScript` calls `_restore_mca_editor()` during layout restore, bypassing the `editor_was_open` check that only gates `_do_auto_open_editor()`.

### Fix
Added `editor_was_open` check at the top of `_restore_mca_editor()`:
- If `False`, hides the workspace control and returns immediately
- If `True`, proceeds with normal widget creation

### Files Changed
- `mca_maya/maya_window.py` — `_restore_mca_editor()` now checks `editor_was_open`

---

## 4. Code Completion — Project Symbol Index

### Problem
Completions only showed keywords and words from the current document, not symbols from project files.

### Fix
- Added `find_by_prefix()` to `SymbolIndex` — returns `(name, kind, filepath)` tuples for prefix matches
- Added `set_symbol_index()` to `CompletionProvider` — Source 3: project symbols (priority 2)
- Wired in `_start_symbol_indexing()` / `_stop_symbol_indexing()` in `editor_panel.py`
- Bumped `_MAX_DEPTH` in `symbol_index.py` from 5 to 15

### Files Changed
- `mca_core/symbol_index.py` — `find_by_prefix()`, `_MAX_DEPTH = 15`
- `mca_qt/widgets/completer.py` — `set_symbol_index()`, Source 3 insertion
- `mca_qt/editor_panel.py` — wiring in `_start_symbol_indexing`

---

## Builds & Deployment

- Version bumped: 1.0.3 → 1.0.4
- Built all 6 variants: Maya 2024/2025/2026 x Windows/macOS
- macOS builds done on Mac Mini via SSH (code transferred via SCP)
- All zips uploaded to VPS `/downloads/maya/` via `deploy_website.py`
- Website rebuilt and deployed with updated changelog
- Pushed to GitHub

---

## Files Changed

| File | Change |
|------|--------|
| `mca_core/__init__.py` | Version bump to 1.0.4 |
| `mca_core/symbol_index.py` | `find_by_prefix()`, `_MAX_DEPTH = 15` |
| `mca_qt/widgets/sidebar.py` | Lazy loading, tree state persistence, workspace folder save/restore |
| `mca_qt/widgets/completer.py` | Project symbol completions via SymbolIndex |
| `mca_qt/editor_panel.py` | Symbol index wiring, `_apply_project_mode` optimization |
| `mca_qt/qt_compat.py` | `ChildIndicatorPolicy` enum patch |
| `mca_editor/ui/sidebar.py` | Lazy loading for standalone/UE editor |
| `mca_maya/maya_window.py` | `_restore_mca_editor` checks `editor_was_open` |
| `CHANGELOG.md` | v1.0.4 entry |
