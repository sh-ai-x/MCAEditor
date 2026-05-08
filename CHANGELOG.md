# MCA Editor Changelog

## v1.0.32 — 2026-05-08
- **Removed the integrated terminal** — `terminal_native`, `terminal_xterm`, `terminal_tab_panel`, `terminal_backend`, `terminal_factory`, `ansi_parser`, the xterm.js resources, the `pywinpty` runtime dep, and all terminal-routing logic in the Maya hotkey filter are gone. The terminal had become a long-running source of regressions and most users prefer running shell/AI workflows in a real terminal.
- **Faster editor open** — when a project is set to auto-open, the default-session restore is skipped (the auto-open immediately rebuilt the layout from the project manifest, throwing away ~0.6s of work on every open). Symbol-index startup delay reduced from 3.0s → 0.5s. Plugin loading kept synchronous so the AI Chat plugin's API binding doesn't race.
- **Instant editor close** — `cleanup()` runs in three phases: synchronous data-critical save, deferred Qt-thread cleanup, and a daemon-thread I/O tail. The dock disappears immediately; symbol-index pickle, JSON-RPC server join, and other slow shutdowns happen off the user-visible path. Reduced `editor_api_server.stop_server` join from 5s → 0.2s; symbol-index worker join from 2.0s → 0.05s.
- **Bounded result repr** — evaluating a huge variable (a 1M-key dict, a 10M-element list, a 100 MB string) used to freeze Maya for tens of seconds while `repr()` allocated megabytes of text. New `_safe_repr` uses `reprlib.Repr` to cap the result line at 4 KB and finishes in microseconds — 100×–5000× speedup, no UI freeze.
- **Save reliability** — `_save_on_execute` and `_save_buffer_content` no longer clear the editor's modified flag when the disk write fails. `_write_file` now returns success/failure and `session_manager.save_buffer` returns `None` on failure so the caller can skip the `*` indicator clear and avoid running module reload on stale on-disk content.
- **Symbol-index throttling rebalanced** — yields every 40 files for 2 ms (was every 200/1 ms). Worst-case main-thread stall during indexing drops from ~2 s to ~200 ms so executing code or switching tabs while the initial 25k-file index is still building no longer hangs Maya.
- **No more reindex thrash** — the workspace file watcher's 3-second debounce no longer cancels an in-progress initial build when the editor itself saves a file. Editor-initiated saves are already covered by `update_file()`; the watcher only triggers a full reindex when the index is already ready.
- **Atomic-save race fix** — `SymbolIndex.save_to_disk` uses a unique per-call temp filename so the poll-tick saver and close-time bg saver don't collide on `.pkl.tmp` (was raising `WinError 32` on Windows).
- **Maya 2024 paint dispatch guard** — `LineNumberArea.paintEvent` now checks `hasattr(event, "rect")` to survive the rare PySide2/Shiboken2 case where a `QShowEvent` is misdispatched into a paint slot during initial workspace-control show.

## v1.0.19 — 2026-05-01
- Fix Unreal terminal silently degrading to subprocess pipes when only Python 3.10 is on PATH — managed venv was being built with the system 3.10 interpreter even though UE 5.5+ runs Python 3.11, leaving a `cp310` pywinpty extension that couldn't import
- `_find_system_python` now prefers UE's bundled interpreter (`Engine/Binaries/ThirdParty/Python3/Win64/python.exe`) and otherwise prefers an exact `(major, minor)` match against the running Python before falling back to any 3.10+
- New `_find_unreal_bundled_python` derives the path from `sys.prefix` so the venv ABI always matches the host process

## v1.0.18 — 2026-04-22
- Ctrl+V terminal routing defense in depth + resize clip fix

## v1.0.17 — 2026-04-15
- Fix symbol-index disk cache save failing with `Can't pickle <class 'importlib._bootstrap.SymbolEntry'>` — SymbolEntry namedtuple's `__module__` gets mis-pinned by the SourcelessFileLoader used by the single-file plugin wrapper; pickled snapshots now use plain tuples and `__module__` is set explicitly. Schema version bumped to v2.

## v1.0.16 — 2026-04-15
- Symbol index survives Maya restart: persist ready index to `~/Documents/mca_preferences/MCAEditor/index_cache/` and reuse on next launch if file mtimes still match
- `SymbolIndex.save_to_disk` / `load_from_disk` / `is_fresh_for` — magic header + schema version + atomic temp-file write
- Editor no longer kicks off a full re-scan on every close/reopen of the panel (6th fix for this regression; disk layer closes the hole that module-level cache alone couldn't)
- Self-heal managed venv when Windows Update swaps host Python: wipe `.venv-3.X` if `pyvenv.cfg` version disagrees with running Python so `pywinpty` cp-ABI mismatches can't silently break the terminal

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
