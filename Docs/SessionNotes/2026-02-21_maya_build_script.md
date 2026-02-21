# Session: 2026-02-21 — Maya 2025 Build & Distribution Script

## Summary
Created a build pipeline that Cython-compiles all MCA Editor source into `.pyd` native binaries and packages them as a distributable zip for Maya 2025 plugin installation.

## Changes Made

### New File: `build_maya.py`
Full build orchestration script (~310 lines) run with `python build_maya.py`. Pipeline steps:
1. **Locate mayapy.exe** — Default `C:/Program Files/Autodesk/Maya2025/bin/mayapy.exe`, override via `--mayapy`.
2. **Ensure Cython** — Auto-installs via `mayapy -m pip install --user cython` if missing.
3. **Clean** — Removes previous `build/` and `dist/` directories.
4. **Compile** — Runs `mayapy setup.py build_ext --inplace` to create `.pyd` files in-place.
5. **Package** — Copies `.pyd` + `__init__.py` into `dist/MCAEditor-Maya2025/` for `mca_core`, `mca_qt`, `mca_maya` only (skips `mca_standalone` and `mca_editor`).
6. **Resources** — Copies `resources/images/*.png` into dist.
7. **Install scripts** — Generates standalone `install_maya.py` and `uninstall_maya.py` (plain Python, no proprietary code) that create/remove `.mod` files and plugin stubs in Maya's directories.
8. **Zip** — Creates `dist/MCAEditor-Maya2025-v0.1.0.zip`.
9. **Clean source** — Removes in-place `.pyd`, `.c`, and `build/` artifacts from the source tree.

### Modified: `.gitignore`
- Added `*.c` under Distribution/Cython section (Cython intermediate files).

### Not Modified: `setup.py`
- Reviewed for `mca_editor` exclusion — already not in the `packages` compilation list. No changes needed.

## Distribution Structure
```
MCAEditor-Maya2025/
├── install_maya.py          # Plain .py — registers with Maya
├── uninstall_maya.py        # Plain .py — unregisters from Maya
├── mca_core/                # Compiled .pyd + __init__.py
│   ├── adapters/
│   └── config/
├── mca_qt/                  # Compiled .pyd + __init__.py
│   └── widgets/
├── mca_maya/                # Compiled .pyd + __init__.py
└── resources/images/        # Icons (mca.png, python_logo.png)
```

## Design Decisions
- **`--user` pip install**: Uses `pip install --user cython` to avoid needing admin rights on Maya's `Program Files` directory.
- **In-place compile then copy**: Compiles in the source tree, then selectively copies only `.pyd` and `__init__.py` to dist. This keeps the dist clean without source `.py` files.
- **Install scripts as templates**: Embedded as string constants in `build_maya.py` and written to dist at build time. They contain no proprietary logic — just filesystem operations.
- **Version via `.replace()`**: The install script template uses `.replace("__VERSION__", VERSION)` instead of `.format()` to avoid conflicts with `{}` format strings inside the template.

## Testing
- Build: `python build_maya.py`
- Install: Unzip, run `python install_maya.py`, open Maya 2025, load plugin from Plug-in Manager.
- Verify `.pyd` files are not human-readable (code protection).
