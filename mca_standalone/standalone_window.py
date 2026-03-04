"""
MCA Standalone - Standalone Window.

QMainWindow wrapper around MCAEditorPanel for standalone desktop use.
Provides the menu bar, status bar (with cursor position, language,
encoding, and mode indicators), window geometry save/restore, and
unsaved-changes check on close.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_qt.editor_panel (MCAEditorPanel)
    - mca_core.config.settings (MCASettings)
"""

import logging
import struct
import sys

from mca_qt.qt_compat import (
    QMainWindow, QStatusBar, QLabel, QMessageBox,
)
from mca_qt.editor_panel import MCAEditorPanel
from mca_core.config.settings import MCASettings

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Standalone Window ------------------------------------------------------

class StandaloneWindow(QMainWindow):
    """
    Standalone application window wrapping MCAEditorPanel.

    Adds QMainWindow chrome that the panel itself does not own:
    menu bar, status bar (with pos/lang/encoding/mode labels),
    window geometry persistence, and unsaved-changes close guard.

    :param MCASettings settings: Application settings instance.
    """

    def __init__(self, settings):
        """
        Initialize the standalone window and embed the editor panel.

        :param MCASettings settings: Application settings instance.
        """
        super().__init__()
        self._settings = settings

        self.setWindowTitle("MCA Editor")
        self.setMinimumSize(900, 600)
        self.resize(1400, 850)

        # --- Editor panel (the real content) ---
        self._panel = MCAEditorPanel(settings, parent=self)
        self.setCentralWidget(self._panel)

        # --- Menu bar (populated by the panel) ---
        self._panel.build_menus(self.menuBar())

        # --- Status bar ---
        self._setup_statusbar()

        # --- Connect panel signals to status bar ---
        self._panel.status_message.connect(self._on_status_message)
        self._panel.cursor_position_changed.connect(self._on_cursor_pos)
        self._panel.language_changed.connect(self._on_language_changed)
        self._panel.mode_changed.connect(self._on_mode_changed)
        self._panel.output_counts_changed.connect(self._on_counts_changed)
        self._panel.index_status_changed.connect(self._on_index_status)

        # Restore saved geometry if available.
        self._restore_geometry()

    # --- Status Bar Setup ---------------------------------------------------

    def _setup_statusbar(self):
        """Build the status bar with Python version, error/warning counts, cursor position, language, encoding, and mode."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # Shared style for all status bar labels.
        label_style = "color: white; padding: 0 8px; font-size: 11px;"

        # --- Left-aligned widgets (addWidget) ---

        # Python version (static, set once at startup).
        bits = struct.calcsize("P") * 8
        py_ver = "Python {}.{}.{} ({}-bit)".format(*sys.version_info[:3], bits)
        py_label = QLabel(py_ver)
        py_label.setStyleSheet(label_style)
        self._statusbar.addWidget(py_label)

        # Error count indicator (circled-X symbol).
        self._error_label = QLabel("\u2297 0")
        self._error_label.setStyleSheet(label_style)
        self._statusbar.addWidget(self._error_label)

        # Warning count indicator (warning triangle symbol).
        self._warning_label = QLabel("\u26a0 0")
        self._warning_label.setStyleSheet(label_style)
        self._statusbar.addWidget(self._warning_label)

        # Symbol index status indicator — shows indexing progress or final count.
        self._index_label = QLabel("")
        self._index_label.setStyleSheet(label_style)
        self._statusbar.addWidget(self._index_label)

        # --- Right-aligned widgets (addPermanentWidget) ---

        # Cursor position display.
        self._pos_label = QLabel("Ln 1, Col 1")
        self._pos_label.setStyleSheet(label_style)
        self._statusbar.addPermanentWidget(self._pos_label)

        # Current language display.
        self._lang_label = QLabel("Python")
        self._lang_label.setStyleSheet(label_style)
        self._statusbar.addPermanentWidget(self._lang_label)

        # Encoding display (always UTF-8 for now).
        encoding_label = QLabel("UTF-8")
        encoding_label.setStyleSheet(label_style)
        self._statusbar.addPermanentWidget(encoding_label)

        # Project indicator (shows project name or "No Project").
        self._mode_label = QLabel("No Project")
        self._mode_label.setStyleSheet(label_style)
        self._statusbar.addPermanentWidget(self._mode_label)

    # --- Signal Handlers ----------------------------------------------------

    def _on_status_message(self, message, duration_ms):
        """
        Show a status message in the status bar.

        :param str message: The message text.
        :param int duration_ms: Display duration in milliseconds.
        """
        self._statusbar.showMessage(message, duration_ms)

    def _on_cursor_pos(self, line, col):
        """
        Update the cursor position label.

        :param int line: Current line number (1-based).
        :param int col: Current column number (1-based).
        """
        self._pos_label.setText("Ln {}, Col {}".format(line, col))

    def _on_language_changed(self, language):
        """
        Update the language label in the status bar.

        :param str language: The display name of the current language.
        """
        self._lang_label.setText(language)

    def _on_mode_changed(self, mode_label):
        """
        Update the title bar and status bar project indicator.

        :param str mode_label: Project name when active, empty string when idle.
        """
        if mode_label:
            self.setWindowTitle("MCA Editor -- {}".format(mode_label))
            self._mode_label.setText(mode_label)
        else:
            self.setWindowTitle("MCA Editor")
            self._mode_label.setText("No Project")

    def _on_counts_changed(self, errors, warnings):
        """
        Update the error and warning count labels in the status bar.

        :param int errors: Current error count.
        :param int warnings: Current warning count.
        """
        self._error_label.setText("\u2297 {}".format(errors))
        self._warning_label.setText("\u26a0 {}".format(warnings))

    def _on_index_status(self, text):
        """
        Update the symbol index indicator in the status bar.

        :param str text: Status text (e.g. "Indexing 45%", "Indexed 120 files", or "" to clear).
        """
        self._index_label.setText(text)

    # --- Geometry Save/Restore ----------------------------------------------

    def _restore_geometry(self):
        """Restore window geometry and state from saved settings."""
        geometry = self._settings.get("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self._settings.get("window_state")
        if state:
            self.restoreState(state)

    # --- Close Event --------------------------------------------------------

    def closeEvent(self, event):
        """
        Save state on close and check for unsaved changes.

        :param QCloseEvent event: The close event.
        """
        # Check for unsaved changes across all tabs.
        if self._panel.check_unsaved_changes():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        # Persist window geometry and state.
        self._settings.set("window_geometry", self.saveGeometry())
        self._settings.set("window_state", self.saveState())

        # Save panel state (splitter sizes, etc.).
        self._panel.save_window_state(self._settings)

        # Clean up DCC connections.
        self._panel.cleanup()

        logger.info("MCA Editor closing")
        event.accept()
