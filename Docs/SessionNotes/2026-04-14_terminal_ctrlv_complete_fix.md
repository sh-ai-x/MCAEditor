# Session Notes — 2026-04-14: Complete Ctrl+V Terminal Paste Fix

## Problem

Ctrl+V stops pasting into the terminal after a few minutes of MCA Editor
use.  Prior fixes addressed individual failure modes but never solved
the compound problem.  The user explicitly asked for a full-stack audit
and fix — no more whack-a-mole.

## Full-Stack Audit Findings

Audited the complete paste path:
1. Qt app-level event filter (`_MayaHotkeyFilter.eventFilter`)
2. `_focus_forced_widget` fallback mechanism
3. `_find_matching_action` QAction dispatch
4. `_find_parent_terminal` tree walk
5. `TerminalWidget._handle_key_press` Ctrl+V branch
6. `TerminalWidget.paste_clipboard`
7. `AnsiParser` bracketed paste mode state
8. `TerminalBackend` ConPTY write path
9. `TerminalWidget.restart` / `start` lifecycle

Found **9 distinct bugs** that combined to produce the observed
"Ctrl+V dies after minutes" symptom.

## Fixes Applied (11 total across 3 files)

### `mca_maya/maya_window.py` — 5 fixes

1. **Stale parent walk in `_find_parent_terminal`**
   - Wrapped `parent.parent()` in try/except RuntimeError (C++-deleted
     widgets raise on attribute access).  Added depth limit of 32 to
     cap runaway loops.

2. **Stale QAction crash in Phase 2 dispatch**
   - Wrapped `action.isEnabled()` / `action.trigger()` in try/except
     RuntimeError so one dead action can't kill the whole dispatch.

3. **Stale `_focus_forced_widget` crash in Phase 2**
   - Added `focus.parent()` liveness probe before use; if RuntimeError
     fires, clear the reference and fall back to `_current_editor()`.

4. **Dead terminal silently ate Ctrl+V** ⭐ (most likely root cause)
   - When shell exited (Claude Code crash, `exit`, Ctrl+D), the old
     Phase 2 branch consumed Ctrl+V without doing anything.  User saw
     "paste stopped working" with no explanation.
   - Fix: auto-restart terminal via `terminal.restart()` then queue
     the paste with `QTimer.singleShot(500, terminal.paste_clipboard)`
     to give the new shell time to initialize.

5. **`_focus_forced_widget` went stale on every focus change**
   - `_on_app_focus_changed` now refreshes the reference whenever
     focus lands inside the editor tree, so the fallback stays fresh.

### `mca_qt/widgets/terminal_native.py` — 4 fixes

6. **`paste_clipboard` had no backend-alive guard**
   - Now checks `self._backend._running` first and returns False early
     if the PTY thread died.  Previously would silently write bytes
     to a dead pipe.

7. **`paste_clipboard` crashed on clipboard read failure**
   - Wrapped `clipboard.text()` in try/except.  PySide6 can raise on
     certain clipboard contention scenarios.

8. **`paste_clipboard` returned None on all paths**
   - Now returns True/False consistently so callers can react to
     failure (`_handle_key_press` Ctrl+V branch uses this).

9. **`start()` didn't reset display/parser state**
   - Added `self._parser.clear()` + `self._display.clear()` on every
     `start()` so restart paths get a clean slate.

### `mca_qt/widgets/ansi_parser.py` — 2 fixes

10. **`AnsiParser.clear()` didn't reset DEC private modes**
    - `_bracketed_paste` (mode 2004) was leaking across restart,
      causing paste failures in simple shells that didn't send the
      reset sequence.  Now clears bracketed paste, cursor visibility,
      alt screen state, scroll region, and SGR state.

11. **`AnsiParser.clear()` didn't reset alt screen snapshots**
    - `_alt_grid`, `_alt_cursor`, etc. survived clear.  If a TUI app
      was running when the shell died, the next session inherited
      alt-screen state.  Fixed in same edit as #10.

## Why This Fixes the "After A Few Minutes" Bug

The most common failure scenario:
1. User runs Claude Code or similar TUI in the terminal
2. TUI sets bracketed paste mode (ESC[?2004h) + enters alt screen
3. TUI crashes or user exits — shell dies
4. Backend thread stops, `_alive` flips to False
5. User presses Ctrl+V → Phase 2 eats event, nothing happens
6. User is confused, thinks paste is broken

After this fix:
1-4. Same as above
5. User presses Ctrl+V → Phase 2 detects dead terminal, calls
   `restart()` which clears parser state (including stuck bracketed
   paste mode), spawns a new shell, and queues the paste
6. 500ms later, paste succeeds into the fresh shell

## Files Changed

- `mca_maya/maya_window.py` — 5 fixes (event filter robustness, dead-
  terminal auto-restart, focus-forced refresh)
- `mca_qt/widgets/terminal_native.py` — 4 fixes (paste guards, start
  reset)
- `mca_qt/widgets/ansi_parser.py` — 2 fixes (full state reset in clear)

## Testing Checklist

- [ ] Ctrl+V in live terminal — pastes
- [ ] Ctrl+V after `exit` — auto-restarts and pastes
- [ ] Ctrl+V after Claude Code crash — auto-restarts and pastes
- [ ] Ctrl+V after running TUI + exit (bracketed paste was set) —
      pastes cleanly without escape sequences leaking into shell
- [ ] Ctrl+V after 30+ min idle — still works
- [ ] Ctrl+C / Ctrl+S / other modifier shortcuts — unaffected
- [ ] No spam in logs during normal paste operations (DEBUG only)
