"""
MCA Core - Code Analysis Engine.

Provides real-time Python code analysis for inline diagnostics (gutter
markers, wavy underlines, hover tooltips). Runs entirely on the main
thread — both tiers are fast enough (<100ms) for typical files.

Tier 1 — ``compile()`` (always available):
    Catches SyntaxError, IndentationError, TabError. Zero dependencies.

Tier 2 — ``pyflakes`` (optional):
    Detects unused imports, undefined names, redefined variables, etc.
    Only runs when pyflakes is importable and the code has no syntax
    errors (pyflakes can't parse broken syntax anyway).

Diagnostic dict format::

    {
        "line": 5,          # 1-based line number
        "col": 0,           # 0-based column (or 0 if unknown)
        "end_col": None,    # 0-based end column (or None)
        "severity": "error",  # "error" or "warning"
        "message": "invalid syntax",
    }

Dependencies:
    - None required (stdlib only)
    - pyflakes (optional, for Tier 2 warnings)
"""

import logging

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Pyflakes availability check -------------------------------------------
# We try to import pyflakes once at module load. If it's not installed,
# Tier 2 analysis is silently skipped.

_HAS_PYFLAKES = False

try:
    from pyflakes import api as _pyflakes_api
    from pyflakes import messages as _pyflakes_messages
    _HAS_PYFLAKES = True
    logger.debug("pyflakes available — Tier 2 analysis enabled")
except ImportError:
    logger.debug("pyflakes not installed — Tier 2 analysis disabled")


# --- Pyflakes severity mapping ----------------------------------------------
# These message types indicate real errors (undefined names, star imports).
# Everything else is treated as a warning.

_PYFLAKES_ERROR_TYPES = (
    "UndefinedName",
    "UndefinedExport",
    "UndefinedLocal",
    "ImportStarUsed",
    "ImportStarNotPermitted",
)


# =============================================================================
# Public API
# =============================================================================

def analyze_python(code):
    """
    Run all available analysis tiers on Python source code.

    Tier 1 (compile) always runs first. If a syntax error is found,
    Tier 2 is skipped because pyflakes can't parse broken syntax.

    :param str code: Python source code to analyze.
    :return: List of diagnostic dicts sorted by line number.
    :rtype: list
    """
    diagnostics = []

    # --- Tier 1: compile() for syntax errors ---
    syntax_diag = _check_syntax(code)
    if syntax_diag:
        diagnostics.append(syntax_diag)
        # Syntax error found — skip Tier 2 since pyflakes can't parse it.
        return diagnostics

    # --- Tier 2: pyflakes for warnings and undefined names ---
    if _HAS_PYFLAKES:
        pyflakes_diags = _check_pyflakes(code)
        diagnostics.extend(pyflakes_diags)

    # Sort by line number for consistent display order.
    diagnostics.sort(key=lambda d: d["line"])
    return diagnostics


# =============================================================================
# Tier 1 — Syntax Check via compile()
# =============================================================================

def _check_syntax(code):
    """
    Attempt to compile the code and catch syntax errors.

    Catches SyntaxError (and its subclasses IndentationError, TabError).

    :param str code: Python source code.
    :return: A diagnostic dict if a syntax error was found, else None.
    :rtype: dict or None
    """
    try:
        compile(code, "<editor>", "exec")
        return None
    except SyntaxError as exc:
        # SyntaxError provides .lineno, .offset, .end_offset, .msg.
        line = exc.lineno or 1
        # .offset is 1-based in Python; convert to 0-based for our format.
        col = (exc.offset - 1) if exc.offset else 0
        # .end_offset was added in Python 3.10; may not exist on older versions.
        end_col = None
        if hasattr(exc, "end_offset") and exc.end_offset is not None:
            end_col = exc.end_offset - 1

        return {
            "line": line,
            "col": col,
            "end_col": end_col,
            "severity": "error",
            "message": exc.msg or "SyntaxError",
        }


# =============================================================================
# Tier 2 — Pyflakes Analysis
# =============================================================================

def _check_pyflakes(code):
    """
    Run pyflakes on the code and collect diagnostics.

    Uses a custom reporter that captures messages instead of printing
    them to stderr. Each pyflakes message class is mapped to either
    "error" or "warning" severity.

    :param str code: Python source code (must be valid syntax).
    :return: List of diagnostic dicts from pyflakes.
    :rtype: list
    """
    diagnostics = []

    try:
        # pyflakes.api.check() takes code, filename, and a reporter.
        # We use a custom reporter to collect messages programmatically.
        result = _pyflakes_api.check(code, "<editor>", reporter=_DiagnosticReporter(diagnostics))
    except Exception:
        # If pyflakes crashes for any reason, don't break the editor.
        logger.debug("pyflakes analysis failed", exc_info=True)

    return diagnostics


class _DiagnosticReporter:
    """
    Custom pyflakes reporter that collects messages as diagnostic dicts.

    Pyflakes calls ``flake(message)`` for each issue and
    ``unexpectedError(filename, msg)`` for internal errors.

    :param list diagnostics: Mutable list to append diagnostics to.
    """

    def __init__(self, diagnostics):
        """
        Initialize the reporter.

        :param list diagnostics: List that will receive diagnostic dicts.
        """
        self._diagnostics = diagnostics

    def flake(self, message):
        """
        Handle a single pyflakes message.

        :param message: A pyflakes message object with .lineno and
            .message_args attributes. The class name indicates the
            type of issue.
        """
        # Determine severity from the message class name.
        class_name = message.__class__.__name__
        if class_name in _PYFLAKES_ERROR_TYPES:
            severity = "error"
        else:
            severity = "warning"

        # Format the human-readable message string.
        try:
            msg_text = message.message % message.message_args
        except (TypeError, AttributeError):
            msg_text = str(message)

        self._diagnostics.append({
            "line": message.lineno,
            "col": message.col if hasattr(message, "col") else 0,
            "end_col": None,
            "severity": severity,
            "message": msg_text,
        })

    def unexpectedError(self, filename, msg):
        """
        Handle unexpected pyflakes errors (internal failures).

        We log these but don't surface them to the user — they're
        pyflakes bugs, not user code problems.

        :param str filename: The filename being analyzed.
        :param str msg: The error message.
        """
        logger.debug("pyflakes unexpected error in %s: %s", filename, msg)
