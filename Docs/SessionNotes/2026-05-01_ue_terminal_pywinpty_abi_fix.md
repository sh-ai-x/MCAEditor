# 2026-05-01 — UE Terminal pywinpty ABI Fix (v1.0.19)

## Symptom

Inside Unreal Editor (UE 5.5), the integrated terminal silently fell
back to subprocess pipes with local echo.  UE log showed:

```
pywinpty import failed: No module named 'winpty.winpty'
Venv site-packages on sys.path: C:\Users\ncomes\Documents\mca_preferences\MCAEditor\.venv-3.11\Lib\site-packages
winpty/ directory found: ['conpty.dll', ..., 'winpty.cp310-win_amd64.pyd', ...]
Terminal start: no PTY available — using subprocess pipe with local echo
```

The compiled extension was tagged `cp310` but the venv folder name was
`.venv-3.11` — clear ABI mismatch.

## Root Cause

The managed venv at `~/Documents/mca_preferences/MCAEditor/.venv-3.11/`
was created with the **system** Python (`C:\Python310\python.exe`), not
UE's bundled Python.  UE 5.5+ ships its own Python 3.11 at
`Engine/Binaries/ThirdParty/Python3/Win64/python.exe`, but
`venv_manager._find_system_python()` only looked for any 3.10+ on PATH.

On this machine the only system Python is 3.10, so:

1. `get_venv_dir()` chose `.venv-3.11` based on the running interpreter.
2. `ensure_venv()` called `_find_system_python()`, which returned
   `C:\Python310\python.exe`.
3. The folder name was 3.11 but `pyvenv.cfg` recorded
   `home = C:\Python310, version = 3.10.8`.
4. `pip install pywinpty` from inside the venv installed
   `winpty.cp310-win_amd64.pyd`.
5. UE's 3.11 interpreter could not load the cp310 extension →
   `ModuleNotFoundError: No module named 'winpty.winpty'`.

The self-heal added in v1.0.16 (`_check_venv_python_match`) **was**
detecting the version drift and wiping the venv, but on the next launch
`ensure_venv()` rebuilt it with the same wrong system Python — so the
heal looped without ever converging.  Maya was unaffected because its
path uses `mayapy` directly and never falls into `_find_system_python`.

## Fix

`mca_core/venv_manager.py`:

- New `_find_unreal_bundled_python()` derives UE's bundled Python from
  `sys.prefix` (which still points at UE's Python install dir even when
  `sys.executable` is the editor binary).  Guards against false matches
  by requiring `thirdparty`, `ue_`, or `epic games` in the path.
- `_find_system_python()` rewritten with explicit priority:
  1. UE bundled interpreter (when running inside UE)
  2. Exact `(major, minor)` match — uses `py -3.11` on Windows, the
     `pythonX.Y` shim on POSIX
  3. Any 3.10+ as a last-resort fallback
- Logs a warning when falling through to (3) so the next-launch ABI
  rebuild has a visible cause in session logs.

This is a no-op for Maya (early `mayapy` detection short-circuits) and
for standalone (where `sys.executable` is already a real Python).

## Recovery

- Wiped the broken venv at
  `C:\Users\ncomes\Documents\mca_preferences\MCAEditor\.venv-3.11\`
- Patched the live `venv_manager.py` in three installed UE plugins:
  - `E:/Rascal/depot/Wayward/Plugins/MCAEditor/`
  - `D:/Unreal-Projects/UE56Test/Plugins/MCAEditor-UE5.6-v1.0.5/`
  - `D:/Unreal-Projects/UE57Test/Plugins/MCAEditor/`
- Bumped version `1.0.18 → 1.0.19`
- Built UE 5.5 / 5.6 / 5.7 plugins
- Staged zips into `dist/latest/` and ran `deploy_website.py`
- `releases.json` updated: `latest = 1.0.19`, 19 total entries
- CHANGELOG entry added for 1.0.18 (was missing) and 1.0.19

## Verification

- New venv built on next UE launch will use the bundled 3.11 interpreter
  and install `winpty.cp311-win_amd64.pyd`
- Re-launch any UE project with the patched plugin to confirm the
  terminal opens with a real PTY (no "subprocess pipe with local echo"
  fallback in the log)

## Related Notes

- `2026-04-15_venv_python_version_self_heal.md` — added the
  `_check_venv_python_match` heal that surfaced this issue.  That fix
  closed the *detection* gap; this one closes the *rebuild* gap so the
  heal can actually converge.
