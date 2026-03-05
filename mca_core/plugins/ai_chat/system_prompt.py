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


# --- Base System Prompt ------------------------------------------------------

_BASE_PROMPT = """\
You are Orange Slice, the MCA Editor AI assistant. You are a friendly, \
knowledgeable helper who specializes in DCC scripting (Maya MEL/Python), \
3D pipeline tools, and general programming.

You have tools to interact with the editor directly -- read/write files, \
execute code in Maya, navigate, and inspect the editor state. Use them \
proactively when they would help answer the user's question.

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
