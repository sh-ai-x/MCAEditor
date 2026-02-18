"""
Forge Editor - Maya Adapter
Connects to Autodesk Maya via command port (socket) for script execution,
auto-complete, and scene information.
"""

import socket
import json
from typing import List, Dict, Any, Optional

from .base_adapter import DCCAdapter, DCCType, ConnectionState


class MayaAdapter(DCCAdapter):
    """
    Maya DCC adapter.
    
    Connection methods:
    1. Maya command port (TCP socket) - for MEL and Python execution
    2. Qt parenting - when running inside Maya's process (future)
    
    Setup in Maya (user runs this once):
        import maya.cmds as cmds
        cmds.commandPort(name=":7001", sourceType="mel", echoOutput=True)
        # For Python:
        cmds.commandPort(name=":7002", sourceType="python", echoOutput=True)
    """
    
    def __init__(self):
        super().__init__()
        self._host = "localhost"
        self._mel_port = 7001
        self._python_port = 7002
        self._socket = None
        self._timeout = 5.0
    
    @property
    def dcc_type(self) -> DCCType:
        return DCCType.MAYA
    
    @property
    def display_name(self) -> str:
        return "Autodesk Maya"
    
    @property
    def supported_languages(self) -> List[str]:
        return ["python", "mel"]
    
    @property
    def default_port(self) -> int:
        return 7001
    
    def connect(self, host: str = "localhost", port: int = None) -> bool:
        """Connect to Maya's command port."""
        self._host = host
        if port:
            self._mel_port = port
            self._python_port = port + 1
        
        self.state = ConnectionState.CONNECTING
        
        try:
            # Test connection with a simple MEL command
            result = self._send_command("about -version", self._mel_port)
            if result:
                self.state = ConnectionState.CONNECTED
                if self._on_output:
                    self._on_output(f"Connected to Maya: {result.strip()}")
                return True
            else:
                self.state = ConnectionState.ERROR
                if self._on_error:
                    self._on_error("Connected but received no response from Maya")
                return False
        except ConnectionRefusedError:
            self.state = ConnectionState.ERROR
            if self._on_error:
                self._on_error(
                    f"Connection refused on {host}:{self._mel_port}. "
                    "Make sure Maya is running and command port is open.\n"
                    "Run in Maya's script editor:\n"
                    '  cmds.commandPort(name=":7001", sourceType="mel", echoOutput=True)\n'
                    '  cmds.commandPort(name=":7002", sourceType="python", echoOutput=True)'
                )
            return False
        except Exception as e:
            self.state = ConnectionState.ERROR
            if self._on_error:
                self._on_error(f"Failed to connect to Maya: {str(e)}")
            return False
    
    def disconnect(self):
        """Disconnect from Maya."""
        self.state = ConnectionState.DISCONNECTED
        if self._on_output:
            self._on_output("Disconnected from Maya")
    
    def ping(self) -> bool:
        """Check if Maya is still responding."""
        try:
            result = self._send_command("about -version", self._mel_port)
            return result is not None
        except Exception:
            self.state = ConnectionState.DISCONNECTED
            return False
    
    def execute(self, code: str, language: str = None) -> str:
        """Execute code in Maya's interpreter."""
        if not self.is_connected:
            return "Error: Not connected to Maya"
        
        if language is None:
            language = "python"
        
        port = self._python_port if language == "python" else self._mel_port
        
        try:
            result = self._send_command(code, port)
            if result and self._on_output:
                self._on_output(result)
            return result or ""
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            if self._on_error:
                self._on_error(error_msg)
            return error_msg
    
    def execute_file(self, filepath: str) -> str:
        """Execute a script file in Maya."""
        if filepath.endswith(".mel"):
            return self.execute(f'source "{filepath}"', "mel")
        elif filepath.endswith(".py"):
            code = f'exec(open(r"{filepath}").read())'
            return self.execute(code, "python")
        else:
            return f"Error: Unsupported file type: {filepath}"
    
    def get_completions(self, partial: str, language: str = None) -> List[Dict[str, str]]:
        """Get auto-complete suggestions from Maya."""
        completions = []
        
        if not self.is_connected:
            return completions
        
        if language == "mel" or (language is None and not "." in partial):
            # Get MEL command completions
            try:
                result = self._send_command(
                    f'stringArrayToString(`commandHelp -list "{partial}*"`, "\\n")',
                    self._mel_port
                )
                if result:
                    for cmd in result.strip().split("\n"):
                        cmd = cmd.strip()
                        if cmd:
                            completions.append({
                                "label": cmd,
                                "detail": "MEL command",
                                "insert_text": cmd,
                            })
            except Exception:
                pass
        
        if language == "python" or language is None:
            # Get Python completions using dir() or jedi
            try:
                # Split on last dot to get the object
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
    
    def get_scene_info(self) -> Dict[str, Any]:
        """Get Maya scene information for AI context."""
        info = super().get_scene_info()
        
        if not self.is_connected:
            return info
        
        try:
            # Get scene file
            scene_file = self._send_command(
                'import maya.cmds; print(maya.cmds.file(q=True, sceneName=True))',
                self._python_port
            )
            info["scene_file"] = (scene_file or "").strip()
            
            # Get Maya version
            version = self._send_command("about -version", self._mel_port)
            info["maya_version"] = (version or "").strip()
            
            # Get selected objects
            selected = self._send_command(
                'import maya.cmds, json; print(json.dumps(maya.cmds.ls(selection=True) or []))',
                self._python_port
            )
            if selected:
                try:
                    info["selected_objects"] = json.loads(selected.strip())
                except json.JSONDecodeError:
                    info["selected_objects"] = []
        except Exception:
            pass
        
        return info
    
    def get_api_documentation(self, symbol: str) -> Optional[str]:
        """Look up Maya command documentation."""
        if not self.is_connected:
            return None
        
        try:
            result = self._send_command(
                f'import maya.cmds; print(maya.cmds.help("{symbol}"))',
                self._python_port
            )
            return result.strip() if result else None
        except Exception:
            return None
    
    def get_mcp_server_info(self) -> Optional[Dict[str, Any]]:
        """Return info about Maya MCP server availability."""
        return {
            "name": "dcc-mcp-maya",
            "description": "MCP server for Maya scene manipulation",
            "url": "https://github.com/loonghao/dcc-mcp-maya",
            "installed": False,  # TODO: detect if installed
        }
    
    # ---- Internal ----
    
    def _send_command(self, command: str, port: int) -> Optional[str]:
        """Send a command to Maya's command port and return the response."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        
        try:
            sock.connect((self._host, port))
            
            # Maya command port expects null-terminated strings
            sock.sendall((command + "\n").encode("utf-8"))
            
            # Read response
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
