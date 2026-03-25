# Session Notes — 2026-03-24: Output Panel Traceback Cleanup

## Problem

Python 3.11+ tracebacks include caret indicator lines (`^^^^...`) that point to the
error location.  In Maya 2025 (Python 3.11), these caused two issues in MCA Editor's
output panel:

1. **Blank-looking lines**: Maya's `MCommandMessage` callback fires once per character
   for caret lines, producing dozens of single-`^` messages that appear as blank rows.
2. **Wrong color**: Traceback text routed through `_StderrTee` was shown in white
   (normal output) instead of red (error), because the tee only checked for `"ERROR:"`
   and `"Warning:"` string patterns.
3. **Duplicate lines**: Each traceback line appeared twice — once from `MCommandMessage`
   (white) and once from `_StderrTee` (also white before fix).
4. **Warnings not colored**: Framework warnings printed via `print()` (e.g. `WARNING:
   Icon is not registered`) came through `_on_maya_output` as kDisplay and were shown
   white instead of orange.

## Root Cause

Three separate output capture paths exist in the Maya plugin:

- **`_on_maya_output`** (MCommandMessage callback): Captures Maya's command system
  output.  Routes by `message_type` (kError, kWarning, kResult, kInfo, kDisplay).
  The kDisplay branch had no content-based detection — everything went to
  `write_output()` (white).

- **`_StderrTee`**: Captures Python `sys.stderr` writes (logging, tracebacks).
  Only detected `"ERROR:"` / `"Warning:"` patterns.  Tracebacks don't match.
  Also, Python's traceback formatter writes the exception line in multiple
  `write()` calls (`AttributeError`, `:`, `' message'`), causing stray `:` lines.

- **Standalone editor (`_apply_error_filters`)**: Receives tracebacks as blocks
  from the TCP adapter — needed caret line stripping but no line-buffering.

## Changes

### `mca_maya/maya_window.py`

**`_StderrTee` — complete rewrite:**
- Added **line-buffering**: accumulates `write()` calls until `\n`, so split
  exception lines recombine into a single output line (no more stray `:` noise)
- Added **`_in_traceback` state tracking**: when "Traceback (most recent call last)"
  is seen, all subsequent lines are routed to `write_error()` (red) until the
  final exception line is detected
- Caret line filtering (`^` / `~` only lines) moved into `_write_line()`
- `flush()` now drains remaining buffer content

**`_on_maya_output`:**
- Added caret indicator filter (lines consisting only of `^` / `~` characters)
- Added bare `#` filter (echo of already-filtered caret lines)
- Added **traceback echo suppression**: when "Traceback" is seen in a kDisplay
  message, sets `_in_traceback_echo = True` and suppresses kDisplay messages until
  the exception line.  `_StderrTee` provides the properly formatted/colored version.
- Added **content-based routing in kDisplay branch**: detects `WARNING:` / `Warning:`
  and routes to `write_warning()`; detects `ERROR:` / `Error:` and routes to
  `write_error()`.  Catches framework warnings/errors that Maya sends as kDisplay.

### `mca_editor/ui/main_window.py` (standalone/Unreal)

- **`_apply_error_filters`**: Added caret line stripping before stack trace filtering
- **`_write_filtered_traceback`**: Added caret line stripping for locally-generated
  tracebacks (Python 3.11+ running in the standalone editor)

## Files Modified

| File | Change |
|------|--------|
| `mca_maya/maya_window.py` | `_StderrTee` rewrite, `_on_maya_output` filters |
| `mca_editor/ui/main_window.py` | Caret stripping in `_apply_error_filters` and `_write_filtered_traceback` |
| `mca_core/__init__.py` | Version bump 1.0.4 → 1.0.5 |

## Version

v1.0.5
