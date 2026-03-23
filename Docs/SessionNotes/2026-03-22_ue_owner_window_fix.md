# 2026-03-22 — UE Plugin: Fix Window Z-Ordering (Owner Window)

## Summary

Replaced the `WindowStaysOnTopHint` hack with a proper Win32 owner-window
relationship. The MCA Editor now floats above UE's main window only — not
above every application on the desktop.

## Problem

`Qt.WindowStaysOnTopHint` sets `WS_EX_TOPMOST` on the Win32 window, making
it stay above ALL windows system-wide. This was a lazy shortcut from the
previous session that should never have been shipped.

## Solution: Win32 Owner-Window Relationship

The correct Win32 mechanism is `SetWindowLongPtrW(qt_hwnd, GWLP_HWNDPARENT, ue_hwnd)`.
For a `WS_POPUP` window (which Qt windows are by default), this establishes an
**owner** relationship — NOT a parent-child relationship. An owned window:

- Floats above its owner in z-order (but NOT above other apps)
- Minimizes/restores together with its owner
- Is destroyed when the owner is destroyed

### C++ Side
- Added `GetMainWindowHWND()` — retrieves UE's main window HWND via
  `FSlateApplication::Get().GetActiveTopLevelWindow()->GetNativeWindow()->GetOSWindowHandle()`
- Modified `OnToolbarButtonClicked()` to embed the HWND as a hex integer in the
  Python launch command: `ue_editor_host.launch(ue_hwnd=0xABCD1234)`

### Python Side
- Added ctypes setup for `SetWindowLongPtrW`, `GetWindowLongPtrW`, `IsWindow`, `SetWindowPos`
- Added `_set_owner_window(qt_hwnd, owner_hwnd)` helper that:
  1. Validates both HWNDs with `IsWindow()`
  2. Calls `SetWindowLongPtrW(qt_hwnd, GWLP_HWNDPARENT, owner_hwnd)`
  3. Calls `SetWindowPos` with `SWP_FRAMECHANGED` to apply
  4. Verifies ownership via `GetWindowLongPtrW`
- Removed `WindowStaysOnTopHint` from `_launch_editor()`
- Added HWND recreation detection in `_pump_qt()` — Qt recreates the HWND once
  after first show, which breaks the owner relationship. The tick function
  detects this and re-applies ownership.
- Fallback: if C++ passes `ue_hwnd=0` (Slate not ready), falls back to
  `WindowStaysOnTopHint` with a warning log.

## Key Win32 Details
- `GWLP_HWNDPARENT = -8` — despite the name, sets the OWNER (not parent) for WS_POPUP windows
- `SetWindowLongPtrW` on x64 uses `LONG_PTR` (8 bytes) — ctypes argtypes must use `c_longlong`
- `SWP_FRAMECHANGED` is required after changing ownership for Windows to re-evaluate z-order
- Qt's `winId()` returns the current native HWND — must be checked each tick for recreation

## Verification Steps
1. Editor floats above UE window
2. Editor does NOT float above other apps (browser, Explorer)
3. Minimizing UE also minimizes editor
4. Restoring UE also restores editor
5. HWND recreation detected and ownership re-applied (check UE output log)
6. Close/reopen editor works across multiple cycles

---

## Fix 2: UE Log Tailer — Show Full Log + Severity Colors

### Problem
The log tailer was showing NO UE logs because:
1. `UELogTailer.__init__` seeked to EOF (`seek(0, 2)`), skipping the entire log history
2. After editor launch, almost no non-MCAEditor log lines are generated
3. On close/reopen, a new tailer was created that seeked to EOF again, losing all logs from the gap

### Solution
1. **Read from beginning**: Changed `__init__` to accept `start_position` param (default 0).
   Always reads from byte 0 (full history) since output panel is recreated each time.
2. **Initial history load**: New `_load_history()` method reads all content from start to EOF,
   parses each line with the same filtering/coloring as `poll()`, writes to output panel.
3. **Severity coloring**: New `_route_line()` method parses both structured UE log lines
   (with `[timestamp][frame]Category: Verbosity: Message`) and unstructured lines.
   Errors route to `write_error()` (red), warnings to `write_warning()` (yellow).
4. **Diagnostic logging**: Both `_load_history()` and `poll()` log line counts.

### Results (verified in live UE 5.6)
```
Log tailer started: D:/Unreal-Projects/UE56Test/Saved/Logs/UE56Test.log
  Start position: 0 bytes
  History loaded: 621 lines written, 561 skipped (category), 4 skipped ([MCAEditor]), 1186 total parsed
Log poll: 1 new lines written to output panel
```

---

## Fix 3: Editor Reopen After X Close

### Problem
When user closed the MCA Editor with the X button, clicking the toolbar button
again didn't reopen it. The `_mca_editor_window` Python reference still existed
pointing to a closed/hidden widget, so `raise_()` silently failed.

### Solution
1. **`_pump_qt()` detects X-close**: Checks `isVisible()` each tick. If the
   window exists but isn't visible (user closed with X), calls `_close_editor()`
   to save state and clean up references.
2. **`_launch_editor()` handles closed windows**: The "already open" check now
   also tests `isVisible()`. If the window exists but isn't visible, cleans up
   and falls through to create a fresh editor.

---

## Fix 4: Window Geometry Persistence

### Problem
Window size and position were lost on close/reopen (both within a UE session
and across UE restarts).

### Solution
1. **In-memory cache**: `_window_geometry` module-level variable stores
   `saveGeometry()` result — survives close/reopen within same UE session.
2. **QSettings persistence**: On close, geometry is saved to QSettings
   (`MCAEditor/UEPlugin` organization/app). On launch, restored from
   QSettings if no in-memory cache (first open of a new UE session).
3. **`_launch_editor()`** checks in-memory cache first, then QSettings,
   then falls back to default 1200x800.

---

## Fix 5: Auto-Reopen on UE Restart

### Problem
If the editor was open when UE closed, the user had to manually click the
toolbar button again after restarting UE.

### Solution
1. **Python `auto_launch(ue_hwnd)`**: New entry point that checks QSettings
   `was_open` flag and launches if True.
2. **`_close_editor(shutting_down)`**: Takes a `shutting_down` parameter.
   - User X-close: `was_open=False` (user chose to close)
   - UE shutdown: `was_open=True` (auto-reopen next session)
3. **C++ auto-launch ticker**: `RegisterToolbarExtension()` schedules a
   `FTSTicker` with a 2-second delay. It retries until `GetMainWindowHWND()`
   returns a valid HWND, then calls `ue_editor_host.auto_launch()`.

---

## Fix 6: Remove MEL/Maya from UE Version

### Changes
- Removed MEL from language combo box
- Hidden Maya-specific menu actions (New MEL Buffer, Save Script to Shelf, Source Script)
- Hidden Maya help links (MEL Command Reference, Python Command Reference, Node and Attribute Reference)
- Added UE help links: UE Python API Reference, UE Blueprint Visual Scripting,
  UE Scripting with Python, UE Editor Scripting Utilities
- Overrode New Tab dialog to offer only Python and Text (no MEL)
- Close any open MEL tabs on launch

---

## Fix 7: Tab Bar Frame Visibility

### Problem
The tab bar strip blended with the editor background, making it hard to see
the divide between editor and output panel.

### Solution
Added `QTabBar { background-color: #383838; }` to the inline stylesheet in
`editor_group.py`. This overrides the transparent background caused by
`setDocumentMode(True)` and provides a visible lighter strip.

---

## Fix 8: Remove "Executed in UE" Noise

Suppressed the "Executed in UE" success message that appeared in the output
panel after every code execution. The message added noise without value.

---

## Fix 9: About Dialog — DCC-Aware Tagline

### Problem
The About dialog showed "A better Maya script editor" even in UE.

### Solution
Check `self._dcc_version` — if it starts with "UE", show "A Python editor
for Unreal Engine" instead of the Maya tagline.

---

## Fix 10: Project Settings Dialog — Double Spacing + Geometry

### Problem
List items in the Project Settings dialog were double-spaced due to CSS padding
stacking: dialog's `padding: 3px` + global theme's `padding: 3px 0px`.
Dialog also didn't remember its size/position.

### Solution
1. Changed `_LIST_STYLE` item padding from `padding: 3px` to `padding: 1px 4px`.
2. Added QSettings-backed geometry save/restore (`accept()` and `reject()`
   both call `_save_geometry()`).

---

## Fix 11: Code Completion — None Adapter Guard

### Problem
`CompletionProvider.get_completions()` crashed when `adapter_manager` is None
(UE passes None since execution is local).

### Solution
Added `if self._adapter_manager else None` guard in `completer.py`.

---

## Fix 12: Eval-First Execution (Variable Inspection)

### Problem
Highlighting a variable and pressing Execute showed nothing — `exec()` doesn't
return values.

### Solution
Added eval-first logic to `_execute_locally()` in `editor_panel.py`:
```python
try:
    compiled = compile(code, "<mca_editor>", "eval")
    result = eval(compiled, self._local_namespace)
    if result is not None:
        print("# Result: {} #".format(repr(result)))
except SyntaxError:
    exec(code, self._local_namespace)
```

---

## Fix 13: Status Bar (Activity Bar) at Bottom

### Problem
The status bar was added to `panel.layout().addWidget(bar)` but the panel's
layout is `QHBoxLayout` (stripe | splitter), so it appeared as a third
horizontal element in the middle-right.

### Solution
Restructured `_launch_editor()` to wrap the panel in an outer `QWidget`
container with `QVBoxLayout`:
- Menu bar at top (via `setMenuBar`)
- MCAEditorPanel fills the middle (stretch=1)
- Blue status bar spans the full width at the bottom

The outer container becomes `_mca_editor_window`; the panel is stored as
`_mca_editor_window._panel`.

---

## Fix 14: Session State Persistence (Tabs + File Tree)

### Problem
Open tabs, file tree expanded state, and splitter positions were lost on
close/reopen because `_close_editor()` never called the panel's save methods.

### Solution
Added `panel.save_window_state(settings)` and `panel.cleanup()` calls in
`_close_editor()` before closing the window. This persists:
- Open tabs and buffer contents (session manifest)
- File tree expanded/collapsed folders
- Splitter sizes and panel visibility
- Completer cleanup (prevents shiboken crashes)

Also deletes `output.log` after cleanup to prevent duplication — the UE log
tailer reloads the full UE log from position 0 on every launch.

---

## Files Changed
- `mca_unreal/Source/MCAEditor/Public/MCAEditorModule.h` — Added `GetMainWindowHWND()` declaration
- `mca_unreal/Source/MCAEditor/Private/MCAEditorModule.cpp` — Added `GetMainWindowHWND()`, auto-launch ticker, `Containers/Ticker.h` include
- `mca_unreal/Content/Python/ue_editor_host.py` — Owner-window, log tailer rewrite, reopen fix, geometry persistence, auto-launch, MEL removal, UE help links, outer container layout, status bar, session state save, eval-first execution
- `mca_qt/widgets/editor_group.py` — Tab bar frame background color
- `mca_qt/widgets/new_tab_dialog.py` — Added `languages` parameter for UE customization
- `mca_qt/editor_panel.py` — Removed "Executed in UE" message, DCC-aware About dialog, eval-first local execution
- `mca_qt/widgets/completer.py` — None adapter_manager guard
- `mca_qt/widgets/project_settings_dialog.py` — Fixed double-spacing CSS, added geometry persistence
