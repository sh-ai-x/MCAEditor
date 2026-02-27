# Session: Features, Bugfixes, and UX Polish — 2026-02-26 (Evening)

## Summary

Major feature session implementing Find in Files, Replace in Files, Go to
Declaration / Find Usages (Ctrl+B), and several UX bugfixes across the editor.
Buffers are now file-backed from creation so they appear in the workspace tree
and are searchable immediately. Multiple rounds of user testing drove iterative
fixes for focus handling, auto-complete dismissal, popup positioning, and more.

## New Features

### Find in Files (Ctrl+Shift+F)
- New file: `mca_qt/widgets/find_in_files.py`
- `SearchWorker(QThread)` — background file search with cancel support
- `FindInFilesDialog(QDialog)` — search input, Cc/W/.* toggles, file filter,
  QTreeWidget results grouped by file, status label
- Double-click match navigates to file:line via `_navigate_to_file_line()`

### Replace in Files (Ctrl+Shift+R)
- Same dialog with `mode="replace"` — adds replace input + Replace All button
- Replace All writes to disk AND reloads any open editor tabs whose files changed
- Added `replace_done_callback` + `_reload_editors_for_paths()` in editor_panel

### Go to Declaration / Find Usages (Ctrl+B)
- Cursor on a usage → jumps to definition (`def`, `class`, `proc`)
- Cursor on a definition → shows all usages in a popup
- Single result navigates directly; multiple results show `GoToDeclarationPopup`
- `GoToDeclarationPopup` added to `quick_open.py` (subclass of `QuickOpenPopup`)
- Helper methods: `_is_on_definition()`, `_find_symbol_definition()`,
  `_find_symbol_usages()`, `_scan_files_for_patterns()`

### Shortcut Rebinding
- Ctrl+B → Go to Declaration (was Toggle Sidebar)
- Ctrl+Shift+B → Toggle Sidebar (moved from Ctrl+B)
- Ctrl+Shift+R → Replace in Files (was Ctrl+Shift+H)

### Output Panel Context Menu
- Right-click on output panel shows Copy, Select All, Clear
- `clear_requested` signal wired to `OutputWindow.clear()`

### File-Backed Buffers
- `_new_buffer()` now writes an empty file to `scripts_dir` immediately
- Buffer tabs have `editor.file_path` set from creation
- Workspace tree auto-refreshes via QFileSystemWatcher
- Session restore updated to set `file_path` on legacy buffer manifests

## Bugfixes

### Sidebar Splitter Not Remembered
- `closeEvent()` wasn't saving `sidebar_splitter_sizes`
- `setSizes()` during `__init__` was overridden by Qt's first layout pass
- Fix: `showEvent()` + `QTimer.singleShot(0, _restore_splitter_sizes)` deferred
  restore in both `editor_panel.py` and `main_window.py`

### Settings Dialog setChecked TypeError
- QSettings persists bools as strings (`"true"` not `True`)
- PySide6 `setChecked()` rejects strings
- Fix: Added `_to_bool()` helper, wrapped bold/italic checkbox calls

### Ctrl+B Word Extraction Failures
- `WordUnderCursor` sometimes grabs punctuation like `():`
- After selection, `positionInBlock()` returns END of selection, not original pos
- Fix: Save `original_col` before `select(WordUnderCursor)`, use it in fallback
- Added identifier validation regex (`^[A-Za-z_]\w*$`)

### Ctrl+B Duplicate Tabs
- `find_editor_by_path()` couldn't match buffer tabs (stored path was None)
- Fix: Also check `editor.file_path` attribute in `_navigate_to_file_line()`

### Auto-Close Quotes Too Aggressive
- Paired quotes even when there was text immediately after cursor
- Fix: Only auto-pair when next char is whitespace or delimiter

### Outline Panel Not Syncing
- Only updated on tab switch, not on edits
- Fix: Connected `document().contentsChanged` to debounced refresh (500ms)

### Completer Not Dismissing on Click-Away
- `focusOutEvent` and `focusChanged` don't fire reliably in Maya's embedded Qt
- Fix: Application-level `eventFilter` on `QApplication` catches `MouseButtonPress`
  anywhere — dismisses popup if click is outside completer and editor

### Quick Open / GoTo Popup Mispositioned in Maya
- `parent.geometry()` returns coords relative to parent's parent, not screen
- Fix: Changed to `parent.mapToGlobal(QPoint(0, 0))` for correct screen coords

### Show in Explorer Not Working
- `subprocess.Popen(["explorer", "/select,", path])` split args incorrectly
- Fix: Use `shell=True` with `'explorer /select,"path"'` format + `os.path.normpath()`

### Tabs Not Saved on Window Close
- `cleanup()` only saved pathless temp buffers, skipping file-backed tabs
- Fix: Now writes ALL open tabs to disk on close (file-backed and legacy buffers)

### Output Lost on Window Reload
- `cmds.deleteUI()` doesn't trigger `dockCloseEventTriggered`
- Fix: Added explicit `save_window_state()` + `cleanup()` before `deleteUI()`
  in `show_mca_editor()`

### Double-Click Tab Bar Opens New Tab Dialog
- Added `new_tab_requested` signal chain: EditorGroup → EditorGroupContainer → Panel
- Ctrl+N also now shows language picker instead of creating default buffer

### Maya Focus Stealing on First Click
- `setFocus()` alone insufficient without active window in docked panels
- Fix: `activateWindow()` + `MouseFocusReason` + `_focus_forced` flag +
  `WindowActivate` event handler

### MCA Log Noise in Output
- `setLevel(WARNING)` for mca_core, mca_qt, mca_maya loggers in maya_window.py
- Filtered MCA log lines from history load and runtime output hook

## Files Modified

| File | Changes |
|------|---------|
| `mca_qt/editor_panel.py` | +600 lines: Find/Replace in Files, Go to Declaration, file-backed buffers, shortcut rebinding, outline sync, splitter restore, tab save on close, reload editors after replace |
| `mca_qt/widgets/find_in_files.py` | **NEW** — SearchWorker + FindInFilesDialog (~480 lines) |
| `mca_qt/widgets/quick_open.py` | GoToDeclarationPopup, mapToGlobal positioning fix |
| `mca_qt/widgets/completer.py` | App-level eventFilter for click-away dismissal |
| `mca_qt/widgets/output_window.py` | Context menu (Copy, Select All, Clear) |
| `mca_qt/widgets/settings_dialog.py` | `_to_bool()` helper for setChecked |
| `mca_qt/widgets/code_editor.py` | Smart auto-close quotes |
| `mca_qt/widgets/editor_group.py` | `new_tab_requested` signal, double-click handler |
| `mca_qt/widgets/editor_group_container.py` | `new_tab_requested` signal relay |
| `mca_qt/widgets/sidebar.py` | Show in Explorer fix (shell=True + normpath) |
| `mca_editor/ui/main_window.py` | Sidebar splitter save/restore, deferred restore |
| `mca_maya/maya_window.py` | Focus fix, log filtering, pre-reload cleanup |
| `mca_core/adapters/internal_maya_adapter.py` | Echo to Maya script editor via MGlobal.displayInfo + suppression flag, focus preservation |
| `mca_qt/icons.py` | Added `settings_icon()` (gear with radial teeth) |

## Additional Fixes (Late Session)

### Echo Execution to Maya's Script Editor
- **Goal**: Executed code should appear in Maya's script editor like Charcoal Editor 2
- **Attempt 1**: `sys.__stdout__` — doesn't route to Maya's script editor
- **Attempt 2**: `MGlobal.displayInfo()` — works but gets captured by our own
  `MCommandMessage` output hook, causing duplicates in MCA Editor
- **Solution**: `MGlobal.displayInfo()` with a module-level `_suppress_output_hook`
  flag. The adapter sets it `True` before echoing, the output hook checks it and
  skips, clearing it in `finally`. No prefix, no duplicates.

### Focus Theft During Output Writes
- **Symptom**: Typing in editor randomly loses focus to Maya
- **Root cause**: `_on_maya_output()` writes to the output QPlainTextEdit via
  `setTextCursor()` + `ensureCursorVisible()`, which can move Qt focus away
- **Fix 1**: Save/restore `focusWidget()` around output panel writes in `_on_maya_output()`
- **Fix 2**: Save/restore focus around `MGlobal.displayInfo()` echo in `_execute_python()`
- Both guards use `setFocus(OtherFocusReason)` to silently return focus

### Settings Button Moved to Left Stripe
- Removed the Unicode gear button from the toolbar
- Added proper `settings_icon()` to `icons.py` (gear with radial lines + circles)
- Button placed below the terminal button in the left tool stripe (`bottom=True`)
- Handled in `_on_left_stripe_clicked()` → `_show_settings()`

### Replace in Files Now Updates Open Editors
- Replace All wrote to disk but open editor tabs still showed old content
- Added `replace_done_callback` parameter to `FindInFilesDialog`
- Added `_reload_editors_for_paths()` that re-reads affected files from disk
  and updates editor content while preserving cursor position

### Minor
- Licensing text changed from "Free / Open Source" to "Free"

## Key Learnings

- **`cursor.positionInBlock()` after `select(WordUnderCursor)`** returns the END
  of the selection, not the original cursor position. Always save the original
  column before calling select().
- **`parent.geometry()` vs `parent.mapToGlobal()`** — geometry() is relative to
  the parent's parent widget, not the screen. Always use mapToGlobal() for
  positioning floating popups, especially in docked/embedded panels.
- **`focusChanged` signal unreliable in Maya** — Maya's embedded Qt doesn't
  always fire focus events when clicking between panels. An application-level
  eventFilter catching MouseButtonPress is more robust.
- **`explorer /select,` on Windows** must be a single string command with
  shell=True — splitting into a list breaks the argument parsing.
- **`MGlobal.displayInfo()` gets captured by MCommandMessage hooks** — use a
  module-level suppression flag to prevent the output hook from re-capturing
  messages that were intentionally echoed to Maya's script editor.
- **`sys.__stdout__` does NOT route to Maya's script editor** — only
  `MGlobal.displayInfo/Warning/Error()` appear in Maya's history panel.
- **`cmds.deleteUI()` does NOT trigger `dockCloseEventTriggered`** — must
  explicitly save state before deleting the workspace control.
- **`setTextCursor()` on a QPlainTextEdit can steal focus** — always
  save/restore `focusWidget()` when writing to UI widgets from callbacks
  that fire during user interaction (e.g. Maya output hooks).
