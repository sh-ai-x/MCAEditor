# Session Notes — 2026-03-25: UE MCP Tools (Python, Blueprints, Control Rig)

## Summary

Added 27 new MCP tools to the Unreal Engine plugin, covering three major UE
workflows: Python API introspection, Blueprint management, and Control Rig
hierarchy operations. These are auto-discovered by the existing
`mcp_unreal_server.py` — no server, setup, or build script changes needed.

## Architecture

All tools follow the established pattern:
- One function per file, name matches filename
- `import unreal` inside the function body (not at module level)
- Return `{"success": bool, ...}` dict
- Write tools wrap mutations in `unreal.ScopedEditorTransaction()` for Ctrl+Z undo
- List outputs capped at 100 items with `total_count`
- Filter params on listing tools from the start

Auto-discovery via `OperationsManager.find_tools()` uses `os.walk()` on the
`unreal_tools/` directory, so new subdirectories are picked up automatically.

## New Tools (27 total)

### Phase 1: Python Introspection (`unreal_tools/python/`, 6 tools)

| Tool | Purpose |
|------|---------|
| `inspect_class` | Inspect a UE class — properties, methods, parent chain |
| `search_api` | Search `unreal` module for functions/classes by keyword |
| `list_enums` | List UE enums and their valid values |
| `get_class_hierarchy` | Get full MRO inheritance chain of a UE class |
| `list_modules` | List importable Python modules (pre-filtered, no engine noise) |
| `get_subsystem` | Inspect editor/engine/game-instance subsystem methods |

### Phase 2: Blueprint Read Tools (`unreal_tools/blueprint/`, 7 tools)

| Tool | Purpose |
|------|---------|
| `list_blueprints` | List Blueprint assets with path/type/name filters |
| `get_blueprint_info` | Full BP overview: type, parent, components, variables, functions |
| `list_blueprint_variables` | All user-defined variables with types and defaults |
| `list_blueprint_functions` | User-defined functions with input/output signatures |
| `list_blueprint_components` | Component hierarchy from SimpleConstructionScript |
| `get_class_defaults` | CDO property values (Class Defaults panel) |
| `list_blueprint_events` | Enumerate event nodes (BeginPlay, Tick, dispatchers, etc.) |

### Phase 3: Blueprint Write Tools (`unreal_tools/blueprint/`, 5 tools)

| Tool | Purpose |
|------|---------|
| `create_blueprint` | Create new BP with specified parent class |
| `set_blueprint_variable` | Add/modify a variable (type, default, category) |
| `add_blueprint_component` | Add component to SCS hierarchy |
| `set_class_default` | Set a CDO property value |
| `compile_blueprint` | Compile BP, report success/errors |

### Phase 4: Control Rig Read Tools (`unreal_tools/control_rig/`, 5 tools)

| Tool | Purpose |
|------|---------|
| `list_control_rigs` | Find Control Rig assets under a content path |
| `get_control_rig_info` | Overview: controls, bones, nulls, hierarchy |
| `list_controls` | All controls with transforms and hierarchy |
| `list_bones` | All bones with transforms and parent-child relationships |
| `get_control_transform` | Get initial/local/global transform of a control |

### Phase 5: Control Rig Write Tools (`unreal_tools/control_rig/`, 4 tools)

| Tool | Purpose |
|------|---------|
| `set_control_transform` | Set initial transform of a control |
| `add_control` | Add new control via RigHierarchyController |
| `add_null` | Add null/space/group to hierarchy |
| `set_control_shape` | Set visual shape and color of a control |

## Hard UE Limitations

- Blueprint node graph editing (adding/connecting visual script nodes) is NOT
  exposed to Python — structural operations only
- Control Rig graph editing (RigVM nodes/connections) is NOT exposed to Python
  — hierarchy management only
- `execute_python` remains the escape hatch for advanced scenarios

## Deployment

- Source: `mca_core/unreal_tools/{python,blueprint,control_rig}/`
- Dist: `dist/MCAEditor-UE5.5-v1.0.5/Content/Python/mca_core/unreal_tools/`
- Wayward: `E:/Rascal/depot/Wayward/Plugins/MCAEditor-UE5.5-v1.0.5/MCAEditor/Content/Python/mca_core/unreal_tools/`
- MCP deploy: Auto-copied by `mcp_setup.py:ensure_unreal_mcp()` on next run

## Prototyping Notes

Two Blueprint write tools need validation in a live UE session:
1. `set_blueprint_variable` — `BlueprintEditorLibrary.add_variable()` API has
   gaps and quirks for variable creation. Type mapping is non-trivial.
2. `add_blueprint_component` — `SCS.create_node()` is not well-documented.
   May need adjustment after testing.
