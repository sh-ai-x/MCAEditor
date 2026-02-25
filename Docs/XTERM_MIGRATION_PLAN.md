# Plan: Replace Custom Terminal with xterm.js + QWebEngineView

## Context

The integrated terminal uses a custom ANSI parser (`ansi_parser.py`, 850 lines) + QPlainTextEdit renderer (`terminal_widget.py`, 697 lines). The parser implements only a subset of VT100 sequences and has persistent cursor positioning bugs — it's missing cursor save/restore (`ESC 7`/`ESC 8`), `ESC[E`/`ESC[F` (cursor next/prev line), and other sequences that ConPTY relies on. This causes the cursor to drift to wrong positions, and arrow keys appear to move the cursor freely through output text.

**Solution**: Replace the custom parser + QPlainTextEdit with **xterm.js** (the terminal emulator VS Code uses) embedded in a **QWebEngineView**, bridged to Python via **QWebChannel**. All dependencies are already installed (PySide6-Addons includes QtWebEngine, pywinpty is already the PTY backend). The backend (`terminal_backend.py`) stays unchanged.

## Architecture

```
QWebEngineView (xterm.js renders everything)
    ↕ QWebChannel (bidirectional bridge)
TerminalAPI (Python QObject with slots/signals)
    ↕ drain_buffer() polling
TerminalBackend (existing pywinpty PTY thread — unchanged)
```

## Changes

### 1. Bundle xterm.js assets — `resources/terminal/`

New directory with static files downloaded via npm:

| File | Source |
|------|--------|
| `xterm.js` | `@xterm/xterm` UMD bundle |
| `xterm.css` | `@xterm/xterm` stylesheet |
| `xterm-addon-fit.js` | `@xterm/addon-fit` UMD bundle |
| `xterm-addon-webgl.js` | `@xterm/addon-webgl` UMD bundle |

Obtain via: `npm install @xterm/xterm @xterm/addon-fit @xterm/addon-webgl`, then copy dist files. Add `node_modules/` to `.gitignore`.

### 2. New file: `resources/terminal/index.html`

HTML page that:
- Loads xterm.js + addons from local files
- Loads `qrc:///qtwebchannel/qwebchannel.js` (Qt-bundled)
- Creates xterm.js Terminal with dark theme matching editor (`#1e1e1e` bg, `#cccccc` fg)
- Loads FitAddon (auto-resize) and WebGL addon (GPU rendering, with canvas fallback)
- Connects to Python `termAPI` object via QWebChannel
- Wires: `api.dataReceived` signal → `term.write()` (PTY output to screen)
- Wires: `term.onData()` → `api.write()` (user input to PTY)
- Wires: `term.onResize()` → `api.resize()` (dimensions to PTY)
- Calls `api.ready(cols, rows)` once fully initialized (eliminates race condition)
- Exposes global JS functions: `setFontSize()`, `setFontFamily()`, `clearTerminal()`, `focusTerminal()`, `pasteText()` — callable from Python via `runJavaScript()`

### 3. New file: `mca_qt/widgets/xterm_widget.py`

**TerminalAPI(QObject)** — QWebChannel bridge:
- `dataReceived = Signal(str)` — Python → JS (PTY output)
- `write(str)` slot — JS → Python (user keyboard input)
- `resize(cols, rows)` slot — JS → Python (terminal resize)
- `ready(cols, rows)` slot — JS → Python (initialization complete)

**TerminalWidget(QWidget)** — Drop-in replacement, same public API:
- Constructor: `TerminalWidget(shell="", cwd="", font_size=12, parent=None)`
- `_setup_ui()`: Creates QWebEngineView, QWebChannel, loads index.html
- `start()`: If JS ready → spawn backend; if not → defer via `_pending_start` flag
- `_do_start(cols, rows)`: Creates TerminalBackend, starts drain_buffer timer (16ms)
- `terminate()`, `is_alive()`, `restart()` — same API as old widget
- `_drain_backend()`: Polls `drain_buffer()`, emits `dataReceived` signal to JS (proven reliable path, avoids double-delivery by NOT connecting backend's `data_received` signal)
- `_on_js_write(text)`: Forwards user input to `backend.write()`
- `_on_js_resize(cols, rows)`: Forwards to `backend.resize()`
- `set_font_size(size)`, `get_font_size()`, `clear()`, `setFocus()` — same API
- Signals: `title_changed(str)`, `process_exited(int)`, `font_size_changed(int)`

**Key decisions**:
- Imports directly from `PySide6.*` (not qt_compat) — QWebEngine is PySide6-only, terminal already doesn't work in Maya's PySide2
- Uses ONLY `drain_buffer()` polling (not signal), same proven approach as current widget
- HTML loaded in `__init__()` so Chromium warms up before user toggles terminal visible

### 4. `terminal_backend.py` — NO changes

Backend already provides everything needed: `drain_buffer()`, `write()`, `resize()`, `process_exited` signal, pywinpty + subprocess fallback.

### 5. `editor_panel.py` — One import change

```python
# Line 43: change from
from mca_qt.widgets.terminal_widget import TerminalWidget
# to
from mca_qt.widgets.xterm_widget import TerminalWidget
```

Everything else unchanged — same constructor, same methods, same signals.

### 6. Files to delete (after verification)

- `mca_qt/widgets/ansi_parser.py` — replaced by xterm.js
- `mca_qt/widgets/terminal_widget.py` — replaced by xterm_widget.py

## Files Summary

| File | Action |
|------|--------|
| `resources/terminal/index.html` | **New** — xterm.js HTML page |
| `resources/terminal/xterm.js` | **New** — bundled from npm |
| `resources/terminal/xterm.css` | **New** — bundled from npm |
| `resources/terminal/xterm-addon-fit.js` | **New** — bundled from npm |
| `resources/terminal/xterm-addon-webgl.js` | **New** — bundled from npm |
| `mca_qt/widgets/xterm_widget.py` | **New** — xterm.js terminal widget |
| `mca_qt/editor_panel.py` | **Edit** — swap import (1 line) |
| `mca_qt/widgets/terminal_widget.py` | **Delete** (after verification) |
| `mca_qt/widgets/ansi_parser.py` | **Delete** (after verification) |
| `mca_qt/widgets/terminal_backend.py` | **No change** |

## Verification

1. `python run.py` → editor opens normally
2. Ctrl+` → terminal panel appears with shell prompt, colors, cursor
3. Type commands (dir, pip, git) → output renders correctly with colors
4. Arrow keys → navigate command history (cursor stays on prompt line)
5. Ctrl+C → sends interrupt
6. Drag splitter → terminal resizes correctly (FitAddon)
7. Ctrl+Scroll → font zoom works
8. Close editor → terminal process terminates cleanly
9. Reopen → terminal_visible state restored from settings
