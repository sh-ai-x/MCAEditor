def execute_python(code: str):
    """Execute arbitrary Python code in Unreal's interpreter.

    The code has full access to the ``unreal`` module and all UE Python APIs.

    :param code: Python code to execute.
    """
    import sys
    import io
    import traceback

    # Capture stdout and stderr during execution.
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf

    result_value = None
    error_text = None

    try:
        # Try eval first (for expressions that return a value).
        try:
            result_value = str(eval(code))
        except SyntaxError:
            # Fall back to exec for statements.
            exec(code, globals())
    except Exception:
        error_text = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    stdout_text = stdout_buf.getvalue()
    stderr_text = stderr_buf.getvalue()

    output = ""
    if stdout_text:
        output += stdout_text
    if result_value:
        output += result_value
    if stderr_text:
        output += "\n[stderr] " + stderr_text

    return {
        "success": error_text is None,
        "output": output,
        "error": error_text,
    }
