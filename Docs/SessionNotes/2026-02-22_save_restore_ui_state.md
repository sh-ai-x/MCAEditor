# Session: 2026-02-22 — Save & Restore All UI State

## Summary
Implemented full persistence and restoration of the editor's UI layout so the
window reopens in the exact same state it was closed in. Previously many
settings were saved on close but never restored on startup, and some (center
splitter, panel visibility) were never saved at all.

## Problem
| UI State | Was Saved? | Was Restored? |
|----------|------------|---------------|
| Window geometry/position | Yes (closeEvent) | **No** |
| Main splitter sizes | Yes (save_window_state) | **No** |
| Center splitter sizes (output/tabs) | **No** | **No** |
| Font size / zoom level | Yes (on zoom) | **No** (hardcoded 12) |
| Show whitespace | Yes (on toggle) | **No** (action unchecked) |
| Output visibility | **No** | **No** |
| Sidebar visibility | **No** | **No** |
| AI panel visibility | **No** (key existed unused) | **No** |

## Changes Made

### `mca_core/config/settings.py`
- Added 3 new default keys to `_DEFAULTS`:
  - `center_splitter_sizes` (None) — vertical splitter between output and editor
  - `output_visible` (True) — whether the output panel is shown
  - `sidebar_visible` (True) — whether the sidebar is shown in Advanced mode

### `mca_qt/editor_panel.py` (Maya embedded panel)
- **Font init**: `_default_font_size` reads from `settings.get("font_size", 12)`
  instead of hardcoded `12`
- **`_restore_ui_state()`**: New method that restores main/center splitter sizes,
  sidebar/output/AI visibility, whitespace toggle, and font zoom level. Called
  after `_apply_editor_mode()`.
- **Toggle persistence**: `_toggle_sidebar()`, `_toggle_output()`, `_toggle_ai_panel()`
  now save their visibility state to settings immediately on toggle.
- **`save_window_state()`**: Expanded to also persist `center_splitter_sizes` and
  all three visibility flags (output, sidebar, AI panel).
- **`_apply_editor_state()`**: New helper that applies current font size and
  whitespace rendering to a single editor widget.
- **`_new_buffer()` / `_open_file_path()`**: Both call `_apply_editor_state()` so
  newly created tabs inherit the session's zoom and whitespace state.

### `mca_editor/ui/main_window.py` (standalone window)
- **Font init**: Same as editor_panel — reads from settings.
- **`_restore_ui_state()`**: Same restore method, called after sidebar/output
  position restore in `__init__`.
- **Geometry restore**: `restoreGeometry()` now called on startup from saved
  `window_geometry`.
- **Toggle persistence**: Same as editor_panel.
- **`closeEvent()`**: Expanded to save `splitter_sizes`, `center_splitter_sizes`,
  and all visibility flags alongside geometry.
- **`_apply_editor_state()`**: Same helper as editor_panel.
- **`_new_buffer()` / `_open_file_path()`**: Both call `_apply_editor_state()`.

## Key Design Decision
`_restore_ui_state()` runs **after** `_apply_editor_mode()` in both files. This
ordering is critical because mode application resets panels to their mode
defaults (Simple hides sidebar/AI, Advanced shows sidebar). The saved state must
override those defaults so the user's last layout is accurately reproduced.

## Testing
1. `python run.py` — launches standalone editor with no errors
2. Resize window, drag splitters, hide output, toggle whitespace, zoom in
3. Close and reopen — all state restored exactly
4. Maya embedded mode uses the same `_restore_ui_state()` / `save_window_state()`
   path via the host calling those methods
