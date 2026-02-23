# Session: 2026-02-22 — Drag-and-Drop Tab Splitting (PyCharm/VS Code Style)

## Summary
Replaced the old "drag 40px outside the tab bar" hack with a real drag-and-drop
tab splitting system. Tabs can now be dragged to any edge of any editor group
to create horizontal or vertical splits, dragged onto another group's tab bar
to merge, or dragged to the center to combine groups. A transparent overlay
shows the five drop zones with visual highlights during drag.

## Problem
The previous system (`SplittableTabBar`) just checked if the mouse moved 40px
vertically outside the tab bar and blindly created a new group to the right.
No visual feedback, no directional control, no merge support, and the splitter
tree was flat (horizontal only).

## Architecture

### New Files
- **`mca_qt/widgets/drop_zone_overlay.py`** — `DropZone` enum (NONE, LEFT,
  RIGHT, TOP, BOTTOM, CENTER) + `DropZoneOverlay(QWidget)` that paints
  semi-transparent blue highlights over the target group during drag.
  Zone geometry: top/bottom 25%, left/right 25% of middle, center remainder.

- **`mca_qt/widgets/drag_tab_manager.py`** — `DragTabManager(QObject)` installed
  as event filter on every EditorGroup. Owns the overlay instance. Intercepts
  DragEnter/DragMove/DragLeave/Drop events. Executes `_merge_tab()` (CENTER
  zone) or `_split_tab()` (directional zones) on drop. MIME type:
  `application/x-mca-editor-tab` with JSON payload `{source_group_id, tab_index}`.

### Modified Files
- **`mca_qt/qt_compat.py`** — Added `QDrag`, `QMimeData`, `QByteArray` imports.
  PySide2 enum patches for DragEnter/DragMove/DragLeave/Drop, DropAction
  (MoveAction, IgnoreAction, CopyAction), WA_TransparentForMouseEvents,
  WA_NoSystemBackground.

- **`mca_qt/widgets/editor_group.py`** — Complete rewrite of `SplittableTabBar`:
  replaced mouse-position tracking with QDrag + QMimeData. Tab bar accepts drops
  for merge-at-position with blue insertion indicator. `EditorGroup` gains
  `group_id()`, `drag_started` signal, directional split signals
  (`split_left_requested`, `split_down_requested`, `split_up_requested`), and
  a "Split Editor" submenu (Right/Left/Down/Up) in the tab context menu.

- **`mca_qt/widgets/editor_group_container.py`** — Replaced flat horizontal
  `QSplitter` with recursive splitter tree. Core `split_group(target, orientation,
  before)` handles same-orientation insertion and orientation-mismatch nesting.
  `_simplify_splitter()` collapses single-child splitters after group removal.
  `DragTabManager` installed on every group. Recursive `get_layout_state()` /
  `restore_layout_state()` for serialization.

- **`mca_core/session_manager.py`** — Bumped to `MANIFEST_VERSION = 3`. Added
  `save_manifest_v3(layout_tree, active_group_index)` with nested splitter/group
  tree format. `upgrade_manifest()` handles v1 → v2 → v3 chain.

- **`mca_qt/editor_panel.py`** — Rewrote `_save_session_manifest()` to walk the
  recursive layout tree and fill tab data per group. Rewrote `_restore_session()`
  to rebuild splitter tree from v3 layout and populate tabs in DFS order.

- **`mca_qt/widgets/__init__.py`** — Added `DropZoneOverlay`, `DropZone`,
  `DragTabManager` exports.

## Key Bug Fix: Tab Drag Conflicts with Qt's Movable Tabs
The initial implementation had two bugs:

1. **Horizontal drag didn't trigger QDrag** — The tab bar spans the full panel
   width, so dragging sideways never left its bounds. Fixed by using **manhattan
   distance from the press point** instead of distance from tab bar edges.

2. **Tab disappeared on cancelled drag** — Qt's built-in `setMovable(True)` tab
   reorder was silently changing tab indices while our MIME payload carried the
   original index. `take_editor()` then removed the wrong tab. Fixed by **never
   calling `super().mouseMoveEvent()`** when a drag candidate exists, preventing
   Qt's internal reorder from activating.

## V3 Session Manifest Format
```json
{
    "version": 3,
    "next_buffer_id": 5,
    "layout": {
        "type": "splitter",
        "orientation": "horizontal",
        "sizes": [400, 600],
        "children": [
            {"type": "group", "tabs": [...], "active_tab": 0},
            {"type": "splitter", "orientation": "vertical", "sizes": [300, 300],
             "children": [
                {"type": "group", "tabs": [...], "active_tab": 0},
                {"type": "group", "tabs": [...], "active_tab": 1}
             ]}
        ]
    },
    "active_group": 0
}
```

## Testing
1. `python run.py` — launches without errors
2. Drag tab to right/left/top/bottom of editor → creates correct split
3. Drag tab to center of another group → merges into that group
4. Drag tab onto another group's tab bar → merges at cursor position
5. Drag tab sideways directly to adjacent panel → QDrag triggers immediately
6. Drag tab out and back → tab stays in place (no disappearing)
7. Close all tabs in a split group → group collapses, splitter simplifies
8. Close and reopen → all splits, positions, and tabs restored exactly
9. Existing v2 session.json auto-upgrades to v3 on load
