# Session Notes: 2026-03-17 — macOS Venv Framework Fix

## What Was Done

Fixed broken venv creation on macOS for all Maya versions (2024, 2025, 2026).
Pulled latest from GitHub, rebuilt and deployed v0.4.0 to all three Maya versions.

### Bug: `ModuleNotFoundError: No module named 'encodings'`

**Symptom:** On macOS, the managed venv's Python could not start. Running
`.venv-3.10/bin/python` produced:

```
PYTHONHOME = '<venv>/Frameworks/Python.framework/Versions/Current'
Fatal Python error: init_fs_encoding: failed to get the Python codec of the filesystem encoding
ModuleNotFoundError: No module named 'encodings'
```

This caused cascading failures:
- `ensurepip` failed (no stdlib)
- `pip install` failed (no pip)
- Fallback to host interpreter tried but still warned

**Root cause:** Maya's `mayapy` on macOS is a framework Python. It resolves
`PYTHONHOME` by walking up from the executable to find
`Frameworks/Python.framework/Versions/Current/`. When symlinked into a
venv's `bin/` directory, the walk resolves to `<venv>/Frameworks/...`
which doesn't exist.

The existing `_fix_maya_venv()` function only handled Windows (directory
junction for `<venv>/Python` → `<maya>/Python`). macOS was skipped
entirely with an early `if platform.system() != "Windows": return`.

**Fix:** Refactored `_fix_maya_venv()` into a dispatcher that calls
platform-specific helpers:
- `_fix_maya_venv_macos()` — Creates symlink `<venv>/Frameworks` →
  `<maya_contents>/Frameworks` so the framework path resolution succeeds
- `_fix_maya_venv_windows()` — Existing junction + DLL copy + sitecustomize
  logic (unchanged)

### Modified Files

- **`mca_core/venv_manager.py`**:
  - `_fix_maya_venv()` refactored from monolithic Windows-only function to
    platform dispatcher
  - New `_fix_maya_venv_macos()` — creates Frameworks symlink
  - Renamed existing Windows logic to `_fix_maya_venv_windows()`

## Testing

- Deleted broken `.venv-3.10` and `.venv-3.11`
- Ran `setup_venv()` via Maya 2024 mayapy (Python 3.10) — success, no warnings
- Ran `setup_venv()` via Maya 2025 mayapy (Python 3.11) — success, no warnings
- Verified venv Python can import `encodings`, `pip`, run normally
- Verified `Frameworks` symlink created in both venvs

## Build Status

- Maya 2024 (Python 3.10): Rebuilt and deployed as v0.4.0
- Maya 2025 (Python 3.11): Rebuilt and deployed as v0.4.0
- Maya 2026 (Python 3.11): Rebuilt and deployed as v0.4.0

## Notes

- Maya must be restarted to pick up the new plugin build — the old compiled
  plugin in memory doesn't have the fix
- The `.venv-3.10` and `.venv-3.11` directories were recreated with the fix
  and are working; Maya 2024/2025/2026 just need a restart
