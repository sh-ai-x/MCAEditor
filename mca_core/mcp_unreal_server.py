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

__version__ = "1.1.0"

# UE Remote Execution multicast group and port for node discovery.
MULTICAST_GROUP = "239.0.0.1"
MULTICAST_PORT = 6766

# Multicast TTL — 0 means localhost only (matches UE's default).
DEFAULT_MULTICAST_TTL = 0

# Buffer size for TCP recv (matches UE's DEFAULT_RECEIVE_BUFFER_SIZE).
RECV_BUFFER_SIZE = 8192

# UDP discovery timeout (seconds).
DISCOVERY_TIMEOUT = 3.0

# Localhost only — Remote Execution should not be network-exposed.
LOCAL_HOST = "127.0.0.1"

# Tool filenames to skip during discovery.
SKIP_TOOLS = {"__init__"}

# --- Multi-project targeting --------------------------------------------------
#
# Multiple Unreal editors can answer multicast discovery at once (one per open
# project). To avoid racing to whichever responds first, the server tracks a
# target project by name; discovery then selects the editor whose pong reports
# a matching ``project_name``. Set a default via the MCAUNREAL_TARGET_PROJECT
# env var; switch at runtime with the ``use_project`` tool.

# Sticky target project_name (case-insensitive). None = no explicit target.
_target_project = os.environ.get("MCAUNREAL_TARGET_PROJECT") or None

# Tokens passed to use_project that CLEAR the target (back to auto-select).
_CLEAR_TARGET_TOKENS = {"", "auto", "any", "none", "clear"}

# Module-level logger — configured in __main__.
logger = logging.getLogger("MCAUnrealMCP")


# =============================================================================
# Unreal Connection (using UE's Remote Execution protocol)
# =============================================================================
#
# UE's Remote Execution protocol (see remote_execution.py shipped with the
# PythonScriptPlugin):
#
#   1. Discovery: UDP multicast — send "ping", receive "pong" with node info
#   2. Open:      UDP multicast — send "open_connection" with our TCP endpoint
#   3. Accept:    UE connects TO our TCP listen socket (reverse connection!)
#   4. Command:   TCP — send "command", receive "command_result"
#   5. Close:     UDP multicast — send "close_connection"
#
# Messages are plain UTF-8 JSON (no binary framing):
#   {"version": 1, "magic": "ue_py", "type": "...", "source": "...", ...}
#
# Protocol version is 1. Multicast group 239.0.0.1:6766 by default.

# Message type constants matching UE's protocol.
_TYPE_PING = "ping"
_TYPE_PONG = "pong"
_TYPE_OPEN_CONNECTION = "open_connection"
_TYPE_CLOSE_CONNECTION = "close_connection"
_TYPE_COMMAND = "command"
_TYPE_COMMAND_RESULT = "command_result"

# UE protocol version (must be 1 to match PythonScriptRemoteExecution.cpp).
_UE_PROTOCOL_VERSION = 1


def _ue_msg(type_, source, dest=None, data=None):
    """
    Build a UE Remote Execution message as UTF-8 bytes.

    :param str type_: Message type (ping, pong, command, etc.).
    :param str source: Our node ID.
    :param str dest: Destination node ID (None = broadcast).
    :param dict data: Optional message-specific payload.
    :return: UTF-8 encoded JSON bytes.
    :rtype: bytes
    """
    obj = {
        "version": _UE_PROTOCOL_VERSION,
        "magic": "ue_py",
        "type": type_,
        "source": source,
    }
    if dest:
        obj["dest"] = dest
    if data:
        obj["data"] = data
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _parse_ue_json(data_bytes):
    """
    Parse a UE Remote Execution JSON message from raw bytes.

    :param bytes data_bytes: Raw UTF-8 bytes received from the socket.
    :return: Parsed message dict, or None if invalid.
    :rtype: dict or None
    """
    try:
        obj = json.loads(data_bytes.decode("utf-8"))
        if obj.get("magic") != "ue_py":
            return None
        return obj
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return None


class UnrealConnection:
    """
    Manages a Remote Execution session with a running UE instance.

    Follows the same protocol as UE's own ``remote_execution.py``:
    UDP multicast for discovery, then a **reverse TCP** connection where
    the client listens and UE connects to us.
    """

    def __init__(self, multicast_group=MULTICAST_GROUP, multicast_port=MULTICAST_PORT,
                 target_project=None):
        """
        Initialize an Unreal connection.

        :param str multicast_group: UDP multicast group address.
        :param int multicast_port: UDP multicast port.
        :param str target_project: project_name to select when several editors
            answer discovery (None = auto-select if exactly one is open).
        """
        self._multicast_group = multicast_group
        self._multicast_port = multicast_port
        self._our_node_id = str(uuid.uuid4())
        # Which open project to route to, and the last selection error (so the
        # caller can surface a specific reason instead of a generic message).
        self._target_project = target_project
        self._last_error = None

    def run_tool_script(self, script):
        """
        Execute a tool script in Unreal and return the result.

        Discovers a UE node, opens a command channel, sends the script,
        waits for the response, and closes the channel.

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

        raw = self._execute(script_with_output)

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

    def _create_broadcast_socket(self):
        """
        Create and configure a UDP multicast socket for discovery.

        Binds to the multicast address on the multicast port, joins the
        multicast group, and enables loopback so we can communicate with
        UE on localhost.

        :return: Configured UDP socket.
        :rtype: socket.socket
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to the multicast bind address on the multicast port (matches UE).
        sock.bind((LOCAL_HOST, self._multicast_port))
        # Enable multicast loopback so we hear our own pings (and UE's pongs).
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        # TTL 0 = localhost only.
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, DEFAULT_MULTICAST_TTL)
        # Set the outgoing multicast interface to localhost.
        sock.setsockopt(
            socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
            socket.inet_aton(LOCAL_HOST),
        )
        # Join the multicast group on the local interface.
        sock.setsockopt(
            socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
            socket.inet_aton(self._multicast_group) + socket.inet_aton(LOCAL_HOST),
        )
        sock.settimeout(0.5)
        return sock

    def _discover_all_nodes(self, sock):
        """
        Discover ALL running UE instances via UDP multicast ping/pong.

        Unlike a first-responder grab, this collects every editor that answers
        within the discovery window, keyed by node ID, along with the node data
        dict from its pong (which includes ``project_name`` / ``project_root``).

        :param socket.socket sock: The multicast socket.
        :return: Mapping of node_id -> node data dict.
        :rtype: dict
        """
        import time

        nodes = {}

        # Send pings for up to DISCOVERY_TIMEOUT seconds, accumulating responders.
        deadline = time.time() + DISCOVERY_TIMEOUT
        while time.time() < deadline:
            ping = _ue_msg(_TYPE_PING, self._our_node_id)
            sock.sendto(ping, (self._multicast_group, self._multicast_port))

            # Listen for pong responses for a short window.
            listen_until = time.time() + 1.0
            while time.time() < listen_until:
                try:
                    data, addr = sock.recvfrom(RECV_BUFFER_SIZE)
                    msg = _parse_ue_json(data)
                    if not msg:
                        continue
                    # Skip our own messages.
                    if msg.get("source") == self._our_node_id:
                        continue
                    if msg.get("type") == _TYPE_PONG:
                        node_id = msg.get("source", "")
                        if node_id:
                            # Last pong wins; node data is stable across pongs.
                            nodes[node_id] = msg.get("data") or {}
                except socket.timeout:
                    break

        return nodes

    def _select_node(self, nodes):
        """
        Choose a single UE node from the discovered set, honoring the target.

        Rules:
          * No nodes              -> None (sets a "not connected" error).
          * Target set            -> node whose project_name matches (exact,
                                     case-insensitive; else unique substring).
                                     No/ambiguous match -> None + descriptive error.
          * No target, one node   -> that node (back-compatible behavior).
          * No target, many nodes -> None + "ambiguous, pick a project" error.

        Setting an error instead of guessing is deliberate: silent mis-routing
        to the wrong open project is the failure mode we must never have.

        :param dict nodes: Mapping of node_id -> node data dict.
        :return: The chosen node_id, or None (with self._last_error set).
        :rtype: str or None
        """
        if not nodes:
            self._last_error = (
                "Not connected. No Unreal editor answered discovery — is the "
                "editor running with Python Remote Execution enabled "
                "(UDP multicast {}:{})?".format(
                    self._multicast_group, self._multicast_port)
            )
            return None

        def proj(nid):
            return (nodes.get(nid) or {}).get("project_name") or "?"

        open_projects = sorted({proj(nid) for nid in nodes})

        target = self._target_project
        if target:
            tnorm = target.strip().lower()
            # Exact case-insensitive project_name match first.
            for nid, data in nodes.items():
                if (data.get("project_name") or "").lower() == tnorm:
                    return nid
            # Unique substring fallback (so "bot" resolves "BotTown").
            matches = [nid for nid, data in nodes.items()
                       if tnorm in (data.get("project_name") or "").lower()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                self._last_error = (
                    "Target project '{}' is ambiguous across open editors: {}. "
                    "Use a more specific name via use_project.".format(
                        target, ", ".join(sorted(proj(n) for n in matches)))
                )
                return None
            self._last_error = (
                "Target project '{}' is not among the open editors: {}. "
                "Open it, or call use_project with one of those names.".format(
                    target, ", ".join(open_projects))
            )
            return None

        # No explicit target.
        if len(nodes) == 1:
            return next(iter(nodes))

        # Multiple editors and no target — refuse to guess.
        self._last_error = (
            "Multiple Unreal editors are open ({}) and no target project is set. "
            "Call use_project to pick one, then retry.".format(
                ", ".join(open_projects))
        )
        return None

    def _discover_ue_node(self, sock):
        """
        Discover all UE nodes and select one, honoring the target project.

        :param socket.socket sock: The multicast socket.
        :return: The chosen UE node ID, or None (with self._last_error set).
        :rtype: str or None
        """
        nodes = self._discover_all_nodes(sock)
        node_id = self._select_node(nodes)
        if node_id:
            logger.info(
                "Selected UE node %s (project=%s, target=%s)",
                node_id[:12],
                (nodes.get(node_id) or {}).get("project_name"),
                self._target_project or "<auto>",
            )
        else:
            logger.warning("Node selection failed: %s", self._last_error)
        return node_id

    def _execute(self, command):
        """
        Full execution flow: discover → open → command → result → close.

        :param str command: Python code to execute in UE.
        :return: The output string from UE, or None on failure.
        :rtype: str or None
        """
        import time

        broadcast_sock = self._create_broadcast_socket()

        try:
            # Step 1: Discover a UE node.
            ue_node_id = self._discover_ue_node(broadcast_sock)
            if not ue_node_id:
                return None

            # Step 2: Create a TCP listen socket for the command channel.
            # UE connects TO us (reverse connection pattern).
            # Bind to port 0 so the OS picks a free port — avoids conflicts.
            listen_sock = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP
            )
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_sock.bind((LOCAL_HOST, 0))
            listen_sock.listen(1)
            listen_sock.settimeout(5)

            # Read the actual port the OS assigned.
            actual_port = listen_sock.getsockname()[1]
            logger.debug("TCP listen socket bound to port %d", actual_port)

            # Step 3: Broadcast open_connection telling UE where to connect.
            open_msg = _ue_msg(
                _TYPE_OPEN_CONNECTION, self._our_node_id, ue_node_id,
                {
                    "command_ip": LOCAL_HOST,
                    "command_port": actual_port,
                },
            )

            # Try up to 6 times (matches UE's reference client).
            cmd_sock = None
            for attempt in range(6):
                broadcast_sock.sendto(
                    open_msg,
                    (self._multicast_group, self._multicast_port),
                )
                try:
                    cmd_sock, remote_addr = listen_sock.accept()
                    cmd_sock.setblocking(True)
                    logger.info(
                        "UE connected to our command channel from %s",
                        remote_addr,
                    )
                    break
                except socket.timeout:
                    continue

            listen_sock.close()

            if cmd_sock is None:
                logger.warning(
                    "UE did not connect to our command channel after 6 attempts."
                )
                # Send close just in case.
                broadcast_sock.sendto(
                    _ue_msg(_TYPE_CLOSE_CONNECTION, self._our_node_id, ue_node_id),
                    (self._multicast_group, self._multicast_port),
                )
                return None

            try:
                # Step 4: Send command over TCP.
                cmd_msg = _ue_msg(
                    _TYPE_COMMAND, self._our_node_id, ue_node_id,
                    {
                        "command": command,
                        "unattended": True,
                        "exec_mode": "ExecuteFile",
                    },
                )
                cmd_sock.sendall(cmd_msg)

                # Step 5: Receive command_result over TCP.
                # Blocking recv — UE sends the full result then we check size.
                response_data = b""
                while True:
                    chunk = cmd_sock.recv(RECV_BUFFER_SIZE)
                    if not chunk:
                        # Connection closed by UE.
                        break
                    response_data += chunk
                    if len(chunk) < RECV_BUFFER_SIZE:
                        # Got less than a full buffer — all data received.
                        break

                result_msg = _parse_ue_json(response_data)
                output = ""
                if result_msg and result_msg.get("type") == _TYPE_COMMAND_RESULT:
                    result_data = result_msg.get("data", {})
                    # UE may return output as a list of strings or a single string.
                    raw_output = result_data.get("output", "")
                    if isinstance(raw_output, list):
                        output = "\n".join(str(line) for line in raw_output)
                    else:
                        output = str(raw_output) if raw_output else ""
                    # Append result if present (from eval mode).
                    raw_result = result_data.get("result", "")
                    if raw_result:
                        if isinstance(raw_result, list):
                            raw_result = "\n".join(str(r) for r in raw_result)
                        else:
                            raw_result = str(raw_result)
                        output = (output + "\n" + raw_result).strip()
                elif response_data:
                    output = response_data.decode("utf-8", errors="replace")

                return output if output else None

            finally:
                cmd_sock.close()

                # Step 6: Broadcast close_connection.
                broadcast_sock.sendto(
                    _ue_msg(_TYPE_CLOSE_CONNECTION, self._our_node_id, ue_node_id),
                    (self._multicast_group, self._multicast_port),
                )

        except OSError as exc:
            logger.warning("Socket error during UE communication: %s", exc)
            return None
        finally:
            broadcast_sock.close()


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
# Multi-project Native Tools (run on the server, not inside Unreal)
# =============================================================================
#
# These manage WHICH open editor subsequent tool calls route to. They do not
# ship Python into UE — they only probe discovery and set the sticky target.

def _node_matches_target(project_name):
    """
    Whether a project_name satisfies the current sticky target.

    :param str project_name: A node's reported project_name.
    :return: True if it matches the target (exact or substring), else False.
    :rtype: bool
    """
    if not _target_project or not project_name:
        return False
    t = _target_project.strip().lower()
    return t == project_name.lower() or t in project_name.lower()


def _probe_open_nodes():
    """
    Discover all currently-open UE editors and their project metadata.

    :return: List of {node_id, project_name, project_root, machine, user}.
    :rtype: list
    """
    conn = UnrealConnection(target_project=_target_project)
    sock = conn._create_broadcast_socket()
    try:
        nodes = conn._discover_all_nodes(sock)
    finally:
        sock.close()

    out = []
    for nid, data in nodes.items():
        out.append({
            "node_id": nid,
            "project_name": data.get("project_name"),
            "project_root": data.get("project_root"),
            "machine": data.get("machine"),
            "user": data.get("user"),
        })
    # Stable ordering for readability.
    out.sort(key=lambda n: (n.get("project_name") or "").lower())
    return out


def _tool_list_ue_nodes():
    """
    List every open Unreal editor answering discovery, marking the target.

    :return: Result payload dict.
    :rtype: dict
    """
    nodes = _probe_open_nodes()
    for node in nodes:
        node["is_target"] = _node_matches_target(node.get("project_name"))
    return {
        "success": True,
        "target_project": _target_project,
        "count": len(nodes),
        "nodes": nodes,
    }


def _tool_use_project(project):
    """
    Set (or clear) the sticky target project for subsequent tool calls.

    :param str project: project_name (substring allowed), or an auto/clear token.
    :return: Result payload dict.
    :rtype: dict
    """
    global _target_project

    token = (project or "").strip().lower()
    if token in _CLEAR_TARGET_TOKENS:
        _target_project = None
        return {
            "success": True,
            "target_project": None,
            "message": "Target cleared — auto-select when exactly one editor is open.",
        }

    _target_project = project.strip()

    # Best-effort confirmation that the chosen project is actually open.
    nodes = _probe_open_nodes()
    open_names = [node.get("project_name") for node in nodes]
    matched = [name for name in open_names if name and _node_matches_target(name)]
    return {
        "success": True,
        "target_project": _target_project,
        "open_editors": open_names,
        "currently_open": bool(matched),
        "message": ("Now targeting '{}'.".format(_target_project)
                    + ("" if matched
                       else " Note: no open editor currently reports that project.")),
    }


# Server-native tools, surfaced alongside the discovered Unreal tools.
NATIVE_TOOLS = [
    Tool(
        name="list_ue_nodes",
        description=(
            "List all Unreal editors currently answering discovery — each with its "
            "project_name, project_root, and node_id — and flag which one is the "
            "active target. Use this when more than one project may be open."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="use_project",
        description=(
            "Set the target Unreal project (by project_name) for all subsequent tool "
            "calls, so commands route to the right editor when several are open. Pass "
            "a name like 'BotTown' (substring allowed). Pass 'auto' to clear the target "
            "and auto-select when exactly one editor is open."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Target project_name (substring allowed), or 'auto' to clear.",
                },
            },
            "required": ["project"],
        },
    ),
]

_NATIVE_TOOL_NAMES = {tool.name for tool in NATIVE_TOOLS}


# =============================================================================
# MCP Server
# =============================================================================

server = Server("MCAUnrealMCP")

# Set in __main__ before the server starts.
_operation_manager = None


@server.list_tools()
async def handle_list_tools():
    """
    Handle MCP ``list_tools`` request — return all discovered Unreal tools.

    :return: List of Tool objects.
    :rtype: list
    """
    discovered = _operation_manager.get_tools()
    logger.info("Client requested tool list (%d discovered + %d native).",
                len(discovered), len(NATIVE_TOOLS))
    # Native multi-project tools are surfaced alongside the Unreal tools.
    return discovered + NATIVE_TOOLS


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

    # Server-native multi-project tools are handled here, not shipped to UE.
    if name in _NATIVE_TOOL_NAMES:
        try:
            if name == "list_ue_nodes":
                payload = _tool_list_ue_nodes()
            elif name == "use_project":
                payload = _tool_use_project((arguments or {}).get("project", ""))
            else:
                payload = {"success": False, "message": "Unknown native tool."}
            return [TextContent(type="text", text=json.dumps(payload))]
        except Exception as exc:
            logger.critical("Native tool '%s' failed: %s", name, exc, exc_info=True)
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "message": "Error: {}".format(exc)}))]

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

        # Send to Unreal and get results — routed to the targeted project.
        ue_conn = UnrealConnection(target_project=_target_project)
        result = ue_conn.run_tool_script(script)

        # None means discovery/selection or the connection failed. Prefer the
        # specific selection error (ambiguous / wrong project) when present.
        if result is None:
            error_msg = ue_conn._last_error or (
                "Not connected. Unreal Engine either isn't running or "
                "doesn't have Remote Execution enabled. Check that the "
                "Python plugin's Remote Execution setting is on (UDP "
                "multicast 239.0.0.1:6766)."
            )
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
        "--tool-dir",
        action="append",
        default=None,
        help="Additional directory of tool .py files to load. "
             "Can be specified multiple times.",
    )
    args = parser.parse_args()

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
    logger.info("UE discovery: UDP multicast %s:%d", MULTICAST_GROUP, MULTICAST_PORT)

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
