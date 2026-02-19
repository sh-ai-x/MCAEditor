# Session: 2026-02-19 — Real-Time Diagnostics, Icons, and Settings Polish

## Summary
Added live code analysis with inline error markers (gutter dots, wavy underlines, hover tooltips), replaced programmatic Python icon with a real PNG logo, differentiated the settings dialog from its Charcoal Editor 2 origins, and various UI polish.

## Changes Made

### New File: `mca_core/analyzer.py`
Pure-Python code analysis engine with two tiers:
- **Tier 1** — `compile()` catches SyntaxError, IndentationError, TabError. Always available, zero dependencies.
- **Tier 2** — `pyflakes` for unused imports, undefined names, etc. Gracefully skipped if not installed.
- Returns standardized diagnostic dicts: `{line, col, end_col, severity, message}`.
- Custom `_DiagnosticReporter` class collects pyflakes messages programmatically.

### Modified: `mca_qt/widgets/code_editor.py`
- Added `QTimer`, `QEvent`, `QToolTip` imports.
- New `_diagnostics` and `_diagnostic_lines` attributes for storing analysis results.
- 500ms debounced `_analysis_timer` connected to `textChanged` — prevents CPU burn during rapid typing.
- `set_diagnostics()` — stores diagnostics, builds per-line severity lookup, triggers visual refresh.
- `_build_diagnostic_selections()` — creates wavy underline `ExtraSelection` items (red for errors, yellow for warnings). Uses column info when available, falls back to underlining full line text.
- `_run_analysis()` — runs analyzer for Python, clears diagnostics for other languages.
- `event()` override — intercepts `QEvent.Type.ToolTip` to show diagnostic messages on hover.
- `paint_line_numbers()` — draws anti-aliased colored gutter dots (10px, red/yellow) next to diagnostic lines.

### Modified: `mca_qt/qt_compat.py`
- Added `QToolTip` to both PySide6 and PySide2 import blocks.
- Added PySide2 enum patches for: `Qt.PenStyle`, `QTextCharFormat.UnderlineStyle`, `QEvent.Type`, `QPainter.RenderHint`, `Qt.AspectRatioMode`, `Qt.TransformationMode`.

### Modified: `mca_qt/editor_panel.py`
- `_on_language_changed()` — calls `editor._run_analysis()` when language switches.
- `build_menus()` — conditionally skips DCC menu when embedded inside Maya.
- `_setup_toolbar()` — hides DCC indicator when embedded.
- New `_embedded_in_dcc` flag: True when adapter_manager is provided (Maya), False for standalone.
- Default shortcut for Copy Line Down changed from Alt+Shift+Down to Ctrl+D.

### Modified: `mca_qt/icons.py`
- Added `os` import and `_RESOURCES_DIR` constant for image asset loading.
- `python_logo()` now loads `resources/images/python_logo.png` instead of painting a simplified icon. Falls back to a colored square if the PNG is missing.

### Modified: `mca_qt/widgets/sidebar.py`
- Imported `python_logo`, `maya_logo`, `text_icon` from `mca_qt.icons`.
- `OpenEditorsPanel.update_editors()` — replaced text labels (`[Py]`, `[MEL]`, `[?]`) with actual language icons from the icon module.

### Modified: `mca_qt/widgets/settings_dialog.py`
Differentiated from Charcoal Editor 2's settings layout:
- **Category renames**: Tabs and Spacing -> Indentation, Fonts and Colors -> Appearance, Code Editor -> Editor Behavior, Pylint -> Code Analysis.
- **Alphabetical ordering**: General stays first, rest sorted A-Z.
- **Group box renames**: Main Window -> Startup and Saving, Tab Bar -> Tabs, Buffer Size -> Output History, Auto-Complete -> Completion Triggers, etc.
- **Checkbox label rewording**: all reworded to feel more natural (e.g. "Save all on execute" -> "Auto-save before execution", "Insert closing bracket" -> "Auto-close brackets").
- Unlocked the Assigned Shortcut combo box in the Keyboard page (was disabled).

## Decisions
- Analysis runs on main thread — both `compile()` and `pyflakes` are fast enough (<100ms) that the 500ms debounce prevents any UI jank.
- Pyflakes is optional (not in requirements) — Tier 1 syntax checking always works.
- DCC controls hidden when embedded in Maya (already has direct access), shown in standalone (needs TCP connection).
- Gutter dots are 10px anti-aliased circles to match Charcoal Editor's visual style.

## Known Issues / Future Work
- Pyflakes not currently installed — Tier 2 analysis is silently disabled.
- The `pylint_enabled` setting exists but is not yet wired to control the built-in analysis.
- Color theme customization in Appearance page is not yet functional (UI exists but doesn't apply changes).
