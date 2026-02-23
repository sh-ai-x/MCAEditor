# Session: 2026-02-22 — Workspace Tree Drag-and-Drop File Moving

## Summary
Added drag-and-drop support to the workspace tree sidebar so users can move
files and folders between directories by dragging them onto folder items.
Also removed noisy "Saved" log messages from the output panel.

## Changes

### Workspace Tree Drag-and-Drop (`mca_qt/widgets/sidebar.py`)
- Created `_WorkspaceTree(QTreeWidget)` subclass with drag-drop handling
- Uses `QAbstractItemView.DragDropMode.InternalMove` for built-in drag support
- `dragEnterEvent` — accepts drags originating from within the tree only
- `dragMoveEvent` — accepts when hovering over any existing file/folder item
- `dropEvent` — resolves file targets to parent folder, validates the move,
  calls `shutil.move()`, and emits `file_moved(old_path, new_path)` signal
- Validation rules:
  - Source path must exist
  - Target must resolve to a directory
  - Destination must not already exist (shows warning dialog)
  - Cannot move a folder into itself or a subdirectory of itself
  - No-op if source is already in the target folder
- `WorkspacePanel` replaced `QTreeWidget()` with `_WorkspaceTree()` and
  connected `file_moved` signal to `_on_file_moved()` which refreshes the tree
- Added `QAbstractItemView` to the import block

### Removed Noisy Save Messages
- **`mca_qt/editor_panel.py`** — Removed `write_info("Saved: ...")` from
  `_write_file()` and downgraded `logger.info` to `logger.debug`
- **`mca_editor/ui/main_window.py`** — Same changes as above
- Drag-drop log messages in sidebar also set to `logger.debug`

## Testing
1. Drag a file onto a folder — file moves on disk, tree refreshes
2. Drag a folder onto another folder — folder moves inside it
3. Drag a file onto another file — moves into that file's parent folder
4. Drag a folder into itself — rejected (no-op)
5. Drag a file to same parent folder — rejected (no-op)
6. Drag item where destination name exists — shows warning dialog
7. No more "Saved" messages in output panel when running scripts
