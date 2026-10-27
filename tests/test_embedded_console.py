"""
Smoke test for EmbeddedConsoleWidget (native Win32 console reparenting).

Spawns a real powershell.exe console, waits for it to be reparented
into the widget, resizes the widget, and checks that cleanup() leaves
no process behind.

NOT headless -- reparenting a real HWND requires an actual native
window, so this does not set QT_QPA_PLATFORM=offscreen like the other
tests in this directory. Windows-only.

Usage:
    python tests/test_embedded_console.py
"""

import ctypes
import os
import platform
import sys
import time
from ctypes import wintypes

# Run from anywhere -- resolve the project root relative to this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mca_qt.qt_compat import QApplication
from mca_core.plugins.powershell_terminal.native_console_widget import (
    EmbeddedConsoleWidget,
)

# A single QApplication serves every check.
_app = QApplication.instance() or QApplication(sys.argv)

# Labels of checks that did not match, reported together at the end.
FAILURES = []

_user32 = ctypes.windll.user32 if platform.system() == "Windows" else None
if _user32:
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND


def check(label, got, want):
    """
    Compare *got* against *want* and record the outcome.

    :param str label: Human-readable description of the check.
    :param got: Actual value.
    :param want: Expected value.
    """
    if got == want:
        print("PASS   %s" % label)
        return
    print("FAIL   %s" % label)
    print("         want: %r" % want)
    print("         got : %r" % got)
    FAILURES.append(label)


def pump_until(predicate, timeout_secs=10.0):
    """
    Process Qt events until *predicate()* is true or the timeout elapses.

    :param callable predicate: Returns True once the awaited condition holds.
    :param float timeout_secs: Max time to wait.
    :return: True if *predicate* became true, False on timeout.
    :rtype: bool
    """
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        _app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def run():
    """Run all checks and report pass/fail."""
    if platform.system() != "Windows":
        print("SKIPPED (Windows-only: requires real console windows)")
        return

    widget = EmbeddedConsoleWidget(["powershell.exe", "-NoLogo", "-NoExit"])
    widget.resize(600, 400)
    widget.show()

    attached = pump_until(lambda: widget._console_hwnd is not None)
    check("console window gets attached", attached, True)

    if attached:
        container_hwnd = int(widget.winId())
        actual_parent = _user32.GetParent(widget._console_hwnd)
        check(
            "embedded console's parent is this widget",
            hex(actual_parent),
            hex(container_hwnd),
        )

        widget.resize(300, 200)
        pump_until(lambda: True, timeout_secs=0.3)  # let the resize event land
        check(
            "console window survives a resize",
            bool(_user32.IsWindow(widget._console_hwnd)),
            True,
        )

    # Read the process object's own exit status (poll()) *before*
    # cleanup() drops the reference -- checking the PID afterwards via
    # OpenProcess() is unreliable because Windows can reassign a PID to
    # an unrelated process within milliseconds of the original exiting.
    child_process = widget._process
    widget.cleanup()
    check(
        "child process exited after cleanup()",
        child_process.poll() is not None if child_process else None,
        True,
    )
    check(
        "cleanup() clears the process reference",
        pump_until(lambda: widget._process is None),
        True,
    )

    print()
    if FAILURES:
        print("%d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("=" * 60)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    run()
