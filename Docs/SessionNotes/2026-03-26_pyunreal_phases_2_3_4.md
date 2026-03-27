# Session Notes -- 2026-03-26: PyUnreal Phases 2, 3, 4 + Material & Viewport

## Summary

Built five major PyUnreal modules covering Blueprints, Control Rigs,
Scene/Actor manipulation, Materials, and Viewport control. Bumped version
to 0.3.0. All modules import cleanly outside UE (lazy `import unreal`
pattern). 137 tests passing. Deployed to Wayward project.

## Phase 2: Blueprint Module (`pyunreal/blueprint/`)

### Classes

- **Blueprint** — wraps `UBlueprint`. Methods: `create()`, `load()`, `find()`,
  `add_component()`, `add_variable()`, `set_default()`, `get_default()`,
  `compile()`. Properties: `name`, `path`, `parent_class`, `components`,
  `variables`, `functions`, `events`.

- **Component** — read-only snapshot of an SCS node. Properties: `name`,
  `component_class`, `parent`, `location`, `rotation`, `scale`.

- **Variable** — wraps a user-defined Blueprint variable. Properties: `name`,
  `var_type`, `default`. Methods: `set(value)`. Type mapping from friendly
  names (`int`, `bool`, `float`, `str`) to UE property types (`IntProperty`,
  `BoolProperty`, etc.).

### UE APIs Used

- `BlueprintFactory`, `AssetToolsHelpers.get_asset_tools()` — creation
- `BlueprintEditorLibrary.add_variable()`, `set_variable_category()` — variables
- `KismetEditorUtilities.compile_blueprint()` — compilation
- `simple_construction_script`, `scs.create_node()`, `add_child_node()` — components
- `get_default_object()`, CDO property access — defaults
- `ScopedEditorTransaction` — undo support on all writes

## Phase 3: Control Rig Module (`pyunreal/control_rig/`)

### Classes

- **ControlRig** — wraps `UControlRigBlueprint`. Methods: `load()`, `find()`,
  `add_control()`, `add_null()`, `get_control()`. Properties: `name`, `path`,
  `controls`, `bones`, `nulls`.

- **Control** — wraps a control element. Methods: `set_transform()`,
  `set_shape()`. Properties: `name`, `parent`, `transform`, `rig`.
  Includes color preset system (red, green, blue, yellow, cyan, etc.).

- **Null** — read-only space/group element. Properties: `name`, `parent`,
  `transform`.

- **Bone** — read-only skeleton bone. Properties: `name`, `parent`, `transform`.

### UE APIs Used

- `ControlRigBlueprint.hierarchy` — element traversal
- `hierarchy.get_all_keys()`, `get_type()`, `get_name()`, `get_parent()` — inspection
- `hierarchy.get_initial_global_transform()`, `set_initial_global_transform()` — transforms
- `rig_bp.get_controller()` — hierarchy controller for mutations
- `controller.add_control()`, `controller.add_null()` — adding elements
- `hierarchy.get_control_settings()`, `set_control_settings()` — shape/color

## Phase 4: Scene Module (`pyunreal/scene/`)

### Classes

- **Actor** — wraps a level actor. Methods: `spawn()`, `set_property()`,
  `get_property()`, `destroy()`. Properties (read-write): `name`, `location`,
  `rotation`, `scale`. Properties (read-only): `class_name`, `hidden`.

### Module-Level Functions (`scene`)

- `scene.all()` — all level actors
- `scene.selected()` — currently selected actors
- `scene.select(actors_or_names)` — set selection
- `scene.find(name_pattern)` — glob-style name search
- `scene.find_by_type(class_name)` — filter by actor class
- `scene.find_by_tag(tag)` — filter by actor tag

### UE APIs Used

- `EditorLevelLibrary.spawn_actor_from_class()` — spawning
- `EditorLevelLibrary.get_all_level_actors()` — queries
- `EditorLevelLibrary.get_selected_level_actors()`, `set_selected_level_actors()` — selection
- Actor transform methods: `get/set_actor_location()`, `get/set_actor_rotation()`, `get/set_actor_scale3d()`

## Examples Added

- `examples/batch_blueprint_setup.py` — creates multiple pickup BPs with components and variables
- `examples/control_rig_from_skeleton.py` — loads a rig, inspects hierarchy, adds controls
- `examples/scene_operations.py` — spawns actors, queries scene, bulk operations

## Deployment

- PyUnreal v0.2.0 deployed to `E:\Rascal\depot\Wayward\Content\Python\pyunreal\`
- PYUNREAL_PLAN.md milestones 2-4 marked complete
- Committed to PyUnreal repo: `da91ac0`

## Files Created

- `pyunreal/blueprint/__init__.py`
- `pyunreal/blueprint/blueprint.py`
- `pyunreal/blueprint/component.py`
- `pyunreal/blueprint/variable.py`
- `pyunreal/control_rig/__init__.py`
- `pyunreal/control_rig/rig.py`
- `pyunreal/control_rig/control.py`
- `pyunreal/control_rig/null.py`
- `pyunreal/control_rig/bone.py`
- `pyunreal/scene/__init__.py`
- `pyunreal/scene/actor.py`
- `pyunreal/scene/scene_queries.py`
- `examples/batch_blueprint_setup.py`
- `examples/control_rig_from_skeleton.py`
- `examples/scene_operations.py`

## Tests (104 passing)

Full test suite using mocked `unreal` module — tests run outside UE.

- `tests/mock_unreal.py` — configurable mock with all UE types/libraries
- `tests/test_core.py` — errors, base wrapper, detection, utils (17 tests)
- `tests/test_anim.py` — AnimBlueprint, StateMachine, State, Transition (21 tests)
- `tests/test_blueprint.py` — Blueprint, Component, Variable, type mapping (22 tests)
- `tests/test_control_rig.py` — ControlRig, Control, Bone, Null, colors (20 tests)
- `tests/test_scene.py` — Actor, scene queries (24 tests)

## API Docs

API reference pages for all new classes:
- `docs/api/Blueprint.md`, `Component.md`, `Variable.md`
- `docs/api/ControlRig.md`, `Control.md`, `Bone.md`, `Null.md`
- `docs/api/Actor.md`, `scene.md`
- `docs/index.md` updated with all new sections

## Material Module (`pyunreal/material/`)

- **Material** — wraps `UMaterial` / `UMaterialInstance`. Methods: `create()`,
  `load()`, `set_param()`, `get_param()`, `assign_to()`. Properties: `name`, `path`.
- `set_param()` auto-detects scalar (float/int) vs color (tuple) parameters
- `assign_to()` finds first StaticMeshComponent or MeshComponent on the actor
- Supports method chaining: `mat.set_param('Roughness', 0.2).assign_to('Chair')`

### UE APIs Used (Material)

- `MaterialFactoryNew`, `AssetToolsHelpers.get_asset_tools()` — creation
- `set_editor_property()` / `get_editor_property()` — parameter access
- `unreal.LinearColor(r, g, b, a)` — color parameters
- `actor.get_components_by_class(StaticMeshComponent)` — mesh finding
- `mesh_comp.set_material(slot, material)` — assignment

## Viewport Module (`pyunreal/viewport/`)

Module-level functions (not a class):

- `viewport.focus(actor_or_name)` — pilots viewport to an actor
- `viewport.set_camera(location, rotation)` — positions the viewport camera
- `viewport.get_camera()` — returns current camera location/rotation
- `viewport.screenshot(path, width, height)` — captures high-res screenshot

### UE APIs Used (Viewport)

- `unreal.get_editor_subsystem(LevelEditorSubsystem)` — viewport control
- `subsystem.pilot_level_actor(target)` — focus on actor
- `unreal.get_editor_subsystem(UnrealEditorSubsystem)` — camera access
- `subsystem.set_level_viewport_camera_info(loc, rot)` — camera positioning
- `subsystem.get_level_viewport_camera_info()` — camera readback
- `unreal.AutomationLibrary.take_high_res_screenshot(w, h, path)` — screenshots

## Cookbook Guides Added

- `docs/guides/blueprint-cookbook.md` — Blueprint creation, variables, batch setup, introspection
- `docs/guides/control-rig-cookbook.md` — Rig inspection, controls, transforms, shapes, colors

## Tests (137 passing)

Full test suite using mocked `unreal` module — tests run outside UE.

- `tests/test_core.py` — 17 tests (errors, base wrapper, detection, utils)
- `tests/test_anim.py` — 21 tests (AnimBlueprint, StateMachine, State, Transition)
- `tests/test_blueprint.py` — 22 tests (Blueprint, Component, Variable, type mapping)
- `tests/test_control_rig.py` — 20 tests (ControlRig, Control, Bone, Null, colors)
- `tests/test_scene.py` — 24 tests (Actor, scene queries)
- `tests/test_material.py` — 20 tests (Material create, load, params, assign)
- `tests/test_viewport.py` — 13 tests (focus, camera, screenshot)

## Additional Files Created

- `pyunreal/material/__init__.py`, `pyunreal/material/material.py`
- `pyunreal/viewport/__init__.py`, `pyunreal/viewport/viewport_ops.py`
- `tests/test_material.py`, `tests/test_viewport.py`
- `docs/api/Material.md`, `docs/api/viewport.md`
- `docs/guides/blueprint-cookbook.md`, `docs/guides/control-rig-cookbook.md`
- `examples/material_setup.py`, `examples/viewport_tools.py`

## Phase 1.5: EventGraph Node Wiring (C++ + Python)

### C++ Bridge Functions Added (`PyUnrealBlueprintLibrary`)

New UFUNCTIONs in `PyUnrealEventGraphLibrary.cpp`:

- `AddEventNode(Blueprint, EventName)` — creates UK2Node_Event
- `AddFunctionCallNode(Blueprint, FunctionName, TargetClass)` — creates UK2Node_CallFunction
- `AddCastNode(Blueprint, TargetClassName)` — creates UK2Node_DynamicCast
- `AddVariableGetNode(Blueprint, VarName)` — creates UK2Node_VariableGet
- `AddVariableSetNode(Blueprint, VarName)` — creates UK2Node_VariableSet
- `ConnectPins(Blueprint, SourceNodeId, SourcePin, TargetNodeId, TargetPin)` — wires pins via Schema
- `GetNodePins(Blueprint, NodeId, OutPins)` — lists pins for discovery
- `SetNodePosition(Blueprint, NodeId, X, Y)` — positions node in graph
- `ListEventGraphNodes(Blueprint, OutNodes)` — lists all EventGraph nodes

All functions return node IDs as GUID strings for Python-side referencing.

### UE C++ APIs Used

- `UEdGraph` (UbergraphPages[0]) — the EventGraph container
- `UK2Node_Event` — event nodes (override or custom)
- `UK2Node_CallFunction` + `FunctionReference.SetFromField()` — function calls
- `UK2Node_DynamicCast` + `TargetType` — cast nodes
- `UK2Node_VariableGet/Set` + `VariableReference.SetSelfMember()` — variable access
- `UEdGraphSchema_K2::TryCreateConnection()` — pin wiring (validates type compatibility)
- `FGraphNodeCreator<T>` — proper node creation pattern
- `FindObject<UClass>(ANY_PACKAGE, ...)` — class lookup by name with prefix fallbacks

### Python Wrappers

- `EventGraph` class — wraps a Blueprint's EventGraph, methods: `add_event()`,
  `add_call()`, `add_cast()`, `add_variable_get()`, `add_variable_set()`, `nodes`
- `GraphNode` class — wraps a single node, methods: `connect()`, `set_position()`, `pins`
- `AnimBlueprint.event_graph` property — returns EventGraph wrapper
- `Blueprint.event_graph` property — returns EventGraph wrapper

### Status

C++ code written but NOT compiled — requires UE build environment. Python wrappers
import cleanly and are ready. Once the C++ plugin is compiled and loaded in UE, the
full EventGraph API becomes available.

## Deployment

- PyUnreal v0.3.0 deployed to `E:\Rascal\depot\Wayward\Content\Python\pyunreal\`
- PYUNREAL_PLAN.md milestones 1-4 fully complete, 1.5 C++ written
- PyUnreal repo commits: `69c5b30`, `6329fbc`, `5e73033`

## Files Modified

- `pyunreal/__init__.py` — version bump to 0.3.0, added material/viewport modules
- `pyproject.toml` — version bump to 0.3.0
- `tests/mock_unreal.py` — added Material, Viewport, Subsystem mocks
- `docs/index.md` — added Material, Viewport, cookbook links
- `Docs/PYUNREAL_PLAN.md` — milestones 1-4 marked fully complete
