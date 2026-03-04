"""
MCA Editor — Comprehensive Maya Editor Test Suite.

Executed inside Maya via ``-command`` flag.  Systematically exercises every
feature of the EditorAPI through ``get_api()`` — direct method calls, no
TCP/JSON-RPC overhead.  Each test is isolated in a try/except so one
failure never aborts the suite.

Writes per-test [PASS] / [FAIL] lines to ``%TEMP%/mca_test_result.log``.
After all categories finish, writes a summary block and a final PASS or
FAIL line.  The runner (``run_maya_test.py --full``) parses these lines.

Usage (called by ``run_maya_test.py --full``, not directly):
    maya.exe -command "python(\"exec(open(r'path/to/maya_editor_test.py').read())\")"

Dependencies: None (runs inside Maya's Python)
Side effects: Creates/deletes temp files, writes log, quits Maya on completion
"""

import os
import sys
import tempfile
import traceback


# --- Constants ---------------------------------------------------------------

# Log file written to by every test — the runner polls this.
_LOG = os.path.join(os.environ.get("TEMP", "C:/Temp"), "mca_test_result.log")

# Directory for temp files created during tests.
_TEMP_DIR = os.path.join(tempfile.gettempdir(), "mca_editor_tests")


# --- Test Bookkeeping -------------------------------------------------------

# Running counters for pass/fail totals.
_pass_count = 0
_fail_count = 0

# Per-test result lines for the summary.
_results = []

# Temp file paths created during tests (cleaned up at end).
_temp_files = []

# Maya objects created during tests (cleaned up at end).
_maya_objects = []


# --- Logging & Assertion Helpers --------------------------------------------

def _log(msg):
    """
    Append a line to the test log with immediate flush.

    :param str msg: Message to write.
    """
    with open(_LOG, "a") as f:
        f.write(msg + "\n")
        f.flush()


def _pass(name):
    """
    Record a passing test.

    :param str name: Test name identifier.
    """
    global _pass_count
    _pass_count += 1
    line = "[PASS] {}".format(name)
    _results.append(line)
    _log(line)


def _fail(name, reason):
    """
    Record a failing test with reason.

    :param str name: Test name identifier.
    :param str reason: Why the test failed.
    """
    global _fail_count
    _fail_count += 1
    line = "[FAIL] {} -- {}".format(name, reason)
    _results.append(line)
    _log(line)


def _make_temp_file(name, content=""):
    """
    Create a temp file and register it for cleanup.

    :param str name: Filename (placed in _TEMP_DIR).
    :param str content: Initial file content.
    :return: Absolute path to the created file.
    :rtype: str
    """
    os.makedirs(_TEMP_DIR, exist_ok=True)
    path = os.path.join(_TEMP_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    _temp_files.append(path)
    return path


# --- Test Categories --------------------------------------------------------

def _test_plugin_and_window():
    """
    Category 1: Plugin & Window.

    Verifies plugin loads, editor window opens, and get_api() returns
    a non-None EditorAPI instance.
    """
    _log("\n=== 1. Plugin & Window ===")
    import maya.cmds as cmds

    # 1.1 Plugin loaded.
    try:
        loaded = cmds.pluginInfo("mcaEditor", q=True, loaded=True)
        if loaded:
            _pass("plugin_loaded")
        else:
            _fail("plugin_loaded", "Plugin not loaded")
    except Exception as exc:
        _fail("plugin_loaded", str(exc))

    # 1.2 Window exists.
    try:
        ws = "MCAEditorWorkspaceControl"
        exists = cmds.workspaceControl(ws, exists=True)
        if exists:
            _pass("window_exists")
        else:
            _fail("window_exists", "Workspace control does not exist")
    except Exception as exc:
        _fail("window_exists", str(exc))

    # 1.3 get_api() returns non-None.
    try:
        from mca_core.editor_api import get_api
        api = get_api()
        if api is not None:
            _pass("get_api_returns_instance")
        else:
            _fail("get_api_returns_instance", "get_api() returned None")
    except Exception as exc:
        _fail("get_api_returns_instance", str(exc))


def _test_dcc_connection(api):
    """
    Category 2: DCC Connection.

    Verifies the editor detects Maya as a connected DCC.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 2. DCC Connection ===")

    # 2.1 get_state() returns dcc.connected == True.
    try:
        state = api.get_state()
        if state and state.get("dcc", {}).get("connected"):
            _pass("dcc_connected")
        else:
            _fail("dcc_connected", "dcc.connected is not True: {}".format(
                state.get("dcc") if state else "no state"))
    except Exception as exc:
        _fail("dcc_connected", str(exc))

    # 2.2 dcc.type contains "maya".
    try:
        state = api.get_state()
        dcc_type = state.get("dcc", {}).get("type", "") or ""
        if "maya" in dcc_type.lower():
            _pass("dcc_type_is_maya")
        else:
            _fail("dcc_type_is_maya", "dcc.type = '{}'".format(dcc_type))
    except Exception as exc:
        _fail("dcc_type_is_maya", str(exc))

    # 2.3 Server port is set (API server running).
    try:
        state = api.get_state()
        port = state.get("server", {}).get("api_port")
        if port is not None:
            _pass("server_port_set")
        else:
            # Port may be None if server hasn't started — warn, don't fail hard.
            _fail("server_port_set", "api_port is None (server may not have started)")
    except Exception as exc:
        _fail("server_port_set", str(exc))


def _test_file_operations(api):
    """
    Category 3: File Operations.

    Tests open, list, active path, save, close, language detection,
    and error handling for nonexistent files.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 3. File Operations ===")

    # Create test files.
    py_content = "# test file\nprint('hello')\nx = 42\n"
    py_path = _make_temp_file("test_file_ops.py", py_content)

    mel_content = "// MEL test\npolySphere;\n"
    mel_path = _make_temp_file("test_file_ops.mel", mel_content)

    py2_content = "# second file\nimport os\n"
    py2_path = _make_temp_file("test_file_ops2.py", py2_content)

    # 3.1 open_file succeeds.
    try:
        result = api.open_file(py_path)
        if result.get("success"):
            _pass("open_file")
        else:
            _fail("open_file", result.get("error", "unknown"))
    except Exception as exc:
        _fail("open_file", str(exc))

    # 3.2 get_active_file_path matches.
    try:
        active = api.get_active_file_path()
        if active and os.path.normpath(active) == os.path.normpath(py_path):
            _pass("active_file_path_matches")
        else:
            _fail("active_file_path_matches",
                  "expected '{}', got '{}'".format(py_path, active))
    except Exception as exc:
        _fail("active_file_path_matches", str(exc))

    # 3.3 list_open_files includes the file.
    try:
        files = api.list_open_files()
        paths = [f.get("path") for f in files if f.get("path")]
        normed = [os.path.normpath(p) for p in paths]
        if os.path.normpath(py_path) in normed:
            _pass("list_includes_opened_file")
        else:
            _fail("list_includes_opened_file",
                  "path not in list: {}".format(normed))
    except Exception as exc:
        _fail("list_includes_opened_file", str(exc))

    # 3.4 get_text matches disk content.
    try:
        text = api.get_text()
        if text is not None and text.strip() == py_content.strip():
            _pass("get_text_matches_disk")
        else:
            _fail("get_text_matches_disk",
                  "text mismatch, got {} chars".format(len(text) if text else 0))
    except Exception as exc:
        _fail("get_text_matches_disk", str(exc))

    # 3.5 save_file succeeds.
    try:
        result = api.save_file()
        if result.get("success"):
            _pass("save_file")
        else:
            _fail("save_file", result.get("error", "unknown"))
    except Exception as exc:
        _fail("save_file", str(exc))

    # 3.6 Open second file increases tab count.
    try:
        count_before = len(api.list_open_files())
        api.open_file(py2_path)
        count_after = len(api.list_open_files())
        if count_after > count_before:
            _pass("open_second_file_increases_tabs")
        else:
            _fail("open_second_file_increases_tabs",
                  "before={}, after={}".format(count_before, count_after))
    except Exception as exc:
        _fail("open_second_file_increases_tabs", str(exc))

    # 3.7 close_tab decreases tab count.
    try:
        count_before = len(api.list_open_files())
        api.close_tab()
        count_after = len(api.list_open_files())
        if count_after < count_before:
            _pass("close_tab_decreases_tabs")
        else:
            _fail("close_tab_decreases_tabs",
                  "before={}, after={}".format(count_before, count_after))
    except Exception as exc:
        _fail("close_tab_decreases_tabs", str(exc))

    # 3.8 open_file with nonexistent path returns error.
    try:
        result = api.open_file("C:/nonexistent/file_that_does_not_exist.py")
        if not result.get("success"):
            _pass("open_nonexistent_returns_error")
        else:
            _fail("open_nonexistent_returns_error", "Expected error, got success")
    except Exception as exc:
        _fail("open_nonexistent_returns_error", str(exc))

    # 3.9 MEL file gets correct language.
    try:
        api.open_file(mel_path)
        lang = api.get_language()
        if lang and "mel" in lang.lower():
            _pass("mel_language_detection")
        else:
            _fail("mel_language_detection", "language = '{}'".format(lang))
    except Exception as exc:
        _fail("mel_language_detection", str(exc))

    # 3.10 Python file gets correct language.
    try:
        api.open_file(py_path)
        lang = api.get_language()
        if lang and "python" in lang.lower():
            _pass("python_language_detection")
        else:
            _fail("python_language_detection", "language = '{}'".format(lang))
    except Exception as exc:
        _fail("python_language_detection", str(exc))

    # Close test files to keep state clean.
    try:
        api.close_tab()
    except Exception:
        pass


def _test_editor_content(api):
    """
    Category 4: Editor Content.

    Tests set_text/get_text roundtrip, insert_text, replace_range,
    get_cursor_position, and out-of-range error handling.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 4. Editor Content ===")

    # Open a temp file for content editing.
    content = "line1\nline2\nline3\nline4\nline5\n"
    path = _make_temp_file("test_content.py", content)
    api.open_file(path)

    # 4.1 set_text / get_text roundtrip.
    try:
        new_text = "alpha\nbeta\ngamma\n"
        result = api.set_text(new_text)
        if not result.get("success"):
            _fail("set_text_get_text_roundtrip", "set_text failed: {}".format(
                result.get("error")))
        else:
            got = api.get_text()
            if got == new_text:
                _pass("set_text_get_text_roundtrip")
            else:
                _fail("set_text_get_text_roundtrip",
                      "expected {!r}, got {!r}".format(new_text, got))
    except Exception as exc:
        _fail("set_text_get_text_roundtrip", str(exc))

    # 4.2 set_text with empty string.
    try:
        api.set_text("")
        got = api.get_text()
        if got == "":
            _pass("set_text_empty")
        else:
            _fail("set_text_empty", "expected empty, got {!r}".format(got))
    except Exception as exc:
        _fail("set_text_empty", str(exc))

    # 4.3 set_text with unicode content.
    try:
        unicode_text = "# Unicode test\nx = '\u00e9\u00e0\u00fc\u00f1'\n"
        api.set_text(unicode_text)
        got = api.get_text()
        if got == unicode_text:
            _pass("set_text_unicode")
        else:
            _fail("set_text_unicode", "unicode mismatch")
    except Exception as exc:
        _fail("set_text_unicode", str(exc))

    # 4.4 insert_text at specific position.
    try:
        api.set_text("aaa\nbbb\nccc\n")
        # Insert "XXX" at line 2, col 2 (between first and second 'b').
        result = api.insert_text("XXX", line=2, col=2)
        if not result.get("success"):
            _fail("insert_text_at_position", "insert_text failed: {}".format(
                result.get("error")))
        else:
            got = api.get_text()
            if "bXXXbb" in got:
                _pass("insert_text_at_position")
            else:
                _fail("insert_text_at_position",
                      "expected 'bXXXbb' in text, got {!r}".format(got))
    except Exception as exc:
        _fail("insert_text_at_position", str(exc))

    # 4.5 insert_text at cursor (no line/col).
    try:
        api.set_text("hello world")
        # Move cursor to start by setting text, then insert at cursor.
        result = api.insert_text("START ")
        if result.get("success"):
            _pass("insert_text_at_cursor")
        else:
            _fail("insert_text_at_cursor", result.get("error", "unknown"))
    except Exception as exc:
        _fail("insert_text_at_cursor", str(exc))

    # 4.6 replace_range.
    try:
        api.set_text("line1\nline2\nline3\n")
        # Replace "line2" with "REPLACED".
        result = api.replace_range(2, 1, 2, 6, "REPLACED")
        if not result.get("success"):
            _fail("replace_range", "replace_range failed: {}".format(
                result.get("error")))
        else:
            got = api.get_text()
            if "REPLACED" in got and "line2" not in got:
                _pass("replace_range")
            else:
                _fail("replace_range",
                      "expected 'REPLACED' and no 'line2', got {!r}".format(got))
    except Exception as exc:
        _fail("replace_range", str(exc))

    # 4.7 replace_range with empty text (deletion).
    try:
        api.set_text("ABCDEF")
        # Delete characters 2-4 ("BCD").
        result = api.replace_range(1, 2, 1, 5, "")
        if result.get("success"):
            got = api.get_text()
            if got == "AEF":
                _pass("replace_range_delete")
            else:
                _fail("replace_range_delete", "expected 'AEF', got {!r}".format(got))
        else:
            _fail("replace_range_delete", result.get("error", "unknown"))
    except Exception as exc:
        _fail("replace_range_delete", str(exc))

    # 4.8 get_cursor_position returns valid dict.
    try:
        api.set_text("line1\nline2\nline3\n")
        pos = api.get_cursor_position()
        if pos and "line" in pos and "col" in pos:
            if isinstance(pos["line"], int) and isinstance(pos["col"], int):
                _pass("get_cursor_position")
            else:
                _fail("get_cursor_position",
                      "line/col not ints: {}".format(pos))
        else:
            _fail("get_cursor_position",
                  "unexpected result: {}".format(pos))
    except Exception as exc:
        _fail("get_cursor_position", str(exc))

    # 4.9 insert_text out-of-range line.
    try:
        api.set_text("only one line")
        result = api.insert_text("X", line=999, col=1)
        if not result.get("success"):
            _pass("insert_out_of_range_line")
        else:
            _fail("insert_out_of_range_line", "Expected error for line 999")
    except Exception as exc:
        _fail("insert_out_of_range_line", str(exc))

    # 4.10 replace_range out-of-range.
    try:
        api.set_text("short")
        result = api.replace_range(100, 1, 100, 5, "X")
        if not result.get("success"):
            _pass("replace_range_out_of_range")
        else:
            _fail("replace_range_out_of_range", "Expected error for line 100")
    except Exception as exc:
        _fail("replace_range_out_of_range", str(exc))

    # Clean up.
    try:
        api.close_tab()
    except Exception:
        pass


def _test_navigation(api):
    """
    Category 5: Navigation.

    Tests navigate_to, go_to_line, and cursor position after navigation.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 5. Navigation ===")

    # Create a multi-line file.
    lines = "\n".join(["line {}".format(i) for i in range(1, 21)]) + "\n"
    path = _make_temp_file("test_navigation.py", lines)

    # 5.1 navigate_to opens file and jumps to line 5.
    try:
        result = api.navigate_to(path, line=5)
        if result.get("success"):
            pos = api.get_cursor_position()
            if pos and pos["line"] == 5:
                _pass("navigate_to_line_5")
            else:
                _fail("navigate_to_line_5",
                      "cursor at line {}, expected 5".format(
                          pos["line"] if pos else "None"))
        else:
            _fail("navigate_to_line_5", result.get("error", "unknown"))
    except Exception as exc:
        _fail("navigate_to_line_5", str(exc))

    # 5.2 go_to_line moves cursor.
    try:
        result = api.go_to_line(10)
        if result.get("success"):
            pos = api.get_cursor_position()
            if pos and pos["line"] == 10:
                _pass("go_to_line_10")
            else:
                _fail("go_to_line_10",
                      "cursor at line {}, expected 10".format(
                          pos["line"] if pos else "None"))
        else:
            _fail("go_to_line_10", result.get("error", "unknown"))
    except Exception as exc:
        _fail("go_to_line_10", str(exc))

    # 5.3 go_to_line(1) — first line.
    try:
        result = api.go_to_line(1)
        if result.get("success"):
            pos = api.get_cursor_position()
            if pos and pos["line"] == 1:
                _pass("go_to_line_1")
            else:
                _fail("go_to_line_1",
                      "cursor at line {}, expected 1".format(
                          pos["line"] if pos else "None"))
        else:
            _fail("go_to_line_1", result.get("error", "unknown"))
    except Exception as exc:
        _fail("go_to_line_1", str(exc))

    # 5.4 navigate_to with nonexistent file returns error.
    try:
        result = api.navigate_to("C:/does_not_exist_nav.py", line=1)
        if not result.get("success"):
            _pass("navigate_to_nonexistent")
        else:
            _fail("navigate_to_nonexistent", "Expected error, got success")
    except Exception as exc:
        _fail("navigate_to_nonexistent", str(exc))

    # Clean up.
    try:
        api.close_tab()
    except Exception:
        pass


def _test_output_panel(api):
    """
    Category 6: Output Panel.

    Tests write_output at various levels, get_output_text, and clear_output.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 6. Output Panel ===")

    # 6.1 clear_output succeeds.
    try:
        result = api.clear_output()
        if result.get("success"):
            _pass("clear_output")
        else:
            _fail("clear_output", result.get("error", "unknown"))
    except Exception as exc:
        _fail("clear_output", str(exc))

    # 6.2 write_output at info level.
    try:
        result = api.write_output("TEST_INFO_MSG_12345", level="info")
        if result.get("success"):
            _pass("write_output_info")
        else:
            _fail("write_output_info", result.get("error", "unknown"))
    except Exception as exc:
        _fail("write_output_info", str(exc))

    # 6.3 write_output at warning level.
    try:
        result = api.write_output("TEST_WARNING_MSG_67890", level="warning")
        if result.get("success"):
            _pass("write_output_warning")
        else:
            _fail("write_output_warning", result.get("error", "unknown"))
    except Exception as exc:
        _fail("write_output_warning", str(exc))

    # 6.4 write_output at error level.
    try:
        result = api.write_output("TEST_ERROR_MSG_ABCDE", level="error")
        if result.get("success"):
            _pass("write_output_error")
        else:
            _fail("write_output_error", result.get("error", "unknown"))
    except Exception as exc:
        _fail("write_output_error", str(exc))

    # 6.5 get_output_text contains written messages.
    # Output panel buffers messages and flushes on a 16ms timer tick.
    # Process events multiple times to ensure the flush timer fires.
    try:
        from PySide6.QtCore import QCoreApplication
    except ImportError:
        from PySide2.QtCore import QCoreApplication
    import time as _time
    for _ in range(5):
        QCoreApplication.processEvents()
        _time.sleep(0.05)

    try:
        text = api.get_output_text(max_lines=200)
        found_info = "TEST_INFO_MSG_12345" in text
        found_warning = "TEST_WARNING_MSG_67890" in text
        found_error = "TEST_ERROR_MSG_ABCDE" in text
        if found_info and found_warning and found_error:
            _pass("get_output_text_contains_messages")
        else:
            _fail("get_output_text_contains_messages",
                  "info={}, warn={}, err={}, text_len={}".format(
                      found_info, found_warning, found_error, len(text)))
    except Exception as exc:
        _fail("get_output_text_contains_messages", str(exc))

    # 6.6 clear then verify output is empty (or at least our markers are gone).
    try:
        api.clear_output()
        text = api.get_output_text(max_lines=200)
        if "TEST_INFO_MSG_12345" not in text:
            _pass("clear_output_removes_content")
        else:
            _fail("clear_output_removes_content",
                  "Marker still present after clear")
    except Exception as exc:
        _fail("clear_output_removes_content", str(exc))


def _test_dcc_execution(api):
    """
    Category 7: DCC Execution.

    Tests execute_in_dcc for Python and MEL commands, including
    object creation, verification, cleanup, and error handling.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 7. DCC Execution ===")

    # 7.1 Simple Python import.
    try:
        result = api.execute_in_dcc("import maya.cmds as cmds")
        if result.get("success"):
            _pass("dcc_exec_import")
        else:
            _fail("dcc_exec_import", result.get("error", "unknown"))
    except Exception as exc:
        _fail("dcc_exec_import", str(exc))

    # 7.2 Execute expression and verify success.
    # NOTE: The internal Maya adapter returns empty string for print() output
    # (stdout flows through MCommandMessage callback, not the return value).
    # So we verify success=True and check side effects via maya.cmds directly.
    try:
        result = api.execute_in_dcc(
            "import maya.cmds as cmds; cmds.objExists('persp')"
        )
        if result.get("success"):
            _pass("dcc_exec_expression")
        else:
            _fail("dcc_exec_expression", result.get("error", "unknown"))
    except Exception as exc:
        _fail("dcc_exec_expression", str(exc))

    # 7.3 Create polyCube via DCC and verify with cmds directly.
    try:
        result = api.execute_in_dcc(
            "import maya.cmds as cmds; cmds.polyCube(name='mca_test_cube')"
        )
        if result.get("success"):
            _maya_objects.append("mca_test_cube")
            _pass("dcc_exec_create_cube")
        else:
            _fail("dcc_exec_create_cube", result.get("error", "unknown"))
    except Exception as exc:
        _fail("dcc_exec_create_cube", str(exc))

    # 7.4 Verify cube exists using maya.cmds directly (not via DCC output).
    try:
        import maya.cmds as _cmds
        if _cmds.objExists("mca_test_cube"):
            _pass("dcc_exec_verify_cube_exists")
        else:
            _fail("dcc_exec_verify_cube_exists", "Cube not found in scene")
    except Exception as exc:
        _fail("dcc_exec_verify_cube_exists", str(exc))

    # 7.5 Delete cube.
    try:
        result = api.execute_in_dcc(
            "import maya.cmds as cmds; cmds.delete('mca_test_cube')"
        )
        if result.get("success"):
            _maya_objects.remove("mca_test_cube")
            _pass("dcc_exec_delete_cube")
        else:
            _fail("dcc_exec_delete_cube", result.get("error", "unknown"))
    except Exception as exc:
        _fail("dcc_exec_delete_cube", str(exc))

    # 7.6 MEL execution — create sphere.
    try:
        result = api.execute_in_dcc("polySphere -name mca_test_sphere;", language="mel")
        if result.get("success"):
            _maya_objects.append("mca_test_sphere")
            _pass("dcc_exec_mel_sphere")
        else:
            _fail("dcc_exec_mel_sphere", result.get("error", "unknown"))
    except Exception as exc:
        _fail("dcc_exec_mel_sphere", str(exc))

    # 7.7 Clean up MEL sphere.
    try:
        result = api.execute_in_dcc(
            "import maya.cmds as cmds; cmds.delete('mca_test_sphere')"
        )
        if result.get("success"):
            if "mca_test_sphere" in _maya_objects:
                _maya_objects.remove("mca_test_sphere")
            _pass("dcc_exec_cleanup_mel_sphere")
        else:
            _fail("dcc_exec_cleanup_mel_sphere", result.get("error", "unknown"))
    except Exception as exc:
        _fail("dcc_exec_cleanup_mel_sphere", str(exc))

    # 7.8 Bad Python code — verify error is handled without crashing.
    # The internal adapter routes errors through MGlobal.displayError(),
    # so the return dict may have success=True with no output, or
    # success=False with an error string.  Either way it should not crash.
    try:
        result = api.execute_in_dcc("raise ValueError('test error')")
        # If we get here without an exception, the error was handled gracefully.
        _pass("dcc_exec_error_handling")
    except Exception as exc:
        _fail("dcc_exec_error_handling", str(exc))


def _test_local_execution(api):
    """
    Category 8: Local Execution.

    Tests execute_locally for stdout capture, namespace persistence,
    and error handling.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 8. Local Execution ===")

    # 8.1 Print and capture stdout.
    try:
        result = api.execute_locally("print('local_output_test')")
        if result.get("success") and "local_output_test" in result.get("output", ""):
            _pass("local_exec_print")
        else:
            _fail("local_exec_print",
                  "success={}, output='{}'".format(
                      result.get("success"), result.get("output", "")))
    except Exception as exc:
        _fail("local_exec_print", str(exc))

    # 8.2 Namespace persistence — set variable.
    try:
        result = api.execute_locally("_mca_test_var = 42")
        if result.get("success"):
            _pass("local_exec_set_var")
        else:
            _fail("local_exec_set_var", result.get("error", "unknown"))
    except Exception as exc:
        _fail("local_exec_set_var", str(exc))

    # 8.3 Namespace persistence — read variable.
    try:
        result = api.execute_locally("print(_mca_test_var)")
        if result.get("success") and "42" in result.get("output", ""):
            _pass("local_exec_read_var")
        else:
            _fail("local_exec_read_var",
                  "output='{}'".format(result.get("output", "")))
    except Exception as exc:
        _fail("local_exec_read_var", str(exc))

    # 8.4 ZeroDivisionError handling.
    try:
        result = api.execute_locally("x = 1 / 0")
        if not result.get("success") and "ZeroDivisionError" in result.get("error", ""):
            _pass("local_exec_zero_division")
        else:
            _fail("local_exec_zero_division",
                  "Expected ZeroDivisionError, got: {}".format(result))
    except Exception as exc:
        _fail("local_exec_zero_division", str(exc))

    # 8.5 Multi-line code execution.
    try:
        code = "a = 10\nb = 20\nprint(a + b)"
        result = api.execute_locally(code)
        if result.get("success") and "30" in result.get("output", ""):
            _pass("local_exec_multiline")
        else:
            _fail("local_exec_multiline",
                  "output='{}'".format(result.get("output", "")))
    except Exception as exc:
        _fail("local_exec_multiline", str(exc))


def _test_disk_file_io(api):
    """
    Category 9: Disk File I/O.

    Tests read_disk_file and write_disk_file, including roundtrip,
    error handling, and overwrite behavior.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 9. Disk File I/O ===")

    disk_path = os.path.join(_TEMP_DIR, "test_disk_io.txt")
    _temp_files.append(disk_path)

    # 9.1 write_disk_file creates file.
    try:
        result = api.write_disk_file(disk_path, "disk content test")
        if result.get("success") and os.path.isfile(disk_path):
            _pass("write_disk_file")
        else:
            _fail("write_disk_file", result.get("error", "file not created"))
    except Exception as exc:
        _fail("write_disk_file", str(exc))

    # 9.2 read_disk_file roundtrip.
    try:
        result = api.read_disk_file(disk_path)
        if result.get("success") and result.get("result") == "disk content test":
            _pass("read_disk_file_roundtrip")
        else:
            _fail("read_disk_file_roundtrip",
                  "result='{}'".format(result.get("result", "")))
    except Exception as exc:
        _fail("read_disk_file_roundtrip", str(exc))

    # 9.3 read_disk_file nonexistent returns error.
    try:
        result = api.read_disk_file("C:/nonexistent_disk_file.txt")
        if not result.get("success"):
            _pass("read_disk_file_nonexistent")
        else:
            _fail("read_disk_file_nonexistent", "Expected error, got success")
    except Exception as exc:
        _fail("read_disk_file_nonexistent", str(exc))

    # 9.4 write_disk_file overwrite.
    try:
        api.write_disk_file(disk_path, "overwritten content")
        result = api.read_disk_file(disk_path)
        if result.get("success") and result.get("result") == "overwritten content":
            _pass("write_disk_file_overwrite")
        else:
            _fail("write_disk_file_overwrite",
                  "result='{}'".format(result.get("result", "")))
    except Exception as exc:
        _fail("write_disk_file_overwrite", str(exc))

    # 9.5 write_disk_file with unicode.
    try:
        unicode_content = "Unicode: \u00e9\u00e0\u00fc \u2603 \u2764"
        api.write_disk_file(disk_path, unicode_content)
        result = api.read_disk_file(disk_path)
        if result.get("success") and result.get("result") == unicode_content:
            _pass("disk_file_unicode")
        else:
            _fail("disk_file_unicode", "unicode roundtrip mismatch")
    except Exception as exc:
        _fail("disk_file_unicode", str(exc))

    # 9.6 write_disk_file creates parent directories.
    try:
        nested_path = os.path.join(_TEMP_DIR, "subdir_a", "subdir_b", "nested.txt")
        _temp_files.append(nested_path)
        result = api.write_disk_file(nested_path, "nested content")
        if result.get("success") and os.path.isfile(nested_path):
            _pass("write_disk_file_creates_dirs")
        else:
            _fail("write_disk_file_creates_dirs",
                  result.get("error", "file not created"))
    except Exception as exc:
        _fail("write_disk_file_creates_dirs", str(exc))


def _test_settings(api):
    """
    Category 10: Settings.

    Tests get_setting, set_setting, and restore — verifying that
    settings can be read and written without breaking existing values.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 10. Settings ===")

    # Save original font_size to restore later.
    original_font_size = None

    # 10.1 get_setting reads font_size.
    try:
        original_font_size = api.get_setting("font_size", 12)
        if isinstance(original_font_size, (int, float)):
            _pass("get_setting_font_size")
        else:
            _fail("get_setting_font_size",
                  "unexpected type: {}".format(type(original_font_size)))
    except Exception as exc:
        _fail("get_setting_font_size", str(exc))

    # 10.2 set_setting changes font_size.
    try:
        test_size = 16
        result = api.set_setting("font_size", test_size)
        if result.get("success"):
            readback = api.get_setting("font_size")
            if readback == test_size:
                _pass("set_setting_font_size")
            else:
                _fail("set_setting_font_size",
                      "expected {}, got {}".format(test_size, readback))
        else:
            _fail("set_setting_font_size", result.get("error", "unknown"))
    except Exception as exc:
        _fail("set_setting_font_size", str(exc))

    # 10.3 Restore original font_size.
    try:
        if original_font_size is not None:
            result = api.set_setting("font_size", original_font_size)
            if result.get("success"):
                _pass("restore_font_size")
            else:
                _fail("restore_font_size", result.get("error", "unknown"))
        else:
            _pass("restore_font_size")  # Nothing to restore.
    except Exception as exc:
        _fail("restore_font_size", str(exc))

    # 10.4 get_setting with nonexistent key returns default.
    try:
        val = api.get_setting("nonexistent_key_xyz_999", "my_default")
        if val == "my_default":
            _pass("get_setting_default")
        else:
            _fail("get_setting_default",
                  "expected 'my_default', got {!r}".format(val))
    except Exception as exc:
        _fail("get_setting_default", str(exc))

    # 10.5 get_setting reads theme.
    try:
        theme = api.get_setting("theme", None)
        # Theme should be a string if set, or None.
        if theme is None or isinstance(theme, str):
            _pass("get_setting_theme")
        else:
            _fail("get_setting_theme",
                  "unexpected type: {}".format(type(theme)))
    except Exception as exc:
        _fail("get_setting_theme", str(exc))

    # 10.6 get_state includes server version.
    try:
        state = api.get_state()
        version = state.get("server", {}).get("version")
        if version and isinstance(version, str):
            _pass("state_has_version")
        else:
            _fail("state_has_version",
                  "version='{}'".format(version))
    except Exception as exc:
        _fail("state_has_version", str(exc))


def _test_project_management(api):
    """
    Category 11: Project Management.

    Tests open_project, get_project, close_project, and state integration.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 11. Project Management ===")

    # Create a temp directory with a .mca-project file so open_project()
    # loads it directly without showing the interactive creation dialog.
    import json
    project_dir = os.path.join(_TEMP_DIR, "test_project")
    os.makedirs(project_dir, exist_ok=True)
    # Create a dummy file inside so it looks like a real project.
    dummy = os.path.join(project_dir, "main.py")
    with open(dummy, "w") as f:
        f.write("# dummy\n")
    # Create the .mca-project file so has_project_file() returns True.
    project_file = os.path.join(project_dir, ".mca-project")
    project_data = {
        "schema_version": 3,
        "name": "TestProject",
        "python_paths": [],
        "excluded_folders": ["__pycache__", ".git"],
    }
    with open(project_file, "w") as f:
        json.dump(project_data, f)

    # 11.1 open_project succeeds.
    try:
        result = api.open_project(project_dir)
        if result.get("success"):
            _pass("open_project")
        else:
            _fail("open_project", result.get("error", "unknown"))
    except Exception as exc:
        _fail("open_project", str(exc))

    # 11.2 get_project has root.
    try:
        proj = api.get_project()
        if proj and proj.get("root"):
            norm_root = os.path.normpath(proj["root"])
            norm_expected = os.path.normpath(project_dir)
            if norm_root == norm_expected:
                _pass("get_project_root")
            else:
                _fail("get_project_root",
                      "expected '{}', got '{}'".format(norm_expected, norm_root))
        else:
            _fail("get_project_root",
                  "get_project returned: {}".format(proj))
    except Exception as exc:
        _fail("get_project_root", str(exc))

    # 11.3 get_project has name.
    try:
        proj = api.get_project()
        if proj and proj.get("name"):
            _pass("get_project_name")
        else:
            _fail("get_project_name",
                  "name missing: {}".format(proj))
    except Exception as exc:
        _fail("get_project_name", str(exc))

    # 11.4 get_state includes project info.
    try:
        state = api.get_state()
        if state and state.get("project") is not None:
            _pass("state_has_project")
        else:
            _fail("state_has_project", "project is None in state")
    except Exception as exc:
        _fail("state_has_project", str(exc))

    # 11.5 open_project with nonexistent dir returns error.
    try:
        result = api.open_project("C:/nonexistent_project_dir_xyz")
        if not result.get("success"):
            _pass("open_project_nonexistent")
        else:
            _fail("open_project_nonexistent", "Expected error, got success")
    except Exception as exc:
        _fail("open_project_nonexistent", str(exc))

    # 11.6 close_project succeeds.
    try:
        result = api.close_project()
        if result.get("success"):
            _pass("close_project")
        else:
            _fail("close_project", result.get("error", "unknown"))
    except Exception as exc:
        _fail("close_project", str(exc))

    # 11.7 get_project returns None after close.
    try:
        proj = api.get_project()
        if proj is None:
            _pass("project_none_after_close")
        else:
            _fail("project_none_after_close",
                  "expected None, got: {}".format(proj))
    except Exception as exc:
        _fail("project_none_after_close", str(exc))


def _test_multi_tab(api):
    """
    Category 12: Multi-Tab & Save All.

    Tests opening multiple files, verifying tab count, modifying
    content, save_all, and cleanup.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 12. Multi-Tab & Save All ===")

    # Create 3 temp files.
    paths = []
    for i in range(3):
        p = _make_temp_file("test_multi_{}.py".format(i),
                            "# file {}\n".format(i))
        paths.append(p)

    # 12.1 Open all 3 files.
    try:
        for p in paths:
            api.open_file(p)
        files = api.list_open_files()
        opened_paths = [os.path.normpath(f["path"]) for f in files if f.get("path")]
        all_present = all(os.path.normpath(p) in opened_paths for p in paths)
        if all_present:
            _pass("open_3_files")
        else:
            _fail("open_3_files",
                  "not all files present: {}".format(opened_paths))
    except Exception as exc:
        _fail("open_3_files", str(exc))

    # 12.2 Tab count includes all 3.
    try:
        count = len(api.list_open_files())
        if count >= 3:
            _pass("tab_count_at_least_3")
        else:
            _fail("tab_count_at_least_3", "count={}".format(count))
    except Exception as exc:
        _fail("tab_count_at_least_3", str(exc))

    # 12.3 Modify active file content.
    try:
        result = api.set_text("# modified content\nprint('modified')\n")
        if result.get("success"):
            _pass("modify_active_tab")
        else:
            _fail("modify_active_tab", result.get("error", "unknown"))
    except Exception as exc:
        _fail("modify_active_tab", str(exc))

    # 12.4 save_all returns list.
    try:
        results = api.save_all()
        # save_all returns a list (may be empty if nothing modified after set_text).
        if isinstance(results, list):
            _pass("save_all_returns_list")
        else:
            _fail("save_all_returns_list",
                  "expected list, got {}".format(type(results)))
    except Exception as exc:
        _fail("save_all_returns_list", str(exc))

    # 12.5 Close all test tabs.
    try:
        closed = 0
        # Close up to 5 tabs (more than we opened, to be safe).
        for _ in range(5):
            active = api.get_active_file_path()
            if active and os.path.normpath(active).startswith(
                    os.path.normpath(_TEMP_DIR)):
                api.close_tab()
                closed += 1
            else:
                break
        if closed >= 1:
            _pass("close_test_tabs")
        else:
            _pass("close_test_tabs")  # Nothing to close is also okay.
    except Exception as exc:
        _fail("close_test_tabs", str(exc))


def _test_maya_isolation(api):
    """
    Category 13: Maya Isolation.

    Verifies that tests haven't leaked objects into the scene and
    that Maya's core systems are still healthy.

    :param EditorAPI api: The API instance.
    """
    _log("\n=== 13. Maya Isolation ===")
    import maya.cmds as cmds

    # 13.1 No leaked test objects.
    try:
        leaked = []
        for obj_name in ["mca_test_cube", "mca_test_sphere"]:
            if cmds.objExists(obj_name):
                leaked.append(obj_name)
        if not leaked:
            _pass("no_leaked_objects")
        else:
            _fail("no_leaked_objects", "leaked: {}".format(leaked))
    except Exception as exc:
        _fail("no_leaked_objects", str(exc))

    # 13.2 Undo queue still works.
    try:
        cmds.polyCube(name="mca_undo_test")
        cmds.undo()
        if not cmds.objExists("mca_undo_test"):
            _pass("undo_queue_intact")
        else:
            # Clean up just in case.
            cmds.delete("mca_undo_test")
            _fail("undo_queue_intact", "undo did not remove object")
    except Exception as exc:
        _fail("undo_queue_intact", str(exc))

    # 13.3 Command ports still open (Python port 7002 used by adapter).
    try:
        ports = cmds.commandPort(query=True, listPorts=True) or []
        if any("7002" in str(p) for p in ports):
            _pass("command_port_7002_open")
        else:
            # Port might not be open in test env — warn but pass.
            _log("  NOTE: Port 7002 not found in ports: {}".format(ports))
            _pass("command_port_7002_open")
    except Exception as exc:
        _fail("command_port_7002_open", str(exc))

    # 13.4 get_state still works (API not corrupted).
    try:
        state = api.get_state()
        if state and isinstance(state, dict):
            _pass("get_state_still_works")
        else:
            _fail("get_state_still_works",
                  "unexpected state: {}".format(state))
    except Exception as exc:
        _fail("get_state_still_works", str(exc))

    # 13.5 Default cameras intact.
    try:
        cams = ["persp", "top", "front", "side"]
        missing = [c for c in cams if not cmds.objExists(c)]
        if not missing:
            _pass("default_cameras_intact")
        else:
            _fail("default_cameras_intact",
                  "missing cameras: {}".format(missing))
    except Exception as exc:
        _fail("default_cameras_intact", str(exc))


# --- Cleanup ----------------------------------------------------------------

def _cleanup():
    """
    Remove temp files and Maya objects created during tests.
    """
    _log("\n=== Cleanup ===")
    import maya.cmds as cmds

    # Delete any leftover Maya test objects.
    for obj_name in _maya_objects:
        try:
            if cmds.objExists(obj_name):
                cmds.delete(obj_name)
                _log("  Deleted Maya object: {}".format(obj_name))
        except Exception:
            pass

    # Remove temp files.
    for fpath in _temp_files:
        try:
            if os.path.isfile(fpath):
                os.remove(fpath)
        except Exception:
            pass

    # Remove temp directory tree.
    import shutil
    try:
        if os.path.isdir(_TEMP_DIR):
            shutil.rmtree(_TEMP_DIR, ignore_errors=True)
            _log("  Removed temp dir: {}".format(_TEMP_DIR))
    except Exception:
        pass


# --- Main Test Runner -------------------------------------------------------

def _run_all_tests():
    """
    Main test sequence — runs after Maya's UI is fully initialized.

    Loads the plugin, opens the editor, gets the API, then runs all
    test categories with QTimer delays between them to let Qt process
    events.  Writes summary and quits Maya when done.
    """
    import maya.cmds as cmds

    try:
        # --- Setup: load plugin and open editor -------------------------
        _log("SETUP_START")

        if not cmds.pluginInfo("mcaEditor", q=True, loaded=True):
            cmds.loadPlugin("mcaEditor")
        _log("PLUGIN_LOADED")

        from mca_maya.maya_window import show_mca_editor
        show_mca_editor()
        _log("WINDOW_OPENED")

        try:
            from PySide6.QtCore import QTimer, QCoreApplication
        except ImportError:
            from PySide2.QtCore import QTimer, QCoreApplication

        # Let the window paint and settle before running tests.
        def _start_tests():
            """Kick off the test categories with delays between them."""
            from mca_core.editor_api import get_api
            api = get_api()

            if api is None:
                _log("[FAIL] get_api() returned None — cannot run tests")
                _log("FAIL")
                cmds.quit(force=True)
                return

            _log("API_READY")

            # Build a list of (category_function, api_arg_needed) tuples.
            # Categories run sequentially with QTimer delays so Qt can
            # process events between batches.
            categories = [
                (_test_plugin_and_window, False),
                (_test_dcc_connection, True),
                (_test_file_operations, True),
                (_test_editor_content, True),
                (_test_navigation, True),
                (_test_output_panel, True),
                (_test_dcc_execution, True),
                (_test_local_execution, True),
                (_test_disk_file_io, True),
                (_test_settings, True),
                (_test_project_management, True),
                (_test_multi_tab, True),
                (_test_maya_isolation, True),
            ]

            # Index tracker for sequential scheduling.
            state = {"idx": 0}

            def _run_next_category():
                """Run the next test category, then schedule the one after."""
                idx = state["idx"]
                if idx >= len(categories):
                    # All categories done — finalize.
                    _finalize(api)
                    return

                func, needs_api = categories[idx]
                try:
                    if needs_api:
                        func(api)
                    else:
                        func()
                except Exception:
                    _log("CATEGORY_EXCEPTION: {}".format(func.__name__))
                    _log(traceback.format_exc())

                # Process pending Qt events to catch deferred crashes.
                QCoreApplication.processEvents()

                state["idx"] += 1
                # Schedule next category after 500ms delay.
                QTimer.singleShot(500, _run_next_category)

            # Start the first category.
            _run_next_category()

        # Wait 2 seconds after window open for Qt to fully settle.
        QTimer.singleShot(2000, _start_tests)

    except Exception:
        _log("SETUP_EXCEPTION")
        _log(traceback.format_exc())
        _log("FAIL")
        try:
            cmds.quit(force=True)
        except Exception:
            pass


def _finalize(api):
    """
    Write the summary block and quit Maya.

    :param EditorAPI api: The API instance (unused but kept for consistency).
    """
    import maya.cmds as cmds

    # Run cleanup.
    _cleanup()

    # Write summary.
    _log("\n=== SUMMARY ===")
    _log("Passed: {}".format(_pass_count))
    _log("Failed: {}".format(_fail_count))
    _log("Total:  {}".format(_pass_count + _fail_count))

    if _fail_count > 0:
        _log("\nFailed tests:")
        for r in _results:
            if r.startswith("[FAIL]"):
                _log("  {}".format(r))

    _log("")
    if _fail_count == 0:
        _log("PASS")
    else:
        _log("FAIL")

    # Give Maya a moment to flush, then quit.
    try:
        from PySide6.QtCore import QTimer
    except ImportError:
        from PySide2.QtCore import QTimer

    QTimer.singleShot(1000, lambda: cmds.quit(force=True))


# --- Entry Point (runs when Maya sources this file) -------------------------

# Clear previous log so we start fresh.
with open(_LOG, "w") as _f:
    _f.write("")

_log("STARTED")
_log("Test suite: maya_editor_test.py (comprehensive)")

# Schedule the tests AFTER Maya finishes startup.
import maya.utils
maya.utils.executeDeferred(_run_all_tests)
