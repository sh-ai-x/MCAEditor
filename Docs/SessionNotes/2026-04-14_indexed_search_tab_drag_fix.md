# Session Notes — 2026-04-14: Indexed Search, Find in Files Seeding, Tab Drag Regression Fix

## Overview

Two rounds of work in one day:

1. **v1.0.14** — Routed Find in Files through the SymbolIndex, seeded
   Find/Replace in Files from the current editor selection, and fixed
   a post-drag tooltip regression on merged tabs.
2. **v1.0.15** — Hotfix for a Maya 2024 Windows regression introduced
   by v1.0.14's `setMovable(False)` change.  Restored native Qt tab
   reorder as a fallback on PySide2.

## v1.0.14 — Indexed Search + Find in Files Seeding

### Problem

- Ctrl+B (Find Usages) was fast (already indexed), but Ctrl+Shift+F
  (Find in Files) was slow — it was falling through to a filesystem
  walk instead of using the SymbolIndex.
- Find in Files always opened with an empty search box; users wanted
  highlighted text in the current editor to auto-populate and run.
- Dragging a tab between groups silently dropped its full-path hover
  tooltip.

### Fixes

**`mca_core/symbol_index.py`**
- Added `get_files_with_word(name)` — exact word match, O(1) set
  lookup.
- Added `get_files_containing_substring(substring, case_sensitive)` —
  iterates each file's `_file_words` frozenset looking for the
  substring.  Much faster than walking the filesystem because it
  only touches indexed files and only their word sets.

**`mca_qt/widgets/find_in_files.py`** (ships as `.pyc`)
- Three-tier optimization in `_on_search`:
  1. Regex mode → `get_all_files()` (skip `os.listdir` only).
  2. Whole-word + identifier → `get_files_with_word(pattern)`.
  3. Identifier fragment → `get_files_containing_substring(pattern,
     case_sensitive)`.
- Distinguishes `None` (no index / walk needed) from `[]` (index
  confirmed no hits) — fixed a bug where an empty candidate list fell
  back to a full filesystem walk.
- Status label now shows the candidate count: e.g.
  `"Searching 42 indexed file(s)..."`.
- New `initial_text` constructor param: when provided, the dialog
  pre-populates the search box, selects it, gives it focus, and
  auto-runs via `QTimer.singleShot(0, self._on_search)`.

**`mca_qt/editor_panel.py`** (ships as `.pyc`)
- `_current_selection_for_search()` helper — returns the current
  editor's selected text, stripped, only if it's single-line.
- `_find_in_files` / `_replace_in_files` now pass that selection as
  `initial_text` to the dialog.

**`mca_qt/widgets/editor_group.py`** (ships as `.pyc`)
- `SplittableTabBar.dropEvent` — restore `setTabToolTip` after
  `insertTab` so merged tabs keep their full-path hover text.  Qt
  does not carry tooltips across `insertTab`.

## v1.0.14 — Tab Drag Behavior Change (the cause of the 1.0.15 hotfix)

Changed `self._tab_widget.setMovable(False)` to prevent a "sticky
state" where Qt's built-in reorder kept tracking a press after our
custom QDrag ate the release, which was breaking subsequent clicks
(no focus transfer) and tooltips after any drag.

With `setMovable(False)`:
- Qt no longer dispatches in-bar tab reorder.
- All tab movement goes through our custom `QDrag` flow.
- Works reliably on PySide6.
- **Broke Maya 2024 Windows** — see v1.0.15 below.

## v1.0.15 — Hotfix for Maya 2024 Windows Tab Drag

### Problem

After v1.0.14 deployed, user reported: "Draging the tab does not work
in Maya 2024 Windows."  Other Maya versions (2025, 2026) were fine.

### Investigation

- Verified `qt_compat.py` patches `QDrag.exec` to call `exec_()` on
  PySide2 — confirmed working via SSH test on Mac Maya 2024.
- Verified `Qt.DropAction.MoveAction`, `Qt.MouseButton.LeftButton`,
  and other scoped enum patches — all applied correctly.
- Ruled out the qt_compat lambda patch as root cause (patch succeeds
  in isolation tests).
- Concluded: PySide2 on Windows has a QDrag binding quirk where the
  custom drag doesn't start reliably.  Since v1.0.14 made the custom
  QDrag the ONLY path, the failure became visible.

### Fix

Split tab-drag behavior by Qt binding in `editor_group.py`:

| Binding | setMovable | Below-threshold mouseMove | Rationale |
|---------|------------|---------------------------|-----------|
| PySide6 | `False` | Suppress `super()` | Custom QDrag is authoritative and works reliably. |
| PySide2 | `True` (respects `lock_tabs`) | Pass to `super()` | Qt's native reorder handles in-bar drags as a fallback. |

Also: call `drag.exec_()` directly on PySide2 instead of relying on
the qt_compat lambda patch, and wrap the exec call in a try/except
so a binding-level failure logs a warning instead of killing the
mouse handler.

Files changed:
- `mca_qt/widgets/editor_group.py` — import `PYSIDE_VERSION`, branch
  `setMovable` in `_setup_ui` and `apply_settings`, branch
  `super().mouseMoveEvent()` pass-through in `mouseMoveEvent`, branch
  `drag.exec`/`drag.exec_` + exception guard.
- `mca_core/__init__.py` — bump to 1.0.15.

## Builds / Deploys

| Target | Location | Version |
|--------|----------|---------|
| Windows Maya 2024/25/26 | `dist/MCAEditor-MayaXXXX-v1.0.15.zip` | 1.0.15 |
| Mac Maya 2024/25/26 | `~/Projects/MCAEditor/dist/MCAEditor-MayaXXXX-v1.0.15.zip` (built via SSH on Nathans-Mac-mini.local) | 1.0.15 |
| Unreal 5.5/5.6/5.7 | `dist/MCAEditor-UEX.X-v1.0.15.zip` | 1.0.15 |

## Commits

- `907e2ea` — v1.0.14: Indexed search, seeded Find in Files, tab drag/tooltip fixes
- `38054b7` — v1.0.15: Fix Maya 2024 Windows tab drag regression

## Test Results (confirmed by user)

- Windows Maya 2024 — tab drag works after v1.0.15.
- Windows Maya 2025, 2026 — working (unchanged from v1.0.14).
- Mac + Unreal — pending user test.

## Lessons

- `setMovable(False)` is a PySide6-only optimization — PySide2 still
  needs Qt's native reorder as a safety net because custom QDrag has
  binding quirks we can't easily detect at runtime.
- When a regression hits exactly one DCC version on one OS, suspect
  the Qt binding before suspecting the application code.  qt_compat
  patches are the first thing to verify, but they're not always the
  only difference.
- Fast candidate filtering via `_file_words` frozensets turns Find
  in Files from a filesystem walk into an in-memory set scan — the
  same pattern already used by Ctrl+B.
