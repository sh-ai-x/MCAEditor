# Session: Shiboken Crash Fix, Terminal Copy & Cleanup — 2026-03-02 (session 2)

## Summary

Resolved the persistent Maya segfault from the previous session: **ALL files with
Qt virtual method overrides crash when compiled to `.pyd`** due to
`Shiboken::Enum::unpickleEnum` failing on enum-typed arguments in Cython-compiled
code. Fixed by shipping 16 widget files as `.pyc` (bytecode) instead of `.pyd`,
keeping 31 files compiled. Also fixed terminal copy (broken by the `.pyc` switch),
Maya zombie processes on shutdown, and MCP command port issues.

---

## What Was Completed

### 1. Shiboken Enum Crash — Root Cause & Fix

**Root cause**: Cython-compiled `.pyd` files containing Qt virtual method overrides
(`eventFilter`, `paintEvent`, `keyPressEvent`, `sizeHint`, `showEvent`, `closeEvent`,
`resizeEvent`, drag events, etc.) crash with `ACCESS_VIOLATION at 0x00000008` in
`Shiboken::Enum::unpickleEnum`. This happens when Shiboken's C++ virtual dispatch
tries to handle enum-typed arguments through compiled extension code. The crash
occurs during Qt's paint/event dispatch cycles (e.g., `processGeometryChangeEvent`,
`processExposeEvent`, `drawWidget`, `notify_helper`).

**Fix**: 16 files with Qt virtual overrides ship as `.pyc` (bytecode, no source
exposed). 31 files without overrides compile to `.pyd` normally. This is tracked in
two parallel lists:
- `setup.py:exclude_from_compilation` — skips these during Cython compilation
- `build_maya.py:DIST_PYC_FILES` — compiles these to `.pyc` in the dist structure

**16 files excluded from .pyd compilation:**
- `mca_maya/maya_window.py` — eventFilter, event
- `mca_qt/editor_panel.py` — showEvent
- `mca_qt/widgets/code_editor.py` — paintEvent, keyPressEvent, sizeHint, event
- `mca_qt/widgets/completer.py` — eventFilter
- `mca_qt/widgets/drag_tab_manager.py` — eventFilter
- `mca_qt/widgets/drop_zone_overlay.py` — paintEvent
- `mca_qt/widgets/editor_group.py` — mousePressEvent, paintEvent, eventFilter
- `mca_qt/widgets/find_in_files.py` — closeEvent
- `mca_qt/widgets/find_replace_bar.py` — eventFilter, keyPressEvent
- `mca_qt/widgets/output_window.py` — eventFilter, keyPressEvent, event
- `mca_qt/widgets/quick_open.py` — eventFilter
- `mca_qt/widgets/settings_dialog.py` — keyPressEvent
- `mca_qt/widgets/sidebar.py` — dragEnterEvent, dragMoveEvent, dropEvent
- `mca_qt/widgets/terminal_native.py` — eventFilter, resizeEvent
- `mca_qt/widgets/terminal_xterm.py` — eventFilter
- `mca_qt/widgets/tool_stripe.py` — sizeHint

### 2. Terminal Copy Fix (3 issues)

When `terminal_native.py` was compiled as `.pyd`, its `eventFilter` crashed
(Shiboken enum issue), so Qt's default QPlainTextEdit behavior handled everything
— mouse selection and Ctrl+C copy worked "for free." Now that eventFilter works
properly as `.pyc`, all event handling had to be made explicit:

1. **Ctrl+C smart copy/interrupt** — If the user has text selected, Ctrl+C copies
   to clipboard (like Windows Terminal). If no selection, Ctrl+C sends `\x03`
   interrupt to the shell. Ctrl+Shift+C always copies.

2. **Mouse selection tracking** — Added `_mouse_selecting` flag set on
   `MouseButtonPress`, cleared on `MouseButtonRelease`. While the flag is True,
   the 60fps render timer skips display rebuilds so the selection isn't destroyed.

3. **Selection preservation** — Added `hasSelection()` check in the render loop.
   When the user has completed a selection (mouse released), the render still
   pauses until the selection is cleared, preventing Ctrl+C from finding an empty
   selection.

4. **Left-click pass-through** — Stopped consuming left MouseButtonPress events
   (`return True` removed) so QPlainTextEdit handles click-drag selection natively.

### 3. Maya Zombie Process Fix

Maya was hanging as a zombie process after closing because our terminal's ConPTY
child shell processes survived shutdown.

**Two fixes:**

1. **`terminal_backend.py:terminate()`** — Now explicitly kills the PTY child
   process via `os.kill(pid, signal.SIGTERM)` instead of relying on garbage
   collection (which never runs during Maya shutdown).

2. **`plugin_main.py:uninitializePlugin()`** — Now calls
   `maya_window.cleanup_editor()` which terminates all terminal processes,
   disconnects adapters, and removes callbacks. Previously only the window-close
   callback (`dockCloseEventTriggered`) did this, which doesn't fire during Maya
   shutdown.

3. **`maya_window.py:cleanup_editor()`** — New module-level function that safely
   cleans up the global `_mca_editor_window` instance, removing hotkey filter,
   output callback, and calling `_panel.cleanup()`.

### 4. MCP Command Port Fix

Command port 7002 was open but unresponsive (accepted TCP connections but never
processed data). Root cause: port opened too early in Maya startup, or stale
state from zombie processes. Fixed by:

1. Moved `_ensure_command_ports()` to top of `show_mca_editor()` (before early
   return for already-visible workspace)
2. Added `_ensure_command_ports()` to `_restore_mca_editor()` (layout restore path)
3. Added verification + 2-second QTimer retry in `_ensure_command_ports()`

---

## Key Insight: .pyc Placement

`.pyc` files must go **directly in the package directory** (e.g.,
`mca_maya/maya_window.pyc`), NOT in `__pycache__/`. Python's SourcelessFileLoader
only looks in the package dir for sourceless `.pyc` imports.

---

## Files Modified

| File | Change |
|------|--------|
| `setup.py` | Added `exclude_from_compilation` set (16 files), reverted safety directives |
| `build_maya.py` | Added `DIST_PYC_FILES` list (16 files), `compile_pyc_files()` function |
| `mca_qt/widgets/terminal_native.py` | Smart Ctrl+C, mouse selection tracking, render pausing, left-click pass-through |
| `mca_qt/widgets/terminal_backend.py` | Explicit `os.kill()` for PTY child in `terminate()` |
| `mca_maya/maya_window.py` | Added `cleanup_editor()`, `_ensure_command_ports()` with retry |
| `mca_maya/plugin_main.py` | `uninitializePlugin()` calls `cleanup_editor()` |
| `tools/maya_plugin_test.py` | Enhanced smoke test with geometry resize + longer wait |
| `tools/run_maya_test.py` | Test runner wrapper |

## Build & Deploy Commands

```bash
cd E:/Projects/MCAEditor
python build_maya.py
python pack_single_file.py
rm -rf "$LOCALAPPDATA/MCAEditor"
cp dist/mcaEditor.py "$USERPROFILE/Documents/maya/2025/plug-ins/mcaEditor.py"
```
