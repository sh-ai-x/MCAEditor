# 2026-03-19 — Unreal Engine Native Plugin Implementation

## Summary
Implemented the full MCA Editor Unreal Engine plugin — a C++ Slate-based code editor
that docks natively in the UE editor, plus a standalone MCP server for Claude Code
integration. This is Phase 0-1 of the plan, covering the entire directory structure,
all C++ headers/implementations, the remote execution spike, and 24 MCP tool files.

## Phase 0: Remote Execution Spike

### New Files
- **`tools/ue_remote_exec_spike.py`** — Standalone Python script to validate UE's
  Remote Execution protocol before writing any C++. Tests UDP multicast discovery
  (239.0.0.1:6766), TCP code execution, print() output capture, expression evaluation,
  error/traceback format, stdout-redirect wrapper fallback, and latency measurement.
  This spike gates all subsequent work — its findings determine whether PythonBridge.cpp
  needs a stdout wrapper or can use the protocol directly.

## Unreal C++ Plugin (28 files)

### Plugin Root
- **`mca_unreal/MCAEditor.uplugin`** — Plugin descriptor, PostEngineInit loading phase,
  soft dependency on PythonScriptPlugin, Editor-only module.

### Build System
- **`MCAEditor.Build.cs`** — UBT module rules with dependencies: Core, Slate, SlateCore,
  UnrealEd, ToolMenus, DirectoryWatcher, EditorSubsystem.

### Core Module Files
- **`MCAEditorModule.h/.cpp`** — Plugin entry point. Registers nomad tab spawner
  ("MCAEditor"), toolbar button, Window menu entry. License check stub (TODO) at
  tab spawn gate. Mirrors `plugin_main.py` from Maya version.
- **`MCAEditorCommands.h/.cpp`** — 9 UI commands: OpenMCAEditor, ExecuteCode (Shift+Enter),
  SaveFile (Ctrl+S), OpenFile (Ctrl+O), NewFile (Ctrl+N), FindReplace (Ctrl+F),
  QuickOpen (Ctrl+P), GoToLine (Ctrl+G), ToggleComment (Ctrl+/).
- **`MCAEditorStyle.h/.cpp`** — 16 color constants ported from `mca_qt/theme.py`
  (#1E1E1E background, #D4D4D4 text, #569CD6 keywords, etc.). Syntax highlight
  text styles, output severity styles, line number style. Singleton pattern.
- **`MCAEditorSettings.h/.cpp`** — `UDeveloperSettings` subclass in Project Settings >
  Plugins > MCA Editor. Settings: FontFamily, FontSize, TabSize, bUseSpaces,
  bShowLineNumbers, bWordWrap, bAutoSaveOnExecute, RemoteExecutionPort.
- **`PythonBridge.h/.cpp`** — In-process Python execution via `IPythonScriptPlugin`.
  Output capture via custom `FMCAOutputDevice` (registered with GLog). Broadcast
  delegate `OnPythonOutput` for UI binding. Remote execution stub for future TCP
  protocol. `WrapCodeIfNeeded()` placeholder for stdout redirect (informed by spike).

### Widget Files (8 widgets, 16 files)
- **`SMCAEditorPanel`** — Main container. SSplitter layout: sidebar | (tabs + code editor
  + output) | tool stripe. Toolbar (Execute/Save/Open/New), status bar (cursor pos,
  language, encoding). Creates FPythonBridge, wires output delegate to panel.
- **`SMCACodeEditor`** — `SMultiLineEditableTextBox` with `FMCAPythonSyntaxMarshaller`.
  Marshaller has Python keyword/builtin sets (35 keywords, 25 builtins). Phase 1
  renders in default style; Phase 2 will add per-token tokenization. Text access,
  selection, execute text (selection or all), modified tracking.
- **`SMCAOutputPanel`** — `SRichTextBlock` in `SScrollBox`. AppendOutput() with severity
  color coding. Clear/Copy buttons, timestamp toggle, auto-scroll.
- **`SMCASidebar`** — `STreeView<FMCAFileItem>` with `FDirectoryWatcher`. Recursive
  scanning, hidden/`__pycache__` filtering, double-click to open file.
- **`SMCATabBar`** — Dynamic `SHorizontalBox` tab buttons. Modified indicator (*),
  close button (x), add button (+). FindTabByPath deduplication.
- **`SMCAFindReplace`** — Overlay bar. SEditableTextBox for search/replace. Regex,
  case-sensitive, whole-word toggles. Match count display ("N of M"). Starts collapsed.
- **`SMCAQuickOpen`** — Fuzzy file search popup. Recursive file index, scoring with
  consecutive/boundary bonuses, shorter-name preference. Escape/Enter/arrow keys.
- **`SMCAToolStripe`** — Vertical button bar (32px wide). Toggle behavior. Default
  buttons: Terminal, AI Chat.

## MCP Server

### New Files
- **`mca_core/mcp_unreal_server.py`** — Standalone MCP server (700+ lines). Uses UE
  Remote Execution TCP protocol instead of Maya's base64 commandPort. Identical
  architecture to `mcp_maya_server.py`:
  - `UnrealConnection` class with `_build_ue_message()`/`_parse_ue_message()` for
    the UE wire format (5-byte magic "ue_py" + version + payload size + JSON)
  - `OperationsManager` for tool discovery (walks directories, loads modules,
    builds JSON schemas from function signatures)
  - `wrap_script_in_scoped_function()` wrapping tool source in `_mcp_ue_scope()`
  - `_serialize_arg()` for safe argument embedding (repr/json.dumps)
  - `@server.list_tools()` and `@server.call_tool()` handlers
  - CLI entry point with `--port` and `--tool-dir` args
  - Two-phase timeout recv (30s first, 0.5s idle)

### MCP Tool Files (24 tools in 7 categories)
All tools follow the proven pattern: single function per file, filename = function name,
`import unreal` inside function body (runs in UE's interpreter, not MCP server).

- **Level (4):** `level_new`, `level_open`, `level_save`, `get_level_info`
- **Actor (7):** `create_actor`, `delete_actors`, `select_actors`, `get_selected_actors`,
  `get_actor_properties`, `set_actor_transform`, `set_actor_property`
- **Asset (3):** `list_assets`, `import_asset`, `get_asset_info`
- **Material (3):** `create_material`, `set_material_parameter`, `assign_material`
- **Viewport (3):** `viewport_focus`, `set_viewport_camera`, `take_screenshot`
- **Execution (2):** `execute_python`, `get_python_output`
- **Project (2):** `get_project_info`, `list_objects_by_type`

## Modified Files

### `mca_core/mcp_setup.py`
- Added `_UNREAL_MCP_SERVER_NAME = "MCAUnrealMCP"` and deploy path constants
- Added `_UNREAL_TOOLS_SOURCE_DIR` / `_UNREAL_TOOLS_DEPLOY_DIR` constants
- Added `ensure_unreal_mcp(background, status_callback)` — public API entry point
- Added `_run_unreal_setup()` — deploys server script + tool files, ensures shared
  venv (reuses MayaMCP's), registers with Claude Code. No git clone needed.
- Added `"unreal"` sub-dict to `get_mcp_server_status()` return value
- **All Maya/Editor paths completely untouched** — purely additive changes

## Key Design Decisions
- UE plugin is C++ (Slate UI, UBT build) while Maya version is Python (PySide6, Cython).
  UI code cannot be shared, but architectural patterns and MCP infrastructure are reused.
- Remote Execution protocol (UDP discovery + TCP execution) instead of Maya's commandPort.
  The spike must validate this before Phase 1 C++ work proceeds.
- MCP server reuses the same venv as Maya MCP (both just need the `mcp` pip package).
- Tool files use `import unreal` inside the function body — this runs inside UE's
  Python interpreter, not in the MCP server process.
- License check is a stub (TODO comment) — will be implemented before any public release.

## File Count
- **54 new files** created (28 C++, 24 Python tools, 1 MCP server, 1 spike script)
- **1 file modified** (mcp_setup.py — additive only)
- **0 existing files broken** — entirely additive to the repo

## Next Steps
1. Run spike against UE 5.4 to validate communication strategy
2. Copy `mca_unreal/` to a UE project's Plugins/ and compile with UBT
3. Use spike findings to finalize PythonBridge.cpp stdout capture approach
4. Phase 2: Syntax highlighting tokenizer, line numbers, tab system polish
