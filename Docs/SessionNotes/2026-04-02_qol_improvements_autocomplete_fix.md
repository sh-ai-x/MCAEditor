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
| Maya 2024 Windows | v1.0.9 | Built + deployed |
| Maya 2025 Windows | v1.0.9 | Built + deployed |
| Maya 2026 Windows | v1.0.9 | Built + deployed |
| Maya 2024 macOS | v1.0.9 | Built + deployed |
| Maya 2025 macOS | v1.0.9 | Built + deployed |
| Maya 2026 macOS | v1.0.9 | Built + deployed |
| UE 5.5 Windows | v1.0.9 | Built (zip ready) |
| UE 5.6 Windows | v1.0.9 | Built + deployed to Wayward |
| UE 5.7 Windows | v1.0.9 | Built (zip ready) |

---

## Known Issues
- **macOS autocomplete not working** — reported by Nathan, being investigated on the Mac Mini separately
- Website not redeployed with v1.0.9 download zips yet — waiting on Mac/UE testing

---

## Files Modified (12 files)
- `mca_core/__init__.py` — version bump 1.0.8 → 1.0.9
- `mca_core/analyzer.py` — `known_globals` parameter for cross-tab suppression
- `mca_core/config/color_scheme.py` — `imported_stdlib` + `imported_user` tokens
- `mca_core/adapters/maya_adapter.py` — autocomplete limit + module filter
- `mca_core/adapters/internal_maya_adapter.py` — autocomplete limit + module filter
- `mca_core/adapters/blender_adapter.py` — autocomplete limit + module filter
- `mca_core/adapters/internal_blender_adapter.py` — autocomplete limit + module filter
- `mca_qt/widgets/code_editor.py` — smart home, smart backspace, imported name highlighting
- `mca_qt/editor_panel.py` — `_collect_known_globals()` + provider wiring
- `mca_qt/widgets/settings_dialog.py` — preview update for imported names
- `website/docs/pricing.md` — new pricing
- `website/docs/index.md` — new pricing on homepage buttons
