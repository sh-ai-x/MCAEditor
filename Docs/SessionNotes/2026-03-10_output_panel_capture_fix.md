# 2026-03-10: Output Panel Capture Fix (v0.3.6)

## Problem

The MCA Editor output panel was not showing the same logs that Maya's Script Editor shows. The user's MCA framework startup produces extensive logging output (`[MCA - Module: ...]` lines, ASCII banners, framework status) that appeared in Maya's Script Editor but was completely missing from our output panel.

This had been broken across multiple versions and multiple attempted fixes.

## Root Cause Analysis

### Discovery 1: MCommandMessage does NOT capture print() from exec'd code

`MCommandMessage.addCommandOutputCallback` (the "Phase 2" approach from 2026-02-28) only captures output from Maya's C++ command system:
- MEL echo, `cmds.warning()`, `cmds.error()`, `MGlobal.displayInfo()`
- Python output executed via Maya's command port (7002)
- Script Editor "Execute" button output

It does **NOT** capture:
- `print()` from directly `exec()`'d Python code (our `InternalMayaAdapter`)
- Python `logging` module output (goes to stderr)
- Output from deferred callbacks and framework startup

### Discovery 2: Temporary vs permanent tees

- **v0.3.4 (temporary tee)**: Captured exec-time print() output correctly, but missed deferred callback output (framework startup logging)
- **v0.3.5 (permanent tee only)**: Captured deferred callback output ("Running project startup...") but exec-time print() was lost — the permanent tee on `sys.stdout` doesn't capture print() during exec for reasons still under investigation (likely related to the double-creation cycle during Maya startup)

### Discovery 3: Three separate output streams need capture

1. **Python stdout** (print calls) — needs stdout tee
2. **Python stderr** (logging module) — needs stderr tee
3. **Maya C++ output** (MEL echo, cmds.warning/error) — needs MCommandMessage

## Solution (v0.3.6): Hybrid four-mechanism capture

### 1. Temporary stdout tee during exec (adapter)
`InternalMayaAdapter._execute_python()` installs a `_TeeWriter` that:
- Bypasses the permanent tee (unwraps `_original` chain) to avoid double writes
- Captures to StringIO buffer while passing through to Maya's raw stdout
- Returns captured text; `_write_adapter_output()` writes it to the panel

### 2. Permanent stdout tee (`_StdoutTee`)
Installed on `sys.stdout` by `maya_window._install_output_hook()` at window creation.
Captures ALL Python print() output outside of exec — deferred callbacks, framework startup, module imports.

### 3. Permanent stderr tee (`_StderrTee`)
Installed on `sys.stderr` — captures Python logging module output with ERROR/WARNING pattern detection for color coding.

### 4. MCommandMessage callback
`_on_maya_output()` routes kError, kWarning, kResult, kInfo from Maya's C++ system. kDisplay routes MEL echo (not duplicated by stdout tees since MEL output doesn't go through Python's sys.stdout).

## Files Changed

- **`mca_core/__init__.py`** — Version bumped to 0.3.6; added preferences migration from flat `mca_preferences/` to `mca_preferences/MCAEditor/` subfolder
- **`mca_core/adapters/internal_maya_adapter.py`** — Added `_TeeWriter` class; `_execute_python()` uses temporary tee that bypasses permanent tee, returns captured stdout
- **`mca_maya/maya_window.py`** — Added `_StdoutTee` class; `_install_output_hook()` installs both stdout and stderr tees; shutdown/cleanup restores both; `_on_maya_output` broadened exception handling
- **`mca_qt/editor_panel.py`** — Added `_write_adapter_output()` helper; execute methods write captured adapter output to panel
- **`mca_core/mcp_setup.py`**, **`mca_core/session_manager.py`**, **`mca_core/venv_manager.py`**, **`mca_core/plugins/__init__.py`**, **`mca_core/editor_api_server.py`**, **`mca_core/mcp_editor_server.py`** — Updated to use `mca_core.get_prefs_dir()` for preferences path
- **`mca_qt/widgets/plugin_settings_dialog.py`** — Updated prefs path usage

## Key Insight

Maya's output capture is NOT a single mechanism. Three completely independent streams exist, and each requires its own capture:
- MCommandMessage for Maya C++ output
- sys.stdout tee for Python print()
- sys.stderr tee for Python logging

The "Phase 2" approach (MCommandMessage-only) was always incomplete — it could never capture print() from exec'd code. The original session notes from 2026-02-28 were incorrect in stating MCommandMessage captures "ALL output including print()."

## Status

v0.3.6 deployed and ready for testing. Exec-time print() capture confirmed working (v0.3.4 approach). Permanent tee for deferred callback output confirmed working (v0.3.5 showed "Running project startup..."). Need to verify the combined approach shows ALL output on fresh Maya launch.
