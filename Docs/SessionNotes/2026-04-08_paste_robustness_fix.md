# Session Notes — 2026-04-08: Paste Robustness Fix (Maya Event Filter)

## Problem

Ctrl+V paste in the MCA Editor in Maya stops working after a while.
This is a recurring issue — previous fixes addressed terminal-specific
failure modes, but the Maya hotkey filter's Phase 2 dispatch had
several silent failure paths that could swallow paste events.

---

## Changes Made

### 1. Stale QAction Crash Protection (`maya_window.py` — `_find_matching_action`)
- **Problem**: If any QAction in the `_action_registry` had its C++ object
  garbage-collected, calling `.shortcut()` raised RuntimeError. This crashed
  the entire Phase 2 dispatch — ALL modifier shortcuts (Ctrl+V, Ctrl+C,
  Ctrl+S, etc.) silently stopped working.
- **Fix**: Wrapped each action's shortcut check in try/except. Also wrapped
  the `_find_matching_action()` call site in the event filter. Stale actions
  are skipped instead of crashing the search.

### 2. Dead Terminal Swallowing Paste (`maya_window.py` — Phase 2 terminal path)
- **Problem**: `terminal.eventFilter()` was called unconditionally and its
  return value was ignored — line 658 always returned True. When the terminal
  process had exited (`_alive=False`), the filter returned False (unhandled),
  but the event was consumed anyway. Paste silently failed.
- **Fix**: Check `terminal._alive` before routing. Respect the return value
  of `terminal.eventFilter()`. Dead terminals log a debug message and consume
  the event (to block Maya hotkeys) without attempting paste.

### 3. Read-Only Widget Paste Redirect (`maya_window.py` — Phase 2 non-terminal path)
- **Problem**: When focus was on the output panel (a read-only QPlainTextEdit),
  `focus.paste()` silently did nothing. The user perceived paste as "broken"
  after clicking the output panel.
- **Fix**: Before calling `focus.paste()`, check `focus.isReadOnly()`. If the
  widget is read-only and the operation needs a writable target (paste, cut),
  redirect to `self._panel._current_editor()`. Copy and selectAll still work
  on read-only widgets as expected.

### 4. Fallback to Active Editor (`maya_window.py` — Phase 2 non-terminal path)
- **Problem**: When the focused widget (file tree, toolbar, etc.) didn't have
  a `.paste()` method, the code fell through to `keyPressEvent()` which
  typically ignored Ctrl+V.
- **Fix**: If the focused widget can't handle the text operation, try
  `self._panel._current_editor()` as a last resort before falling back to
  `keyPressEvent`.

### 5. Diagnostic Logging for Paste
- Added DEBUG-level logging at every Ctrl+V decision point: focus widget
  resolution, read-only redirect, terminal liveness, no-focus warnings.
- These will be visible in Maya's output when debugging but won't spam
  during normal use.

---

## Files Changed
- `mca_maya/maya_window.py` — `_find_matching_action` stale action guard,
  Phase 2 terminal liveness check, read-only redirect, active editor
  fallback, diagnostic logging

## Build & Deploy Status

| Platform | Version | Status |
|----------|---------|--------|
| Maya 2024 Windows | v1.0.10 | Built + deployed locally |
| Maya 2025 Windows | v1.0.10 | Built + deployed locally |
| Maya 2026 Windows | v1.0.10 | Built + deployed locally |

## Testing Checklist (Nathan testing 2026-04-09)
- [ ] Ctrl+V in code editor — works
- [ ] Ctrl+V in terminal (live shell) — works
- [ ] Ctrl+V in terminal after process exits — no silent failure
- [ ] Ctrl+V when output panel has focus — redirects to code editor
- [ ] Ctrl+V when file tree has focus — redirects to code editor
- [ ] Ctrl+C (copy) from output panel — still works (read-only OK)
- [ ] Ctrl+V after extended use (30+ min) — still works
- [ ] All other Ctrl+ shortcuts (Ctrl+S, Ctrl+Z, Ctrl+C, etc.) — still work
