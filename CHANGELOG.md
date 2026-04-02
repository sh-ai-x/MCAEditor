# MCA Editor Changelog

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
