# Session Notes — 2026-03-03: Comprehensive Maya Editor Test Suite

## Summary
Built a comprehensive automated test suite that exercises every EditorAPI
feature inside Maya.  78 tests across 13 categories, all run through
`get_api()` directly — no TCP/JSON-RPC overhead.  Integrated into the
existing `run_maya_test.py` runner via a new `--full` flag.

---

## New File: `tools/maya_editor_test.py`

Self-contained test suite (no pytest dependency) that runs inside Maya via
`executeDeferred`.  Each test is wrapped in try/except so one failure never
aborts the suite.

### Test Categories (78 tests)

| # | Category | Tests | Coverage |
|---|----------|-------|----------|
| 1 | Plugin & Window | 3 | Plugin loads, window exists, get_api() returns instance |
| 2 | DCC Connection | 3 | dcc.connected, dcc.type contains "maya", server port |
| 3 | File Operations | 10 | Open, active path, list, get_text, save, tab count, close, error, language detection |
| 4 | Editor Content | 10 | set/get roundtrip, empty, unicode, insert at position/cursor, replace, delete, cursor pos, out-of-range |
| 5 | Navigation | 4 | navigate_to, go_to_line, first line, nonexistent error |
| 6 | Output Panel | 6 | clear, write info/warning/error, get_output_text, clear removes content |
| 7 | DCC Execution | 8 | Import, expression, create/verify/delete cube, MEL sphere, error handling |
| 8 | Local Execution | 5 | Print/capture, namespace persistence, ZeroDivisionError, multi-line |
| 9 | Disk File I/O | 6 | Write, read roundtrip, nonexistent error, overwrite, unicode, nested dirs |
| 10 | Settings | 6 | Get/set/restore font_size, default key, theme read, version in state |
| 11 | Project Management | 7 | Open (with .mca-project file), get root/name, state, nonexistent, close, None after close |
| 12 | Multi-Tab & Save All | 5 | Open 3 files, tab count, modify, save_all, close tabs |
| 13 | Maya Isolation | 5 | No leaked objects, undo works, command ports, API healthy, cameras intact |

### Architecture
- Tests run sequentially via `QTimer.singleShot(500ms)` chains between
  categories so Qt processes events between batches (catches deferred crashes)
- Temp files created in `%TEMP%/mca_editor_tests/`, cleaned up at end
- Maya objects tracked in `_maya_objects` list, deleted during cleanup
- Log written to `%TEMP%/mca_test_result.log` with `[PASS]`/`[FAIL]` per test

---

## Edit: `tools/run_maya_test.py`

- Added `--full` flag to select comprehensive test script
- Default timeout 300s for `--full` (vs 120s for smoke)
- Fixed PASS detection to match standalone `PASS`/`FAIL` verdict lines
  (not `[PASS] test_name` per-test lines)
- Added `_print_full_summary()` — parses `[PASS]`/`[FAIL]` lines, prints
  grouped summary with failure details
- Exit code 0 only when zero failures

---

## Bugs Found & Fixed During Development

1. **Output panel buffering**: `_append_formatted()` queues messages on a
   16ms flush timer.  Tests need `processEvents()` + brief sleep to let
   the timer fire before reading `get_output_text()`.

2. **DCC execution returns empty output**: Internal Maya adapter's `execute()`
   returns empty string — `print()` output flows through MCommandMessage
   callback, not the return value.  Fixed tests to verify side effects via
   `maya.cmds` directly instead of checking output strings.

3. **Project dialog blocks tests**: `_open_project()` shows `CreateProjectDialog`
   when no `.mca-project` file exists, which blocks in automated tests.
   Fixed by creating a `.mca-project` JSON file in the temp directory before
   calling `open_project()`.

---

## Usage

```bash
# Comprehensive test suite (78 tests):
python tools/run_maya_test.py --full --timeout 300

# Build + comprehensive tests:
python tools/run_maya_test.py --full --build --timeout 300

# Smoke test only (default):
python tools/run_maya_test.py
```

## Files Changed

| Action | File | What |
|--------|------|------|
| NEW | `tools/maya_editor_test.py` | 78 tests across 13 categories |
| EDIT | `tools/run_maya_test.py` | `--full` flag, summary table, verdict detection fix |
