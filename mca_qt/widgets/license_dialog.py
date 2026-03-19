"""
MCA Qt - License Key Dialog.

Modal dialog for entering and validating a license key.  Shows the
current license status (trial info or masked active key) and provides
a QLineEdit with an input mask that enforces the MCA-XXXX-XXXX-XXXX-XXXX
format automatically.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_core.license (validate_key, store_license_key, check_license)
"""

import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QLabel, QDialogButtonBox, Qt,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- License Dialog ---------------------------------------------------------

class LicenseDialog(QDialog):
    """
    Dialog for viewing license status and entering a license key.

    Displays the current license state (licensed, trial, or expired) and
    provides a masked input field for entering a new key.  Validates on
    submit and stores the key if valid.

    :param settings: An MCASettings instance.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, settings, parent=None):
        """
        Initialize the license dialog.

        :param settings: An MCASettings instance.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("MCA Editor Licensing")
        self.setMinimumWidth(420)
        self._settings = settings
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: status display, key input, buttons."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Current Status Section ---
        status_label = QLabel("<b>License Status</b>")
        layout.addWidget(status_label)

        # Import here to avoid circular imports at module level.
        from mca_core.license import check_license

        status = check_license(self._settings)

        # Build a human-readable status string with color coding.
        if status["licensed"]:
            # Show the masked key so the user knows which key is active.
            masked = self._mask_key(self._settings.get("license_key", ""))
            status_text = (
                "<span style='color: #4ec9b0;'>Licensed</span>"
                "<br>Key: <code>{}</code>"
                "<br>{}"
            ).format(masked, status["message"])
        elif status["trial"]:
            status_text = (
                "<span style='color: #dcdcaa;'>Trial Mode</span>"
                "<br>{} days remaining"
            ).format(status["days_remaining"])
        else:
            status_text = (
                "<span style='color: #f44747;'>Trial Expired</span>"
                "<br>Please enter a license key to continue."
            )

        self._status_display = QLabel(status_text)
        self._status_display.setWordWrap(True)
        self._status_display.setStyleSheet("padding: 8px; font-size: 12px;")
        layout.addWidget(self._status_display)

        # --- Separator ---
        separator = QLabel("<hr>")
        layout.addWidget(separator)

        # --- Key Entry Section ---
        entry_label = QLabel("<b>Enter License Key</b>")
        layout.addWidget(entry_label)

        # Form layout for the key input and activate button.
        form = QFormLayout()
        form.setSpacing(8)

        # QLineEdit with input mask for the MCA-XXXX-XXXX-XXXX-XXXX format.
        # NOTE: Do NOT use the '>' (force-uppercase) mask modifier — it
        # causes digits to be silently rejected on some PySide/Qt builds
        # because the uppercase conversion logic drops characters that
        # "can't be uppercased."  We handle uppercase manually via the
        # textEdited signal instead.
        # Mask format: NNN-NNNN-NNNN-NNNN-NNNN;_
        #   N = required alphanumeric (A-Z, a-z, 0-9)
        #   - = literal dash
        #   ;_ = placeholder character
        self._key_input = QLineEdit()
        self._key_input.setInputMask("NNN-NNNN-NNNN-NNNN-NNNN;_")
        self._key_input.setPlaceholderText("MCA-XXXX-XXXX-XXXX-XXXX")
        self._key_input.setFont(self._key_input.font())
        self._key_input.setStyleSheet("font-family: Consolas; font-size: 14px; padding: 4px;")

        # Force uppercase as the user types (replaces the broken '>' mask modifier).
        self._key_input.textEdited.connect(self._force_uppercase)
        form.addRow("Key:", self._key_input)

        layout.addLayout(form)

        # --- Validation Feedback Label ---
        self._feedback_label = QLabel("")
        self._feedback_label.setWordWrap(True)
        self._feedback_label.setStyleSheet("padding: 4px; font-size: 11px;")
        layout.addWidget(self._feedback_label)

        # --- Buttons ---
        button_layout = QHBoxLayout()

        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setDefault(True)
        self._activate_btn.clicked.connect(self._on_activate)
        button_layout.addWidget(self._activate_btn)

        # Deactivate button — only visible when a license is currently active.
        self._deactivate_btn = QPushButton("Deactivate")
        self._deactivate_btn.setToolTip("Remove the current license key")
        self._deactivate_btn.clicked.connect(self._on_deactivate)
        self._deactivate_btn.setVisible(status["licensed"])
        button_layout.addWidget(self._deactivate_btn)

        self._close_btn = QPushButton("Cancel")
        self._close_btn.clicked.connect(self.reject)
        button_layout.addWidget(self._close_btn)

        layout.addLayout(button_layout)

        # Connect Enter key in the input field to activate.
        self._key_input.returnPressed.connect(self._on_activate)

    def _force_uppercase(self, text):
        """
        Force the key input text to uppercase as the user types.

        Connected to ``textEdited`` because Qt's '>' input mask modifier
        silently rejects digits on some PySide builds.  This manual
        approach handles uppercase without breaking numeric input.

        :param str text: The current text in the QLineEdit.
        """
        # Block signals to avoid recursive textEdited firing.
        self._key_input.blockSignals(True)
        cursor_pos = self._key_input.cursorPosition()
        self._key_input.setText(text.upper())
        self._key_input.setCursorPosition(cursor_pos)
        self._key_input.blockSignals(False)

    def _mask_key(self, key_str):
        """
        Mask a license key for display, showing only the MCA- prefix.

        Example: MCA-AIBQ-RDEF-GHIJ-AILP  →  MCA-****-****-****-****

        :param str key_str: The full license key string.
        :rtype: str
        """
        if not key_str or len(key_str) < 10:
            return key_str

        parts = key_str.strip().upper().split("-")
        if len(parts) != 5:
            return key_str

        # Only show the MCA- prefix — mask all key groups.
        return "{}-****-****-****-****".format(parts[0])

    def _on_deactivate(self):
        """
        Remove the stored license key and revert to trial mode.

        Clears the key from settings, refreshes the status display,
        and hides the Deactivate button.
        """
        from mca_core.license import check_license

        # Clear the stored license key.
        self._settings.set("license_key", "")
        logger.info("License key deactivated")

        # Refresh the status display to show trial/expired state.
        status = check_license(self._settings)
        if status["trial"]:
            status_text = (
                "<span style='color: #dcdcaa;'>Trial Mode</span>"
                "<br>{} days remaining"
            ).format(status["days_remaining"])
        else:
            status_text = (
                "<span style='color: #f44747;'>Trial Expired</span>"
                "<br>Please enter a license key to continue."
            )

        self._status_display.setText(status_text)
        self._feedback_label.setText(
            "<span style='color: #dcdcaa;'>License key removed.</span>"
        )

        # Hide the deactivate button since there's no longer an active key.
        self._deactivate_btn.setVisible(False)

    def _on_activate(self):
        """
        Validate and store the entered license key.

        Shows green feedback on success, red on failure. On success,
        accepts the dialog after a brief delay so the user sees the
        confirmation message.
        """
        from mca_core.license import store_license_key, check_license

        # Read the key from the input field.
        key_str = self._key_input.text().strip()

        # Check for empty / incomplete key (input mask leaves underscores).
        if not key_str or "_" in key_str or len(key_str.replace("-", "")) < 19:
            self._feedback_label.setText(
                "<span style='color: #f44747;'>Please enter a complete license key.</span>"
            )
            return

        # Validate and store the key.
        result = store_license_key(self._settings, key_str)

        if result["valid"]:
            # Success — show green feedback and update the status display.
            if result["perpetual"]:
                msg = "Key activated (perpetual license)"
            else:
                msg = "Key activated (expires {}, {} days remaining)".format(
                    result["expiry_date"], result["days_remaining"]
                )

            self._feedback_label.setText(
                "<span style='color: #4ec9b0;'>{}</span>".format(msg)
            )
            logger.info("License key activated successfully")

            # Refresh the status display.
            masked = self._mask_key(key_str)
            new_status = check_license(self._settings)
            self._status_display.setText(
                "<span style='color: #4ec9b0;'>Licensed</span>"
                "<br>Key: <code>{}</code>"
                "<br>{}".format(masked, new_status["message"])
            )

            # Accept the dialog after a short delay so the user sees the
            # success message before it closes.
            from mca_qt.qt_compat import QTimer
            QTimer.singleShot(1200, self.accept)
        else:
            # Failure — show red feedback.
            self._feedback_label.setText(
                "<span style='color: #f44747;'>{}</span>".format(result["error"])
            )
            logger.warning("License key rejected: %s", result["error"])
