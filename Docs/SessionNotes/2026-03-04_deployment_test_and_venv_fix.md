# Session Notes — 2026-03-04: Deployment Test & Venv Fix

## Goal
Full clean deployment test — wipe all installed artifacts and verify fresh build + deploy works end-to-end.

## What Was Done

### 1. Clean Wipe
Removed all deployed artifacts to simulate a fresh install:
- `~/Documents/mca_preferences/` — prefs, venvs (.venv-3.11, .venv-3.14), MCP servers, session, logs
- `%LOCALAPPDATA%/MCAEditor/` — single-file extracted packages
- `~/Documents/maya/2025/plug-ins/mcaEditor.py` — old plugin stub
- `~/Documents/maya/modules/` — mod file
- `dist/` — previous build output

### 2. Build & Install
- Ran `build_maya.py` — compiled v0.1.4 successfully (36 Cython modules + 16 .pyc fallbacks)
- Ran `install_maya.py` — created mod file + plugin stub

### 3. Bug Fix: pluginPrefs.mel (old plugin name)
Maya's `pluginPrefs.mel` still referenced the old single-file plugin name `mcaEditor.py`.
Updated to `mca_editor_plugin.py` in `~/Documents/maya/2025/prefs/pluginPrefs.mel`.

### 4. Bug Fix: Maya Venv Broken on Windows (`venv_manager.py`)
**Root cause**: Maya's `mayapy.exe` uses hardcoded relative path resolution for `PYTHONHOME` — it looks for stdlib at `<exe_dir>/../Python/`. When copied into a venv's `Scripts/` directory, this resolves to a nonexistent path, causing `ModuleNotFoundError: No module named 'encodings'`.

Additionally, even after fixing stdlib access, SSL was broken because Python 3.8+ on Windows requires `os.add_dll_directory()` to find runtime DLLs — the old PATH-based DLL search no longer works.

**Three fixes applied in `_fix_maya_venv()`**:
1. **Directory junction** — `<venv>/Python` → `<maya_install>/Python` so mayapy's hardcoded path resolves correctly
2. **DLL copy** — `python311.dll` copied into `Scripts/` so the venv executable can load
3. **sitecustomize.py** — Written to venv's `site-packages/`, calls `os.add_dll_directory()` at startup to register Maya's `bin/` for SSL and other native extensions

**Also added**: `_pip_install_via_host()` fallback in `ensure_packages()` — if the venv's pip fails, falls back to using the original `mayapy.exe` with `--target` to install packages.

### 5. Bug Fix: Editor API Server Shutdown Error (`editor_api_server.py`)
**Error**: `EditorAPI server error: Event loop stopped before Future completed.`

**Root cause**: `stop_server()` calls `loop.stop()` immediately after `server.close()`. The event loop stops before `serve_forever()` can process the cancellation, raising a `RuntimeError`.

**Fix**: Added `except RuntimeError: pass` in `_server_thread_main()` alongside the existing `CancelledError` catch — this is a normal shutdown race, not a real error.

## Files Changed
- `mca_core/venv_manager.py` — Major: Maya venv fixes (junction, DLL, sitecustomize, pip fallback)
- `mca_core/editor_api_server.py` — Minor: suppress harmless shutdown RuntimeError

## Test Results
- Fresh `mayapy -c "setup_venv()"` creates working venv with junction, DLL, sitecustomize
- Venv Python can import ssl, pywinpty, pyflakes
- Plugin loads cleanly in Maya 2025 — no errors on open or close
