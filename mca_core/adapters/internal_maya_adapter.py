"""
MCA Core - Internal Maya Adapter.

Direct-execution adapter for when MCA Editor runs INSIDE Maya's process
(as a plugin). Instead of TCP sockets and base64 wrapping, this adapter
calls ``maya.cmds``, ``maya.mel.eval()``, and ``exec()`` directly in
Maya's ``__main__`` namespace.

Output from executed code (``print()``, results, errors) flows through
Maya's native output system — the same pipeline that feeds the Script
Editor and Charcoal Editor. The ``MCommandMessage`` callback installed
in ``maya_window.py`` is the sole route into MCA Editor's output panel.

This adapter is always "connected" — we ARE Maya.

Dependencies:
    - maya.cmds (available only inside Maya's Python interpreter)
    - maya.mel (available only inside Maya's Python interpreter)
"""

import sys
import logging
import traceback

from .base_adapter import DCCAdapter, DCCType, ConnectionState

# Module-level logger for internal Maya operations.
logger = logging.getLogger(__name__)


# --- Stdout Tee Writer (exec-time capture) ----------------------------------

class _TeeWriter:
    """
    Temporary tee writer used ONLY during ``_execute_python()`` to capture
    ``print()`` output from exec'd code.

    Writes pass through to Maya's original stdout (so the Script Editor
    still shows them) and simultaneously buffer to a StringIO for the
    output panel.  This is installed for the duration of a single exec()
    call, then removed.

    The permanent ``_StdoutTee`` in ``maya_window.py`` handles output
    that occurs OUTSIDE of exec (deferred callbacks, framework startup).
    During exec, the permanent tee is temporarily bypassed so output
    doesn't appear twice in the panel.

    :param object original: Maya's original stdout (NOT the permanent tee).
    :param io.StringIO capture: Buffer to capture a copy of all writes.
    """

    def __init__(self, original, capture):
        """
        Initialize the tee with both output targets.

        :param object original: The original stdout to pass through to.
        :param io.StringIO capture: StringIO buffer for our output panel.
        """
        self._original = original
        self._capture = capture

    def write(self, text):
        """
        Write to both the original stdout and the capture buffer.

        :param str text: Text to write.
        """
        self._original.write(text)
        self._capture.write(text)

    def flush(self):
        """Flush the original stdout."""
        self._original.flush()

    def __getattr__(self, name):
        """
        Forward unknown attributes to the original stdout.

        Preserves compatibility with Maya's OutputRedirector attributes.

        :param str name: Attribute name.
        :return: The attribute from the original stdout.
        """
        return getattr(self._original, name)


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
        - Output flows through Maya's native output system (no stdout capture)
    """

    def __init__(self):
        """Initialize the internal Maya adapter as always-connected."""
        super().__init__()
        # We are already inside Maya — mark as connected immediately.
        self._state = ConnectionState.CONNECTED

        # Workspace paths to add to sys.path for user script imports.
        self._scripts_dir = ""
        self._site_packages_dir = ""
        # Project paths (higher priority than workspace paths).
        self._project_paths = []

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

    def set_project_paths(self, paths):
        """
        Set project-specific paths and add them directly to ``sys.path``.

        Clears any previously set project paths first, then inserts
        the new paths at position 0 in reverse order so the first path
        has the highest priority.

        :param list paths: List of absolute directory path strings.
        """
        # Remove old project paths before adding new ones.
        self.clear_project_paths()
        self._project_paths = list(paths)

        # Insert in reverse so the first path ends up at index 0.
        for p in reversed(self._project_paths):
            if p and p not in sys.path:
                sys.path.insert(0, p)
                logger.info("Added project path to sys.path (internal): %s", p)

    def clear_project_paths(self):
        """
        Remove all project-specific paths from ``sys.path``.
        """
        for p in self._project_paths:
            while p in sys.path:
                sys.path.remove(p)
                logger.info("Removed project path from sys.path (internal): %s", p)
        self._project_paths = []

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

        For Python, uses the eval-first-then-exec pattern.  Stdout is
        NOT redirected — all ``print()`` output flows through Maya's
        native ``sys.stdout`` (OutputRedirector), which fires
        ``MCommandMessage`` with kDisplay type.  The ``_on_maya_output``
        callback in ``maya_window.py`` picks it up and writes it to the
        output panel.  This is the same pipeline Maya's Script Editor
        uses, ensuring complete content parity.

        For MEL, calls ``maya.mel.eval()`` directly.

        :param str code: Source code to execute.
        :param str language: 'python' or 'mel' (defaults to 'python').
        :return: Empty string (output arrives via MCommandMessage).
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

        Uses the eval-first-then-exec pattern:
        1. Try to compile as "eval" — single expressions show their result
           via a formatted ``print("# Result: <value> #")`` call.
        2. Fall back to "exec" for statements (imports, assignments, etc.).

        During execution, a temporary ``_TeeWriter`` captures stdout
        to a StringIO buffer while passing through to Maya's original
        stdout (Script Editor).  The temporary tee bypasses the permanent
        ``_StdoutTee`` installed by ``maya_window.py`` to avoid double
        writes.  After execution, the permanent tee is restored so it
        can capture deferred callback output.

        :param str code: Python source code to execute.
        :return: Captured stdout text from execution.
        :rtype: str
        """
        import __main__
        import io
        import maya.api.OpenMaya as om2

        # Save current stdout — this is typically the permanent _StdoutTee
        # from maya_window.py (or Maya's raw stdout if no tee installed).
        saved_stdout = sys.stdout

        # Get Maya's ORIGINAL stdout, bypassing any tee wrappers.
        # The permanent _StdoutTee stores the original as _original.
        # We bypass it during exec so output doesn't appear twice in
        # the panel (once from the temporary tee's return value, once
        # from the permanent tee's live write).
        maya_stdout = saved_stdout
        while hasattr(maya_stdout, '_original'):
            maya_stdout = maya_stdout._original

        # Install temporary tee: captures to StringIO while passing
        # through to Maya's original stdout (Script Editor still works).
        captured = io.StringIO()
        sys.stdout = _TeeWriter(maya_stdout, captured)

        try:
            # Try eval mode first — expressions like variable names,
            # function calls, etc. show their return value.
            try:
                compiled = compile(code, "<mca_editor>", "eval")
                result = eval(compiled, __main__.__dict__)

                # Display the result in Maya's exact format:
                #   # Result: <value> #
                # Goes through the temp tee → Maya stdout + captured.
                if result is not None:
                    print("# Result: {} #".format(repr(result)))

            except SyntaxError:
                # Not a single expression — execute as statements.
                # print() calls flow through the temporary tee.
                exec(compile(code, "<mca_editor>", "exec"), __main__.__dict__)

        except Exception as exc:
            # Determine if this error was already displayed by Maya's
            # own output system.  Maya commands like cmds.error(),
            # cmds.warning(), cmds.polySphere(invalidFlag=True), etc.
            # fire MCommandMessage BEFORE the exception reaches us.
            # Re-displaying those would create duplicates.
            #
            # Heuristic: RuntimeError from Maya C++ commands has already
            # been displayed.  Pure Python errors (NameError, TypeError,
            # SyntaxError, etc.) have NOT been displayed and need routing
            # through displayError().
            if isinstance(exc, RuntimeError):
                # Maya already displayed this — log but don't re-display.
                logger.debug("Maya RuntimeError (already displayed): %s", exc)
            else:
                # Pure Python error — route through Maya's output system
                # so it appears in BOTH the Script Editor and our panel.
                # Format in Maya's style: "file <source> line N: Error"
                error_display = self._format_error_for_maya(exc)
                om2.MGlobal.displayError(error_display)

        finally:
            # Restore the saved stdout (permanent tee or original).
            # This re-enables the permanent tee for deferred callback
            # output that fires after exec() returns.
            sys.stdout = saved_stdout

        # Return captured output so the caller can write it to the panel.
        return captured.getvalue()

    def _format_error_for_maya(self, exc):
        """
        Format an exception in Maya's Script Editor style.

        Maya's Script Editor shows Python errors as:
            ``file <source> line N: ErrorType: message``

        Extracts the source file and line number from the innermost
        traceback frame that originated in user code (``<mca_editor>``).

        :param Exception exc: The caught exception with traceback.
        :return: Formatted error string for ``MGlobal.displayError()``.
        :rtype: str
        """
        # The error type and message (e.g. "NameError: name 'x' is not defined").
        error_line = "{}: {}".format(type(exc).__name__, exc)

        # Walk the traceback chain to find the innermost user code frame.
        tb = exc.__traceback__
        source = "<mca_editor>"
        line_num = 1

        while tb is not None:
            frame = tb.tb_frame
            filename = frame.f_code.co_filename
            # Prefer the user's code frame over internal frames.
            if filename == "<mca_editor>" or not filename.startswith("<"):
                source = filename
                line_num = tb.tb_lineno
            tb = tb.tb_next

        return "file {} line {}: {}".format(source, line_num, error_line)

    def _execute_mel(self, code):
        """
        Execute MEL code via ``maya.mel.eval()``.

        Output, results, and errors all flow through Maya's normal
        output system, which fires the ``MCommandMessage`` callback.
        MEL command return values do NOT fire ``kResult`` when called
        via ``maya.mel.eval()``, so we print them in the ``# Result:``
        format.  The ``_on_maya_output`` callback detects this prefix
        and routes to ``write_result()`` for proper coloring.

        :param str code: MEL source code to execute.
        :return: Empty string (output arrives via MCommandMessage callback).
        :rtype: str
        """
        try:
            import maya.mel
            result = maya.mel.eval(code)

            # Display the return value — mel.eval() returns the result
            # as a Python value but does NOT fire kResult via
            # MCommandMessage.  print() goes through Maya's stdout →
            # MCommandMessage kDisplay → _on_maya_output.
            if result is not None and result != "" and result != 0:
                print("# Result: {} #".format(result))

        except Exception as exc:
            # Maya already displayed the error through its output system
            # (MCommandMessage kError fired before the exception reached
            # us).  Just log for internal debugging — no _on_error call
            # to avoid duplicate display.
            logger.error("MEL execution error: %s", exc)

        # All output arrives through MCommandMessage — return empty.
        return ""

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
