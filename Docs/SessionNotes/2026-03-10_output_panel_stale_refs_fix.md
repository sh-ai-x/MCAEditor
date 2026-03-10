# 2026-03-10: Output Panel Stale Widget Reference Fix

## Problem

Output panel broken since v0.3.6 — three symptoms:
1. Output doesn't match Maya's Script Editor
2. Only "somewhat works" after unloading and reloading the plugin
3. At startup, only MCA Editor logs (stderr/logging) appear — not Maya stdout or command output

## Root Cause: Stale Widget References from Startup Race

The v0.3.6 "hybrid four-mechanism capture" architecture was sound, but all three capture
mechanisms held **direct references** to a specific output widget that gets destroyed during
the startup race condition:

1. Plug-in Manager auto-loads plugin -> queues deferred work
2. Maya restores workspace -> uiScript -> creates **Window A** -> hooks bind to Window A's output widget
3. userSetup.py fires -> deletes workspace control -> **Window A destroyed** -> hooks now reference dead C++ objects
4. `_do_auto_open_editor` fires -> creates **Window B** -> reinstalls hooks (but gap already lost output)

Between steps 3 and 4, all output silently swallowed by `except` handlers. Even after step 4
reinstalls hooks, startup output is lost.

Why unload/reload fixed it: clean unload removes all hooks, clean reload creates single window
with fresh hooks. No competing creation paths.

## Solution: Two-Part Fix

### Commit 1: `_output_target` indirection (`maya_window.py`)

- Added module-level `_output_target` pointer — all capture mechanisms read this on every write
- `_on_maya_output`: converted from instance method to module-level function (zero `self.` refs)
- `_StdoutTee`/`_StderrTee`: removed `output_widget` constructor param, read `_output_target` each write
- `_install_output_hook`: only swaps `_output_target` pointer on window recreation (tees installed once)
- `dockCloseEventTriggered`: clears `_output_target` but **leaves tees installed** (they no-op)
- `cleanup_editor`: clears target AND removes tees (plugin unload = full teardown)

### Commit 2: Startup race fix (`plugin_main.py`)

- `_do_auto_open_editor`: early-out if uiScript already created a healthy window — just refresh hooks
- userSetup.py block: added `pluginInfo(loaded=True)` guard — if plugin already loaded, skip
  workspace control deletion (takes effect next Maya launch after plugin loads once)

## Key Design Decisions

1. **Tees survive dock close** — only removed on plugin unload. Avoids breaking stdout/stderr chain.
2. **Module-level callback** — `_on_maya_output` has zero `self.` references, survives any window lifecycle.
3. **`_output_target = None` guard** — all three mechanisms check before writing, silent no-op when closed.
4. **userSetup.py guard is additive** — existing installs get updated on next plugin load via marker replacement.

## Verification Plan

### Close/Reopen Cycle (Commit 1)
1. Load plugin, open editor
2. Run `print("hello")` in Script Editor — verify in MCA output
3. Run `cmds.warning("test")` — verify yellow warning
4. Close editor (dock close button)
5. Reopen via Script Editor button
6. Repeat steps 2-3 — verify output resumes immediately
7. Unload plugin, reload — verify output works

### Startup Race (Commit 2)
1. Close Maya with editor open (editor_was_open = True)
2. Relaunch Maya (plugin auto-loads)
3. Verify output panel shows startup history AND captures ongoing output
4. Compare side-by-side with Script Editor
5. Execute code from MCA Editor — verify print(), results, errors all appear

## Status

Implementation complete. Ready for Maya testing.
