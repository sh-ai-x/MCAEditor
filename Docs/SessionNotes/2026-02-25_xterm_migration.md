# Session: 2026-02-25 — xterm.js Terminal Migration

## Summary
Replaced the custom ANSI parser + QPlainTextEdit terminal with xterm.js
embedded in a QWebEngineView, bridged to Python via QWebChannel. The
backend (`terminal_backend.py`) is completely unchanged.

## What Was Done

### New Files
- `resources/terminal/xterm.js` — bundled from `@xterm/xterm`
- `resources/terminal/xterm.css` — bundled from `@xterm/xterm`
- `resources/terminal/xterm-addon-fit.js` — bundled from `@xterm/addon-fit`
- `resources/terminal/xterm-addon-webgl.js` — bundled from `@xterm/addon-webgl`
- `resources/terminal/index.html` — xterm.js page with QWebChannel bridge
- `mca_qt/widgets/xterm_widget.py` — drop-in TerminalWidget replacement

### Modified Files
- `mca_qt/editor_panel.py` — swapped import to `xterm_widget`
- `.gitignore` — added `node_modules/`, `package.json`, `package-lock.json`

### Key Fixes During Session
- **Data delivery**: QWebChannel signal emission silently dropped ANSI
  control characters. Switched to `runJavaScript("term.write(...)")` with
  `json.dumps()` for safe escaping — this fixed the blank terminal.
- **Dimensions**: Initial xterm.js `ready()` fired at `2x1` when the
  terminal was hidden. Added tracking of latest dims via `_js_cols`/`_js_rows`
  so `start()` uses actual dimensions. After fix: `178x14`.
- **Maya compatibility**: Made QtWebEngine imports conditional with
  `HAS_WEBENGINE` flag. Module imports cleanly in Maya without crashing.

### Not Yet Done
- Old files (`ansi_parser.py`, `terminal_widget.py`) still on disk — delete
  after full verification.
- Terminal does not work inside Maya yet (see idea below).

## Idea: Maya Terminal via Subprocess

The xterm.js terminal requires QtWebEngine (PySide6-only, not in Maya) and
pywinpty (not in Maya's Python). Instead of a degraded fallback, launch the
terminal as a **separate floating window in its own process**.

### Concept
- When running inside Maya, Ctrl+` spawns a subprocess instead of showing
  an embedded widget.
- The subprocess uses the project `.venv` Python (which has PySide6 +
  pywinpty) and runs a small standalone script.
- The script creates a minimal QApplication + QMainWindow wrapping the
  existing `TerminalWidget` — full xterm.js experience, no compromises.
- Maya just manages the subprocess lifecycle (launch on toggle, kill on close).

### What's Needed
1. **`terminal_standalone.py`** — Small entry-point script. Accepts `--cwd`
   arg for the working directory. Creates QApp + window + TerminalWidget,
   starts the shell, runs the event loop.
2. **`TerminalProxy` class** — Lives in `xterm_widget.py`. Same public API
   as `TerminalWidget` (`start()`, `terminate()`, `is_alive()`, etc.) but
   manages a `QProcess` / `subprocess.Popen` pointing at
   `terminal_standalone.py`. Invisible widget — the real UI is the other
   window.
3. **`editor_panel.py` selection logic** — Detect Maya environment and
   instantiate `TerminalProxy` instead of `TerminalWidget`.
4. **Python discovery** — Find the `.venv` Python in the project directory.
   Could also check `sys.executable` or a user-configured path.

### Open Questions
- Should the floating window stay on top of Maya? (Probably configurable.)
- Can we pass the Maya workspace `scripts/` path as `--cwd` reliably?
- Should the proxy forward `font_size_changed` / `process_exited` signals
  back to Maya, or is launch/terminate enough?
