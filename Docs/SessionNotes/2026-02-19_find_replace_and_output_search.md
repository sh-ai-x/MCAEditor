# Session: 2026-02-19 — PyCharm-Style Find/Replace & Output Search

## Summary
Redesigned the editor's find/replace bar to match PyCharm's compact layout, added an independent search bar to the output panel, and positioned the find bar as a right-aligned overlay directly under the tab strip.

## Changes Made

### New File: `mca_qt/widgets/find_replace_bar.py`
Full rewrite of the find/replace bar UI to match PyCharm's UX:
- **Expand/collapse toggle** (`▶`/`▼`) on the far left controls replace row visibility.
- **Inline clear buttons** on both find and replace fields via `setClearButtonEnabled(True)`.
- **Toggle buttons** relabeled: `Cc` (Match Case), `W` (Whole Word), `.*` (Regex) — placed immediately after the find field.
- **Up/Down arrows** (`↑`/`↓`) replace the old `<`/`>` nav buttons.
- **Compact counter**: `3/15` format instead of `3 of 15`.
- **Close button** (`✕`) moved to far right of the find row.
- **Overlay positioning**: The bar is a direct child of the QTabWidget (not in any layout), positioned right below the tab bar using manual geometry. Right-aligned, 450-580px wide, with an opaque `#2d2d30` background and rounded border.
- **Escape fix**: Event filter on both QLineEdits intercepts Escape before the clear-button-enabled QLineEdit consumes it.
- **`geometry_changed` signal**: Emitted when the replace row toggles so the parent can reposition the overlay.
- All existing search logic (incremental, debounced, regex, case, word) and public API preserved.

### Modified: `mca_qt/widgets/output_window.py`
Added `OutputSearchBar` class — a self-contained search bar for the read-only output panel:
- **Layout**: `[Find: ___(x)] [Cc] [.*] 3/15 [↑] [↓] [✕]` — no replace, no Whole Word.
- **Incremental search** with 150ms debounce, Match Case and Regex toggles.
- **Match highlighting** via `QPlainTextEdit.setExtraSelections()` with same color scheme as editor find (dim yellow for all matches, bright yellow for current).
- **Up/Down navigation** with wrap-around and auto-scroll to current match.
- **Escape handling** via event filter (same pattern as editor find bar).
- **Toggle access**: Search icon button (🔍) added to the output header bar, plus Ctrl+F routing from the editor panel.
- `clear()` now dismisses the search bar since content is gone.
- Removed `find_requested` signal from `_OutputTextEdit` — Ctrl+F is now routed by the panel's shortcut system.

### Modified: `mca_qt/editor_panel.py`
- **`_setup_find_bar()`**: Changed from `_center_layout.insertWidget()` to creating the find bar as an overlay child of `_tab_widget`. Installs event filter for resize tracking.
- **`_reposition_find_bar()`**: New method — positions the overlay right below the tab bar, right-aligned (450-580px wide, 8px right margin). Called on tab widget resize, find bar show, and replace row toggle.
- **`eventFilter()`**: Extended to handle `QEvent.Type.Resize` on the tab widget for overlay repositioning.
- **`_show_find()`**: Now checks `QApplication.focusWidget()` — if focus is inside the output panel, routes Ctrl+F to `self._output.toggle_search_bar()` instead of the editor find bar. Calls `_reposition_find_bar()` after showing.
- **`_show_replace()`**: Calls `_reposition_find_bar()` after showing.

### Modified: `mca_qt/widgets/code_editor.py`
- Added `_search_selections` attribute and `set_search_selections()` method for find bar integration.
- Search highlights merged into `setExtraSelections()` alongside bracket-matching, word-matching, and diagnostics.
- Added `focusOutEvent()` to dismiss the completer popup when focus leaves the editor.

### Modified: `mca_qt/widgets/__init__.py`
- Added `FindReplaceBar` to the package exports.

## Design Decisions
- **Overlay vs layout**: The find bar is an overlay (child widget with manual geometry) rather than a layout item. This avoids restructuring the QTabWidget and matches how PyCharm/VS Code actually implement their find bars — floating above editor content.
- **Ctrl+F routing**: Instead of having the output handle Ctrl+F via `keyPressEvent` (which conflicts with the panel's `WidgetWithChildrenShortcut` action), focus detection in `_show_find()` routes to the correct search bar.
- **Right-aligned, compact**: The find bar doesn't span the full editor width — it's 450-580px wide, right-aligned, matching PyCharm's floating panel aesthetic.
- **Escape event filter**: `QLineEdit.setClearButtonEnabled(True)` causes the line edit to consume Escape to clear text. The event filter intercepts Escape before the QLineEdit processes it.

## Known Issues / Future Work
- The overlay find bar covers the first 1-2 lines of editor content when visible (standard behavior in PyCharm/VS Code).
- Find in Files and Replace in Files are still stubbed out ("coming soon").
- Output search doesn't have Whole Word toggle (intentional — output text is freeform).
