# Session: 2026-02-24 — Integrated Terminal Widget

## Summary
Added an embedded terminal emulator to the MCA Editor, backed by pywinpty's
ConPTY implementation. The terminal lives as a hidden third panel in the center
splitter (below the editor) and can be toggled with Ctrl+`. Includes a full
VT100/ANSI escape sequence parser, styled QPlainTextEdit rendering at ~60fps,
and keyboard input translation.

## Architecture

### Data Flow
```
pywinpty PTY.read() (C++ extension, non-blocking)
    → thread-safe buffer (threading.Lock)
    → drain_buffer() polled by QTimer at 16ms (~60fps)
    → AnsiParser.feed() updates 2D character grid
    → QPlainTextEdit rebuilt from grid with QTextCharFormat styling
```

### Files Created
- **`mca_qt/widgets/terminal_backend.py`** — QThread-based PTY manager using
  pywinpty's `PTY` class. Non-blocking reads with 5ms sleep between polls.
  Thread-safe `drain_buffer()` method for reliable cross-thread data delivery.
- **`mca_qt/widgets/ansi_parser.py`** — VT100/ANSI escape sequence parser with
  2D character grid. Handles SGR colors (16/256/truecolor), cursor movement
  (CSI A/B/C/D/H), screen/line clear, scroll regions, OSC title changes,
  alternate screen buffer, and scrollback.
- **`mca_qt/widgets/terminal_widget.py`** — User-facing terminal widget combining
  backend + parser + QPlainTextEdit display. Handles keyboard → ANSI translation,
  Ctrl+Scroll zoom, clipboard, right-click context menu.

### Files Modified
- **`mca_qt/editor_panel.py`** — Added TerminalWidget as third element in center
  splitter (hidden by default). Added `_toggle_terminal()` (Ctrl+\`), view menu
  entry, state persistence, and cleanup on exit.
- **`mca_core/config/settings.py`** — Added terminal settings: `terminal_shell`,
  `terminal_font_family`, `terminal_font_size`, `terminal_scrollback_lines`,
  `terminal_visible`.
- **`mca_qt/qt_compat.py`** — Added `QThread`, `QFontMetricsF` imports.
- **`requirements.txt`** — Added `pywinpty>=2.0.0`.

## Key Technical Discoveries

### Why ctypes ConPTY ReadFile Fails
The initial implementation used raw `kernel32.ReadFile()` on anonymous pipes
connected to `CreatePseudoConsole()`. On Windows 11 build 26200, this approach
only returns 16 bytes of initial control sequences (`\x1b[?9001h\x1b[?1004h`)
and then blocks permanently — the actual shell output never arrives through
the pipe. pywinpty's C++ extension (`winpty.cp311-win_amd64.pyd`) reads
correctly using its own internal mechanism.

**Lesson**: Don't use raw ctypes ReadFile for ConPTY pipes on modern Windows.
Use pywinpty's proven C++ implementation instead.

### Cross-Thread Signal(bytes) Unreliable
PySide6's `Signal(bytes)` emitted from a QThread does not reliably deliver
to the main thread slot on some builds. The fix is a thread-safe buffer
(`threading.Lock` + list) polled by the render timer, bypassing Qt's signal
system entirely for data transfer.

### ConPTY Startup Delay
ConPTY takes ~3-4 seconds before shell output starts flowing through the
pipes. The initial control sequences arrive immediately, then there's a delay
while the shell starts up and the ConPTY processes the screen buffer. This
is normal behavior — the terminal appears blank for a few seconds on first open.

### Terminal Dimensions Must Be Deferred
If `start()` is called before Qt processes the splitter layout change, the
terminal viewport is tiny (e.g. 113x2 rows). The fix is to set splitter sizes
first, then defer `start()` via `QTimer.singleShot(0, ...)` so Qt processes
the layout change before the PTY spawns.

## Layout
```
center_splitter (QSplitter, Vertical):
    [0] OutputWindow       — top, 30% (unchanged from before)
    [1] EditorGroupContainer — middle, 70% (unchanged)
    [2] TerminalWidget     — bottom, hidden by default
```

The existing output panel and editor panel positions were NOT changed.
The terminal is simply appended as a third hidden element.

## Testing Checklist
1. Ctrl+` toggles terminal visibility
2. Terminal shows PowerShell prompt after ~3-4 second startup delay
3. Keyboard input works (type commands, arrow keys, Ctrl+C, Tab)
4. Ctrl+Scroll zooms terminal font
5. Right-click shows Copy/Paste/Clear/Select All context menu
6. Close and reopen editor — terminal visibility state persists
7. View menu shows "Toggle Terminal (Ctrl+`)" entry

## Known Limitations
- pywinpty is required — terminal is disabled in environments where it can't
  be installed (e.g. Maya's embedded Python). Will need an alternative approach
  for Maya in a future session.
- Terminal starts at the bottom of center_splitter only — the "move to sidebar"
  stretch goal is deferred to a future session.
- 3-4 second startup delay before shell output appears (ConPTY limitation).
