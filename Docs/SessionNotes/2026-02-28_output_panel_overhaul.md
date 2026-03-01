# Session: Output Panel Overhaul (Phase 1 + Phase 2) — 2026-02-28

## Summary

Complete overhaul of the MCA Editor output panel to achieve content and
behavior parity with Maya's Script Editor and Charcoal Editor 2.  Two
phases of changes across three files.

## Phase 1: Performance and UX

### Problem
Output arrived in visible chunks instead of streaming smoothly.  The
panel showed a blinking text cursor (Maya's has none).  Focus could
jump away from the code editor during rapid output because each
message triggered `setTextCursor()` + `ensureCursorVisible()`.

### Fix
- **Batch buffering**: Messages queue in `_pending_messages` list and
  flush via a 16ms single-shot `QTimer` (~60fps), coalescing rapid
  output into a single paint cycle.
- **Document cursor**: `_flush_pending()` creates a cursor from
  `QTextCursor(document)` — data-only, no focus side effects.  No
  `setTextCursor()` call at all.
- **Smart auto-scroll**: Only scrolls to bottom if user was already
  at/near bottom.  Scrolling up to read history is preserved.
- **Cursor-less display**: `setCursorWidth(0)` hides the blinking
  text cursor.  `setAcceptDrops(False)` prevents drag-and-drop.
- **No word wrap**: `setLineWrapMode(NoWrap)` — long lines scroll
  horizontally, matching Maya's Script Editor.

## Phase 2: Content Parity

### Problem
Output content didn't match Maya's Script Editor side-by-side.
Missing `//` prefixes on info messages, extra Python `logging` lines
appearing that Maya's Script Editor never shows, and output arriving
in chunks instead of real-time streaming.

### Root Cause
The internal adapter's `_execute_python()` redirected `sys.stdout` to
`StringIO` during execution.  This short-circuited Maya's output
pipeline — output went directly from Python to MCA's panel, bypassing
the entire Maya output system that both Script Editor and
`MCommandMessage` callback rely on.

### Fix
- **Removed StringIO stdout capture** from `_execute_python()`.
  `print()` now flows through Maya's native stdout hook, which fires
  `MCommandMessage` callbacks.
- **Eval-first-then-exec pattern**: Single expressions route results
  through `MGlobal.displayResult()`.  Statements execute via bare
  `exec()` with no stdout capture.
- **Error routing**: Pure Python errors go through
  `MGlobal.displayError()`.  Maya `RuntimeError`s (from cmds calls)
  are skipped to avoid duplicate display (Maya already showed them).
- **MEL errors**: Removed manual `_on_error()` calls — Maya's output
  system fires `MCommandMessage` before the exception propagates.
- **MCommandMessage callback** (`_on_maya_output`) is now the SOLE
  output source for embedded mode.  No content filtering except
  `cutCopyPaste.mel` artifact suppression.
- **Removed focus save/restore** from `_on_maya_output()` — no longer
  needed with document cursor writes.

## Iterative Refinements

Based on user testing with side-by-side comparison:

- **Removed aggressive content filters**: Initially filtered out
  `[MCA - Module:` and `mca_core.*` lines, but Maya's Script Editor
  and Charcoal BOTH show these.  All content filters removed.
- **Blank line stripping in history**: `cmdScrollFieldReporter` stores
  entries with blank lines between them, but Maya renders them packed.
  Strip blank lines but keep all content.
- **Color-coded history**: `_load_maya_history()` parses each line and
  routes through `write_error()` / `write_warning()` / `write_result()`
  / `write_output()` so startup history has proper coloring.
- **Error color**: Red (`#f44747`) via `write_error()`.
- **Warning color**: Changed from orange (`#cca700`) to yellow
  (`#e5e510`) per user preference.
- **Word wrap disabled**: Horizontal scroll instead.

## Files Changed

| Action | File | Changes |
|--------|------|---------|
| MODIFY | `mca_qt/widgets/output_window.py` | Batch buffer, document cursor, `setCursorWidth(0)`, `setAcceptDrops(False)`, `setLineWrapMode(NoWrap)`, yellow warnings |
| MODIFY | `mca_maya/maya_window.py` | Sole-source `_on_maya_output()`, color-coded history, removed focus save/restore, removed content filters |
| MODIFY | `mca_core/adapters/internal_maya_adapter.py` | Removed StringIO capture, `MGlobal.displayResult/displayError`, RuntimeError heuristic, cleaned MEL error handling |
| CREATE | `Docs/SessionNotes/2026-02-28_output_panel_overhaul.md` | This file |
