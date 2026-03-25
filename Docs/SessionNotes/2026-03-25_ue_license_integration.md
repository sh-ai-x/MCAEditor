# Session Notes — 2026-03-25: UE License Integration

## Summary

Hooked up the license system to the Unreal Engine plugin. Previously the UE
version had zero license checks — users could run it indefinitely without a key.
Also added cross-namespace key sharing so a Maya perpetual key automatically
unlocks the UE plugin (and vice versa).

## Problems Found

1. **No license gate in UE** — `ue_editor_host.py:_launch_editor()` created the
   editor panel directly without calling `check_license()` or
   `validate_on_launch()`. Both `launch()` and `auto_launch()` entry points
   were affected.

2. **License keys siloed per DCC** — Each DCC has its own QSettings namespace
   (`MCAEditor-Maya2025`, `MCAEditor-UE5`, etc.). A key entered in Maya was
   invisible to UE and vice versa.

3. **`activation._get_settings()` missing "unreal" product** — Fell through to
   the base `MCAEditor` namespace instead of the UE5-specific one.

4. **`LicensingDialog` doesn't call `self.accept()`** — After entering a valid
   key and seeing "success", closing via X returns `Rejected` (0). Initial code
   treated this as "cancelled" and aborted the launch, causing the dialog to
   pop up a second time.

5. **Auto-launch popup on expired license** — If the editor was open last
   session and the license expired, `auto_launch()` would show the licensing
   dialog during UE startup, which is disruptive.

## Changes

### `mca_core/license.py`
- Added `_find_key_in_other_namespaces()` — searches all known QSettings
  namespaces (Maya 2024/2025/2026, UE5, standalone) for a valid key
- `check_license()` now falls back to cross-namespace search when the current
  DCC has no key, copies it locally for future use
- `store_license_key()` also writes to the shared base namespace
  (`MCATools/MCAEditor`) so all DCCs can discover new keys

### `mca_core/activation.py`
- `_get_settings("unreal")` now returns `MCASettings(dcc_version="UE5")`

### `mca_unreal/Content/Python/ue_editor_host.py`
- Added full license gate in `_launch_editor()` using `validate_on_launch()`
  from the activation module (same flow as Maya), with offline fallback
- Added `show_license_dialog` parameter — `launch()` passes True (toolbar
  button), `auto_launch()` passes False (silent skip on expired license)
- Dialog result no longer checked — re-checks license state after dialog closes
  regardless of how it was dismissed
- Trial message shown on status bar for 10 seconds after launch

## Deployment

- Updated `ue_editor_host.py` in source, `dist/`, and Wayward project plugin
- Replaced `license.pyd` and `activation.pyd` with `.pyc` versions in both
  dist and Wayward deploy (temporary for testing — full rebuild needed for
  production distribution)

## Testing

Verified all scenarios:
- Fresh UE install with no key → finds Maya perpetual key automatically
- Expired trial with no key + toolbar button → licensing dialog appears
- Expired trial with no key + auto_launch → silently skips, no popup
- Valid key entered in dialog → editor opens after closing dialog via X
- Key generation and validation round-trip confirmed working
