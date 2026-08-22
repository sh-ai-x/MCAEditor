# MCA Editor Changelog

## v1.0.35 - 2026-08-21

*First public release since v1.0.32 — v1.0.33 and v1.0.34 were internal builds, so everything below has landed since your last update.*

### Startup and indexing

- **The editor opens in a fraction of the time.** Opening used to block for several seconds while the symbol index was loaded and validated on the UI thread. That work now happens entirely in the background. On a 26,000-file project the window went from **7.6s to 0.3s**.
- **Fixed: the symbol index was rebuilt from scratch on every single open.** A mismatch between the indexer's file filters and the cache-validation filters meant the cached index was rejected 100% of the time, so every launch rescanned the whole workspace. Reopening that same project went from a **34–200s rescan to under 2s**.
- **Indexing is now incremental.** A changed file no longer discards the rest of the index — only what actually moved is re-read, and the cached index is available immediately, so Go To Declaration works right away instead of after the scan finishes.
- **The index cache is half the size and loads without stalling the UI** — 102 MB to 51 MB, read in bounded chunks so it can never freeze the editor mid-load.
- **Upgrading from an older cache no longer forces a full rescan** — existing caches are converted in place in seconds.
- The editor's own project and session files are no longer indexed, and abandoned temp files from interrupted cache writes are cleaned up (one could reach ~100 MB).
- Faster workspace scanning, and a full rebuild — now a rare event — is about 30% quicker.

### Fixes

- **Fixed: MEL procedures with no return type were indexed under the wrong name.** `global proc doThing()` was recorded as `g`, so Go To Declaration could never find those procedures.
- **License validation can no longer delay startup.** A background activation call was running inline on the main thread with a 10-second timeout.
- **Fixed: pressing Enter at the start of a `def` or `class` line indented that line.** `_handle_newline()` derived both the indentation and the "is this a block opener" check from the *whole* line instead of the text left of the cursor, so the trailing colon counted even when the cursor was nowhere near it. Inserting a blank line above a definition shoved the definition one level to the right. The same bug applied to MEL lines ending in `{`, and to splitting a line mid-way (`def foo(` + Enter picked up an indent from the colon further right). Auto-indent after a colon at the end of a line is unchanged.
- Enter over a selection now takes its indentation from where the selection *starts* rather than from the cursor position, which on a forward selection sits at the far end and could be on a completely different line.
- New `tests/test_editor_indent.py` (16 checks, headless Qt).

## v1.0.34 - 2026-08-21
- **Editor open is no longer blocked by the symbol index.** `_start_symbol_indexing()` used to unpickle the on-disk index *and* walk the entire workspace verifying mtimes before returning, all on the Qt main thread. On a 26k-file project that was ~5.5s of dead air (3.5s unpickle + 1.7s walk) on every single open, paid before the window appeared. `IndexWorker` now owns the whole cache lifecycle - load, validate, refresh, save - on its own thread. Measured on the same project: window up in **0.6s instead of 7.6s**.
- **Fixed: the on-disk index cache was always discarded, so every open triggered a full rescan.** The indexer skipped files over 512 KB but the freshness check counted them, so the two file sets could never match. On the reference project 343 oversized files (PySide `.pyd`s, `.pak` bundles, generated autocomplete stubs) guaranteed a "cache is stale" verdict *every* time. Both paths now share one `enumerate_source_files()` with one filter set.
- **Indexing is incremental.** A changed file no longer throws away the other 25,724. The worker reuses everything whose mtime still matches, reparses only what moved, and drops what is gone. Reopening the reference project went from a **34-214s full rescan to 2.4s**, and the index is adopted from the cache up front so Go To Declaration works immediately rather than after the scan finishes.
- **The cache no longer freezes the UI while it loads.** `pickle.load` holds the GIL for its whole duration, so reading a 50 MB index as one object stalled the main thread for 1.6s even from a background thread. The cache is now written as bounded chunks through one shared `Pickler` (schema v4), capping each uninterruptible read at ~80ms. Worst observed startup stall: 283ms, once.
- **The cache is half the size.** `symbols_by_name` and `all_files` are pure derivations of `symbols_by_file` and are rebuilt on load instead of being written; identifiers are interned at parse time so pickle's memo collapses millions of duplicate strings. **102 MB to 51 MB**, unpickle 3.5s to 1.1s.
- **Writes only happen when something changed.** A new dirty flag means an unchanged workspace never rewrites the cache - on close or on completion. Previously every indexing run and every editor close re-serialized the entire index, and the completion path did it on the main thread.
- **Faster, cleaner filesystem walk.** `os.scandir` replaces `listdir` + `isdir` + `isfile` + `getmtime` (Windows returns the attributes as part of the enumeration), recursion is now an explicit stack, and the skip-extension list covers the binaries that were previously walked and only rejected later by the size gate. Walk time on the reference project: **1.4s to 0.2s**.
- **Removed the O(n^2) insert.** `_bulk_insert` did `if filepath not in self._all_files` against a growing list - about 1.6s of pure list scanning across a 26k-file index. The list was redundant with `symbols_by_file` and is gone.
- **Abandoned `.pkl.tmp` files are cleaned up.** A killed write left a full-size copy behind and nothing ever removed it; one machine had a 99 MB orphan sitting in the prefs folder since May.
- **Fixed: MEL procs with no return type were indexed under the wrong name.** In `global proc doThing()` the greedy return-type pattern swallowed the name and backtracked, indexing the symbol as `g`. Go To Declaration could never find those procs. Now matches on the required open paren instead.
- **License validation can't stall the launch.** The auto-activation call for legacy keys ran inline on Maya's main thread despite being documented fire-and-forget - it now runs on a daemon thread. The grace-period revalidation still runs inline (so revocation is still enforced at launch) but with a 3s timeout instead of 10s.
- **Older cache formats are upgraded in place, not discarded.** A schema bump used to mean re-reading every file in the workspace - over three minutes on the reference project with a cold filesystem cache, during which Maya appears to hang on `mcaEditor`. Schema 2 and 3 caches hold the same symbol data in a different container, so they are now converted (and re-interned, or the upgraded cache would be permanently oversized at 85 MB instead of 51 MB). Measured: **5.8s instead of 200s+**, keeping 25,705 of 25,725 files. Only `.mel` entries are dropped for reparse, since the MEL regex fix above changes what the parser extracts from them.
- **The editor's own metadata is no longer indexed.** `.mca-project` and the `.mca-session-*.json` manifests live in the workspace root and are rewritten on a 400ms debounce while you work, so every launch saw "changed files" and rewrote the entire multi-megabyte cache for nothing.
- **Cache invalidation after a parser fix is keyed off what the parser produced, not the file extension.** A new `parser_version` field records which parser wrote the cache; when it is behind, only the files that change could possibly affect are dropped for reparse. The first attempt at this keyed off `.mel` and silently left stale symbols in the 10 `.py` files that contain embedded MEL (MEL generators, `melparse.py`, Tcl templates) - Go To Declaration kept offering symbols named `g`, `_` and `s`.
- Full index rebuild is also ~30% faster (42s to 29s on the reference project), though it should now be a rare event rather than a once-per-open one.

## v1.0.33 — 2026-08-18
- **Fixed: auto-opening a project wiped the default session.** `_will_auto_open_project()` makes `__init__` skip the default-session restore, but `_open_project()` then called `_save_context_session()` *before* `_active_project` was set — writing a zero-tab manifest straight over the user's default `session.json`. Their non-project tabs were gone the next time they closed the project. This was the main source of "I lost all my tabs" reports. A new empty-session guard refuses to write a zero-tab manifest from a panel that has never held a tab.
- **All session writes are now atomic.** `session.json`, buffer files, `output.log`, and every editor save go through `session_manager.atomic_write()` — temp file, `flush()`, `fsync()`, `os.replace()`. Previously a plain `open(path, "w")` truncated the destination first, so a crash or hard DCC exit mid-write left a zero-byte `session.json` and every tab was lost.
- **`session.json.bak` rollover.** Before each manifest write, a manifest that parses *and* holds at least one tab is copied to `.bak`. Loads fall back to the backup when the live file is unreadable, so a single bad write no longer costs the whole tab list. An empty session never overwrites a good backup.
- **A corrupt manifest is never overwritten.** If a manifest exists but neither it nor its backup can be read, tab persistence is paused for the session (`_session_manifest_locked`) and the user is told — so the file stays on disk for manual recovery instead of being replaced by the blank fallback session.
- **The manifest now tracks every structural change.** `_new_buffer()` and `_open_file_path()` save it immediately, `editors_changed` / `active_editor_changed` schedule a debounced save (400 ms), and the panel writes the manifest once at the end of `__init__`. Previously only Ctrl+S, close-tab, and a graceful shutdown wrote it, so a crash after opening files lost the tab list.
- **Autosave and crash recovery (new).** A timer (default 15s, `autosave_interval_secs`) writes shadow copies of every modified tab to `mca_preferences/<dcc>/recovery/`. The user's real files are never touched, so there is no surprise overwrite, no Perforce fight, and no module auto-reload. On next launch a snapshot that differs from disk is restored into the tab and marked modified. Snapshots are cleared on successful save and on explicit Discard, and purged after 30 days. Opt in to writing modified tabs straight to their real file with `autosave_to_file`; autosave failures show a status message instead of a modal dialog.
- **Tabs for temporarily missing files survive.** `_restore_session` used to silently drop a tab whose file wasn't there, and the next save pruned it from the manifest for good — a network share offline for one launch cost the tab permanently. Such entries are now carried forward for 7 days and reopen automatically when the file returns.
- **Unsaved edits survive a project switch.** `_save_context_session()` only persisted path-less buffers, so modified file-backed tabs were destroyed by the context teardown. They now get a recovery snapshot first.
- **Restored `mca_core/adapters/base_adapter.py`**, which had been deleted in the working tree while `adapters/__init__.py` still imported `DCCAdapter`/`DCCType`/`ConnectionState` — the package could not import at all.
- New regression suites: `tests/test_session_persistence.py` (26 checks) and `tests/test_panel_persistence.py` (34 checks, headless Qt).

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
