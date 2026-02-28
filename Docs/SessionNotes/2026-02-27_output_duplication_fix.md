# Session: Output Duplication Fix — 2026-02-27

## Summary

Fixed two bugs in the Maya dockable editor window:

1. **Massive output duplication** — The output panel appeared to show
   the startup sequence repeated 10-20 times every time the editor opened.
2. **Stale output callbacks** — Maya output hook could be orphaned when
   the window was recreated during layout restore, causing lost output.

## Root Cause: Output Duplication

`_load_maya_history()` in `maya_window.py` creates a temporary
`cmdScrollFieldReporter` widget and reads Maya's entire accumulated
session output buffer. This was then dumped into the output panel
via `write_bulk()`.

The problem: `_restore_output()` (in `editor_panel.py`) ALSO loads
the saved `output.log` from the previous session.  So every time the
editor opened:

1. `_restore_output()` inserts the saved output.log
2. `_load_maya_history()` inserts Maya's FULL session buffer on top

Since Maya's session buffer includes everything from ALL previous
editor opens (startup logs, code output, etc.), the output panel
grew exponentially with each open — appearing as if the startup
ran 10-20 times.

### Fix

Disabled `_load_maya_history()` by removing the
`QTimer.singleShot(0, self._load_maya_history)` call in `__init__`.
Left the method intact with a detailed comment explaining why it
was disabled.

The output hook (`_on_maya_output` via `MCommandMessage`) captures
all NEW Maya output going forward, and `_restore_output()` provides
session continuity.  Together they make the history load unnecessary.

## Fix: Stale Output Callbacks

Moved `_output_callback_id` from an instance variable to a
module-level variable so it survives window recreation during
Maya's `uiScript` layout restore.

Also added:
- Cleanup of old callbacks before installing new ones in
  `_install_output_hook()`
- Guard in `_restore_mca_editor()` to prevent repeated
  uiScript calls from creating multiple window instances
- Explicit callback cleanup in `show_mca_editor()` during
  window teardown

## Files Changed

| Action | File |
|--------|------|
| MODIFY | `mca_maya/maya_window.py` |
| CREATE | `Docs/SessionNotes/2026-02-27_output_duplication_fix.md` |
