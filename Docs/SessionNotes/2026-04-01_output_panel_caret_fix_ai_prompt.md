# Session Notes — 2026-04-01

## Output Panel: Caret Line Filtering (Recurring Bug)

### Problem
Python 3.11+ traceback caret indicator lines (`^`, `~`) were appearing in the
output panel as dozens of near-blank lines, creating huge visual gaps. This bug
has recurred multiple times because filters were scattered across upstream
callers but not at the output panel's own entry point.

### Root Cause
`_load_session_history()` in `maya_window.py` had **zero caret filtering**.
When the editor opened, it read Maya's session history buffer (which contains
raw `^` lines) and dumped them directly into the output panel. The live
callback `_on_maya_output()` and `_StderrTee` both had caret filters, but
the history loader was missing one entirely.

### Fix — Three Layers of Defense
1. **`output_window.py:_append_formatted()`** — Added a defensive filter at
   the **single entry point** for all output text. Strips optional Maya `#`
   echo prefix, then rejects lines that are only `^` / `~` characters. This
   is the catch-all that guarantees no caret lines reach the document,
   regardless of which upstream path sends them.
2. **`maya_window.py:_load_session_history()`** — Added the same caret filter
   to the session history loader (the primary source of this bug).
3. Existing filters in `_on_maya_output()` and `_StderrTee` remain as
   early-exit optimizations.

### Lesson
When a shared sink (output panel) needs content filtering, put the filter at
the sink's single entry point — not scattered across every caller. This
guarantees coverage even when new callers are added later.

---

## Orange Slice AI Chat: Environment Awareness

### Problem
The AI assistant was asking users to clarify their environment ("Is it in Maya,
a terminal, or an IDE?") and asking them to paste errors — even though Orange
Slice is running directly inside the DCC and has a `get_output` tool to read
the output panel.

### Fix
Updated `system_prompt.py` with two critical rules at the top of the prompt:

1. **"You already know the user's environment."** — Explicit NEVER list:
   never ask "Is it in Maya?", "Where are you seeing this?", "Can you paste
   the error?". The AI is embedded inside the DCC.
2. **"When the user mentions ANY issue, your FIRST action must be to call
   `get_output`."** — Broadened trigger from just "errors" to include
   warnings, tracebacks, unexpected behavior, and anything going wrong.

Updated both the Maya helpdesk block and the Unreal Engine block with
matching environment-awareness language.

### Note
Changes to `system_prompt.py` (compiled to `.pyd`) require a **full Maya
restart** — not just plugin reload. Python caches imported `.pyd` modules in
`sys.modules` and re-importing doesn't reload them.

---

## Build Fix: mcp_blender_server.py Cython Exclusion

### Problem
`mcp_blender_server.py` uses top-level `mcp` package references that Cython
cannot resolve, causing build failure for all Maya versions.

### Fix
- Added to `exclude_from_compilation` in `setup.py` (ships as `.pyc`)
- Added to `DIST_PURE_PYTHON` in `build_maya.py` (ships as `.py` — runs as
  separate process outside Maya, same as `mcp_maya_server.py`)

---

## Terminal Paste Issue (Reported, Under Investigation)

Nathan reported that Ctrl+V paste no longer works in the native terminal.
Code analysis shows the paste path (`_handle_key_press` → `paste_clipboard`)
is correct and no terminal files were modified. Most likely cause is stale
cached modules from a previous build — needs Maya restart to verify. If still
broken after restart, add debug logging to the paste path.

---

---

## AI Chat: Blank Space in Plan Rendering

### Problem
When the AI generated a plan-style response, a huge blank gap appeared in the
middle of the chat bubble, requiring scrolling past empty space to see the
second half of the plan.

### Root Cause
`_markdown_to_html()` in `chat_widget.py` converted every empty line in the
AI's output to a `<br>` tag with no limit. Plan-style responses often use
multiple consecutive blank lines between sections. Each became a separate
`<br>`, stacking up into a massive vertical gap.

Also found dead code: lines 192-195 computed a filtered `<br>` join that was
immediately overwritten by line 198's `\n` join.

### Fix
Collapse consecutive blank lines to a single `<br>`. If `html_lines[-1]` is
already a `<br>`, skip the duplicate. Removed the dead code join.

---

## Terminal Paste: Multi-Mode CSI Parsing Bug (Ctrl+V with Claude Code)

### Problem
Ctrl+V paste worked in the normal shell but NOT when Claude Code (a TUI app)
was running inside the terminal.

### Root Cause
**Bug 1 — Multi-mode CSI sequences only processed the first mode.** The ANSI
parser's `h`/`l` handler extracted `int(mode_str.split(";")[0])`, so a sequence
like `ESC[?1049;2004h` (alt screen + bracketed paste) only processed mode 1049.
Mode 2004 (bracketed paste) was silently dropped, meaning `_bracketed_paste`
never became `True`.

**Bug 2 — Alt screen didn't save/restore bracketed paste state.**
`_enter_alt_screen()` saved grid, cursor, scrollback, and scroll region, but
NOT `_bracketed_paste`. When a TUI exited alt screen, the bracketed paste mode
from the alt session incorrectly persisted into the main screen.

### Fix
1. **`ansi_parser.py:_handle_csi()` h/l handler** — Changed from processing
   only the first mode to iterating over ALL `;`-separated modes. This ensures
   combined sequences like `ESC[?1049;2004h` enable both alt screen and
   bracketed paste.
2. **`ansi_parser.py:_enter_alt_screen()/_leave_alt_screen()`** — Save
   `_bracketed_paste` when entering alt screen, restore when leaving. Mode
   state is now properly isolated between main and alt screen buffers.
3. **Diagnostic logging** added to `paste_clipboard()`, `write()`, and mode
   2004 toggle to trace the full paste flow through Maya's Script Editor.

### Lesson
When fixing bugs, trace the ENTIRE code flow end-to-end and identify ALL issues
in one pass. The multi-mode parsing bug and the alt screen save/restore bug were
independent but both contributed to paste failures. Fixing one without the other
would have left paste broken in certain sequences.

---

## Files Changed
- `mca_qt/widgets/output_window.py` — Defensive caret filter in `_append_formatted()`
- `mca_maya/maya_window.py` — Caret filter in `_load_session_history()`
- `mca_core/plugins/ai_chat/system_prompt.py` — Environment-aware critical rules
- `mca_core/plugins/ai_chat/chat_widget.py` — Collapse consecutive `<br>` in markdown renderer, friendly tool labels
- `mca_qt/widgets/ansi_parser.py` — Multi-mode CSI parsing, alt screen bracketed paste save/restore
- `mca_qt/widgets/terminal_native.py` — Bracketed paste wrapping in `paste_clipboard()`, diagnostic logging
- `mca_qt/widgets/terminal_backend.py` — Diagnostic logging for paste-sized writes
- `setup.py` — Exclude `mcp_blender_server.py` from Cython compilation
- `build_maya.py` — Add `mcp_blender_server.py` to `DIST_PURE_PYTHON`

## Logging Caused Lag (v1.0.7 → v1.0.8 hotfix)

### Problem
After deploying v1.0.7 with the terminal paste fixes, the terminal lagged badly
and Ctrl+V stopped working after a while.

### Root Cause
INFO-level logging in `terminal_backend.py:write()` fired on every multi-byte
PTY write (arrow keys, escape sequences). When Claude Code was running, this
flooded Maya's Script Editor at high volume, causing Qt's event loop to back up.
Key events (including Ctrl+V) got dropped under the load.

### Fix
Downgraded `write()` and mode 2004 toggle logging to DEBUG. Only
`paste_clipboard()` remains at INFO (user-triggered, rare). Bumped version to
v1.0.8.

---

## Remaining: macOS v1.0.8 Website Deploy

The Mac Mini builds for v1.0.8 are compiled and deployed locally on the Mac,
but the zip files couldn't be transferred to `dist/latest/` for website upload
because the Mac Mini went unreachable (WiFi adapter crashed on this PC, and the
Mac may have gone to sleep). **Next session**: pull the three macOS v1.0.8 zips
from the Mac Mini and re-run `python tools/deploy_website.py`.

Files needed from Mac Mini `~/Projects/MCAEditor/dist/`:
- `MCAEditor-Maya2024-v1.0.8.zip` → `dist/latest/MCAEditor-Maya2024-macOS-v1.0.8.zip`
- `MCAEditor-Maya2025-v1.0.8.zip` → `dist/latest/MCAEditor-Maya2025-macOS-v1.0.8.zip`
- `MCAEditor-Maya2026-v1.0.8.zip` → `dist/latest/MCAEditor-Maya2026-macOS-v1.0.8.zip`

---

## Files Changed
- `mca_qt/widgets/output_window.py` — Defensive caret filter in `_append_formatted()`
- `mca_maya/maya_window.py` — Caret filter in `_load_session_history()`
- `mca_core/plugins/ai_chat/system_prompt.py` — Environment-aware critical rules
- `mca_core/plugins/ai_chat/chat_widget.py` — Collapse consecutive `<br>` in markdown renderer, friendly tool labels
- `mca_qt/widgets/ansi_parser.py` — Multi-mode CSI parsing, alt screen bracketed paste save/restore
- `mca_qt/widgets/terminal_native.py` — Bracketed paste wrapping in `paste_clipboard()`, diagnostic logging
- `mca_qt/widgets/terminal_backend.py` — Downgraded diagnostic logging to DEBUG
- `mca_core/__init__.py` — Version bump to 1.0.8
- `CHANGELOG.md` — v1.0.8 entry
- `setup.py` — Exclude `mcp_blender_server.py` from Cython compilation
- `build_maya.py` — Add `mcp_blender_server.py` to `DIST_PURE_PYTHON`

## Builds Deployed (v1.0.8)
- Windows: Maya 2024, 2025, 2026 — deployed locally
- Mac: Maya 2024, 2025, 2026 — deployed on Mac Mini
- UE: 5.5, 5.6, 5.7 — built, UE 5.6 deployed to Wayward project
- Website: Windows Maya + all UE uploaded. macOS Maya pending (see above)
