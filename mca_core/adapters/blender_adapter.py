"""
MCA Editor - Blender Adapter.

Connects to Blender via a TCP socket server addon for script execution,
auto-complete, and scene information retrieval. The Blender side runs a
lightweight socket server (registered via ``bpy.app.timers``) that accepts
JSON commands and executes them on Blender's main thread.

Blender Setup (user installs the MCA Blender socket server addon):
    The addon opens a TCP socket on port 8400 and listens for JSON commands.

Protocol:
    Request:  {"command": "exec"|"eval", "code": "...", "id": N}
    Response: {"status": "ok"|"error", "output": "...", "error": "...", "id": N}

Dependencies:
    - socket (stdlib)
    - json (stdlib)
"""

import json
import logging
import socket
import struct

from .base_adapter import DCCAdapter, DCCType, ConnectionState

# Module-level logger for Blender connection operations.
logger = logging.getLogger(__name__)

# --- Connection Constants ---------------------------------------------------

DEFAULT_BLENDER_PORT = 8400      # Blender socket server port
CONNECT_TIMEOUT_SECS = 5.0      # Timeout for initial TCP connect
FIRST_RECV_TIMEOUT_SECS = 10.0  # Max wait for Blender to START responding
IDLE_RECV_TIMEOUT_SECS = 0.5    # Silence after last chunk = response done
RECV_BUFFER_SIZE = 4096          # Bytes per socket recv call

# Monotonic command ID for request/response matching.
_next_command_id = 0


def _get_next_id():
    """
    Return a monotonically increasing command ID.

    Used to match JSON requests to responses when multiple
    commands are in flight.

    :return: The next unique command ID.
    :rtype: int
    """
    global _next_command_id
    _next_command_id += 1
    return _next_command_id


# --- Blender Adapter --------------------------------------------------------

class BlenderAdapter(DCCAdapter):
    """
    Blender DCC adapter for socket-based communication.

    Connects to a Blender instance running the MCA socket server addon.
    Commands are sent as JSON objects over TCP, and responses are received
    as JSON objects containing status, output, and error fields.

    This adapter is used when MCA Editor runs as a standalone application
    connecting to an external Blender instance.
    """

    def __init__(self):
        """Initialize Blender adapter with default connection settings."""
        super().__init__()
        self._host = "localhost"
        self._port = DEFAULT_BLENDER_PORT
        self._connect_timeout = CONNECT_TIMEOUT_SECS
        self._first_recv_timeout = FIRST_RECV_TIMEOUT_SECS
        self._idle_recv_timeout = IDLE_RECV_TIMEOUT_SECS

        # Workspace paths to inject into Blender's sys.path before execution.
        self._scripts_dir = ""
        self._site_packages_dir = ""
        # Project paths (higher priority than workspace paths).
        self._project_paths = []

    # --- Abstract Property Implementations -----------------------------------

    @property
    def dcc_type(self):
        """
        Return the DCC type for Blender.

        :rtype: DCCType
        """
        return DCCType.BLENDER

    @property
    def display_name(self):
        """
        Human-readable name for Blender.

        :rtype: str
        """
        return "Blender"

    @property
    def supported_languages(self):
        """
        Languages Blender supports for script execution.

        Blender only supports Python — no MEL equivalent.

        :rtype: list
        """
        return ["python"]

    @property
    def default_port(self):
        """
        Default TCP port for the Blender socket server.

        :rtype: int
        """
        return DEFAULT_BLENDER_PORT

    # --- Workspace Path Injection --------------------------------------------

    def set_workspace_paths(self, scripts_dir, site_packages_dir):
        """
        Set the workspace paths to inject into Blender's ``sys.path``.

        These directories are added via a sys.path injection command
        before each execution so user scripts and packages are importable.

        :param str scripts_dir: Path to the user scripts directory.
        :param str site_packages_dir: Path to the site-packages directory.
        """
        self._scripts_dir = scripts_dir
        self._site_packages_dir = site_packages_dir
        logger.debug("Blender workspace paths set: scripts=%s, site_packages=%s",
                      scripts_dir, site_packages_dir)

    def set_project_paths(self, paths):
        """
        Set project-specific paths to inject into Blender's ``sys.path``.

        These paths are injected BEFORE workspace paths so project modules
        take precedence.

        :param list paths: List of absolute directory path strings.
        """
        self._project_paths = list(paths)
        logger.debug("Blender project paths set: %s", paths)

    def clear_project_paths(self):
        """
        Remove project paths from Blender's ``sys.path``.

        Sends ``sys.path.remove()`` commands to Blender for each stored
        project path, then clears the local list.
        """
        if self._project_paths and self.is_connected:
            # Build a cleanup command that removes project paths.
            remove_lines = []
            for p in self._project_paths:
                remove_lines.append(
                    "while {path!r} in sys.path: sys.path.remove({path!r})"
                    .format(path=p)
                )
            cleanup_code = "import sys\n" + "\n".join(remove_lines)
            try:
                self._send_json_command("exec", cleanup_code)
            except Exception as exc:
                logger.warning("Failed to remove project paths from Blender: %s", exc)
        self._project_paths = []
        logger.debug("Blender project paths cleared")

    # --- Connection ----------------------------------------------------------

    def connect(self, host="localhost", port=None):
        """
        Connect to Blender's socket server addon.

        Tests the connection with a version query to verify the server
        is responding.

        :param str host: Blender host address.
        :param int port: Socket server port number.
        :return: True if connection was successful.
        :rtype: bool
        """
        self._host = host
        if port:
            self._port = port

        self.state = ConnectionState.CONNECTING
        logger.info("Connecting to Blender at %s:%d...", self._host, self._port)

        try:
            # Test connection with a version query.
            response = self._send_json_command(
                "eval",
                "'.'.join(str(v) for v in __import__('bpy').app.version)"
            )

            if response is None or response.get("status") != "ok":
                self.state = ConnectionState.ERROR
                error_msg = "Connected but received no valid response from Blender"
                if response and response.get("error"):
                    error_msg = response["error"]
                if self._on_error:
                    self._on_error(error_msg)
                return False

            # Extract Blender version from the response.
            version = response.get("output", "").strip()

            self.state = ConnectionState.CONNECTED
            if self._on_output:
                self._on_output("Connected to Blender: {}".format(version))

            logger.info("Connected to Blender: %s", version)
            return True

        except ConnectionRefusedError:
            self.state = ConnectionState.ERROR
            error_msg = (
                "Connection refused on {}:{}. "
                "Make sure Blender is running and the MCA socket server addon is enabled.\n"
                "Install the addon via Edit > Preferences > Add-ons > Install."
            ).format(host, self._port)
            if self._on_error:
                self._on_error(error_msg)
            logger.warning("Connection refused to Blender at %s:%d", host, self._port)
            return False

        except Exception as exc:
            self.state = ConnectionState.ERROR
            if self._on_error:
                self._on_error("Failed to connect to Blender: {}".format(str(exc)))
            logger.error("Failed to connect to Blender: %s", exc, exc_info=True)
            return False

    def disconnect(self):
        """Disconnect from Blender and reset state."""
        self.state = ConnectionState.DISCONNECTED
        if self._on_output:
            self._on_output("Disconnected from Blender")
        logger.info("Disconnected from Blender")

    def ping(self):
        """
        Check if Blender is still responding.

        :return: True if Blender responded to a version query.
        :rtype: bool
        """
        try:
            response = self._send_json_command("eval", "1")
            return response is not None and response.get("status") == "ok"
        except Exception:
            self.state = ConnectionState.DISCONNECTED
            return False

    # --- Execution -----------------------------------------------------------

    def execute(self, code, language=None):
        """
        Execute code in Blender's interpreter via the socket server.

        The code is sent as a JSON command to the socket server addon,
        which executes it on Blender's main thread and returns the
        output as a JSON response.

        :param str code: Source code to execute.
        :param str language: Only 'python' supported (defaults to 'python').
        :return: Output from Blender.
        :rtype: str
        """
        if not self.is_connected:
            return "Error: Not connected to Blender"

        # Build sys.path injection prefix for workspace and project paths.
        path_inject = self._build_path_inject()

        # Wrap code with eval-first-then-exec pattern.
        # The wrapper captures stdout, tries eval first (for expressions),
        # falls back to exec (for statements), and returns the result.
        wrapper = self._build_execution_wrapper(code, path_inject)

        try:
            response = self._send_json_command("exec", wrapper)

            if response is None:
                error_msg = "No response from Blender"
                if self._on_error:
                    self._on_error(error_msg)
                return error_msg

            # Route output and errors to the appropriate callbacks.
            output = response.get("output", "").strip()
            error = response.get("error", "").strip()

            if error:
                if self._on_error:
                    self._on_error(error)
            if output:
                if self._on_output:
                    self._on_output(output)

            return output if output else error if error else ""

        except Exception as exc:
            error_msg = "Execution error: {}".format(str(exc))
            if self._on_error:
                self._on_error(error_msg)
            logger.error("Blender execution error: %s", exc)
            return error_msg

    def _build_path_inject(self):
        """
        Build sys.path injection code for workspace and project paths.

        :return: Python code string that injects paths into sys.path.
        :rtype: str
        """
        lines = []
        if self._scripts_dir:
            lines.append(
                "if {scripts!r} not in __sys.path: "
                "__sys.path.insert(0, {scripts!r})"
                .format(scripts=self._scripts_dir)
            )
        if self._site_packages_dir:
            lines.append(
                "if {sitepkg!r} not in __sys.path: "
                "__sys.path.insert(0, {sitepkg!r})"
                .format(sitepkg=self._site_packages_dir)
            )
        # Inject project paths with highest priority.
        for proj_path in reversed(self._project_paths):
            lines.append(
                "if {path!r} not in __sys.path: "
                "__sys.path.insert(0, {path!r})"
                .format(path=proj_path)
            )
        return "\n".join(lines)

    def _build_execution_wrapper(self, code, path_inject):
        """
        Build the execution wrapper that captures stdout and handles
        eval-first-then-exec pattern.

        :param str code: User's Python source code.
        :param str path_inject: sys.path injection code.
        :return: Complete wrapper code string.
        :rtype: str
        """
        import base64

        # Base64-encode the user code to avoid quoting issues.
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")

        wrapper = (
            "import base64 as __b64, sys as __sys, io as __io, traceback as __tb\n"
            + (path_inject + "\n" if path_inject else "")
            + "__mca_old_stdout = __sys.stdout\n"
            "__mca_old_stderr = __sys.stderr\n"
            "__sys.stdout = __mca_buf = __io.StringIO()\n"
            "__sys.stderr = __mca_err_buf = __io.StringIO()\n"
            "__mca_err = None\n"
            "__mca_code = __b64.b64decode('{}').decode('utf-8')\n"
            "try:\n"
            "    try:\n"
            "        __mca_compiled = compile(__mca_code, '<mca_editor>', 'eval')\n"
            "        __mca_eval_result = eval(__mca_compiled, globals())\n"
            "        if __mca_eval_result is not None:\n"
            "            print('# Result: {{}} #'.format(repr(__mca_eval_result)))\n"
            "    except SyntaxError:\n"
            "        exec(compile(__mca_code, '<mca_editor>', 'exec'), globals())\n"
            "except Exception as __e:\n"
            "    __mca_err = __e\n"
            "    __mca_tb = __sys.exc_info()[2]\n"
            "    __mca_err.__context__ = None\n"
            "finally:\n"
            "    __sys.stdout = __mca_old_stdout\n"
            "    __sys.stderr = __mca_old_stderr\n"
            "__mca_result = __mca_buf.getvalue()\n"
            "__mca_error_result = __mca_err_buf.getvalue()\n"
            "if __mca_result:\n"
            "    print(__mca_result, end='')\n"
            "if __mca_err:\n"
            "    __tb.print_exception(type(__mca_err), __mca_err, __mca_tb)\n"
            "if __mca_error_result:\n"
            "    print(__mca_error_result, end='', file=__sys.stderr)\n"
        ).format(encoded)

        return wrapper

    def execute_file(self, filepath):
        """
        Execute a script file in Blender.

        :param str filepath: Path to the script file.
        :return: Output from Blender.
        :rtype: str
        """
        if filepath.endswith(".py"):
            code = 'exec(open(r"{}").read())'.format(filepath)
            return self.execute(code, "python")
        else:
            return "Error: Unsupported file type: {} (Blender only supports Python)".format(filepath)

    # --- Auto-complete -------------------------------------------------------

    def get_completions(self, partial, language=None):
        """
        Get auto-complete suggestions from Blender.

        Queries Python dir() for completions including bpy namespace.

        :param str partial: Partial text to complete.
        :param str language: Ignored (only Python supported).
        :return: List of completion dicts with 'label', 'detail', 'insert_text'.
        :rtype: list
        """
        completions = []

        if not self.is_connected:
            return completions

        try:
            if "." in partial:
                # Completing an attribute on an object.
                obj_part = partial.rsplit(".", 1)[0]
                attr_prefix = partial.rsplit(".", 1)[1]
                # Filter out module-type attributes — these are the
                # module's own imports and clutter the completion list.
                code = (
                    'import json, types; _obj={0}; '
                    'json.dumps([x for x in dir(_obj) '
                    'if x.startswith("{1}") and not x.startswith("__") '
                    'and not isinstance(getattr(_obj, x, None), types.ModuleType)][:500])'
                ).format(obj_part, attr_prefix)
            else:
                # Completing a top-level name.
                code = (
                    'import json; '
                    'json.dumps([x for x in dir() '
                    'if x.startswith("{}")][:500])'
                ).format(partial)

            response = self._send_json_command("eval", code)
            if response and response.get("status") == "ok":
                output = response.get("output", "").strip()
                if output:
                    try:
                        items = json.loads(output)
                        for item in items:
                            completions.append({
                                "label": item,
                                "detail": "Python",
                                "insert_text": item,
                            })
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass

        return completions

    # --- Scene Context -------------------------------------------------------

    def get_scene_info(self):
        """
        Get Blender scene information for AI context injection.

        Queries the current blend file path, Blender version, and
        selected objects.

        :return: Dictionary of scene metadata.
        :rtype: dict
        """
        info = super().get_scene_info()

        if not self.is_connected:
            return info

        try:
            code = (
                "import json, bpy; "
                "json.dumps({"
                "'scene_file': bpy.data.filepath or '', "
                "'blender_version': '.'.join(str(v) for v in bpy.app.version), "
                "'selected_objects': [o.name for o in bpy.context.selected_objects], "
                "'total_objects': len(bpy.data.objects), "
                "'active_object': bpy.context.active_object.name if bpy.context.active_object else ''"
                "})"
            )
            response = self._send_json_command("eval", code)
            if response and response.get("status") == "ok":
                output = response.get("output", "").strip()
                if output:
                    try:
                        scene_data = json.loads(output)
                        info.update(scene_data)
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            logger.warning("Failed to get Blender scene info: %s", exc)

        return info

    def get_api_documentation(self, symbol):
        """
        Look up Blender Python API documentation.

        :param str symbol: The API symbol to look up (e.g. "bpy.ops.mesh").
        :return: Help text, or None if unavailable.
        :rtype: str or None
        """
        if not self.is_connected:
            return None

        try:
            code = (
                "import io, sys; "
                "__buf = io.StringIO(); "
                "__old = sys.stdout; "
                "sys.stdout = __buf; "
                "help({}); "
                "sys.stdout = __old; "
                "print(__buf.getvalue())"
            ).format(symbol)
            response = self._send_json_command("exec", code)
            if response and response.get("status") == "ok":
                output = response.get("output", "").strip()
                return output if output else None
        except Exception:
            return None

    def get_mcp_server_info(self):
        """
        Return info about Blender MCP server availability.

        :return: MCP server metadata dictionary.
        :rtype: dict
        """
        try:
            from mca_core.mcp_setup import get_mcp_server_status
            return get_mcp_server_status()
        except Exception:
            return {
                "name": "MCABlenderMCP",
                "description": "MCP server for Blender scene manipulation",
                "installed": False,
            }

    # --- Internal Socket Communication --------------------------------------

    def _send_json_command(self, command_type, code):
        """
        Send a JSON command to Blender's socket server and return the response.

        Opens a new TCP socket for each command, sends a JSON request,
        and reads the JSON response using a two-phase timeout strategy
        (same as the Maya adapter).

        :param str command_type: "exec" or "eval".
        :param str code: The Python code to execute.
        :return: Parsed JSON response dict, or None on failure.
        :rtype: dict or None
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # SO_LINGER with zero timeout sends RST immediately on close,
        # preventing CLOSE_WAIT accumulation.
        sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
        )

        # Use the longer timeout for the initial TCP handshake.
        sock.settimeout(self._connect_timeout)

        try:
            sock.connect((self._host, self._port))

            # Build JSON request.
            request = json.dumps({
                "command": command_type,
                "code": code,
                "id": _get_next_id(),
            })

            # Send as newline-terminated UTF-8 string.
            sock.sendall((request + "\n").encode("utf-8"))

            # Phase 1: Wait up to 10s for Blender to start responding.
            sock.settimeout(self._first_recv_timeout)

            response = b""
            while True:
                try:
                    chunk = sock.recv(RECV_BUFFER_SIZE)
                    if not chunk:
                        break
                    response += chunk

                    # Phase 2: Once we have data, switch to short idle timeout.
                    sock.settimeout(self._idle_recv_timeout)

                except socket.timeout:
                    break

            # Decode and parse the JSON response.
            decoded = response.decode("utf-8", errors="replace").strip()
            if not decoded:
                return None

            try:
                return json.loads(decoded)
            except json.JSONDecodeError:
                # Response wasn't valid JSON — return it as plain output.
                logger.warning("Non-JSON response from Blender: %s", decoded[:500])
                return {"status": "ok", "output": decoded, "error": ""}

        finally:
            sock.close()
