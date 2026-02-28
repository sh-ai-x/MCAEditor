# Session: Inline Startup Code & Output Bug — 2026-02-27

## Summary

Added inline startup code support to the Project Settings dialog so users
can either point to a script file OR type a small Python snippet that runs
when the project opens (after sys.path and env vars are applied).  Also
identified a bug where the output panel stops displaying output after
opening a project in Maya — investigation is in progress.

## Fresh Clone

The local repo was out of sync with the remote (local was at `c87f730`,
remote at `61c8813`).  Wiped the project directory and did a fresh
`git clone` to get a clean starting point.

## Feature: Inline Startup Code

### Project Model (`mca_core/project.py`)
- Added `_startup_code` instance variable (inline Python string)
- Added `startup_code` property with getter/setter
- `load()` now reads `startup_code` from the `.mca-project` JSON
- `to_dict()` now serializes `startup_code`
- Updated module docstring to mention inline code

### Project Settings Dialog (`mca_qt/widgets/project_settings_dialog.py`)
- Added `QPlainTextEdit` import
- Added `_CODE_EDIT_STYLE` constant (dark monospace editor look)
- Expanded the "Startup Script" group box:
  - File path row stays as-is (QLineEdit + Browse button)
  - New label: "Inline code (runs after the script file, if any)"
  - New `QPlainTextEdit` (`_code_edit`) with monospace font, placeholder,
    min height 90px, max height 160px, tab stop ~4 spaces
- `_on_save()` now includes `startup_code` in the result dict
- Bumped dialog minimum height from 450 to 600 to fit the new section

### Editor Panel (`mca_qt/editor_panel.py`)
- `_show_project_settings()` now applies `startup_code` from the dialog result
- `_run_startup_script()` rewritten to support both file and inline code:
  - Runs the script file first (if configured)
  - Runs inline code second (if configured)
  - Either or both can be used independently
  - Both route through the active adapter or local execution

### Updated .mca-project Format

```json
{
    "startup_script": "scripts/startup.py",
    "startup_code": "import os\nprint('Project loaded from', os.getcwd())"
}
```

## Bug: Output Panel Stops Working After Project Open (Maya)

### Symptoms
- Running inside Maya (internal adapter, docked plugin)
- Opening a project shows startup messages and code output correctly
- After that, executing code or performing Maya actions produces NO output
  in MCA Editor's output panel
- The output panel is still visible — it just never updates

### Investigation So Far
- Output callbacks (`_on_output`, `_on_error`) are set once during init and
  never reset — confirmed they stay intact
- `_suppress_output_hook` flag (used by `_echo_to_script_editor`) has a
  `finally` block that always clears it — should not get stuck
- Maya output hook (`MCommandMessage.addCommandOutputCallback`) is only
  removed on dock close — should remain active during project open
- `sys.stdout` redirect in `_execute_python` has a `finally` block that
  always restores — should not get stuck
- No code in the project opening flow touches output panel visibility
- Splitter sizes are not modified during project open

### Next Steps
- Need to determine: does the **code echo** (blue text) still appear when
  executing after project open?  If not, the issue is in `_execute_all`
  or the output panel itself.  If yes, the issue is in the adapter.
- Check if Maya's Script Editor still shows output — if it does, the
  Maya output hook may have been disconnected
- Try adding debug logging to `_on_maya_output` to see if the callback
  fires but messages are filtered
- Consider whether clearing the output panel and retrying fixes it
- May need to test with a minimal project (no startup script) to isolate
  whether the startup script execution itself causes the issue

## Files Changed

| Action | File |
|--------|------|
| MODIFY | `mca_core/project.py` |
| MODIFY | `mca_qt/editor_panel.py` |
| MODIFY | `mca_qt/widgets/project_settings_dialog.py` |
| CREATE | `Docs/SessionNotes/2026-02-27_inline_startup_code.md` |
