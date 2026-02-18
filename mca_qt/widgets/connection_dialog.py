"""
MCA Qt - DCC Connection Dialog.

Dialog for connecting to a DCC application. Presents a dropdown of
registered adapters, host/port fields, and auto-detection results.

Extracted from the original main_window.py for reuse in both standalone
and embedded modes.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_core.adapters (AdapterManager)
"""

import logging

from mca_qt.qt_compat import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QSpinBox,
    QDialogButtonBox, QLabel,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Connection Dialog ------------------------------------------------------

class ConnectionDialog(QDialog):
    """
    Dialog for connecting to a DCC application.

    Presents a dropdown of registered adapters (Maya-only for now),
    host/port fields, and auto-detection results.

    :param AdapterManager adapter_manager: The adapter manager instance.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, adapter_manager, parent=None):
        """
        Initialize the connection dialog.

        :param AdapterManager adapter_manager: The adapter manager.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Connect to DCC Application")
        self.setMinimumWidth(350)
        self._adapter_manager = adapter_manager
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: DCC selection, host, port, buttons."""
        layout = QFormLayout(self)
        layout.setSpacing(8)

        # DCC application dropdown (shows connection status).
        self._dcc_combo = QComboBox()
        for dcc_type, adapter in self._adapter_manager.get_all_adapters().items():
            status = " [Connected]" if adapter.is_connected else ""
            self._dcc_combo.addItem(
                "{}{}".format(adapter.display_name, status),
                dcc_type
            )
        layout.addRow("Application:", self._dcc_combo)

        # Host input field.
        self._host_input = QLineEdit("localhost")
        layout.addRow("Host:", self._host_input)

        # Port input with auto-update when DCC selection changes.
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(7001)
        self._dcc_combo.currentIndexChanged.connect(self._on_dcc_changed)
        self._on_dcc_changed(0)
        layout.addRow("Port:", self._port_input)

        # Show auto-detected DCC processes.
        detected = self._adapter_manager.detect_running_dccs()
        if detected:
            names = ", ".join(d["name"] for d in detected)
            detect_label = QLabel("Detected: {}".format(names))
            detect_label.setStyleSheet("color: #4ec9b0; font-size: 11px;")
            layout.addRow("", detect_label)

        # OK/Cancel buttons.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_dcc_changed(self, index):
        """
        Update the port field when the DCC selection changes.

        :param int index: The new combo box index.
        """
        dcc_type = self._dcc_combo.currentData()
        adapter = self._adapter_manager.get_adapter(dcc_type)
        if adapter:
            self._port_input.setValue(adapter.default_port)

    def get_connection_info(self):
        """
        Get the user's connection settings.

        :return: Dict with 'dcc_type', 'host', and 'port' keys.
        :rtype: dict
        """
        return {
            "dcc_type": self._dcc_combo.currentData(),
            "host": self._host_input.text(),
            "port": self._port_input.value(),
        }
