"""
MCA Qt - Terminal Tab Panel (multi-terminal tabbed container).

A QWidget containing a QTabWidget that manages multiple independent
terminal instances.  Each tab hosts a terminal widget created by
``create_terminal_widget()`` from the terminal factory.

Layout::

    TerminalTabPanel(QWidget)
      +-- QTabWidget (closable, movable tabs)
      |     +-- Tab "Terminal 1" -> TerminalWidget
      |     +-- Tab "Terminal 2" -> TerminalWidget
      |     +-- ...
      +-- Corner widget: "+" QPushButton (add new terminal)

Terminals are created lazily — no shell processes are spawned until
the user explicitly opens a terminal tab.

Dependencies:
    - PySide6 or PySide2 (via mca_qt.qt_compat)
    - mca_qt.widgets.terminal_factory
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QTabWidget, QPushButton,
    Qt, Signal, QTimer,
)

from mca_qt.widgets.terminal_factory import create_terminal_widget

# Module-level logger.
logger = logging.getLogger(__name__)

# Counter for generating unique terminal tab names across all panels.
_next_terminal_id = 1


def _allocate_terminal_id():
    """
    Allocate a globally unique terminal tab number.

    :return: The next terminal ID.
    :rtype: int
    """
    global _next_terminal_id
    tid = _next_terminal_id
    _next_terminal_id += 1
    return tid


# =============================================================================
# TerminalTabPanel
# =============================================================================

class TerminalTabPanel(QWidget):
    """
    Multi-terminal tabbed panel.

    Manages multiple independent terminal instances in a QTabWidget
    with closable/movable tabs and a "+" button in the corner to
    create new terminals.

    Signals:
        all_terminals_closed — emitted when the last tab is closed.
            The host can use this to auto-hide the panel.

    :param str shell: Path to the shell executable (passed to each terminal).
    :param str cwd: Working directory for new terminals.
    :param int font_size: Initial font size for terminals.
    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the last terminal tab is closed.
    all_terminals_closed = Signal()

    def __init__(self, shell="", cwd="", font_size=12, parent=None):
        """
        Initialize the terminal tab panel.

        :param str shell: Shell path (auto-detected if empty).
        :param str cwd: Working directory for new terminals.
        :param int font_size: Initial font size.
        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)

        self._shell = shell
        self._cwd = cwd
        self._font_size = font_size

        # Build the UI.
        self._setup_ui()

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the tab widget and corner '+' button."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget for multiple terminal tabs.
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self.close_terminal)

        # Style the tab widget to match the dark theme.
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #969696;
                border: none;
                padding: 4px 12px;
                min-width: 80px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
                border-bottom: 2px solid #569cd6;
            }
            QTabBar::tab:hover {
                background-color: #3e3e42;
                color: #ffffff;
            }
        """)

        # "+" button in the top-right corner to add new terminals.
        add_btn = QPushButton("+")
        add_btn.setToolTip("New Terminal")
        add_btn.setFixedSize(28, 22)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #569cd6;
                border: none;
                font-size: 16px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #3e3e42;
            }
        """)
        add_btn.clicked.connect(self.add_terminal)
        self._tabs.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)

        layout.addWidget(self._tabs)

    # --- Public API ----------------------------------------------------------

    def add_terminal(self):
        """
        Create a new terminal tab, start the shell, and switch to it.

        The terminal widget is created via the factory (which selects
        xterm.js or native QPlainTextEdit depending on environment).
        Returns None if no terminal backend is available.

        :return: The new terminal widget, or None.
        :rtype: TerminalWidget or None
        """
        widget = create_terminal_widget(
            shell=self._shell,
            cwd=self._cwd,
            font_size=self._font_size,
            parent=self,
        )
        if widget is None:
            logger.warning("Cannot add terminal tab — no terminal backend available")
            return None

        # Allocate a unique tab name.
        tid = _allocate_terminal_id()
        tab_name = "Terminal {}".format(tid)

        # Update the tab title when the terminal reports a title change.
        # Capture the widget reference in the closure for correct lookup.
        widget.title_changed.connect(
            lambda title, w=widget: self._on_title_changed(w, title)
        )

        # When the terminal process exits, show it in the tab title.
        widget.process_exited.connect(
            lambda code, w=widget: self._on_process_exited(w, code)
        )

        # Add the tab and switch to it.
        index = self._tabs.addTab(widget, tab_name)
        self._tabs.setCurrentIndex(index)

        # Defer start so the QTabWidget tab bar has rendered and the
        # terminal viewport reports its true size.  A 0ms delay is too
        # short — the tab bar hasn't appeared yet, so the terminal
        # measures too many rows; when the bar renders the viewport
        # shrinks and blank scrollback lines get pushed to the top.
        QTimer.singleShot(200, widget.start)

        logger.info("Added terminal tab: %s (index %d)", tab_name, index)
        return widget

    def close_terminal(self, index):
        """
        Terminate and remove the terminal tab at the given index.

        Emits ``all_terminals_closed`` when the last tab is removed.

        :param int index: Tab index to close.
        """
        widget = self._tabs.widget(index)
        if widget is None:
            return

        # Terminate the terminal process.
        try:
            widget.terminate()
        except Exception as exc:
            logger.warning("Error terminating terminal tab %d: %s", index, exc)

        # Remove the tab and delete the widget.
        self._tabs.removeTab(index)
        widget.deleteLater()

        logger.info("Closed terminal tab at index %d (%d remaining)",
                     index, self._tabs.count())

        # Notify the host when all tabs are closed.
        if self._tabs.count() == 0:
            self.all_terminals_closed.emit()

    def has_terminals(self):
        """
        Check whether any terminal tabs are open.

        :return: True if at least one tab exists.
        :rtype: bool
        """
        return self._tabs.count() > 0

    def terminal_count(self):
        """
        Return the number of open terminal tabs.

        :return: Tab count.
        :rtype: int
        """
        return self._tabs.count()

    def ensure_terminal(self):
        """
        Ensure at least one terminal tab exists.

        If no tabs are open, creates one. Useful for panel show
        actions that need a terminal ready to go.

        :return: The current (or newly created) terminal widget.
        :rtype: TerminalWidget or None
        """
        if self._tabs.count() == 0:
            return self.add_terminal()
        return self._tabs.currentWidget()

    def focus_current(self):
        """Give keyboard focus to the currently active terminal tab."""
        widget = self._tabs.currentWidget()
        if widget is not None:
            widget.setFocus()

    def cleanup(self):
        """
        Terminate all terminal processes.

        Called by the host on application close. Safe to call multiple times.
        """
        for i in range(self._tabs.count()):
            widget = self._tabs.widget(i)
            if widget is not None:
                try:
                    widget.terminate()
                except Exception as exc:
                    logger.warning("Error cleaning up terminal tab %d: %s", i, exc)

        logger.info("Terminal tab panel cleanup: %d terminals terminated",
                     self._tabs.count())

    # --- Internal Callbacks --------------------------------------------------

    def _on_title_changed(self, widget, title):
        """
        Update the tab title when a terminal reports a new title.

        :param QWidget widget: The terminal widget.
        :param str title: The new title string.
        """
        index = self._tabs.indexOf(widget)
        if index >= 0 and title:
            # Truncate long titles for the tab label.
            display = title if len(title) <= 30 else title[:27] + "..."
            self._tabs.setTabText(index, display)

    def _on_process_exited(self, widget, exit_code):
        """
        Update the tab title when a terminal process exits.

        :param QWidget widget: The terminal widget.
        :param int exit_code: The process exit code.
        """
        index = self._tabs.indexOf(widget)
        if index >= 0:
            current_text = self._tabs.tabText(index)
            self._tabs.setTabText(index, "{} (exited)".format(current_text))
