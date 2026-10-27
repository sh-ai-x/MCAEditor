"""
Smoke test for the PowerShell Terminal plugin's widget.

Spawns a real powershell.exe child process (no DCC involved), sends a
few commands through the same code path the UI uses, and checks that
output (including non-ASCII text) comes back and that cleanup() does
not leave the process running.

Runs headless -- no DCC, no user settings touched. Windows-only, since
it exercises powershell.exe directly.

Usage:
    python tests/test_powershell_terminal.py
"""

import os
import platform
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Run from anywhere -- resolve the project root relative to this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mca_qt.qt_compat import QApplication, QProcess
from mca_core.plugins.powershell_terminal.terminal_widget import PowerShellTerminalWidget

# A single QApplication serves every check.
_app = QApplication.instance() or QApplication(sys.argv)

# Labels of checks that did not match, reported together at the end.
FAILURES = []


def check(label, got, want_substring):
    """
    Assert that *want_substring* appears in *got* and record the outcome.

    :param str label: Human-readable description of the check.
    :param str got: Actual text collected from the terminal.
    :param str want_substring: Substring that must appear in *got*.
    """
    if want_substring in got:
        print("PASS   %s" % label)
        return
    print("FAIL   %s" % label)
    print("         want substring: %r" % want_substring)
    print("         got           : %r" % got)
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
        print("SKIPPED (Windows-only: requires powershell.exe)")
        return

    widget = PowerShellTerminalWidget()

    started = pump_until(
        lambda: widget._process is not None
        and widget._process.state() == QProcess.ProcessState.Running
    )
    check("powershell.exe starts", "yes" if started else "no", "yes")

    # --- ASCII round trip ---------------------------------------------------
    widget._input.setText("Write-Output mca-terminal-ascii-check")
    widget._on_submit()
    pump_until(lambda: "mca-terminal-ascii-check" in widget._output.toPlainText())
    check(
        "ASCII command output appears in the panel",
        widget._output.toPlainText(),
        "mca-terminal-ascii-check",
    )

    # --- Non-ASCII (Korean) round trip --------------------------------------
    # Exercises the chcp 65001 init command -- without it this renders as
    # mojibake instead of the original characters.
    widget._input.setText("Write-Output 한글테스트")
    widget._on_submit()
    pump_until(lambda: "한글테스트" in widget._output.toPlainText())
    check(
        "Korean command output decodes correctly",
        widget._output.toPlainText(),
        "한글테스트",
    )

    # --- Cleanup terminates the child process, no zombie left behind -------
    widget.cleanup()
    stopped = pump_until(lambda: widget._process is None)
    check("cleanup() clears the process reference", "yes" if stopped else "no", "yes")

    print()
    if FAILURES:
        print("%d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("=" * 60)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    run()
