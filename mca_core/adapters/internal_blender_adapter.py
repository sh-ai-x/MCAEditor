"""
MCA Core - Internal Blender Adapter.

Direct-execution adapter for when MCA Editor runs INSIDE Blender's process
(as an addon). Instead of TCP sockets and JSON wrapping, this adapter
calls ``exec()`` and ``eval()`` directly in Blender's ``__main__`` namespace,
with full access to ``bpy``.

Output from executed code (``print()``, results, errors) is captured via
stdout/stderr tee writers installed by ``blender_window.py``. There is no
Blender equivalent of Maya's ``MCommandMessage`` callback — stdout tees
are the sole route into MCA Editor's output panel.

This adapter is always "connected" — we ARE Blender.

Dependencies:
    - bpy (available only inside Blender's Python interpreter)
"""

import sys
import logging
import traceback

from .base_adapter import DCCAdapter, DCCType, ConnectionState

# Module-level logger for internal Blender operations.
logger = logging.getLogger(__name__)


# --- Internal Blender Adapter ------------------------------------------------

class InternalBlenderAdapter(DCCAdapter):
    """
    Blender adapter for embedded (in-process) execution.

    When MCA Editor runs as a Blender addon, there is no need for TCP
    sockets or JSON encoding. This adapter calls Blender's Python API
    directly, which is faster and more reliable than the socket path.

    Key differences from BlenderAdapter (TCP):
        - No sockets, no JSON wrapping, no timeouts
        - Always "connected" (we ARE Blender)
        - Executes in Blender's ``__main__`` namespace via eval/exec
        - Same eval-first-then-exec pattern for expression display
        - Output flows through stdout/stderr tees (no MCommandMessage)
    """

    def __init__(self):
        """Initialize the internal Blender adapter as always-connected."""
        super().__init__()
        # We are already inside Blender — mark as connected immediately.
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
        Return the DCC type for Blender.

        :rtype: DCCType
        """
        return DCCType.BLENDER

    @property
    def display_name(self):
        """
        Human-readable name for internal Blender mode.

        :rtype: str
        """
        return "Blender (Internal)"

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
        No port needed — we run inside Blender's process.

        :rtype: int
        """
        return 0

    # --- Workspace Path Injection --------------------------------------------

    def set_workspace_paths(self, scripts_dir, site_packages_dir):
        """
        Set workspace paths and add them to ``sys.path`` for user imports.

        Since the internal adapter runs in Blender's process, we can modify
        ``sys.path`` directly (no wrapper injection needed).

        :param str scripts_dir: Path to the user scripts directory.
        :param str site_packages_dir: Path to the site-packages directory.
        """
        self._scripts_dir = scripts_dir
        self._site_packages_dir = site_packages_dir

        # Add directly to sys.path since we share Blender's process.
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

    # --- Connection (no-ops — we're always inside Blender) -------------------

    def connect(self, host="localhost", port=None):
        """
        No-op connect — we are already inside Blender.

        :param str host: Ignored.
        :param int port: Ignored.
        :return: Always True.
        :rtype: bool
        """
        self.state = ConnectionState.CONNECTED
        if self._on_output:
            self._on_output("MCA Editor running inside Blender (direct execution)")
        logger.info("InternalBlenderAdapter: already connected (running inside Blender)")
        return True

    def disconnect(self):
        """No-op disconnect — cannot disconnect from ourselves."""
        # We intentionally do NOT change state to DISCONNECTED because
        # we are always inside Blender. Just log for debugging.
        logger.info("InternalBlenderAdapter: disconnect called (ignored, we ARE Blender)")

    def ping(self):
        """
        Always alive — we are Blender's process.

        :return: Always True.
        :rtype: bool
        """
        return True

    # --- Execution -----------------------------------------------------------

    def execute(self, code, language=None):
        """
        Execute code directly in Blender's interpreter.

        Uses the eval-first-then-exec pattern. All ``print()`` output
        flows through the stdout/stderr tee writers installed by
        ``blender_window.py``, which route it to the MCA Editor output
        panel. No MCommandMessage equivalent exists in Blender — stdout
        tees are the sole capture mechanism.

        :param str code: Source code to execute.
        :param str language: Only 'python' is supported (defaults to 'python').
        :return: Empty string (output arrives via stdout tee).
        :rtype: str
        """
        # Blender only supports Python — ignore language parameter.
        return self._execute_python(code)

    def _execute_python(self, code):
        """
        Execute Python code directly in Blender's ``__main__`` namespace.

        Uses the eval-first-then-exec pattern:
        1. Try to compile as "eval" — single expressions show their result
           via a formatted ``# Result: <value> #`` message.
        2. Fall back to "exec" for statements (imports, assignments, etc.).

        Stdout is temporarily redirected to a StringIO buffer so that
        ``print()`` output from the user's code is captured and routed
        through the adapter's ``_on_output`` callback (wired to the
        output panel by ``editor_panel.py``).

        :param str code: Python source code to execute.
        :return: Empty string (output arrives via callbacks).
        :rtype: str
        """
        import __main__
        import io

        # Redirect stdout to capture print() output from user code.
        # Blender has no MCommandMessage equivalent — we must capture
        # stdout ourselves and route it through _on_output.
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        capture_buf = io.StringIO()
        error_buf = io.StringIO()
        sys.stdout = capture_buf
        sys.stderr = error_buf

        try:
            # Try eval mode first — expressions like variable names,
            # function calls, etc. show their return value.
            try:
                compiled = compile(code, "<mca_editor>", "eval")
                result = eval(compiled, __main__.__dict__)

                # Display the result in the standard format.
                if result is not None:
                    print("# Result: {} #".format(repr(result)))

            except SyntaxError:
                # Not a single expression — execute as statements.
                exec(compile(code, "<mca_editor>", "exec"), __main__.__dict__)

        except Exception as exc:
            # Capture the full traceback NOW while sys.exc_info() is alive.
            exc.__traceback__ = sys.exc_info()[2]

            # Suppress implicit exception chaining from the eval→exec
            # fallback. The user only cares about the final error.
            exc.__context__ = None

            # Format and route the error through _on_error callback.
            error_display = self._format_error(exc)
            if self._on_error:
                self._on_error(error_display)

        finally:
            # Always restore stdout/stderr, even if the code raised.
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        # Route captured stdout to BOTH Blender's console AND MCA Editor panel.
        captured = capture_buf.getvalue()
        if captured:
            # Echo to Blender's console. If stdout is wrapped by our tee,
            # write to the underlying stream to avoid double output in the
            # MCA Editor panel (the tee also writes to the panel).
            echo_out = getattr(old_stdout, '_original', old_stdout)
            echo_out.write(captured)
            echo_out.flush()
            # Route to MCA Editor output panel via adapter callback.
            if self._on_output:
                self._on_output(captured.rstrip())

        # Route captured stderr to BOTH Blender's console AND MCA Editor panel.
        captured_err = error_buf.getvalue()
        if captured_err:
            # Echo to Blender's console (bypass tee to avoid double output).
            echo_err = getattr(old_stderr, '_original', old_stderr)
            echo_err.write(captured_err)
            echo_err.flush()
            # Route to MCA Editor output panel via adapter callback.
            if self._on_error:
                self._on_error(captured_err.rstrip())

        return ""

    def _format_error(self, exc):
        """
        Format an exception as a full Python traceback.

        Uses ``traceback.format_exception()`` to produce the standard
        Python traceback output including all stack frames. Internal
        wrapper frames (``<mca_editor_wrapper>``) are filtered out so
        only user-relevant frames remain.

        :param Exception exc: The caught exception with traceback.
        :return: Formatted traceback string.
        :rtype: str
        """
        # Use Python's traceback module for full, standard formatting.
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)

        # Filter out internal wrapper frames that aren't useful to the user.
        filtered = []
        skip_next = False
        for line in tb_lines:
            # Skip frames from our internal wrapper.
            if "<mca_editor_wrapper>" in line:
                skip_next = True
                continue
            if skip_next and not line.startswith(" "):
                skip_next = False
            elif skip_next:
                continue
            filtered.append(line)

        result = "".join(filtered).rstrip()
        return result if result else "{}: {}".format(type(exc).__name__, exc)

    def execute_file(self, filepath):
        """
        Execute a script file directly in Blender.

        :param str filepath: Path to the script file.
        :return: Output from execution.
        :rtype: str
        """
        if filepath.endswith(".py"):
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
            return "Error: Unsupported file type: {} (Blender only supports Python)".format(filepath)

    # --- Auto-complete -------------------------------------------------------

    def get_completions(self, partial, language=None):
        """
        Get auto-complete suggestions directly from Blender's interpreter.

        Provides completions from bpy, bpy.context, bpy.data, and the
        ``__main__`` namespace.

        :param str partial: Partial text to complete.
        :param str language: Ignored (only Python supported).
        :return: List of completion dicts with 'label', 'detail', 'insert_text'.
        :rtype: list
        """
        completions = []

        try:
            import __main__

            if "." in partial:
                # Completing an attribute on an object (e.g. "bpy.context.").
                obj_part = partial.rsplit(".", 1)[0]
                attr_prefix = partial.rsplit(".", 1)[1]
                obj = eval(obj_part, __main__.__dict__)
                attrs = [
                    x for x in dir(obj)
                    if x.startswith(attr_prefix) and not x.startswith("__")
                ]
                for attr in attrs[:30]:
                    completions.append({
                        "label": attr,
                        "detail": "Python",
                        "insert_text": attr,
                    })
            else:
                # Completing a top-level name from __main__ namespace.
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
        Get Blender scene information directly (no socket needed).

        Queries the current blend file path, Blender version, selected
        objects, and total object count for AI context injection.

        :return: Dictionary of scene metadata.
        :rtype: dict
        """
        info = super().get_scene_info()

        try:
            import bpy
            info["scene_file"] = bpy.data.filepath or ""
            info["blender_version"] = ".".join(str(v) for v in bpy.app.version)
            info["selected_objects"] = [obj.name for obj in bpy.context.selected_objects]
            info["total_objects"] = len(bpy.data.objects)
            info["active_object"] = (
                bpy.context.active_object.name
                if bpy.context.active_object else ""
            )
        except Exception as exc:
            logger.warning("Failed to get Blender scene info: %s", exc)

        return info

    def get_api_documentation(self, symbol):
        """
        Look up Blender Python API documentation for a symbol.

        Uses Python's built-in ``help()`` on the bpy attribute.

        :param str symbol: The API symbol to look up (e.g. "bpy.ops.mesh").
        :return: Help text, or None if unavailable.
        :rtype: str or None
        """
        try:
            import __main__
            import io

            # Capture help() output to a string buffer.
            buf = io.StringIO()
            obj = eval(symbol, __main__.__dict__)
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                help(obj)
            finally:
                sys.stdout = old_stdout
            text = buf.getvalue()
            return text if text else None
        except Exception:
            return None

    def get_mcp_server_info(self):
        """
        Return info about Blender MCP server availability.

        Delegates to ``mcp_setup.get_mcp_server_status()`` for real-time
        status. Falls back to a stub if mcp_setup is unavailable.

        :return: MCP server metadata dictionary.
        :rtype: dict
        """
        try:
            from mca_core.mcp_setup import get_mcp_server_status
            return get_mcp_server_status()
        except Exception:
            # Fallback if mcp_setup is unavailable.
            return {
                "name": "MCABlenderMCP",
                "description": "MCP server for Blender scene manipulation",
                "installed": False,
            }
