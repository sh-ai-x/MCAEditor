"""
MCA Qt - Bug Report & Feedback Dialog.

Modal dialog for submitting bug reports and feature feedback.  Collects
a category (Bug / Feedback), subject, and description from the user,
then opens the system's default email client pre-populated with the
report addressed to the MCA Editor support inbox.

System information (OS, Python version, app version, DCC info) is
automatically appended to the message body so the user doesn't have
to gather it manually.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - webbrowser (stdlib, for opening mailto: links)
    - platform (stdlib, for OS info)
    - sys (stdlib, for Python version)
    - urllib.parse (stdlib, for URL encoding)
"""

import logging
import platform
import sys
import webbrowser

from urllib.parse import quote

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPlainTextEdit, QComboBox,
    QPushButton, QCheckBox, QMessageBox,
    Qt,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# Support email address.
SUPPORT_EMAIL = "info@mechart.org"

# --- Styles ------------------------------------------------------------------

_INPUT_STYLE = """
    QLineEdit {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 4px 8px;
        font-size: 12px;
    }
"""

_COMBO_STYLE = """
    QComboBox {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 4px 8px;
        font-size: 12px;
        min-width: 140px;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    QComboBox QAbstractItemView {
        background-color: #2d2d30;
        color: #d4d4d4;
        selection-background-color: #094771;
        border: 1px solid #555;
    }
"""

_TEXT_EDIT_STYLE = """
    QPlainTextEdit {
        background-color: #1e1e1e;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 4px;
        font-family: Consolas, 'Courier New', monospace;
        font-size: 12px;
    }
"""

_BTN_STYLE = """
    QPushButton {
        background-color: #3c3c3c;
        color: #cccccc;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 5px 14px;
        font-size: 11px;
    }
    QPushButton:hover { background-color: #4e4e52; }
"""

_PRIMARY_BTN_STYLE = """
    QPushButton {
        background-color: #094771;
        color: #ffffff;
        border: 1px solid #094771;
        border-radius: 3px;
        padding: 5px 14px;
        font-size: 11px;
    }
    QPushButton:hover { background-color: #0e639c; }
"""

_LABEL_STYLE = "color: #bbbbbb; font-size: 11px;"

_CHECKBOX_STYLE = """
    QCheckBox {
        color: #d4d4d4;
        font-size: 11px;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 14px;
        height: 14px;
    }
"""


# --- Feedback Dialog ---------------------------------------------------------

class FeedbackDialog(QDialog):
    """
    Dialog for submitting bug reports and feature feedback.

    Collects a category, subject line, and description from the user.
    Optionally includes system information. On submit, opens the
    default email client with a pre-populated message.

    :param str app_version: The current application version string.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, app_version="", parent=None):
        """
        Initialize the feedback dialog.

        :param str app_version: Current app version for the system info block.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app_version = app_version
        self.setWindowTitle("Bug Report / Feedback")
        self.setMinimumSize(500, 460)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: category, subject, description, buttons."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 12, 16, 12)

        # --- Header ---
        header = QLabel("<b>Send Bug Report or Feedback</b>")
        header.setStyleSheet("color: #d4d4d4; font-size: 13px;")
        layout.addWidget(header)

        subtitle = QLabel(
            "Your default email client will open with the report "
            "pre-filled. Review and send from there."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(subtitle)

        # --- Form fields ---
        form = QFormLayout()
        form.setSpacing(8)

        # Category selector (Bug Report vs Feedback).
        self._category_combo = QComboBox()
        self._category_combo.addItems(["Bug Report", "Feature Request", "General Feedback"])
        self._category_combo.setStyleSheet(_COMBO_STYLE)
        form.addRow(self._make_label("Type:"), self._category_combo)

        # Subject line.
        self._subject_edit = QLineEdit()
        self._subject_edit.setPlaceholderText("Brief summary of the issue or suggestion")
        self._subject_edit.setStyleSheet(_INPUT_STYLE)
        form.addRow(self._make_label("Subject:"), self._subject_edit)

        layout.addLayout(form)

        # Description text area.
        desc_label = QLabel("Description:")
        desc_label.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(desc_label)

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText(
            "Describe the bug or your suggestion in detail...\n\n"
            "For bugs, include:\n"
            "  - Steps to reproduce\n"
            "  - What you expected to happen\n"
            "  - What actually happened"
        )
        self._desc_edit.setStyleSheet(_TEXT_EDIT_STYLE)
        self._desc_edit.setMinimumHeight(180)
        self._desc_edit.setTabStopDistance(28.0)
        layout.addWidget(self._desc_edit)

        # Include system info checkbox.
        self._sysinfo_cb = QCheckBox("Include system information (OS, Python version, app version)")
        self._sysinfo_cb.setStyleSheet(_CHECKBOX_STYLE)
        self._sysinfo_cb.setChecked(True)
        self._sysinfo_cb.setToolTip(
            "Attaches OS version, Python version, and MCA Editor version\n"
            "to the email body. Helps diagnose issues faster."
        )
        layout.addWidget(self._sysinfo_cb)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        send_btn = QPushButton("Open Email...")
        send_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        send_btn.setDefault(True)
        send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(send_btn)

        layout.addLayout(btn_layout)

    # --- Helpers --------------------------------------------------------------

    def _make_label(self, text):
        """
        Create a styled form label.

        :param str text: Label text.
        :return: Styled QLabel.
        :rtype: QLabel
        """
        label = QLabel(text)
        label.setStyleSheet(_LABEL_STYLE)
        return label

    def _gather_system_info(self):
        """
        Collect system information for the report.

        Gathers OS, Python version, app version, and DCC info if
        available from the Maya adapter.

        :return: Formatted system info string.
        :rtype: str
        """
        lines = []
        lines.append("--- System Information ---")
        lines.append("OS: {} {}".format(platform.system(), platform.version()))
        lines.append("Platform: {}".format(platform.platform()))
        lines.append("Python: {}".format(sys.version.split()[0]))
        lines.append("MCA Editor: v{}".format(self._app_version))

        # Try to get DCC info if running inside Maya.
        try:
            import maya.cmds as cmds
            maya_ver = cmds.about(version=True)
            lines.append("Maya: {}".format(maya_ver))
        except ImportError:
            lines.append("DCC: Standalone")

        return "\n".join(lines)

    # --- Send -----------------------------------------------------------------

    def _on_send(self):
        """
        Build the mailto: URL and open the user's default email client.

        Validates that the subject and description are not empty before
        proceeding. Constructs a mailto: link with the subject, category
        prefix, and formatted body.
        """
        subject_text = self._subject_edit.text().strip()
        desc_text = self._desc_edit.toPlainText().strip()

        # Require at least a subject.
        if not subject_text:
            QMessageBox.warning(
                self, "Missing Subject",
                "Please enter a subject for your report."
            )
            self._subject_edit.setFocus()
            return

        # Require a description.
        if not desc_text:
            QMessageBox.warning(
                self, "Missing Description",
                "Please enter a description of the issue or suggestion."
            )
            self._desc_edit.setFocus()
            return

        # Build the email subject with category prefix.
        category = self._category_combo.currentText()
        email_subject = "[MCA Editor - {}] {}".format(category, subject_text)

        # Build the email body.
        body_parts = [desc_text]

        # Append system info if the checkbox is checked.
        if self._sysinfo_cb.isChecked():
            body_parts.append("")
            body_parts.append(self._gather_system_info())

        email_body = "\n".join(body_parts)

        # Build the mailto: URL with encoded subject and body.
        mailto_url = "mailto:{}?subject={}&body={}".format(
            SUPPORT_EMAIL,
            quote(email_subject),
            quote(email_body),
        )

        # Open the default email client.
        logger.info("Opening email client for %s report", category.lower())
        webbrowser.open(mailto_url)

        # Accept the dialog to close it.
        self.accept()
