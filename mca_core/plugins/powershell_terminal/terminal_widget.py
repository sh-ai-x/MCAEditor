"""
MCA Core - PowerShell Terminal Widget.

Simple QProcess-backed PowerShell panel: no PTY, no ANSI/VT100 parsing.
Runs powershell.exe as a child process, shows merged stdout/stderr in a
read-only QPlainTextEdit, and sends typed commands from a single-line
QLineEdit.

Deliberately minimal: this trades full terminal emulation (colors,
cursor movement, full-screen TUI apps like vim/htop) for a much smaller
surface area than the PTY + custom ANSI parser terminal MCA Editor
shipped through v1.0.31 and removed in v1.0.32 after a long history of
crashes, zombie processes, and render freezes (see the v1.0.32 changelog
entry and Docs/terminal_factory.py). Ordinary commands (dir, git,
running a script) work fine.

Dependencies:
    - mca_qt.qt_compat (QProcess, QPlainTextEdit, QLineEdit, QTextCursor)

Side Effects:
    - Spawns a powershell.exe child process on widget creation.
    - Terminates that process in cleanup().
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QPlainTextEdit, QLineEdit, QProcess, QTextCursor,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# Sent as the first command so PowerShell's console codepage is UTF-8.
# Without this, non-ASCII output (e.g. Korean) renders as mojibake because
# the legacy Windows console host defaults to the OEM codepage.
_INIT_COMMAND = "chcp 65001 > $null\n"

# How long to wait (ms) for powershell.exe to start / exit before giving up.
_START_TIMEOUT_MS = 5000
_STOP_TIMEOUT_MS = 2000


class PowerShellTerminalWidget(QWidget):
    """
    Minimal PowerShell panel: scrollback output view + single-line input.

    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, parent=None):
        """
        Build the panel and start the PowerShell child process.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)

        self._process = None

        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(5000)
        self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText("PowerShell command...")
        self._input.returnPressed.connect(self._on_submit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self._output)
        layout.addWidget(self._input)

        self._start_process()

    # --- Process lifecycle ----------------------------------------------------

    def _start_process(self):
        """Spawn the powershell.exe child process and wire up its signals."""
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)

        self._process.start(
            "powershell.exe",
            ["-NoLogo", "-NoExit", "-Command", "-"],
        )
        if not self._process.waitForStarted(_START_TIMEOUT_MS):
            self._append_text("[powershell.exe failed to start]\n")
            logger.warning("powershell.exe failed to start within %dms", _START_TIMEOUT_MS)
            return

        self._process.write(_INIT_COMMAND.encode("utf-8"))

    def _on_output(self):
        """Read available bytes from the process and append as text."""
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput())
        self._append_text(data.decode("utf-8", errors="replace"))

    def _on_finished(self, exit_code, exit_status):
        """Note that the shell exited; the panel stays open so output stays readable."""
        self._append_text("\n[process exited, code {}]\n".format(exit_code))

    def _on_submit(self):
        """Echo and send the typed command to the running shell."""
        command = self._input.text()
        self._input.clear()

        if self._process is None or self._process.state() != QProcess.ProcessState.Running:
            self._append_text("[not connected]\n")
            return

        self._append_text("> {}\n".format(command))
        self._process.write((command + "\n").encode("utf-8"))

    def _append_text(self, text):
        """
        Append text to the output view and scroll to the bottom.

        :param str text: Text to append.
        """
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    # --- Cleanup ----------------------------------------------------------------

    def cleanup(self):
        """
        Terminate the PowerShell child process.

        Called by the plugin's ``deactivate()`` so the process doesn't
        linger as a zombie after the panel is removed or the editor closes.
        """
        if self._process is None:
            return
        if self._process.state() == QProcess.ProcessState.Running:
            self._process.kill()
            self._process.waitForFinished(_STOP_TIMEOUT_MS)
        self._process = None
