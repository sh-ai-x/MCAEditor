# Session: License Key System & Cython Build Pipeline — 2026-03-02

## Summary

Implemented the full offline license key system (HMAC-SHA256 validation, trial
tracking, license dialog UI, startup gates). Built the Cython compilation
pipeline for Maya 2025 and the single-file packer (`mcaEditor.py`). Hit a
persistent Maya segfault in compiled code — narrowed it to Cython's
`wraparound=False` causing undefined behavior on negative list indexing, but
the crash persists after fixing that. Debug logging is baked into the current
deployed build to pinpoint the exact crash line.

---

## What Was Completed

### 1. License Key System (fully implemented)

- **`mca_core/license.py`** — HMAC-SHA256 offline validation, trial tracking
  (14 days), key format `MCA-XXXX-XXXX-XXXX-XXXX` (base32, 10 bytes payload).
  Contains `_HMAC_SECRET` that must be protected via compilation.
  - Key functions: `check_license()`, `validate_key()`, `store_license_key()`,
    `get_trial_status()`, `generate_key()`

- **`tools/generate_keys.py`** — CLI key generator (gitignored, never ships)

- **`pack_single_file.py`** — Single-file packer: base64-encoded zip embedded
  in a self-extracting Python file, extracts to `%LOCALAPPDATA%/MCAEditor/`

- **`mca_core/config/settings.py`** — Added `license_key` and
  `first_launch_date` to `_DEFAULTS`

- **`mca_qt/widgets/license_dialog.py`** — Modal QDialog with input mask
  `>AAA-AAAA-AAAA-AAAA-AAAA;_`, validation feedback, masked key display

- **`mca_qt/widgets/__init__.py`** — Added `LicenseDialog` export

- **`mca_standalone/main.py`** — Startup license gate (blocks on `needs_key`,
  shows trial notice on status bar)

- **`mca_maya/maya_window.py`** — Startup license gate (same logic, doesn't
  kill Maya on cancel — just doesn't open the editor)

- **`mca_qt/editor_panel.py`** — Replaced `_show_licensing()` placeholder
  with real dialog

- **`.gitignore`** — Added `tools/` directory

- **`dist/beta_keys.txt`** — Generated 10 beta keys (90-day expiry)

### 2. Build Pipeline Fixes

- **`pyproject.toml`** — Changed `license = "MIT"` to
  `license = {text = "MIT"}` for Maya 2025's older setuptools

- **`setup.py`** — Added `_find_maya_paths()` to locate Maya's non-standard
  `include/Python311/Python/` and `lib/` directories. Added `binding=True`
  Cython directive (required for PySide6/Shiboken). Changed to Extension
  objects with `include_dirs`/`library_dirs`.

- **`pack_single_file.py`** — Added `maya_useNewAPI = True` to the outer
  wrapper template (Maya 2025 needs this on the outer module, not the inner
  compiled one)

- **`build_maya.py`** — Added `mcp_maya_server.py` to `DIST_PURE_PYTHON`

### 3. Cython Directive: `wraparound=True`

Changed `setup.py` from `wraparound=False` to `wraparound=True`. The old
setting made `list[-1]` undefined behavior in compiled code — Cython accessed
raw memory before the list buffer instead of counting from the end. This was
confirmed as one crash source via debug logging (crash between steps 19a and
19b in `_restore_ui_state`, exactly where `sizes[-1]` was used).

---

## What's Still Broken — Maya Segfault

### Symptom
Maya crashes (segfault) when opening MCA Editor with fully compiled `.pyd`
files. The crash is in `python311.dll` at `PyObject_GetAttr` (offset
`0x14216`), which is an access violation on attribute lookup.

### What We Know
- **All 35 compiled modules import successfully** (test_compiled_imports.py)
- **All individual widgets instantiate fine** (MCACodeEditor, OutputWindow,
  MCASidebar, ToolStripe, TerminalTabPanel, EditorGroupContainer, etc.)
- **Crash is inside `MCAEditorPanel._restore_ui_state()`** — confirmed by
  instrumenting `__init__` with file-based logging
- **Same operations work perfectly from Python** — ran every line of
  `_restore_ui_state` manually from the Script Editor, all passed
- **Compiled method crashes even when called from Python context** — saved
  the compiled method reference, skipped it during `__init__`, called it
  after panel creation → still crashed
- **`wraparound=False` was ONE cause** — `sizes[-1]` was undefined behavior
  in compiled code. Fixed to `wraparound=True`, but crash persists (possibly
  at a different location now)

### Current State — Debug Build Deployed
The currently deployed `mcaEditor.py` has **file-based debug logging baked
into the compiled `_restore_ui_state`**. It writes step numbers to:

```
%LOCALAPPDATA%\MCAEditor\restore_debug.log
```

**Nathan needs to:**
1. Restart Maya
2. Load the mcaEditor plugin
3. After the crash, check `restore_debug.log`
4. Tell us the last step number in the log

The step numbers in the log are:
- `1` — got settings
- `2` — main splitter restored
- `3` — center splitter restored
- `4` — sidebar splitter restored
- `5` — sidebar visibility set
- `6` — output visibility set
- `7` — legacy terminal migration
- `8` — bottom terminal (8a/8b/8c/8d for sub-steps)
- `9` — bottom terminal done
- `10` — right terminal (10a-10e for sub-steps: setVisible, sizes(), check, singleShot, stripe)
- `11` — right terminal done
- `12` — whitespace rendering
- `13` — whitespace done
- `14` — font size done
- `DONE` — method completed successfully

### Previous Log (before wraparound fix)
```
19a: right terminal setVisible done
```
Crashed between 19a and the next line — which was `sizes[-1]` (now fixed).
The new log will show if that's resolved and where it crashes now.

### Theories for Remaining Crash
1. **`QTimer.singleShot` with compiled bound methods** — passing
   `self._right_terminal_panel.ensure_terminal` (a bound method on a
   compiled class) to Qt's timer might not work correctly through Shiboken
2. **Cython type inference + Qt return types** — `QSplitter.sizes()` returns
   a `QList<int>` wrapped by Shiboken; Cython might optimize attribute
   access on the result in ways that conflict with Shiboken's proxy
3. **Another `boundscheck=False` issue** — though less likely since list
   operations typically go through Python's `__getitem__` protocol

### Files Used for Debugging
- `tools/test_compiled_imports.py` — imports all 35 modules one by one
- `tools/test_compiled_widgets.py` — instantiates widgets with logging

---

## Important Rules (from Nathan)

- **ALL code must be compiled to `.pyd`** — no `.py` files except
  `__init__.py`. Code protection is mandatory and non-negotiable.
- **Run commands yourself** — don't ask Nathan to run builds, tests, etc.
- **Extraction cache** at `%LOCALAPPDATA%/MCAEditor/` must be deleted when
  testing new builds (same version `0.1.0` won't re-extract otherwise)

## Build & Deploy Commands

```bash
# Full build + pack + deploy cycle:
cd E:/Projects/MCAEditor
python build_maya.py
python pack_single_file.py
rm -rf "$LOCALAPPDATA/MCAEditor"
cp dist/mcaEditor.py "$USERPROFILE/Documents/maya/2025/plug-ins/mcaEditor.py"
```

## Files Modified This Session

| File | Change |
|------|--------|
| `mca_core/license.py` | NEW — license validation |
| `tools/generate_keys.py` | NEW — key generator CLI |
| `pack_single_file.py` | NEW — single-file packer (+ maya_useNewAPI fix) |
| `mca_core/config/settings.py` | Added license_key, first_launch_date |
| `mca_qt/widgets/license_dialog.py` | NEW — license entry dialog |
| `mca_qt/widgets/__init__.py` | Added LicenseDialog export |
| `mca_standalone/main.py` | Startup license gate |
| `mca_maya/maya_window.py` | Startup license gate + try/except around window |
| `mca_qt/editor_panel.py` | Replaced _show_licensing() + debug logging in _restore_ui_state |
| `.gitignore` | Added tools/ |
| `pyproject.toml` | License format fix for old setuptools |
| `setup.py` | Maya paths, binding=True, wraparound=True |
| `build_maya.py` | Added mcp_maya_server.py to DIST_PURE_PYTHON |
| `dist/beta_keys.txt` | 10 beta keys (90-day expiry) |
| `tools/test_compiled_imports.py` | Diagnostic script |
| `tools/test_compiled_widgets.py` | Diagnostic script |
