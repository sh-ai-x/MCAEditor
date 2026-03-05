"""
MCA Core - AI Chat Tool Handler.

Dispatch function that routes tool calls from the AI assistant to the
appropriate MCAPluginAPI method and returns JSON-serializable results.

All tool execution happens on the **main thread** (safe for EditorAPI
and Qt widget access).  The ChatWorker signals back here via Qt's
auto-marshaling signal-slot mechanism.

Dependencies:
    - json (stdlib) — for argument parsing and result serialization
"""

import json
import logging
import traceback

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Tool Dispatch -----------------------------------------------------------

def execute_tool(api, tool_name, arguments_json):
    """
    Execute a tool call and return the result as a JSON string.

    Parses the arguments JSON, dispatches to the appropriate MCAPluginAPI
    method, and wraps the result in a JSON-serializable format.  Errors
    are caught and returned as error strings rather than raised.

    :param MCAPluginAPI api: The plugin API instance.
    :param str tool_name: The name of the tool to execute.
    :param str arguments_json: JSON string of tool arguments.
    :return: JSON string with the tool result.
    :rtype: str
    """
    # Parse arguments from JSON.
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as exc:
        logger.warning("Invalid tool arguments JSON: %s", exc)
        return json.dumps({"error": "Invalid arguments JSON: {}".format(str(exc))})

    try:
        result = _dispatch(api, tool_name, args)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("Tool '%s' failed: %s", tool_name, exc, exc_info=True)
        return json.dumps({
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })


def _dispatch(api, tool_name, args):
    """
    Route a tool call to the appropriate API method.

    :param MCAPluginAPI api: The plugin API instance.
    :param str tool_name: The tool name.
    :param dict args: Parsed tool arguments.
    :return: The tool result (must be JSON-serializable).
    :rtype: dict or list or str
    :raises ValueError: If the tool name is unknown.
    """
    # --- State Tools ---
    if tool_name == "get_editor_state":
        return api.get_state()

    if tool_name == "list_open_files":
        return api.list_open_files()

    if tool_name == "get_output":
        max_lines = args.get("max_lines", 100)
        return {"output": api.get_output_text(max_lines=max_lines)}

    # --- Read Tools ---
    if tool_name == "get_editor_text":
        text = api.get_text()
        return {"text": text if text is not None else ""}

    if tool_name == "get_selected_text":
        text = api.get_selected_text()
        return {"text": text if text is not None else ""}

    if tool_name == "read_disk_file":
        return api.read_disk_file(args["filepath"])

    # --- Write Tools ---
    if tool_name == "set_editor_text":
        return api.set_text(args["text"])

    if tool_name == "insert_text":
        return api.insert_text(
            args["text"],
            line=args.get("line"),
            col=args.get("col"),
        )

    if tool_name == "replace_range":
        return api.replace_range(
            args["start_line"],
            args["start_col"],
            args["end_line"],
            args["end_col"],
            args["text"],
        )

    if tool_name == "write_disk_file":
        return api.write_disk_file(args["filepath"], args["content"])

    if tool_name == "save_file":
        return api.save_file()

    # --- Navigate Tools ---
    if tool_name == "open_file":
        return api.open_file(args["filepath"])

    if tool_name == "navigate_to":
        return api.navigate_to(args["filepath"], line=args.get("line", 1))

    # --- Execute Tools ---
    if tool_name == "execute_in_dcc":
        return api.execute_in_dcc(
            args["code"],
            language=args.get("language", "python"),
        )

    if tool_name == "execute_locally":
        return api.execute_locally(args["code"])

    # --- Output Tools ---
    if tool_name == "write_output":
        return api.write_output(
            args["text"],
            level=args.get("level", "info"),
        )

    # Unknown tool — should not happen if TOOLS and handler are in sync.
    raise ValueError("Unknown tool: '{}'".format(tool_name))
