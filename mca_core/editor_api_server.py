"""
MCA Editor - TCP JSON-RPC Server.

Provides a cross-process IPC server so external tools (Claude Code via MCP,
plugins, scripts) can programmatically control the editor over TCP using
the JSON-RPC 2.0 protocol (newline-delimited).

Architecture:
    - Asyncio TCP server running in a **daemon thread** so it doesn't block
      the Qt event loop.
    - Newline-delimited JSON-RPC 2.0: one JSON object per line, terminated
      by ``\\n``.
    - Thread-safe bridge: the server thread enqueues requests into a
      ``queue.Queue``, and a ``QTimer`` on the main thread drains them each
      tick (50ms), executing EditorAPI methods and setting futures.
    - Only methods listed in ``ALLOWED_METHODS`` can be called — no
      arbitrary attribute access.
    - Multiple simultaneous clients allowed (each gets its own asyncio task).
    - Port discovery file at ``~/Documents/mca_preferences/api_port.json``
      so MCP tools can find the running editor automatically.

Protocol:
    Request:  ``{"jsonrpc":"2.0","method":"get_state","params":{},"id":1}\\n``
    Response: ``{"jsonrpc":"2.0","result":{...},"id":1}\\n``
    Error:    ``{"jsonrpc":"2.0","error":{"code":-1,"message":"..."},"id":1}\\n``

Dependencies:
    - Python stdlib only (asyncio, json, queue, threading, socket)
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import queue
import socket
import threading
import time

# Module-level logger for server operations.
logger = logging.getLogger(__name__)

# --- Configuration ----------------------------------------------------------

# Default port for the API server.
DEFAULT_PORT = 7003

# Number of ports to try if the default is in use (7003-7013).
PORT_RANGE = 10

# Timeout for waiting on a main-thread method call (seconds).
METHOD_TIMEOUT = 10

# Discovery file path — MCP tools read this to find the editor.
from mca_core.platform_utils import get_preferences_dir
_PREFS_DIR = get_preferences_dir()
_DISCOVERY_FILE = os.path.join(_PREFS_DIR, "api_port.json")


# --- Whitelist of Allowed Methods -------------------------------------------

# Only these method names can be called through the JSON-RPC interface.
# Prevents arbitrary attribute access on the EditorAPI instance.
ALLOWED_METHODS = frozenset([
    # File operations.
    "open_file",
    "save_file",
    "save_all",
    "close_tab",
    "list_open_files",
    "get_active_file_path",
    "read_disk_file",
    "write_disk_file",
    # Editor content.
    "get_text",
    "set_text",
    "get_selected_text",
    "insert_text",
    "replace_range",
    "get_cursor_position",
    "get_language",
    # Navigation.
    "navigate_to",
    "go_to_line",
    # Output panel.
    "write_output",
    "get_output_text",
    "clear_output",
    # Project.
    "open_project",
    "close_project",
    "get_project",
    # Execution.
    "execute_in_dcc",
    "execute_locally",
    # Settings.
    "get_setting",
    "set_setting",
    # Status.
    "get_state",
])


# --- Server State -----------------------------------------------------------

# The dispatch queue: tuples of (method_name, params_dict, Future).
_dispatch_queue = queue.Queue()

# Server thread and event loop references.
_server_thread = None
_event_loop = None
_tcp_server = None
_bound_port = None
_running = False

# Lock for thread-safe access to server state.
_state_lock = threading.Lock()


# --- JSON-RPC Helpers -------------------------------------------------------

def _jsonrpc_result(result, request_id):
    """
    Build a JSON-RPC 2.0 success response.

    :param result: The result value.
    :param request_id: The request ID to echo back.
    :return: JSON-RPC response dict.
    :rtype: dict
    """
    return {"jsonrpc": "2.0", "result": result, "id": request_id}


def _jsonrpc_error(code, message, request_id):
    """
    Build a JSON-RPC 2.0 error response.

    :param int code: Error code.
    :param str message: Error message.
    :param request_id: The request ID to echo back (can be None).
    :return: JSON-RPC error response dict.
    :rtype: dict
    """
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": request_id}


# --- Connection Handler -----------------------------------------------------

async def _handle_client(reader, writer):
    """
    Handle a single JSON-RPC client connection.

    Reads newline-delimited JSON requests, dispatches them to the EditorAPI
    via the main-thread queue, and writes responses back.

    :param asyncio.StreamReader reader: The client reader.
    :param asyncio.StreamWriter writer: The client writer.
    """
    peer = writer.get_extra_info("peername")
    logger.info("API client connected: %s", peer)

    try:
        while True:
            # Read one line (newline-delimited JSON).
            line = await reader.readline()
            if not line:
                # Client disconnected.
                break

            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            # Parse JSON-RPC request.
            try:
                request = json.loads(line_str)
            except json.JSONDecodeError as exc:
                response = _jsonrpc_error(-32700, "Parse error: {}".format(exc), None)
                await _send_response(writer, response)
                continue

            # Validate JSON-RPC structure.
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if not method:
                response = _jsonrpc_error(-32600, "Invalid request: missing 'method'", request_id)
                await _send_response(writer, response)
                continue

            # Check the method whitelist.
            if method not in ALLOWED_METHODS:
                response = _jsonrpc_error(-32601, "Method not found: {}".format(method), request_id)
                await _send_response(writer, response)
                continue

            # Ensure params is a dict (JSON-RPC allows arrays, but we use kwargs).
            if not isinstance(params, dict):
                response = _jsonrpc_error(-32602, "Invalid params: expected object", request_id)
                await _send_response(writer, response)
                continue

            # Dispatch to the main thread and wait for the result.
            future = concurrent.futures.Future()
            _dispatch_queue.put((method, params, future))

            try:
                # Wait for the main thread to execute the method.
                result = await asyncio.get_event_loop().run_in_executor(
                    None, future.result, METHOD_TIMEOUT
                )

                # If the result is an ApiResult dict with success=False,
                # convert it to a JSON-RPC error response.
                if isinstance(result, dict) and "success" in result and not result["success"]:
                    error_msg = result.get("error", "Unknown error")
                    response = _jsonrpc_error(-1, error_msg, request_id)
                else:
                    response = _jsonrpc_result(result, request_id)

            except concurrent.futures.TimeoutError:
                response = _jsonrpc_error(-32000, "Method call timed out", request_id)
            except Exception as exc:
                response = _jsonrpc_error(-32603, "Internal error: {}".format(exc), request_id)

            await _send_response(writer, response)

    except (ConnectionResetError, BrokenPipeError, OSError):
        # Client disconnected abruptly — not an error.
        pass
    except Exception as exc:
        logger.error("Error handling API client %s: %s", peer, exc)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("API client disconnected: %s", peer)


async def _send_response(writer, response):
    """
    Serialize and send a JSON-RPC response to the client.

    :param asyncio.StreamWriter writer: The client writer.
    :param dict response: The JSON-RPC response dict.
    """
    data = json.dumps(response, default=str) + "\n"
    writer.write(data.encode("utf-8"))
    await writer.drain()


# --- Discovery File ---------------------------------------------------------

def _write_discovery_file(port):
    """
    Write the port discovery file so MCP tools can find the editor.

    :param int port: The actual bound port.
    """
    os.makedirs(_PREFS_DIR, exist_ok=True)
    discovery = {
        "port": port,
        "pid": os.getpid(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        with open(_DISCOVERY_FILE, "w", encoding="utf-8") as f:
            json.dump(discovery, f, indent=2)
        logger.info("Discovery file written: %s (port %d)", _DISCOVERY_FILE, port)
    except Exception as exc:
        logger.warning("Failed to write discovery file: %s", exc)


def _remove_discovery_file():
    """Remove the port discovery file on shutdown."""
    try:
        if os.path.isfile(_DISCOVERY_FILE):
            os.remove(_DISCOVERY_FILE)
            logger.info("Discovery file removed: %s", _DISCOVERY_FILE)
    except Exception as exc:
        logger.warning("Failed to remove discovery file: %s", exc)


# --- Server Thread ----------------------------------------------------------

def _find_available_port(start_port):
    """
    Find an available port starting from ``start_port``.

    Tries ``PORT_RANGE`` consecutive ports.  Returns the first port that
    can be bound, or raises ``OSError`` if none are available.

    :param int start_port: The first port to try.
    :return: An available port number.
    :rtype: int
    :raises OSError: If no port in the range is available.
    """
    for offset in range(PORT_RANGE):
        port = start_port + offset
        try:
            # Test whether the port is available.
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(("127.0.0.1", port))
            test_sock.close()
            return port
        except OSError:
            continue
    raise OSError(
        "No available port in range {}-{}".format(start_port, start_port + PORT_RANGE - 1)
    )


async def _run_server(port):
    """
    Start the asyncio TCP server on the given port.

    This coroutine runs in the server thread's event loop and blocks
    until the server is shut down.

    :param int port: The port to listen on.
    """
    global _tcp_server, _bound_port

    server = await asyncio.start_server(_handle_client, "127.0.0.1", port)
    _tcp_server = server
    _bound_port = port

    # Write the discovery file so external tools can find us.
    _write_discovery_file(port)

    logger.info("EditorAPI server listening on 127.0.0.1:%d", port)

    async with server:
        await server.serve_forever()


def _server_thread_main(port):
    """
    Entry point for the server daemon thread.

    Creates a new asyncio event loop, starts the TCP server, and runs
    until the loop is stopped by ``stop_server()``.

    :param int port: The port to listen on.
    """
    global _event_loop, _running

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _event_loop = loop

    try:
        loop.run_until_complete(_run_server(port))
    except asyncio.CancelledError:
        # Expected when server.close() cancels serve_forever().
        pass
    except RuntimeError:
        # Expected during shutdown: loop.stop() fires before
        # serve_forever() can process the server.close() cancellation,
        # raising "Event loop stopped before Future completed".
        pass
    except Exception as exc:
        logger.error("EditorAPI server error: %s", exc)
    finally:
        # Clean up all remaining tasks.
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()
        _event_loop = None
        _running = False
        logger.info("EditorAPI server thread exited")


# --- Public API: Start / Stop / Status --------------------------------------

def start_server(port=DEFAULT_PORT):
    """
    Start the JSON-RPC server in a daemon thread.

    Finds an available port (starting from ``port``) and spawns the
    server thread.  Safe to call multiple times — no-ops if already running.

    :param int port: The preferred port (default 7003).
    """
    global _server_thread, _running, _bound_port

    with _state_lock:
        if _running:
            logger.debug("Server already running on port %s", _bound_port)
            return

        # Find an available port before starting the thread.
        try:
            actual_port = _find_available_port(port)
        except OSError as exc:
            logger.error("Failed to find available port: %s", exc)
            return

        _running = True
        _server_thread = threading.Thread(
            target=_server_thread_main,
            args=(actual_port,),
            name="EditorAPI-Server",
            daemon=True,
        )
        _server_thread.start()
        logger.info("EditorAPI server starting on port %d...", actual_port)


def stop_server():
    """
    Stop the JSON-RPC server and clean up.

    Signals the asyncio event loop to stop, joins the server thread,
    and removes the discovery file.
    """
    global _server_thread, _running, _tcp_server, _bound_port

    with _state_lock:
        if not _running:
            return

        logger.info("Stopping EditorAPI server...")
        _running = False

        # Tell the asyncio event loop to shut down the server.
        loop = _event_loop
        server = _tcp_server
        if loop is not None and server is not None:
            try:
                loop.call_soon_threadsafe(server.close)
                # Give the server a moment to close, then stop the loop.
                loop.call_soon_threadsafe(loop.stop)
            except Exception as exc:
                logger.warning("Error stopping server loop: %s", exc)

        # Wait for the thread to finish.
        if _server_thread is not None:
            _server_thread.join(timeout=5)
            _server_thread = None

        _tcp_server = None
        _bound_port = None

    # Remove the discovery file outside the lock (filesystem I/O).
    _remove_discovery_file()


def is_running():
    """
    Check whether the server is currently running.

    :return: True if the server thread is alive.
    :rtype: bool
    """
    return _running


def get_port():
    """
    Get the port the server is actually listening on.

    :return: The bound port number, or None if not running.
    :rtype: int or None
    """
    return _bound_port


# --- Main-Thread Dispatch ---------------------------------------------------

def drain_queue():
    """
    Process all pending API requests on the Qt main thread.

    Called by a QTimer (50ms interval) on the main thread.  For each
    queued item, looks up the method on the EditorAPI singleton, calls
    it with the provided params, and sets the Future result so the
    server thread can send the response back to the client.

    This is a no-op if the queue is empty (just a ``queue.empty()`` check).
    """
    from mca_core.editor_api import get_api

    api = get_api()
    if api is None:
        # API not registered yet — drain and error all pending.
        while not _dispatch_queue.empty():
            try:
                method, params, future = _dispatch_queue.get_nowait()
                future.set_result({"success": False, "error": "API not initialized"})
            except queue.Empty:
                break
        return

    # Process all queued requests in this tick.
    while not _dispatch_queue.empty():
        try:
            method, params, future = _dispatch_queue.get_nowait()
        except queue.Empty:
            break

        try:
            # Look up the method on the API instance.
            func = getattr(api, method, None)
            if func is None:
                future.set_result({"success": False, "error": "Method not found: {}".format(method)})
                continue

            # Call the method with the provided keyword arguments.
            result = func(**params)
            future.set_result(result)
        except TypeError as exc:
            # Bad arguments (wrong kwargs, missing required params).
            future.set_result({"success": False, "error": "Invalid parameters: {}".format(exc)})
        except Exception as exc:
            # Unexpected error during method execution.
            logger.error("Error executing API method '%s': %s", method, exc)
            future.set_result({"success": False, "error": "Internal error: {}".format(exc)})
