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
import ctypes
import importlib
import importlib.util
import inspect
import json
import logging
import os
import platform
import pprint as pprint_mod
import socket
import struct
import sys
import tempfile
import time
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

# Deferred execution: directory for result files (Maya 2024 workaround).
_DEFERRED_RESULT_DIR = os.path.join(tempfile.gettempdir(), "mca_mcp_results")

# Deferred execution: poll interval and max wait time (seconds).
DEFERRED_POLL_INTERVAL = 0.1
DEFERRED_MAX_WAIT = 15.0

# Tool filenames to skip during discovery (known broken/dangerous).
SKIP_TOOLS = {"generate_scene", "__init__"}

# Module-level logger — configured in __main__.
logger = logging.getLogger("MCAMayaMCP")


# =============================================================================
# Editor API Client (Maya 2024 Workaround)
# =============================================================================
#
# Maya 2024's commandPort has bugs that prevent reliable execution of
# maya.cmds operations through the socket handler.  As an alternative, we
# can route tool calls through the MCA Editor's JSON-RPC API server, which
# runs inside Maya's process and uses the internal adapter (direct exec()
# on the main thread — immune to all commandPort issues).
#
# The Editor API server writes a discovery file (api_port.json) so external
# tools can find it.  This code is inlined here because mcp_maya_server.py
# must be fully standalone (zero mca_core imports).
#
# The fallback chain is: Editor API → direct commandPort → deferred commandPort.

# --- Editor API Discovery File Path ---
# Mirrors the path logic from mcp_editor_server.py.
_home = os.path.expanduser("~")
if sys.platform in ("win32", "darwin"):
    # Windows and macOS both use ~/Documents.
    _EDITOR_PREFS_DIR = os.path.join(
        _home, "Documents", "mca_preferences", "MCAEditor"
    )
else:
    # Linux follows XDG convention — ~/.config.
    _xdg = os.environ.get("XDG_CONFIG_HOME", os.path.join(_home, ".config"))
    _EDITOR_PREFS_DIR = os.path.join(_xdg, "mca_preferences", "MCAEditor")
_EDITOR_DISCOVERY_FILE = os.path.join(_EDITOR_PREFS_DIR, "api_port.json")

# Timeout for the Editor API TCP connection (seconds).
EDITOR_API_CONNECT_TIMEOUT = 5.0

# Timeout for reading the Editor API response (seconds).
# Generous because tool scripts (scene analysis, etc.) can take a while
# and execute_in_dcc blocks the main thread synchronously.
EDITOR_API_RECV_TIMEOUT = 30.0


def _is_process_alive(pid):
    """
    Check if a process with the given PID is still running.

    Uses ``OpenProcess`` on Windows and ``os.kill(pid, 0)`` on POSIX.
    Returns False if the process is definitely dead; True if it might
    be alive (or we cannot tell).

    :param int pid: The process ID to check.
    :return: True if the process appears to be alive.
    :rtype: bool
    """
    if pid is None or pid <= 0:
        return False

    if platform.system() == "Windows":
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


def _read_editor_discovery():
    """
    Read the MCA Editor's port discovery file.

    Returns the parsed JSON dict, or None if the file doesn't exist,
    is unreadable, or refers to a dead process.

    :return: Discovery dict with ``port``, ``pid``, ``started`` keys,
             or None if the editor is not available.
    :rtype: dict or None
    """
    if not os.path.isfile(_EDITOR_DISCOVERY_FILE):
        return None

    try:
        with open(_EDITOR_DISCOVERY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Cannot read editor discovery file: %s", exc)
        return None

    # Check if the editor process is still alive.
    pid = data.get("pid")
    if pid and not _is_process_alive(pid):
        logger.debug(
            "Editor discovery file references dead PID %d — ignoring.", pid
        )
        return None

    return data


def _call_editor_api(method, params=None):
    """
    Send a JSON-RPC request to the MCA Editor's API server.

    Returns the result value on success, or None on any failure.  Unlike
    ``mcp_editor_server.py:_call_editor()``, this function returns None
    instead of raising so the fallback chain in ``run_tool_script()`` can
    continue to the next execution method.

    :param str method: The JSON-RPC method name (e.g. ``execute_in_dcc``).
    :param dict params: Keyword arguments for the method (optional).
    :return: The result from the JSON-RPC response, or None on failure.
    :rtype: dict or list or str or None
    """
    # Step 1: Read the discovery file.
    discovery = _read_editor_discovery()
    if discovery is None:
        logger.debug("Editor API not available (no discovery file or dead PID).")
        return None

    port = discovery.get("port")
    if not port:
        logger.debug("Editor discovery file has no port — skipping Editor API.")
        return None

    # Step 2: Build the JSON-RPC request.
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1,
    }
    request_line = json.dumps(request) + "\n"

    # Step 3: Send the request and read the response.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(EDITOR_API_CONNECT_TIMEOUT)

    try:
        # Honor the configured Maya host (not the hardcoded LOCAL_HOST) so the
        # Editor-API path targets the same box as the command-port paths.  This
        # is the easy-to-miss connect: leaving it as LOCAL_HOST gives a
        # half-working remote setup where this path silently hits localhost.
        sock.connect((_maya_host, port))
        sock.sendall(request_line.encode("utf-8"))

        # Read the newline-delimited JSON-RPC response.
        sock.settimeout(EDITOR_API_RECV_TIMEOUT)
        response_data = b""
        while True:
            chunk = sock.recv(RECV_BUFFER_SIZE)
            if not chunk:
                break
            response_data += chunk
            # JSON-RPC responses are newline-delimited — stop at first newline.
            if b"\n" in response_data:
                break

    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        logger.debug("Editor API connection failed (port %d): %s", port, exc)
        return None
    finally:
        sock.close()

    # Step 4: Parse the JSON-RPC response.
    response_str = response_data.decode("utf-8", errors="replace").strip()
    if not response_str:
        logger.debug("Empty response from Editor API.")
        return None

    try:
        response = json.loads(response_str)
    except json.JSONDecodeError as exc:
        logger.debug("Invalid JSON from Editor API: %s", exc)
        return None

    # Check for JSON-RPC error.
    if "error" in response:
        error = response["error"]
        msg = error.get("message", "Unknown") if isinstance(error, dict) else str(error)
        logger.debug("Editor API returned error: %s", msg)
        return None

    return response.get("result")


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

        Uses a 3-level fallback chain:

        1. **Editor API** — routes through the MCA Editor's JSON-RPC server,
           which uses the internal adapter (direct ``exec()`` on the main
           thread).  Completely immune to all commandPort bugs.  Only
           available when MCA Editor is open in Maya.
        2. **Direct commandPort** — stdout-redirect wrapper via port 7002.
           Works on Maya 2025+ but fails on Maya 2024.
        3. **Deferred commandPort** — sends lightweight Python via port 7002
           that queues real work via ``executeDeferred()``, retrieves results
           from a temp file.  Maya 2024 fallback when Editor is not open.

        :param str script: Python source code to execute in Maya.
        :return: Parsed result (dict/list if JSON, raw string otherwise).
        :rtype: dict or list or str or None
        """
        # Level 1: Try the Editor API (bypasses commandPort entirely).
        result = self._run_via_editor_api(script)
        if result is not None:
            return result

        # Level 2: Try direct commandPort execution (works on Maya 2025+).
        result = self._run_direct(script)
        if result is not None:
            return result

        # Level 3: Fall back to deferred commandPort execution.
        # Maya 2024's commandPort crashes when maya.cmds runs inside
        # the socket handler.  Deferred mode queues the work via
        # maya.utils.executeDeferred() and retrieves results from a
        # temp file, avoiding the crash entirely.
        logger.info("Direct execution returned no data, trying deferred mode.")
        return self._run_deferred(script)

    # --- Shared Helpers -------------------------------------------------------

    def _make_result_file(self):
        """
        Create a unique result file path in the temp directory.

        The result file is used by both the Editor API and deferred execution
        paths to retrieve tool results written by the Maya-side script.

        :return: Tuple of (native path for Python, forward-slash path for Maya).
        :rtype: tuple
        """
        os.makedirs(_DEFERRED_RESULT_DIR, exist_ok=True)
        result_id = "{:.6f}".format(time.time()).replace(".", "_")
        result_file = os.path.join(
            _DEFERRED_RESULT_DIR, "mcp_{}.json".format(result_id)
        )
        # Normalize to forward slashes for Maya's Python on Windows.
        result_file_maya = result_file.replace("\\", "/")
        return result_file, result_file_maya

    @staticmethod
    def _build_result_suffix(result_file_maya):
        """
        Build Python code that writes ``_mcp_maya_results`` to a temp JSON file.

        Appended to tool scripts so their results can be retrieved from disk
        instead of through stdout/socket.  Includes a try/except so errors
        are also written to the file for diagnosis.

        :param str result_file_maya: Forward-slash path to the result file.
        :return: Python source code to append to the tool script.
        :rtype: str
        """
        return (
            "\nimport json as _mcp_json, traceback as _mcp_tb\n"
            "try:\n"
            "    with open('{outfile}', 'w') as _mcp_f:\n"
            "        _mcp_json.dump({{'success': True, "
            "'result': _mcp_maya_results}}, _mcp_f)\n"
            "except Exception as _mcp_e:\n"
            "    with open('{outfile}', 'w') as _mcp_f:\n"
            "        _mcp_json.dump({{'success': False, "
            "'error': str(_mcp_e), "
            "'traceback': _mcp_tb.format_exc()}}, _mcp_f)\n"
        ).format(outfile=result_file_maya)

    def _poll_result_file(self, result_file, max_wait=DEFERRED_MAX_WAIT):
        """
        Poll for a temp result file and return parsed content.

        Waits up to ``max_wait`` seconds for the file to appear, reads and
        parses the JSON, cleans up, and returns the result.  Used by both
        the Editor API and deferred execution paths.

        :param str result_file: Native path to the result file.
        :param float max_wait: Maximum time to wait (seconds).
        :return: Parsed result, or None on timeout/failure.
        :rtype: dict or list or str or None
        """
        elapsed = 0.0
        while elapsed < max_wait:
            if os.path.isfile(result_file):
                try:
                    with open(result_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    # File might be partially written — retry.
                    time.sleep(DEFERRED_POLL_INTERVAL)
                    elapsed += DEFERRED_POLL_INTERVAL
                    continue

                # Clean up the result file.
                try:
                    os.remove(result_file)
                except OSError:
                    pass

                if data.get("success"):
                    return data.get("result")
                else:
                    logger.warning(
                        "Execution error: %s", data.get("error", "unknown")
                    )
                    return None

            time.sleep(DEFERRED_POLL_INTERVAL)
            elapsed += DEFERRED_POLL_INTERVAL

        logger.warning(
            "Timed out after %.1fs waiting for result file %s",
            max_wait, result_file,
        )
        return None

    # --- Level 1: Editor API --------------------------------------------------

    def _run_via_editor_api(self, script):
        """
        Execute a tool script through the MCA Editor's JSON-RPC API server.

        The Editor API routes code through the internal Maya adapter, which
        uses ``exec()`` directly on the main thread — completely immune to
        all commandPort bugs.  This is the preferred execution path.

        The ``execute_in_dcc`` method runs synchronously on Maya's main
        thread (via the QTimer drain), so ``maya.cmds`` works perfectly.
        Since the exec blocks until completion, the result file is written
        before the API response comes back.

        Returns None if the Editor API is not available (editor not open,
        discovery file missing, dead PID, connection refused) so the
        fallback chain can continue.

        :param str script: Python source code to execute in Maya.
        :return: Parsed result, or None if Editor API is unavailable.
        :rtype: dict or list or str or None
        """
        # Prepare a result file — the Editor API's execute_in_dcc returns
        # empty output (internal adapter limitation), so we capture results
        # via a temp file instead.
        result_file, result_file_maya = self._make_result_file()
        full_script = script + self._build_result_suffix(result_file_maya)

        # Send to the Editor API's execute_in_dcc method.
        api_result = _call_editor_api("execute_in_dcc", {
            "code": full_script,
            "language": "python",
        })

        # If the Editor API is not available, return None to fall through.
        if api_result is None:
            return None

        logger.info("Editor API accepted the tool script, reading result file.")

        # The exec was synchronous — the result file should already exist.
        # Use a short poll in case of filesystem caching delays on Windows.
        return self._poll_result_file(result_file, max_wait=5.0)

    # --- Level 2: Direct CommandPort ------------------------------------------

    def _run_direct(self, script):
        """
        Execute a tool script via the direct stdout-redirect approach.

        Uses a stdout-redirect wrapper (matching ``maya_adapter.py``) to
        capture results through the commandPort socket.  Works on Maya
        2025+ but fails on Maya 2024 (``maya.cmds`` aborts the connection).

        :param str script: Python source code to execute in Maya.
        :return: Parsed result, or None if no data came back.
        :rtype: dict or list or str or None
        """
        # Append result-printing code to the script.
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

    # --- Level 3: Deferred CommandPort ----------------------------------------

    def _run_deferred(self, script):
        """
        Execute a tool script using deferred execution (Maya 2024 workaround).

        Maya 2024's commandPort crashes when ``maya.cmds`` operations run
        inside the socket handler.  This method avoids the crash by:

        1. Sending a lightweight Python command (no ``maya.cmds``) to port
           7002 that queues the real work via ``maya.utils.executeDeferred()``.
        2. The deferred callback runs on Maya's next idle cycle (outside the
           commandPort handler) where ``maya.cmds`` is safe.
        3. The callback writes the JSON result to a temp file.
        4. This method polls the temp file and returns the result.

        :param str script: Python source code to execute in Maya.
        :return: Parsed result, or None on timeout/failure.
        :rtype: dict or list or str or None
        """
        result_file, result_file_maya = self._make_result_file()

        # Build the deferred execution script.  This code runs INSIDE the
        # commandPort handler but does NOT call maya.cmds — it only queues
        # the real work.  The actual tool script (with maya.cmds) runs in
        # the deferred callback on Maya's idle loop.
        deferred_script = (
            "import maya.utils as _mcp_utils, base64 as _mcp_b64, "
            "json as _mcp_json, traceback as _mcp_tb\n"
            "_mcp_code = _mcp_b64.b64decode('{code_b64}').decode('utf-8')\n"
            "_mcp_outfile = '{outfile}'\n"
            "def _mcp_deferred_run():\n"
            "    try:\n"
            "        exec(compile(_mcp_code, '<mca_mcp>', 'exec'), globals())\n"
            "        with open(_mcp_outfile, 'w') as _f:\n"
            "            _mcp_json.dump({{'success': True, "
            "'result': _mcp_maya_results}}, _f)\n"
            "    except Exception as _e:\n"
            "        with open(_mcp_outfile, 'w') as _f:\n"
            "            _mcp_json.dump({{'success': False, "
            "'error': str(_e), "
            "'traceback': _mcp_tb.format_exc()}}, _f)\n"
            "_mcp_utils.executeDeferred(_mcp_deferred_run)\n"
        ).format(
            code_b64=base64.b64encode(script.encode("utf-8")).decode("ascii"),
            outfile=result_file_maya,
        )

        # Send the deferred script to Maya's Python port.  We use
        # _send_fire_and_forget because we don't need a socket response —
        # the result comes from the temp file.
        success = self._send_fire_and_forget(deferred_script, self._python_port)
        if not success:
            logger.warning("Failed to send deferred script to Maya.")
            return None

        # Poll for the result file.
        return self._poll_result_file(result_file)

    def _send_fire_and_forget(self, command, port):
        """
        Send a Python command to Maya without waiting for a response.

        Used by the deferred execution path — the command queues work via
        ``executeDeferred()`` and the result is retrieved from a temp file,
        so we don't need the socket response.

        :param str command: Python code to execute.
        :param int port: TCP port (Maya's Python command port).
        :return: True if the command was sent successfully.
        :rtype: bool
        """
        # Single base64 layer is sufficient — no stdout redirect needed.
        code_b64 = base64.b64encode(command.encode("utf-8")).decode("ascii")
        wire_command = (
            'import base64; '
            'exec(compile(base64.b64decode("{}").decode("utf-8"), '
            '"<mca_mcp_deferred>", "exec"))\n'
        ).format(code_b64)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT_SECS)
        sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
        )

        try:
            sock.connect((self._host, port))
            sock.sendall(wire_command.encode("utf-8"))
            # Brief pause to let Maya's commandPort receive the data
            # before we RST the connection.
            time.sleep(0.05)
            return True
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            logger.warning(
                "Failed to send deferred command to port %d: %s", port, exc
            )
            return False
        finally:
            sock.close()

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

        # Maya 2024's commandPort never closes its side of accepted
        # connections, leaving them in CLOSE_WAIT.  After 1-2 calls the
        # accept backlog fills and Maya freezes.  SO_LINGER with a zero
        # timeout sends RST instead of FIN, tearing down both sides
        # immediately and preventing CLOSE_WAIT accumulation.
        sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
        )

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

# The Maya host the connection targets.  Defaults to localhost so local dev is
# unchanged; set via MAYA_MCP_HOST to a remote/tailnet address (the relay's IP)
# so an AI1-hosted server can drive a Maya on another box over the tailnet.
_maya_host = LOCAL_HOST


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

        # Send to Maya and get results.  Host comes from config (_maya_host) so
        # the same server can drive a local or a remote (tailnet) Maya.
        maya_conn = MayaConnection(mel_port=_mel_port, host=_maya_host)
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

    # Resolve the MEL port: CLI --port > MAYA_MEL_PORT > (MAYA_MCP_PORT - 1) > default.
    # MAYA_MCP_PORT is the PYTHON command port the MCP actually connects to
    # (mel + 1) and the port the relay forwards; the server tracks the MEL port
    # internally, so derive it.
    if args.port is not None:
        _mel_port = args.port
    elif os.environ.get("MAYA_MEL_PORT"):
        _mel_port = int(os.environ["MAYA_MEL_PORT"])
    elif os.environ.get("MAYA_MCP_PORT"):
        _mel_port = int(os.environ["MAYA_MCP_PORT"]) - 1
    else:
        _mel_port = DEFAULT_MEL_PORT

    # Resolve the Maya host: MAYA_MCP_HOST > localhost default.  AI1-Frank sets
    # this to the Maya box's tailnet IP (the relay's address); unset keeps local
    # dev on 127.0.0.1, unchanged.
    _maya_host = os.environ.get("MAYA_MCP_HOST", LOCAL_HOST)

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
    logger.info("Maya host: %s, MEL port: %d, Python port: %d",
                _maya_host, _mel_port, _mel_port + 1)

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
