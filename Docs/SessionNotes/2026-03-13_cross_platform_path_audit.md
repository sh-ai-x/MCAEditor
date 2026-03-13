# Session Notes — 2026-03-13: Cross-Platform Path Audit

## Goal
Centralize all hardcoded Windows-only paths (`~/Documents/...`, `%LOCALAPPDATA%`) into
a single `platform_utils.py` module so the codebase works on Windows, macOS, and Linux.

## What Changed

### New File: `mca_core/platform_utils.py`
- 9 functions, pure stdlib (`os`, `sys`, `platform`), no type hints, Sphinx docstrings
- **Platform detection**: `get_platform()`, `is_windows()`, `is_macos()`, `is_linux()`
- **MCA dirs**: `get_preferences_dir()`, `get_cache_dir(maya_version, python_version)`
- **Maya dirs**: `get_maya_app_dir()`, `get_maya_scripts_dir(version)`, `get_maya_plugins_dir(version)`
- **Runtime**: `is_batch_mode()` — checks `cmds.about(batch=True)`
- All return `str`, never create directories (callers do `os.makedirs()` at point of use)
- Compiles to `.pyd` automatically (no Qt virtual overrides, not on exclusion list)

### Platform Path Rules
| Directory        | Windows                    | macOS                        | Linux                          |
|-----------------|----------------------------|------------------------------|--------------------------------|
| Preferences     | `~/Documents/mca_prefs/`   | `~/Documents/mca_prefs/`     | `~/.config/mca_prefs/`         |
| Cache           | `%LOCALAPPDATA%/MCAEditor-*`| `~/Library/Caches/MCAEditor-*`| `$XDG_CACHE_HOME/MCAEditor-*` |
| Maya app dir    | `~/Documents/maya`         | `~/Library/Prefs/Autodesk/maya`| `~/maya`                     |

### Files Modified
1. **`mca_core/__init__.py`** — `_prefs_dir` now calls `get_preferences_dir()` instead of hardcoding `~/Documents/...`
2. **`mca_core/editor_api_server.py`** — `_PREFS_DIR` uses `get_preferences_dir()`
3. **`mca_core/mcp_editor_server.py`** — Inline 3-way `sys.platform` check (can't import mca_core, standalone process)
4. **`pack_single_file.py`** — Template `_get_extract_dir()` now has 3-way platform check for cache dirs (can't import platform_utils, runs pre-extraction)
5. **`mca_maya/plugin_main.py`** — `_ensure_auto_load()` uses `get_maya_scripts_dir()` instead of hardcoded path
6. **`mca_maya/plugin_main.py`** — Added `is_batch_mode()` early return in `initializePlugin()` — batch mode registers the command but skips venv/UI/ports/license

### Files NOT Changed (already platform-aware)
- `build_maya.py` — has 3-way platform checks
- `mca_core/venv_manager.py` — has Scripts/bin, Lib/lib detection
- `mca_core/mcp_setup.py` — Claude CLI paths guarded by platform check
- `mca_maya/install.py` — has `_get_maya_app_dir()` with 3-way check
- `mca_core/license.py` — trial tracking already works cross-platform

## Build Verification
- Maya 2025 build passed — `platform_utils.py` compiled to `.pyd` as file 14/33
- All imports resolve correctly, paths match expected Windows values on this machine

## Notes
- `mcp_editor_server.py` and `pack_single_file.py` template cannot import `platform_utils` (standalone/pre-extraction), so they have inline platform checks that mirror the same logic
- Linux uses XDG conventions (`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`) with standard fallbacks
