"""
MCA Core - Terminal Panel (shell picker + embedded console).

Single right-sidebar panel: shows a "PowerShell / WSL" picker, and once
one is chosen, swaps in an EmbeddedConsoleWidget for that shell. A
small header lets the user switch back to the picker (killing the
current shell first).

The console process is created only after the user picks a shell --
NOT eagerly on plugin activation. Besides avoiding an unwanted process
launch every time the editor opens, this also sidesteps a real bug:
embedding a console into a widget that is not yet visible (e.g. a
right-panel tab the user has never clicked) gives it zero size, since
Qt has not laid the widget out yet -- the embedded console then shows
up as a blank panel. Creating it only once the user has clicked into
an already-visible panel guarantees a real size is available.

Dependencies:
    - mca_qt.qt_compat (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
      QStackedWidget, QLabel)
    - mca_core.plugins.powershell_terminal.native_console_widget
"""

import logging
import os

from mca_core import get_prefs_dir
from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget, QLabel,
)

from mca_core.plugins.powershell_terminal.native_console_widget import (
    EmbeddedConsoleWidget,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# (display label, argv builder) -- argv is built lazily so scripts_dir
# is only read when a shell is actually picked.
_SHELLS = {
    "PowerShell": lambda scripts_dir: ["powershell.exe", "-NoLogo", "-NoExit"],
    "WSL": lambda scripts_dir: ["wsl.exe", "--cd", scripts_dir],
}


class TerminalPanel(QWidget):
    """Picker + embedded console, swapped in a QStackedWidget."""

    def __init__(self, parent=None):
        """
        Build the picker page. No process is started yet.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)

        self._console = None  # EmbeddedConsoleWidget, created on pick.

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_picker_page())
        # Console page is built on demand in _pick(); index 1 is reserved
        # once it exists.

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    # --- Picker page --------------------------------------------------------

    def _build_picker_page(self):
        """
        Build the "choose a shell" page.

        :return: The picker page widget.
        :rtype: QWidget
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        layout.addWidget(QLabel("Open a terminal:", page))
        for name in _SHELLS:
            btn = QPushButton(name, page)
            btn.clicked.connect(lambda _checked=False, n=name: self._pick(n))
            layout.addWidget(btn)
        layout.addStretch()
        return page

    def _pick(self, shell_name):
        """
        Start the chosen shell and swap in its embedded console page.

        Only called from a button click, which guarantees this panel
        is already visible and laid out -- so the new console widget
        gets a real size instead of embedding at zero size.

        :param str shell_name: Key into ``_SHELLS``.
        """
        scripts_dir = os.path.join(get_prefs_dir(), "scripts")
        command = _SHELLS[shell_name](scripts_dir)

        self._console = EmbeddedConsoleWidget(command, cwd=scripts_dir)

        console_page = QWidget()
        page_layout = QVBoxLayout(console_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        header = QWidget(console_page)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.addWidget(QLabel(shell_name, header))
        header_layout.addStretch()
        switch_btn = QPushButton("↺ Switch Shell", header)
        switch_btn.clicked.connect(self._switch_back_to_picker)
        header_layout.addWidget(switch_btn)

        page_layout.addWidget(header)
        page_layout.addWidget(self._console)

        # Replace any previous console page (switching shells twice).
        if self._stack.count() > 1:
            old_page = self._stack.widget(1)
            self._stack.removeWidget(old_page)
            old_page.deleteLater()

        self._stack.addWidget(console_page)
        self._stack.setCurrentWidget(console_page)

        logger.info("Terminal panel: started %s", shell_name)

    def _switch_back_to_picker(self):
        """Kill the current shell and show the picker page again."""
        if self._console is not None:
            self._console.cleanup()
            self._console = None
        self._stack.setCurrentIndex(0)

    # --- Cleanup ----------------------------------------------------------------

    def cleanup(self):
        """Terminate the active console process, if any."""
        if self._console is not None:
            self._console.cleanup()
            self._console = None
