# Session Notes — 2026-04-20: Ctrl+V Defense in Depth + Terminal Resize Fix

## Problem

Two active terminal bugs in Maya:

1. **Ctrl+V routing regression (recurring)** — After a few prompts using
   Claude Code in the editor terminal, Ctrl+V stops pasting into the
   terminal and instead pastes into the code editor panel.  Previous
   fixes (2026-04-08 and 2026-04-14) addressed individual failure modes
   but the bug kept returning.  Nathan asked for a real fix + guardrails
   so it cannot silently regress again.

2. **Terminal horizontal clip on resize** — When the integrated terminal
   is resized horizontally, the start of each line is cut off.  With no
   visible horizontal scrollbar, the user has no way to recover the
   left column.

## Root Causes

### Ctrl+V

The v1.0.17 routing already had multiple heuristics (focusWidget,
`_focus_forced_widget`, panel fallback).  The failure mode is:

- User clicks terminal → `_focus_forced_widget` stores the terminal
  display.
- Claude Code's MCP tool calls (e.g. `editor_open_file`,
  `editor_navigate_to`) programmatically call `setFocus()` on a code
  editor.  This fires `focusChanged` but does not stomp
  `_focus_forced_widget` (which is only stomped by explicit mouse
  clicks).
- Under certain interleavings (tab reparents, menu transients, panel
  rebuilds), `_focus_forced_widget` could end up pointing at a
  non-terminal widget in the editor tree — the override bails and
  `focus.paste()` lands on the code editor.

Root cause in short: a **single stored reference** tracking "where
paste should go" is fragile.  We need multiple independent signals so
drift in any one of them does not break routing.

### Terminal resize clipping

`QPlainTextEdit.setTextCursor()` in the render path calls
`ensureCursorVisible()` internally.  When the cursor column exceeds
the post-resize viewport width, Qt scrolls the viewport horizontally
to keep the cursor on screen — but the scrollbar is policy-hidden
(`ScrollBarAlwaysOff`), so the user sees clipped text on the left
with no affordance to scroll back.

## Fixes Applied

### `mca_maya/maya_window.py` — Defense in depth for Ctrl+V

1. **Dedicated `_last_terminal_widget` tracker** (new instance var on
   `_MayaHotkeyFilter`, initialized in `__init__`).  Independent from
   `_focus_forced_widget`:
   - Phase 0 `MouseButtonPress`: set to click target when the click is
     inside a terminal; **cleared to None** when click is anywhere else
     in the editor tree (so paste follows user intent after the user
     moves on to a code editor).
   - `_on_app_focus_changed`: also updates when focus programmatically
     enters a terminal (MCP tool setFocus path).  This survives even
     when there is never a mouse click.

2. **Ctrl+V override now uses layered preferences** (`eventFilter`
   Phase 2 Ctrl+V branch):
   - Preference 1: `_last_terminal_widget`, validated alive + visible.
   - Preference 2: `_focus_forced_widget` if it belongs to a
     visible + alive terminal.
   - Previously there was only one preference; the second is a
     backstop in case the new tracker ever drifts.

3. **Paste-only backstop in the "standard text editing" branch.**
   When focus ends up on a non-text widget (tab bar, sidebar, status
   strip) and `_last_terminal_widget` points at a visible terminal,
   `paste_clipboard()` is invoked directly on the terminal.  Skipped
   when the focused widget is a writable text editor so normal code
   editing is unaffected.

4. **`_find_parent_terminal` dual-import hardening.**  Added a
   class-name + duck-type fallback (`cls.__name__ == "TerminalWidget"`
   and `hasattr(parent, "paste_clipboard")`) after `isinstance()`.
   If the module is ever loaded twice (historical `.mod` path
   conflict, CLAUDE.md), `isinstance` fails silently; the name check
   survives.

### `mca_qt/widgets/terminal_native.py` — Resize fix

- In `_calculate_dimensions` (fires on `resizeEvent`): after parser +
  backend resize, call `self._display.horizontalScrollBar().setValue(0)`
  to force the viewport back to column 0.
- In `_render()` Phase 2: after `setTextCursor()` (which triggers
  `ensureCursorVisible`), also reset horizontal scroll to 0 so long
  prompts rendered at narrow widths can't push the left edge off
  screen.

### `mca_core/__init__.py` — Version bump

- `__version__ = "1.0.18"` (was 1.0.17).

## Guardrail — Regression Test

`tools/test_ctrl_v_routing.py` — new pure-Qt test (no Maya, no real
shell) exercising the 5 known failure modes:

1. baseline click + Ctrl+V
2. focus drifts to editor after terminal click (Claude-Code regression)
3. click editor after terminal → paste follows user intent
4. hidden terminal is not used as a paste target
5. backstop routes from non-text focus to tracked terminal

All 5 tests pass with v1.0.18.  Run with:

```
python tools/test_ctrl_v_routing.py
```

Any future change that breaks paste routing fails this suite — making
silent regressions harder.

## Build / Deploy

- Built v1.0.18 for Maya 2024, 2025, 2026.
- **First 2024 build failed** with `PermissionError` on
  `base_adapter.py` because two `build_maya.py` invocations ran in
  parallel (they share `build_ext --inplace`).  Serial is required.
- **Second issue blocked all builds:** `mca_core/adapters/base_adapter.py`
  was silently deleted from the working tree by Surfshark Antivirus.
  Every tool (bash, cmd, PowerShell, Python, git checkout, Write) got
  "Access is denied" when trying to recreate the file at that exact
  path; writes to the same dir with any other filename succeeded.
  Surfshark's real-time protection was matching signature patterns
  (connect/disconnect/ping/execute abstract class = C2 client shape)
  and blocking re-creation.
  - **End users unaffected**: they receive compiled
    `base_adapter.cp31X-win_amd64.pyd`; Cython 3.x encodes string
    literals inside the binary, so the source-level pattern Defender/
    Surfshark matches never appears in shipped builds.
  - **Fix for dev machine**: add `E:\Projects\MCAEditor` as an
    exclusion in the installed security product (Surfshark, Defender,
    etc.).  Then `git checkout HEAD -- mca_core/adapters/base_adapter.py`
    restores the file.

- After restoring the file, all three Maya builds completed clean with
  `base_adapter.cp31X-win_amd64.pyd` bundled.  Deployed to:
  - `C:\Users\ncomes\Documents\maya\2024\plug-ins\mcaEditor.py`
  - `C:\Users\ncomes\Documents\maya\2025\plug-ins\mcaEditor.py`
  - `C:\Users\ncomes\Documents\maya\2026\plug-ins\mcaEditor.py`
- Zips for distribution: `dist/MCAEditor-Maya202X-v1.0.18.zip`.

## Follow-up Ideas (Not Done This Session)

- **Rename `base_adapter.py`** to `dcc_adapter.py` so a future
  signature update on the exact filename can't re-bite.  Pure rename
  + update ~5 import sites.
- **Code-sign `mcaEditor.py`** so SmartScreen does not nag users on
  first run.  Requires an EV certificate to bypass "Unknown publisher"
  warnings reliably.

## Files Changed

- `mca_maya/maya_window.py`
- `mca_qt/widgets/terminal_native.py`
- `mca_core/__init__.py`
- `tools/test_ctrl_v_routing.py` (new)
- `Docs/SessionNotes/2026-04-20_ctrlv_defense_in_depth_and_terminal_resize.md` (this file)
