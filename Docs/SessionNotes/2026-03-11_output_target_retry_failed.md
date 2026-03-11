# 2026-03-11: `_output_target` Indirection Retry — Failed Again

## Summary

Second attempt at the `_output_target` indirection fix for the output panel
close/reopen bug.  This time the code was applied cleanly and rebuilt via
`build_maya.py` (full clean build, not manual `.pyc` recompilation).  The
build succeeded, packed, deployed, and cache was cleared.  **Still didn't work.**

This eliminates the "stale `.pyd` files" theory from the first attempt.
The problem is in the approach itself, not the build pipeline.

---

## What Was Done

### 7 Changes to `maya_window.py` (same architecture as previous attempt)

1. Added `_output_target = None` module-level variable
2. `_StderrTee` — removed `output_widget` param, reads `_output_target` on every `write()`
3. `_StdoutTee` — same as above
4. `_on_maya_output` — moved from instance method to module-level function, reads `_output_target`
5. `_install_output_hook` — sets `_output_target`, only installs tees/callback if they're `None` (first time); on reopen just updates the target pointer
6. `dockCloseEventTriggered` — sets `_output_target = None` only; does NOT remove callback, does NOT restore sys.stdout/sys.stderr, does NOT touch tees
7. `show_mca_editor` cleanup path — removed the `MMessage.removeCallback` block; callback is now permanent

Also added `_output_target` to `cleanup_editor`'s `global` and clears it before teardown.

### Build & Deploy

- `python build_maya.py` — full clean rebuild (all 31 `.pyd` + 19 `.pyc`)
- `python pack_single_file.py` — packed 75 files into single `mcaEditor.py`
- Copied to Maya plug-ins folder
- Deleted `%LOCALAPPDATA%/MCAEditor/` cache
- **Build was clean — no errors, no stale artifacts**

### Result

**Not working.**  Specific failure mode not yet diagnosed (Nathan reported
"not working" — need to instrument to find out whether it's zero output,
partial output, or a crash).

---

## Why This Approach Keeps Failing

The `_output_target` indirection is architecturally sound in theory but
has failed twice now.  Possible explanations:

### Theory 1: `.pyc` files can't read module-level globals reliably
When `maya_window.py` ships as `.pyc` (not `.pyd`), the tee classes and
module-level function `_on_maya_output` are in the same module.  They should
be able to read `_output_target` as a module global.  But maybe Python's
compiled bytecode handles `global` differently in `.pyc` than in source —
unlikely but worth verifying with a minimal test.

### Theory 2: The tees are never installed on first open
The change to `_install_output_hook` uses `if _stdout_tee is None:` to
decide whether to install.  If something sets `_stdout_tee` to a non-None
value before the first call (e.g. a stale module state from a previous
plugin load within the same Maya session), the tees would never install.

### Theory 3: `_output_target` is set but the widget is not ready
`_output_target = self._panel._output` is called in `_install_output_hook()`,
which runs during `MCAMayaWindow.__init__()`.  The output widget exists at
this point, but it may not be fully initialized (no parent, no layout, not
visible).  The `write_*()` methods may silently fail or queue text that gets
lost when the widget is reparented by Maya's workspace control system.

### Theory 4: The callback registration with a module-level function fails
The old code registered `self._on_maya_output` (a bound method).  The new
code registers `_on_maya_output` (a module-level function).  Maya's
`MCommandMessage.addCommandOutputCallback` may have requirements about the
callable that a plain function doesn't satisfy (e.g. it may need to be
prevent-GC'd by reference counting, and a bound method stored on `self`
has a different GC lifetime than a module function).

---

## What Was Reverted

Reverted `maya_window.py` to git HEAD (v0.3.6 baseline) via:
```
git checkout HEAD -- mca_maya/maya_window.py
```

Full rebuild + pack + deploy + cache clear done with reverted code.
**Back to known v0.3.6 baseline** (output works after plugin reload,
broken on startup and after dock close).

---

## Suggestions for Next Attempt

### 1. Instrument Before Fixing (highest priority)
Write diagnostic output to a temp file (`%TEMP%/mca_output_diag.log`) to
understand exactly what's happening.  The output panel itself can't be
trusted for diagnostics since it's the thing that's broken.

### 2. Try Approach 3 from Previous Session Notes
The simplest possible fix: call `cleanup_editor()` in `_do_auto_open_editor`
before discarding Window A.  This doesn't change any output capture code —
just ensures proper cleanup before recreation.  Much lower risk than the
`_output_target` refactor.

### 3. Try Approach 4: No-op `_restore_mca_editor`
Make `_restore_mca_editor()` a no-op so the startup race never creates
Window A.  `_do_auto_open_editor` becomes the sole window creator.

### 4. If retrying `_output_target`, add file-based diagnostics
Before deploying, add `with open(TEMP/diag.log, 'a') as f: f.write(...)`
calls at every key point to trace execution without depending on the output
panel.

---

## Files at Session End

All source files match git HEAD.  No uncommitted changes.
Deployed plugin is a full `build_maya.py` rebuild from clean v0.3.6 source.
