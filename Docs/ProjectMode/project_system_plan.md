# MCA Editor — Project System Plan

## Goal

When an artist is developing tools, rigs, or pipeline code for a DCC app,
they can open their codebase as a project in MCA Editor and work on it
directly — with their code live on `sys.path`, inline execution against
the DCC, and a refresh button that reloads changes without restarting.
No manual path setup, no `userSetup.py` hacks, no context-switching to
an external IDE.

The project system is the feature that moves MCA Editor from "better
Script Editor" to "actual development environment inside your DCC."

---

## Two Modes, One Layout

The editor has two modes controlled by the existing toolbar button:

### Simple Mode (Current Default)
- Workspace locked to `mca_preferences/scripts/`
- Buffer-based editing (Python_1.py, MEL_1.mel)
- Quick scripts, one-offs, experimentation
- The "Maya Script Editor replacement" experience

### Project Mode
- Workspace pointed at a project folder (user-selected)
- Full file tree of the codebase
- `sys.path` managed from project settings
- Refresh button with configurable behavior
- The "I'm developing tools" experience

### What Changes Between Modes

| Element | Simple Mode | Project Mode |
|---------|-------------|--------------|
| Workspace tree | Locked to `scripts/` | Project root folder |
| Workspace header | "WORKSPACE" | Project name |
| Mode button text | "Simple" | Project name or "Project" |
| Title bar | "MCA Editor" | "MCA Editor — Project Name" |
| Refresh button | Hidden | Visible in toolbar |
| sys.path | `scripts/` + `site-packages/` | Project's `python_paths` |
| Terminal cwd | `scripts/` | Project root |
| Buffer files | Stored in `scripts/` | Stored in `scripts/` (still available) |

### What Stays the Same

Everything else. Output panel, editor tabs, terminal, tool stripes,
sidebar panels (Open Editors, Outline), find/replace, all menus,
code execution, completions, diagnostics. The layout is identical.
No panels appear or disappear. It's a context change, not a UI change.

---

## The Project File

A project is a folder containing an `.mca-project` file (JSON) at its
root. This is the only requirement — no enforced directory structure,
no mandatory folders, fully flexible.

### Format

```json
{
    "version": 1,
    "name": "Character Pipeline",

    "python_paths": [
        "src",
        "lib",
        "third_party/vendor"
    ],

    "excluded_folders": [
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "build",
        "dist"
    ],

    "refresh_mode": "path_only",
    "refresh_script": null,
    "refresh_function": null,
    "lightweight_reload_on_save": false,
    "lightweight_reload_on_execute": false,

    "startup_script": null,

    "maya": {
        "startup_script": null,
        "mel_paths": []
    },

    "unreal": {
        "startup_script": null,
        "content_paths": []
    },

    "blender": {
        "startup_script": null,
        "addon_paths": []
    },

    "motionbuilder": {
        "startup_script": null
    }
}
```

### Field Reference

**Core Fields**

- **`version`** — Schema version for future migration. Starts at 1.
- **`name`** — Display name shown in title bar, mode button, workspace
  header. Defaults to the folder name if not set.

**Path Management**

- **`python_paths`** — List of directories (relative to project root)
  to add to `sys.path`. Order matters — first entry has highest priority.
  These are injected into the DCC's interpreter on project open and
  removed on project close.
- **`excluded_folders`** — Directories hidden from the workspace tree.
  Does not affect `sys.path` or execution, purely visual. Sensible
  defaults provided on project creation.

**Refresh System**

- **`refresh_mode`** — One of three values:
  - `"path_only"` (default) — Refresh button re-injects `python_paths`
    into `sys.path`. Safe, no side effects, sub-second.
  - `"smart_reload"` — Refresh button walks `sys.modules`, finds stale
    modules under the project's `python_paths`, reloads in dependency
    order using `importlib.reload()`.
  - `"custom"` — Refresh button executes the user's script/function.
- **`refresh_script`** — Path (relative to project root) to a Python
  file executed when refresh_mode is `"custom"`. Example:
  `"src/tools/reload_all.py"`.
- **`refresh_function`** — Optional function name within `refresh_script`
  to call instead of executing the whole file. Example:
  `"reload_codebase"`. If null, the entire script is exec'd.

**Lightweight Reload (Independent of Refresh Button)**

- **`lightweight_reload_on_save`** — When true, saving a Python file
  triggers `importlib.reload()` on that specific module (if it's in
  `sys.modules`). Fast, targeted. If the reload errors, the error shows
  in output and the user can hit the full refresh button.
- **`lightweight_reload_on_execute`** — When true, before executing
  highlighted code, check all project modules in `sys.modules` for
  files modified since their last import. Reload stale ones. Then
  execute the code.

These two flags ALWAYS use the safe importlib approach regardless of
what `refresh_mode` is set to. They never trigger the custom script.

**Startup Scripts**

- **`startup_script`** — DCC-agnostic startup script (relative path).
  Executed once when the project opens and a DCC is connected. Use for
  cross-DCC initialization.
- **`maya.startup_script`** — Maya-specific startup. Executed after the
  generic `startup_script` when connected to Maya. Use for shelf setup,
  plugin registration, Maya-specific config.
- **`maya.mel_paths`** — MEL script directories to add to Maya's
  `MAYA_SCRIPT_PATH` equivalent.
- Similar blocks for `unreal`, `blender`, `motionbuilder` — each DCC
  gets its own section for DCC-specific paths and startup.

---

## Project Discovery and Creation

### Opening a Project

Three ways to open a project:

1. **Mode button dropdown** → "Open Project..." → folder picker.
   If the selected folder has `.mca-project`, open it. If not, offer
   to create one.
2. **Mode button dropdown** → "Recent Projects" → list of previously
   opened projects with paths.
3. **File menu** → "Open Project..." (same as #1).

### Creating a Project

When opening a folder without `.mca-project`:

1. Dialog: "This folder doesn't have an MCA project file. Create one?"
2. If yes, show a simple setup dialog:
   - Project name (defaults to folder name)
   - Python paths to scan for (auto-detect: look for `src/`, `lib/`,
     `python/`, `scripts/`, or any folder containing `__init__.py`)
   - Excluded folders (pre-populated with common defaults)
3. Write `.mca-project` to the folder root.
4. Open the project.

### Auto-Detection of Python Paths

When creating a new project, scan the folder for likely Python source
directories. Heuristics:

- Folders containing `__init__.py` at depth 1-2
- Common names: `src`, `lib`, `python`, `scripts`, `tools`, `pipeline`
- The root folder itself (if it contains `.py` files directly)

Present these as checkboxes in the setup dialog, pre-checked. User can
add/remove before confirming. This helps less experienced users who
wouldn't know what "python_paths" means — they just see their folder
names and check the ones that have code.

---

## sys.path Management

### Injection

When a project opens and a DCC is connected (or local execution is
active), the project's `python_paths` are resolved to absolute paths
and inserted at the front of `sys.path`:

```python
# Project root: C:/Users/ncomes/repos/character_pipeline
# python_paths: ["src", "lib", "third_party/vendor"]
#
# Injected (in order):
#   C:/Users/ncomes/repos/character_pipeline/src
#   C:/Users/ncomes/repos/character_pipeline/lib
#   C:/Users/ncomes/repos/character_pipeline/third_party/vendor
```

The injection uses the same adapter mechanism already in place:

- **Local execution**: Direct `sys.path.insert()` in the local namespace
- **Maya TCP** (`maya_adapter.py`): `sys.path.insert()` injected into
  the command wrapper (same pattern as workspace paths today)
- **Maya Internal** (`internal_maya_adapter.py`): Direct `sys.path`
  manipulation (same process)
- **Future adapters**: Each adapter's `set_workspace_paths()` method
  handles its DCC's path mechanism

### Removal

When switching back to Simple mode or closing a project, the injected
paths are removed from `sys.path`. This prevents stale paths from
accumulating across project switches.

Note: modules already imported from those paths remain in `sys.modules`.
This is Python's standard behavior and is expected. A full refresh
would be needed to truly unload them.

### Path Validation UI

The project settings panel shows each `python_paths` entry with a
status indicator:

- Green: Path exists and is on `sys.path`
- Yellow: Path exists but is NOT on `sys.path` (needs refresh)
- Red: Path does not exist on disk
- Gray: Path has not been checked yet (no DCC connected)

This helps diagnose the #1 Maya TD problem: "why can't Python find my
module?" — the answer is usually visible in this list.

---

## The Refresh Button

### Appearance

Split button in the toolbar, visible only in Project mode:

- **Main click area**: Runs the current refresh action
- **Dropdown arrow**: Opens a menu with mode selection and settings

The button icon could be a circular arrow (standard refresh icon).
Tooltip shows the current mode: "Refresh (re-inject paths)" or
"Refresh (custom: reload_all.py)".

### Dropdown Menu

```
[Refresh Button ▾]
  ─────────────────────────
  ● Re-inject Paths Only        (refresh_mode: path_only)
  ○ Smart Module Reload          (refresh_mode: smart_reload)
  ○ Custom Script                (refresh_mode: custom)
  ─────────────────────────
  Configure Custom Script...
  ─────────────────────────
  Project Settings...
```

### Refresh Mode: path_only (Default)

The safe option. Re-runs the sys.path injection:

1. Remove any previously injected project paths from `sys.path`
2. Re-read `python_paths` from the project file (in case it changed)
3. Re-inject all paths at the front of `sys.path`

This handles the common cases:
- User added a new folder to `python_paths`
- User pip-installed a package into the project's venv
- User pulled new code that added a new subpackage
- Path order got corrupted by another tool

Sub-second execution. No module reloading, no side effects.

### Refresh Mode: smart_reload

Automated module reloading for users who don't have their own system:

1. Do everything `path_only` does (re-inject paths)
2. Walk `sys.modules` and find all modules whose `__file__` is under
   any of the project's `python_paths`
3. Build a dependency graph by inspecting each module's imports
4. Reload in leaf-first order (dependencies before dependents)
5. Report results in the output panel: "Reloaded 12 modules (3 skipped)"

**Dependency ordering algorithm:**
- For each project module in `sys.modules`, inspect its `__dict__` for
  references to other project modules
- Build a DAG, topologically sort it
- Reload from leaves inward
- If circular dependencies are detected, reload them in file-modified-
  time order (best effort) and log a warning

**Modules skipped:**
- Anything not under the project's `python_paths`
- `__init__.py` modules are reloaded last (after their submodules)
- Modules that raise on reload get an error logged, then skipped

This mode takes 1-5 seconds depending on codebase size. Good enough
for most development workflows, but power users with complex init
sequences will want custom mode.

### Refresh Mode: custom

Runs the user's own reload system:

1. Do everything `path_only` does (re-inject paths)
2. If `refresh_function` is set:
   - Import the module from `refresh_script`
   - Call the function: `module.function()`
3. If only `refresh_script` is set (no function):
   - `exec(open(script_path).read())` in the DCC's `__main__` namespace

The script runs in the DCC's interpreter via the adapter — same
mechanism as inline execution. For Maya embedded, this means the
script has full access to `maya.cmds`, `pymel`, etc.

Example custom refresh that Nathan might use:

```python
# src/tools/reload_all.py

def reload_codebase():
    """Tear down and restart the entire tool depot."""
    from my_pipeline import depot
    depot.shutdown()
    
    # Clear all project modules from sys.modules
    import sys
    to_remove = [k for k in sys.modules if k.startswith("my_pipeline")]
    for k in to_remove:
        del sys.modules[k]
    
    # Re-import and initialize
    from my_pipeline import depot
    depot.startup()
```

---

## Lightweight Reload (On Save / On Execute)

Completely independent from the refresh button. These use safe
`importlib.reload()` and never trigger the custom script.

### On Save

When `lightweight_reload_on_save` is true and the user saves a Python
file that is part of the project:

1. Resolve the saved file path to a module name using `python_paths`
   (e.g., `src/rigging/spine.py` → `rigging.spine`)
2. Check if that module name is in `sys.modules`
3. If yes, call `importlib.reload(sys.modules["rigging.spine"])`
4. If the reload succeeds: log debug message, no output panel noise
5. If the reload fails: show the error in the output panel with a hint:
   "Module reload failed for rigging.spine — try a full Refresh (F5)"

This only reloads the single saved module. It does NOT chase
dependencies. This is intentional — it's meant to be fast and safe.
If a change affects multiple modules, the user hits the refresh button.

### On Execute

When `lightweight_reload_on_execute` is true and the user runs code
(Execute, Execute Line, or Execute All):

1. Walk `sys.modules` for all project modules
2. For each, compare `os.path.getmtime(module.__file__)` against a
   stored timestamp from the last reload/import
3. Any modules with newer file times get `importlib.reload()`
4. Then execute the user's code as normal

This catches the common workflow: edit a utility module in one tab,
switch to a test script in another tab, highlight and run. The stale
module gets reloaded before the test code uses it.

If any reload fails, the error is shown in output and execution
continues with the stale module. The user sees the error and knows
to hit the full refresh.

### Why These Are Separate From the Refresh Button

The refresh button might run a custom script that takes several seconds
and tears down the entire depot. You don't want that happening every
time you save a file or run a line of code. The lightweight options are
specifically designed to be fast, safe, and invisible — they handle the
80% case (single module changed) and defer the 20% case (structural
changes) to the manual refresh.

---

## Mode Switching Flow

### Simple → Project

1. User clicks mode button → dropdown → "Open Project..."
2. Folder picker dialog opens
3. User selects a folder
4. If `.mca-project` exists:
   a. Load project settings
   b. Unlock workspace tree, set root to project folder
   c. Apply `excluded_folders` filter to the tree
   d. Inject `python_paths` into DCC (if connected) and local namespace
   e. Update title bar, mode button text, workspace header
   f. Show refresh button in toolbar
   g. Start terminal in project root (if terminal is open)
   h. Run `startup_script` if configured and DCC is connected
   i. Save project path in recent projects list
5. If `.mca-project` does NOT exist:
   a. Show "Create project?" dialog
   b. If yes → project creation flow → then step 4
   c. If no → open folder as workspace anyway (no project features,
      just unlocked tree — this is still useful for browsing)

### Project → Simple

1. User clicks mode button → dropdown → "Switch to Simple"
2. Remove project's `python_paths` from `sys.path`
3. Re-lock workspace tree to `scripts/`
4. Update title bar, mode button, workspace header
5. Hide refresh button
6. Terminal cwd unchanged (user can navigate manually)
7. Buffer files in `scripts/` are still there, tabs still open

### Project → Different Project

1. User clicks mode button → dropdown → "Open Project..." or recent
2. Same as Project → Simple, then Simple → Project with new folder
3. Or shortcut: just swap the workspace root and re-inject paths
   without the intermediate Simple state

---

## Project Settings Panel

Accessible from:
- Refresh button dropdown → "Project Settings..."
- Mode button dropdown → "Project Settings..."
- Edit menu → "Project Settings..." (only visible in Project mode)

### Layout

A dialog (not a tab in the existing Settings dialog — project settings
are per-project, not global). Similar structure to the settings dialog
but simpler.

**General Tab**
- Project name (text field)
- Project root (read-only, shows path)

**Python Paths Tab**
- List of paths with add/remove/reorder buttons
- Each entry shows: relative path, absolute path, status indicator
- "Add Folder..." button opens folder picker (constrained to project)
- "Detect Paths" button re-runs the auto-detection heuristic
- Drag to reorder (order = sys.path priority)

**Refresh Tab**
- Radio buttons for refresh_mode (path_only / smart_reload / custom)
- Custom script path picker (enabled when custom is selected)
- Custom function name field (optional)
- Checkboxes for lightweight_reload_on_save and lightweight_reload_on_execute
- Help text explaining each option in plain language

**Startup Tab**
- Generic startup script path picker
- DCC-specific startup script path picker (label changes based on
  connected DCC: "Maya Startup Script", "Blender Startup Script", etc.)
- DCC-specific path fields (MEL paths for Maya, etc.)

**Excluded Folders Tab**
- List of folder names/patterns to hide from the workspace tree
- Add/remove buttons
- Common defaults pre-populated

---

## Persistence

### Project-Level (`.mca-project` file)
Everything in the project file format above. Committed to version
control, shared between team members.

### User-Level (`mca_preferences/`)
- **Recent projects list** — ordered by last-opened date
- **Last active project** — restored on editor launch (if the user
  was in Project mode when they closed the editor)
- **Per-project UI state** — splitter sizes, open tabs, terminal state.
  Stored under `mca_preferences/project_sessions/<project_hash>/`
  using the same session manifest system (v3) already in place.

### Why Separate?

The `.mca-project` file is intentionally lean — it's meant to be
committed to git and shared. No user-specific UI state, no absolute
paths, no machine-specific configuration. Just the project definition.

User-specific state (which tabs were open, splitter positions, which
files were expanded in the tree) lives in `mca_preferences/` where it
belongs.

---

## DCC Adapter Integration

### Existing Methods (Already Implemented)

These methods on the adapter base class already handle path injection:

- `set_workspace_paths(paths)` — sets paths for command wrapper injection
- `_wrap_python_for_port()` (Maya TCP) — injects `sys.path.insert()`
- Direct `sys.path` manipulation (Maya Internal, local execution)

### New Methods Needed

- **`remove_paths(paths)`** — remove specific entries from `sys.path`
  in the DCC. Needed for clean project switching.
- **`reload_module(module_name)`** — execute `importlib.reload()` for
  a specific module in the DCC. Used by lightweight reload.
- **`get_sys_path()`** — query the DCC's current `sys.path`. Used by
  the path validation UI to show actual state.
- **`run_file(file_path)`** — execute a Python file in the DCC (not
  a string, the actual file). Used for startup scripts and custom
  refresh scripts. Differs from `send_python()` in that it uses
  `exec(open(...).read())` instead of the base64 command wrapper.

These are on the base adapter class, so they apply to all current and
future DCC adapters. Each adapter implements the mechanism appropriate
for its DCC.

---

## Inline Execution in Project Mode

Inline execution (highlight code, Ctrl+Enter) works identically to
Simple mode. The only differences are environmental:

1. `sys.path` already has the project's paths, so imports resolve
2. If `lightweight_reload_on_execute` is on, stale modules get
   reloaded before the code runs
3. The execution target is the same — Maya's `__main__` namespace
   (or local namespace if no DCC connected)

The highlight-and-execute workflow is one of MCA Editor's core
strengths. Project mode enhances it without changing it.

---

## Workspace Tree in Project Mode

### Filtering

The tree hides folders matching `excluded_folders`. These are matched
by name (not path), so `"__pycache__"` hides ALL `__pycache__` folders
at any depth. For path-based exclusion, prefix with `/`:
`"/build/temp"` only hides `<project_root>/build/temp`.

### File Watching (Future Enhancement)

In Phase 1, the tree refreshes on manual "R" button click (same as
Simple mode). A future phase could add `QFileSystemWatcher` for
automatic updates when files change on disk. Not critical for launch.

### Buffer Files

Buffer files (Python_1.py, MEL_1.mel) still live in
`mca_preferences/scripts/`. They are NOT visible in the project tree.
The user can still access them by switching to Simple mode. This keeps
the project tree clean — it only shows the actual codebase.

The "New" button in Project mode creates a new file in the project
folder (with a "Save As" dialog), not a buffer file. This is a
behavioral difference from Simple mode.

---

## Terminal Integration

When in Project mode:
- Terminal opens with cwd set to the project root
- The project's `python_paths` are available in the terminal's
  environment via `PYTHONPATH` (so `python -c "import my_module"` works)
- Claude Code launched in the terminal automatically has context about
  the project structure

---

## Cross-DCC Design

The project file is DCC-agnostic at the top level. The `python_paths`,
`refresh_mode`, `refresh_script`, and `excluded_folders` work the same
way in every DCC. DCC-specific settings live in their own sections.

When the editor opens a project, it reads the core fields plus the
section matching the currently connected DCC. If no DCC is connected,
only the core fields apply (local execution still benefits from
`python_paths`).

This means a single project file works across all DCCs. A studio with
shared rigging code used in both Maya and MotionBuilder can have one
`.mca-project` with both sections configured. Artists open the same
project in whichever DCC they're working in.

---

## Implementation Phases

### Phase 1: Foundation
- `.mca-project` file reading/writing (`mca_core/project.py`)
- Mode switching (Simple ↔ Project) in `editor_panel.py`
- Workspace tree unlock and project root binding
- `sys.path` injection via existing adapter `set_workspace_paths()`
- `sys.path` removal on project close
- Refresh button (path_only mode only — the safe default)
- Project creation dialog (folder picker + auto-detect paths)
- Title bar / mode button / workspace header updates
- Recent projects list persistence
- Terminal cwd set to project root

### Phase 2: Refresh System
- Smart reload mode (dependency graph, ordered `importlib.reload()`)
- Custom script mode (script/function execution via adapter)
- Refresh button dropdown with mode switching
- Lightweight reload on save
- Lightweight reload on execute
- Module staleness tracking (file modification times)
- Error handling with "try full Refresh" hints in output

### Phase 3: Project Settings UI
- Project settings dialog (5 tabs)
- Python paths editor with drag-to-reorder and status indicators
- Refresh configuration UI
- Startup script configuration
- Excluded folders editor
- Path validation display (green/yellow/red indicators)

### Phase 4: Session & Polish
- Per-project session state (open tabs, splitter sizes, etc.)
- Restore last project on launch
- Project switching without intermediate Simple state
- Startup script execution on project open + DCC connect
- DCC-specific path injection (MEL paths, Unreal content paths)
- "New File" in project mode creates in project folder

### Phase 5: Cross-DCC (Later)
- Blender adapter `set_workspace_paths()` implementation
- Unreal adapter path injection
- MotionBuilder adapter support
- DCC-specific project settings sections
- Per-DCC startup script execution

---

## File Impact Estimate

### New Files
- `mca_core/project.py` — Project file loading, saving, validation,
  path resolution, creation dialog logic
- `mca_core/module_reloader.py` — Smart reload: dependency graph,
  staleness tracking, ordered importlib.reload()
- `mca_qt/widgets/project_settings_dialog.py` — Project settings UI
- `mca_qt/widgets/refresh_button.py` — Split button widget with
  dropdown mode menu

### Modified Files
- `mca_qt/editor_panel.py` — Mode switching, refresh button, project
  state management, lightweight reload hooks
- `mca_editor/ui/main_window.py` — Same changes for standalone window
- `mca_qt/widgets/sidebar.py` — Unlock workspace tree, excluded folder
  filtering, project-aware "New File" behavior
- `mca_core/config/settings.py` — Recent projects, last project path,
  per-project session directory
- `mca_core/session_manager.py` — Per-project session storage
- `mca_core/adapters/base_adapter.py` — New methods: `remove_paths()`,
  `reload_module()`, `get_sys_path()`, `run_file()`
- `mca_core/adapters/maya_adapter.py` — Implement new adapter methods
- `mca_core/adapters/internal_maya_adapter.py` — Implement new methods

---

## Open Questions

1. **Should the project file track a Python version?** Studios often
   need to match Maya's Python version. Could warn if the project
   targets 3.9 but Maya 2025 runs 3.11.

2. **Should `python_paths` support glob patterns?** e.g., `"plugins/*"`
   to add all subdirectories of a folder. Nice for plugin systems but
   adds complexity.

3. **Should we support `.env` files?** Some studios use `.env` for
   environment variables. Could read these and inject into the DCC's
   environment on project open.

4. **Git integration?** The workspace tree could show git status
   (modified/untracked/staged indicators) on files. Useful but
   potentially complex to implement well.

5. **Multiple projects?** Some artists work across multiple repos
   simultaneously (tools repo + show repo). Should the editor support
   opening multiple projects in split workspace panels? Or is one
   project at a time sufficient?
