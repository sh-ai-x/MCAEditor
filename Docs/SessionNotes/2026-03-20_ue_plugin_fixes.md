# 2026-03-20 — UE Plugin: Critical Fixes

## Summary
Fixed multiple issues with the UE plugin: CMD window popup, output not appearing
in MCA panel, wrong toolbar icon, session state persistence, and cleanup/embedding
improvements. All fixes verified via automated MCP testing in live UE 5.6.

## Issue 1: CMD Window Popup — VERIFIED FIXED
### Root Cause
`adapter_manager.py:319` called `subprocess.run(["tasklist", ...])` WITHOUT
`creationflags=CREATE_NO_WINDOW`. Triggered 1 second after panel init via
`QTimer.singleShot(1000, self._auto_detect_dccs)` (editor_panel.py:242).

### Fix
Added `_CREATION_FLAGS` constant and `creationflags=_CREATION_FLAGS` to both
subprocess.run calls at lines 319 (tasklist) and 326 (ps aux).

### File Changed
- `mca_core/adapters/adapter_manager.py`

## Issue 2: Output Not Appearing — VERIFIED FIXED
### Root Cause (Two-Phase)
1. `_execute_via_unreal()` used UE's `execute_python_command_ex()` with
   `EXECUTE_FILE` mode (treats code as file path). Even after fixing to
   `EXECUTE_STATEMENT`, UE's API does NOT capture `print()` output in
   `log_entries` for inline statements.
2. `.pyc` bytecode cache in `__pycache__/` prevented code changes from
   being picked up — UE was running old code.

### Fix
- Removed `_execute_via_unreal()` entirely
- Modified `_execute_locally()` to use plain `exec()` with
  `sys.stdout`/`sys.stderr` redirect for ALL environments including UE
- Added `self._output.flush()` for UE context
- Cleared all `.pyc` caches

### Verification (via MCP)
```
=== COMPREHENSIVE UE OUTPUT TEST ===
Test 1: Basic print
Test 2: f-string: x=42
Test 3: Loop iteration 0/1/2
Test 4: UE version = 5.6.1-44394996+++UE5+Release-5.6
=== ALL TESTS PASSED ===
Executed in UE
```
Error tracebacks also display correctly (ZeroDivisionError tested).

### File Changed
- `mca_qt/editor_panel.py`

## Issue 3: MCA Logo for Toolbar Button — CONFIRMED FIXED (by user)
Replaced code bracket icons with MCA logo from `resources/images/mca.png`.

### Files Changed
- `mca_unreal/Resources/Icon16.png`, `Icon40.png`, `Icon128.png`

## Issue 4: Session State Persistence — VERIFIED FIXED
### Design
Uses `GConfig->SetString/GetString` with `GEditorPerProjectIni` to persist
`EditorWasOpen` flag. Auto-opens via `FSlateApplication::Get().OnPostTick()`
one-shot pattern. Tab close callback clears the flag.

### Verification
UE log shows: `MCAEditor: Auto-opened (was open in previous session)` on
every test restart.

### Files Changed
- `mca_unreal/Source/MCAEditor/Public/MCAEditorModule.h`
- `mca_unreal/Source/MCAEditor/Private/MCAEditorModule.cpp`

## Issue 5: True WS_CHILD Embedding — VERIFIED FIXED
### Root Cause
Qt creates windows with WS_POPUP by default. With WS_POPUP, Win32's
SetParent() only establishes an "owner" relationship (z-ordering only),
not true parent-child embedding. GetParent() returns 0, MoveWindow uses
screen coordinates, and the widget is not clipped to the parent.

Previous session's conclusion that "Qt overrides WS_CHILD on processEvents"
was WRONG — that was tested on a different widget state. With the correct
approach, WS_CHILD is stable across hundreds of event pump cycles.

### Fix (WS_CHILD approach)
1. **`_apply_child_style(hwnd, parent_hwnd)`**: Helper function that
   clears WS_POPUP, sets WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
   via SetWindowLongW, then SetParent + SetWindowPos(SWP_FRAMECHANGED).
2. **`_ensure_embedded()`**: Called every tick. Checks if the HWND
   changed (Qt may recreate it once after first show) or if WS_CHILD
   was lost, and re-applies the embedding. Qt recreates the HWND
   exactly once (tick 2 after launch) — this function catches it.
3. **ctypes argtypes**: Configured `GetWindowLongW`/`SetWindowLongW`
   argtypes to prevent `OverflowError` on 32-bit signed style values.
4. **Cleanup improvements**: `_mca_cleanup_qt()` hides HWND immediately,
   pumps events, and clears references.

### Key Findings
- Qt's `QWindow.fromWinId()` + `setParent()` does NOT work for foreign windows
- Qt's `SubWindow` flag still creates WS_POPUP
- Direct Win32 `SetWindowLongW` to set WS_CHILD DOES work and survives processEvents
- Qt recreates the HWND once after first show — `_ensure_embedded()` catches this
- After the single recreation, the HWND and WS_CHILD are stable indefinitely

### Verification
```
=== EMBEDDING VERIFICATION ===
HWND: 0x5718f8
WS_CHILD: True
WS_POPUP: False
Parent: 0x1d10030
Visible: True
Size: 1381x1019
EMBEDDING: SUCCESS
```

### File Changed
- `mca_unreal/Content/Python/ue_editor_host.py`

## Issue 6: UE Log Piping to MCA Output Panel — VERIFIED FIXED
### Design
Log file tailing: reads new lines from UE's `Saved/Logs/<Project>.log`
every ~2 seconds (60 tick throttle). Filters to relevant log categories:
- LogPython, LogMCAEditor, LogCompile, LogBlueprintUserMessages, LogScript
- Plus ALL errors and warnings from any category

Routes to appropriate output methods:
- Errors → `write_error()` (red)
- Warnings → `write_warning()` (orange)
- Normal → `write_output()` (default)

### Verification
```
LogPython: TEST_LOG_PIPING: Hello from MCA Editor!
LogPython: Warning: TEST_LOG_PIPING: This is a warning
LogPython: Error: TEST_LOG_PIPING: This is an error
```
All three test messages appeared in the MCA output panel with correct formatting.

### File Changed
- `mca_unreal/Content/Python/ue_editor_host.py`

## C++ Plugin Compilation
The C++ changes required UBT compilation. UE does NOT auto-compile source
plugins on startup (only if using Live Coding). Must run UBT manually:
```
UnrealBuildTool.exe UE56TestEditor Win64 Development -Project="..."
```
Build time: ~3 seconds on this machine (20 cores, RTX 4090).

## Files Modified This Session
- `mca_core/adapters/adapter_manager.py` — CMD popup fix
- `mca_qt/editor_panel.py` — Output capture rewrite
- `mca_unreal/Content/Python/ue_editor_host.py` — Embedding improvements
- `mca_unreal/Resources/Icon*.png` — MCA logo icons
- `mca_unreal/Source/MCAEditor/Private/MCAEditorModule.cpp` — Session persistence
- `mca_unreal/Source/MCAEditor/Public/MCAEditorModule.h` — Session persistence
