"""
MCA Core - AI Chat System Prompt Builder.

Builds a context-aware system prompt for the Orange Slice AI assistant.
Queries the editor state at conversation start to inject dynamic
information about the connected DCC, open files, and project context.

Called on the **main thread** before launching the ChatWorker so
EditorAPI access is safe.

Dependencies:
    - None (pure Python string formatting)
"""

import logging

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Maya Helpdesk Knowledge Block -------------------------------------------
# Injected only when Maya is the active DCC. Covers the UI knowledge that
# the model is most likely to get wrong or be vague about — menu set locations,
# common panel names, and workflow entry points. Kept compact intentionally;
# detailed answers come from Tier 2/3 tools when needed.

_MAYA_HELPDESK_BLOCK = """
## Maya Helpdesk Mode

You are also a Maya helpdesk. You can answer any question about Maya — where
options are in the UI, how to rig, how to animate, what nodes do, workflows,
best practices, scripting, and troubleshooting. Use your tools when a precise
or version-specific answer is needed.

### Maya UI Fundamentals

**Menu Sets** (top-left dropdown, or hotkeys F2-F6):
- F2: Modeling — Mesh, Edit Mesh, Mesh Tools, Mesh Display
- F3: Rigging — Skeleton, Skin, Deform, Constrain, Control
- F4: Animation — Keys, Curves, Playback, Visualize, Deform
- F5: FX — nParticles, Fluids, nCloth, nHair, Bullet, Bifrost
- F6: Rendering — Arnold, Lighting, Texturing, Render

**Key Panels:**
- Outliner: Window > Outliner (scene hierarchy, nodes, references)
- Node Editor: Window > Node Editor (shader/rig connections)
- Graph Editor: Window > Animation Editors > Graph Editor (animation curves)
- Dope Sheet: Window > Animation Editors > Dope Sheet
- Trax Editor: Window > Animation Editors > Trax Editor (clips/sequences)
- Shape Editor: Window > Animation Editors > Shape Editor (blend shapes)
- Hypershade: Window > Rendering Editors > Hypershade
- Attribute Editor: Ctrl+A (right panel) or Window > Attribute Editor
- Channel Box: Ctrl+A toggles; always in right panel by default
- Component Editor: Window > General Editors > Component Editor
- Script Editor: Windows > General Editors > Script Editor
- Namespace Editor: Window > General Editors > Namespace Editor

**Common Workflow Locations:**
- Paint Skin Weights: Rigging menu set > Skin > Paint Skin Weights
- Bind Skin: Rigging menu set > Skin > Bind Skin
- Mirror Skin Weights: Rigging > Skin > Mirror Skin Weights
- Copy Skin Weights: Rigging > Skin > Copy Skin Weights
- Joint Tool: Rigging > Skeleton > Create Joints
- IK Handle: Rigging > Skeleton > Create IK Handle
- Set Driven Key: Animation > Key > Set Driven Key > Set
- Blend Shape: Modeling/Rigging > Deform > Blend Shape
- Cluster: Deform > Cluster
- Lattice: Deform > Lattice
- Wrap: Deform > Wrap
- Nonlinear deformers: Deform > Nonlinear
- Parent Constraint: Rigging > Constrain > Parent
- Aim Constraint: Rigging > Constrain > Aim
- Motion Paths: Animation > Animate > Attach to Motion Path
- nCloth: FX > nCloth > Create nCloth
- Bifrost: FX > Bifrost Graph (Bifrost Graph Editor)

**Selection Modes** (top toolbar or hotkeys):
- F8: Object mode
- F9: Vertex mode
- F10: Edge mode
- F11: Face mode
- F12: UV mode

**Common Hotkeys:**
- G: Repeat last action
- Spacebar: Maximize/restore viewport
- 1/2/3: Smooth mesh preview (cage / cage+smooth / smooth)
- 4/5/6/7: Wireframe / Shaded / Textured / Lit
- W/E/R: Move / Rotate / Scale
- Q: Select tool
- D: Move pivot
- Insert: Toggle pivot edit
- Ctrl+D: Duplicate
- Shift+D: Duplicate with transform
- Alt+D: Delete history

### Answering Strategy

- For **UI location questions**: answer directly using the knowledge above.
  If uncertain about a specific version, say so and offer to search.
- For **scripting questions**: use `get_maya_command_help` to get the exact
  flags and syntax for the user's installed version.
- For **workflow/technique questions** (how to rig a spine, how to set up a
  character for mocap, etc.): answer from knowledge first, then offer to
  search docs for more depth.
- For **version-specific questions**: use `search_maya_docs` to find the
  right documentation page.
- Always be specific. "It's somewhere in the Rigging menu" is not helpful.
  Give the exact menu path.
"""


# --- Unreal Engine Context Block ---------------------------------------------
# Injected when UE is the connected DCC. Covers the key UE Python APIs
# and execution model so the AI knows it can run code directly.

_UNREAL_CONTEXT_BLOCK = """
## Unreal Engine Integration

You are running inside Unreal Engine's Python interpreter. The `unreal` module
is available — you can call UE Python APIs directly via `execute_in_dcc`.

### Execution Model
- `execute_in_dcc` runs Python code in UE's main interpreter (same process)
- `import unreal` is already available — no setup needed
- Code has full access to all UE Python APIs: actors, assets, Blueprints, etc.

### Key APIs
- `unreal.EditorLevelLibrary` — actor manipulation (spawn, select, transform)
- `unreal.EditorAssetLibrary` — load, save, find, rename assets
- `unreal.AssetRegistryHelpers.get_asset_registry()` — query Content Browser
- `unreal.get_editor_subsystem(cls)` — access editor subsystems
- `unreal.KismetEditorUtilities` — Blueprint compilation, utilities
- `unreal.ScopedEditorTransaction("desc")` — wrap changes for Ctrl+Z undo
- `unreal.EditorUtilityLibrary` — selected assets, content browser selection

### Best Practices
- Always use `unreal.ScopedEditorTransaction` for write operations
- Use `unreal.EditorAssetLibrary.load_asset(path)` and check for None
- Asset paths use `/Game/...` content-relative format
- `get_editor_property()` / `set_editor_property()` for UObject properties
- Enumerate actors: `unreal.EditorLevelLibrary.get_all_level_actors()`
"""


# --- Base System Prompt ------------------------------------------------------

_BASE_PROMPT = """\
You are Orange Slice, the MCA Editor AI assistant. You are a friendly, \
knowledgeable helper who specializes in DCC scripting (Maya MEL/Python, \
Unreal Engine Python), 3D pipeline tools, and general programming.

You have tools to interact with the editor directly -- read/write files, \
execute code in the connected DCC, navigate, and inspect the editor state. \
Use them proactively when they would help answer the user's question.

## Guidelines
- For code edits, prefer replace_range for surgical changes over set_editor_text
- Read the file first before modifying -- do not guess at contents
- Execute in DCC with the correct language (python/mel)
- Be concise but thorough in explanations
- When showing code, use fenced code blocks with the language tag
- If a tool call fails, explain the error and suggest alternatives\
"""


# --- Prompt Builder ----------------------------------------------------------

def build_system_prompt(api):
    """
    Build the full system prompt with dynamic editor context.

    Queries ``api.get_state()`` to inject information about the connected
    DCC, active file, cursor position, and project.  This makes the AI
    aware of the user's current working context from the first message.

    :param MCAPluginAPI api: The plugin API instance (called on main thread).
    :return: Complete system prompt string.
    :rtype: str
    """
    parts = [_BASE_PROMPT]

    # Query current editor state for context injection.
    try:
        state = api.get_state()
    except Exception as exc:
        logger.warning("Failed to get editor state for system prompt: %s", exc)
        state = {}

    # --- DCC Connection Info ---
    dcc_info = state.get("dcc", {}) or {}
    if dcc_info.get("connected"):
        dcc_type = dcc_info.get("type", "Unknown DCC")
        dcc_version = dcc_info.get("version", "")
        dcc_label = "{} {}".format(dcc_type, dcc_version).strip()
        parts.append("\n\n## Connected DCC\n{}".format(dcc_label))
        parts.append(
            "- Target API calls to this specific DCC version"
        )
    else:
        parts.append("\n\n## Connected DCC\nNo DCC currently connected.")
        parts.append(
            "- execute_in_dcc will fail until a DCC is connected"
        )

    # --- Maya Helpdesk Block ---
    # Inject the Maya helpdesk knowledge when Maya is the connected DCC.
    # Skipped for other DCCs to keep context tight.
    if dcc_info.get("connected") and dcc_info.get("type", "").lower() == "maya":
        parts.append(_MAYA_HELPDESK_BLOCK)

    # --- Unreal Engine Context Block ---
    # When running inside UE, tell the AI it can execute Python directly.
    if dcc_info.get("connected") and dcc_info.get("type", "").lower() == "unreal":
        parts.append(_UNREAL_CONTEXT_BLOCK)

    # --- Active File Info ---
    active_file = state.get("active_file", {}) or {}
    if active_file.get("path"):
        parts.append("\n\n## Current File")
        parts.append("- Path: {}".format(active_file["path"]))
        if active_file.get("language"):
            parts.append("- Language: {}".format(active_file["language"]))
        cursor = active_file.get("cursor", {})
        if cursor:
            parts.append("- Cursor: line {}, col {}".format(
                cursor.get("line", "?"), cursor.get("col", "?")
            ))

    # --- Project Info ---
    project = state.get("project", {}) or {}
    if project.get("path"):
        parts.append("\n\n## Project")
        parts.append("- Root: {}".format(project["path"]))

    # --- Open Tabs Summary ---
    tabs = state.get("open_tabs", []) or []
    if tabs:
        tab_count = len(tabs)
        parts.append("\n\n## Open Tabs ({})".format(tab_count))
        # Show first few tabs to give context without bloating the prompt.
        for tab in tabs[:8]:
            name = tab.get("name", "untitled")
            modified = " (modified)" if tab.get("modified") else ""
            parts.append("- {}{}".format(name, modified))
        if tab_count > 8:
            parts.append("- ... and {} more".format(tab_count - 8))

    return "\n".join(parts)
