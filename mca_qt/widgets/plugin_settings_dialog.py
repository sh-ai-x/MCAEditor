"""
MCA Editor - Plugin Settings Dialog.

Simple dialog for viewing installed plugins and toggling them on/off.
Accessed via Plugins > Plugin Settings in the menu bar.

Layout::

    PluginSettingsDialog (QDialog)
      +-- QHBoxLayout
            +-- Left: QListWidget (plugin list, grouped by Bundled / Installed)
            +-- Right: QVBoxLayout (plugin details + enable/disable button)

Dependencies:
    - PySide6 (QDialog, QListWidget, etc.)

Side Effects:
    - Reads and writes ``disabled_plugins`` setting via PluginManager.
"""

import os
import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QListWidget, QListWidgetItem, QLabel, QPushButton,
    QGroupBox, QFrame,
    Qt, QSize,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Dialog Dimensions -------------------------------------------------------

DIALOG_MIN_WIDTH = 600
DIALOG_MIN_HEIGHT = 400


# =============================================================================
# Plugin Settings Dialog
# =============================================================================

class PluginSettingsDialog(QDialog):
    """
    Dialog for managing MCA Editor plugins.

    Shows a list of all discovered plugins (bundled and user-installed)
    with enable/disable controls and plugin metadata display.

    :param PluginManager plugin_manager: The plugin manager instance.
    :param MCASettings settings: The application settings instance.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, plugin_manager, settings, parent=None):
        """
        Initialize the plugin settings dialog.

        :param PluginManager plugin_manager: The plugin manager.
        :param MCASettings settings: Application settings.
        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        self._settings = settings

        self.setWindowTitle("Plugin Settings")
        self.setMinimumSize(QSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT))

        # Apply dark theme styling consistent with the rest of the editor.
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #cccccc;
            }
            QListWidget {
                background-color: #252526;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 6px;
            }
            QListWidget::item:selected {
                background-color: #094771;
            }
            QLabel {
                color: #cccccc;
            }
            QPushButton {
                background-color: #0e639c;
                color: #ffffff;
                border: none;
                padding: 6px 16px;
                font-size: 12px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:disabled {
                background-color: #3c3c3c;
                color: #666666;
            }
            QGroupBox {
                border: 1px solid #3c3c3c;
                margin-top: 10px;
                padding-top: 16px;
                color: #cccccc;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)

        self._build_ui()
        self._populate_plugin_list()

    def _build_ui(self):
        """Build the dialog UI layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --- Left panel: Plugin list ---
        left_layout = QVBoxLayout()

        list_label = QLabel("Plugins")
        list_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 4px;")
        left_layout.addWidget(list_label)

        self._plugin_list = QListWidget()
        self._plugin_list.setMinimumWidth(200)
        self._plugin_list.currentRowChanged.connect(self._on_plugin_selected)
        left_layout.addWidget(self._plugin_list)

        # "Open Plugins Folder" button below the list.
        open_folder_btn = QPushButton("Open Plugins Folder")
        open_folder_btn.clicked.connect(self._open_plugins_folder)
        open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
            }
            QPushButton:hover {
                background-color: #4e4e4e;
            }
        """)
        left_layout.addWidget(open_folder_btn)

        layout.addLayout(left_layout, 1)

        # --- Right panel: Plugin details ---
        right_layout = QVBoxLayout()

        # Plugin name header.
        self._name_label = QLabel("")
        self._name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        right_layout.addWidget(self._name_label)

        # Version and author.
        self._version_label = QLabel("")
        self._version_label.setStyleSheet("font-size: 12px; color: #999999;")
        right_layout.addWidget(self._version_label)

        # Separator line.
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #3c3c3c;")
        right_layout.addWidget(line)

        # Description.
        self._description_label = QLabel("")
        self._description_label.setWordWrap(True)
        self._description_label.setStyleSheet("font-size: 12px; margin-top: 8px;")
        right_layout.addWidget(self._description_label)

        # Status indicator.
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 12px; margin-top: 12px; font-weight: bold;")
        right_layout.addWidget(self._status_label)

        # Type indicator (bundled vs installed).
        self._type_label = QLabel("")
        self._type_label.setStyleSheet("font-size: 11px; color: #888888;")
        right_layout.addWidget(self._type_label)

        right_layout.addStretch()

        # Enable / Disable button.
        self._toggle_btn = QPushButton("Enable")
        self._toggle_btn.clicked.connect(self._toggle_plugin)
        right_layout.addWidget(self._toggle_btn)

        # Close button.
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
            }
            QPushButton:hover {
                background-color: #4e4e4e;
            }
        """)
        right_layout.addWidget(close_btn)

        layout.addLayout(right_layout, 2)

    def _populate_plugin_list(self):
        """
        Fill the plugin list widget with all discovered plugins.

        Groups plugins by Bundled and Installed (user) categories.
        """
        self._plugin_list.clear()
        self._plugin_data = []

        plugins = self._plugin_manager.list_plugins()

        # Separate bundled from user plugins.
        bundled = [p for p in plugins if p.get("bundled")]
        user = [p for p in plugins if not p.get("bundled")]

        # Add bundled plugins section.
        if bundled:
            header = QListWidgetItem("-- Bundled --")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(Qt.GlobalColor.gray)
            self._plugin_list.addItem(header)
            self._plugin_data.append(None)

            for plugin in bundled:
                status = "Active" if plugin["active"] else "Disabled"
                item = QListWidgetItem("  {} [{}]".format(plugin["name"], status))
                self._plugin_list.addItem(item)
                self._plugin_data.append(plugin)

        # Add user plugins section.
        if user:
            header = QListWidgetItem("-- Installed --")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(Qt.GlobalColor.gray)
            self._plugin_list.addItem(header)
            self._plugin_data.append(None)

            for plugin in user:
                status = "Active" if plugin["active"] else "Disabled"
                item = QListWidgetItem("  {} [{}]".format(plugin["name"], status))
                self._plugin_list.addItem(item)
                self._plugin_data.append(plugin)

        # Show placeholder if no plugins found.
        if not bundled and not user:
            item = QListWidgetItem("No plugins installed")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._plugin_list.addItem(item)
            self._plugin_data.append(None)

        # Clear the details panel.
        self._clear_details()

    def _on_plugin_selected(self, row):
        """
        Update the details panel when a plugin is selected.

        :param int row: The selected row index in the list.
        """
        if row < 0 or row >= len(self._plugin_data):
            self._clear_details()
            return

        plugin = self._plugin_data[row]
        if plugin is None:
            # Header row selected — clear details.
            self._clear_details()
            return

        # Populate detail fields.
        self._name_label.setText(plugin.get("name", "Unknown"))

        version_text = "v{}".format(plugin.get("version", "?"))
        author = plugin.get("author", "")
        if author:
            version_text += "  by {}".format(author)
        self._version_label.setText(version_text)

        self._description_label.setText(
            plugin.get("description", "No description available.")
        )

        # Status.
        if plugin.get("active"):
            self._status_label.setText("Status: Active")
            self._status_label.setStyleSheet(
                "font-size: 12px; margin-top: 12px; font-weight: bold; color: #4ec9b0;"
            )
            self._toggle_btn.setText("Disable")
        else:
            self._status_label.setText("Status: Disabled")
            self._status_label.setStyleSheet(
                "font-size: 12px; margin-top: 12px; font-weight: bold; color: #999999;"
            )
            self._toggle_btn.setText("Enable")

        # Type.
        if plugin.get("bundled"):
            self._type_label.setText("Type: Bundled (built-in)")
        else:
            self._type_label.setText("Type: Installed (user)")

        self._toggle_btn.setEnabled(True)
        self._toggle_btn.setProperty("plugin_id", plugin.get("id"))

    def _clear_details(self):
        """Clear the plugin details panel."""
        self._name_label.setText("Select a plugin")
        self._version_label.setText("")
        self._description_label.setText("")
        self._status_label.setText("")
        self._type_label.setText("")
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.setText("Enable")

    def _toggle_plugin(self):
        """Enable or disable the currently selected plugin."""
        plugin_id = self._toggle_btn.property("plugin_id")
        if not plugin_id:
            return

        # Find the current plugin data.
        current_row = self._plugin_list.currentRow()
        if current_row < 0 or current_row >= len(self._plugin_data):
            return
        plugin = self._plugin_data[current_row]
        if plugin is None:
            return

        if plugin.get("active"):
            # Disable the plugin.
            self._plugin_manager.disable_plugin(plugin_id)
            logger.info("Disabled plugin: %s", plugin_id)
        else:
            # Enable the plugin.
            self._plugin_manager.enable_plugin(plugin_id)
            logger.info("Enabled plugin: %s", plugin_id)

        # Refresh the list to show updated status.
        self._populate_plugin_list()

        # Re-select the same plugin by ID.
        for i, data in enumerate(self._plugin_data):
            if data and data.get("id") == plugin_id:
                self._plugin_list.setCurrentRow(i)
                break

    def _open_plugins_folder(self):
        """Open the user plugins directory in the system file explorer."""
        user_dir = os.path.join(
            os.path.expanduser("~"), "Documents", "mca_preferences", "plugins"
        )
        # Create the directory if it doesn't exist yet.
        os.makedirs(user_dir, exist_ok=True)

        # Open in the system file explorer.
        if os.name == "nt":
            os.startfile(user_dir)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", user_dir])

    def keyPressEvent(self, event):
        """
        Handle key press events.

        Escape closes the dialog.

        :param QKeyEvent event: The key event.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)
