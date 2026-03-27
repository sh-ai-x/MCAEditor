# PyUnreal — A Pythonic Wrapper for Unreal Engine

> Plan document for building an open-source PyMEL-equivalent for Unreal Engine,
> focused on Tech Art workflows: AnimBP, Blueprint, and Control Rig authoring.

---

## Vision

Make Unreal Engine's Python API feel like Python — not C++ with Python syntax.

PyMEL transformed Maya scripting by wrapping three clunky APIs into one
object-oriented, discoverable, Pythonic interface. UE Python has the same
problems (worse, actually) and nobody has solved it yet. PyUnreal will be
that solution, starting with the workflows Tech Artists care about most.

---

## Why Open Source / Separate Repo

- **Community trust & contributions** — TAs will adopt a library they can read and extend
- **pip-installable** — `pip install pyunreal`, works in any UE Python environment
- **Clean separation** from MCA Editor's proprietary compiled code (.pyd)
- **MCA Editor as the "power tier"** — PyUnreal works standalone for standard UE APIs;
  MCA Editor's C++ module (MCAEditorScripting) unlocks advanced graph editing
  (AnimBP state machines, Blueprint node wiring, etc.) that UE doesn't expose to Python
- **Drives adoption** — open-source library funnels power users toward MCA Editor

### Repo Structure (proposed)

```
pyunreal/
    README.md
    LICENSE                 # MIT
    pyproject.toml
    docs/                   # Sphinx, auto-generated + hand-written guides
        conf.py
        index.rst
        api/                # Auto-generated class/method reference
        guides/             # Tutorials, cookbooks, migration guides
    pyunreal/
        __init__.py         # Version, top-level imports
        core/
            __init__.py
            base.py         # Base wrapper classes, UnrealObject
            registry.py     # Class registry, lazy wrapping
            utils.py        # Common helpers (load_asset, find, etc.)
        anim/
            __init__.py
            anim_blueprint.py   # AnimBlueprint, StateMachine, State, Transition
        blueprint/
            __init__.py
            blueprint.py    # Blueprint, Component, Variable, Function
        control_rig/
            __init__.py
            rig.py          # ControlRig, Control, Bone, Null
        scene/
            __init__.py
            actor.py        # Actor wrappers, scene queries
            level.py        # Level operations
        material/
            __init__.py
            material.py     # Material, MaterialInstance, parameters
        viewport/
            __init__.py
            camera.py       # Viewport camera control
    tests/
        test_anim.py
        test_blueprint.py
        test_control_rig.py
    examples/
        create_locomotion_abp.py
        batch_blueprint_setup.py
        control_rig_from_skeleton.py
```

---

## Architecture

### Two-Tier System

```
+--------------------------------------------------+
|  PyUnreal (open source, pure Python)             |
|  - Pythonic wrappers around unreal.* APIs        |
|  - Works standalone in any UE Python env         |
+--------------------------------------------------+
         |                          |
         v                          v
+--------------------+   +-------------------------+
| Standard UE Python |   | MCAEditorScripting C++  |
| (unreal module)    |   | (MCA Editor plugin)     |
| - Always available |   | - Optional power tier   |
| - Limited access   |   | - AnimBP graph editing  |
+--------------------+   | - BP node wiring        |
                         | - Deep engine access     |
                         +-------------------------+
```

### Core Design Principles

1. **Object-oriented** — everything returns wrapped objects, not strings or dicts
2. **Discoverable** — tab completion, consistent method names, logical hierarchy
3. **Graceful degradation** — works without MCA Editor; advanced features check for
   MCAEditorScripting at runtime and raise clear errors if unavailable
4. **Undo-friendly** — all mutations wrapped in `unreal.ScopedEditorTransaction`
5. **Lazy** — don't load/wrap things until accessed (performance)
6. **No magic** — explicit is better than implicit; wrappers are thin

### Detection Pattern

```python
# Internal helper — checks once, caches result
def _has_mca_scripting():
    """Check if MCAEditorScripting C++ module is available."""
    try:
        return hasattr(unreal, 'MCAAnimBlueprintLibrary')
    except:
        return False

# In AnimBlueprint methods that need C++ bridge:
def add_state_machine(self, name, connect_to_root=True):
    if not _has_mca_scripting():
        raise RuntimeError(
            "AnimBP graph editing requires MCA Editor plugin. "
            "Install from: https://mcaeditor.com"
        )
    unreal.MCAAnimBlueprintLibrary.add_state_machine(
        self._asset, name, connect_to_root)
    return StateMachine(self, name)
```

---

## Phase 1: AnimBlueprint Wrappers (Priority — C++ Already Done)

### Target API

```python
from pyunreal.anim import AnimBlueprint

# --- Create an AnimBP --------------------------------------------------
skeleton = load('/Game/Characters/Mannequin/Skeleton')
abp = AnimBlueprint.create('/Game/AnimBP', 'ABP_Character', skeleton)

# --- Build a state machine ---------------------------------------------
loco = abp.add_state_machine('Locomotion', connect_to_root=True)

# --- Add states with animations ----------------------------------------
idle_anim = load('/Game/Animations/Idle')
walk_anim = load('/Game/Animations/Walk')
run_anim  = load('/Game/Animations/Run')

idle = loco.add_state('Idle', animation=idle_anim, default=True)
walk = loco.add_state('Walk', animation=walk_anim)
run  = loco.add_state('Run',  animation=run_anim)

# --- Wire transitions --------------------------------------------------
idle.transition_to(walk, crossfade=0.2)
walk.transition_to(idle, crossfade=0.2)
walk.transition_to(run,  crossfade=0.15)
run.transition_to(walk,  crossfade=0.15)

# --- Auto-transitions (time-remaining triggers) ------------------------
idle.auto_transition_to(walk, trigger_time=0.1)

# --- Compile ------------------------------------------------------------
result = abp.compile()
print(result)  # "Success" or error details

# --- Introspection ------------------------------------------------------
print(abp.state_machines)           # ['Locomotion']
print(loco.states)                  # ['Idle', 'Walk', 'Run']
print(idle.transitions)             # [Transition(Idle -> Walk)]
```

### Classes

| Class | Wraps | Key Methods |
|-------|-------|-------------|
| `AnimBlueprint` | `UAnimBlueprint` asset | `create()`, `load()`, `add_state_machine()`, `compile()`, `state_machines` |
| `StateMachine` | State machine graph node | `add_state()`, `states`, `name` |
| `State` | `UAnimStateNode` | `set_animation()`, `transition_to()`, `auto_transition_to()`, `transitions` |
| `Transition` | `UAnimStateTransitionNode` | `crossfade`, `trigger_time`, `from_state`, `to_state` |

### C++ Functions Used (MCAEditorScripting)

All 11 existing functions in `UMCAAnimBlueprintLibrary`:
- `CreateAnimBlueprint`, `AddStateMachine`, `ListStateMachines`
- `AddState`, `ListStates`, `SetDefaultState`, `SetStateAnimation`
- `AddTransition`, `SetAutoTransitionRule`
- `CompileAnimBlueprint`

---

## Phase 1.5: AnimBP EventGraph Wiring (C++ Bridge Extension)

AnimBP state machines are only half the picture. The EventGraph drives the
variables that transitions read (Speed, IsInAir, IsAccelerating, etc.). This
is currently impossible from Python — UE doesn't expose graph node creation
or pin wiring to the scripting layer. We need new C++ bridge functions.

### Motivation

Every AnimBP needs an EventGraph that:
1. **Initialize Animation** — gets the pawn owner, casts to the character
   class, caches references (Character, MovementComponent)
2. **Update Animation** — reads Velocity, Speed, IsFalling, etc. into
   variables that state machine transitions consume

Without this, users must manually wire 15+ nodes per AnimBP. This is the
most-requested gap after state machine creation.

### Target API

```python
from pyunreal.anim import AnimBlueprint

abp = AnimBlueprint.load('/Game/AnimBP/ABP_Character')
eg = abp.event_graph

# --- Initialize Animation Event ----------------------------------------
init = eg.add_event('BlueprintInitializeAnimation')
pawn = eg.add_call('TryGetPawnOwner')
cast = eg.add_cast('WCompanionCharacter')
set_char = eg.add_variable_set('Character')
get_move = eg.add_call('GetCharacterMovement')
set_move = eg.add_variable_set('MovementComponent')

# Wire the chain
init.exec >> pawn.exec >> cast.exec
cast.on_success >> set_char.exec >> get_move.exec >> set_move.exec
cast.as_type >> set_char.value
cast.as_type >> get_move.self
get_move.result >> set_move.value

# --- Update Animation Event --------------------------------------------
update = eg.add_event('BlueprintUpdateAnimation')
is_valid = eg.add_call('IsValid', args={'Object': 'Character'})
get_vel = eg.add_call('GetVelocity', target='Character')
vec_len = eg.add_math('VectorLength', input=get_vel.result)
set_speed = eg.add_variable_set('Speed', value=vec_len.result)
is_falling = eg.add_call('IsFalling', target='MovementComponent')
set_air = eg.add_variable_set('IsInAir', value=is_falling.result)

update.exec >> is_valid.exec
is_valid.on_true >> get_vel.exec >> set_speed.exec >> is_falling.exec >> set_air.exec

# --- Compile ------------------------------------------------------------
abp.compile()
```

### C++ Functions Needed (PyUnrealBlueprintLibrary)

New UFUNCTIONs to add alongside the existing state machine functions:

| Function | Purpose |
|----------|---------|
| `AddEventNode(Blueprint, GraphName, EventName)` | Add an event node (BlueprintInitializeAnimation, BlueprintUpdateAnimation, etc.) |
| `AddFunctionCallNode(Blueprint, GraphName, FunctionName, TargetClass)` | Add a function call (TryGetPawnOwner, GetVelocity, IsFalling, etc.) |
| `AddCastNode(Blueprint, GraphName, TargetClass)` | Add a Cast To node |
| `AddVariableGetNode(Blueprint, GraphName, VarName)` | Add a GET node for a BP variable |
| `AddVariableSetNode(Blueprint, GraphName, VarName)` | Add a SET node for a BP variable |
| `AddMathExpressionNode(Blueprint, GraphName, Operation)` | Add math/comparison (VectorLength, GreaterThan, etc.) |
| `ConnectPins(Blueprint, NodeA_Id, PinNameA, NodeB_Id, PinNameB)` | Wire two pins together (exec or data) |
| `GetNodePins(Blueprint, Node_Id)` | List available pins on a node (for discovery) |
| `SetNodePosition(Blueprint, Node_Id, X, Y)` | Position node in graph for clean layout |

### UE C++ APIs Involved

- `UEdGraph` — the graph container (EventGraph, AnimGraph)
- `UK2Node_Event` — event nodes (Init, Update)
- `UK2Node_CallFunction` — function call nodes
- `UK2Node_DynamicCast` — cast nodes
- `UK2Node_VariableGet/Set` — variable access
- `UEdGraphSchema_K2::TryCreateConnection()` — pin wiring
- `FKismetEditorUtilities::CompileBlueprint()` — compile after changes
- `UEdGraphPin` — individual input/output pins on nodes

### Implementation Notes

- Node IDs can be the node's `FGuid` or a user-assigned name
- Pin names follow UE conventions: "execute" (exec), "then" (exec out),
  "ReturnValue", "self", etc.
- `ConnectPins` is the key function — everything else just creates nodes;
  this wires them together
- Need auto-layout helper so programmatically created graphs aren't a mess
- EventGraph is `Blueprint->UbergraphPages[0]` in C++

### Priority

HIGH — this is what users hit immediately after creating state machines.
The Claude session in MCA Editor specifically couldn't wire AnimBP variables
because this doesn't exist yet. Every AnimBP workflow needs this.

---

## Phase 2: Blueprint Wrappers

### Target API

```python
from pyunreal.blueprint import Blueprint

# --- Create a Blueprint ------------------------------------------------
bp = Blueprint.create('/Game/Blueprints', 'BP_Pickup', parent='Actor')

# --- Add components ----------------------------------------------------
mesh = bp.add_component('StaticMesh', name='PickupMesh')
collision = bp.add_component('SphereCollision', name='Trigger')

# --- Set defaults -------------------------------------------------------
bp.set_default('PickupMesh.StaticMesh', load('/Game/Meshes/Gem'))
bp.set_default('Trigger.SphereRadius', 150.0)

# --- Variables ----------------------------------------------------------
bp.add_variable('PointValue', 'int', default=10)
bp.add_variable('IsCollected', 'bool', default=False)

# --- Introspection ------------------------------------------------------
print(bp.components)    # ['PickupMesh', 'Trigger']
print(bp.variables)     # [Variable('PointValue', int), Variable('IsCollected', bool)]
print(bp.functions)     # ['ReceiveBeginPlay', ...]
print(bp.events)        # [Event('ActorBeginOverlap')]

# --- Compile ------------------------------------------------------------
bp.compile()
```

### Classes

| Class | Wraps | Key Methods |
|-------|-------|-------------|
| `Blueprint` | `UBlueprint` asset | `create()`, `load()`, `add_component()`, `add_variable()`, `set_default()`, `compile()` |
| `Component` | SCS node | `name`, `type`, `parent`, `children` |
| `Variable` | BP variable | `name`, `type`, `default`, `set()`, `get()` |

### Python Functions Used (existing MCP tools)

These already exist in `mca_core/unreal_tools/blueprint/`:
- `create_blueprint`, `add_blueprint_component`, `compile_blueprint`
- `get_blueprint_info`, `list_blueprint_components`
- `list_blueprint_variables`, `set_blueprint_variable`
- `get_class_defaults`, `set_class_default`

---

## Phase 3: Control Rig Wrappers

### Target API

```python
from pyunreal.control_rig import ControlRig

# --- Load existing rig --------------------------------------------------
rig = ControlRig.load('/Game/Rigs/CR_Character')

# --- Add controls -------------------------------------------------------
root = rig.add_null('Root')
hips = rig.add_control('Hips', parent=root, shape='Box', color='yellow')
spine = rig.add_control('Spine_01', parent=hips, shape='Circle')

# --- Set transforms -----------------------------------------------------
hips.transform.location = Vector(0, 0, 100)
spine.transform.location = Vector(0, 0, 130)

# --- Introspection ------------------------------------------------------
print(rig.controls)   # ['Hips', 'Spine_01']
print(rig.bones)      # ['root', 'pelvis', 'spine_01', ...]
print(rig.hierarchy)  # Tree view
```

### Classes

| Class | Wraps | Key Methods |
|-------|-------|-------------|
| `ControlRig` | `UControlRigBlueprint` | `load()`, `add_control()`, `add_null()`, `controls`, `bones` |
| `Control` | Control element | `transform`, `shape`, `color`, `parent`, `children` |
| `Null` | Null element | `transform`, `parent`, `children` |
| `Bone` | Bone element | `transform`, `parent`, `children` (read-only) |

---

## Phase 4: Scene & Actor Wrappers

### Target API

```python
from pyunreal.scene import Actor, scene

# --- Spawn actors -------------------------------------------------------
chair = Actor.spawn('StaticMeshActor', name='Chair_01')
chair.mesh = load('/Game/Meshes/Chair')
chair.location = Vector(100, 200, 0)
chair.rotation = Rotator(0, 45, 0)

# --- Scene queries ------------------------------------------------------
lights = scene.find_by_type('PointLight')
chairs = scene.find('Chair_*')
selected = scene.selected()

# --- Bulk operations ----------------------------------------------------
for actor in scene.find_by_type('StaticMeshActor'):
    actor.location.z += 10

# --- Properties ---------------------------------------------------------
print(chair.location)       # Vector(100, 200, 0)
print(chair.components)     # ['StaticMeshComponent0']
```

---

## Phase 5: Documentation Pipeline

### Auto-Generated Reference (like PyMEL docs)

```
Sphinx autodoc
    |
    v
Walk pyunreal classes → extract docstrings → generate .rst per class
    |
    v
Build HTML → deploy to mcaeditor.com/docs/pyunreal/
```

### Doc Structure on mcaeditor.com

```
mcaeditor.com/docs/pyunreal/
    getting-started/
        installation.md
        quickstart.md
        mca-editor-integration.md
    guides/
        animblueprint-cookbook.md
        blueprint-batch-setup.md
        control-rig-from-skeleton.md
        migrating-from-raw-unreal.md
    api/
        anim/
            AnimBlueprint.md        # Auto-generated
            StateMachine.md
            State.md
            Transition.md
        blueprint/
            Blueprint.md
            Component.md
            Variable.md
        control_rig/
            ControlRig.md
            Control.md
        scene/
            Actor.md
            scene.md (module-level functions)
    changelog.md
```

### Doc Generation Pipeline

1. **Introspection script** walks all pyunreal classes and methods
2. **Sphinx autodoc** generates .rst from docstrings
3. **Custom templates** match mcaeditor.com styling
4. **CI/CD** rebuilds docs on every tagged release
5. **Version selector** — docs versioned per UE version (5.4, 5.5, 5.6)

---

## Maintenance Strategy

### Per UE Release (5.5 → 5.6, etc.)

1. Read Epic's Python API migration notes
2. Run test suite against new UE version
3. Grep for deprecated/renamed APIs in wrapper code
4. Update wrappers, add new features
5. Rebuild docs
6. Tag new pyunreal version

**Estimated effort**: A few hours per engine release for Python wrappers.
C++ module (MCAEditorScripting) may need more work if engine internals change.

### AI-Assisted Maintenance

The maintenance pattern is mechanical and well-suited for AI:
- Read changelog → find breaking changes → update wrappers → run tests → update docs
- Pattern-heavy, repetitive — exactly what Claude is good at

---

## Development Milestones

### Milestone 1: Project Setup & AnimBP (Phase 1) -- COMPLETE
- [x] Create GitHub repo (pyunreal, MIT license)
- [x] Set up pyproject.toml, package structure
- [x] Implement core base classes (UnrealObject, asset loading, utils)
- [x] Implement AnimBlueprint, StateMachine, State, Transition wrappers
- [x] Write tests (mocked — 21 AnimBP tests)
- [x] Write AnimBP cookbook / getting-started guide
- [x] Create MCP wrapper tools for AnimBP (missing from MCA Editor)

### Milestone 1.5: EventGraph Wiring (Phase 1.5) -- C++ WRITTEN
- [x] C++ bridge functions: AddEventNode, AddFunctionCallNode, AddCastNode,
      AddVariableGetNode, AddVariableSetNode, ConnectPins, GetNodePins,
      SetNodePosition, ListEventGraphNodes
- [x] Python wrappers: EventGraph, GraphNode classes
- [x] API docs (EventGraph.md)
- [ ] Compile C++ plugin in UE (requires UE build)
- [ ] Live integration test in UE

### Milestone 2: Blueprint Wrappers (Phase 2) -- COMPLETE
- [x] Implement Blueprint, Component, Variable wrappers
- [x] Wrap existing MCP tool functions into Pythonic classes
- [x] Write examples
- [x] Write tests (22 tests)
- [x] Blueprint cookbook guide

### Milestone 3: Control Rig Wrappers (Phase 3) -- COMPLETE
- [x] Implement ControlRig, Control, Null, Bone wrappers
- [x] Write examples
- [x] Write tests (20 tests)
- [x] Control Rig cookbook guide

### Milestone 4: Scene, Material, Viewport (Phase 4) -- COMPLETE
- [x] Implement Actor wrappers, scene query functions
- [x] Material wrappers (create, load, set_param, get_param, assign_to)
- [x] Viewport helpers (focus, set_camera, get_camera, screenshot)
- [x] Write examples
- [x] Write tests (24 scene + 20 material + 13 viewport = 57 tests)
- [x] API docs for all new classes

### Milestone 5: Documentation Site (Phase 5)
- [x] Hand-written API reference docs (Markdown)
- [x] Getting started guide and AnimBP cookbook
- [ ] Sphinx autodoc pipeline
- [ ] Deploy to mcaeditor.com/docs/pyunreal/
- [ ] Version selector for UE versions
- [ ] SEO and discoverability

---

## Open Questions

1. **Package name**: `pyunreal`? `unrealpy`? `ue_python`? Need to check PyPI availability.
2. **Minimum UE version**: 5.4? 5.5? How far back do we support?
3. **Vector/Rotator wrappers**: Do we wrap `unreal.Vector` with operator overloads,
   or just pass through the native types?
4. **Async support**: Some UE operations are slow (compilation). Worth adding async/progress?
5. **Community governance**: Contribution guidelines, code review process for PRs.

---

## Key Takeaway

The hardest part — the C++ bridge for AnimBP graph editing — is already done.
PyUnreal is primarily a Python API design and documentation project, not an
engine hacking project. The foundation is solid; we need to make it beautiful.
