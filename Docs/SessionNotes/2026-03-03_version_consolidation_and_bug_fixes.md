# Session Notes — 2026-03-03: Version Consolidation & Bug Fixes

## Summary
Consolidated the version string to a single source of truth, fixed several
editor bugs (Ctrl+C in output, Ctrl+B navigation, auto-reload noise), and
improved the Go to Declaration popup UX.

---

## Changes

### 1. Single Source of Truth for Version String
- **`mca_core/__init__.py`** is now the canonical location for `__version__`.
- `build_maya.py`, `setup.py`, `mca_maya/plugin_main.py`, and
  `mca_maya/install.py` all import from `mca_core` instead of hardcoding
  `"0.1.0"`.
- `pack_single_file.py` already had this pattern — no change needed.
- Version bumped to **0.1.1** for this session's builds.

### 2. Ctrl+C First-Press Leak in Maya Output Window
- **Symptom**: First Ctrl+C in the output window leaked to Maya's
  `cutCopyPaste.mel` ("Nothing is selected" warning). Subsequent presses
  worked.
- **Root cause**: The `_focus_forced` flag in the hotkey filter was cleared
  on every `ShortcutOverride` event (Phase 1), making it a one-shot that
  couldn't survive focus timing gaps on first interaction.
- **Fix** (`maya_window.py`):
  - Connected `QApplication.focusChanged` to a new
    `_on_app_focus_changed()` handler that manages `_focus_forced` as
    persistent state — set True when focus enters the editor tree, cleared
    when it leaves.
  - Phase 1 no longer clears the flag; the `focusChanged` signal owns the
    lifecycle.
  - `WindowActivate` always sets the flag (previously conditional).

### 3. Ctrl+B (Go to Declaration) — Double-Click Navigation Broken
- **Symptom**: Pressing Ctrl+B on a definition showed usages in the popup,
  but double-clicking a result did nothing.
- **Root cause** (`editor_panel.py`): `_navigate_to_file_line()` found the
  file via `find_editor_by_path()` but never called `set_current_index()`
  to switch to that tab. `_current_editor()` returned the wrong editor.
- **Fix**: Added `group.set_current_index(idx)` +
  `_on_group_activated(group)` when the file is already open.
- Also swapped `accept()` / `_on_confirm()` order in
  `QuickOpenPopup._confirm_selection()` so navigation runs before the
  dialog closes.

### 4. Ctrl+B Popup — Visual Cleanup
- **Before**: Single-line plain text, hard to scan.
- **After** (`quick_open.py`):
  - Custom `_DeclarationItemDelegate` paints filename:line in yellow
    (#dcdcaa) with a fixed-width column, code preview in dim gray (#9a9a9a).
  - All rows align uniformly regardless of filename length.
  - Changed popup window flags from `Dialog` + `setModal(True)` to
    `Popup` — clicking outside now dismisses the popup (no need for Escape).

### 5. Auto-Reload in Default Mode
- **Symptom**: "Auto-reload: python_1 not in sys.modules (not imported yet)"
  printed on every save in non-project mode.
- **Fix** (`editor_panel.py`): Guard was inverted — `if self._active_project
  and not ...` should be `if not self._active_project or not ...`. Now
  auto-reload is skipped entirely outside project mode.

### 6. Auto-Reload Noise in Project Mode (DCC)
- **Symptom**: "Auto-reload: startup not in sys.modules (not imported yet)"
  spammed on every save even in project mode.
- **Fix**: Removed the `else` branch from the DCC reload code that printed
  the "not imported yet" message. If the module isn't in `sys.modules`,
  there's nothing to reload — skip silently.

### 7. Save Unlocks Locked Files
- Pressing Ctrl+S on a read-only/locked editor now clears the read-only
  flag before writing, so subsequent edits work immediately.

---

## Files Changed
| File | Changes |
|------|---------|
| `mca_core/__init__.py` | Version bumped to 0.1.1 |
| `build_maya.py` | Import version from `mca_core` |
| `setup.py` | Import version from `mca_core` |
| `mca_maya/plugin_main.py` | Import version from `mca_core` |
| `mca_maya/install.py` | Import version from `mca_core` |
| `mca_maya/maya_window.py` | focusChanged-based `_focus_forced` lifecycle, WindowActivate always sets flag |
| `mca_qt/editor_panel.py` | Ctrl+B tab switch fix, auto-reload guard fix, DCC reload noise fix, save-unlock |
| `mca_qt/widgets/quick_open.py` | Custom delegate for Ctrl+B popup, Popup window flag for click-off-to-close |

## Testing
- Clean deploy tested: cleared `%LOCALAPPDATA%/MCAEditor` and
  `HKCU\Software\MCATools\MCAEditor`, deployed fresh `mcaEditor.py`.
- Multiple rebuilds during session to iterate on fixes.
