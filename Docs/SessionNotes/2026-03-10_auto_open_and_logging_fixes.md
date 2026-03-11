# Session Notes — 2026-03-10: Auto-Open & Logging Fixes

## Summary

Fixed two bugs preventing the MCA Editor from reliably auto-opening on Maya
startup and surviving plugin reloads.

---

## Bug 1: Plugin Reload Permanently Breaks Auto-Open

### Root Cause

`uninitializePlugin()` set `editor_was_open = False` in QSettings whenever
the plugin was manually unloaded (not Maya shutdown).  This was intended for
the "user disabled the plugin" case, but it also fired during a simple
reload (unload + load).  Since QSettings persists across sessions, a single
reload would permanently prevent auto-open until the user manually opened
the editor again.

Additionally, `_restore_mca_editor()` (the uiScript path) never set
`editor_was_open = True`.  Only `show_mca_editor()` did.  So even if the
editor opened via uiScript on restart, the flag stayed at whatever value
it had before — potentially False from a previous reload.

### Fix

- **`plugin_main.py` — `uninitializePlugin()`:** Removed the
  `editor_was_open = False` block entirely.  The flag is now only set to
  False in `dockCloseEventTriggered()` (user explicitly closes the editor),
  which is the correct semantic.

- **`maya_window.py` — `_restore_mca_editor()`:** Added
  `MCASettings().set("editor_was_open", True)` after the window is created,
  matching what `show_mca_editor()` already does.

---

## Bug 2: uiScript Restoration Produces Blank Windows

### Root Cause

Maya's workspace layout restore fires the `uiScript` to recreate the
editor panel.  The uiScript calls `_restore_mca_editor()`, which creates
a `MCAMayaWindow` and calls `.show(dockable=True)`.  In certain startup
sequences, the widget is correctly parented inside the workspace control
(verified: correct parent, correct size, `isVisible()=True`,
stylesheet applied) but **nothing renders** — the workspace control
appears as a grey rectangle with the title bar.

The previous `_do_auto_open_editor()` code checked if the uiScript had
already created a "healthy" window (objectName alive check) and returned
early, trusting it.  This left the blank window in place.

### Fix

- **`plugin_main.py` — `_do_auto_open_editor()`:** Simplified to always
  discard whatever the uiScript created and start fresh:
  1. Set `_mca_editor_window = None` and `_output_target = None`
  2. Delete the workspace control if it exists
  3. Call `show_mca_editor()` to create everything cleanly

  The `show_mca_editor()` path works reliably because it creates the
  workspace control from scratch rather than trying to populate an
  existing control from Maya's layout restore.

---

## Files Modified

| File | Change |
|------|--------|
| `mca_maya/plugin_main.py` | Simplified `_do_auto_open_editor()` — always fresh create via `show_mca_editor()` |
| `mca_maya/plugin_main.py` | Removed `editor_was_open = False` from `uninitializePlugin()` |
| `mca_maya/maya_window.py` | Added `editor_was_open = True` in `_restore_mca_editor()` |

## Files NOT Modified

- `maya_window.py` — `show_mca_editor()`, `_install_output_hook()`,
  `cleanup_editor()`, `dockCloseEventTriggered()` unchanged
- `editor_panel.py`, `output_window.py`, `plugin_main.py` startup
  scheduling unchanged

---

## Testing

1. Open Maya — editor auto-opens with content (not blank)
2. Close Maya — reopen — editor auto-opens again
3. Reload plugin (unload + load) — editor_was_open not cleared
4. Close editor (dock close) — reopen Maya — editor stays closed (correct)

---

## Known Limitation

There may be a brief visual flash on startup: Maya's layout restore creates
an empty workspace control shell (from the saved layout), which is then
deleted and replaced by a fresh one from `show_mca_editor()`.  This is
acceptable — the alternative (reusing the uiScript-created window) produces
blank windows.
