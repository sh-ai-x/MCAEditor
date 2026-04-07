# Session Notes — 2026-04-06: Terminal Crash Fix, ConPTY Fallback, MCP Fix

## Version: 1.0.10

---

## Changes Made

### 1. Fix Maya Crash — QPlainTextEdit Paint Engine Corruption (`terminal_native.py`)
- **Problem**: Maya crashes with ACCESS_VIOLATION at 0x00000040 in `QRasterPaintEngine::ensurePen` during `QPlainTextEdit::paintEvent`. Confirmed on both Maya 2024 (Qt5/PySide2) and Maya 2025 (Qt6/PySide6).
- **Root cause**: The terminal's 60fps render timer modifies the QPlainTextEdit document via cursor operations (removeSelectedText, insertText with QTextCharFormat) wrapped only in `setUpdatesEnabled(False/True)`. This suppresses new `update()` calls but does NOT prevent:
  - Already-queued paint events from executing mid-modification
  - Document `contentsChanged` signals from triggering layout recomputation
  - The paint engine from accessing partially-modified layout data
- **Fix** (three-layer protection):
  1. **`cursor.beginEditBlock()` / `endEditBlock()`** — Wraps all document modifications into atomic edit blocks.
  2. **`doc.blockSignals(True/False)`** — Blocks all document signals during modification.
  3. **`self._rendering` re-entrancy guard** — Prevents `_render()` from being called recursively.

### 2. Fix Render Timer Lifecycle — Stop When Process Exits (`terminal_native.py`)
- **Problem**: The 60fps render timer continued running after the terminal process exited, causing repaint cascades across the entire Qt widget tree.
- **Fix**: Timer is created but NOT started in `__init__`. Started only in `start()`. Stopped in `_on_process_exited()` and `terminate()`.

### 3. Direct ConPTY Backend via ctypes (`terminal_backend.py`)
- **Problem**: On Windows 11 build 26200, `conpty.dll` behavior is broken — `kernel32.CreatePseudoConsole()` (used by pywinpty) creates a pseudo-console but never forwards shell output. Only init escape sequences arrive.
- **Fix**: Added `_run_direct_conpty()` method that loads `conpty.dll` directly via ctypes and calls its `CreatePseudoConsole` instead of kernel32's. This works because pywinpty ships its own `conpty.dll` (user copied it to System32).
- **Fallback chain**: pywinpty → sanity check (3s) → `_ConPTYBrokenError` → direct ConPTY via ctypes → subprocess (last resort).

### 4. Non-blocking Read Loop for Direct ConPTY (`terminal_backend.py`)
- **Problem**: `ReadFile` on the ConPTY pipe blocks indefinitely. When `terminate()` is called, the thread can't exit → QThread destroyed while running → ACCESS_VIOLATION crash on editor close.
- **Fix**: Replaced blocking `ReadFile` with `PeekNamedPipe` + `ReadFile`. The loop polls every 5ms, checks `_running` each iteration, and exits within one cycle when `terminate()` sets `_running = False`. No cross-thread handle operations needed.

### 5. Fix Maya Lockup on Editor Close (`terminal_backend.py`)
- **Problem**: `terminate()` called `self.wait(3000)` which blocked Maya's main thread for up to 3 seconds per terminal while the blocking ReadFile held the thread alive.
- **Fix**: With non-blocking PeekNamedPipe, the thread exits within ~5ms. Reduced wait timeout to 1 second as safety net. Removed cross-thread `ClosePseudoConsole` call that was causing crashes.

### 6. Fix QThread GC Crash on Editor Close (`terminal_native.py`)
- **Problem**: `self._backend = None` in `terminate()` dropped the last reference to the QThread. If `wait()` timed out and the thread was still running, Python GC'd the QThread → ACCESS_VIOLATION.
- **Fix**: Keep the `_backend` reference alive. The QThread is a child of the widget; Qt handles cleanup through the parent-child hierarchy.

### 7. Fix Double Cursor in TUI Apps (`ansi_parser.py`, `terminal_native.py`)
- **Problem**: Both our block cursor (inverted colors) and TUI app cursors (Claude Code, vim) were visible simultaneously — double cursor artifact.
- **Root cause**: ANSI parser didn't track `ESC[?25l` / `ESC[?25h` (DECTCEM cursor visibility). TUI apps send `?25l` to hide the hardware cursor and render their own.
- **Fix**: Added `_cursor_visible` flag to ANSI parser, handle mode 25 in DEC private mode section, expose via `is_cursor_visible()`. Save/restore across alt screen transitions. Renderer skips block cursor when `is_cursor_visible()` returns False.

### 8. Fix Horizontal Scrollbar / Text Cut-off (`terminal_native.py`)
- **Problem**: Terminal showed a horizontal scrollbar and text was cut off on the sides.
- **Fix**:
  - Added `setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)`
  - Changed column calculation from `averageCharWidth()` to `horizontalAdvance("M")` for exact monospace cell width
  - Subtract document margin (4px per side) from usable width so columns don't overflow

### 9. Fix MCP Server Broken Venv
- **Problem**: MCP server venv had `pydantic_core` compiled for Python 3.11 but the venv uses Python 3.10. `mca_unreal_server.py` and `mca_maya_server.py` couldn't start → Claude Code not connected to Maya/UE.
- **Fix**: Nuked the venv and recreated from scratch with `C:/Python310/python.exe`. Reinstalled `mcp` package with all correct native modules.

### 10. Fix UE MCP Server — Zero Tools Discovered
- **Problem**: `unreal_tools/` directory had `.pyd` compiled files instead of `.py` source. The MCP server reads tool files as source text to send to UE, so it needs `.py` files. `find_tools()` filters for `.py` extension → found 0 tools.
- **Root cause**: `setup.py` Cython compilation walked into `mca_core/unreal_tools/` and compiled all tool scripts to `.pyd`. The build cleanup then removed the `.py` originals.
- **Fix**: Added `"unreal_tools"` to the `dirs[:] = [d for d in dirs if d not in ...]` skip list in `setup.py`. Redeployed raw `.py` files to MCP servers directory.

### 11. Fix Extraction Cache Locked Files (`pack_single_file.py`)
- **Problem**: When updating the plugin while Maya is running, `shutil.rmtree()` fails because `.pyd` files are loaded by the running process.
- **Fix**: On `PermissionError`/`OSError`, rename the old cache directory to `.old.<timestamp>` suffix. Old directories cleaned up on next launch.

### 12. Other Fixes
- **Unix PTY on Windows in UE**: Added `is_windows = platform.system() == "Windows"` guard — Unix PTY path only taken on non-Windows.
- **WinptyError killing terminal**: Catch read exceptions, check `iseof()` before breaking loop.
- **Resize error spam**: Downgraded "The handle is invalid" to `logger.debug()`.
- **ConPTY sanity check**: 3-second check for printable output after PTY spawn, raises `_ConPTYBrokenError` if only escape sequences arrive.

---

## Build & Deploy Status

| Platform | Version | Status |
|----------|---------|--------|
| Maya 2024 Windows | v1.0.10 | Built + deployed + website |
| Maya 2025 Windows | v1.0.10 | Built + deployed + close test PASS + website |
| Maya 2026 Windows | v1.0.10 | Built + deployed + website |
| UE 5.5 Windows | v1.0.10 | Built + website |
| UE 5.6 Windows | v1.0.10 | Built + deployed to Wayward + tested + website |
| UE 5.7 Windows | v1.0.10 | Built + website |

---

## Files Modified
- `mca_qt/widgets/terminal_native.py` — render timer lifecycle, double cursor fix, horizontal scrollbar fix, column calculation, QThread GC fix
- `mca_qt/widgets/terminal_backend.py` — direct ConPTY ctypes backend, non-blocking PeekNamedPipe read loop, terminate cleanup, Windows PTY guard
- `mca_qt/widgets/ansi_parser.py` — DECTCEM cursor visibility (mode 25), save/restore across alt screen
- `mca_core/__init__.py` — version bump 1.0.9 → 1.0.10
- `pack_single_file.py` — locked file handling via rename + cleanup
- `setup.py` — exclude `unreal_tools/` from Cython compilation
- `tools/maya_plugin_test.py` — plugin name fix
- `CHANGELOG.md` — v1.0.10 entry
