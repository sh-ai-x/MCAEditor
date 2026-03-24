# MCA Editor Changelog

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
