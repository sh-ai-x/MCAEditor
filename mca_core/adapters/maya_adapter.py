"""
MCA Editor - Maya Adapter.

Connects to Autodesk Maya via TCP command port (socket) for script
execution, auto-complete, and scene information retrieval.

Maya Setup (user runs this once in Maya's Script Editor):
    import maya.cmds as cmds
    cmds.commandPort(name=":7001", sourceType="mel", echoOutput=True)
    cmds.commandPort(name=":7002", sourceType="python", echoOutput=True)

Dependencies:
    - socket (stdlib)
    - json (stdlib)
"""

import base64
import json
import logging
import socket

from .base_adapter import DCCAdapter, DCCType, ConnectionState

# Module-level logger for Maya connection operations.
logger = logging.getLogger(__name__)

# --- Connection Constants ---------------------------------------------------

DEFAULT_MEL_PORT = 7001        # Maya MEL command port
DEFAULT_PYTHON_PORT = 7002     # Maya Python command port
CONNECT_TIMEOUT_SECS = 5.0    # Timeout for initial TCP connect
FIRST_RECV_TIMEOUT_SECS = 10.0  # Max wait for Maya to START responding
IDLE_RECV_TIMEOUT_SECS = 0.2    # Silence after last chunk = response done
RECV_BUFFER_SIZE = 4096          # Bytes per socket recv call


# --- Maya Adapter -----------------------------------------------------------

class MayaAdapter(DCCAdapter):
    """
    Maya DCC adapter for command port communication.

    Supports both MEL and Python execution via separate TCP ports.
    The MEL port is used for connection testing and MEL commands;
    the Python port is used for Python execution and scene queries.

    Connection methods:
        1. Maya command port (TCP socket) - for MEL and Python execution
        2. Qt parenting - when running inside Maya's process (future)
    """

    def __init__(self):
        """Initialize Maya adapter with default connection settings."""
        super().__init__()
        self._host = "localhost"
        self._mel_port = DEFAULT_MEL_PORT
        self._python_port = DEFAULT_PYTHON_PORT
        self._connect_timeout = CONNECT_TIMEOUT_SECS
        self._first_recv_timeout = FIRST_RECV_TIMEOUT_SECS
        self._idle_recv_timeout = IDLE_RECV_TIMEOUT_SECS

        # Workspace paths to inject into Maya's sys.path before execution.
        # Set via set_workspace_paths() during editor initialization.
        self._scripts_dir = ""
        self._site_packages_dir = ""

    # --- Abstract Property Implementations -----------------------------------

    @property
    def dcc_type(self):
        """
        Return the DCC type for Maya.

        :rtype: DCCType
        """
        return DCCType.MAYA

    @property
    def display_name(self):
        """
        Human-readable name for Maya.

        :rtype: str
        """
        return "Autodesk Maya"

    @property
    def supported_languages(self):
        """
        Languages Maya supports for script execution.

        :rtype: list
        """
        return ["python", "mel"]

    @property
    def default_port(self):
        """
        Default MEL command port.

        :rtype: int
        """
        return DEFAULT_MEL_PORT

    # --- Workspace Path Injection --------------------------------------------

    def set_workspace_paths(self, scripts_dir, site_packages_dir):
        """
        Set the workspace paths to inject into Maya's ``sys.path``.

        These directories are added to ``sys.path`` inside the Python wrapper
        so that user scripts and third-party packages can be imported when
        executing code in Maya.

        :param str scripts_dir: Path to the user scripts directory.
        :param str site_packages_dir: Path to the site-packages directory.
        """
        self._scripts_dir = scripts_dir
        self._site_packages_dir = site_packages_dir
        logger.debug("Maya workspace paths set: scripts=%s, site_packages=%s",
                      scripts_dir, site_packages_dir)

    # --- Connection ----------------------------------------------------------

    def connect(self, host="localhost", port=None):
        """
        Connect to Maya's command port.

        Tests the MEL port with a version query, then verifies the
        Python port is also reachable.  If a custom port is provided,
        the Python port is assumed to be one higher (e.g. 7001 -> 7002).

        :param str host: Maya host address.
        :param int port: MEL port number (Python port = port + 1).
        :return: True if connection was successful.
        :rtype: bool
        """
        self._host = host
        if port:
            self._mel_port = port
            self._python_port = port + 1

        self.state = ConnectionState.CONNECTING
        logger.info("Connecting to Maya at %s:%d...", self._host, self._mel_port)

        try:
            # Test MEL port with a simple version command.
            result = self._send_command("about -version", self._mel_port)
            if not result:
                self.state = ConnectionState.ERROR
                if self._on_error:
                    self._on_error("Connected but received no response from Maya")
                return False

            # Parse version — take just the last non-empty line to avoid
            # any command-port echo noise in the response.
            version_lines = [l.strip() for l in result.strip().splitlines() if l.strip()]
            version = version_lines[-1] if version_lines else result.strip()

            # Also verify the Python port is reachable.
            py_ok = False
            try:
                py_result = self._send_command("print('__mca_py_ok__')", self._python_port)
                if py_result and "__mca_py_ok__" in py_result:
                    py_ok = True
            except Exception:
                pass

            self.state = ConnectionState.CONNECTED
            if self._on_output:
                status_msg = "Connected to Maya: {}".format(version)
                if py_ok:
                    status_msg += " (Python port :{} OK)".format(self._python_port)
                else:
                    status_msg += (
                        "\nWARNING: Python port :{} not responding. "
                        "Run in Maya's Script Editor:\n"
                        '  cmds.commandPort(name=":{}", sourceType="python", '
                        "echoOutput=True)".format(self._python_port, self._python_port)
                    )
                self._on_output(status_msg)

            logger.info("Connected to Maya: %s (python port: %s)",
                        version, "OK" if py_ok else "UNAVAILABLE")
            return True

        except ConnectionRefusedError:
            self.state = ConnectionState.ERROR
            error_msg = (
                "Connection refused on {}:{}. "
                "Make sure Maya is running and command ports are open.\n"
                "Run in Maya's Script Editor:\n"
                '  import maya.cmds as cmds\n'
                '  cmds.commandPort(name=":{}", sourceType="mel", echoOutput=True)\n'
                '  cmds.commandPort(name=":{}", sourceType="python", echoOutput=True)'
            ).format(host, self._mel_port, self._mel_port, self._python_port)
            if self._on_error:
                self._on_error(error_msg)
            logger.warning("Connection refused to Maya at %s:%d", host, self._mel_port)
            return False

        except Exception as exc:
            self.state = ConnectionState.ERROR
            if self._on_error:
                self._on_error("Failed to connect to Maya: {}".format(str(exc)))
            logger.error("Failed to connect to Maya: %s", exc, exc_info=True)
            return False

    def disconnect(self):
        """Disconnect from Maya and reset state."""
        self.state = ConnectionState.DISCONNECTED
        if self._on_output:
            self._on_output("Disconnected from Maya")
        logger.info("Disconnected from Maya")

    def ping(self):
        """
        Check if Maya is still responding.

        :return: True if Maya responded to a version query.
        :rtype: bool
        """
        try:
            result = self._send_command("about -version", self._mel_port)
            return result is not None
        except Exception:
            self.state = ConnectionState.DISCONNECTED
            return False

    # --- Execution -----------------------------------------------------------

    def execute(self, code, language=None):
        """
        Execute code in Maya's interpreter.

        For Python, multi-line code is base64-encoded and wrapped in
        an exec() call so Maya's command port receives it as a single
        line, preventing newline-splitting issues.

        :param str code: Source code to execute.
        :param str language: 'python' or 'mel' (defaults to 'python').
        :return: Output from Maya.
        :rtype: str
        """
        if not self.is_connected:
            return "Error: Not connected to Maya"

        # Default to Python if no language specified.
        if language is None:
            language = "python"

        # Route to the correct port based on language.
        port = self._python_port if language == "python" else self._mel_port

        # For Python code, wrap in base64 to avoid newline/quote issues.
        # Maya's commandPort can split multi-line strings incorrectly.
        if language == "python":
            command = self._wrap_python_for_port(code)
        else:
            command = code

        try:
            result = self._send_command(command, port)

            # Clean up whitespace from the response.
            if result:
                result = result.strip()

            # Strip the "None" artifact from exec()'s return value.
            # Maya's commandPort echoes the return value of the expression
            # (always "None" for exec()) alongside any print() output.
            # It appears as a leading or trailing "None" line in the response.
            if result:
                result = self._strip_exec_none(result)

            # If there's actual output left, display it.
            if result:
                if self._on_output:
                    self._on_output(result)
                return result

            # No meaningful output — return empty string.
            return ""
        except Exception as exc:
            error_msg = "Execution error: {}".format(str(exc))
            if self._on_error:
                self._on_error(error_msg)
            logger.error("Maya execution error: %s", exc)
            return error_msg

    def _wrap_python_for_port(self, code):
        """
        Wrap Python code for safe transmission over Maya's command port.

        ALL code is base64-encoded and executed via ``exec(compile(...),
        globals())`` so that:

        1. Multi-line code arrives as a single line (no newline-splitting).
        2. ``globals()`` ensures variables, imports, and functions persist
           in Maya's ``__main__`` namespace across executions.  Without it,
           Maya's commandPort handler runs exec() in a temporary local
           scope that is discarded after each command.

        Additionally, ``sys.stdout`` is temporarily redirected to a
        ``StringIO`` buffer during execution.  This captures any
        ``print()`` output from the user's code and re-prints it
        after exec() completes, so the output flows back through
        the commandPort socket.  Without this, ``exec()`` always
        returns ``None`` and print output goes to Maya's internal
        console instead of the socket.

        :param str code: Raw Python source code.
        :return: A single-line Python command safe for the command port.
        :rtype: str
        """
        # Base64-encode the code to avoid newline and quote issues.
        # compile() with "exec" mode supports multi-statement code,
        # and "<mca_editor>" shows up in tracebacks for easy identification.
        # globals() makes variables persist in Maya's __main__ namespace.
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")

        # Build the full wrapper as clean, readable Python code, then
        # base64-encode the ENTIRE wrapper for single-line transmission.
        # This avoids nested quoting hell from trying to inline everything.
        #
        # The wrapper:
        # 1. Saves sys.stdout and redirects to a StringIO buffer.
        # 2. Tries to compile as "eval" first — if the code is a single
        #    expression (variable name, function call, etc.), evaluate it
        #    and display the result as "# Result: <repr> #".  This matches
        #    Charcoal Editor 2's behavior where highlighting a variable
        #    and executing shows its current value.
        # 3. Falls back to "exec" mode for statements (imports, assignments).
        # 4. In a finally block: restores stdout (even if code raises).
        # 5. Re-prints captured output so it returns through the socket.
        # 6. If an error occurred, prints the traceback too.
        # Build sys.path injection lines for workspace directories.
        # These ensure user scripts and site-packages are importable in Maya.
        path_inject = ""
        if self._scripts_dir:
            # Use repr() for safe string escaping of Windows backslash paths.
            path_inject += (
                "if {scripts!r} not in __sys.path: "
                "__sys.path.insert(0, {scripts!r})\n"
            ).format(scripts=self._scripts_dir)
        if self._site_packages_dir:
            path_inject += (
                "if {sitepkg!r} not in __sys.path: "
                "__sys.path.insert(0, {sitepkg!r})\n"
            ).format(sitepkg=self._site_packages_dir)

        wrapper = (
            "import base64 as __b64, sys as __sys, io as __io, traceback as __tb\n"
            + path_inject
            + "__mca_old_stdout = __sys.stdout\n"
            "__sys.stdout = __mca_buf = __io.StringIO()\n"
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
            "finally:\n"
            "    __sys.stdout = __mca_old_stdout\n"
            "__mca_result = __mca_buf.getvalue()\n"
            "if __mca_result:\n"
            "    print(__mca_result, end='')\n"
            "if __mca_err:\n"
            "    __tb.print_exception(type(__mca_err), __mca_err, "
            "__mca_err.__traceback__)\n"
        ).format(encoded)

        # Now base64-encode the wrapper itself for safe single-line transmission.
        wrapper_encoded = base64.b64encode(wrapper.encode("utf-8")).decode("ascii")
        return (
            'import base64; '
            'exec(compile(base64.b64decode("{}").decode("utf-8"), '
            '"<mca_editor_wrapper>", "exec"))'
        ).format(wrapper_encoded)

    def _strip_exec_none(self, result):
        """
        Remove the 'None' artifact that exec() leaves in commandPort responses.

        Maya's commandPort echoes the return value of the last expression.
        Since our wrapper uses ``exec()``, that return value is always
        ``None``, which appears as a leading or trailing ``"None"`` line
        mixed in with the actual print output from the wrapper.

        This method strips that artifact while preserving any legitimate
        output the user's code may have produced.

        :param str result: Raw response string from Maya.
        :return: Cleaned response with exec() artifact removed.
        :rtype: str
        """
        # Split into lines and strip the "None" line from start or end.
        lines = result.split("\n")

        # Remove leading "None" line (Maya often echoes return value first).
        if lines and lines[0].strip() == "None":
            lines = lines[1:]

        # Remove trailing "None" line (sometimes appears at the end instead).
        if lines and lines[-1].strip() == "None":
            lines = lines[:-1]

        return "\n".join(lines).strip()

    def execute_file(self, filepath):
        """
        Execute a script file in Maya.

        Routes to MEL source or Python exec based on file extension.

        :param str filepath: Path to the script file.
        :return: Output from Maya.
        :rtype: str
        """
        if filepath.endswith(".mel"):
            return self.execute('source "{}"'.format(filepath), "mel")
        elif filepath.endswith(".py"):
            code = 'exec(open(r"{}").read())'.format(filepath)
            return self.execute(code, "python")
        else:
            return "Error: Unsupported file type: {}".format(filepath)

    # --- Auto-complete -------------------------------------------------------

    def get_completions(self, partial, language=None):
        """
        Get auto-complete suggestions from Maya.

        Queries MEL commandHelp for MEL completions and Python dir()
        for Python completions.

        :param str partial: Partial text to complete.
        :param str language: Target language for completions.
        :return: List of completion dicts with 'label', 'detail', 'insert_text'.
        :rtype: list
        """
        completions = []

        if not self.is_connected:
            return completions

        # MEL completions — query maya.cmds via the Python port.
        # The MEL-only `commandHelp` procedure doesn't exist in all Maya
        # versions, so we use dir(maya.cmds) which reliably lists every
        # command Maya exposes (MEL and Python share the same command set).
        if language == "mel" or (language is None and "." not in partial):
            try:
                code = (
                    'import json, maya.cmds; '
                    'json.dumps([c for c in sorted(dir(maya.cmds)) '
                    'if c.startswith("{}") and not c.startswith("_")][:50])'
                ).format(partial)
                result = self._send_command(code, self._python_port)
                if result:
                    try:
                        items = json.loads(result.strip())
                        for item in items:
                            completions.append({
                                "label": item,
                                "detail": "MEL command",
                                "insert_text": item,
                            })
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass

        # Python completions via dir().
        if language == "python" or language is None:
            try:
                if "." in partial:
                    # Completing an attribute on an object.
                    obj_part = partial.rsplit(".", 1)[0]
                    attr_prefix = partial.rsplit(".", 1)[1]
                    code = (
                        'import json; '
                        'json.dumps([x for x in dir({}) '
                        'if x.startswith("{}") and not x.startswith("__")][:30])'
                    ).format(obj_part, attr_prefix)
                else:
                    # Completing a top-level name.
                    code = (
                        'import json; '
                        'json.dumps([x for x in dir() '
                        'if x.startswith("{}")][:30])'
                    ).format(partial)

                result = self._send_command(code, self._python_port)
                if result:
                    try:
                        items = json.loads(result.strip())
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
        Get Maya scene information for AI context injection.

        Queries scene file path, Maya version, and selected objects.

        :return: Dictionary of scene metadata.
        :rtype: dict
        """
        info = super().get_scene_info()

        if not self.is_connected:
            return info

        try:
            # Get the current scene file path.
            scene_file = self._send_command(
                'import maya.cmds; print(maya.cmds.file(q=True, sceneName=True))',
                self._python_port
            )
            info["scene_file"] = (scene_file or "").strip()

            # Get the Maya version string.
            version = self._send_command("about -version", self._mel_port)
            info["maya_version"] = (version or "").strip()

            # Get the list of currently selected objects.
            selected = self._send_command(
                'import maya.cmds, json; print(json.dumps(maya.cmds.ls(selection=True) or []))',
                self._python_port
            )
            if selected:
                try:
                    info["selected_objects"] = json.loads(selected.strip())
                except json.JSONDecodeError:
                    info["selected_objects"] = []
        except Exception as exc:
            logger.warning("Failed to get Maya scene info: %s", exc)

        return info

    def get_api_documentation(self, symbol):
        """
        Look up Maya command documentation.

        :param str symbol: The Maya command or API symbol.
        :return: Help text, or None if unavailable.
        :rtype: str or None
        """
        if not self.is_connected:
            return None

        try:
            result = self._send_command(
                'import maya.cmds; print(maya.cmds.help("{}"))'.format(symbol),
                self._python_port
            )
            return result.strip() if result else None
        except Exception:
            return None

    def get_mcp_server_info(self):
        """
        Return info about Maya MCP server availability.

        Delegates to ``mcp_setup.get_mcp_server_status()`` for real-time
        status instead of returning a hardcoded stub.

        :return: MCP server metadata dictionary.
        :rtype: dict
        """
        try:
            from mca_core.mcp_setup import get_mcp_server_status
            return get_mcp_server_status()
        except Exception:
            # Fallback if mcp_setup is unavailable.
            return {
                "name": "MCAMayaMCP",
                "description": "MCP server for Maya scene manipulation",
                "installed": False,
            }

    # --- Internal Socket Communication --------------------------------------

    def _send_command(self, command, port):
        """
        Send a command to Maya's command port and return the response.

        Opens a new TCP socket for each command, sends the command
        as a newline-terminated UTF-8 string, and reads the response
        using a two-phase timeout strategy:

        Phase 1 (first recv): Wait up to 10 seconds for Maya to START
        responding.  Heavy commands like ``import pymel.core`` can take
        several seconds before producing any output.

        Phase 2 (subsequent recvs): Once data starts flowing, use a
        short 0.2-second idle timeout.  If Maya goes silent for 0.2s,
        we treat the response as complete.

        This gives Maya plenty of processing time while still returning
        results quickly once the output is done.

        :param str command: The command string to send.
        :param int port: The TCP port to connect to.
        :return: Response string from Maya, or None on failure.
        :rtype: str or None
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Use the longer timeout for the initial TCP handshake.
        sock.settimeout(self._connect_timeout)

        try:
            sock.connect((self._host, port))

            # Maya command port expects newline-terminated strings.
            sock.sendall((command + "\n").encode("utf-8"))

            # Phase 1: Wait up to 10s for Maya to start responding.
            # Heavy operations (imports, scene queries) may take seconds.
            sock.settimeout(self._first_recv_timeout)

            response = b""
            while True:
                try:
                    chunk = sock.recv(RECV_BUFFER_SIZE)
                    if not chunk:
                        break
                    response += chunk

                    # Phase 2: Once we have data, switch to short idle timeout.
                    # 0.2s of silence after receiving data = response is done.
                    sock.settimeout(self._idle_recv_timeout)

                except socket.timeout:
                    # In phase 1: Maya didn't respond at all within 10s.
                    # In phase 2: 0.2s silence after last chunk = done.
                    break

            # Decode and strip null bytes that Maya's commandPort appends.
            decoded = response.decode("utf-8", errors="replace")
            return decoded.replace("\x00", "")

        finally:
            sock.close()
