"""
MCA Editor MCP Server — Self-contained MCP server for editor control.

Runs inside MayaMCP's venv (which provides the ``mcp`` package).  Zero imports
from ``mca_core`` — this file is copied to the deployment directory at setup
time and must be completely standalone.

Connects to the MCA Editor's JSON-RPC server (``editor_api_server.py``) via
TCP to forward tool calls.  Port discovery uses ``api_port.json`` written by
the editor on startup.

Architecture::

    Claude Code
        |
        |--- MCP stdio ---> mca_editor_server.py (this file)
        |                       |
        |                       |--- TCP JSON-RPC ---> editor_api_server.py (port 7003+)
        |                                                  |
        |                                                  |--- QTimer drain ---> EditorAPI

MCP Tool Set (17 tools):
    - editor_get_state: Full editor state snapshot
    - editor_open_file: Open a file in the editor
    - editor_save_file: Save the active file
    - editor_list_open_files: List all open tabs
    - editor_get_text: Get active buffer content
    - editor_set_text: Replace active buffer content
    - editor_insert_text: Insert text at position
    - editor_replace_range: Replace a range of text
    - editor_navigate_to: Open file and jump to line
    - editor_execute_in_dcc: Execute code in Maya
    - editor_execute_locally: Execute Python locally
    - editor_write_output: Write to output panel
    - editor_get_output: Get recent output text
    - editor_read_disk_file: Read file from disk
    - editor_write_disk_file: Write file to disk
    - editor_open_project: Open a folder as a project
    - editor_close_project: Close the active project

Dependencies:
    - mcp (installed in MayaMCP's .venv)
    - pydantic_core (pulled in by mcp)

Side effects:
    - Opens TCP connections to the editor's JSON-RPC server on each tool call
    - Writes log file to ``mca_preferences/mcp_servers/mca_editor_server.log``
"""

import asyncio
import ctypes
import json
import logging
import os
import platform
import socket
import sys

import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

# --- Constants ----------------------------------------------------------------

__version__ = "1.0.0"

# Discovery file written by the editor's JSON-RPC server.
_PREFS_DIR = os.path.join(os.path.expanduser("~/Documents"), "mca_preferences")
_DISCOVERY_FILE = os.path.join(_PREFS_DIR, "api_port.json")

# TCP connection timeout to the editor's JSON-RPC server (seconds).
CONNECT_TIMEOUT_SECS = 5.0

# Response read timeout (seconds) — the editor should respond quickly.
RECV_TIMEOUT_SECS = 10.0

# Recv buffer size.
RECV_BUFFER_SIZE = 4096

# Module-level logger — configured in __main__.
logger = logging.getLogger("MCAEditorMCP")


# =============================================================================
# PID Staleness Check
# =============================================================================

def _is_process_alive(pid):
    """
    Check if a process with the given PID is still running.

    Uses ``os.kill(pid, 0)`` on POSIX and ``OpenProcess`` on Windows.
    Returns False if the process is definitely dead; True if it might
    be alive (or we can't tell).

    :param int pid: The process ID to check.
    :return: True if the process appears to be alive.
    :rtype: bool
    """
    if pid is None or pid <= 0:
        return False

    if platform.system() == "Windows":
        # Use kernel32.OpenProcess to check if the PID exists.
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        try:
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            # If ctypes fails, assume alive to avoid false negatives.
            return True
    else:
        # POSIX: signal 0 checks existence without sending a real signal.
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we don't have permission — it's alive.
            return True
        except Exception:
            return True


# =============================================================================
# JSON-RPC Client
# =============================================================================

def _read_discovery():
    """
    Read the editor's port discovery file.

    Returns the parsed JSON dict, or None if the file doesn't exist
    or is unreadable.

    :return: Discovery dict with ``port``, ``pid``, ``started`` keys.
    :rtype: dict or None
    """
    if not os.path.isfile(_DISCOVERY_FILE):
        return None

    try:
        with open(_DISCOVERY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read discovery file: %s", exc)
        return None


def _call_editor(method, params=None):
    """
    Send a JSON-RPC request to the editor's API server and return the result.

    Reads ``api_port.json`` on each call so it handles editor restarts
    and port changes automatically.  Checks the PID before connecting
    to give fast, clear errors when the editor has crashed.

    :param str method: The JSON-RPC method name (e.g. ``get_state``).
    :param dict params: Keyword arguments for the method (optional).
    :return: The result value from the JSON-RPC response.
    :rtype: dict or list or str or None
    :raises RuntimeError: If the editor is not running or not reachable.
    """
    # Step 1: Read the discovery file.
    discovery = _read_discovery()
    if discovery is None:
        raise RuntimeError(
            "MCA Editor is not running. The discovery file was not found at: "
            "{}".format(_DISCOVERY_FILE)
        )

    port = discovery.get("port")
    pid = discovery.get("pid")

    # Step 2: Check if the editor process is still alive.
    if pid and not _is_process_alive(pid):
        raise RuntimeError(
            "MCA Editor process (PID {}) is no longer running. "
            "Please restart the editor.".format(pid)
        )

    if not port:
        raise RuntimeError(
            "Discovery file exists but contains no port. "
            "The editor may not have started its API server."
        )

    # Step 3: Build the JSON-RPC request.
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1,
    }
    request_line = json.dumps(request) + "\n"

    # Step 4: Send the request and read the response.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT_SECS)

    try:
        sock.connect(("127.0.0.1", port))
        sock.sendall(request_line.encode("utf-8"))

        # Read the newline-delimited response.
        sock.settimeout(RECV_TIMEOUT_SECS)
        response_data = b""
        while True:
            chunk = sock.recv(RECV_BUFFER_SIZE)
            if not chunk:
                break
            response_data += chunk
            # JSON-RPC responses are newline-delimited — stop at first newline.
            if b"\n" in response_data:
                break

    except ConnectionRefusedError:
        raise RuntimeError(
            "Cannot connect to MCA Editor on port {}. "
            "The editor may have restarted — try again.".format(port)
        )
    except socket.timeout:
        raise RuntimeError(
            "Connection to MCA Editor on port {} timed out.".format(port)
        )
    except OSError as exc:
        raise RuntimeError(
            "Socket error connecting to MCA Editor on port {}: {}".format(port, exc)
        )
    finally:
        sock.close()

    # Step 5: Parse the JSON-RPC response.
    response_str = response_data.decode("utf-8", errors="replace").strip()
    if not response_str:
        raise RuntimeError("Empty response from MCA Editor")

    try:
        response = json.loads(response_str)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON response from editor: {}".format(exc))

    # Check for JSON-RPC error.
    if "error" in response:
        error = response["error"]
        msg = error.get("message", "Unknown error") if isinstance(error, dict) else str(error)
        raise RuntimeError("Editor API error: {}".format(msg))

    return response.get("result")


# =============================================================================
# Tool Definitions
# =============================================================================

# Each tool is defined as a dict with name, description, and JSON schema.
# The call_tool handler dispatches by name to the appropriate _call_editor() call.

_TOOLS = [
    {
        "name": "editor_get_state",
        "description": (
            "Get a comprehensive snapshot of the MCA Editor's current state. "
            "Returns the active file, cursor position, selection, all open tabs, "
            "project info, DCC connection status, and server info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "editor_open_file",
        "description": (
            "Open a file in the MCA Editor. If the file is already open in a tab, "
            "switches to that tab. Returns success/failure status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute path to the file to open.",
                },
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "editor_save_file",
        "description": "Save the currently active file in the MCA Editor.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "editor_list_open_files",
        "description": (
            "List all open tabs across all editor groups in the MCA Editor. "
            "Returns name, path, language, and modified status for each tab."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "editor_get_text",
        "description": (
            "Get the full text content of the active editor buffer. "
            "Returns the in-memory content (including unsaved changes)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "editor_set_text",
        "description": (
            "Replace the entire content of the active editor buffer with new text. "
            "This modifies the buffer in-memory; use editor_save_file to persist."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The new content to replace the entire buffer with.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "editor_insert_text",
        "description": (
            "Insert text at a specific position in the active editor. "
            "If line/col are omitted, inserts at the current cursor position. "
            "Line and column numbers are 1-based."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to insert.",
                },
                "line": {
                    "type": "integer",
                    "description": "1-based line number to insert at (optional).",
                },
                "col": {
                    "type": "integer",
                    "description": "1-based column number to insert at (optional).",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "editor_replace_range",
        "description": (
            "Replace a range of text in the active editor. Selects from "
            "(start_line, start_col) to (end_line, end_col) and replaces with "
            "the given text. All positions are 1-based. Pass empty text to delete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_line": {
                    "type": "integer",
                    "description": "1-based start line number.",
                },
                "start_col": {
                    "type": "integer",
                    "description": "1-based start column number.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-based end line number.",
                },
                "end_col": {
                    "type": "integer",
                    "description": "1-based end column number.",
                },
                "text": {
                    "type": "string",
                    "description": "Replacement text (empty string to delete the range).",
                },
            },
            "required": ["start_line", "start_col", "end_line", "end_col", "text"],
        },
    },
    {
        "name": "editor_navigate_to",
        "description": (
            "Open a file in the MCA Editor and jump to a specific line. "
            "Combines open_file + go_to_line in one call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute path to the file to open.",
                },
                "line": {
                    "type": "integer",
                    "description": "1-based line number to jump to (default: 1).",
                    "default": 1,
                },
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "editor_execute_in_dcc",
        "description": (
            "Execute code in the connected DCC application (e.g. Maya). "
            "Returns success status, stdout output, and any error messages. "
            "The DCC must be connected to the editor for this to work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Source code to execute in the DCC.",
                },
                "language": {
                    "type": "string",
                    "description": "Language: 'python' or 'mel' (default: 'python').",
                    "default": "python",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "editor_execute_locally",
        "description": (
            "Execute Python code locally in the editor's process with stdout "
            "capture. Uses a persistent namespace so variables survive across "
            "calls. Returns success, output, and error."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute locally.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "editor_write_output",
        "description": (
            "Write a message to the MCA Editor's output panel. "
            "Supports different levels: 'output', 'info', 'warning', 'error', 'success'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The message text to display.",
                },
                "level": {
                    "type": "string",
                    "description": "Message level (default: 'info').",
                    "enum": ["output", "info", "warning", "error", "success"],
                    "default": "info",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "editor_get_output",
        "description": (
            "Get recent text from the MCA Editor's output panel. "
            "Useful for checking execution results or editor messages."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default: 100).",
                    "default": 100,
                },
            },
        },
    },
    {
        "name": "editor_read_disk_file",
        "description": (
            "Read a file directly from disk, bypassing editor buffers. "
            "If the file is open with unsaved edits, this returns the on-disk "
            "version. Use editor_get_text for the active buffer content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "editor_write_disk_file",
        "description": (
            "Write content directly to a file on disk. Creates parent "
            "directories if they don't exist. Does not update editor buffers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file.",
                },
            },
            "required": ["filepath", "content"],
        },
    },
    {
        "name": "editor_open_project",
        "description": (
            "Open a folder as a project in the MCA Editor. Sets the sidebar "
            "tree root and enables project-level features like find-in-files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the project root directory.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "editor_close_project",
        "description": "Close the currently active project in the MCA Editor.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

# Mapping from MCP tool name to JSON-RPC method name.
_TOOL_METHOD_MAP = {
    "editor_get_state": "get_state",
    "editor_open_file": "open_file",
    "editor_save_file": "save_file",
    "editor_list_open_files": "list_open_files",
    "editor_get_text": "get_text",
    "editor_set_text": "set_text",
    "editor_insert_text": "insert_text",
    "editor_replace_range": "replace_range",
    "editor_navigate_to": "navigate_to",
    "editor_execute_in_dcc": "execute_in_dcc",
    "editor_execute_locally": "execute_locally",
    "editor_write_output": "write_output",
    "editor_get_output": "get_output_text",
    "editor_read_disk_file": "read_disk_file",
    "editor_write_disk_file": "write_disk_file",
    "editor_open_project": "open_project",
    "editor_close_project": "close_project",
}


# =============================================================================
# MCP Server
# =============================================================================

server = Server("MCAEditorMCP")


@server.list_tools()
async def handle_list_tools():
    """
    Handle MCP ``list_tools`` request — return all editor tools.

    :return: List of Tool objects.
    :rtype: list
    """
    logger.info("Client requested tool list (%d tools available).", len(_TOOLS))
    return [
        Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["inputSchema"],
        )
        for t in _TOOLS
    ]


@server.call_tool()
async def handle_call_tool(name, arguments):
    """
    Handle MCP ``call_tool`` request — forward to the editor via JSON-RPC.

    Looks up the JSON-RPC method name from the tool name, sends the
    request to the editor, and returns the result as MCP TextContent.

    :param str name: The MCP tool name (e.g. ``editor_get_state``).
    :param dict arguments: Tool arguments from Claude Code.
    :return: List of MCP TextContent objects.
    :rtype: list
    """
    logger.info("Calling tool '%s' with arguments: %s", name, arguments)

    # Look up the JSON-RPC method for this tool.
    rpc_method = _TOOL_METHOD_MAP.get(name)
    if not rpc_method:
        error_msg = "Unknown tool: '{}'".format(name)
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps(
            {"success": False, "message": error_msg}))]

    try:
        # Forward the call to the editor's JSON-RPC server.
        params = arguments if arguments else {}
        result = _call_editor(rpc_method, params)

        # Convert the result to a JSON string for MCP.
        if result is None:
            result_text = json.dumps({"success": True, "result": None})
        elif isinstance(result, str):
            result_text = result
        else:
            result_text = json.dumps(result, default=str)

        return [TextContent(type="text", text=result_text)]

    except RuntimeError as exc:
        # Expected errors (editor not running, connection failed, etc.).
        error_msg = str(exc)
        logger.warning("Tool '%s' error: %s", name, error_msg)
        return [TextContent(type="text", text=json.dumps(
            {"success": False, "message": error_msg}))]

    except Exception as exc:
        # Unexpected errors.
        logger.critical("Tool '%s' failed unexpectedly: %s", name, exc, exc_info=True)
        error_msg = "Unexpected error in tool '{}': {}".format(name, exc)
        return [TextContent(type="text", text=json.dumps(
            {"success": False, "message": error_msg}))]


# =============================================================================
# Async Entry Point
# =============================================================================

async def run():
    """
    Start the MCP stdio server loop.

    Runs until the client (Claude Code) disconnects.
    """
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="MCAEditorMCP",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":

    # --- Logging Setup --------------------------------------------------------

    # Log to the deployment directory (mca_preferences/mcp_servers/).
    log_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(log_dir, "mca_editor_server.log")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    logger.info("MCA Editor MCP Server v%s starting up", __version__)
    logger.info("Discovery file: %s", _DISCOVERY_FILE)

    # Verify the discovery file is readable at startup (informational only).
    discovery = _read_discovery()
    if discovery:
        logger.info("Editor discovered: port=%s, pid=%s, started=%s",
                     discovery.get("port"), discovery.get("pid"),
                     discovery.get("started"))
    else:
        logger.warning(
            "Discovery file not found or unreadable. "
            "Tools will return errors until the editor starts."
        )

    # --- Run ------------------------------------------------------------------

    asyncio.run(run())
