"""
MCA Editor - Public Editor API.

Provides a pure-Python wrapper around the MCA Editor panel, exposing all
editor functionality through simple method calls with plain Python return
types.  Designed for cross-process consumers (JSON-RPC server, MCP tools,
plugins) that need programmatic control of the editor.

Architecture:
    - Zero Qt imports in this module — all Qt interaction is delegated to the
      registered panel reference.
    - Module-level singleton via ``register_panel()`` / ``get_api()``.
    - A ``@_require_main_thread`` decorator (injected at registration time)
      asserts that API methods run on the Qt main thread in debug builds.
    - Thread safety: callers from non-Qt threads must dispatch through the
      JSON-RPC server's queue mechanism (see ``editor_api_server.py``).

Return Convention:
    - Simple getters return their value directly (or ``None``).
    - Mutating operations return an ``ApiResult`` dict::

          {"success": True, "result": <value>}
          {"success": False, "error": "description"}

Dependencies:
    - None (pure Python stdlib only)
"""

import io
import logging
import os
import sys
import traceback

# Module-level logger for API operations.
logger = logging.getLogger(__name__)


# --- Module-Level Singleton -------------------------------------------------

# The registered panel reference and API instance.  Set by ``register_panel()``.
_panel = None
_api = None

# The main-thread check function, injected by ``register_panel()`` so this
# module never needs to import Qt itself.
_is_main_thread = None


def register_panel(panel):
    """
    Register the editor panel and create the API singleton.

    Called once during ``MCAEditorPanel.__init__`` after all widgets are
    built.  Injects the Qt main-thread check so ``@_require_main_thread``
    works without any Qt imports in this module.

    :param MCAEditorPanel panel: The fully-initialized editor panel.
    """
    global _panel, _api, _is_main_thread

    _panel = panel

    # Build the main-thread checker from the panel's Qt context.
    # This closure captures QThread and QApplication without us importing them.
    try:
        from mca_qt.qt_compat import QThread, QApplication
        def _check_main_thread():
            app = QApplication.instance()
            if app is None:
                return True
            return QThread.currentThread() == app.thread()
        _is_main_thread = _check_main_thread
    except ImportError:
        # Fallback — always passes (for headless testing).
        _is_main_thread = lambda: True

    _api = EditorAPI()
    logger.info("EditorAPI registered with panel: %s", type(panel).__name__)


def get_api():
    """
    Return the EditorAPI singleton.

    :return: The API instance, or None if ``register_panel()`` hasn't been called.
    :rtype: EditorAPI or None
    """
    return _api


# --- Main-Thread Decorator --------------------------------------------------

def _require_main_thread(func):
    """
    Decorator that asserts the wrapped function runs on the Qt main thread.

    Raises ``RuntimeError`` if called from a worker thread.  This is a
    safety net — the JSON-RPC server is responsible for dispatching calls
    onto the main thread before they reach the API.

    :param callable func: The API method to wrap.
    :return: Wrapped function with thread check.
    :rtype: callable
    """
    def wrapper(*args, **kwargs):
        if _is_main_thread is not None and not _is_main_thread():
            raise RuntimeError(
                "EditorAPI.{}() must be called on the Qt main thread. "
                "Use the JSON-RPC server's queue dispatch.".format(func.__name__)
            )
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# --- ApiResult Helpers ------------------------------------------------------

def _ok(result=None):
    """
    Build a success ApiResult dict.

    :param result: The result value (any JSON-serializable type).
    :return: Success dict.
    :rtype: dict
    """
    return {"success": True, "result": result}


def _err(message):
    """
    Build a failure ApiResult dict.

    :param str message: Human-readable error description.
    :return: Failure dict.
    :rtype: dict
    """
    return {"success": False, "error": str(message)}


# --- EditorAPI Class --------------------------------------------------------

class EditorAPI:
    """
    Public API for programmatic control of the MCA Editor.

    All methods return plain Python types (str, dict, list, bool, None).
    Mutating operations return ``ApiResult`` dicts so callers always know
    why something failed.  Simple getters return their value directly.

    Every method None-guards against a missing panel or missing editor
    so callers never see AttributeError from a closed/empty editor state.
    """

    # =========================================================================
    # File Operations
    # =========================================================================

    @_require_main_thread
    def open_file(self, filepath):
        """
        Open a file in the editor (or switch to its tab if already open).

        :param str filepath: Absolute path to the file to open.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        if not filepath:
            return _err("No filepath provided")
        filepath = os.path.normpath(filepath)
        if not os.path.isfile(filepath):
            return _err("File not found: {}".format(filepath))
        try:
            _panel._open_file_path(filepath)
            return _ok()
        except Exception as exc:
            return _err("Failed to open file: {}".format(exc))

    @_require_main_thread
    def save_file(self):
        """
        Save the currently active file.

        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        editor = _panel._current_editor()
        if editor is None:
            return _err("No active editor")
        try:
            _panel._save_file()
            return _ok()
        except Exception as exc:
            return _err("Failed to save file: {}".format(exc))

    @_require_main_thread
    def save_all(self):
        """
        Save all modified file-backed tabs.

        :return: List of dicts with ``path``, ``success``, and ``error`` per file.
        :rtype: list
        """
        if _panel is None:
            return []
        results = []
        for editor, name, path in _panel._group_container.all_editors():
            if path and editor.document().isModified():
                try:
                    _panel._write_file(editor, path)
                    results.append({"path": path, "success": True, "error": None})
                except Exception as exc:
                    results.append({"path": path, "success": False, "error": str(exc)})
        return results

    @_require_main_thread
    def close_tab(self):
        """
        Close the currently active tab.

        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        editor = _panel._current_editor()
        if editor is None:
            return _err("No active editor")
        try:
            _panel._close_current_tab()
            return _ok()
        except Exception as exc:
            return _err("Failed to close tab: {}".format(exc))

    @_require_main_thread
    def list_open_files(self):
        """
        List all open tabs across all editor groups.

        :return: List of dicts with ``name``, ``path``, ``language``, ``modified``.
        :rtype: list
        """
        if _panel is None:
            return []
        result = []
        for editor, name, path in _panel._group_container.all_editors():
            result.append({
                "name": name,
                "path": path,
                "language": getattr(editor, "language", None),
                "modified": editor.document().isModified(),
            })
        return result

    @_require_main_thread
    def get_active_file_path(self):
        """
        Get the file path of the currently active editor tab.

        :return: Absolute file path, or None for temp buffers / no editor.
        :rtype: str or None
        """
        if _panel is None:
            return None
        editor = _panel._current_editor()
        if editor is None:
            return None
        return getattr(editor, "file_path", None)

    def read_disk_file(self, filepath):
        """
        Read a file directly from disk (bypasses editor buffers).

        If the file is open in a tab with unsaved edits, this returns the
        **on-disk** version, not the buffer.  Use ``get_text()`` for the
        active buffer content instead.

        :param str filepath: Absolute path to the file to read.
        :return: ApiResult dict with ``result`` containing file content.
        :rtype: dict
        """
        if not filepath:
            return _err("No filepath provided")
        filepath = os.path.normpath(filepath)
        if not os.path.isfile(filepath):
            return _err("File not found: {}".format(filepath))
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            return _ok(content)
        except Exception as exc:
            return _err("Failed to read file: {}".format(exc))

    def write_disk_file(self, filepath, content):
        """
        Write content directly to disk (bypasses editor buffers).

        :param str filepath: Absolute path to the file to write.
        :param str content: The content to write.
        :return: ApiResult dict.
        :rtype: dict
        """
        if not filepath:
            return _err("No filepath provided")
        filepath = os.path.normpath(filepath)
        try:
            # Ensure parent directory exists.
            parent_dir = os.path.dirname(filepath)
            if parent_dir and not os.path.isdir(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return _ok()
        except Exception as exc:
            return _err("Failed to write file: {}".format(exc))

    # =========================================================================
    # Editor Content
    # =========================================================================

    @_require_main_thread
    def get_text(self):
        """
        Get the full text content of the active editor.

        :return: Editor content, or None if no editor is open.
        :rtype: str or None
        """
        if _panel is None:
            return None
        editor = _panel._current_editor()
        if editor is None:
            return None
        return editor.get_all_text()

    @_require_main_thread
    def set_text(self, text):
        """
        Replace the entire content of the active editor.

        :param str text: The new content.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        editor = _panel._current_editor()
        if editor is None:
            return _err("No active editor")
        try:
            editor.setPlainText(text)
            return _ok()
        except Exception as exc:
            return _err("Failed to set text: {}".format(exc))

    @_require_main_thread
    def get_selected_text(self):
        """
        Get the currently selected text in the active editor.

        :return: Selected text, or None if nothing is selected / no editor.
        :rtype: str or None
        """
        if _panel is None:
            return None
        editor = _panel._current_editor()
        if editor is None:
            return None
        cursor = editor.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace("\u2029", "\n")
        return None

    @_require_main_thread
    def insert_text(self, text, line=None, col=None):
        """
        Insert text at a specific position or at the current cursor.

        If ``line`` and ``col`` are None, inserts at the current cursor
        position.  Otherwise moves the cursor to ``(line, col)`` first.

        :param str text: The text to insert.
        :param int line: 1-based line number (optional).
        :param int col: 1-based column number (optional).
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        editor = _panel._current_editor()
        if editor is None:
            return _err("No active editor")
        try:
            cursor = editor.textCursor()
            # Move to the specified position if provided.
            if line is not None:
                block = editor.document().findBlockByNumber(line - 1)
                if not block.isValid():
                    return _err("Line {} is out of range".format(line))
                pos = block.position() + min(col - 1 if col else 0, block.length() - 1)
                cursor.setPosition(pos)
            cursor.insertText(text)
            editor.setTextCursor(cursor)
            return _ok()
        except Exception as exc:
            return _err("Failed to insert text: {}".format(exc))

    @_require_main_thread
    def replace_range(self, start_line, start_col, end_line, end_col, text):
        """
        Replace a range of text in the active editor.

        Selects from ``(start_line, start_col)`` to ``(end_line, end_col)``
        and replaces with ``text``.  All positions are 1-based.  Pass
        ``text=""`` to delete a range.

        :param int start_line: 1-based start line.
        :param int start_col: 1-based start column.
        :param int end_line: 1-based end line.
        :param int end_col: 1-based end column.
        :param str text: Replacement text (empty string to delete).
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        editor = _panel._current_editor()
        if editor is None:
            return _err("No active editor")
        try:
            doc = editor.document()
            # Calculate start position.
            start_block = doc.findBlockByNumber(start_line - 1)
            if not start_block.isValid():
                return _err("Start line {} is out of range".format(start_line))
            start_pos = start_block.position() + min(start_col - 1, start_block.length() - 1)

            # Calculate end position.
            end_block = doc.findBlockByNumber(end_line - 1)
            if not end_block.isValid():
                return _err("End line {} is out of range".format(end_line))
            end_pos = end_block.position() + min(end_col - 1, end_block.length() - 1)

            # Select the range and replace.
            cursor = editor.textCursor()
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, cursor.MoveMode.KeepAnchor)
            cursor.insertText(text)
            editor.setTextCursor(cursor)
            return _ok()
        except Exception as exc:
            return _err("Failed to replace range: {}".format(exc))

    @_require_main_thread
    def get_cursor_position(self):
        """
        Get the current cursor position in the active editor.

        :return: Dict with ``line`` and ``col`` (1-based), or None.
        :rtype: dict or None
        """
        if _panel is None:
            return None
        editor = _panel._current_editor()
        if editor is None:
            return None
        cursor = editor.textCursor()
        block = cursor.block()
        line = block.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        return {"line": line, "col": col}

    @_require_main_thread
    def get_language(self):
        """
        Get the language of the active editor.

        :return: Language string ('python', 'mel', 'text', etc.), or None.
        :rtype: str or None
        """
        if _panel is None:
            return None
        editor = _panel._current_editor()
        if editor is None:
            return None
        return getattr(editor, "language", None)

    # =========================================================================
    # Navigation
    # =========================================================================

    @_require_main_thread
    def navigate_to(self, filepath, line=1):
        """
        Open a file and jump to a specific line.

        :param str filepath: Absolute path to the file.
        :param int line: 1-based line number to navigate to.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        if not filepath:
            return _err("No filepath provided")
        filepath = os.path.normpath(filepath)
        if not os.path.isfile(filepath):
            return _err("File not found: {}".format(filepath))
        try:
            _panel._navigate_to_file_line(filepath, line)
            return _ok()
        except Exception as exc:
            return _err("Failed to navigate: {}".format(exc))

    @_require_main_thread
    def go_to_line(self, line):
        """
        Jump to a line in the currently active editor.

        :param int line: 1-based line number.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        editor = _panel._current_editor()
        if editor is None:
            return _err("No active editor")
        try:
            editor.go_to_line(line)
            return _ok()
        except Exception as exc:
            return _err("Failed to go to line: {}".format(exc))

    # =========================================================================
    # Output Panel
    # =========================================================================

    @_require_main_thread
    def write_output(self, text, level="info"):
        """
        Write a message to the output panel.

        :param str text: The message text.
        :param str level: One of 'output', 'info', 'warning', 'error', 'success'.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")

        # Map level names to output methods.
        level_map = {
            "output": _panel._output.write_output,
            "info": _panel._output.write_info,
            "warning": _panel._output.write_warning,
            "error": _panel._output.write_error,
            "success": _panel._output.write_success,
        }
        writer = level_map.get(level, _panel._output.write_info)
        try:
            writer(text)
            return _ok()
        except Exception as exc:
            return _err("Failed to write output: {}".format(exc))

    @_require_main_thread
    def get_output_text(self, max_lines=100):
        """
        Get recent output panel text.

        :param int max_lines: Maximum number of lines to return.
        :return: Output text (last ``max_lines`` lines).
        :rtype: str
        """
        if _panel is None:
            return ""
        try:
            return _panel._output.get_recent_text(max_lines)
        except Exception:
            return ""

    @_require_main_thread
    def clear_output(self):
        """
        Clear the output panel.

        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        try:
            _panel._output.clear()
            return _ok()
        except Exception as exc:
            return _err("Failed to clear output: {}".format(exc))

    # =========================================================================
    # Project
    # =========================================================================

    @_require_main_thread
    def open_project(self, path):
        """
        Open a folder as a project.

        :param str path: Absolute path to the project root.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        if not path:
            return _err("No project path provided")
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            return _err("Directory not found: {}".format(path))
        try:
            _panel._open_project(path)
            return _ok()
        except Exception as exc:
            return _err("Failed to open project: {}".format(exc))

    @_require_main_thread
    def close_project(self):
        """
        Close the active project.

        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        if _panel._active_project is None:
            return _err("No project is open")
        try:
            _panel._close_project()
            return _ok()
        except Exception as exc:
            return _err("Failed to close project: {}".format(exc))

    @_require_main_thread
    def get_project(self):
        """
        Get information about the active project.

        :return: Project info dict, or None if no project is open.
        :rtype: dict or None
        """
        if _panel is None:
            return None
        project = _panel._active_project
        if project is None:
            return None
        return {
            "name": getattr(project, "name", ""),
            "root": getattr(project, "project_root", ""),
            "python_paths": list(getattr(project, "python_paths", [])),
            "excluded_folders": list(getattr(project, "excluded_folders", [])),
        }

    # =========================================================================
    # Execution
    # =========================================================================

    @_require_main_thread
    def execute_in_dcc(self, code, language="python"):
        """
        Execute code in the connected DCC (e.g. Maya).

        The adapter's ``execute()`` returns the socket response (stdout
        captured by the base64 wrapper).  The ``success`` field is True
        if the socket call succeeded — it does not guarantee the Maya
        code ran without errors.  Inspect ``output`` for error patterns.

        :param str code: Source code to execute.
        :param str language: 'python' or 'mel' (default 'python').
        :return: Dict with ``success``, ``output``, ``error``.
        :rtype: dict
        """
        if _panel is None:
            return {"success": False, "output": "", "error": "Editor panel not registered"}
        try:
            return _panel._api_execute_code(code, language)
        except Exception as exc:
            return {"success": False, "output": "", "error": str(exc)}

    @_require_main_thread
    def execute_locally(self, code):
        """
        Execute Python code locally with stdout/stderr capture.

        Uses a persistent namespace so variables survive across calls
        (same as the editor's local execution mode).

        :param str code: Python source code to execute.
        :return: Dict with ``success``, ``output``, ``error``.
        :rtype: dict
        """
        if _panel is None:
            return {"success": False, "output": "", "error": "Editor panel not registered"}

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exec(code, _panel._local_namespace)
            output = sys.stdout.getvalue()
            errors = sys.stderr.getvalue()
            return {
                "success": True,
                "output": output.rstrip() if output else "",
                "error": errors.rstrip() if errors else None,
            }
        except Exception:
            tb = traceback.format_exc()
            return {"success": False, "output": "", "error": tb.rstrip()}
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    # =========================================================================
    # Settings
    # =========================================================================

    @_require_main_thread
    def get_setting(self, key, default=None):
        """
        Get a setting value.

        :param str key: The setting key.
        :param default: Default value if key is not set.
        :return: The setting value.
        """
        if _panel is None:
            return default
        return _panel._settings.get(key, default)

    @_require_main_thread
    def set_setting(self, key, value):
        """
        Set a setting value.

        :param str key: The setting key.
        :param value: The value to set.
        :return: ApiResult dict.
        :rtype: dict
        """
        if _panel is None:
            return _err("Editor panel not registered")
        try:
            _panel._settings.set(key, value)
            return _ok()
        except Exception as exc:
            return _err("Failed to set setting: {}".format(exc))

    # =========================================================================
    # Status / State
    # =========================================================================

    @_require_main_thread
    def get_state(self):
        """
        Get a comprehensive snapshot of the editor's current state.

        :return: State dict with ``editor``, ``open_files``, ``project``,
            ``dcc``, and ``server`` sections.
        :rtype: dict
        """
        if _panel is None:
            return {
                "editor": None,
                "open_files": [],
                "project": None,
                "dcc": {"connected": False, "name": None, "type": None},
                "server": {"api_port": None, "version": None},
            }

        # --- Active editor info ---
        editor = _panel._current_editor()
        editor_info = None
        if editor is not None:
            cursor = editor.textCursor()
            block = cursor.block()
            # Get selected text (None if nothing selected).
            selection = None
            if cursor.hasSelection():
                selection = cursor.selectedText().replace("\u2029", "\n")
            editor_info = {
                "file_path": getattr(editor, "file_path", None),
                "file_name": os.path.basename(editor.file_path) if editor.file_path else None,
                "language": getattr(editor, "language", None),
                "modified": editor.document().isModified(),
                "cursor": {
                    "line": block.blockNumber() + 1,
                    "col": cursor.positionInBlock() + 1,
                },
                "selection": selection,
            }

        # --- Open files ---
        open_files = []
        for ed, name, path in _panel._group_container.all_editors():
            open_files.append({
                "name": name,
                "path": path,
                "language": getattr(ed, "language", None),
                "modified": ed.document().isModified(),
            })

        # --- Project ---
        project_info = None
        project = _panel._active_project
        if project is not None:
            project_info = {
                "name": getattr(project, "name", ""),
                "root": getattr(project, "project_root", ""),
                "python_paths": list(getattr(project, "python_paths", [])),
                "excluded_folders": list(getattr(project, "excluded_folders", [])),
            }

        # --- DCC connection ---
        adapter = _panel._adapter_manager.get_active_adapter()
        dcc_info = {
            "connected": False,
            "name": None,
            "type": None,
        }
        if adapter is not None and adapter.is_connected:
            dcc_info = {
                "connected": True,
                "name": getattr(adapter, "display_name", None),
                "type": getattr(adapter, "dcc_type", None),
            }
            # Convert enum to string if needed.
            if dcc_info["type"] is not None:
                dcc_info["type"] = str(dcc_info["type"].value) if hasattr(dcc_info["type"], "value") else str(dcc_info["type"])

        # --- Server info ---
        # Import lazily to avoid circular import at module load time.
        server_port = None
        try:
            from mca_core.editor_api_server import get_port
            server_port = get_port()
        except ImportError:
            pass

        from mca_core import __version__ as version

        server_info = {
            "api_port": server_port,
            "version": version,
        }

        return {
            "editor": editor_info,
            "open_files": open_files,
            "project": project_info,
            "dcc": dcc_info,
            "server": server_info,
        }
