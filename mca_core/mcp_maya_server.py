"""
MCA Maya MCP Server — Self-contained MCP server for Maya scene interaction.

Runs inside MayaMCP's venv (which provides the ``mcp`` package).  Zero imports
from ``mca_core`` — this file is copied to the deployment directory at setup
time and must be completely standalone.

Uses MayaMCP's tool .py files for tool discovery and schema generation, but
replaces the communication layer with base64-encoded Python sent directly to
Maya's Python command port (default 7002).  This matches the battle-tested
socket patterns from ``mca_core/adapters/maya_adapter.py``.

Improvements over stock MayaMCP:
    - Python port (7002) instead of MEL port (50007)
    - Base64 encoding instead of MEL ``python("...")`` wrapping (no quote bugs)
    - Single TCP connection per tool call (no second connection for results)
    - Two-phase timeout recv (10s first, 0.2s idle) instead of ``len==1024``
    - 4096 byte recv buffer instead of 1024
    - ``repr()`` / ``json.dumps()`` for arg serialization (no f-string quoting bugs)
    - ``generate_scene`` tool is skipped by name (broken/dangerous)
    - Configurable port via ``--port`` CLI arg or ``MAYA_MEL_PORT`` env var
    - Logging to ``mca_preferences/mcp_servers/`` instead of next to source

Dependencies:
    - mcp (installed in MayaMCP's .venv)
    - pydantic_core (pulled in by mcp)

Side effects:
    - Opens TCP connection to Maya's Python command port on each tool call
    - Writes log file to ``mca_preferences/mcp_servers/mca_maya_server.log``
"""

import argparse
import asyncio
import base64
import importlib
import importlib.util
import inspect
import json
import logging
import os
import pprint as pprint_mod
import socket
import sys
import traceback
from itertools import chain
from typing import get_origin

import mcp.server.stdio
import pydantic_core
from mcp.server.fastmcp.server import Context
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from mcp.server.fastmcp.utilities.types import Image
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

# --- Constants ----------------------------------------------------------------

__version__ = "1.0.0"

# Default Maya MEL command port.  The Python port is MEL + 1.
DEFAULT_MEL_PORT = 7001

# TCP connection timeout (seconds).
CONNECT_TIMEOUT_SECS = 5.0

# Phase 1 recv: wait for Maya to START responding (heavy ops take time).
FIRST_RECV_TIMEOUT_SECS = 10.0

# Phase 2 recv: silence threshold once data is flowing.
IDLE_RECV_TIMEOUT_SECS = 0.2

# Larger buffer than MayaMCP's 1024 to reduce recv loop iterations.
RECV_BUFFER_SIZE = 4096

# Localhost only — Maya's command port should never be network-exposed.
LOCAL_HOST = "127.0.0.1"

# Tool filenames to skip during discovery (known broken/dangerous).
SKIP_TOOLS = {"generate_scene", "__init__"}

# Module-level logger — configured in __main__.
logger = logging.getLogger("MCAMayaMCP")


# =============================================================================
# Maya Connection
# =============================================================================

class MayaConnection:
    """
    TCP connection to Maya's Python command port using base64 encoding.

    Mirrors the proven socket patterns from ``maya_adapter.py:_send_command()``:
    two-phase timeout recv, null byte stripping, newline-terminated commands.
    Uses base64 encoding instead of MEL wrapping to avoid all quoting issues.
    """

    def __init__(self, mel_port=DEFAULT_MEL_PORT, host=LOCAL_HOST):
        """
        Initialize a Maya connection.

        :param int mel_port: Maya's MEL command port (Python port = mel_port + 1).
        :param str host: Hostname (always localhost for Maya).
        """
        # Python port is always one above the MEL port.
        self._python_port = mel_port + 1
        self._host = host

    def run_tool_script(self, script):
        """
        Execute a tool script in Maya and return the result.

        Uses a stdout-redirect wrapper (matching ``maya_adapter.py``) to
        capture results.  ``print()`` inside ``exec()`` on Maya's commandPort
        goes to Maya's Script Editor, NOT back through the socket.  The
        adapter's proven pattern solves this by:

        1. Redirecting stdout to a StringIO buffer before exec()
        2. Running the script (which does ``print(_mcp_maya_results)``)
        3. Restoring stdout
        4. Re-printing the captured buffer — this print IS at the outer
           exec() level and flows back through the socket

        :param str script: Python source code to execute in Maya.
        :return: Parsed result (dict/list if JSON, raw string otherwise).
        :rtype: dict or list or str or None
        """
        # Append result-printing code to the script.  The stdout redirect
        # in _send_command's wrapper will capture this and re-emit it.
        script_with_output = (
            script
            + "\nimport json as _mcp_json\n"
            "try:\n"
            "    _mcp_out = _mcp_json.dumps(_mcp_maya_results)\n"
            "except Exception:\n"
            "    _mcp_out = str(_mcp_maya_results)\n"
            "print(_mcp_out)\n"
        )

        raw = self._send_command(script_with_output, self._python_port)

        if not raw:
            return None

        # Strip the trailing "None" artifact that exec() produces.
        raw = self._strip_exec_none(raw)

        # Try to parse as JSON for structured results.
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass

        return raw

    def _send_command(self, command, port):
        """
        Send a Python command to Maya via double-base64-encoded TCP.

        Uses the same stdout-redirect wrapper as ``maya_adapter.py``:

        1. Outer layer: base64-encoded ``exec(compile(...))`` — single line
           safe for Maya's commandPort.
        2. Inner layer: base64-encoded user code, executed inside a stdout
           redirect.  ``print()`` inside ``exec()`` goes to Maya's Script
           Editor, NOT back through the socket.  The wrapper captures stdout
           to a StringIO buffer, then re-prints it AFTER restoring stdout
           so the output flows through the commandPort socket.

        The two-phase timeout recv matches ``maya_adapter.py`` exactly:
        Phase 1 (first recv): Wait up to 10s for Maya to START responding.
        Phase 2 (subsequent recvs): 0.2s idle timeout = response is done.

        :param str command: Python code to execute.
        :param int port: TCP port (Maya's Python command port).
        :return: Response string from Maya, or None on failure.
        :rtype: str or None
        """
        # Inner base64: the actual code to run.
        inner_b64 = base64.b64encode(command.encode("utf-8")).decode("ascii")

        # Build the stdout-redirect wrapper (mirrors maya_adapter.py:352-377).
        # This is the key pattern that makes results flow back through the
        # commandPort socket instead of disappearing into Maya's console.
        wrapper = (
            "import base64 as __b64, sys as __sys, io as __io, "
            "traceback as __tb\n"
            "__mca_old_stdout = __sys.stdout\n"
            "__sys.stdout = __mca_buf = __io.StringIO()\n"
            "__mca_err = None\n"
            "__mca_code = __b64.b64decode('{}').decode('utf-8')\n"
            "try:\n"
            "    exec(compile(__mca_code, '<mca_mcp>', 'exec'), globals())\n"
            "except Exception as __e:\n"
            "    __mca_err = __e\n"
            "finally:\n"
            "    __sys.stdout = __mca_old_stdout\n"
            "__mca_result = __mca_buf.getvalue()\n"
            "if __mca_result:\n"
            "    print(__mca_result, end='')\n"
            "if __mca_err:\n"
            "    __tb.print_exception(type(__mca_err), __mca_err, "
            "__mca_err.__traceback__)\n"
        ).format(inner_b64)

        # Outer base64: wrap the wrapper for single-line transmission.
        outer_b64 = base64.b64encode(wrapper.encode("utf-8")).decode("ascii")
        wire_command = (
            'import base64; '
            'exec(compile(base64.b64decode("{}").decode("utf-8"), '
            '"<mca_mcp_wrapper>", "exec"))\n'
        ).format(outer_b64)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT_SECS)

        try:
            sock.connect((self._host, port))
            sock.sendall(wire_command.encode("utf-8"))

            # Phase 1: Wait up to 10s for Maya to start responding.
            sock.settimeout(FIRST_RECV_TIMEOUT_SECS)

            response = b""
            while True:
                try:
                    chunk = sock.recv(RECV_BUFFER_SIZE)
                    if not chunk:
                        break
                    response += chunk

                    # Phase 2: Once data is flowing, short idle timeout.
                    sock.settimeout(IDLE_RECV_TIMEOUT_SECS)

                except socket.timeout:
                    # Phase 1: Maya didn't respond at all within 10s.
                    # Phase 2: 0.2s silence = response is done.
                    break

            # Decode and strip null bytes that Maya's commandPort appends.
            decoded = response.decode("utf-8", errors="replace")
            return decoded.replace("\x00", "")

        except ConnectionRefusedError:
            logger.warning(
                "Maya Python port %d not open (Maya may not be running or "
                "command port not enabled).  Tool call will return an error.",
                port,
            )
            return None
        except socket.timeout:
            logger.warning(
                "Connection to Maya port %d timed out after %.1fs.",
                port, CONNECT_TIMEOUT_SECS,
            )
            return None
        except OSError as exc:
            logger.warning("Socket error connecting to Maya port %d: %s", port, exc)
            return None
        finally:
            sock.close()

    @staticmethod
    def _strip_exec_none(result):
        """
        Remove the trailing ``None`` artifact that Maya's exec() path produces.

        When Maya evaluates a command via exec(), the return value is ``None``,
        which gets appended to the output as a literal string.  We strip it
        if it appears at the very end.

        :param str result: Raw result string from Maya.
        :return: Cleaned result.
        :rtype: str
        """
        if not result:
            return result

        stripped = result.rstrip()

        # Remove trailing "None" (case-sensitive, from exec() return).
        if stripped.endswith("None"):
            stripped = stripped[:-4].rstrip()

        return stripped


# =============================================================================
# Tool Discovery (OperationsManager)
# =============================================================================

class OperationsManager:
    """
    Discovers MCP tools from MayaMCP's ``mayatools/`` directory structure.

    Walks directories for ``.py`` files, dynamically loads each module,
    inspects the function signature, and builds MCP ``Tool`` objects with
    JSON schemas.  This is adapted from MayaMCP's ``OperationsManager``
    with defensive improvements (skip list, better error handling).
    """

    def __init__(self):
        """Initialize empty tool and path registries."""
        self._paths = {}
        self._tools = {}

    def has_tool(self, name):
        """
        Check if a tool is registered.

        :param str name: Tool name.
        :return: True if the tool exists.
        :rtype: bool
        """
        return name in self._tools

    def get_tool(self, name):
        """
        Get a Tool by name.

        :param str name: Tool name.
        :return: The Tool object, or None if not found.
        :rtype: Tool or None
        """
        return self._tools.get(name)

    def get_file_path(self, name):
        """
        Get the source file path for a tool.

        :param str name: Tool name.
        :return: Absolute path to the .py file, or None.
        :rtype: str or None
        """
        return self._paths.get(name)

    def get_tools(self):
        """
        Return all registered tools.

        :return: Collection of Tool objects.
        :rtype: list
        """
        return list(self._tools.values())

    def find_tools(self, tool_dirs):
        """
        Walk one or more directories and register all valid tool files.

        Each ``.py`` file must contain a function whose name matches the
        filename (e.g. ``create_object.py`` exports ``create_object``).
        Files in the ``SKIP_TOOLS`` set are silently ignored.

        :param list tool_dirs: List of directory paths to scan.
        """
        for tool_dir in tool_dirs:
            if not os.path.isdir(tool_dir):
                logger.warning("Tool directory not found, skipping: %s", tool_dir)
                continue

            for root, dirs, files in os.walk(tool_dir):
                for filename in files:
                    if not filename.endswith(".py"):
                        continue

                    name = os.path.splitext(filename)[0]

                    # Skip known-bad tools.
                    if name in SKIP_TOOLS:
                        logger.debug("Skipping tool '%s' (in skip list)", name)
                        continue

                    path = os.path.join(root, filename)
                    tool = self._load_tool(name, path)

                    if tool:
                        self._paths[name] = path
                        self._tools[name] = tool
                        logger.debug("Registered tool: %s", name)

        logger.info("Discovered %d tools from %d directories.",
                     len(self._tools), len(tool_dirs))

    def _load_tool(self, name, filepath):
        """
        Load a single tool file and build an MCP Tool from its function signature.

        Uses ``importlib`` to load the module, finds the function matching the
        filename, inspects its signature via ``func_metadata()``, and creates
        a ``Tool`` with the function's docstring as description and its parameter
        annotations as the JSON input schema.

        :param str name: Expected function name (matches filename stem).
        :param str filepath: Absolute path to the .py file.
        :return: MCP Tool object, or None on failure.
        :rtype: Tool or None
        """
        try:
            spec = importlib.util.spec_from_file_location(name, filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, name)
        except Exception as exc:
            logger.warning("Failed to load tool '%s' from %s: %s", name, filepath, exc)
            return None

        func_doc = fn.__doc__ or ""

        # Inspect signature for MCP Context parameter (skip it in schema).
        sig = inspect.signature(fn)
        context_kwarg = None
        for param_name, param in sig.parameters.items():
            if get_origin(param.annotation) is not None:
                continue
            try:
                if issubclass(param.annotation, Context):
                    context_kwarg = param_name
                    break
            except TypeError:
                # annotation is not a class — skip
                continue

        # Build pydantic-based JSON schema from function signature.
        try:
            func_arg_metadata = func_metadata(
                fn,
                skip_names=[context_kwarg] if context_kwarg is not None else [],
            )
            parameters = func_arg_metadata.arg_model.model_json_schema()
        except Exception as exc:
            logger.warning("Failed to extract schema for tool '%s': %s", name, exc)
            return None

        return Tool(
            name=name,
            description=func_doc,
            inputSchema=parameters,
        )


# =============================================================================
# Script Building
# =============================================================================

def load_maya_tool_source(name, filepath, args):
    """
    Load a tool's Python source and build the full execution script.

    Reads the ``.py`` file, wraps it in a scoped function, appends the
    function call with properly serialized arguments, and sets
    ``_mcp_maya_results`` to the return value.

    Arg serialization fixes over stock MayaMCP:
        - Strings: ``repr(v)`` handles all escaping (single quotes, backslashes)
        - Lists/dicts: ``json.dumps(v)`` for safe nested structures
        - Numbers/bools: passed through directly

    :param str name: Tool function name (must match a function in the file).
    :param str filepath: Absolute path to the tool .py file.
    :param dict args: Keyword arguments to pass to the tool function.
    :return: Complete Python script ready to send to Maya.
    :rtype: str
    """
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    # Wrap in scoped function to isolate variables and catch exceptions.
    script = wrap_script_in_scoped_function(source, name, list(args.keys()))

    # Build the function call with serialized arguments.
    call_params = []
    for key, value in args.items():
        serialized = _serialize_arg(value)
        call_params.append("{}={}".format(key, serialized))

    script += "\n_mcp_maya_results = _mcp_maya_scope({})\n".format(", ".join(call_params))

    logger.debug("Built script for tool '%s' (%d chars)", name, len(script))
    return script


def wrap_script_in_scoped_function(source, tool_name, arg_names):
    """
    Wrap tool source code in a ``_mcp_maya_scope()`` function.

    The wrapper function:
        - Receives tool arguments as keyword parameters
        - Defines the tool function inside its scope
        - Calls the tool function and catches exceptions
        - Returns JSON-serialized results (or error dict on failure)

    :param str source: The raw Python source of the tool file.
    :param str tool_name: Name of the function to call inside the source.
    :param list arg_names: List of argument names for the wrapper function.
    :return: The wrapper function source code.
    :rtype: str
    """
    # Indent the tool source to live inside the wrapper function body.
    indented_source = "    " + source.replace("\n", "\n    ")

    # Build the wrapper.  The tool function is defined inside the scope,
    # then called with its arguments forwarded by name.
    arg_list = ", ".join(arg_names)
    call_args = ", ".join("{}={}".format(a, a) for a in arg_names)

    return (
        "def _mcp_maya_scope({arg_list}):\n"
        "    import json\n"
        "    import traceback\n"
        "{indented_source}\n"
        "    try:\n"
        "        results = {tool_name}({call_args})\n"
        "    except Exception as e:\n"
        "        traceback.print_exc()\n"
        "        results = {{'success': False, 'message': 'Error: ' + str(e)}}\n"
        "    if results is not None and not isinstance(results, str):\n"
        "        try:\n"
        "            results = json.dumps(results)\n"
        "        except Exception:\n"
        "            results = str(results)\n"
        "    return results\n"
    ).format(
        arg_list=arg_list,
        indented_source=indented_source,
        tool_name=tool_name,
        call_args=call_args,
    )


def _serialize_arg(value):
    """
    Safely serialize a single argument value for embedding in Python source.

    Fixes the quoting bug in stock MayaMCP where ``f"{k}='{v}'"`` breaks
    on strings containing single quotes.

    :param value: The argument value to serialize.
    :return: Python source representation of the value.
    :rtype: str
    """
    if isinstance(value, str):
        # repr() handles all escaping: quotes, backslashes, unicode.
        return repr(value)
    elif isinstance(value, (list, dict)):
        # json.dumps() for safe nested structures.
        return json.dumps(value)
    elif isinstance(value, bool):
        # Must check bool before int (bool is a subclass of int).
        return "True" if value else "False"
    elif isinstance(value, (int, float)):
        # Numbers pass through directly.
        return str(value)
    elif value is None:
        return "None"
    else:
        # Fallback: repr() for anything unexpected.
        return repr(value)


# =============================================================================
# Result Conversion
# =============================================================================

def convert_to_content(result):
    """
    Convert a tool result to a sequence of MCP content objects.

    Handles strings, dicts, lists, MCP content types, and Image objects.
    Falls back to JSON serialization, then str() for anything else.

    :param result: Raw result from the tool execution.
    :return: List of MCP content objects.
    :rtype: list
    """
    if result is None:
        return []

    if isinstance(result, (TextContent, ImageContent, EmbeddedResource)):
        return [result]

    if isinstance(result, Image):
        return [result.to_image_content()]

    if isinstance(result, (list, tuple)):
        return list(chain.from_iterable(convert_to_content(item) for item in result))

    if not isinstance(result, str):
        try:
            result = json.dumps(pydantic_core.to_jsonable_python(result))
        except Exception:
            result = str(result)

    return [TextContent(type="text", text=result)]


# =============================================================================
# MCP Server
# =============================================================================

server = Server("MCAMayaMCP")

# These get set in __main__ before the server starts.
_operation_manager = None
_mel_port = DEFAULT_MEL_PORT


@server.list_tools()
async def handle_list_tools():
    """
    Handle MCP ``list_tools`` request — return all discovered Maya tools.

    :return: List of Tool objects.
    :rtype: list
    """
    logger.info("Client requested tool list (%d tools available).",
                len(_operation_manager.get_tools()))
    return _operation_manager.get_tools()


@server.call_tool()
async def handle_call_tool(name, arguments):
    """
    Handle MCP ``call_tool`` request — execute a Maya tool.

    Loads the tool source file, builds the execution script with serialized
    arguments, sends it to Maya via base64-encoded TCP, and returns the
    results as MCP content.

    If Maya's Python port is not open (e.g. Maya not running, command port
    not enabled), returns a clean error message — no crash.  Claude Code
    manages server lifecycle and will retry tool calls naturally.

    :param str name: The tool name.
    :param dict arguments: Keyword arguments for the tool.
    :return: List of MCP content objects.
    :rtype: list
    """
    logger.info("Calling tool '%s' with arguments: %s",
                name, pprint_mod.pformat(arguments))

    # Look up the tool's source file.
    path = _operation_manager.get_file_path(name)
    if not path:
        error_msg = "Tool '{}' not found.".format(name)
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps(
            {"success": False, "message": error_msg}))]

    try:
        # Build the execution script with serialized arguments.
        args = arguments if arguments else {}
        script = load_maya_tool_source(name, path, args)

        # Send to Maya and get results.
        maya_conn = MayaConnection(mel_port=_mel_port)
        result = maya_conn.run_tool_script(script)

        # None means the connection failed (Maya not running, port closed).
        # Surface this clearly to Claude so it knows the problem.
        if result is None:
            error_msg = (
                "Cannot connect to Maya's Python port ({}).  Make sure Maya is "
                "running and its command port is enabled.  In Maya, run:\n"
                '  cmds.commandPort(name=":7001", sourceType="mel", echoOutput=True)\n'
                '  cmds.commandPort(name=":7002", sourceType="python", echoOutput=True)'
            ).format(_mel_port + 1)
            logger.error(error_msg)
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "message": error_msg}))]

        # Convert to MCP content format.
        converted = convert_to_content(result)

    except Exception as exc:
        logger.critical("Tool '%s' failed: %s", name, exc, exc_info=True)
        error_msg = "Error: tool '{}' failed. Reason: {}".format(name, exc)
        return [TextContent(type="text", text=json.dumps(
            {"success": False, "message": error_msg}))]

    if converted:
        return converted

    # Tool returned nothing — report success with no data.
    return [TextContent(type="text", text=json.dumps({"success": True}))]


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
                server_name="MCAMayaMCP",
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

    # --- Argument Parsing -----------------------------------------------------

    parser = argparse.ArgumentParser(
        description="MCA Maya MCP Server — connects Claude Code to Maya"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Maya MEL command port (default: {} or MAYA_MEL_PORT env var). "
             "Python port is MEL port + 1.".format(DEFAULT_MEL_PORT),
    )
    parser.add_argument(
        "--tool-dir",
        action="append",
        default=None,
        help="Additional directory of tool .py files to load. "
             "Can be specified multiple times.",
    )
    args = parser.parse_args()

    # Resolve port: CLI arg > env var > default.
    if args.port is not None:
        _mel_port = args.port
    elif os.environ.get("MAYA_MEL_PORT"):
        _mel_port = int(os.environ["MAYA_MEL_PORT"])
    else:
        _mel_port = DEFAULT_MEL_PORT

    # --- Logging Setup --------------------------------------------------------

    # Log to the deployment directory (mca_preferences/mcp_servers/).
    log_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(log_dir, "mca_maya_server.log")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    logger.info("MCA Maya MCP Server v%s starting up", __version__)
    logger.info("Maya MEL port: %d, Python port: %d", _mel_port, _mel_port + 1)

    # --- Tool Discovery -------------------------------------------------------

    # The default tool directory is MayaMCP/src/mayatools/ relative to the
    # deployment location.  Our server lives at:
    #   mca_preferences/mcp_servers/mca_maya_server.py
    # MayaMCP's tools live at:
    #   mca_preferences/mcp_servers/MayaMCP/src/mayatools/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_tool_dir = os.path.join(script_dir, "MayaMCP", "src", "mayatools")

    tool_dirs = [default_tool_dir]

    # Add any extra tool directories from CLI.
    if args.tool_dir:
        tool_dirs.extend(args.tool_dir)

    # Also check for a "thirdparty" directory inside mayatools for custom tools.
    thirdparty_dir = os.path.join(default_tool_dir, "thirdparty")
    if os.path.isdir(thirdparty_dir) and thirdparty_dir not in tool_dirs:
        tool_dirs.append(thirdparty_dir)

    _operation_manager = OperationsManager()
    _operation_manager.find_tools(tool_dirs)

    logger.info("Tool discovery complete.  Starting MCP stdio server...")

    # --- Run ------------------------------------------------------------------

    asyncio.run(run())
