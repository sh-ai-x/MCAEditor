# Session Notes — 2026-04-02: QOL Editor Improvements, Autocomplete Fixes, Pricing Update

## Version: 1.0.9

---

## Changes Made

### 1. Smart Home Key (`code_editor.py`)
- First press of Home moves cursor to first non-whitespace character on the line
- Second press (or if already at first non-whitespace) moves to column 0
- Shift+Home extends selection using the same toggle logic
- Ctrl+Home still goes to document start (not intercepted)

### 2. Smart Backspace (`code_editor.py`)
- When cursor is in leading whitespace at a tab-stop boundary (col divisible by `_tab_size`), Backspace deletes back to the previous tab stop (e.g. 4 spaces) instead of one character
- Only activates when prefix is all spaces and cursor is at a tab-stop boundary
- Otherwise falls through to normal single-character backspace

### 3. Imported Module Name Highlighting
- **Two distinct colors**: stdlib imports (teal `#4EC9B0`) vs third-party/project imports (purple `#C586C0`)
- Uses `sys.stdlib_module_names` (Python 3.10+) to classify; falls back to hardcoded list for 3.9
- Regex-based collection from `import X`, `from X import Y`, and `as` aliases
- Refreshes on same 500ms debounce as diagnostics; only rehighlights when name sets change
- Both colors customizable in **Settings > Appearance** as "Imports (stdlib)" and "Imports (packages)"
- Settings preview updated with `from maya.cmds import ls` to show both colors
- **Files changed**: `code_editor.py`, `color_scheme.py`, `settings_dialog.py`

### 4. Cross-Tab Diagnostic Suppression
- **Problem**: pyflakes flagged `os` as "undefined name" in Tab B even though it was imported in Tab A
- **Fix**: `editor_panel.py` provides a `_known_globals_provider` callback to each editor that collects imported names from all OTHER open Python tabs
- Also reads `py_forced_imports` setting (comma-separated names) as additional known globals
- `analyzer.py` accepts optional `known_globals` set and filters out matching "undefined name" diagnostics
- **Files changed**: `analyzer.py`, `code_editor.py`, `editor_panel.py`

### 5. Autocomplete — Missing Completions After Dot (All Adapters)
- **Root cause**: All four adapters (maya, internal_maya, blender, internal_blender) capped `dir()` results at `[:30]`
- When typing `os.` (dot, no letter yet), only the first 30 alphabetical items were cached — all uppercase constants (`CLD_*`, `F_OK`, `O_*`, `P_*`). Lowercase items like `path`, `pathsep`, `popen` were never fetched.
- Subsequent keystrokes filtered the cached 30-item list case-insensitively, giving wrong results
- **Fix**: Raised limit from 30 to 200 across all four adapters
- **Files changed**: `maya_adapter.py`, `internal_maya_adapter.py`, `blender_adapter.py`, `internal_blender_adapter.py`

### 6. Autocomplete — Module-Type Attributes Filtered
- **Problem**: `plugins.` showed `os`, `pm`, `mel` (the module's own imports) alongside real functions
- **Fix**: Added `types.ModuleType` isinstance check to all four adapters — attributes that are module objects are excluded from dot-completion results
- **Files changed**: Same four adapter files

### 7. Pricing Update
- Maya/UE perpetual: $99 → $49
- Maya/UE annual: $35 → $25
- Bundle perpetual: $140 → $75
- Bundle annual: $40 → $30
- Updated `pricing.md` and `index.md`, deployed to mcaeditor.com
- Gumroad updated separately by Nathan

---

## Build Status

| Platform | Version | Status |
|----------|---------|--------|
| Maya 2024 Windows | v1.0.9 | Rebuilt + deployed (hide_mel) |
| Maya 2025 Windows | v1.0.9 | Rebuilt + deployed (hide_mel) |
| Maya 2026 Windows | v1.0.9 | Rebuilt + deployed (hide_mel) |
| Maya 2024 macOS | v1.0.9 | Built + deployed |
| Maya 2025 macOS | v1.0.9 | Built + deployed |
| Maya 2026 macOS | v1.0.9 | Built + deployed |
| UE 5.5 Windows | v1.0.9 | Rebuilt (zip ready, hide_mel) |
| UE 5.6 Windows | v1.0.9 | Rebuilt + deployed to Wayward (hide_mel) |
| UE 5.7 Windows | v1.0.9 | Rebuilt (zip ready, hide_mel) |

---

### 8. Hide MEL from UE Settings Dialog
- **Problem**: Settings > Appearance showed MEL tokens, MEL page was accessible, and Maya-specific options (Script Editor override, PyMEL, echo suppress) were visible when running in Unreal Engine
- **Fix**: Added `hide_mel` parameter to `SettingsDialog.__init__()`. When True:
  - Removes "MEL" from the category list sidebar
  - Skips building the MEL settings page entirely
  - Removes MEL tokens from the Appearance color tree
  - Removes "MEL" from the Appearance preview language combo
  - Removes MEL items from Output highlight toggles
  - Hides "Replace Maya Script Editor", "Pre-import PyMEL", "Suppress Maya echo-all", "MEL variable prefix ($)", and "Maya introspection fallback" checkboxes
- `editor_panel.py:_show_settings()` detects MEL availability by checking if "MEL" is in the language combo (already stripped by `ue_editor_host.py:_strip_mel_from_ui()`)
- **Files changed**: `settings_dialog.py`, `editor_panel.py`

### 9. UE Deployment Fix
- **Problem**: v1.0.9 UE builds existed in `dist/` but were never copied to Wayward — deployed plugin still had v1.0.8 files (Apr 1 timestamps)
- **Fix**: Clean-deployed v1.0.9 Content/Python/ to Wayward and cleared runtime `__pycache__` dirs

---

## macOS Autocomplete Fix (Follow-up Session)

Three root causes identified and fixed for autocomplete not working on macOS:

### 1. Popup Invisible on macOS (`completer.py`)
- **Root cause**: The completer `QFrame` (ToolTip window type) is created during Maya startup before the macOS window system is fully initialized. The native NSWindow gets created in an unshowable state — `isVisible()` returns True but nothing renders on screen.
- **Fix**: On macOS, force native window recreation by re-setting window flags (`self.setWindowFlags(self.windowFlags())`) on first show. This destroys and recreates the NSWindow after the window system is ready. One-time cost via `_mac_native_ready` flag.
- **Diagnosis method**: Monkey-patched `_show_items` to trace visibility — confirmed `isVisible=True`, correct geometry, opacity 1.0, but user couldn't see it. Created a fresh `QFrame` with identical flags — it was visible. Proved the issue was creation timing, not flags.

### 2. `os.path` Missing from Completions (`internal_maya_adapter.py`, `maya_adapter.py`, `completer.py`)
- **Root cause**: Two compounding issues:
  - The v1.0.9 module-type filter (`isinstance(val, types.ModuleType)`) removed ALL module attributes including legitimate sub-modules like `os.path`
  - The `[:200]` result limit cut off `os.path` which sits at index 208 in `dir(os)` — `os` has 297+ public attributes
- **Fix**: Changed module filter to only remove re-exported top-level modules: `isinstance(..., ModuleType) and x in sys.modules`. This keeps `os.path` (not in `sys.modules` as `"path"`) while filtering `os.sys` and `os.abc`. Raised result limit from 200 to 500 across all adapters.

### 3. `Ctrl+Space` Manual Trigger on macOS (`code_editor.py`)
- **Root cause**: Qt on macOS maps `ControlModifier` to the Command key (⌘), not physical Ctrl (⌃). `Command+Space` is captured by Spotlight and never reaches the app.
- **Fix**: On `sys.platform == "darwin"`, also accept `MetaModifier` (physical Ctrl) for the Ctrl+Space shortcut.

### 4. focusOutEvent Race Condition (`code_editor.py`)
- Showing a ToolTip-type window on macOS can trigger a transient `focusOutEvent` on the editor. The old code dismissed the completer immediately, causing the popup to appear and vanish in the same frame.
- **Fix**: Deferred dismiss with `QTimer.singleShot(0, ...)` — only dismisses if the editor truly lost focus after the event loop settles.

### 5. Module Import Fallback for Dot-Completion (`internal_maya_adapter.py`, `completer.py`)
- `eval("os", __main__.__dict__)` fails if the user typed `import os` but hasn't executed it yet.
- **Fix**: Fall back to `__import__()` when eval fails, so dot-completion works for any importable module even before execution.

### 6. Cross-Tab Imported Names in Autocomplete (`completer.py`)
- The `_known_globals_provider` (cross-tab imports) only fed pyflakes diagnostics, not completions.
- **Fix**: Completer now passes cross-tab names to the provider as "cross-tab" priority completions.

### 7. Stale Extraction Cache
- Maya's single-file plugin extracts to `~/Library/Caches/MCAEditor-MayaXXXX-pyX.XX/`. The cache must be cleared when deploying new builds, otherwise Maya runs stale compiled code even after restarting.
- **Action**: Cleared caches manually. The version+hash stamp system should handle this automatically, but cache dirs should be verified after deployment.

---

## Windows Follow-up Session (2026-04-02 evening)

### 10. Chat Panel Empty Space Fix (`chat_widget.py`)
- **Problem**: Massive empty vertical gaps between messages in the AI chat panel, especially visible in UE
- **Root cause**: QLabel with `setWordWrap(True)` + RichText inside nested layouts in a QScrollArea — `sizeHint()` returns height for the preferred (non-wrapped) text width, but the chat panel is narrow. Layout allocates inflated height, creating gaps.
- **Fix**: Created `_WrappingLabel(QLabel)` subclass that overrides `sizeHint()` to use `heightForWidth(actualWidth)` and calls `updateGeometry()` on resize. Propagated `heightForWidth(True)` on size policies of intermediate containers (content widget, bubble frame, MessageBubble). Replaced `adjustSize()` with `updateGeometry()` in streaming token handler.
- **Files changed**: `mca_core/plugins/ai_chat/chat_widget.py`

### 11. Windows Autocomplete + macOS Fixes Merged
- Pulled macOS autocomplete fixes to Windows and rebuilt all Maya + UE versions
- Key fixes applied: `sys.modules` module filter (keeps `os.path`), limit 200→500, `__import__()` fallback, cross-tab completions in autocomplete, focusOut race condition fix

### 12. Hide MEL from UE Settings Dialog (continued)
- `settings_dialog.py` and `editor_panel.py` changes deployed with UE rebuild

---

## Build Status (Updated)

| Platform | Version | Status |
|----------|---------|--------|
| Maya 2024 Windows | v1.0.9 | **Rebuilt + deployed (autocomplete + chat fix)** |
| Maya 2025 Windows | v1.0.9 | **Rebuilt + deployed (autocomplete + chat fix)** |
| Maya 2026 Windows | v1.0.9 | **Rebuilt + deployed (autocomplete + chat fix)** |
| Maya 2024 macOS | v1.0.9 | Rebuilt + deployed (autocomplete fixed) |
| Maya 2025 macOS | v1.0.9 | Rebuilt + deployed (autocomplete fixed) |
| Maya 2026 macOS | v1.0.9 | Rebuilt + deployed (autocomplete fixed) |
| UE 5.5 Windows | v1.0.9 | **Rebuilt (zip ready, autocomplete + chat fix)** |
| UE 5.6 Windows | v1.0.9 | **Rebuilt + deployed to Wayward** |
| UE 5.7 Windows | v1.0.9 | **Rebuilt (zip ready, autocomplete + chat fix)** |

---

## Known Issues
- **REGRESSION**: Maya Windows — editor re-indexes every time you close and reopen, bogging down Maya. Needs investigation.
- Website not redeployed with v1.0.9 download zips yet — waiting on testing

---

## Files Modified (original session)
- `mca_core/__init__.py` — version bump 1.0.8 → 1.0.9
- `mca_core/analyzer.py` — `known_globals` parameter for cross-tab suppression
- `mca_core/config/color_scheme.py` — `imported_stdlib` + `imported_user` tokens
- `mca_core/adapters/maya_adapter.py` — autocomplete limit + module filter
- `mca_core/adapters/internal_maya_adapter.py` — autocomplete limit + module filter
- `mca_core/adapters/blender_adapter.py` — autocomplete limit + module filter
- `mca_core/adapters/internal_blender_adapter.py` — autocomplete limit + module filter
- `mca_qt/widgets/code_editor.py` — smart home, smart backspace, imported name highlighting
- `mca_qt/editor_panel.py` — `_collect_known_globals()` + provider wiring + `hide_mel` detection
- `mca_qt/widgets/settings_dialog.py` — preview update, imported names, `hide_mel` support
- `website/docs/pricing.md` — new pricing
- `website/docs/index.md` — new pricing on homepage buttons

## Files Modified (macOS autocomplete fix session)
- `mca_qt/widgets/completer.py` — macOS native window fix, cross-tab completions, module import fallback, limit 200→500
- `mca_qt/widgets/code_editor.py` — deferred focusOut dismiss, Ctrl+Space macOS fix
- `mca_core/adapters/internal_maya_adapter.py` — __import__ fallback, sys.modules filter, limit 200→500
- `mca_core/adapters/maya_adapter.py` — __import__ fallback, sys.modules filter, limit 200→500
- `mca_core/adapters/blender_adapter.py` — limit 200→500
- `mca_core/adapters/internal_blender_adapter.py` — limit 200→500

## Files Modified (Windows follow-up session)
- `mca_core/plugins/ai_chat/chat_widget.py` — `_WrappingLabel` fix for empty space in chat panel
- `mca_qt/editor_panel.py` — hide_mel detection for UE settings
- `mca_qt/widgets/settings_dialog.py` — hide_mel parameter support
- `mca_unreal/Content/Python/ue_editor_host.py` — UE host updates
- `CHANGELOG.md` — updated
