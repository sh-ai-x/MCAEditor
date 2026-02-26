"""
MCA Qt - xterm.js Terminal Widget.

Drop-in replacement for the old custom terminal widget. Embeds xterm.js
(the terminal emulator used by VS Code) inside a QWebEngineView, bridged
to Python via QWebChannel.  The existing TerminalBackend (pywinpty-based)
is reused unchanged — only the rendering layer is swapped out.

Architecture::

    QWebEngineView  (xterm.js renders everything)
        ↕ QWebChannel  (bidirectional bridge)
    TerminalAPI     (Python QObject with slots/signals)
        ↕ drain_buffer() polling
    TerminalBackend (existing pywinpty PTY thread — unchanged)

Dependencies:
    - PySide6 (QtWebEngineWidgets, QtWebChannel)
    - pywinpty >= 2.0.0
    - xterm.js assets in resources/terminal/
"""

import json
import os
import logging

from mca_qt.qt_compat import QWidget, QVBoxLayout, Signal, QTimer

# Module-level logger.
logger = logging.getLogger(__name__)

# --- QtWebEngine Availability Check ------------------------------------------

# QtWebEngine is only available in PySide6 (not Maya's PySide2).
# When unavailable, the terminal widget falls back to an inert stub
# that does nothing — the terminal menu item simply won't work.
try:
    from PySide6.QtCore import QObject, Slot, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebChannel import QWebChannel
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False
    logger.info("QtWebEngine not available — integrated terminal disabled")

# pywinpty backend (optional — disabled gracefully if missing).
from mca_qt.widgets.terminal_backend import TerminalBackend, HAS_CONPTY

# Path to the bundled xterm.js HTML page.
_RESOURCES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "resources", "terminal"
)
_INDEX_HTML = os.path.join(_RESOURCES_DIR, "index.html")


# =============================================================================
# TerminalAPI — QWebChannel Bridge
# =============================================================================

# Only define the bridge class when QtWebEngine is available.
# In Maya (PySide2), the entire xterm.js path is skipped.
if HAS_WEBENGINE:

    class TerminalAPI(QObject):
        """
        Bridge object exposed to JavaScript via QWebChannel.

        Provides bidirectional communication between xterm.js (running inside
        QWebEngineView) and the Python TerminalBackend.

        Signals (Python → JS):
            - ``dataReceived(str)`` — PTY output forwarded to xterm.js for display.

        Slots (JS → Python):
            - ``write(str)``         — User keyboard input from xterm.js.
            - ``resize(int, int)``   — Terminal dimensions changed (cols, rows).
            - ``ready(int, int)``    — JS side is fully initialized.
        """

        # Emitted to push PTY output to xterm.js for rendering.
        dataReceived = Signal(str)

        # Emitted when the JS side reports it is fully initialized.
        jsReady = Signal(int, int)

        def __init__(self, parent=None):
            """
            Initialize the terminal API bridge.

            :param QObject parent: Optional parent.
            """
            super().__init__(parent)

            # Callbacks set by the owning TerminalWidget.
            self._write_callback = None
            self._resize_callback = None

        @Slot(str)
        def write(self, data):
            """
            Receive user input from xterm.js and forward to the PTY.

            Called by JavaScript when the user types in the terminal.

            :param str data: Raw input string from xterm.js onData().
            """
            if self._write_callback:
                self._write_callback(data)

        @Slot(int, int)
        def resize(self, cols, rows):
            """
            Receive terminal dimension changes from xterm.js FitAddon.

            Called by JavaScript when xterm.js detects a resize.

            :param int cols: New column count.
            :param int rows: New row count.
            """
            if self._resize_callback:
                self._resize_callback(cols, rows)

        @Slot(int, int)
        def ready(self, cols, rows):
            """
            Receive initialization-complete notification from JavaScript.

            Called once when xterm.js and QWebChannel are both fully wired up.

            :param int cols: Initial column count.
            :param int rows: Initial row count.
            """
            self.jsReady.emit(cols, rows)


# =============================================================================
# TerminalWidget — Drop-in replacement
# =============================================================================

class TerminalWidget(QWidget):
    """
    Embeddable terminal emulator widget using xterm.js + QWebEngineView.

    Same public API as the old QPlainTextEdit-based widget so it can be
    swapped in without changes to editor_panel.py.

    :param str shell: Path to the shell executable (auto-detected if empty).
    :param str cwd: Working directory for the shell process.
    :param int font_size: Initial terminal font size.
    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the terminal title changes (via OSC escape sequence).
    title_changed = Signal(str)

    # Emitted when the PTY process exits.
    process_exited = Signal(int)

    # Emitted when the font size changes (for persistence).
    font_size_changed = Signal(int)

    def __init__(self, shell="", cwd="", font_size=12, parent=None):
        """
        Initialize the xterm.js terminal widget.

        The QWebEngineView is created and the HTML page is loaded
        immediately so Chromium can warm up before the user toggles
        the terminal visible.

        :param str shell: Shell path (auto-detected if empty).
        :param str cwd: Working directory for the shell.
        :param int font_size: Initial font size.
        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)

        self._shell = shell
        self._cwd = cwd
        self._font_size = font_size

        # PTY backend — created on start(), not in __init__().
        self._backend = None

        # Track whether the terminal process is alive.
        self._alive = False

        # Flag: JS side has reported ready.
        self._js_ready = False

        # Flag: start() was called before JS was ready.
        self._pending_start = False

        # Track the latest xterm.js dimensions so start() can use them
        # instead of hardcoded defaults.  Updated by ready() and resize().
        self._js_cols = 80
        self._js_rows = 24

        # Build the UI and begin loading the HTML page.
        self._setup_ui()

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """
        Build the widget layout and configure the QWebEngineView.

        Loads the xterm.js HTML page and sets up the QWebChannel bridge.
        When QtWebEngine is not available (e.g. inside Maya), creates
        an empty layout — the terminal simply won't be usable.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Drain timer — polls the backend's thread-safe buffer at ~60fps.
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(16)  # ~60fps.
        self._drain_timer.timeout.connect(self._drain_backend)

        # QtWebEngine is PySide6-only — skip setup when unavailable.
        if not HAS_WEBENGINE:
            self._web_view = None
            self._web_page = None
            self._api = None
            return

        # Create the web view that hosts xterm.js.
        self._web_view = QWebEngineView()
        self._web_page = self._web_view.page()

        # Enable JavaScript and local content access.
        settings = self._web_page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        # Set up the QWebChannel for Python ↔ JS communication.
        self._channel = QWebChannel()
        self._api = TerminalAPI(self)
        self._api._write_callback = self._on_js_write
        self._api._resize_callback = self._on_js_resize
        self._api.jsReady.connect(self._on_js_ready)
        self._channel.registerObject("termAPI", self._api)
        self._web_page.setWebChannel(self._channel)

        # Load the xterm.js HTML page from the local filesystem.
        url = QUrl.fromLocalFile(_INDEX_HTML)
        self._web_view.load(url)
        logger.debug("Loading xterm.js from: %s", _INDEX_HTML)

        layout.addWidget(self._web_view)

    # --- Process Lifecycle ---------------------------------------------------

    def start(self):
        """
        Start the terminal by spawning the PTY process.

        If the JS side is not yet ready, defers the actual spawn until
        the ``ready()`` callback fires. This prevents a race condition
        where PTY output would be lost before xterm.js can display it.
        """
        if self._alive:
            return

        # Guard: both QtWebEngine and pywinpty must be available.
        if not HAS_WEBENGINE or not HAS_CONPTY:
            logger.info("Terminal unavailable (WebEngine=%s, ConPTY=%s)",
                         HAS_WEBENGINE, HAS_CONPTY)
            return

        if not self._js_ready:
            # JS is still loading — defer start until ready() fires.
            self._pending_start = True
            logger.debug("start() deferred — waiting for JS ready")
            return

        # JS is ready — spawn the backend with the latest known dimensions.
        self._do_start(self._js_cols, self._js_rows)

    def _do_start(self, cols, rows):
        """
        Actually create the backend and start the PTY process.

        Called either from ``start()`` (if JS is ready) or from the
        ``_on_js_ready()`` callback (if start was deferred).

        :param int cols: Initial column count from xterm.js.
        :param int rows: Initial row count from xterm.js.
        """
        # Apply the configured font size to xterm.js before spawning.
        self._run_js("setFontSize({})".format(self._font_size))

        # Create and wire up the backend.
        self._backend = TerminalBackend(
            shell=self._shell,
            cwd=self._cwd,
            rows=rows,
            cols=cols,
            parent=self,
        )
        self._backend.process_exited.connect(self._on_process_exited)

        # Start the backend thread.
        self._backend.start()
        self._alive = True

        # Begin polling the backend buffer.
        self._drain_timer.start()

        logger.info("Terminal started: %dx%d", cols, rows)

    def terminate(self):
        """
        Stop the PTY process and clean up.

        Safe to call multiple times.
        """
        self._drain_timer.stop()
        if self._backend:
            self._backend.terminate()
            self._backend = None
        self._alive = False

    def is_alive(self):
        """
        Check whether the PTY process is still running.

        :return: True if the terminal process is active.
        :rtype: bool
        """
        return self._alive

    def restart(self):
        """Terminate the current session and start a new one."""
        self.terminate()
        self.clear()
        # Small delay to let the old process clean up.
        QTimer.singleShot(100, self.start)

    # --- Data Flow -----------------------------------------------------------

    def _drain_backend(self):
        """
        Poll the backend's thread-safe buffer and push data to xterm.js.

        Called by the drain timer at ~60fps. Uses ``drain_buffer()`` for
        reliable cross-thread data transfer, and ``runJavaScript()`` to
        push data directly into xterm.js. This avoids QWebChannel signal
        serialization issues with ANSI control characters.
        """
        if not self._backend:
            return

        chunks = self._backend.drain_buffer()
        if not chunks:
            return

        # Concatenate all chunks and decode to string for xterm.js.
        combined = b"".join(chunks)
        text = combined.decode("utf-8", errors="replace")

        # Use json.dumps() to safely escape all control characters
        # (ESC, CR, LF, etc.) into a valid JS string literal, then
        # call term.write() directly via runJavaScript().  This is
        # more reliable than QWebChannel signal delivery for raw
        # terminal data containing ANSI escape sequences.
        js_str = json.dumps(text)
        self._web_page.runJavaScript("term.write({})".format(js_str))

    def _on_js_write(self, data):
        """
        Forward user keyboard input from xterm.js to the PTY backend.

        :param str data: Input string from xterm.js onData().
        """
        if self._backend and self._alive:
            self._backend.write(data.encode("utf-8"))

    def _on_js_resize(self, cols, rows):
        """
        Forward terminal resize from xterm.js to the PTY backend.

        Also stores the latest dimensions so start() can use them
        instead of hardcoded defaults.

        :param int cols: New column count.
        :param int rows: New row count.
        """
        # Always track the latest dimensions.
        self._js_cols = cols
        self._js_rows = rows

        if self._backend and self._alive:
            self._backend.resize(rows, cols)

    def _on_js_ready(self, cols, rows):
        """
        Handle the JavaScript-side ready notification.

        If ``start()`` was called before JS was ready, spawn the
        backend now with the actual terminal dimensions.

        :param int cols: Terminal column count from xterm.js.
        :param int rows: Terminal row count from xterm.js.
        """
        self._js_ready = True
        self._js_cols = cols
        self._js_rows = rows
        logger.info("xterm.js ready: %dx%d", cols, rows)

        if self._pending_start:
            self._pending_start = False
            self._do_start(cols, rows)

    def _on_process_exited(self, exit_code):
        """
        Handle PTY process exit.

        :param int exit_code: The child process exit code.
        """
        self._alive = False
        self._drain_timer.stop()
        self.process_exited.emit(exit_code)
        logger.info("Terminal process exited with code %d", exit_code)

    # --- Font Size -----------------------------------------------------------

    def set_font_size(self, size):
        """
        Set the terminal font size.

        :param int size: Font point size.
        """
        self._font_size = max(6, min(48, size))
        self._run_js("setFontSize({})".format(self._font_size))

    def get_font_size(self):
        """
        Get the current terminal font size.

        :return: Font point size.
        :rtype: int
        """
        return self._font_size

    # --- Clear ---------------------------------------------------------------

    def clear(self):
        """Clear the terminal screen and scrollback."""
        self._run_js("clearTerminal()")
        # Also send Ctrl+L to the shell so it redraws its prompt.
        if self._alive and self._backend:
            self._backend.write(b"\x0c")

    # --- Focus ---------------------------------------------------------------

    def setFocus(self, reason=None):
        """
        Override setFocus to direct focus to the web view and xterm.js.

        :param reason: Focus reason (optional).
        """
        self._web_view.setFocus()
        self._run_js("focusTerminal()")

    # --- Helper: Run JavaScript ----------------------------------------------

    def _run_js(self, script):
        """
        Execute a JavaScript expression in the xterm.js page.

        Only runs if the JS side has been initialized. Silently
        skips if the page is not yet ready.

        :param str script: JavaScript code to evaluate.
        """
        if self._js_ready:
            self._web_page.runJavaScript(script)
