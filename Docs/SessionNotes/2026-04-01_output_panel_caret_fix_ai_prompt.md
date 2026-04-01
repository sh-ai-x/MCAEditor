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

## Files Changed
- `mca_qt/widgets/output_window.py` — Defensive caret filter in `_append_formatted()`
- `mca_maya/maya_window.py` — Caret filter in `_load_session_history()`
- `mca_core/plugins/ai_chat/system_prompt.py` — Environment-aware critical rules
- `setup.py` — Exclude `mcp_blender_server.py` from Cython compilation
- `build_maya.py` — Add `mcp_blender_server.py` to `DIST_PURE_PYTHON`

## Build Deployed
- Maya 2025 v1.0.7 (build hash `fb3921541bae`)
