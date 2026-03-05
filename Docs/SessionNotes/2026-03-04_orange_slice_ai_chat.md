# Session Notes — 2026-03-04: Orange Slice AI Chat Plugin

## Goal
Implement Phase 2 of the plugin system — the "Orange Slice" AI chat plugin.
A bundled plugin providing an AI assistant panel in the right sidebar with
Claude/OpenAI/Gemini support, streaming responses, tool use, and Orange Slice
branding.

## What Was Done

### 1. Plugin Infrastructure (8 new files in `mca_core/plugins/ai_chat/`)

- **`provider.py`** — Provider configs + client factory. Uses single `openai`
  SDK with different `base_url` for Anthropic, OpenAI, and Gemini. Lazy import
  so the plugin can be discovered before venv is ready.
- **`tools.py`** — 16 OpenAI function-calling tool schemas organized by
  category: state (get_editor_state, list_open_files, get_output), read
  (get_editor_text, get_selected_text, read_disk_file), write (set_editor_text,
  insert_text, replace_range, write_disk_file, save_file), navigate (open_file,
  navigate_to), execute (execute_in_dcc, execute_locally), output (write_output).
- **`tool_handler.py`** — Dispatch function that calls the appropriate
  MCAPluginAPI method. Runs on main thread (safe for EditorAPI).
- **`system_prompt.py`** — Context-aware prompt builder. Injects DCC type/
  version, active file, cursor position, project info, open tabs.
- **`chat_worker.py`** — `ChatWorker(QThread)` for streaming API calls off
  main thread. Tool execution on main thread via signal-slot marshaling with
  60-second timeout. Ships as `.pyc` (QThread.run virtual override).
- **`chat_widget.py`** — Main chat panel UI: header with logo + gear button,
  welcome screen with suggestion chips, message area with code block detection,
  input area (Enter sends, Shift+Enter newline), settings overlay (provider/
  key/model). Ships as `.pyc` (keyPressEvent override).
- **`__init__.py`** — `AIChatPlugin(MCAPlugin)` entry point. Registers panel
  `"ai-chat"` and menu actions under "Plugins > Orange Slice".
- **`plugin.json`** — Plugin manifest (`com.mechart.ai-chat`).

### 2. Dependency & Settings Changes

- **`mca_core/venv_manager.py`** — Added `"openai>=1.30.0": "openai"` to
  `REQUIRED_PACKAGES`.
- **`mca_core/config/settings.py`** — Updated `ai_provider` comment to reflect
  new provider IDs: `none`, `anthropic`, `openai`, `gemini`.

### 3. Build Pipeline Updates

- **`build_maya.py`** — Added `chat_widget.py` and `chat_worker.py` to
  `DIST_PYC_FILES`.
- **`setup.py`** — Added both files to `exclude_from_compilation`.

### 4. Bug Fixes

#### Anthropic 404 Error
- **Cause**: Default model `claude-sonnet-4-5-20250514` was outdated/invalid.
  Also had unnecessary `anthropic-version` header (only for native API).
- **Fix**: Updated default model to `claude-sonnet-4-6`, removed extra header.
  The OAI-compat endpoint handles auth via standard Authorization header.

#### QMenu GC Crash
- **Cause**: Plugin submenu returned by `addMenu()` was garbage collected
  between two `_register_plugin_menu_action` calls — `Internal C++ object
  (PySide6.QtWidgets.QMenu) already deleted`.
- **Fix**: Added `self._plugin_submenus = {}` dict in `editor_panel.py` to
  hold Python references to plugin submenus.

#### Copy Fails on First Click (Output Panel)
- **Cause**: `focusWidget()` returns wrong widget (or None) on first click
  into editor from Maya because `activateWindow()` is async on Win11.
  Phase 2 of the hotkey filter was dispatching Ctrl+C to the wrong widget.
- **Fix**: Phase 0 now stores `_focus_forced_widget` (the widget we set focus
  on). Phase 2 falls back to it when `focusWidget()` is outside our editor
  tree. Additionally, standard text editing shortcuts (Ctrl+C/V/X/A/Z/Y,
  Ctrl+Shift+Z) now call the widget method directly (`copy()`, `paste()`,
  etc.) instead of routing through `keyPressEvent()`.

## Version
Bumped from 0.1.6 to 0.1.7.

## Files Changed
| Action | File |
|--------|------|
| NEW | `mca_core/plugins/ai_chat/__init__.py` |
| NEW | `mca_core/plugins/ai_chat/plugin.json` |
| NEW | `mca_core/plugins/ai_chat/provider.py` |
| NEW | `mca_core/plugins/ai_chat/tools.py` |
| NEW | `mca_core/plugins/ai_chat/tool_handler.py` |
| NEW | `mca_core/plugins/ai_chat/system_prompt.py` |
| NEW | `mca_core/plugins/ai_chat/chat_worker.py` |
| NEW | `mca_core/plugins/ai_chat/chat_widget.py` |
| EDIT | `mca_core/__init__.py` (version bump) |
| EDIT | `mca_core/venv_manager.py` (openai dep) |
| EDIT | `mca_core/config/settings.py` (provider IDs) |
| EDIT | `mca_qt/editor_panel.py` (submenu GC fix) |
| EDIT | `mca_maya/maya_window.py` (copy fix) |
| EDIT | `build_maya.py` (PYC list) |
| EDIT | `setup.py` (exclusion list) |

## Verification
- Orange Slice panel appears in right sidebar with branding
- Anthropic provider connects and streams responses
- Tool use works (list_open_files, get_editor_text, execute_in_dcc)
- Copy works on first click in the output panel
- API key and provider persist across editor restarts
