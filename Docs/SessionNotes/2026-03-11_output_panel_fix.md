# 2026-03-11: Output Panel Fix — Stale `.mod` File Causing Dual Module Imports

## Summary

The output panel bug (broken on startup auto-open and after dock close/reopen)
was **not** a code bug.  The root cause was a **stale `.mod` file** from
version 0.1.9 that added the old `dist/` directory to Maya's `PYTHONPATH`.
This conflicted with the `mcaEditor.py` single-file wrapper's extraction path
(`%LOCALAPPDATA%/MCAEditor-py3.11/`), causing the `mca_maya` package to be
importable from **two separate locations**.  Python loaded two independent
copies of `maya_window.py` with separate module globals, breaking `isinstance()`
checks, stacking tees on top of each other, and firing orphaned callbacks on
dead widgets.

**Fix**: Removed the `.mod` file, bumped version to 0.3.9, added `force=True`
to `cythonize()` in `setup.py`.  All four test scenarios now pass with zero
write failures.

---

## Root Cause Analysis

### The `.mod` File

A Maya `.mod` (module description) file from v0.1.9 was still present in
Maya's `modules/` directory.  It contained a line like:

```
+ MCAEditor 0.1.9 C:/path/to/dist
```

Maya processes `.mod` files at startup and prepends their paths to
`PYTHONPATH` / `sys.path`.  This meant `mca_maya/` was importable from BOTH:

1. The `.mod` file's path: `C:/path/to/dist/mca_maya/`
2. The single-file wrapper's extraction path: `%LOCALAPPDATA%/MCAEditor-py3.11/mca_maya/`

### Dual Module Import Problem

With two `mca_maya/` packages on `sys.path`, Python loaded `maya_window.py`
from **both locations** as separate modules with separate `globals()`.  This
caused cascading failures:

1. **`isinstance()` failures**: `_StdoutTee` from Copy A is a different class
   object than `_StdoutTee` from Copy B.  The `isinstance(sys.stdout, _StdoutTee)`
   check in `_install_output_hook()` returned `False` even when a tee was
   already installed, causing tees to stack infinitely.

2. **Stacking tees**: Each copy thought no tee was installed (because the
   other copy's tee didn't match its class).  New tees wrapped old tees
   instead of wrapping the raw `Output` stream.

3. **Orphaned callbacks**: The `MCommandMessage` callback ID stored in one
   copy's `_output_callback_id` was invisible to the other copy.  Callbacks
   fired on widgets that had been destroyed by the other copy's lifecycle.

4. **Module-level globals diverged**: `_mca_editor_window`, `_output_target`,
   `_stdout_tee`, `_stderr_tee` — all module-level state — existed in TWO
   separate namespaces.  Setting `_mca_editor_window = None` in one copy had
   no effect on the other.

### Why Previous Debugging Failed

1. **Stale extraction cache**: The single-file wrapper only re-extracts when
   the version changes.  Builds at the same version (0.3.8) never re-extracted,
   so code changes appeared to have no effect.  Version bumps are mandatory
   for testing.

2. **Cython 3.x string compression**: Attempting to verify `.pyd` contents
   by searching for string literals in the binary was misleading.  Cython 3.x
   compresses/encodes strings, so `grep` / hex editors cannot find Python
   string literals in compiled `.pyd` files.  This led to false conclusions
   about which version of code was deployed.

3. **Symptoms mimicked code bugs**: The dual-import symptoms (stale refs,
   dead widgets, lost output) looked identical to the stale widget reference
   bug that was being investigated.  Every code-level fix was doomed because
   the code was correct — the environment was broken.

---

## Fix Applied

### 1. Removed the `.mod` File

Deleted the stale `MCAEditor.mod` from Maya's `modules/` directory.  This
eliminated the duplicate `sys.path` entry and ensured `mca_maya` is only
importable from the single-file wrapper's extraction path.

### 2. Bumped Version to 0.3.9

Changed `__version__` in `mca_core/__init__.py` to `"0.3.9"`.  This forces
the single-file wrapper to re-extract on next launch, ensuring the deployed
code matches the source.

### 3. Added `force=True` to `cythonize()` in `setup.py`

Added the `force=True` parameter to the `cythonize()` call in `setup.py`.
This ensures Cython always recompiles all `.pyx` / `.py` files even if
timestamps suggest they haven't changed, preventing stale `.pyd` artifacts.

---

## Test Results

All four test scenarios pass with zero write failures:

| Scenario | Result |
|----------|--------|
| Launcher startup (auto-open) | PASS — all output types captured |
| Close editor, reopen | PASS — output continues working |
| Normal Maya restart | PASS — output works on first launch |
| Plugin unload/reload | PASS — output works (was already working in v0.3.6) |

Output types verified in all scenarios:
- `print()` statements
- `logging` module output (stderr)
- `cmds.warning()` / `cmds.error()`
- MEL echo
- Maya startup history

---

## Key Lessons Learned

### 1. Environment Before Code

When output capture breaks in mysterious ways, check `sys.path` and module
identity FIRST.  `id(module)` and `module.__file__` comparisons instantly
reveal dual imports.  Code-level debugging is wasted effort when the
environment is broken.

### 2. `.mod` Files Persist Across Versions

Maya `.mod` files are not cleaned up by plugin updates.  When switching from
a `.mod`-based distribution model to a single-file wrapper, old `.mod` files
MUST be explicitly removed.  Consider adding a check in `initializePlugin()`
that warns if a stale `.mod` file is detected.

### 3. Cython 3.x Binaries Are Opaque

Unlike Cython 2.x, Cython 3.x compresses string literals and other constants
in compiled `.pyd` files.  You cannot verify deployed code by searching for
strings in the binary.  The only reliable verification is version comparison
or hash comparison against a known-good build.

### 4. Version Bumps Are Mandatory for Testing

The single-file wrapper's extraction cache only invalidates on version change.
Building at the same version and expecting new code to take effect is a trap.
Always bump the version before every test build.

---

## Files Changed

- `mca_core/__init__.py` — version bumped to 0.3.9
- `setup.py` — added `force=True` to `cythonize()`
- Maya `modules/MCAEditor.mod` — deleted (external to repo)

---

## Related Session Notes

- `2026-03-11_output_panel_debugging_rollback.md` — previous session's rollback
- `2026-03-11_output_target_retry_failed.md` — `_output_target` indirection retry
- `2026-03-10_output_panel_stale_refs_fix.md` — original stale refs investigation
- `2026-03-10_output_panel_capture_fix.md` — v0.3.6 hybrid capture implementation
- `2026-02-28_output_panel_overhaul.md` — output panel architecture
