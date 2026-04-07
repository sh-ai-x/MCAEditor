# Session Notes — 2026-04-07: Terminal Blank Lines & Copy/Paste Fix

## Version: 1.0.11

---

## Changes Made

### 1. Fix Huge Blank Gaps in Terminal (`terminal_native.py`)
- **Problem**: After using Claude Code (alt screen app) in the Maya terminal, several hundred blank lines would suddenly appear. The terminal became unusable with massive gaps in the output.
- **Root cause**: When the ANSI parser's scrollback buffer changes size during alt screen transitions (entering clears it to 0, leaving restores the saved scrollback), the `_scrollback_rendered` counter was adjusted but the QPlainTextEdit document was never cleared. Stale blocks from the previous screen's scrollback accumulated as orphaned blank lines that were never updated or removed.
- **Fix**: When `new_scrollback_count < 0` (scrollback shrank), clear the entire document and set `new_scrollback_count = current_sb_len` so Phase 1 rebuilds all scrollback from scratch.

### 2. Fix Alt Screen Dimension Mismatch (`ansi_parser.py`)
- **Problem**: If the terminal was resized while a TUI app (Claude Code, vim) was running in the alt screen, leaving the alt screen restored a grid with the wrong dimensions. This caused `get_visible_lines()` to return fewer lines than `_rows`, and left `_scroll_bottom` pointing to the wrong row, creating additional blank gaps and potential index errors.
- **Root cause**: `_leave_alt_screen()` restored the saved grid, cursor, and scroll region without checking if the terminal dimensions had changed since entering the alt screen.
- **Fix**: After restoring the grid, compare dimensions against current `_rows`/`_cols`. If they differ, resize the restored grid to match (preserving existing content). Always reset scroll region to `(0, _rows - 1)` and clamp cursor to bounds.

### 3. Fix Terminal Copy Not Working (`terminal_native.py`)
- **Problem**: Users could not copy text from the terminal. Selecting text with the mouse appeared to work momentarily, but the selection would vanish before Ctrl+C could be pressed.
- **Root cause**: The 60fps render timer replaces the grid text every dirty frame. The `_mouse_selecting` flag only guarded during the active mouse drag. Once the mouse button was released, the very next render frame (16ms later) called `removeSelectedText()` + `setTextCursor()`, obliterating the selection before the user could press Ctrl+C.
- **Fix**: Added `hasSelection()` check in `_render()` to skip visual updates while text is selected. Added selection clearing on any non-copy key press in `_handle_key_press()` to prevent permanent render freeze (which was why the `hasSelection()` check had been previously removed).

### 4. Fix restart() Leaving Stale Scrollback (`terminal_native.py`)
- **Problem**: After restarting a terminal session, old scrollback content remained visible as blank or stale lines.
- **Root cause**: `restart()` called `self._parser.clear()` (which clears the parser's scrollback) but did NOT clear the QPlainTextEdit document. Old scrollback blocks remained in the document and were never replaced because the parser reported no scrollback to insert.
- **Fix**: Added `self._display.clear()` and `self._scrollback_rendered = 0` to `restart()` alongside the parser clear.

---

## Files Changed
- `mca_qt/widgets/terminal_native.py` — scrollback rebuild, hasSelection guard, selection clearing, restart cleanup
- `mca_qt/widgets/ansi_parser.py` — alt screen grid resize + scroll region reset on leave

## Regression Prevention
- Saved `feedback_terminal_regressions.md` memory with 5 terminal invariants that must be preserved on every change:
  1. Copy works (hasSelection pauses render, non-copy keys clear selection)
  2. Paste works (Ctrl+V → paste_clipboard path)
  3. No blank gaps (document cleared on scrollback shrink)
  4. Alt screen dimension sync (grid resized on leave)
  5. restart() clears everything (parser + document + counter)

## Testing Checklist
- [ ] Open terminal in Maya, run Claude Code, exit → no blank gaps
- [ ] Resize terminal panel while Claude Code is running, exit → no blank gaps
- [ ] Select text in terminal with mouse drag → selection persists after release
- [ ] Ctrl+C with selection → text copied to clipboard
- [ ] Ctrl+C without selection → sends interrupt (^C)
- [ ] Ctrl+V → pastes clipboard content into terminal
- [ ] Type any key after making a selection → selection clears, render resumes
- [ ] Right-click → Copy/Paste context menu works
- [ ] Restart terminal → no stale scrollback visible
