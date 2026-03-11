# 2026-03-11: Output Panel Debugging — Rollback to v0.3.6 Baseline

## Summary

Spent the session attempting to fix the output panel's stale widget reference
problem via `_output_target` indirection.  The fix was architecturally sound
but when deployed, the editor showed **zero output** — worse than the v0.3.6
baseline.  After multiple failed deploy attempts, rolled back to exact v0.3.6
source and did a **full `build_maya.py` rebuild**.  v0.3.6 baseline confirmed
working again (output works on plugin reload, but not on initial startup or
after dock close — the known stale ref issue).

---

## What Was Attempted

### `_output_target` Indirection Fix (8 changes to `maya_window.py`)

The fix was designed to solve the stale widget reference problem in v0.3.6:

1. Added `_output_target = None` module-level variable
2. `_StderrTee.__init__` — removed `output_widget` param, reads `_output_target` in `write()`
3. `_StdoutTee.__init__` — removed `output_widget` param, reads `_output_target` in `write()`
4. `_on_maya_output` — moved from instance method to module-level function
5. `_install_output_hook` — sets `_output_target`, installs tees ONCE (only if None)
6. `dockCloseEventTriggered` — clears `_output_target`, leaves tees installed
7. `cleanup_editor` — clears `_output_target` AND removes tees (full teardown)

### Why It Failed

**Unknown.**  The code changes are logically correct — syntax verified via
`ast.parse()`, compiled cleanly to `.pyc`.  But when deployed, the editor
showed zero output.  Even `print()` didn't appear.  Possible causes:

1. **Partial dist corruption** — Initially only `maya_window.pyc` was
   recompiled in the dist folder.  The other 18 `.pyc` files and all 31
   `.pyd` files were stale from a previous broken build (the MayaOutputPanel
   experiment from earlier in the session).  Even after recompiling all `.pyc`
   files, the `.pyd` files (including `plugin_main.pyd`, `internal_maya_adapter.pyd`)
   may have been incompatible.

2. **Build pipeline lesson** — Simply recompiling individual `.pyc` files in
   the `dist/` folder is NOT reliable.  The `.pyd` files (compiled via Cython
   by `build_maya.py`) must also be rebuilt when source changes affect their
   interfaces.  **Always use `build_maya.py` for a clean rebuild.**

3. **Possible `.pyd` / `.pyc` interface mismatch** — `plugin_main.pyd`
   (compiled from post-v0.3.6 source) references `_mw._output_target = None`
   in `_do_auto_open_editor()`.  While setting a nonexistent attribute on a
   module just creates it (no crash), the `.pyd` may have other subtle
   incompatibilities with the v0.3.6 `.pyc` files.

### What Fixed It

Full `build_maya.py` rebuild from clean v0.3.6 source → `pack_single_file.py`
→ deploy → clear cache.  This rebuilt ALL `.pyd` and `.pyc` files from the
same source snapshot, eliminating any interface mismatches.

---

## Current State (v0.3.6 Baseline)

### What Works
- Output panel captures ALL output types after **unloading and reloading** the plugin:
  - `print()` statements
  - `logging` module output (stderr)
  - `cmds.warning()` / `cmds.error()`
  - MEL echo
  - Maya startup history loaded into panel

### What Doesn't Work (Known v0.3.6 Issues)
- **Startup**: Output doesn't work on initial Maya launch (even with auto-open).
  The startup race creates multiple windows; tees bind to the first window's
  output widget, which gets destroyed when `_do_auto_open_editor` creates a
  fresh window.  Tees then point to dead C++ objects.
- **After dock close**: Closing the editor and reopening it breaks output.
  `dockCloseEventTriggered` removes tees and restores original stdout/stderr.
  The new window creates new tees, but they wrap the *already-restored*
  originals.  However, MCommandMessage callback is reinstalled with the new
  `self._on_maya_output` bound method — so Maya C++ output might work, but
  stdout/stderr tees fail because the new window's `self._panel._output`
  reference eventually goes stale.

---

## Diagnosis: Why v0.3.6 Fails on Startup

The startup race condition (documented in `2026-03-10_auto_open_and_logging_fixes.md`):

1. Plugin auto-loads → `initializePlugin()` queues `_do_auto_open_editor` via `evalDeferred`
2. Maya restores workspace → fires `uiScript` → `_restore_mca_editor()` creates **Window A**
3. Window A's `__init__` calls `_install_output_hook()` → tees and callback bind to Window A's output widget
4. `_do_auto_open_editor` fires → sets `_mca_editor_window = None`, deletes workspace control (destroys Window A's C++ side)
5. Calls `show_mca_editor()` → creates **Window B** → `_install_output_hook()` runs again
6. Step 5 removes old tees and creates new ones pointing to Window B — this SHOULD work
7. BUT: Between step 4 (widget destroyed) and step 5 (new hooks installed), any output is lost
8. AND: The tees created in step 6 may have issues if `sys.stdout` was left in an inconsistent state after step 4 destroyed the old tee's target

**Key question**: Why does reload work but startup doesn't?  On reload,
`cleanup_editor()` properly restores original stdout/stderr BEFORE creating
new tees.  On startup, `_do_auto_open_editor` does NOT call `cleanup_editor()`
— it just sets `_mca_editor_window = None` and deletes the workspace control.
The old tees from Window A are still on `sys.stdout` / `sys.stderr` but their
target widget is destroyed.  When `_install_output_hook` runs for Window B,
it does `sys.stdout = _stdout_tee._original` to "restore" — but `_original`
is Window A's tee (which wraps the REAL original), not the actual original.
So we get a chain: new tee → old tee (dead target) → real original.  The old
tee's `write()` tries to write to the dead widget and silently fails.

**Actually no** — `_install_output_hook` in v0.3.6 does:
```python
if _stdout_tee is not None:
    sys.stdout = _stdout_tee._original  # restore before creating new
    _stdout_tee = None
```
This restores whatever `_stdout_tee._original` was.  If Window A's tee
captured Maya's original OutputRedirector, then `_stdout_tee._original` is
clean.  The new tee should wrap the clean original.  So theoretically this
should work on startup too.  **The actual failure mechanism is still unclear.**

---

## Suggestions for Next Session

### Approach 1: Instrument the Startup Race (Recommended)

Before changing any code, add temporary logging to understand EXACTLY what
happens during startup:

```python
# In _install_output_hook, log what sys.stdout/stderr are BEFORE and AFTER
import logging
logger.warning("DIAG: sys.stdout type=%s id=%s", type(sys.stdout).__name__, id(sys.stdout))
logger.warning("DIAG: sys.stderr type=%s id=%s", type(sys.stderr).__name__, id(sys.stderr))
logger.warning("DIAG: _stdout_tee=%s _stderr_tee=%s", _stdout_tee, _stderr_tee)
logger.warning("DIAG: _output_callback_id=%s", _output_callback_id)
```

Also add logging to `_do_auto_open_editor()` in `plugin_main.py` and
`_restore_mca_editor()`.  Write all diagnostics to a temp file
(`%TEMP%/mca_startup_diag.log`) since the output panel itself isn't working.

This will reveal:
- How many times `_install_output_hook` is called during startup
- What `sys.stdout` is at each call (original? old tee? new tee?)
- Whether `_stdout_tee._original` is clean or a stale tee
- The exact ordering of uiScript vs _do_auto_open_editor

### Approach 2: `_output_target` Indirection (Retry with Full Build)

The `_output_target` indirection fix was the right architecture.  The failure
was likely due to stale `.pyd` files in the dist, not the code itself.  To
retry properly:

1. Apply the 8 changes to `maya_window.py`
2. Run `build_maya.py` for a **full clean rebuild** (not manual `.pyc` compilation)
3. Pack and deploy
4. Test

**Critical**: NEVER manually compile individual `.pyc` files into the dist
folder.  Always use `build_maya.py` which rebuilds everything from scratch.

### Approach 3: Fix `_do_auto_open_editor` to Call `cleanup_editor` First

The simplest possible fix: before discarding Window A, properly clean up its
hooks so the new window starts from a clean slate:

```python
def _do_auto_open_editor():
    ...
    from mca_maya import maya_window as _mw

    # Clean up any existing hooks BEFORE discarding the window.
    # This restores original stdout/stderr so the new window
    # gets clean originals, not stale tees.
    if _mw._mca_editor_window is not None:
        _mw.cleanup_editor(maya_is_exiting=False)

    _ctrl = "MCAEditorWorkspaceControl"
    if cmds.workspaceControl(_ctrl, exists=True):
        cmds.deleteUI(_ctrl)

    from mca_maya.maya_window import show_mca_editor
    show_mca_editor()
```

This is the least invasive fix — it doesn't change any output capture code,
just ensures proper cleanup before recreation.

### Approach 4: Skip uiScript Entirely

Prevent `_restore_mca_editor` from creating Window A in the first place:

```python
def _restore_mca_editor():
    # Don't create a window — _do_auto_open_editor will handle it.
    pass
```

This eliminates the race condition entirely.  `_do_auto_open_editor` is the
sole creator.  Downside: if `_do_auto_open_editor` doesn't fire (e.g. user
manually opens editor without plugin system), the uiScript path is dead.

---

## Anti-Patterns Confirmed

1. **NEVER manually recompile `.pyc` files in `dist/`** — always use
   `build_maya.py` for a full rebuild.  Mixing stale `.pyd` files with
   fresh `.pyc` files causes silent failures.

2. **NEVER pile multiple fix attempts** — when the first deploy doesn't work,
   resist the urge to add more changes.  Roll back, diagnose, understand.

3. **The build pipeline is fragile** — `pack_single_file.py` packs whatever
   is in `dist/`.  If `dist/` is stale or mixed-version, the packed plugin
   will be broken in mysterious ways with no error messages.

---

## Files at Session End

All source files match commit `f5a5648` (HEAD of main).  No uncommitted
changes.  `maya_window.py` is exact v0.3.6 code (reverted via
`git checkout 9ee96b0 -- mca_maya/maya_window.py`, which matches HEAD).

The deployed plugin (`mcaEditor.py` in Maya's plug-ins folder) is a full
`build_maya.py` rebuild from this clean v0.3.6 source.

---

## Git Log (Relevant Commits)

```
f5a5648  Bump version to 0.3.7, add session notes for output panel fix
067bff8  Fix startup race: reuse healthy uiScript window, guard userSetup.py
dfffc83  Fix stale output widget refs with _output_target indirection
9ee96b0  Fix output panel capture with hybrid stdout/stderr/MCommandMessage approach (v0.3.6)
```

Current working state is effectively `9ee96b0` (v0.3.6) code, built and
deployed as v0.3.7.
