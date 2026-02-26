# MCA Editor — Maya MCP Integration Plan (v2)

## Goal
When Claude Code runs in the MCA Editor terminal, it can automatically
interact with the live Maya scene. No setup steps for the artist. No
mention of "MCP" in the UI. It just works.

We're using Patrick Palmer's open-source MayaMCP server (MIT license).

---

## How It Works

### Embedded in Maya (Plugin)
1. Artist loads the MCA Editor plugin in Maya
2. `initializePlugin` runs the existing venv setup (pywinpty, etc.)
3. Immediately after, MayaMCP setup runs silently in the background:
   - Clone MayaMCP if not present
   - Create its venv and install dependencies if needed
   - Register with Claude Code if not already registered
4. Artist opens terminal (Ctrl+`), launches Claude Code
5. Claude Code automatically sees the MayaMCP server and can query the scene

### Standalone Connected to Maya
1. Artist launches the standalone MCA Editor
2. Artist connects to Maya via the DCC connection dialog
3. On successful connection, MayaMCP setup runs silently in the background
   (same sequence as above)
4. Artist opens terminal, launches Claude Code, scene access works

### No Maya Connected
- MayaMCP setup is skipped entirely
- Claude Code still works for code assistance, just without scene tools
- If the user later connects to Maya, setup triggers at that point

---

## Automatic Trigger Points

| Environment | Trigger | Timing |
|-------------|---------|--------|
| Maya plugin | `initializePlugin` | After venv_manager.setup() |
| Standalone + Maya | DCC connection success | After adapter.connect() returns True |
| Standalone, no Maya | Never | MayaMCP not needed |

The setup function is idempotent — calling it multiple times is safe.
If everything is already installed and registered, it returns immediately
with no network calls, no subprocesses, no delay.

---

## Directory Structure

```
mca_preferences/
├── .venv-3.11/               # MCA Editor venv (pywinpty, pyflakes)
└── mcp_servers/
    └── MayaMCP/              # Cloned from GitHub
        ├── .venv/            # MayaMCP's own venv (mcp SDK, Python 3.10+)
        ├── src/
        │   ├── maya_mcp_server.py
        │   └── mayatools/
        │       ├── ...       # Built-in tools
        │       └── thirdparty/  # Custom tools (survives updates)
        └── requirements.txt
```

MayaMCP's venv uses system Python (3.10+), NOT mayapy. MayaMCP runs as
a separate process that talks to Maya over the command port — it doesn't
run inside Maya.

---

## New File: `mca_core/mcp_setup.py`

Pure Python, no Qt dependency. All functions are safe to call from any
context (plugin init, standalone app, background thread).

### Public API

```python
def ensure_maya_mcp(background=True):
    """
    Ensure MayaMCP is installed, configured, and registered with
    Claude Code. Safe to call repeatedly — skips steps that are
    already done.

    When background=True (default), runs the full setup in a
    background thread so it doesn't block the UI. Status messages
    are logged but not shown to the user unless something fails.

    Returns immediately if everything is already set up.

    :param bool background: If True, run in a daemon thread.
    :rtype: None (background) or tuple(bool, str) (foreground)
    """
```

### Internal Functions

- **`_is_maya_mcp_present()`**
  Checks if `mca_preferences/mcp_servers/MayaMCP/src/maya_mcp_server.py`
  exists. Quick filesystem check, no subprocess.

- **`_is_maya_mcp_venv_ready()`**
  Checks if MayaMCP's `.venv/Scripts/python.exe` exists and the `mcp`
  package is importable from it. Quick filesystem check.

- **`_is_registered_with_claude_code()`**
  Reads `~/.claude.json` and checks if an "MayaMCP" entry exists in
  `mcpServers`. Pure JSON parsing, no subprocess.

- **`_clone_maya_mcp()`**
  Runs `git clone https://github.com/PatrickPalmer/MayaMCP.git` into
  `mca_preferences/mcp_servers/`. Subprocess call.
  Returns (success, message).

- **`_setup_maya_mcp_venv()`**
  Creates venv with system Python, installs requirements.txt.
  Uses `_find_system_python()` to locate Python 3.10+ (not mayapy).
  Returns (success, message).

- **`_register_with_claude_code()`**
  Runs `claude mcp add-json "MayaMCP" '...' --scope user` via subprocess.
  Uses full absolute paths to the MayaMCP venv Python and server script.
  The `--scope user` flag makes it available across all projects.
  Returns (success, message).

- **`_find_system_python()`**
  Locates a Python 3.10+ interpreter on the system. Search order:
  1. `python` on PATH (check version >= 3.10)
  2. `python3` on PATH
  3. `py -3` on Windows (Python Launcher)
  4. Common install locations (C:/Python3*/python.exe)
  Returns path or None.

- **`_find_claude_code()`**
  Locates the `claude` CLI. Search order:
  1. `claude` on PATH
  2. Common npm global install locations
  3. `%APPDATA%/npm/claude.cmd` on Windows
  Returns path or None.

- **`_update_maya_mcp()`**
  Runs `git pull` in the MayaMCP directory. Called during update checks,
  not on every launch.

### Error Handling

All failures are logged but do NOT block the editor from launching.
The artist never sees an error dialog for MCP setup. The worst case is
that Claude Code doesn't have scene access — everything else still works.

Specific failure modes:
- **Git not installed**: Log warning, skip clone. Scene access unavailable.
- **No system Python 3.10+**: Log warning, skip venv creation.
- **pip install fails** (no internet): Log warning. Setup retries next launch.
- **Claude Code not installed**: Log info (expected — user may not use it).
  Registration skipped, will retry when triggered again.
- **~/.claude.json doesn't exist**: Claude Code hasn't been run yet.
  Registration skipped, will retry next launch.

### First-Time Setup Timing

The git clone + pip install takes ~30-60 seconds on a decent connection.
This only happens once. Since it runs in a background thread, the editor
is fully usable during this time.

A subtle, temporary status bar message shows during first-time setup:
- "Setting up AI scene access..." (during clone/install)
- "AI scene access ready" (on completion, fades after 5 seconds)
- Nothing shown on subsequent launches (everything already installed)

If setup fails silently, no message is shown. The artist doesn't know
MCP exists — they just won't have scene tools in Claude Code.

---

## Integration: Maya Plugin (`mca_maya/plugin_main.py`)

```python
def initializePlugin(plugin):
    # --- Existing: venv setup ---
    venv_manager.setup()

    # --- Existing: register command, etc. ---
    ...

    # --- NEW: ensure MayaMCP is ready (background thread) ---
    from mca_core import mcp_setup
    mcp_setup.ensure_maya_mcp(background=True)
```

The command port (7001) is already open by default in Maya for MEL.
MayaMCP uses this default port. No additional port setup needed.

---

## Integration: Standalone (`mca_qt/editor_panel.py`)

In the DCC connection success callback (after adapter.connect() succeeds
for a Maya adapter):

```python
def _on_dcc_connected(self, adapter):
    # ... existing connection success handling ...

    if adapter.dcc_type == DCCType.MAYA:
        from mca_core import mcp_setup
        mcp_setup.ensure_maya_mcp(background=True)
```

---

## Integration: Status Bar

Add an optional status callback to `ensure_maya_mcp()` so the editor panel
can show subtle progress messages:

```python
def ensure_maya_mcp(background=True, status_callback=None):
    """
    :param callable status_callback: Optional function(str) called with
        status messages. Used by the UI to show progress in the status bar.
        If None, messages are only logged.
    """
```

The editor panel passes its status bar update function:

```python
mcp_setup.ensure_maya_mcp(
    background=True,
    status_callback=self._set_status_message
)
```

Status messages (only shown during first-time setup):
- "Setting up AI scene access..."
- "AI scene access ready"

On subsequent launches, nothing is shown (setup completes instantly).

---

## Claude Code Configuration Details

The registration adds this to `~/.claude.json` under the user scope:

```json
{
    "mcpServers": {
        "MayaMCP": {
            "command": "C:/Users/<user>/mca_preferences/mcp_servers/MayaMCP/.venv/Scripts/python.exe",
            "args": [
                "C:/Users/<user>/mca_preferences/mcp_servers/MayaMCP/src/maya_mcp_server.py"
            ]
        }
    }
}
```

All paths are absolute. The `--scope user` flag ensures this is available
in every project the artist works in, not just the current directory.

After registration, the next time Claude Code launches (new terminal tab
or restart), it automatically starts the MayaMCP server process and
connects to it. Claude Code handles the MCP server lifecycle — the MCA
Editor doesn't need to manage the process.

---

## What Claude Code Can Do Once Connected

These tools are available to Claude Code automatically:

**Basic Scene Operations**
- List objects by type (meshes, cameras, lights, materials, shapes)
- Create primitives (cube, sphere, cylinder, cone, lights, cameras)
- Get/set any object attribute
- Select objects
- New scene, open scene, save scene

**Advanced Modeling**
- Complex model creation (cars, trees, buildings, cups, chairs)
- Mesh operations (extrude, bevel, subdivide, boolean, combine, bridge)
- NURBS curves (line, circle, spiral, helix, star, gear)
- Curve-based modeling (extrude, loft, revolve, sweep)
- Material creation/assignment (lambert, phong, wood, marble, chrome, glass)
- Object organization (group, parent, align, distribute)
- Complete scene generation (city, forest, living room, office, park)

The artist doesn't need to know these tools exist. They just talk to
Claude Code naturally:

```
"What's in my scene?"
"Add a spot light pointing at the character"
"The elbow deformation looks wrong, can you check the skinning?"
"Create a simple outdoor environment with trees and lighting"
```

---

## Extending with Custom Tools (Future)

MayaMCP supports adding custom tools by dropping Python files in
`src/mayatools/thirdparty/`. These survive `git pull` updates.

Future custom tools we'd want for professional workflows:
- Skin weight inspection and repair
- Animation curve analysis
- Node graph / connection inspection
- Scene hierarchy dump (full outliner tree)
- Reference management
- Undo/redo exposure

These would ship as part of the MCA Editor and get copied into
MayaMCP's thirdparty directory during setup. But that's a later phase.

---

## Implementation Order

### Phase 1: Core (This Session)
1. Write `mca_core/mcp_setup.py`
2. Add `ensure_maya_mcp()` call to `plugin_main.py` (Maya embedded)
3. Add `ensure_maya_mcp()` call to connection callback (standalone)
4. Status bar integration for first-time setup messages
5. Test end-to-end: load plugin → setup runs → open terminal →
   launch Claude Code → "what's in my scene?" → it answers

### Phase 2: Robustness (Next Session)
1. Periodic update check (git pull, maybe weekly)
2. Recovery from corrupted clone/venv
3. Handle Claude Code not yet installed (retry on next terminal open)
4. Handle edge case: Maya connection drops and reconnects

### Phase 3: Custom Tools (Later)
1. Ship custom tool files with MCA Editor
2. Copy them into MayaMCP's thirdparty directory during setup
3. Rigging, skinning, animation, node graph tools
4. Eventually: consider building our own MCP server using the
   InternalMayaAdapter for zero-latency in-process communication

---

## Prerequisites

These are Claude Code prerequisites, not MCA Editor prerequisites.
Artists who want AI scene access need:

- **Node.js 18+** — Required by Claude Code
- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **Git** — For cloning MayaMCP
- **Python 3.10+** — System Python for MayaMCP's venv (NOT mayapy)

If any of these are missing, MCP setup silently skips and the terminal
still works for everything else. No error dialogs, no blocked workflows.
