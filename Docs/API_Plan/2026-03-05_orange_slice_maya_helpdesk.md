# MCA Editor — Orange Slice Maya Helpdesk
## Implementation Plan — Document 17

**Date:** 2026-03-05
**Status:** Approved for implementation
**Version target:** 0.1.8

---

## Goal

Upgrade Orange Slice from a script-writing assistant into a full Maya helpdesk.
Users should be able to ask anything — "how do I rig a spine?", "where is the
Paint Skin Weights tool?", "what does the nCloth nucleus node do?" — and get
accurate, version-aware answers without any scraping, vector databases, or
extra infrastructure.

---

## Architecture: Three Tiers

### Tier 1 — Enriched System Prompt (Always-On, Zero Cost)
Inject a compact Maya knowledge block into every prompt when Maya is the
connected DCC. Covers UI layout, menu sets, and common workflow patterns.
This tier answers the majority of "where is X" questions with zero tool calls.

### Tier 2 — `get_maya_command_help` Tool (On-Demand, Version-Accurate)
A new tool that executes `cmds.help()` inside the live Maya session. Returns
exact flag/argument documentation for the installed version. This is the
authoritative source for any scripting question.

### Tier 3 — `search_maya_docs` Tool (On-Demand, Broad Coverage)
A web search tool scoped to Autodesk's help site and community forums. Handles
UI workflow questions, rigging concepts, animation techniques — anything that
goes beyond scripting into general Maya usage.

---

## Files to Change

| Action | File |
|--------|------|
| EDIT   | `mca_core/plugins/ai_chat/system_prompt.py` |
| EDIT   | `mca_core/plugins/ai_chat/tools.py` |
| EDIT   | `mca_core/plugins/ai_chat/tool_handler.py` |
| EDIT   | `mca_core/__init__.py` (version bump) |

No new files. No new dependencies. No build pipeline changes.

---

## Tier 1: Enriched System Prompt

### File: `mca_core/plugins/ai_chat/system_prompt.py`

The existing `build_system_prompt()` function already injects DCC type and
version. Extend it to conditionally append a Maya helpdesk block.

#### Change: Add `_MAYA_HELPDESK_BLOCK` constant

Add this constant near the top of the file, after the existing imports:

```python
# --- Maya Helpdesk Knowledge Block ---
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

**Menu Sets** (top-left dropdown, or hotkeys F2–F6):
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
```

#### Change: Inject the block conditionally in `build_system_prompt()`

In the existing function, after the DCC context is assembled (where it
currently appends `dcc_type`, `dcc_version`, etc.), add:

```python
# Inject Maya helpdesk knowledge when Maya is connected.
# Skipped for other DCCs to keep context tight.
from mca_core.adapters import DCCType  # already imported elsewhere, confirm location
if dcc_type == DCCType.MAYA:
    prompt_parts.append(_MAYA_HELPDESK_BLOCK)
```

The exact insertion point depends on how `prompt_parts` is assembled in the
current implementation — place it after the DCC version line, before the
"open files" context. Confirm the exact variable names by reading the current
`system_prompt.py` before editing.

---

## Tier 2: `get_maya_command_help` Tool

This tool calls `cmds.help()` inside the live Maya session and returns the
output. It uses the existing `execute_in_dcc` path — no new IPC, no new
infrastructure.

### File: `mca_core/plugins/ai_chat/tools.py`

#### Change: Add tool schema to the `TOOLS` list

Add this entry in the `execute` category section, after `execute_in_dcc`:

```python
{
    "type": "function",
    "function": {
        "name": "get_maya_command_help",
        "description": (
            "Returns the official help documentation for a Maya Python command "
            "from the live Maya session. Use this for any scripting question to "
            "get exact flag names, types, and descriptions for the user's "
            "installed Maya version. Examples: 'polyCube', 'skinCluster', "
            "'parentConstraint', 'keyframe', 'joint'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The Maya Python command name to look up. "
                        "Use the maya.cmds form (e.g. 'polyCube', not "
                        "'maya.cmds.polyCube'). Case-sensitive."
                    )
                }
            },
            "required": ["command"]
        }
    }
},
```

### File: `mca_core/plugins/ai_chat/tool_handler.py`

#### Change: Add handler case for `get_maya_command_help`

In the main dispatch function (likely a large `if/elif` block or dict lookup),
add:

```python
elif tool_name == "get_maya_command_help":
    command = arguments.get("command", "").strip()
    if not command:
        return {"error": "No command name provided."}

    # Build a script that calls cmds.help() and captures its output.
    # cmds.help() prints to stdout rather than returning a string, so we
    # redirect it via a StringIO capture inside the Maya session.
    script = (
        "import sys, io, maya.cmds as cmds\n"
        "_buf = io.StringIO()\n"
        "_old = sys.stdout\n"
        "sys.stdout = _buf\n"
        "try:\n"
        f"    cmds.help('{command}')\n"
        "finally:\n"
        "    sys.stdout = _old\n"
        "print(_buf.getvalue())\n"
    )

    # Reuse the existing execute_in_dcc handler path. The api reference
    # is whatever is already used for execute_in_dcc — confirm the variable
    # name from the current tool_handler.py implementation.
    result = api.execute_in_dcc(script)

    if not result or not result.strip():
        return {
            "error": (
                f"No help found for '{command}'. Check the spelling — "
                "Maya command names are case-sensitive (e.g. 'polyCube' "
                "not 'PolyCube')."
            )
        }

    return {"command": command, "help": result.strip()}
```

**Implementation note:** The exact call to `api.execute_in_dcc()` must match
how the existing `execute_in_dcc` tool handler invokes it. Read the current
`tool_handler.py` before writing this — confirm the API object reference and
return value format.

---

## Tier 3: `search_maya_docs` Tool

A web search scoped to Autodesk's help site and Maya community. Handles
questions that go beyond scripting into general workflow, rigging concepts,
animation techniques, and UI navigation for complex features.

### File: `mca_core/plugins/ai_chat/tools.py`

#### Change: Add tool schema

Add this entry in a new `search` category at the end of the `TOOLS` list:

```python
# --- Search ---

{
    "type": "function",
    "function": {
        "name": "search_maya_docs",
        "description": (
            "Searches Autodesk's Maya documentation and community forums for "
            "answers about Maya workflows, UI locations, rigging techniques, "
            "animation methods, rendering, and any other Maya topic. Use this "
            "when the question requires finding specific documentation, is "
            "version-specific, involves a complex workflow not covered by "
            "get_maya_command_help, or when you want to verify UI locations "
            "in a specific Maya version."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The search query. Be specific. Include Maya version "
                        "if relevant (e.g. 'Maya 2025 paint skin weights UI'). "
                        "Good examples: 'Maya 2024 IK spline handle setup', "
                        "'Maya bind skin options proximity', "
                        "'Maya nCloth collision thickness attribute'."
                    )
                }
            },
            "required": ["query"]
        }
    }
},
```

### File: `mca_core/plugins/ai_chat/tool_handler.py`

#### Change: Add handler case for `search_maya_docs`

```python
elif tool_name == "search_maya_docs":
    query = arguments.get("query", "").strip()
    if not query:
        return {"error": "No search query provided."}

    # Scope the search to Autodesk help and community to avoid noise.
    # Adding site constraints as search terms is more portable than
    # using operator syntax which varies by search backend.
    scoped_query = f"{query} site:help.autodesk.com OR site:area.autodesk.com"

    try:
        import urllib.request
        import urllib.parse
        import json

        # Use DuckDuckGo Instant Answer API — no key required, no scraping.
        # Returns structured results including AbstractText and RelatedTopics.
        encoded = urllib.parse.quote(scoped_query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"

        req = urllib.request.Request(url, headers={"User-Agent": "MCAEditor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []

        # AbstractText is a direct answer summary if one exists.
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "summary": data["AbstractText"],
                "url": data.get("AbstractURL", "")
            })

        # RelatedTopics are search result links.
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:120],
                    "url": topic.get("FirstURL", "")
                })

        if not results:
            return {
                "query": query,
                "message": (
                    "No results found. Try rephrasing the query or being more "
                    "specific about the Maya version and feature name."
                )
            }

        return {"query": query, "results": results}

    except Exception as exc:
        return {
            "error": f"Search failed: {exc}",
            "suggestion": (
                "Try asking the question directly — the answer may be in "
                "Orange Slice's built-in Maya knowledge."
            )
        }
```

**Important note on the search backend:** DuckDuckGo's Instant Answer API is
zero-dependency and requires no API key, making it safe for offline-first
environments. However, its coverage of deep Maya docs pages is limited. If
results are consistently poor in testing, the fallback is to switch to a
simple `urllib` GET against Google with a `site:` operator — results are
better but Google may rate-limit headless requests. Evaluate DuckDuckGo first;
document the outcome in the session notes.

---

## Suggestion Chips Update

The welcome screen in `chat_widget.py` has suggestion chips that appear when
the panel is empty. With Maya helpdesk mode active, these should reflect the
new capabilities.

### File: `mca_core/plugins/ai_chat/chat_widget.py`

#### Change: Update Maya suggestion chips

The current chips are script-writing focused. When Maya is the connected DCC,
replace or augment them with helpdesk-flavored chips. The exact implementation
depends on how chips are currently defined — locate the list constant or
`_build_welcome_screen()` method and update the Maya chip set to include:

```python
MAYA_HELPDESK_CHIPS = [
    "How do I bind skin to a skeleton?",
    "Where is Paint Skin Weights?",
    "How do I set up an IK spine rig?",
    "What does the skinCluster node do?",
    "How do I bake animation to keyframes?",
    "Where are blend shape controls?",
]
```

Show 4 of these at random on each welcome screen display so users see variety.
Mix in 1–2 scripting-focused chips from the existing set so the panel doesn't
feel narrowed.

This file ships as `.pyc` — remember to add it to the Cython/PYC exclusion
list in `build_maya.py` if it isn't already covered by the existing entry.

---

## Version Bump

### File: `mca_core/__init__.py`

Bump `0.1.7` → `0.1.8`.

---

## Verification Checklist

After implementation, verify each tier independently:

**Tier 1 — System Prompt:**
- [ ] Ask "where is Paint Skin Weights?" — answer should be exact menu path
      with no tool calls fired
- [ ] Ask "what hotkey toggles smooth mesh preview?" — answered from prompt
- [ ] Ask "where is the Graph Editor?" — correct path returned
- [ ] Confirm the Maya block does NOT appear in a non-Maya session (if
      testable in standalone mode)

**Tier 2 — `get_maya_command_help`:**
- [ ] Ask "what flags does skinCluster support?" — tool fires, returns
      `cmds.help('skinCluster')` output from live Maya
- [ ] Ask "how do I use the joint command in Python?" — tool fires for `joint`
- [ ] Ask about a misspelled command (e.g. "polycube") — returns clear error
      message about case sensitivity

**Tier 3 — `search_maya_docs`:**
- [ ] Ask "how do I rig a ribbon spine in Maya 2025?" — tool fires, returns
      results with Autodesk URLs
- [ ] Ask about nCloth setup — search returns relevant result
- [ ] Confirm graceful failure if network is unavailable (offline Maya session)

---

## What Was Deliberately Left Out

- **Vector database / RAG pipeline** — Rejected. DuckDuckGo + `cmds.help()`
  provides better coverage with zero infrastructure overhead. Scraping 5000+
  docs adds a maintenance burden that doesn't justify the marginal improvement.
- **Caching search results** — Not needed at this stage. Queries are
  infrequent and varied; a cache would rarely hit.
- **Studio/pipeline docs corpus** — Valid future feature for enterprise tier
  (internal rigging guides, naming conventions, custom tool docs). Out of
  scope for this release.
