"""
MCA Unreal MCP Server — Self-contained MCP server for Unreal Engine interaction.

Runs inside MayaMCP's venv (which provides the ``mcp`` package).  Zero imports
from ``mca_core`` — this file is copied to the deployment directory at setup
time and must be completely standalone.

Uses custom tool .py files for tool discovery and schema generation.  The
communication layer uses Unreal Engine's Remote Execution protocol (UDP
discovery on 239.0.0.1:6766, TCP execution on the discovered port).

The tool source files (``unreal_tools/``) are NOT executed locally — they are
read as source text, wrapped in a ``_mcp_ue_scope()`` function, serialized
with arguments via ``repr()``/``json.dumps()``, and sent as a code string to
Unreal's Python interpreter via the Remote Execution TCP protocol.

This mirrors the exact pattern from ``mca_maya_server.py`` — the only
difference is the transport layer (UE Remote Execution protocol vs Maya
commandPort base64 encoding).

Dependencies:
    - mcp (installed in MayaMCP's .venv)
    - pydantic_core (pulled in by mcp)

Side effects:
    - Opens UDP multicast socket on 239.0.0.1:6766 for UE discovery
    - Opens TCP connection to UE's Remote Execution port on each tool call
    - Writes log file to ``mca_preferences/mcp_servers/mca_unreal_server.log``
"""

import argparse
import asyncio
import importlib
import importlib.util
import inspect
import json
import logging
import os
import pprint as pprint_mod
import socket
import struct
import uuid
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

# UE Remote Execution multicast group and port for node discovery.
MULTICAST_GROUP = "239.0.0.1"
MULTICAST_PORT = 6766

# Default TCP port for UE Remote Execution (if discovery fails).
DEFAULT_REMOTE_PORT = 6776

# UE Remote Execution protocol magic bytes and version.
PROTOCOL_MAGIC = b"ue_py"
PROTOCOL_VERSION = 2

# TCP connection timeout (seconds).
CONNECT_TIMEOUT_SECS = 5.0

# Phase 1 recv: wait for UE to START responding.
FIRST_RECV_TIMEOUT_SECS = 30.0

# Phase 2 recv: silence threshold once data is flowing.
IDLE_RECV_TIMEOUT_SECS = 0.5

# Buffer size for TCP recv.
RECV_BUFFER_SIZE = 65536

# UDP discovery timeout (seconds).
DISCOVERY_TIMEOUT = 3.0

# Localhost only — Remote Execution should not be network-exposed.
LOCAL_HOST = "127.0.0.1"

# Tool filenames to skip during discovery.
SKIP_TOOLS = {"__init__"}

# Module-level logger — configured in __main__.
logger = logging.getLogger("MCAUnrealMCP")


# =============================================================================
# Unreal Remote Execution Protocol
# =============================================================================

def _build_ue_message(payload_dict):
    """
    Build a UE Remote Execution protocol message.

    Wire format:
        [5 bytes magic "ue_py"]
        [4 bytes version (uint32 LE)]
        [4 bytes payload size (uint32 LE)]
        [N bytes UTF-8 JSON payload]

    :param dict payload_dict: The JSON payload to serialize.
    :return: The complete binary message.
    :rtype: bytes
    """
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    header = PROTOCOL_MAGIC
    header += struct.pack("<I", PROTOCOL_VERSION)
    header += struct.pack("<I", len(payload_bytes))
    return header + payload_bytes


def _parse_ue_message(data):
    """
    Parse a UE Remote Execution protocol message from raw bytes.

    :param bytes data: Raw bytes received from the socket.
    :return: Parsed payload dict, or None if invalid.
    :rtype: dict or None
    """
    # Minimum size: 5 (magic) + 4 (version) + 4 (size) = 13 bytes.
    if len(data) < 13:
        return None

    magic = data[:5]
    if magic != PROTOCOL_MAGIC:
        return None

    payload_size = struct.unpack("<I", data[9:13])[0]
    payload_bytes = data[13:13 + payload_size]

    if len(payload_bytes) < payload_size:
        return None

    try:
        return json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# =============================================================================
# Unreal Connection
# =============================================================================

class UnrealConnection:
    """
    TCP connection to UE's Python interpreter via Remote Execution protocol.

    Mirrors the proven socket patterns from ``mca_maya_server.py``:
    two-phase timeout recv, clean error handling, idempotent connections.
    """

    def __init__(self, port=DEFAULT_REMOTE_PORT, host=LOCAL_HOST):
        """
        Initialize an Unreal connection.

        :param int port: UE Remote Execution TCP port.
        :param str host: Hostname (always localhost for UE).
        """
        self._port = port
        self._host = host

    def run_tool_script(self, script):
        """
        Execute a tool script in Unreal and return the result.

        Sends the script via the Remote Execution TCP protocol.  The script
        should produce its result by printing JSON to stdout, which the
        stdout redirect wrapper captures and returns.

        :param str script: Python source code to execute in Unreal.
        :return: Parsed result (dict/list if JSON, raw string otherwise).
        :rtype: dict or list or str or None
        """
        # Append result-printing code to the script.
        script_with_output = (
            script
            + "\nimport json as _mcp_json\n"
            "try:\n"
            "    _mcp_out = _mcp_json.dumps(_mcp_ue_results)\n"
            "except Exception:\n"
            "    _mcp_out = str(_mcp_ue_results)\n"
            "print(_mcp_out)\n"
        )

        raw = self._send_command(script_with_output)

        if not raw:
            return None

        # Try to parse as JSON for structured results.
        raw = raw.strip()
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass

        return raw if raw else None

    def _send_command(self, command):
        """
        Send a Python command to UE via the Remote Execution TCP protocol.

        The command is sent as a "C" (command) type message with exec_mode "F"
        (file execution).  The response is a "R" (response) message containing
        the output.

        Two-phase timeout recv (matching maya_adapter.py pattern):
        Phase 1: Wait up to 30s for UE to start responding.
        Phase 2: 0.5s idle timeout = response is complete.

        :param str command: Python code to execute.
        :return: Response string from UE, or None on failure.
        :rtype: str or None
        """
        # Build the command payload.
        command_id = str(uuid.uuid4())
        payload = {
            "type": "C",
            "id": command_id,
            "body": command,
            "exec_mode": "F",
        }

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT_SECS)

        try:
            sock.connect((self._host, self._port))
            msg = _build_ue_message(payload)
            sock.sendall(msg)

            # Phase 1: Wait for UE to start responding.
            sock.settimeout(FIRST_RECV_TIMEOUT_SECS)

            response_data = b""
            while True:
                try:
                    chunk = sock.recv(RECV_BUFFER_SIZE)
                    if not chunk:
                        break
                    response_data += chunk

                    # Check if we have a complete message.
                    if len(response_data) >= 13:
                        payload_size = struct.unpack("<I", response_data[9:13])[0]
                        if len(response_data) >= 13 + payload_size:
                            break

                    # Phase 2: Once data is flowing, short idle timeout.
                    sock.settimeout(IDLE_RECV_TIMEOUT_SECS)

                except socket.timeout:
                    break

            if not response_data:
                return None

            resp_payload = _parse_ue_message(response_data)
            if resp_payload is None:
                # Fallback: try to decode raw response as text.
                return response_data.decode("utf-8", errors="replace")

            # Extract the output from the response payload.
            # UE Remote Execution puts output in the "output" field.
            output = resp_payload.get("output", "")
            if not output:
                # Some UE versions use "body" for the response.
                output = resp_payload.get("body", "")

            return output

        except ConnectionRefusedError:
            logger.warning(
                "UE Remote Execution port %d not open (Unreal may not be "
                "running or Remote Execution not enabled).",
                self._port,
            )
            return None
        except socket.timeout:
            logger.warning(
                "Connection to UE port %d timed out after %.1fs.",
                self._port, CONNECT_TIMEOUT_SECS,
            )
            return None
        except OSError as exc:
            logger.warning("Socket error connecting to UE port %d: %s", self._port, exc)
            return None
        finally:
            sock.close()


# =============================================================================
# Tool Discovery (OperationsManager)
# =============================================================================

class OperationsManager:
    """
    Discovers MCP tools from the ``unreal_tools/`` directory structure.

    Identical to the Maya version: walks directories for ``.py`` files,
    dynamically loads each module, inspects the function signature, and
    builds MCP ``Tool`` objects with JSON schemas.
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
        filename (e.g. ``create_actor.py`` exports ``create_actor``).
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

def load_unreal_tool_source(name, filepath, args):
    """
    Load a tool's Python source and build the full execution script.

    Reads the ``.py`` file, wraps it in a scoped function, appends the
    function call with properly serialized arguments, and sets
    ``_mcp_ue_results`` to the return value.

    :param str name: Tool function name (must match a function in the file).
    :param str filepath: Absolute path to the tool .py file.
    :param dict args: Keyword arguments to pass to the tool function.
    :return: Complete Python script ready to send to Unreal.
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

    script += "\n_mcp_ue_results = _mcp_ue_scope({})\n".format(", ".join(call_params))

    logger.debug("Built script for tool '%s' (%d chars)", name, len(script))
    return script


def wrap_script_in_scoped_function(source, tool_name, arg_names):
    """
    Wrap tool source code in a ``_mcp_ue_scope()`` function.

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

    # Build the wrapper.
    arg_list = ", ".join(arg_names)
    call_args = ", ".join("{}={}".format(a, a) for a in arg_names)

    return (
        "def _mcp_ue_scope({arg_list}):\n"
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

    :param value: The argument value to serialize.
    :return: Python source representation of the value.
    :rtype: str
    """
    if isinstance(value, str):
        return repr(value)
    elif isinstance(value, (list, dict)):
        return json.dumps(value)
    elif isinstance(value, bool):
        # Must check bool before int (bool is a subclass of int).
        return "True" if value else "False"
    elif isinstance(value, (int, float)):
        return str(value)
    elif value is None:
        return "None"
    else:
        return repr(value)


# =============================================================================
# Result Conversion
# =============================================================================

def convert_to_content(result):
    """
    Convert a tool result to a sequence of MCP content objects.

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

server = Server("MCAUnrealMCP")

# These get set in __main__ before the server starts.
_operation_manager = None
_remote_port = DEFAULT_REMOTE_PORT


@server.list_tools()
async def handle_list_tools():
    """
    Handle MCP ``list_tools`` request — return all discovered Unreal tools.

    :return: List of Tool objects.
    :rtype: list
    """
    logger.info("Client requested tool list (%d tools available).",
                len(_operation_manager.get_tools()))
    return _operation_manager.get_tools()


@server.call_tool()
async def handle_call_tool(name, arguments):
    """
    Handle MCP ``call_tool`` request — execute an Unreal tool.

    Loads the tool source file, builds the execution script with serialized
    arguments, sends it to Unreal via the Remote Execution protocol, and
    returns the results as MCP content.

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
        script = load_unreal_tool_source(name, path, args)

        # Send to Unreal and get results.
        ue_conn = UnrealConnection(port=_remote_port)
        result = ue_conn.run_tool_script(script)

        # None means the connection failed.
        if result is None:
            error_msg = (
                "Cannot connect to Unreal's Remote Execution port ({}).  "
                "Make sure Unreal Engine is running and Remote Execution is "
                "enabled in Editor Preferences > Plugins > Python > Remote "
                "Execution > Enable Remote Execution."
            ).format(_remote_port)
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
                server_name="MCAUnrealMCP",
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
        description="MCA Unreal MCP Server — connects Claude Code to Unreal Engine"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="UE Remote Execution TCP port (default: {} or UE_REMOTE_PORT env var).".format(
            DEFAULT_REMOTE_PORT
        ),
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
        _remote_port = args.port
    elif os.environ.get("UE_REMOTE_PORT"):
        _remote_port = int(os.environ["UE_REMOTE_PORT"])
    else:
        _remote_port = DEFAULT_REMOTE_PORT

    # --- Logging Setup --------------------------------------------------------

    # Log to the deployment directory (mca_preferences/mcp_servers/).
    log_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(log_dir, "mca_unreal_server.log")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    logger.info("MCA Unreal MCP Server v%s starting up", __version__)
    logger.info("UE Remote Execution port: %d", _remote_port)

    # --- Tool Discovery -------------------------------------------------------

    # The default tool directory is unreal_tools/ relative to the deployment
    # location.  Our server lives at:
    #   mca_preferences/mcp_servers/mca_unreal_server.py
    # Tool files live at:
    #   mca_preferences/mcp_servers/unreal_tools/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_tool_dir = os.path.join(script_dir, "unreal_tools")

    tool_dirs = [default_tool_dir]

    # Add any extra tool directories from CLI.
    if args.tool_dir:
        tool_dirs.extend(args.tool_dir)

    _operation_manager = OperationsManager()
    _operation_manager.find_tools(tool_dirs)

    logger.info("Tool discovery complete.  Starting MCP stdio server...")

    # --- Run ------------------------------------------------------------------

    asyncio.run(run())
