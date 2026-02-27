"""
MCA Core - Internal Maya Adapter.

Direct-execution adapter for when MCA Editor runs INSIDE Maya's process
(as a plugin). Instead of TCP sockets and base64 wrapping, this adapter
calls ``maya.cmds``, ``maya.mel.eval()``, and ``exec()`` directly in
Maya's ``__main__`` namespace.

This adapter is always "connected" — we ARE Maya.

Dependencies:
    - maya.cmds (available only inside Maya's Python interpreter)
    - maya.mel (available only inside Maya's Python interpreter)
"""

import io
import sys
import logging
import traceback

from .base_adapter import DCCAdapter, DCCType, ConnectionState

# Module-level logger for internal Maya operations.
logger = logging.getLogger(__name__)

# Flag to suppress the MCA output hook while echoing to Maya's script editor.
# The internal adapter sets this True before calling MGlobal.displayInfo() and
# clears it after, so _on_maya_output() in maya_window.py can skip the echo
# and avoid duplicate output in MCA Editor's panel.
_suppress_output_hook = False


# --- Internal Maya Adapter --------------------------------------------------

class InternalMayaAdapter(DCCAdapter):
    """
    Maya adapter for embedded (in-process) execution.

    When MCA Editor runs as a Maya plugin, there is no need for TCP
    sockets or base64 encoding. This adapter calls Maya's Python API
    directly, which is faster and more reliable than the socket path.

    Key differences from MayaAdapter (TCP):
        - No sockets, no base64 wrapping, no timeouts
        - Always "connected" (we ARE Maya)
        - Executes in Maya's ``__main__`` namespace via eval/exec
        - Same eval-first-then-exec pattern for expression display
        - Captures stdout/stderr with StringIO
    """

    def __init__(self):
        """Initialize the internal Maya adapter as always-connected."""
        super().__init__()
        # We are already inside Maya — mark as connected immediately.
        self._state = ConnectionState.CONNECTED

        # Workspace paths to add to sys.path for user script imports.
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
        Human-readable name for internal Maya mode.

        :rtype: str
        """
        return "Maya (Internal)"

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
        No port needed — we run inside Maya's process.

        :rtype: int
        """
        return 0

    # --- Workspace Path Injection --------------------------------------------

    def set_workspace_paths(self, scripts_dir, site_packages_dir):
        """
        Set workspace paths and add them to ``sys.path`` for user imports.

        Since the internal adapter runs in Maya's process, we can modify
        ``sys.path`` directly (no wrapper injection needed).

        :param str scripts_dir: Path to the user scripts directory.
        :param str site_packages_dir: Path to the site-packages directory.
        """
        self._scripts_dir = scripts_dir
        self._site_packages_dir = site_packages_dir

        # Add directly to sys.path since we share Maya's process.
        if scripts_dir and scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            logger.info("Added to sys.path (internal): %s", scripts_dir)
        if site_packages_dir and site_packages_dir not in sys.path:
            sys.path.insert(0, site_packages_dir)
            logger.info("Added to sys.path (internal): %s", site_packages_dir)

    # --- Connection (no-ops — we're always inside Maya) ----------------------

    def connect(self, host="localhost", port=None):
        """
        No-op connect — we are already inside Maya.

        :param str host: Ignored.
        :param int port: Ignored.
        :return: Always True.
        :rtype: bool
        """
        self.state = ConnectionState.CONNECTED
        if self._on_output:
            self._on_output("MCA Editor running inside Maya (direct execution)")
        logger.info("InternalMayaAdapter: already connected (running inside Maya)")
        return True

    def disconnect(self):
        """No-op disconnect — cannot disconnect from ourselves."""
        # We intentionally do NOT change state to DISCONNECTED because
        # we are always inside Maya. Just log for debugging.
        logger.info("InternalMayaAdapter: disconnect called (ignored, we ARE Maya)")

    def ping(self):
        """
        Always alive — we are Maya's process.

        :return: Always True.
        :rtype: bool
        """
        return True

    # --- Execution -----------------------------------------------------------

    def execute(self, code, language=None):
        """
        Execute code directly in Maya's interpreter.

        For Python, uses the same eval-first-then-exec pattern as the
        TCP adapter, but without base64 wrapping. Captures stdout/stderr
        via StringIO redirect.

        For MEL, calls ``maya.mel.eval()`` directly.

        :param str code: Source code to execute.
        :param str language: 'python' or 'mel' (defaults to 'python').
        :return: Output from execution.
        :rtype: str
        """
        # Default to Python if no language specified.
        if language is None:
            language = "python"

        if language == "mel":
            return self._execute_mel(code)
        else:
            return self._execute_python(code)

    def _execute_python(self, code):
        """
        Execute Python code directly in Maya's ``__main__`` namespace.

        Uses the same eval-first-then-exec pattern as the TCP adapter:
        1. Try to compile as "eval" — single expressions show their result.
        2. Fall back to "exec" for statements (imports, assignments, etc.).

        Stdout is redirected to a StringIO buffer so print() output is
        captured and returned to the MCA Editor output panel.  After
        execution, the code and output are echoed to Maya's script
        editor via ``sys.__stdout__`` so history is visible there too.

        :param str code: Python source code to execute.
        :return: Captured output.
        :rtype: str
        """
        import __main__

        # Redirect stdout to capture print() output.
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        error = None

        try:
            # Try eval mode first — expressions like variable names show their value.
            try:
                compiled = compile(code, "<mca_editor>", "eval")
                result = eval(compiled, __main__.__dict__)
                if result is not None:
                    print("# Result: {} #".format(repr(result)))
            except SyntaxError:
                # Not a single expression — execute as statements.
                exec(compile(code, "<mca_editor>", "exec"), __main__.__dict__)
        except Exception as exc:
            error = exc
        finally:
            # Always restore stdout, even if code raised.
            sys.stdout = old_stdout

        # Collect captured output.
        output = buf.getvalue()

        # Echo the executed code and output to Maya's script editor.
        # MGlobal.displayInfo() can trigger Maya UI updates that steal
        # keyboard focus from the code editor, so save and restore focus.
        try:
            from mca_qt.qt_compat import QApplication, Qt as _Qt
            _app = QApplication.instance()
            _saved = _app.focusWidget() if _app else None
        except Exception:
            _app, _saved = None, None

        self._echo_to_script_editor(code, output, error)

        # Restore focus if displayInfo() stole it.
        if _saved and _app:
            _current = _app.focusWidget()
            if _current is not _saved:
                _saved.setFocus(_Qt.FocusReason.OtherFocusReason)

        # If there was an error, format the traceback.
        if error:
            tb_text = traceback.format_exception(type(error), error, error.__traceback__)
            error_text = "".join(tb_text)
            if self._on_error:
                self._on_error(error_text.rstrip())
            # Combine any output before the error with the traceback.
            if output:
                return output.rstrip() + "\n" + error_text.rstrip()
            return error_text.rstrip()

        # Report output via callback and return it.
        if output:
            output = output.rstrip()
            if self._on_output:
                self._on_output(output)
            return output

        return ""

    def _echo_to_script_editor(self, code, output, error):
        """
        Echo executed code and results to Maya's script editor.

        Uses ``maya.OpenMaya.MGlobal.displayInfo()`` so the text appears
        in Maya's script editor history (just like Charcoal Editor 2).

        Sets the module-level ``_suppress_output_hook`` flag while
        echoing so MCA Editor's ``_on_maya_output()`` hook skips
        these messages and doesn't create duplicates.

        :param str code: The executed source code.
        :param str output: Captured stdout from execution (may be empty).
        :param Exception error: Exception raised during execution, or None.
        """
        global _suppress_output_hook
        try:
            import maya.OpenMaya as om

            # Suppress our own output hook to prevent duplicates.
            _suppress_output_hook = True

            # Echo the executed code.
            om.MGlobal.displayInfo(code.rstrip())

            # Echo any captured output.
            if output and output.strip():
                for line in output.rstrip().split("\n"):
                    om.MGlobal.displayInfo(line)

            # Echo errors.
            if error:
                tb_text = traceback.format_exception(
                    type(error), error, error.__traceback__
                )
                om.MGlobal.displayError("".join(tb_text).rstrip())

        except Exception:
            # If something goes wrong, silently skip — never break execution.
            pass
        finally:
            _suppress_output_hook = False

    def _execute_mel(self, code):
        """
        Execute MEL code via ``maya.mel.eval()``.

        :param str code: MEL source code to execute.
        :return: Result string from MEL evaluation.
        :rtype: str
        """
        try:
            import maya.mel
            result = maya.mel.eval(code)
            # MEL eval returns the result of the last expression.
            if result is not None:
                result_str = str(result)
                if self._on_output:
                    self._on_output(result_str)
                return result_str
            return ""
        except Exception as exc:
            error_msg = "MEL Error: {}".format(str(exc))
            if self._on_error:
                self._on_error(error_msg)
            logger.error("MEL execution error: %s", exc)
            return error_msg

    def execute_file(self, filepath):
        """
        Execute a script file directly in Maya.

        :param str filepath: Path to the script file.
        :return: Output from Maya.
        :rtype: str
        """
        if filepath.endswith(".mel"):
            return self.execute('source "{}"'.format(filepath), "mel")
        elif filepath.endswith(".py"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                return self.execute(code, "python")
            except Exception as exc:
                error_msg = "Error reading file: {}".format(str(exc))
                if self._on_error:
                    self._on_error(error_msg)
                return error_msg
        else:
            return "Error: Unsupported file type: {}".format(filepath)

    # --- Auto-complete -------------------------------------------------------

    def get_completions(self, partial, language=None):
        """
        Get auto-complete suggestions directly from Maya's interpreter.

        :param str partial: Partial text to complete.
        :param str language: Target language for completions.
        :return: List of completion dicts with 'label', 'detail', 'insert_text'.
        :rtype: list
        """
        completions = []

        # MEL completions via dir(maya.cmds).
        # The MEL-only `commandHelp` procedure doesn't exist in all Maya
        # versions, so we use dir(maya.cmds) which reliably lists every
        # command Maya exposes (MEL and Python share the same command set).
        if language == "mel" or (language is None and "." not in partial):
            try:
                import maya.cmds
                cmds_list = [
                    c for c in sorted(dir(maya.cmds))
                    if c.startswith(partial) and not c.startswith("_")
                ]
                for cmd in cmds_list[:50]:
                    completions.append({
                        "label": cmd,
                        "detail": "MEL command",
                        "insert_text": cmd,
                    })
            except Exception:
                pass

        # Python completions via dir() in __main__ namespace.
        if language == "python" or language is None:
            try:
                import __main__
                if "." in partial:
                    # Completing an attribute on an object.
                    obj_part = partial.rsplit(".", 1)[0]
                    attr_prefix = partial.rsplit(".", 1)[1]
                    obj = eval(obj_part, __main__.__dict__)
                    attrs = [x for x in dir(obj) if x.startswith(attr_prefix) and not x.startswith("__")]
                    for attr in attrs[:30]:
                        completions.append({
                            "label": attr,
                            "detail": "Python",
                            "insert_text": attr,
                        })
                else:
                    # Completing a top-level name.
                    names = [x for x in dir(__main__) if x.startswith(partial)]
                    for name in names[:30]:
                        completions.append({
                            "label": name,
                            "detail": "Python",
                            "insert_text": name,
                        })
            except Exception:
                pass

        return completions

    # --- Scene Context -------------------------------------------------------

    def get_scene_info(self):
        """
        Get Maya scene information directly (no socket needed).

        :return: Dictionary of scene metadata.
        :rtype: dict
        """
        info = super().get_scene_info()

        try:
            import maya.cmds
            info["scene_file"] = maya.cmds.file(q=True, sceneName=True) or ""
            info["maya_version"] = maya.cmds.about(version=True) or ""
            info["selected_objects"] = maya.cmds.ls(selection=True) or []
        except Exception as exc:
            logger.warning("Failed to get Maya scene info: %s", exc)

        return info

    def get_api_documentation(self, symbol):
        """
        Look up Maya command documentation directly.

        :param str symbol: The Maya command or API symbol.
        :return: Help text, or None if unavailable.
        :rtype: str or None
        """
        try:
            import maya.cmds
            return maya.cmds.help(symbol) or None
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
