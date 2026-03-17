# Session Notes: 2026-03-16 — License Check on Plugin Load

## What Was Done

Wired the license activation system into MCA Editor's Maya plugin startup
sequence. Previously the license gate only lived inside `show_mca_editor()`.
Now there's a full license check at plugin load time with a 3-tab dialog
and a trial countdown indicator in the status bar.

### New Files

- **`mca_core/activation.py`** — Stub module providing the online activation
  API surface (`validate_on_launch`, `activate`, `deactivate`,
  `get_activations`, `get_trial_status`). All functions fall back to the
  existing offline `license.py` system. Ready to be replaced with HTTP
  calls when the license server is connected.

- **`mca_qt/widgets/licensing_dialog.py`** — New 3-tab `LicensingDialog`:
  - **Activate** tab: key input with mask, activate button, buy link
  - **Trial Status** tab: days remaining card, buy button
  - **Manage Activations** tab: masked key display, deactivate button,
    placeholder for online activation list
  - `open_from_menu()` (non-modal) and `show_if_needed()` (modal) class methods
  - Initial tab selection based on reason code (not_activated, expired, etc.)

### Modified Files

- **`mca_maya/plugin_main.py`**:
  - Added `HAS_ACTIVATION` import guard
  - Extracted `_open_editor_window()` from `_do_auto_open_editor()` for
    post-activation use
  - Added `_run_license_check()` replacing `_queue_auto_open()` in
    `initializePlugin()` — validates license, checks trial, shows banner
    or dialog as needed
  - Helper functions: `_queue_auto_open_inner()`, `_show_licensing_dialog()`,
    `_queue_trial_banner()`, `_run_pending_trial_banner()`

- **`mca_maya/maya_window.py`**:
  - Added `_trial_indicator` QLabel to the status bar
  - `show_trial_indicator(days)` — yellow text for >5 days, red for <=5
  - `_check_trial_for_status_bar()` — runs at build time AND on
    activate/deactivate for live updates

- **`mca_qt/editor_panel.py`**: Help > Licensing now opens `LicensingDialog`
  with the correct version-specific settings instance

- **`build_maya.py` / `setup.py`**: Added `licensing_dialog.py` to `.pyc`
  exclusion lists (QDialog subclass)

- **`mca_core/__init__.py`**: Version bumped to 0.4.0

## Issues Found & Fixed

1. **Trial expired popup too early**: The licensing dialog was called
   directly from `_run_license_check()` which runs at `executeDeferred`
   timing. A modal dialog at that point halts Maya's entire startup
   sequence (workspace restore, UI layout, etc.). Fixed by adding
   `_queue_licensing_dialog()` which defers via
   `evalDeferred(lowestPriority=True)` — Maya finishes loading first,
   then the dialog appears. Uses the same module-level closure pattern
   as `_queue_trial_banner`.

2. **Settings namespace mismatch**: The licensing dialog was creating
   `MCASettings()` (default namespace) but license keys are stored under
   `MCASettings(app_name="MCAEditor-Maya2025")`. Dialog showed trial info
   even when user had a valid perpetual key. Fixed by passing the panel's
   `self._settings` through to `open_from_menu()`.

3. **Trial banner race condition**: Original plan used a deferred chain
   (`_queue_trial_banner` -> `evalDeferred` -> find window) but the
   window often didn't exist yet when the callback ran. Fixed by checking
   trial status directly in `_build_status_bar()` at window creation time.

4. **Mid-session state sync**: Deactivating a license mid-session didn't
   update the status bar. Fixed by having `_on_deactivate_this()` and
   `_on_success()` in the dialog call `_refresh_status_bar_indicator()`,
   which traverses to the Maya window and calls `_check_trial_for_status_bar()`.

## Testing Status

- Licensed user: no trial indicator, editor opens normally
- Trial user: yellow/red indicator in status bar, licensing dialog from menu works
- Deactivate mid-session: status bar updates immediately
- Activate mid-session: status bar hides trial indicator immediately
- Trial expiration: pending test on 2026-03-17 (trial started 2026-03-03)

## Build Status

- Maya 2024: Built and deployed as v0.4.0 (2026-03-17)
- Maya 2025: Built and deployed as v0.4.0 (2026-03-16)
- Maya 2026: Built and deployed as v0.4.0 (2026-03-17)

## Next Steps

- Test trial expiration flow (2026-03-17) — should show modal licensing dialog
  blocking the editor
- Connect `activation.py` to the real license server (replace stubs with HTTP)
- Populate Manage Activations tab with real server data when available
