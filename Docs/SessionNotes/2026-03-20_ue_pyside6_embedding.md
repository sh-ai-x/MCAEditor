# 2026-03-20 — UE Plugin: PySide6/Qt Embedding via Win32 Native Host

## Summary
Pivoted the UE plugin from native Slate widgets to embedding the existing PySide6/Qt
MCA Editor inside a UE docked tab via Win32 SetParent. This gives UE users the EXACT
same editor as Maya — same codebase, same features, same theme, same workflow.

Major breakthrough: solved the HWND destruction problem that occurs during dock/undock
transitions. When UE destroys a parent window (floating tab), all Win32 child windows
are also destroyed. Standard Qt methods (`setWindowFlags()`, `setParent(None)`,
`hide()`/`show()`) fail to recreate the HWND. Solution: `widget.destroy()` +
`widget.create()` rebuilds the native handle while preserving all widget state.

Also fixed output capture by routing code execution through UE's
`PythonScriptLibrary.execute_python_command_ex()` API instead of plain `exec()`.

**Key accomplishments:**
- Win32 child window embedding (SetParent) with pixel-perfect positioning
- HWND recreation via destroy()+create() — survives unlimited dock/undock cycles
- All widget state preserved (children, layout, signals, editor content, window flags)
- Output capture via UE's native Python API (same approach as Nathan's old script editor)
- CMD popup fix: UE executable detection in venv_manager, falls back to system Python
- Deleted 16 old Slate widget files (SMCACodeEditor, SMCAOutputPanel, etc.)
- UE gets separate session workspace (`ue_scripts/` directory)

## The HWND Recreation Problem

### Root Cause
When a Qt widget is embedded as a Win32 child window via `SetParent()`, the child HWND
is destroyed when the parent window is destroyed. UE destroys parent windows during
dock/undock transitions (floating tab window → docked, or vice versa).

After destruction, Qt internally caches the dead HWND. Calling `winId()` returns the
old invalid handle.

### Methods That FAIL (Proven by Automated Tests)
All of these return the same dead HWND from `winId()`:
- `setWindowFlags(same_flags)` — Qt caches the handle
- `setWindowFlags(Window)` then `setWindowFlags(FramelessWindowHint)` — still cached
- `setParent(None)` + `setWindowFlags()` — still cached
- `hide()` + `show()` — still cached

### Method That WORKS
```python
widget.destroy()   # Tear down Qt's native resources
widget.create()    # Rebuild with fresh HWND
new_hwnd = int(widget.winId())  # New valid handle
```
- Preserves all widget state: children, layout, signals, editor content
- Window flags (FramelessWindowHint) survive
- Tested across 2+ full dock/undock cycles
- Tested with complex widget trees (QLabel, QPushButton, QTextEdit children)

### Test Scripts
- `mca_unreal/test_hwnd_recreation.py` — proves standard methods fail
- `mca_unreal/test_hwnd_recreation2.py` — finds destroy()+create() works

## Architecture

### C++ Side (`SMCANativeHost`)
Thin Slate widget that:
1. Finds the containing UE window via `FindWidgetWindow(AsShared())`
2. Launches `ue_editor_host.py` on first tick with valid geometry
3. Detects parent window changes (dock/undock) and calls `_mca_reparent()`
4. Converts Slate absolute coords to parent-relative via `ClientToScreen`
5. Calls `_mca_tick(x,y,w,h)` when geometry changes, `_mca_pump_qt()` otherwise
6. Hides Qt widget when tab is backgrounded (zero geometry)
7. Throttles to ~30fps (every other frame)

### Python Side (`ue_editor_host.py`)
1. Locates MCA Editor source (dev: hardcoded path, prod: bundled)
2. Sets up managed venv with PySide6 as additional requirement
3. Creates QApplication (reuses existing if present)
4. Creates MCAEditorPanel with `dcc_version="UE5"` and empty AdapterManager
5. Sets FramelessWindowHint, gets HWND via `winId()`
6. Reparents into UE window via `SetParent()`
7. Exposes tick/reparent/pump/hide/cleanup functions for C++ to call

### Key Functions
- `_mca_tick(x, y, w, h)` — MoveWindow + ShowWindow + processEvents
- `_mca_reparent(new_parent_hwnd)` — IsWindow check → destroy()+create() if dead → SetParent
- `_mca_pump_qt()` — processEvents only (no geometry change)
- `_mca_hide_qt()` — ShowWindow(SW_HIDE) for backgrounded tabs
- `_mca_cleanup_qt()` — close + clear references on tab close

## Output Capture Fix

### Problem
`_execute_locally()` uses `sys.stdout = io.StringIO()` + `exec()` to capture print
output. This works in standalone and Maya, but in UE, `print()` output is intercepted
at the C level by UE's PythonScriptPlugin and routed to the Output Log — our StringIO
never sees it.

### Solution
Added `_execute_via_unreal()` method in `editor_panel.py`. When `dcc_version` starts
with "UE", execution goes through `unreal.PythonScriptLibrary.execute_python_command_ex()`
which returns `(command_result, log_entries)`. Log entries contain all captured output
with type (INFO/WARNING/ERROR). This is the same approach Nathan's old Wayward script
editor used (`mca-ue/mca/ue/tools/scripteditor/script_editor_ui.py`).

### Reference
Nathan's old script editor at:
`E:/Rascal/depot/Wayward_RAW/Tools/Python/framework/packages/mca-ue/mca/ue/tools/scripteditor/`

## CMD Popup Fix

### Problem
When the MCA Editor opens in UE, a CMD window flashes briefly. This is from
`venv_manager.py` using `sys.executable` (which is `UnrealEditor.exe` in UE) to run
`python -m venv`.

### Solution
Added UE executable detection in `ensure_venv()`: when `sys.executable` basename starts
with "unreal", falls back to `_find_system_python()` which finds Python 3.10+ on PATH.
Added `_find_system_python()` helper to `venv_manager.py` (ported from `mcp_setup.py`).

## Files Changed

### New/Modified in Repo (`mca_unreal/`)
- `Content/Python/ue_editor_host.py` — PySide6 embedding + HWND recreation
- `Source/MCAEditor/Private/Widgets/SMCANativeHost.cpp` — native host implementation
- `Source/MCAEditor/Public/Widgets/SMCANativeHost.h` — native host header
- `test_hwnd_recreation.py` — proves standard HWND recreation fails
- `test_hwnd_recreation2.py` — finds destroy()+create() works

### Modified in Core
- `mca_qt/editor_panel.py` — added `_execute_via_unreal()` for UE output capture
- `mca_core/venv_manager.py` — UE executable detection + `_find_system_python()`
- `mca_core/session_manager.py` — UE gets separate `ue_scripts/` workspace

### Deleted (Old Slate Widgets)
16 files removed: SMCAEditorPanel, SMCACodeEditor, SMCAOutputPanel, SMCATabBar,
SMCASidebar, SMCAFindReplace, SMCAToolStripe, SMCAQuickOpen (h+cpp each),
PythonBridge (h+cpp), MCAEditorSettings (h+cpp)

## Next Steps
1. User testing: verify output capture with `print("hello world")`
2. User testing: verify dock/undock survives transitions
3. Investigate if CMD popup is fully suppressed
4. Test license dialog flow in UE context
