# MCA Editor Changelog

## v1.0.15 — 2026-04-14
- Fix Maya 2024 Windows tab drag regression — PySide2 now falls back to Qt's native tab reorder while PySide6 keeps the custom QDrag flow
- `drag.exec_()` called directly on PySide2 to avoid relying on the qt_compat lambda patch firing first; wrapped in try/except so a binding failure can't kill the mouse handler
- `lock_tabs` now drives `setMovable(not locked)` on PySide2 in addition to the custom bar flag

## v1.0.14 — 2026-04-14
- Find in Files now routes through the SymbolIndex for identifier and substring searches — roughly an order of magnitude faster than the old filesystem walk
- Added `get_files_with_word` and `get_files_containing_substring` to SymbolIndex; status label shows the candidate count
- Find / Replace in Files auto-populate with the current editor selection and auto-run on open
- Fix merged-tab tooltip: dragging a tab between groups no longer drops its full-path hover text
- Fix post-drag click jank: `setMovable(False)` on PySide6 so Qt's reorder state doesn't get stuck after the custom QDrag eats the mouse release

## v1.0.13 — 2026-04-14
- Autocomplete: `from X import ...` now suggests names from module X, including submodules discovered via pkgutil
- Autocomplete: `from X.Y.` and `import X.Y.` offer submodule completions even before the package has been imported
- Autocomplete: fix dotted attribute completion silently hiding submodules (removed faulty `x in sys.modules` filter)
- Autocomplete: module imports cached per session so typing in an import line doesn't re-run package init on every keystroke

## v1.0.12 — 2026-04-14
- Fix Ctrl+V silently failing in the terminal after the shell exits: the terminal now auto-restarts and queues the paste
- Fix stale QAction and stale focus-widget crashes in the Maya hotkey filter that could silently kill all Ctrl+ shortcuts
- Fix bracketed paste mode leaking across terminal restart — paste would insert escape sequences literally in simple shells after a TUI app exited
- Fix paste when focus is on the read-only output panel — now redirects to the active code editor
- Fix terminal selection being destroyed by the 60fps render timer (intermittent copy failures)
- Fix terminal blank-line accumulation after alt-screen TUI apps (Claude Code, vim) exited or resized
- Fix terminal restart leaving stale scrollback in the display

## v1.0.10 — 2026-04-06
- Fix Maya crash on editor close: replace blocking ReadFile with non-blocking PeekNamedPipe polling so terminal thread exits cleanly within 5ms
- Fix Maya crash: QPlainTextEdit paint engine corruption — atomic edit blocks + signal blocking + re-entrancy guard during 60fps render
- Fix Maya crash: keep QThread backend reference alive to prevent GC of running thread
- Fix terminal: render timer lifecycle — only runs while process is alive (stops repaint cascade on exit)
- Fix terminal: pywinpty read loop no longer exits on transient WinptyError
- Fix terminal double cursor: track DECTCEM cursor visibility (ESC[?25l/h) so TUI apps render their own cursor without overlap
- Fix terminal horizontal scrollbar: disable horizontal scroll, use exact monospace cell width, account for document margin
- Add direct ConPTY fallback via ctypes for Windows 11 build 26200 where kernel32.CreatePseudoConsole is broken
- Fix UE MCP server discovering zero tools: exclude unreal_tools/ from Cython compilation in setup.py
- Fix MCP server venv: recreate with correct Python version to resolve pydantic_core ABI mismatch
- Fix extraction cache: handle locked .pyd files when updating plugin while Maya is running (rename to .old.timestamp)

## v1.0.9 — 2026-04-02
- Smart Home key: first press goes to first non-whitespace character, second press to column 0
- Smart Backspace: deletes to previous tab stop when cursor is in leading whitespace
- Imported name highlighting: stdlib imports (teal) vs third-party/project imports (purple)
- Cross-tab diagnostic suppression: imports from other open tabs no longer flagged as undefined
- Autocomplete: fix missing completions after dot (raised adapter limit from 30 to 500)
- Autocomplete: filter out module-type attributes from dot-completion results
- Autocomplete: macOS fixes — invisible popup, missing os.path, Ctrl+Space, focusOut race
- Settings: hide MEL-related options when running in Unreal Engine
- Fix symbol index re-scanning on every editor close/reopen in Maya
- Fix command port startup warning (unreliable port verification removed)
- AI chat: fix large empty gaps between messages
- Pricing update: Maya/UE perpetual $49, annual $25, bundle perpetual $75, annual $30

## v1.0.8 — 2026-04-01
- Fix terminal Ctrl+V paste when TUI apps (Claude Code, vim) are running
- Fix ANSI parser: process all modes in multi-mode DEC private sequences
- Save/restore bracketed paste state across alternate screen transitions
- AI chat: show friendly tool descriptions instead of raw MCP tool names
- AI chat: fix blank space in plan-style responses (consecutive line break collapse)
- AI chat: environment-aware prompts — never asks "Is it in Maya?" or "Can you paste the error?"
- Output panel: defensive caret-line filter at the single entry point for all output text

## v1.0.7 — 2026-03-31
- Syntax highlighting: fix strings with backslashes only coloring the last escape sequence
- Syntax highlighting: support all Python string prefixes (r, b, u, f, rb, br, rf, fr)
- Fix case-only file rename on Windows (e.g. File.py to file.py)
- Add "Rename" option to tab right-click context menu
- Self-hosted analytics (Umami) on mcaeditor.com with download tracking

## v1.0.6 — 2026-03-30
- Save now clears OS read-only attribute on locked files (Perforce compatibility)
- Execute and save-on-close also handle read-only files transparently

## v1.0.5 — 2026-03-24
- Output panel: filter Python 3.11+ caret indicator lines (^^^) from tracebacks
- Output panel: line-buffer stderr tee to recombine split exception lines
- Output panel: proper red coloring for all traceback lines via stderr context tracking
- Output panel: suppress duplicate traceback echo from Maya's command output
- Output panel: detect WARNING/Error patterns in display messages for correct coloring

## v1.0.4 — 2026-03-24
- File tree: lazy on-demand loading replaces 5-level depth limit — unlimited nesting
- File tree: workspace folders and expanded state persist across sessions per-project
- File tree: user-added workspace folders survive project reopen
- Editor window: respects close state — no longer auto-opens when user explicitly closed it
- Code completion: project-wide symbol index (class/def/proc) via background SymbolIndex
- Reduced redundant tree rebuilds during project open (3 → 1)

## v1.0.3 — 2026-03-18
- Added plugin monetization infrastructure (manifest verification + license stub)
- macOS SSL certificate fix for activation on Maya's embedded Python
- Version check on launch — yellow banner if update is available
- All six builds (Windows + macOS, Maya 2024/2025/2026) deployed

## v1.0.2 — 2026-03-17
- Online activation system — machine fingerprinting, 3-seat limit, token caching
- /activate, /validate, /deactivate, /activations endpoints live
- /manage web page for customers (enter email → see machines → deactivate)
- 7-day offline grace period — never blocks user with valid HMAC key
- Gumroad webhook: test purchases now processed normally

## v1.0.1 — 2026-03-16
- License check wired into Maya plugin load (not just editor open)
- 3-tab LicensingDialog: Activate / Trial Status / Manage Activations
- Trial indicator in status bar (yellow >5 days, red ≤5 days)

## v1.0.0 — 2026-03-02
- Initial public release
- HMAC-SHA256 license key system, 14-day trial
- Single-file distribution (mcaEditor.py self-extracting)
- Maya 2024, 2025, 2026 — Windows and macOS
