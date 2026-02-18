# Session: Restructure MCA Editor as Embeddable Maya Plugin
**Date:** 2026-02-17

## Summary
Completed the full 5-phase restructuring plan to convert MCA Editor from a standalone app into an embeddable Maya plugin architecture.

## Phase 1: mca_core (pure Python, zero Qt)
- Created `mca_core/` package with adapters, config, and version metadata
- Moved `base_adapter.py`, `maya_adapter.py`, `adapter_manager.py`, `settings.py`
- Created `InternalMayaAdapter` — direct `maya.cmds`/`maya.mel.eval()` calls (no TCP)
- Added `register_builtin` flag to `AdapterManager` to suppress TCP adapter inside Maya
- Added `register_adapter_instance()` for pre-instantiated adapter registration
- Abstracted `MCASettings` with dict-backend fallback (for non-Qt environments)
- Added re-export stubs in `mca_editor/` for backward compatibility

## Phase 2: mca_qt (shared Qt widget layer)
- Created `qt_compat.py` — PySide2/6 compatibility shim with scoped enum patching
- Created `theme.py` — extracted dark palette and stylesheet from main.py
- Moved all widget files to `mca_qt/widgets/`, updated imports to use `qt_compat`
- Updated `mca_editor/ui/__init__.py` to re-export from `mca_qt.widgets`

## Phase 3: Extract MCAEditorPanel
- Extracted `ConnectionDialog` into `mca_qt/widgets/connection_dialog.py`
- Created `MCAEditorPanel(QWidget)` in `mca_qt/editor_panel.py` — embeddable core
  - Added signals: `status_message`, `cursor_position_changed`, `language_changed`, `mode_changed`
  - Added `build_menus(menubar)` API for host menu bar population
  - Added `set_status_callback()`, `check_unsaved_changes()`, `save_window_state()`, `cleanup()`
  - Guarded menu-dependent action references for safe init before menus exist
- Created `mca_standalone/` package:
  - `standalone_window.py` — QMainWindow wrapping MCAEditorPanel
  - `main.py` — app bootstrap using `mca_qt.theme`
- Updated `run.py` to use `mca_standalone.main`

## Phase 4: mca_maya plugin
- Created `mca_maya/plugin_main.py`:
  - `initializePlugin`/`uninitializePlugin` with Maya API 2.0
  - Registered `mcaEditor` command
  - Overrides `ScriptEditor` MEL procedure to open MCA Editor
- Created `mca_maya/maya_window.py`:
  - `MCAMayaWindow(MayaQWidgetDockableMixin, QWidget)` — dockable in Maya
  - Pre-connects `InternalMayaAdapter` (no TCP, direct execution)
  - `uiScript` pattern for workspace control persistence
  - `show_mca_editor()` public entry point
- Created `mca_maya/install.py`:
  - Detects Maya versions (found 2022, 2024, 2025 on this machine)
  - Creates `.mod` file and plugin stubs in Maya's directories
  - `uninstall()` for clean removal

## Phase 5: Build system
- Created `pyproject.toml` — pip-installable with CLI entry points:
  - `mcaeditor` → standalone launcher
  - `mcaeditor-install-maya` → Maya installer
- Created `setup.py` — Cython build script for `.pyd` compilation
  - 19 source files identified for compilation
  - Skips `__init__.py` (needed for package discovery)

## New Package Structure
```
mca_core/          — Pure Python, zero Qt (adapters, config)
mca_qt/            — Shared Qt widgets (PySide2/6 compatible)
  editor_panel.py  — Core embeddable QWidget
  qt_compat.py     — PySide2/6 shim
  theme.py         — Dark palette + stylesheet
  widgets/         — All reusable UI widgets
mca_standalone/    — Standalone app shell (QMainWindow)
mca_maya/          — Maya plugin (dockable, ScriptEditor override)
mca_editor/        — Backward-compat re-export stubs
```

## Maya Testing & Bug Fixes

Tested the plugin live inside Maya 2025 (Python 3.11, PySide6). Multiple
rounds of debugging to get the editor working natively.

### Workspace control "name not unique" error
- `WINDOW_OBJECT_NAME` was "MCAEditorWindow" but Maya derives the control
  name by appending "WorkspaceControl" — renamed to "MCAEditor" so the
  control becomes "MCAEditorWorkspaceControl"
- Added stale workspace control deletion in `show_mca_editor()` before
  creating a new one

### Maya hotkey interception (multiple iterations)
- **Problem**: Maya hotkeys (S=SetKey, W=Move, Ctrl+D=Duplicate) fire
  while typing in the editor
- **Attempt 1**: `ShortcutOverride` acceptance — worked for plain keys
  but not for Ctrl+D (Maya's hotkey system bypasses Qt shortcuts)
- **Attempt 2**: `WidgetWithChildrenShortcut` context on actions — Maya
  still won because it intercepts events before Qt's shortcut matching
- **Final solution**: Two-phase interception in `_MayaHotkeyFilter`:
  1. Accept ALL `ShortcutOverride` events when editor has focus (completely
     blocks Maya's hotkey system)
  2. For `KeyPress` events with Ctrl/Alt/Meta modifiers, match against
     the panel's `_action_registry` and trigger manually
  3. Unmatched modifier combos are forwarded directly to the widget's
     `keyPressEvent` (so Ctrl+Z/C/V/X/A still work) then consumed to
     prevent propagation to Maya
  - Plain keys pass through to the text editor normally for typing

### QAction GC crash
- `menu.addAction("text")` parents actions to the menu — PySide6 GC
  deletes the C++ object when the menu is rebuilt
- Created `_create_action()` helper that parents all actions to the panel
  with `QAction(text, self)`, adds to both menu and panel's action list
- Converted all 79 action creations across 8 `_build_*_menu` methods

### Maya session history / startup logs
- **Problem**: Output window was empty on open — no startup logs
- **Attempt 1**: `scriptEditorInfo(q=True, historyFilename=True)` to read
  history file — file didn't exist or was empty
- **Final solution**: Create a temporary `cmdScrollFieldReporter` (the same
  widget Maya's Script Editor uses internally). When created, it auto-
  populates with the full session output buffer. Read its text, display
  in our output window, then delete the temporary widget.

### Layout issue
- Gray space between menu bar and editor content
- Fixed with stretch factors: `addWidget(menubar, 0)` and
  `addWidget(panel, 1)`

### PySide6 import issues inside Maya
- Maya's stale module cache didn't pick up new qt_compat exports after
  reload — imported QObject/QEvent/QApplication directly from PySide6
  in `maya_window.py` instead of through qt_compat
- Added `isinstance(focus, _QWidget)` guard in event filter since app-level
  filters see QWindow objects that aren't QWidgets

### Maya output hook
- Installed `MCommandMessage.addCommandOutputCallback` to capture all
  live Maya output (warnings, errors, results, info) and route to our
  output window by message type
- Removed on `dockCloseEventTriggered` to prevent stale callbacks

## Verification
- `python run.py` launches successfully via `mca_standalone.main`
- Old `mca_editor.main` import still works (backward compat)
- All 13 packages discovered by setuptools
- Maya installer detects versions 2022, 2024, 2025
- No errors on startup
- Maya plugin loads and docks correctly in Maya 2025
- All startup/session logs appear in output window on open
- Editor hotkeys (Ctrl+D, etc.) work without triggering Maya commands
- Plain typing (S, W, D, etc.) stays in the editor, doesn't trigger Maya hotkeys
- Unregistered modifier combos are consumed (don't leak to Maya)
- Built-in text editing (Ctrl+Z, Ctrl+C, Ctrl+V) still works
