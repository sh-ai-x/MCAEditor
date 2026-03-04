# Session Notes — 2026-03-03: Maya Popup Removal & Venv Fix

## Summary
Removed the intrusive Maya viewport popup (`inViewMessage`) that appeared during indexing and other status events. Also fixed a venv creation bug where Maya's Python interpreter naming broke pip bootstrapping.

## Changes Made

### 1. Removed Maya Viewport Popup (`mca_maya/maya_window.py`)
- **Problem**: `_maya_status_callback()` used `cmds.inViewMessage()` to show a large popup at the top of Maya's viewport for every status message (indexing progress, "Indexed N files", etc.). This was annoying and intrusive.
- **Fix**: Replaced `inViewMessage` with a simple `print()` to Maya's Script Editor output. Status messages still show in:
  - The bottom action bar (via `_on_status_message` → `_status_message_label`)
  - The output panel log (via `write_info`)
  - Maya's Script Editor output (via `print`)

### 2. Fixed Venv Creation for Maya (`mca_core/venv_manager.py`)
- **Problem**: When Maya creates a venv using `mayapy -m venv`, the resulting executable in `Scripts/` is named `mayapy.exe` instead of `python.exe`. This caused two issues:
  1. `get_venv_python()` couldn't find the venv (only looked for `python.exe`)
  2. `ensurepip` failed because the Maya-named executable can't bootstrap pip
- **Fix**:
  - `get_venv_python()` now checks for both `python.exe` and `mayapy.exe`
  - `ensure_venv()` creates the venv with `--without-pip`, then copies `mayapy.exe` → `python.exe`, then bootstraps pip separately
  - Deleted the broken `.venv-3.11` directory so it gets recreated cleanly

### 3. Version Bump
- Bumped version from `0.1.2` → `0.1.3` in `mca_core/__init__.py`

## Files Modified
- `mca_maya/maya_window.py` — Removed `inViewMessage`, replaced with `print()`
- `mca_core/venv_manager.py` — Fixed Maya venv executable naming + pip bootstrap
- `mca_core/__init__.py` — Version bump to 0.1.3

## Testing Status
- Plugin rebuilt and deployed to Maya 2025 plug-ins folder
- Awaiting Nathan's manual test in Maya
