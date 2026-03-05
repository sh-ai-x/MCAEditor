# Session Notes — 2026-03-05: Shiboken Shutdown Crash Fix

## Problem
Maya crashed ~9% of the time when closing with the MCA Editor plugin loaded.
Every crash was identical: `ACCESS_VIOLATION` in `shiboken6.abi3.dll` at offset
`0002272C` — a null/near-null pointer dereference.

Crash logs in `%LOCALAPPDATA%/Temp/MayaCrashLog*.log` showed 124 crashes out of
1397 sessions (session_start_count vs session_clean_close_count in the `.opt` file).

## Root Cause
The MCA Editor window (`MCAMayaWindow`) is parented to Maya's workspace control.
During Maya's shutdown sequence:

1. `uninitializePlugin()` calls `cleanup_editor()` which saves state, terminates
   terminals, and sets `_mca_editor_window = None`.
2. Maya's C++ Qt teardown destroys the workspace control and all child widgets.
3. Python's GC/atexit finalizers run, and shiboken destructors fire for the
   now-dangling Python wrapper objects whose C++ counterparts were already freed.
4. Shiboken dereferences freed memory -> ACCESS_VIOLATION.

## Fix
In `cleanup_editor()`, when `maya_is_exiting=True`, explicitly destroy the widget
tree via `shiboken6.delete(_mca_editor_window)` BEFORE Maya's C++ teardown.
This tears down both the C++ and Python sides simultaneously, leaving no dangling
wrappers for later GC to trip over.

Also skip `cmds.deleteUI()` and `app.removeEventFilter()` during shutdown since
those are unnecessary when the widget is already destroyed via shiboken.

### Files Changed
- `mca_maya/maya_window.py` — `cleanup_editor()` now accepts `maya_is_exiting`
  param; calls `shiboken6.delete()` during shutdown
- `mca_maya/plugin_main.py` — passes `_maya_is_exiting` flag to `cleanup_editor()`
- `mca_core/__init__.py` — version bump 0.1.7 -> 0.1.8

## Testing
Two consecutive Maya close tests with editor open — no crashes. Previously
crashed frequently (multiple times per day).

## Version
v0.1.8
