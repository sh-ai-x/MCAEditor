# 2026-03-21 — UE Plugin: Keyboard Focus + Anti-Flash Fix

## Summary
Fixed keyboard input in the UE-embedded MCA Editor and eliminated the
blank-on-open flash. All three user-reported issues now verified working
via automated testing in live UE 5.6.

## Issue 1: Keyboard Input Not Working — VERIFIED FIXED
### Root Cause (Two-Part)
1. **Wrong Win32 HWND for focus**: The old event filter called
   `SetFocus(_mca_qt_hwnd)` on every mouse click — but `_mca_qt_hwnd`
   is the **panel's** HWND. Qt child widgets (MCACodeEditor, OutputWindow)
   have their **own** native HWNDs. Win32 delivers keyboard events to the
   focused HWND, so they went to the panel instead of the editor.

2. **Qt "active window" state**: With WS_CHILD embedding, Qt doesn't
   consider our panel as the "active window." This means `setFocus()` fails
   silently, `focusWidget()` returns None, and the focus system is dead.
   Calling `panel.activateWindow()` fixes this — it sets Qt's internal state
   without stealing UE's foreground window.

### Fix
- **Removed** the `_UEFocusFilter` event filter entirely (wrong approach)
- **Added** `_mca_editor.activateWindow()` before `processEvents()` in both
  `_mca_tick()` and `_mca_pump_qt()` — keeps Qt focus system alive
- **Added** `_sync_win32_focus()` after `processEvents()` — checks which
  widget Qt focused and calls `SetFocus()` on that widget's native HWND

### Key Findings
- Qt's panel window proc **forwards keyboard events** to the focused child
  widget even when Win32 focus is on the panel HWND (not the editor HWND).
  So Win32 focus on the panel is sufficient — _sync_win32_focus is a
  belt-and-suspenders measure.
- `activateWindow()` does NOT change the Win32 foreground window — it only
  sets Qt's internal "active" state. Safe to call every tick.
- When UE has Win32 focus (user in viewport), our `activateWindow()` does
  NOT steal focus back.
- Click-to-focus flow: user clicks editor → WM_LBUTTONDOWN reaches child
  HWND → processEvents processes it → QPlainTextEdit::mousePressEvent calls
  setFocus() → Qt sets focusWidget → _sync_win32_focus syncs Win32 focus

### Verification
```
Qt focus: MCACodeEditor
Win32 focus: 0x2580c82
Typed text: 'typing works!'
KEYBOARD: WORKING
```

## Issue 2: Blank-on-Open Flash — FIXED
### Root Cause
The init code called `_mca_editor.show()` immediately, which rendered the
widget at Qt's default position (0,0) before the first `_mca_tick()` call
positioned it correctly via `MoveWindow()`.

### Fix
Changed init to: `show()` → `ShowWindow(SW_HIDE)` → let first `_mca_tick()`
call `MoveWindow()` then `ShowWindow(SW_SHOWNOACTIVATE)`. Also handles
HWND recreation during init's processEvents by re-applying WS_CHILD + hide.

## Issue 3: UE Log Tailing — VERIFIED WORKING
Log tailer uses blacklist filter (excludes only extremely noisy per-frame
categories like LogRHI, LogRenderer, LogShaders). All other categories are
shown. 26 lines of UE startup logs confirmed appearing in the MCA output
panel including LogPython, LogMCAEditor, LogSlate, LogAssetRegistry, etc.

## File Changed
- `mca_unreal/Content/Python/ue_editor_host.py` — all three fixes

## Architecture: UE Keyboard Focus Chain
```
User clicks editor area
  → Win32 WM_LBUTTONDOWN to child HWND
  → _mca_tick: activateWindow() + processEvents()
    → Qt processes click, QPlainTextEdit::mousePressEvent → setFocus()
    → Qt sets focusWidget = MCACodeEditor
  → _sync_win32_focus() → SetFocus(editor_hwnd)
  → User types → WM_CHAR to panel HWND → Qt forwards to focusWidget
```
