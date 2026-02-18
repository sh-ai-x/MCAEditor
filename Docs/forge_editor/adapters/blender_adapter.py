"""
Forge Editor - Blender Adapter
Connects to Blender via socket server addon for script execution.
"""

import socket
import json
from typing import List, Dict, Any, Optional

from .base_adapter import DCCAdapter, DCCType, ConnectionState


class BlenderAdapter(DCCAdapter):
    """
    Blender DCC adapter.
    
    Connection: TCP socket to a lightweight Blender addon that exposes
    a command server. Similar pattern to BlenderMCP.
    
    Setup in Blender (user installs addon):
        The Forge Blender Connector addon opens a socket server
        that accepts Python code for execution in Blender's context.
    """
    
    def __init__(self):
        super().__init__()
        self._host = "localhost"
        self._port = 7002
        self._timeout = 5.0
    
    @property
    def dcc_type(self) -> DCCType:
        return DCCType.BLENDER
    
    @property
    def display_name(self) -> str:
        return "Blender"
    
    @property
    def supported_languages(self) -> List[str]:
        return ["python"]
    
    @property
    def default_port(self) -> int:
        return 7002
    
    def connect(self, host: str = "localhost", port: int = None) -> bool:
        self._host = host
        if port:
            self._port = port
        
        self.state = ConnectionState.CONNECTING
        
        try:
            result = self._send_command(json.dumps({
                "command": "eval",
                "code": "import bpy; bpy.app.version_string"
            }))
            if result:
                self.state = ConnectionState.CONNECTED
                if self._on_output:
                    self._on_output(f"Connected to Blender: {result.strip()}")
                return True
            else:
                self.state = ConnectionState.ERROR
                if self._on_error:
                    self._on_error("No response from Blender")
                return False
        except ConnectionRefusedError:
            self.state = ConnectionState.ERROR
            if self._on_error:
                self._on_error(
                    f"Connection refused on {host}:{self._port}. "
                    "Make sure Blender is running with the Forge Connector addon enabled."
                )
            return False
        except Exception as e:
            self.state = ConnectionState.ERROR
            if self._on_error:
                self._on_error(f"Failed to connect to Blender: {str(e)}")
            return False
    
    def disconnect(self):
        self.state = ConnectionState.DISCONNECTED
        if self._on_output:
            self._on_output("Disconnected from Blender")
    
    def ping(self) -> bool:
        try:
            result = self._send_command(json.dumps({"command": "ping"}))
            return result is not None
        except Exception:
            self.state = ConnectionState.DISCONNECTED
            return False
    
    def execute(self, code: str, language: str = None) -> str:
        if not self.is_connected:
            return "Error: Not connected to Blender"
        
        try:
            result = self._send_command(json.dumps({
                "command": "exec",
                "code": code
            }))
            if result and self._on_output:
                self._on_output(result)
            return result or ""
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            if self._on_error:
                self._on_error(error_msg)
            return error_msg
    
    def execute_file(self, filepath: str) -> str:
        code = f'exec(open(r"{filepath}").read())'
        return self.execute(code)
    
    def get_completions(self, partial: str, language: str = None) -> List[Dict[str, str]]:
        completions = []
        if not self.is_connected:
            return completions
        
        try:
            if "." in partial:
                obj_part = partial.rsplit(".", 1)[0]
                attr_prefix = partial.rsplit(".", 1)[1]
                code = (
                    f'import json; '
                    f'json.dumps([x for x in dir({obj_part}) '
                    f'if x.startswith("{attr_prefix}") and not x.startswith("__")][:30])'
                )
            else:
                code = (
                    f'import json; '
                    f'json.dumps([x for x in dir() '
                    f'if x.startswith("{partial}")][:30])'
                )
            
            result = self._send_command(json.dumps({"command": "eval", "code": code}))
            if result:
                items = json.loads(result.strip())
                for item in items:
                    completions.append({
                        "label": item,
                        "detail": "Python (Blender)",
                        "insert_text": item,
                    })
        except Exception:
            pass
        
        return completions
    
    def get_scene_info(self) -> Dict[str, Any]:
        info = super().get_scene_info()
        if not self.is_connected:
            return info
        
        try:
            result = self._send_command(json.dumps({
                "command": "eval",
                "code": (
                    "import bpy, json; json.dumps({"
                    "'file': bpy.data.filepath, "
                    "'version': bpy.app.version_string, "
                    "'selected': [o.name for o in bpy.context.selected_objects], "
                    "'active': bpy.context.active_object.name if bpy.context.active_object else None"
                    "})"
                )
            }))
            if result:
                info.update(json.loads(result.strip()))
        except Exception:
            pass
        
        return info
    
    def get_mcp_server_info(self) -> Optional[Dict[str, Any]]:
        return {
            "name": "BlenderMCP",
            "description": "MCP server for Blender scene manipulation",
            "url": "https://blender-mcp.com/",
            "installed": False,
        }
    
    def _send_command(self, message: str) -> Optional[str]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        
        try:
            sock.connect((self._host, self._port))
            sock.sendall((message + "\n").encode("utf-8"))
            
            response = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break
            
            return response.decode("utf-8", errors="replace")
        finally:
            sock.close()
