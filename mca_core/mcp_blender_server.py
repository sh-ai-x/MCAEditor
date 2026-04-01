"""
MCA Blender MCP Server — Self-contained MCP server for Blender scene interaction.

Runs as a standalone process and communicates with Blender via a TCP socket
server addon (listening on port 8400 by default). Commands are sent as JSON
objects and responses are received as JSON.

This file must be completely standalone — zero imports from ``mca_core``.
It is copied to the deployment directory at setup time and executed inside
MayaMCP's venv (which provides the ``mcp`` package).

Protocol to Blender:
    Request:  {"command": "exec"|"eval", "code": "...", "id": N}
    Response: {"status": "ok"|"error", "output": "...", "error": "...", "id": N}

Dependencies:
    - mcp (installed in MayaMCP's .venv)

Side effects:
    - Opens TCP connection to Blender's socket server on each tool call
    - Writes log file to ``mca_preferences/mcp_servers/mca_blender_server.log``
"""

import argparse
import asyncio
import json
import logging
import os
import socket
import struct
import sys

# --- Constants ----------------------------------------------------------------

__version__ = "1.0.0"

# Default Blender socket server port.
DEFAULT_BLENDER_PORT = 8400

# TCP connection timeout (seconds).
CONNECT_TIMEOUT_SECS = 5.0

# Phase 1 recv: wait for Blender to START responding.
FIRST_RECV_TIMEOUT_SECS = 10.0

# Phase 2 recv: silence threshold once data is flowing.
IDLE_RECV_TIMEOUT_SECS = 0.5

# Larger buffer to reduce recv loop iterations.
RECV_BUFFER_SIZE = 4096

# Localhost only.
LOCAL_HOST = "127.0.0.1"

# Module-level logger — configured in __main__.
logger = logging.getLogger("MCABlenderMCP")

# Monotonic command ID for request/response matching.
_next_id = 0


# =============================================================================
# Blender Communication
# =============================================================================

def _get_next_id():
    """Return a monotonically increasing command ID."""
    global _next_id
    _next_id += 1
    return _next_id


def _send_to_blender(code, command_type="exec", port=DEFAULT_BLENDER_PORT):
    """
    Send a Python command to Blender's socket server and return the response.

    Opens a new TCP socket for each command, sends a JSON request,
    and reads the JSON response.

    :param str code: The Python code to execute/evaluate in Blender.
    :param str command_type: "exec" or "eval".
    :param int port: The TCP port of Blender's socket server.
    :return: Parsed JSON response dict.
    :rtype: dict
    :raises ConnectionRefusedError: If Blender's socket server is not running.
    :raises socket.timeout: If Blender doesn't respond in time.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # SO_LINGER with zero timeout sends RST on close to prevent CLOSE_WAIT.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.settimeout(CONNECT_TIMEOUT_SECS)

    try:
        sock.connect((LOCAL_HOST, port))

        # Build JSON request.
        request = json.dumps({
            "command": command_type,
            "code": code,
            "id": _get_next_id(),
        })

        # Send as newline-terminated UTF-8.
        sock.sendall((request + "\n").encode("utf-8"))

        # Phase 1: Wait for Blender to start responding.
        sock.settimeout(FIRST_RECV_TIMEOUT_SECS)

        response = b""
        while True:
            try:
                chunk = sock.recv(RECV_BUFFER_SIZE)
                if not chunk:
                    break
                response += chunk
                # Phase 2: short idle timeout once data is flowing.
                sock.settimeout(IDLE_RECV_TIMEOUT_SECS)
            except socket.timeout:
                break

        decoded = response.decode("utf-8", errors="replace").strip()
        if not decoded:
            return {"status": "error", "output": "", "error": "No response from Blender"}

        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            # Treat non-JSON responses as plain output.
            return {"status": "ok", "output": decoded, "error": ""}

    finally:
        sock.close()


def _execute_in_blender(code, port=DEFAULT_BLENDER_PORT):
    """
    Execute Python code in Blender and return the output.

    Convenience wrapper that extracts output/error from the JSON response.

    :param str code: Python code to execute.
    :param int port: Blender socket server port.
    :return: Tuple of (output, error).
    :rtype: tuple(str, str)
    """
    try:
        response = _send_to_blender(code, "exec", port)
        output = response.get("output", "")
        error = response.get("error", "")
        return output, error
    except ConnectionRefusedError:
        return "", "Cannot connect to Blender. Is the socket server addon running?"
    except socket.timeout:
        return "", "Blender did not respond in time."
    except Exception as exc:
        return "", "Communication error: {}".format(exc)


def _eval_in_blender(code, port=DEFAULT_BLENDER_PORT):
    """
    Evaluate a Python expression in Blender and return the result.

    :param str code: Python expression to evaluate.
    :param int port: Blender socket server port.
    :return: Tuple of (output, error).
    :rtype: tuple(str, str)
    """
    try:
        response = _send_to_blender(code, "eval", port)
        output = response.get("output", "")
        error = response.get("error", "")
        return output, error
    except ConnectionRefusedError:
        return "", "Cannot connect to Blender. Is the socket server addon running?"
    except socket.timeout:
        return "", "Blender did not respond in time."
    except Exception as exc:
        return "", "Communication error: {}".format(exc)


# =============================================================================
# MCP Server Setup
# =============================================================================

def _create_server(blender_port):
    """
    Create and configure the MCP server with Blender tools.

    :param int blender_port: TCP port of Blender's socket server.
    :return: Configured MCP Server instance.
    :rtype: Server
    """
    from mcp.server.lowlevel import NotificationOptions, Server
    from mcp.server.models import InitializationOptions
    from mcp.types import TextContent, Tool

    server = Server("MCABlenderMCP")

    # --- Tool definitions ----------------------------------------------------

    @server.list_tools()
    async def list_tools():
        """Return all available Blender tools."""
        return [
            Tool(
                name="blender_execute_python",
                description="Execute Python code in Blender's interpreter. Has access to bpy and all Blender modules.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code to execute in Blender",
                        },
                    },
                    "required": ["code"],
                },
            ),
            Tool(
                name="blender_get_scene_info",
                description="Get information about the current Blender scene: file path, version, objects, materials.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="blender_scene_new",
                description="Create a new empty Blender scene.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="blender_scene_open",
                description="Open a .blend file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Path to the .blend file to open",
                        },
                    },
                    "required": ["filepath"],
                },
            ),
            Tool(
                name="blender_scene_save",
                description="Save the current Blender scene. If filepath is provided, saves to that location (Save As).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Path to save to (optional, omit for regular Save)",
                        },
                    },
                },
            ),
            Tool(
                name="blender_create_object",
                description="Create a new mesh primitive in the Blender scene.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Object type: cube, sphere, cylinder, plane, cone, torus, monkey",
                            "enum": ["cube", "sphere", "cylinder", "plane", "cone", "torus", "monkey"],
                        },
                        "name": {
                            "type": "string",
                            "description": "Name for the new object (optional)",
                        },
                        "location": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Location as [x, y, z] (optional, default [0,0,0])",
                        },
                    },
                    "required": ["type"],
                },
            ),
            Tool(
                name="blender_select_objects",
                description="Select objects in the scene by name. Deselects all first.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of object names to select",
                        },
                    },
                    "required": ["names"],
                },
            ),
            Tool(
                name="blender_get_selected",
                description="Get the names and types of currently selected objects.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="blender_set_transform",
                description="Set the location, rotation, or scale of an object.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the object to transform",
                        },
                        "location": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "New location [x, y, z] (optional)",
                        },
                        "rotation": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "New rotation in degrees [x, y, z] (optional)",
                        },
                        "scale": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "New scale [x, y, z] (optional)",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="blender_get_object_properties",
                description="Get properties of an object: transform, dimensions, type, materials.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the object to query",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="blender_create_material",
                description="Create a new material with a base color.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name for the new material",
                        },
                        "color": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "RGBA color [r, g, b, a] with values 0.0-1.0",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="blender_assign_material",
                description="Assign a material to an object.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "Name of the object to assign material to",
                        },
                        "material_name": {
                            "type": "string",
                            "description": "Name of the material to assign",
                        },
                    },
                    "required": ["object_name", "material_name"],
                },
            ),
            Tool(
                name="blender_delete_objects",
                description="Delete objects from the scene by name.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of object names to delete",
                        },
                    },
                    "required": ["names"],
                },
            ),
            Tool(
                name="blender_viewport_focus",
                description="Focus the viewport on selected objects or a specific object.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "Name of object to focus on (optional, uses selection if omitted)",
                        },
                    },
                },
            ),
        ]

    # --- Tool call handler ---------------------------------------------------

    @server.call_tool()
    async def call_tool(name, arguments):
        """
        Route tool calls to the appropriate Blender command.

        :param str name: Tool name.
        :param dict arguments: Tool arguments.
        :return: List of TextContent with the result.
        :rtype: list
        """
        logger.info("Tool call: %s(%s)", name, arguments)
        port = blender_port

        try:
            result = _handle_tool(name, arguments, port)
            logger.info("Tool result: %s", result[:200] if len(result) > 200 else result)
            return [TextContent(type="text", text=result)]
        except Exception as exc:
            error_msg = "Error executing {}: {}".format(name, exc)
            logger.error(error_msg, exc_info=True)
            return [TextContent(type="text", text=error_msg)]

    return server


def _handle_tool(name, args, port):
    """
    Execute a tool command in Blender and return the result as a string.

    :param str name: Tool name.
    :param dict args: Tool arguments.
    :param int port: Blender socket server port.
    :return: Result text.
    :rtype: str
    """
    if name == "blender_execute_python":
        code = args.get("code", "")
        output, error = _execute_in_blender(code, port)
        if error:
            return "Error:\n{}".format(error)
        return output if output else "(no output)"

    elif name == "blender_get_scene_info":
        code = (
            "import json, bpy\n"
            "info = {\n"
            "    'file': bpy.data.filepath or '(unsaved)',\n"
            "    'blender_version': '.'.join(str(v) for v in bpy.app.version),\n"
            "    'render_engine': bpy.context.scene.render.engine,\n"
            "    'objects': [{'name': o.name, 'type': o.type} for o in bpy.data.objects],\n"
            "    'materials': [m.name for m in bpy.data.materials],\n"
            "    'selected': [o.name for o in bpy.context.selected_objects],\n"
            "    'active': bpy.context.active_object.name if bpy.context.active_object else None,\n"
            "    'collections': [c.name for c in bpy.data.collections],\n"
            "}\n"
            "print(json.dumps(info, indent=2))\n"
        )
        output, error = _execute_in_blender(code, port)
        if error:
            return "Error:\n{}".format(error)
        return output

    elif name == "blender_scene_new":
        code = "import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); print('New scene created')"
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_scene_open":
        filepath = args.get("filepath", "")
        code = "import bpy; bpy.ops.wm.open_mainfile(filepath={!r}); print('Opened: ' + bpy.data.filepath)".format(filepath)
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_scene_save":
        filepath = args.get("filepath", "")
        if filepath:
            code = "import bpy; bpy.ops.wm.save_as_mainfile(filepath={!r}); print('Saved to: ' + bpy.data.filepath)".format(filepath)
        else:
            code = "import bpy; bpy.ops.wm.save_mainfile(); print('Saved: ' + bpy.data.filepath)"
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_create_object":
        obj_type = args.get("type", "cube")
        obj_name = args.get("name", "")
        location = args.get("location", [0, 0, 0])

        # Map type names to bpy.ops calls.
        ops_map = {
            "cube": "bpy.ops.mesh.primitive_cube_add(location={loc})",
            "sphere": "bpy.ops.mesh.primitive_uv_sphere_add(location={loc})",
            "cylinder": "bpy.ops.mesh.primitive_cylinder_add(location={loc})",
            "plane": "bpy.ops.mesh.primitive_plane_add(location={loc})",
            "cone": "bpy.ops.mesh.primitive_cone_add(location={loc})",
            "torus": "bpy.ops.mesh.primitive_torus_add(location={loc})",
            "monkey": "bpy.ops.mesh.primitive_monkey_add(location={loc})",
        }
        op = ops_map.get(obj_type, ops_map["cube"])
        code = "import bpy\n"
        code += op.format(loc=repr(tuple(location))) + "\n"
        if obj_name:
            code += "bpy.context.active_object.name = {!r}\n".format(obj_name)
        code += "print('Created: ' + bpy.context.active_object.name)\n"
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_select_objects":
        names = args.get("names", [])
        code = (
            "import bpy\n"
            "bpy.ops.object.select_all(action='DESELECT')\n"
            "selected = []\n"
            "for name in {names!r}:\n"
            "    obj = bpy.data.objects.get(name)\n"
            "    if obj:\n"
            "        obj.select_set(True)\n"
            "        selected.append(name)\n"
            "if selected:\n"
            "    bpy.context.view_layer.objects.active = bpy.data.objects[selected[0]]\n"
            "print('Selected: ' + ', '.join(selected))\n"
        ).format(names=names)
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_get_selected":
        code = (
            "import json, bpy\n"
            "selected = [{'name': o.name, 'type': o.type} for o in bpy.context.selected_objects]\n"
            "active = bpy.context.active_object.name if bpy.context.active_object else None\n"
            "print(json.dumps({'selected': selected, 'active': active}, indent=2))\n"
        )
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_set_transform":
        obj_name = args.get("name", "")
        code = "import bpy, math\n"
        code += "obj = bpy.data.objects.get({!r})\n".format(obj_name)
        code += "if obj is None:\n"
        code += "    print('Error: Object not found: {}')\n".format(obj_name)
        code += "else:\n"
        if "location" in args:
            loc = args["location"]
            code += "    obj.location = {}\n".format(repr(tuple(loc)))
        if "rotation" in args:
            rot = args["rotation"]
            code += "    obj.rotation_euler = ({}, {}, {})\n".format(
                "math.radians({})".format(rot[0]),
                "math.radians({})".format(rot[1]),
                "math.radians({})".format(rot[2]),
            )
        if "scale" in args:
            scl = args["scale"]
            code += "    obj.scale = {}\n".format(repr(tuple(scl)))
        code += "    print('Transformed: ' + obj.name)\n"
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_get_object_properties":
        obj_name = args.get("name", "")
        code = (
            "import json, bpy\n"
            "obj = bpy.data.objects.get({name!r})\n"
            "if obj is None:\n"
            "    print('Error: Object not found: {name}')\n"
            "else:\n"
            "    props = {{\n"
            "        'name': obj.name,\n"
            "        'type': obj.type,\n"
            "        'location': list(obj.location),\n"
            "        'rotation_euler': list(obj.rotation_euler),\n"
            "        'scale': list(obj.scale),\n"
            "        'dimensions': list(obj.dimensions),\n"
            "        'materials': [m.name for m in obj.data.materials] if hasattr(obj.data, 'materials') else [],\n"
            "        'parent': obj.parent.name if obj.parent else None,\n"
            "        'children': [c.name for c in obj.children],\n"
            "        'visible': obj.visible_get(),\n"
            "    }}\n"
            "    print(json.dumps(props, indent=2))\n"
        ).format(name=obj_name)
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_create_material":
        mat_name = args.get("name", "Material")
        color = args.get("color", [0.8, 0.8, 0.8, 1.0])
        code = (
            "import bpy\n"
            "mat = bpy.data.materials.new(name={name!r})\n"
            "mat.use_nodes = True\n"
            "bsdf = mat.node_tree.nodes.get('Principled BSDF')\n"
            "if bsdf:\n"
            "    bsdf.inputs['Base Color'].default_value = {color}\n"
            "print('Created material: ' + mat.name)\n"
        ).format(name=mat_name, color=repr(tuple(color)))
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_assign_material":
        obj_name = args.get("object_name", "")
        mat_name = args.get("material_name", "")
        code = (
            "import bpy\n"
            "obj = bpy.data.objects.get({obj!r})\n"
            "mat = bpy.data.materials.get({mat!r})\n"
            "if obj is None:\n"
            "    print('Error: Object not found: {obj}')\n"
            "elif mat is None:\n"
            "    print('Error: Material not found: {mat}')\n"
            "else:\n"
            "    if obj.data.materials:\n"
            "        obj.data.materials[0] = mat\n"
            "    else:\n"
            "        obj.data.materials.append(mat)\n"
            "    print('Assigned {{}} to {{}}'.format(mat.name, obj.name))\n"
        ).format(obj=obj_name, mat=mat_name)
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_delete_objects":
        names = args.get("names", [])
        code = (
            "import bpy\n"
            "deleted = []\n"
            "bpy.ops.object.select_all(action='DESELECT')\n"
            "for name in {names!r}:\n"
            "    obj = bpy.data.objects.get(name)\n"
            "    if obj:\n"
            "        obj.select_set(True)\n"
            "        deleted.append(name)\n"
            "if deleted:\n"
            "    bpy.ops.object.delete()\n"
            "print('Deleted: ' + ', '.join(deleted) if deleted else 'No objects found')\n"
        ).format(names=names)
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    elif name == "blender_viewport_focus":
        obj_name = args.get("object_name", "")
        if obj_name:
            code = (
                "import bpy\n"
                "bpy.ops.object.select_all(action='DESELECT')\n"
                "obj = bpy.data.objects.get({name!r})\n"
                "if obj:\n"
                "    obj.select_set(True)\n"
                "    bpy.context.view_layer.objects.active = obj\n"
                "for area in bpy.context.screen.areas:\n"
                "    if area.type == 'VIEW_3D':\n"
                "        for region in area.regions:\n"
                "            if region.type == 'WINDOW':\n"
                "                with bpy.context.temp_override(area=area, region=region):\n"
                "                    bpy.ops.view3d.view_selected()\n"
                "                break\n"
                "        break\n"
                "print('Focused on: {name}')\n"
            ).format(name=obj_name)
        else:
            code = (
                "import bpy\n"
                "for area in bpy.context.screen.areas:\n"
                "    if area.type == 'VIEW_3D':\n"
                "        for region in area.regions:\n"
                "            if region.type == 'WINDOW':\n"
                "                with bpy.context.temp_override(area=area, region=region):\n"
                "                    bpy.ops.view3d.view_selected()\n"
                "                break\n"
                "        break\n"
                "print('Focused on selection')\n"
            )
        output, error = _execute_in_blender(code, port)
        return output if not error else "Error: {}".format(error)

    else:
        return "Unknown tool: {}".format(name)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """
    Parse CLI arguments, set up logging, and run the MCP server.
    """
    parser = argparse.ArgumentParser(description="MCA Blender MCP Server")
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("BLENDER_PORT", DEFAULT_BLENDER_PORT)),
        help="Blender socket server port (default: {})".format(DEFAULT_BLENDER_PORT),
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    args = parser.parse_args()

    # --- Logging setup -------------------------------------------------------
    # Write logs to a file in mca_preferences/mcp_servers/ alongside the server.
    home = os.path.expanduser("~")
    if sys.platform in ("win32", "darwin"):
        log_dir = os.path.join(home, "Documents", "mca_preferences", "mcp_servers")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        log_dir = os.path.join(xdg, "mca_preferences", "mcp_servers")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "mca_blender_server.log")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),
        ],
    )

    logger.info("MCA Blender MCP Server v%s starting", __version__)
    logger.info("Blender port: %d", args.port)
    logger.info("Log file: %s", log_file)

    # --- Create and run the MCP server ---------------------------------------
    server = _create_server(args.port)

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream,
                InitializationOptions(
                    server_name="MCABlenderMCP",
                    server_version=__version__,
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
