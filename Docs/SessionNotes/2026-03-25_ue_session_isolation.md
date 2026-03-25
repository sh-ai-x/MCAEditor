# Session Notes — 2026-03-25: UE Session Isolation & Double Logging Fix

## Summary

Fixed multiple issues with the UE (Unreal Engine) plugin integration:
UE freeze on editor launch, double logging, error coloring, WARNING
detection, and session isolation between Maya and UE.

## Issues Fixed

### 1. UE Freeze on Editor Launch (QtWebEngine/CEF3 Deadlock)

**Root cause**: `terminal_factory.py:is_terminal_available()` imported
`PySide6.QtWebEngineWidgets` which loads Chromium. UE already has CEF3
(Chromium) in-process — two Chromium instances in the same process deadlocked.

**Fix**: Added `_is_inside_ue()` detection (checks `import unreal`) that
guards both `is_terminal_available()` and `create_terminal_widget()` to
skip all QtWebEngine probes when running inside UE. The native terminal
(QPlainTextEdit + pywinpty) is used instead.

**Gotcha**: After copying the fixed `.py`, the old
`terminal_factory.cp311-win_amd64.pyd` took precedence (Python prefers
`.pyd` over `.py`). Had to delete the `.pyd` for the fix to load.

### 2. Error Coloring (Yellow Instead of Red)

**Root cause**: `_execute_locally()` in `editor_panel.py` routed ALL
stderr output to `write_warning()` (yellow). Errors should be red.

**Fix**: Content-based routing — lines containing "ERROR" or "Error" go
to `write_error()` (red), everything else to `write_warning()` (yellow).
In UE mode, stderr is not redirected at all (UE's logging captures it).

### 3. Double Logging in UE

**Two sources of duplication**:

a) **stderr capture + log tailer**: `_execute_locally()` redirected stderr
   AND the UE log tailer picked up the same output from UE's log file.
   Fix: Don't redirect stderr in UE mode.

b) **Traceback echo via `_ue.log_error()`**: Multi-line tracebacks logged
   via `_ue.log_error()` appeared as separate lines in UE's log file.
   Only the first line had `[MCAEditor]` prefix, so the log tailer's skip
   filter missed subsequent lines — they showed as white duplicates.
   Fix: Echo only the final exception line (single line, prefixed).
   Also fixed stdout echo to prefix every line with `[MCAEditor]`.

### 4. WARNING Detection (Case Sensitivity)

**Root cause**: `_route_line()` in `ue_editor_host.py` checked for
`Warning:` (title case) but UE startup messages use `WARNING:` (all caps).

**Fix**: Case-insensitive matching via `.upper()` comparison.

### 5. Session Isolation — QSettings (Partial)

**Root cause**: Maya and UE shared the same QSettings store
(`HKCU\Software\MCATools\MCAEditor`).

**Fix**: Added `dcc_version` parameter to `MCASettings.__init__()` that
suffixes the app name. UE uses `MCASettings(dcc_version="UE5")` which
creates a separate registry key `MCAEditor-UE5`. Applied to both the
editor creation (line 626) and shutdown save (line 1041) in
`ue_editor_host.py`.

### 6. Session Isolation — Project Session File (Final Fix)

**Root cause**: Even with QSettings isolated, both Maya and UE auto-opened
the same project (`last_project_path` pointed to the same directory in
both). The project's tab layout was stored in a single shared file
(`.mca-session.json` in the project root), so both DCCs loaded the same
tabs.

**Fix**: Made `MCAProject.session_file_path` DCC-aware. When `dcc_tag` is
set, it returns a DCC-specific filename:
- UE5: `.mca-session-UE5.json`
- Maya2025: `.mca-session-Maya2025.json`
- Standalone: `.mca-session.json` (default)

This was in `mca_core/project.py` which compiles to `.pyd`, so all three
Maya builds (2024, 2025, 2026) were rebuilt.

## Debugging Lessons

- **`__pycache__` is the enemy**: UE's Python creates `__pycache__/` dirs
  that cache old `.pyc` files. When deploying fixed `.py` files over
  `.pyd` files, the `__pycache__` cached version of the OLD code takes
  precedence. Must delete ALL `__pycache__` dirs after every deploy.

- **`.pyd` takes precedence over `.py`**: When manually patching a
  deployed plugin by copying `.py` files, any existing `.pyd` with the
  same module name MUST be deleted first.

- **Trace the full data flow**: The session isolation required fixes at
  THREE levels: QSettings (registry), SessionManager (file-based session
  dir), and MCAProject (per-project session manifest). Fixing only one
  or two levels left shared state leaking through.

## Files Changed

- `mca_core/config/settings.py` — Added `dcc_version` parameter
- `mca_core/project.py` — DCC-specific session file path
- `mca_qt/editor_panel.py` — Error coloring, double log fix, single-line traceback echo
- `mca_qt/widgets/terminal_factory.py` — UE detection, skip QtWebEngine
- `mca_unreal/Content/Python/ue_editor_host.py` — WARNING case fix, log history cap, settings isolation
- `setup.py` — Environment variable support for custom Python include/lib paths
- `build_unreal.py` — UE Python dev path detection, env var bridge to setup.py

## Builds

- Maya 2024, 2025, 2026 — all rebuilt and deployed
- UE plugin — manually patched at `E:\Rascal\depot\Wayward\Plugins\MCAEditor-UE5.5-v1.0.5\`
