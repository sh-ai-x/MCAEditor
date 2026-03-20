"""
Unreal Engine Remote Execution Protocol Spike Test.

Validates that we can reliably send Python code to a running UE instance
and get output back. This is Phase 0 of the MCA Editor Unreal plugin —
its findings determine the entire communication strategy for both the
MCP server and the C++ PythonBridge.

Requirements:
    - Unreal Engine 5.4+ running with the Python Editor Script Plugin enabled
    - Remote Execution enabled in Editor Preferences > Python > Remote Execution

Usage:
    python tools/ue_remote_exec_spike.py

Protocol Reference:
    UE Remote Execution uses a two-phase approach:
    1. UDP multicast discovery on 239.0.0.1:6766 to find running UE instances
    2. TCP connection to the discovered command port for code execution
    Wire format is a custom binary protocol with magic bytes, JSON payload.

Side Effects:
    - Sends UDP multicast packets on 239.0.0.1:6766
    - Establishes TCP connection to the discovered UE instance
    - Executes Python code inside Unreal's interpreter
"""

import socket
import struct
import json
import uuid
import time
import sys
import hashlib

# --- Constants ---------------------------------------------------------

# UE Remote Execution multicast group and port for node discovery.
MULTICAST_GROUP = "239.0.0.1"
MULTICAST_PORT = 6766

# Magic bytes that prefix every Remote Execution protocol message.
# From Engine/Plugins/Scripting/PythonScriptPlugin/Source/PythonScriptPlugin/Private/PythonScriptRemoteExecution.cpp
PROTOCOL_MAGIC = b"ue_py"

# Protocol version — UE 5.4 uses version 2 (added in ~4.26).
PROTOCOL_VERSION = 2

# --- Message Types (from EPythonCommandResponseType) -------------------

# "N" = ping/discovery (broadcast on multicast).
MSG_PING = ord("N")

# "C" = command execution request.
MSG_COMMAND = ord("C")

# "R" = command response.
MSG_RESPONSE = ord("R")

# --- Execution Modes (from EPythonCommandExecutionMode) ----------------

# Execute the Python command as a file (like running a .py file).
EXEC_FILE = ord("F")

# Execute as individual statements (REPL-like).
EXEC_STATEMENT = ord("S")

# Evaluate as an expression (returns the result).
EXEC_EVALUATE = ord("X")

# --- Discovery Timeout -------------------------------------------------

# How long to wait for UE instance discovery via multicast (seconds).
DISCOVERY_TIMEOUT = 5.0

# How long to wait for a command response (seconds).
COMMAND_TIMEOUT = 10.0


# --- Wire Protocol Helpers --------------------------------------------

def _build_message(msg_type, payload_dict):
    """
    Build a UE Remote Execution protocol message.

    The wire format is:
        [5 bytes magic "ue_py"]
        [4 bytes version (uint32 LE)]
        [4 bytes payload size (uint32 LE)]
        [N bytes UTF-8 JSON payload]

    :param int msg_type: One of MSG_PING, MSG_COMMAND, MSG_RESPONSE.
    :param dict payload_dict: The JSON payload to serialize.
    :return: The complete binary message.
    :rtype: bytes
    """
    # Serialize the payload to compact JSON bytes.
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")

    # Build the header: magic + version + size.
    header = PROTOCOL_MAGIC
    header += struct.pack("<I", PROTOCOL_VERSION)
    header += struct.pack("<I", len(payload_bytes))

    return header + payload_bytes


def _parse_message(data):
    """
    Parse a UE Remote Execution protocol message from raw bytes.

    :param bytes data: Raw bytes received from the socket.
    :return: Tuple of (version, payload_dict) or None if invalid.
    :rtype: tuple or None
    """
    # Validate minimum size: 5 (magic) + 4 (version) + 4 (size) = 13 bytes.
    if len(data) < 13:
        print(f"  [WARN] Message too short: {len(data)} bytes")
        return None

    # Check magic bytes.
    magic = data[:5]
    if magic != PROTOCOL_MAGIC:
        print(f"  [WARN] Bad magic: {magic!r} (expected {PROTOCOL_MAGIC!r})")
        return None

    # Unpack version and payload size.
    version = struct.unpack("<I", data[5:9])[0]
    payload_size = struct.unpack("<I", data[9:13])[0]

    # Extract and parse the JSON payload.
    payload_bytes = data[13:13 + payload_size]
    if len(payload_bytes) < payload_size:
        print(f"  [WARN] Truncated payload: got {len(payload_bytes)}, expected {payload_size}")
        return None

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"  [WARN] Failed to parse payload: {exc}")
        return None

    return version, payload


def _generate_node_id():
    """
    Generate a unique node ID for this spike script.

    UE expects each remote execution client to identify itself with a
    unique ID. We use a UUID4 to avoid collisions.

    :return: A unique node ID string.
    :rtype: str
    """
    return str(uuid.uuid4())


# --- Discovery ---------------------------------------------------------

def discover_ue_instance():
    """
    Discover a running Unreal Engine instance via UDP multicast.

    Sends a ping message on the multicast group and waits for a response
    containing the UE instance's command IP and port.

    :return: Tuple of (ip, port, node_id) for the discovered UE instance, or None.
    :rtype: tuple or None
    """
    node_id = _generate_node_id()
    print(f"[DISCOVERY] Searching for UE instance on {MULTICAST_GROUP}:{MULTICAST_PORT}...")
    print(f"  Our node ID: {node_id}")

    # Build the ping/discovery message.
    ping_payload = {
        "type": "N",
        "source": node_id,
    }

    # Create a UDP socket for multicast.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Set multicast TTL to 1 (local network only).
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

    # Bind to the multicast port to receive responses.
    sock.bind(("", MULTICAST_PORT))

    # Join the multicast group on all interfaces.
    mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    # Set receive timeout.
    sock.settimeout(DISCOVERY_TIMEOUT)

    # Send the ping message to the multicast group.
    msg = _build_message(MSG_PING, ping_payload)
    sock.sendto(msg, (MULTICAST_GROUP, MULTICAST_PORT))
    print(f"  Sent ping ({len(msg)} bytes), waiting for response...")

    try:
        while True:
            data, addr = sock.recvfrom(4096)

            result = _parse_message(data)
            if result is None:
                continue

            version, payload = result

            # Skip our own ping (we're on the same multicast group).
            if payload.get("source") == node_id:
                continue

            print(f"  Received response from {addr}: {json.dumps(payload, indent=2)}")

            # Extract the command connection info.
            # UE sends back its command IP and port in the payload.
            command_ip = payload.get("command_ip", addr[0])
            command_port = payload.get("command_port")

            if command_port:
                print(f"  [OK] Found UE instance at {command_ip}:{command_port}")
                sock.close()
                return command_ip, command_port, payload.get("source", "unknown")
            else:
                print(f"  [INFO] Got response but no command_port — checking payload keys: {list(payload.keys())}")

    except socket.timeout:
        print(f"  [TIMEOUT] No UE instance found after {DISCOVERY_TIMEOUT}s")
        print("  Make sure:")
        print("    1. Unreal Engine is running")
        print("    2. Python Editor Script Plugin is enabled")
        print("    3. Remote Execution is enabled in Editor Preferences > Python")
        sock.close()
        return None

    finally:
        try:
            sock.close()
        except Exception:
            pass


def connect_direct(host="127.0.0.1", port=6776):
    """
    Skip discovery and connect directly to a known UE Remote Execution port.

    This is a fallback if multicast discovery doesn't work (firewall, etc.).

    :param str host: The UE instance IP address.
    :param int port: The UE Remote Execution TCP port (default 6776).
    :return: Tuple of (ip, port, "direct") or None if connection refused.
    :rtype: tuple or None
    """
    print(f"[DIRECT] Attempting direct TCP connection to {host}:{port}...")

    # Quick connection test.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3.0)
    try:
        sock.connect((host, port))
        sock.close()
        print(f"  [OK] Connection accepted at {host}:{port}")
        return host, port, "direct"
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        print(f"  [FAIL] Connection refused: {exc}")
        return None
    finally:
        sock.close()


# --- Command Execution --------------------------------------------------

def execute_command(host, port, code, exec_mode=EXEC_FILE):
    """
    Execute a Python command on the UE instance via TCP.

    :param str host: UE instance IP.
    :param int port: UE command TCP port.
    :param str code: Python code string to execute.
    :param int exec_mode: Execution mode (EXEC_FILE, EXEC_STATEMENT, EXEC_EVALUATE).
    :return: The response payload dict, or None on error.
    :rtype: dict or None
    """
    # Generate a unique command ID for correlation.
    command_id = str(uuid.uuid4())

    # Build the command payload.
    payload = {
        "type": "C",
        "id": command_id,
        "body": code,
        "exec_mode": chr(exec_mode),
    }

    print(f"\n[EXEC] Sending command (mode={chr(exec_mode)}):")
    print(f"  Code: {code!r}")

    # Create TCP connection.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(COMMAND_TIMEOUT)

    try:
        sock.connect((host, port))

        # Send the command message.
        msg = _build_message(MSG_COMMAND, payload)
        sock.sendall(msg)
        print(f"  Sent {len(msg)} bytes, waiting for response...")

        # Read the response — accumulate data until we have a complete message.
        response_data = b""
        while True:
            try:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                response_data += chunk

                # Try to parse — if we have enough data, we're done.
                if len(response_data) >= 13:
                    payload_size = struct.unpack("<I", response_data[9:13])[0]
                    if len(response_data) >= 13 + payload_size:
                        break
            except socket.timeout:
                print("  [TIMEOUT] No more data after timeout")
                break

        if not response_data:
            print("  [ERROR] No response received")
            return None

        result = _parse_message(response_data)
        if result is None:
            print(f"  [ERROR] Failed to parse response ({len(response_data)} bytes)")
            print(f"  Raw: {response_data[:200]!r}")
            return None

        version, resp_payload = result
        return resp_payload

    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        print(f"  [ERROR] Connection failed: {exc}")
        return None

    finally:
        sock.close()


# --- Stdout Redirect Wrapper -------------------------------------------

def make_stdout_wrapper(code):
    """
    Wrap code in a stdout/stderr redirect, analogous to Maya's StringIO trick.

    If UE's Remote Execution doesn't return print() output in the response
    payload, we use this wrapper to capture stdout and return it explicitly.

    :param str code: The original Python code to execute.
    :return: Wrapped code that captures stdout and returns it as a string.
    :rtype: str
    """
    # Escape the code for embedding in a triple-quoted string.
    escaped = code.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')

    wrapper = f'''
import sys
import io

_mca_old_stdout = sys.stdout
_mca_old_stderr = sys.stderr
_mca_stdout_buf = io.StringIO()
_mca_stderr_buf = io.StringIO()
sys.stdout = _mca_stdout_buf
sys.stderr = _mca_stderr_buf

_mca_result = None
_mca_error = None

try:
    _mca_code = """{escaped}"""
    try:
        _mca_result = str(eval(_mca_code))
    except SyntaxError:
        exec(_mca_code)
except Exception as _mca_exc:
    import traceback
    _mca_error = traceback.format_exc()
finally:
    sys.stdout = _mca_old_stdout
    sys.stderr = _mca_old_stderr

_mca_out = _mca_stdout_buf.getvalue()
_mca_err = _mca_stderr_buf.getvalue()

# Build a result string that the MCP server can parse.
import json
print("__MCA_RESULT__" + json.dumps({{"stdout": _mca_out, "stderr": _mca_err, "result": _mca_result, "error": _mca_error}}) + "__MCA_END__")
'''
    return wrapper


# --- Test Suite ---------------------------------------------------------

def run_tests(host, port):
    """
    Run the full spike test suite against a connected UE instance.

    Tests cover:
    1. Simple print() — does output appear in the response?
    2. Expression evaluation — do we get return values?
    3. Error handling — how are tracebacks formatted?
    4. Multi-line code — does exec mode work?
    5. unreal module access — can we call UE APIs?
    6. Stdout wrapper — does our fallback capture work?

    :param str host: UE instance IP.
    :param int port: UE command TCP port.
    """
    results = {}

    # --- Test 1: Simple print() output ---
    print("\n" + "=" * 70)
    print("TEST 1: Does print() output appear in the response?")
    print("=" * 70)
    resp = execute_command(host, port, 'print("hello_from_mca")')
    results["print_output"] = resp
    if resp:
        print(f"  Response payload: {json.dumps(resp, indent=2)}")
        # Check if "hello_from_mca" appears anywhere in the response.
        resp_str = json.dumps(resp)
        if "hello_from_mca" in resp_str:
            print("  [PASS] print() output IS in the response payload!")
            results["print_in_response"] = True
        else:
            print("  [INFO] print() output NOT in the response payload.")
            print("  -> We will need the stdout redirect wrapper.")
            results["print_in_response"] = False
    else:
        print("  [FAIL] No response at all.")
        results["print_in_response"] = None

    # --- Test 2: Expression evaluation ---
    print("\n" + "=" * 70)
    print("TEST 2: Does expression evaluation return a value?")
    print("=" * 70)
    resp = execute_command(host, port, "1 + 1", exec_mode=EXEC_EVALUATE)
    results["eval_result"] = resp
    if resp:
        print(f"  Response payload: {json.dumps(resp, indent=2)}")
        resp_str = json.dumps(resp)
        if "2" in resp_str:
            print("  [PASS] Expression result IS in the response!")
            results["eval_in_response"] = True
        else:
            print("  [INFO] Expression result NOT in the response.")
            results["eval_in_response"] = False

    # --- Test 3: Error / traceback ---
    print("\n" + "=" * 70)
    print("TEST 3: How are Python errors returned?")
    print("=" * 70)
    resp = execute_command(host, port, "raise ValueError('test_error_from_mca')")
    results["error_result"] = resp
    if resp:
        print(f"  Response payload: {json.dumps(resp, indent=2)}")
        resp_str = json.dumps(resp)
        if "test_error_from_mca" in resp_str:
            print("  [PASS] Error message IS in the response!")
        else:
            print("  [INFO] Error message NOT in the response.")

    # --- Test 4: Multi-line code execution ---
    print("\n" + "=" * 70)
    print("TEST 4: Multi-line code execution")
    print("=" * 70)
    multi_code = """
x = 42
y = x * 2
print(f"result={y}")
"""
    resp = execute_command(host, port, multi_code)
    results["multiline_result"] = resp
    if resp:
        print(f"  Response payload: {json.dumps(resp, indent=2)}")
        resp_str = json.dumps(resp)
        if "result=84" in resp_str:
            print("  [PASS] Multi-line output captured!")
        else:
            print("  [INFO] Multi-line output NOT captured.")

    # --- Test 5: unreal module access ---
    print("\n" + "=" * 70)
    print("TEST 5: Can we access the unreal module?")
    print("=" * 70)
    resp = execute_command(host, port, "import unreal; print(unreal.SystemLibrary.get_engine_version())")
    results["unreal_access"] = resp
    if resp:
        print(f"  Response payload: {json.dumps(resp, indent=2)}")

    # --- Test 6: Stdout redirect wrapper ---
    print("\n" + "=" * 70)
    print("TEST 6: Stdout redirect wrapper (fallback capture)")
    print("=" * 70)
    wrapped = make_stdout_wrapper('print("wrapped_output_test")')
    resp = execute_command(host, port, wrapped)
    results["wrapper_result"] = resp
    if resp:
        print(f"  Response payload: {json.dumps(resp, indent=2)}")
        resp_str = json.dumps(resp)
        if "wrapped_output_test" in resp_str:
            print("  [PASS] Stdout wrapper captured output!")
        else:
            print("  [INFO] Stdout wrapper did NOT capture output.")

    # --- Test 7: Latency measurement ---
    print("\n" + "=" * 70)
    print("TEST 7: Latency measurement (10 round trips)")
    print("=" * 70)
    latencies = []
    for i in range(10):
        start = time.perf_counter()
        resp = execute_command(host, port, f"_ = {i}")
        elapsed = time.perf_counter() - start
        if resp is not None:
            latencies.append(elapsed)
            print(f"  Round trip {i + 1}: {elapsed * 1000:.1f}ms")
    if latencies:
        avg = sum(latencies) / len(latencies)
        print(f"  Average: {avg * 1000:.1f}ms")
        print(f"  Min: {min(latencies) * 1000:.1f}ms, Max: {max(latencies) * 1000:.1f}ms")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  print() output in response: {results.get('print_in_response')}")
    print(f"  eval() result in response:  {results.get('eval_in_response')}")
    if results.get("print_in_response"):
        print("\n  STRATEGY: Use protocol as-is. Simpler than Maya.")
        print("  No stdout redirect wrapper needed.")
    elif results.get("print_in_response") is False:
        print("\n  STRATEGY: Need stdout redirect wrapper (like Maya's StringIO trick).")
        print("  The make_stdout_wrapper() function should be used in mcp_unreal_server.py.")
    else:
        print("\n  STRATEGY: Could not determine — manual investigation needed.")

    return results


# --- Entry Point -------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("MCA Editor — Unreal Engine Remote Execution Spike")
    print("=" * 70)
    print()

    # Try discovery first, fall back to direct connection.
    connection = discover_ue_instance()

    if connection is None:
        print("\n[FALLBACK] Multicast discovery failed, trying direct connection...")
        connection = connect_direct()

    if connection is None:
        print("\n[FATAL] Could not connect to any Unreal Engine instance.")
        print("Make sure UE is running with Remote Execution enabled:")
        print("  Editor Preferences > Plugins > Python > Remote Execution > Enable Remote Execution")
        sys.exit(1)

    host, port, node_id = connection
    print(f"\n[CONNECTED] UE instance: {host}:{port} (node: {node_id})")

    # Run the full test suite.
    run_tests(host, port)

    print("\n[DONE] Spike complete. Use findings to inform PythonBridge.cpp and mcp_unreal_server.py.")
