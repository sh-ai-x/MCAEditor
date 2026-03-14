# Session Notes — 2026-03-13: macOS Build Support

## Summary
Made `build_maya.py`, `setup.py`, `venv_manager.py`, and `mcp_setup.py`
cross-platform so the MCA Editor compiles and runs on macOS. All changes
are additive — Windows code paths are untouched.

## Build Script Changes

### `setup.py` — macOS include path fix
- **Problem:** `distutils.sysconfig` returns the system Python framework path
  instead of Maya's embedded framework, causing "Python.h not found" errors.
- **Fix:** Added macOS early-return in `_find_maya_paths()` that uses
  `sysconfig.get_path("include")` (which IS correct on macOS) instead of
  the broken distutils path.
- Windows code path unchanged.

### `build_maya.py` — cross-platform build
- `MAYAPY_TEMPLATE` now has per-platform paths:
  - macOS: `/Applications/Autodesk/maya{version}/Maya.app/Contents/bin/mayapy`
  - Windows: `C:/Program Files/Autodesk/Maya{version}/bin/mayapy.exe` (unchanged)
  - Linux: `/usr/autodesk/maya{version}/bin/mayapy`
- Added `COMPILED_EXT` constant (`.pyd` on Windows, `.so` on Mac/Linux)
- `create_dist_structure()` uses `COMPILED_EXT` instead of hardcoded `.pyd`
- `clean_source_tree()` now also cleans `.so` files alongside `.pyd` and `.c`

## Venv Manager Changes (`mca_core/venv_manager.py`)

### Maya → mayapy lookup (macOS fix)
- `ensure_venv()` now finds `mayapy` (not `mayapy.exe`) on macOS
- Uses `os.path.join(exe_dir, "mayapy")` on POSIX vs `"mayapy.exe"` on Windows

### Post-creation executable rename
- After venv creation on macOS, copies `bin/mayapy` → `bin/python` so pip
  and ensurepip work (same pattern as Windows `Scripts/mayapy.exe → python.exe`)

### `get_venv_python()` — POSIX fallback names
- Now checks `python`, `mayapy`, `python3` in `bin/` (was only `python`)

### `_pip_install_via_host()` — platform-aware exe search
- Windows: `mayapy.exe`, `python.exe`
- POSIX: `mayapy`, `python3`, `python`

## MCP Setup Changes (`mca_core/mcp_setup.py`)

### `_find_system_python()` — mayapy fallback
- When no system Python 3.10+ is found, falls back to Maya's `mayapy`
  (which is 3.10+ in Maya 2024+)
- Added `_find_mayapy()` helper that locates mayapy from `sys.executable`

### `_setup_venv()` — mayapy-aware venv creation
- Detects if using mayapy and creates venv with `--without-pip` to avoid
  early crash (ensurepip fails before stdlib path is fixed)
- Calls `_fix_mayapy_venv()` after creation, then bootstraps pip separately

### `_fix_mayapy_venv()` — stdlib path fix (new function)
- **macOS:** Creates symlink `<venv>/Frameworks/` → Maya's
  `Contents/Frameworks/` so the venv Python can find `Python.framework`
  and the standard library (`encodings`, `os`, etc.)
- **Windows:** Creates directory junction `<venv>/Python/` → Maya's
  `Python/` directory (same logic as `venv_manager._fix_maya_venv()`)

### `_ensure_pip_in_venv()` — pip bootstrapping (new function)
- Tries `ensurepip` first
- Falls back to host interpreter `pip install --target` if ensurepip fails

### `_pip_install_via_host()` — package install fallback (new function)
- Uses host interpreter with `--target` pointing to venv site-packages

## Mac Build Environment (Mac Mini)
- Maya 2024, 2025, 2026 all installed
- Xcode CLI tools installed
- System Python: 3.9.6 (below 3.10 minimum — MCP falls back to mayapy)
- GitHub credentials in macOS Keychain
- Build command: `python3 build_maya.py --maya-version 2025`

## Build Verification
- Maya 2025 macOS build: 34 files Cythonized to `.cpython-311-darwin.so`
  (universal2 arm64 + x86_64), 27 .pyc files, 77 total packed
- Plugin loaded in Maya 2025, extracted, venv created with packages
- MCP venv creation had framework symlink issue — fixed in final iteration

## Known Issues
- Logging/output panel issue reported — also happens on Windows, not
  macOS-specific. Nathan to investigate on Windows side.
