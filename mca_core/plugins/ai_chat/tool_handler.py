"""
MCA Core - AI Chat Tool Handler.

Dispatch function that routes tool calls from the AI assistant to the
appropriate MCAPluginAPI method and returns JSON-serializable results.

All tool execution happens on the **main thread** (safe for EditorAPI
and Qt widget access).  The ChatWorker signals back here via Qt's
auto-marshaling signal-slot mechanism.

Dependencies:
    - json (stdlib) — for argument parsing and result serialization
    - urllib (stdlib) — for search_maya_docs web requests
"""

import json
import logging
import traceback
import urllib.parse
import urllib.request

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

    if tool_name == "get_maya_command_help":
        return _handle_maya_command_help(api, args)

    if tool_name == "execute_locally":
        return api.execute_locally(args["code"])

    # --- Search Tools ---
    if tool_name == "search_maya_docs":
        return _handle_search_maya_docs(args)

    # --- Output Tools ---
    if tool_name == "write_output":
        return api.write_output(
            args["text"],
            level=args.get("level", "info"),
        )

    # Unknown tool — should not happen if TOOLS and handler are in sync.
    raise ValueError("Unknown tool: '{}'".format(tool_name))


# --- Maya Command Help Handler -----------------------------------------------

def _handle_maya_command_help(api, args):
    """
    Look up Maya command documentation via ``cmds.help()`` in the live session.

    Builds a small Python script that captures the ``cmds.help()`` output
    (which prints to stdout) via a StringIO redirect, then sends it to Maya
    through the existing ``execute_in_dcc`` pipeline.

    :param MCAPluginAPI api: The plugin API instance.
    :param dict args: Parsed tool arguments (expects ``command`` key).
    :return: Dict with ``command`` and ``help`` keys, or ``error``.
    :rtype: dict
    """
    command = args.get("command", "").strip()
    if not command:
        return {"error": "No command name provided."}

    # Build a script that captures cmds.help() output through StringIO.
    # Uses repr() to safely quote the command name and prevent injection.
    script = (
        "import sys, io, maya.cmds as cmds\n"
        "_buf = io.StringIO()\n"
        "_old = sys.stdout\n"
        "sys.stdout = _buf\n"
        "try:\n"
        "    cmds.help({cmd})\n"
        "finally:\n"
        "    sys.stdout = _old\n"
        "print(_buf.getvalue())\n"
    ).format(cmd=repr(command))

    # Execute inside the live Maya session via the existing DCC adapter.
    result = api.execute_in_dcc(script)

    # The result is a dict with 'output' and possibly 'error' keys.
    output = ""
    if isinstance(result, dict):
        output = result.get("output", "")
    elif isinstance(result, str):
        output = result

    # Check for meaningful output.
    if not output or not output.strip():
        return {
            "error": (
                "No help found for '{}'. Check the spelling — "
                "Maya command names are case-sensitive (e.g. 'polyCube' "
                "not 'PolyCube')."
            ).format(command)
        }

    return {"command": command, "help": output.strip()}


# --- Maya Docs Search Handler ------------------------------------------------

def _handle_search_maya_docs(args):
    """
    Search Autodesk Maya documentation via DuckDuckGo Instant Answer API.

    Uses the zero-dependency ``urllib`` approach with no API key.  Scopes
    the query to ``help.autodesk.com`` and ``area.autodesk.com`` to bias
    results toward official Autodesk content.

    :param dict args: Parsed tool arguments (expects ``query`` key).
    :return: Dict with ``query`` and ``results`` keys, or ``error``.
    :rtype: dict
    """
    query = args.get("query", "").strip()
    if not query:
        return {"error": "No search query provided."}

    # Scope the search to Autodesk help and community to reduce noise.
    scoped_query = "{} site:help.autodesk.com OR site:area.autodesk.com".format(query)

    try:
        # DuckDuckGo Instant Answer API — no key required, no scraping.
        encoded = urllib.parse.quote(scoped_query)
        url = "https://api.duckduckgo.com/?q={}&format=json&no_html=1&skip_disambig=1".format(encoded)

        req = urllib.request.Request(url, headers={"User-Agent": "MCAEditor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []

        # AbstractText is a direct answer summary if one exists.
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "summary": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
            })

        # RelatedTopics are search result links — take the top 5.
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:120],
                    "url": topic.get("FirstURL", ""),
                })

        if not results:
            return {
                "query": query,
                "message": (
                    "No results found. Try rephrasing the query or being more "
                    "specific about the Maya version and feature name."
                ),
            }

        return {"query": query, "results": results}

    except Exception as exc:
        logger.warning("Maya docs search failed: %s", exc)
        return {
            "error": "Search failed: {}".format(str(exc)),
            "suggestion": (
                "Try asking the question directly — the answer may be in "
                "Orange Slice's built-in Maya knowledge."
            ),
        }
