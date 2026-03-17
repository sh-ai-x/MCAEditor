"""
MCA Qt -- Licensing Dialog (3-Tab).

Full-featured licensing dialog with three tabs:
    1. **Activate** -- key input, activate button, buy link
    2. **Trial Status** -- days remaining, buy button
    3. **Manage** -- activation list (placeholder when offline)

Replaces the old ``license_dialog.py`` for the Help > Licensing menu
entry.  The old dialog is still used by ``show_mca_editor()``'s inline
gate in ``maya_window.py`` and is NOT modified.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_core.license (offline HMAC validation)
    - mca_core.activation (online activation stub)
    - mca_core.config.settings (QSettings access)
"""

import logging
import webbrowser

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QLineEdit, QPushButton, QFrame,
    Qt,
)

# QTableWidget and QHeaderView are not in qt_compat — import directly.
# This dialog only runs in the editor's own Qt context, so the PySide
# version is already known by the time we get here.
try:
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
except ImportError:
    from PySide2.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Pricing page URL -------------------------------------------------------
_PRICING_URL = "https://mcaeditor.com/pricing"

# --- Colour constants -------------------------------------------------------
_GREEN = "#4ec9b0"
_YELLOW = "#dcdcaa"
_RED = "#f44747"
_ORANGE = "#FFA500"
_GRAY = "#888888"
_BG_DARK = "#1e1e1e"
_BG_CARD = "#252526"


# =============================================================================
# Licensing Dialog
# =============================================================================

class LicensingDialog(QDialog):
    """
    Three-tab licensing dialog for MCA Editor.

    Displays activation, trial status, and machine management tabs.
    Can be opened modally (blocking startup) or non-modally (from menu).

    :param QWidget parent: Optional parent widget.
    :param bool modal: If True, dialog blocks until closed.
    :param str reason: Machine-readable reason for showing (used to
        select the initial tab).  One of ``""``, ``"not_activated"``,
        ``"expired"``, ``"limit_reached"``.
    :param str message: Human-readable message from the license check.
    :param settings: Optional MCASettings instance.  If None, a default
        instance is created.
    """

    def __init__(self, parent=None, modal=True, reason="", message="", settings=None):
        """
        Initialise the licensing dialog.

        :param QWidget parent: Optional parent widget.
        :param bool modal: Whether the dialog is application-modal.
        :param str reason: Reason code that drove the dialog open.
        :param str message: Descriptive message from the license check.
        :param settings: MCASettings instance (or None for default).
        """
        super().__init__(parent)
        self.setWindowTitle("MCA Editor Licensing")
        self.setMinimumSize(520, 400)
        self.setModal(modal)

        # Store construction parameters.
        self._reason = reason
        self._message = message

        # Settings instance — create a default if not provided.
        if settings is None:
            from mca_core.config.settings import MCASettings
            settings = MCASettings()
        self._settings = settings

        # Apply dark theme to the dialog itself.
        self.setStyleSheet(
            "QDialog {{ background-color: {}; color: #cccccc; }}"
            .format(_BG_DARK)
        )

        # Build the UI.
        self._setup_ui()

        # Select the initial tab based on the reason.
        self._select_initial_tab()

    # -------------------------------------------------------------------------
    # Class-level convenience constructors
    # -------------------------------------------------------------------------

    @classmethod
    def show_if_needed(cls, result, trial, parent=None, settings=None):
        """
        Show the dialog if the license check requires user interaction.

        Called from ``plugin_main._run_license_check()`` when the user
        is not licensed and the trial is expired.

        :param ActivationResult result: Result from ``validate_on_launch()``.
        :param dict trial: Trial status dict from ``get_trial_status()``.
        :param QWidget parent: Optional parent widget.
        :param settings: Optional MCASettings instance.
        """
        dlg = cls(
            parent=parent,
            modal=True,
            reason=result.status,
            message=result.message,
            settings=settings,
        )
        dlg.exec()

    @classmethod
    def open_from_menu(cls, parent=None, settings=None):
        """
        Open the dialog non-modally from the Help > Licensing menu.

        :param QWidget parent: Optional parent widget.
        :param settings: Optional MCASettings instance.  If None, a
            default instance is created.
        """
        if settings is None:
            from mca_core.config.settings import MCASettings
            settings = MCASettings()

        dlg = cls(
            parent=parent,
            modal=False,
            reason="",
            message="",
            settings=settings,
        )
        # Non-modal — show and return immediately.
        dlg.show()

    # -------------------------------------------------------------------------
    # UI Setup
    # -------------------------------------------------------------------------

    def _setup_ui(self):
        """Build the dialog layout: header, tab widget, footer."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # --- Header message (shown when dialog was opened with a reason) ---
        if self._message:
            header = QLabel(self._message)
            header.setWordWrap(True)
            header.setStyleSheet(
                "color: {}; font-size: 12px; padding: 8px;"
                .format(_YELLOW)
            )
            layout.addWidget(header)

        # --- Tab widget ---
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3f3f46;
                background-color: %s;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #cccccc;
                padding: 8px 16px;
                border: 1px solid #3f3f46;
                border-bottom: none;
                min-width: 100px;
            }
            QTabBar::tab:selected {
                background-color: %s;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #3e3e42;
            }
        """ % (_BG_CARD, _BG_CARD))

        # Build each tab.
        self._tabs.addTab(self._build_activate_tab(), "Activate")
        self._tabs.addTab(self._build_trial_tab(), "Trial Status")
        self._tabs.addTab(self._build_manage_tab(), "Manage Activations")

        layout.addWidget(self._tabs)

        # --- Close button ---
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover { background-color: #4e4e52; }
        """)
        close_btn.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # Tab 1: Activate
    # -------------------------------------------------------------------------

    def _build_activate_tab(self):
        """
        Build the Activate tab — key input, activate button, buy link.

        :return: The activate tab widget.
        :rtype: QWidget
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Instructions.
        instructions = QLabel(
            "Enter your license key below. Keys are in the format "
            "<code>MCA-XXXX-XXXX-XXXX-XXXX</code>."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #cccccc; font-size: 12px;")
        layout.addWidget(instructions)

        # Key input with mask.
        self._key_input = QLineEdit()
        self._key_input.setInputMask(">NNN-NNNN-NNNN-NNNN-NNNN;_")
        self._key_input.setPlaceholderText("MCA-XXXX-XXXX-XXXX-XXXX")
        self._key_input.setStyleSheet(
            "font-family: Consolas; font-size: 14px; padding: 6px;"
            "background-color: #3c3c3c; color: #d4d4d4;"
            "border: 1px solid #555; border-radius: 4px;"
        )
        layout.addWidget(self._key_input)

        # Feedback label for validation results.
        self._feedback_label = QLabel("")
        self._feedback_label.setWordWrap(True)
        self._feedback_label.setStyleSheet("padding: 4px; font-size: 11px;")
        layout.addWidget(self._feedback_label)

        # Button row: Activate + Buy Now link.
        btn_row = QHBoxLayout()

        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setDefault(True)
        self._activate_btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 24px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:pressed { background-color: #094771; }
        """)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        btn_row.addWidget(self._activate_btn)

        btn_row.addStretch()

        buy_link = QLabel(
            "<a href='{}' style='color: {};'>Buy a License</a>"
            .format(_PRICING_URL, _GREEN)
        )
        buy_link.setOpenExternalLinks(True)
        buy_link.setStyleSheet("font-size: 12px;")
        btn_row.addWidget(buy_link)

        layout.addLayout(btn_row)
        layout.addStretch()

        # Connect Enter key to activate.
        self._key_input.returnPressed.connect(self._on_activate_clicked)

        return tab

    # -------------------------------------------------------------------------
    # Tab 2: Trial Status
    # -------------------------------------------------------------------------

    def _build_trial_tab(self):
        """
        Build the Trial Status tab — days remaining, buy buttons.

        :return: The trial status tab widget.
        :rtype: QWidget
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Get current trial info.
        from mca_core.license import get_trial_status, check_license
        trial = get_trial_status(self._settings)
        status = check_license(self._settings)

        # --- Status card ---
        card = QFrame()
        card.setStyleSheet(
            "QFrame {{ background-color: {}; border-radius: 6px;"
            " padding: 16px; }}".format(_BG_CARD)
        )
        card_layout = QVBoxLayout(card)

        if status["licensed"]:
            # Already licensed — show green status.
            status_label = QLabel(
                "<span style='color: {}; font-size: 16px;'>"
                "Licensed</span>".format(_GREEN)
            )
            detail = QLabel(status["message"])
            detail.setStyleSheet("color: #999; font-size: 12px;")
            card_layout.addWidget(status_label)
            card_layout.addWidget(detail)

        elif trial["active"]:
            # Trial still running.
            days = trial["days_remaining"]
            if days <= 3:
                color = _ORANGE
            elif days <= 7:
                color = _YELLOW
            else:
                color = _GREEN

            status_label = QLabel(
                "<span style='color: {}; font-size: 18px;'>"
                "{} days remaining</span>".format(color, days)
            )
            detail = QLabel(
                "Your trial started on {}".format(
                    trial["first_launch"][:10] if trial["first_launch"] else "N/A"
                )
            )
            detail.setStyleSheet("color: #999; font-size: 12px;")
            card_layout.addWidget(status_label)
            card_layout.addWidget(detail)

        else:
            # Trial expired.
            status_label = QLabel(
                "<span style='color: {}; font-size: 16px;'>"
                "Trial Expired</span>".format(_RED)
            )
            detail = QLabel(
                "Please enter a license key on the Activate tab to continue."
            )
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #999; font-size: 12px;")
            card_layout.addWidget(status_label)
            card_layout.addWidget(detail)

        layout.addWidget(card)

        # --- Buy button (always shown on trial tab) ---
        buy_btn = QPushButton("Buy a License")
        buy_btn.setFixedWidth(160)
        buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 24px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #1177bb; }
        """)
        buy_btn.clicked.connect(lambda: webbrowser.open(_PRICING_URL))
        layout.addWidget(buy_btn)

        layout.addStretch()

        return tab

    # -------------------------------------------------------------------------
    # Tab 3: Manage Activations
    # -------------------------------------------------------------------------

    def _build_manage_tab(self):
        """
        Build the Manage Activations tab — activation list with
        deactivate buttons, or a placeholder when offline.

        :return: The manage tab widget.
        :rtype: QWidget
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Check if we have a stored key.
        stored_key = self._settings.get("license_key", "")

        if not stored_key:
            # No key — show message directing to Activate tab.
            no_key_label = QLabel(
                "No license key is currently active.\n\n"
                "Enter a key on the Activate tab to get started."
            )
            no_key_label.setWordWrap(True)
            no_key_label.setStyleSheet("color: #999; font-size: 12px;")
            no_key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_key_label)
            layout.addStretch()
            return tab

        # Show masked key at the top.
        masked = self._mask_key(stored_key)
        key_label = QLabel(
            "Active key: <code>{}</code>".format(masked)
        )
        key_label.setStyleSheet("color: #cccccc; font-size: 12px;")
        layout.addWidget(key_label)

        # Try to get activations list.
        try:
            from mca_core.activation import get_activations
            activations = get_activations()
        except ImportError:
            activations = None

        if activations is None:
            # Online info not available — show placeholder.
            self._activations_table = None

            placeholder = QLabel(
                "Online activation management is not available yet.\n\n"
                "Machine activation details will appear here when the "
                "license server is connected."
            )
            placeholder.setWordWrap(True)
            placeholder.setStyleSheet("color: #888; font-size: 12px;")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)

        else:
            # Build the activations table.
            self._activations_table = QTableWidget()
            self._activations_table.setColumnCount(4)
            self._activations_table.setHorizontalHeaderLabels(
                ["Platform", "Hostname", "Activated", ""]
            )
            header = self._activations_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(3, 100)

            self._activations_table.setStyleSheet("""
                QTableWidget {
                    background-color: %s;
                    color: #cccccc;
                    border: 1px solid #3f3f46;
                    gridline-color: #3f3f46;
                }
                QHeaderView::section {
                    background-color: #2d2d30;
                    color: #cccccc;
                    border: 1px solid #3f3f46;
                    padding: 4px;
                }
            """ % _BG_CARD)

            self._populate_activations(activations)
            layout.addWidget(self._activations_table)

        # --- Deactivate this machine button ---
        deactivate_row = QHBoxLayout()
        deactivate_row.addStretch()

        self._deactivate_btn = QPushButton("Deactivate This Machine")
        self._deactivate_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #4e4e52; }
        """)
        self._deactivate_btn.clicked.connect(self._on_deactivate_this)
        deactivate_row.addWidget(self._deactivate_btn)

        layout.addLayout(deactivate_row)
        layout.addStretch()

        return tab

    # -------------------------------------------------------------------------
    # Tab Selection Logic
    # -------------------------------------------------------------------------

    def _select_initial_tab(self):
        """
        Select the starting tab based on the reason the dialog was opened.

        +--------------------------+--------------------+
        | Condition                | Tab                |
        +--------------------------+--------------------+
        | not_activated + trial    | Trial Status       |
        | not_activated + expired  | Activate           |
        | expired                  | Activate           |
        | limit_reached            | Manage Activations |
        | menu + key cached        | Manage Activations |
        | menu + no key            | Activate           |
        +--------------------------+--------------------+
        """
        from mca_core.license import get_trial_status
        trial = get_trial_status(self._settings)

        if self._reason == "not_activated":
            if trial["active"]:
                # Trial still running — show trial tab.
                self._tabs.setCurrentIndex(1)
            else:
                # Trial expired — direct to activate.
                self._tabs.setCurrentIndex(0)

        elif self._reason == "expired":
            # Key expired — direct to activate.
            self._tabs.setCurrentIndex(0)

        elif self._reason == "limit_reached":
            # Too many machines — show manage tab.
            self._tabs.setCurrentIndex(2)

        elif self._reason == "":
            # Opened from menu.
            stored_key = self._settings.get("license_key", "")
            if stored_key:
                self._tabs.setCurrentIndex(2)
            else:
                self._tabs.setCurrentIndex(0)

        else:
            # Default to activate tab.
            self._tabs.setCurrentIndex(0)

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def _on_activate_clicked(self):
        """
        Validate and store the entered license key.

        Uses ``activation.activate()`` when available, falls back to
        ``license.store_license_key()``.  Shows green feedback on
        success, red on failure.
        """
        key_str = self._key_input.text().strip()

        # Check for empty / incomplete key (input mask leaves underscores).
        if not key_str or "_" in key_str or len(key_str.replace("-", "")) < 19:
            self._feedback_label.setText(
                "<span style='color: {};'>Please enter a complete license key."
                "</span>".format(_RED)
            )
            return

        # Try online activation first, fall back to offline.
        try:
            from mca_core.activation import activate
            from mca_core import __version__ as version
            result = activate(key_str, version)
        except ImportError:
            # activation.py not available — use offline directly.
            from mca_core.license import store_license_key
            raw = store_license_key(self._settings, key_str)
            result = {
                "success": raw["valid"],
                "status": "ok" if raw["valid"] else "invalid",
                "message": "" if raw["valid"] else raw["error"],
            }

        if result["success"]:
            self._feedback_label.setText(
                "<span style='color: {};'>License activated successfully!"
                "</span>".format(_GREEN)
            )
            logger.info("License key activated via licensing dialog")

            # Close after a short delay so the user sees the success message.
            from mca_qt.qt_compat import QTimer
            QTimer.singleShot(1200, self._on_success)
        else:
            self._feedback_label.setText(
                "<span style='color: {};'>{}</span>"
                .format(_RED, result.get("message", "Invalid key"))
            )
            logger.warning("License key rejected: %s", result.get("message"))

    def _on_deactivate_this(self):
        """
        Deactivate the license on this machine.

        Clears the stored key, updates the status bar trial indicator,
        and closes the dialog.
        """
        try:
            from mca_core.activation import deactivate
            result = deactivate()
        except ImportError:
            # Fall back to clearing the key directly.
            self._settings.set("license_key", "")
            result = {"success": True, "message": "Key removed"}

        if result["success"]:
            logger.info("License deactivated from licensing dialog")

            # Update the status bar trial indicator on the Maya window.
            self._refresh_status_bar_indicator()

            # Close and let the user reopen to see refreshed state.
            self.close()

    def _refresh_status_bar_indicator(self):
        """
        Find the Maya editor window and refresh the trial indicator.

        Called after activation or deactivation to keep the status bar
        in sync with the current license state.
        """
        try:
            from mca_maya import maya_window as _mw
            window = _mw._mca_editor_window
            if window is not None and hasattr(window, '_check_trial_for_status_bar'):
                window._check_trial_for_status_bar()
        except ImportError:
            # Not running in Maya — nothing to update.
            pass
        except Exception as exc:
            logger.debug("Could not refresh status bar indicator: %s", exc)

    def _on_deactivate_other(self, machine_id):
        """
        Deactivate the license on another machine.

        Stub: not available until the license server is connected.

        :param str machine_id: Identifier for the machine to deactivate.
        """
        logger.info("Deactivate other machine requested: %s (not yet available)",
                     machine_id)

    def _refresh_activations(self):
        """
        Refresh the activations table from the server.

        Stub: ``get_activations()`` returns None, so this is a no-op.
        """
        try:
            from mca_core.activation import get_activations
            activations = get_activations()
            if activations is not None and self._activations_table is not None:
                self._populate_activations(activations)
        except ImportError:
            pass

    def _on_success(self):
        """
        Called after successful activation.

        Closes the dialog, hides the trial indicator in the status bar,
        and attempts to open the editor if we're in the Maya startup
        path (modal dialog blocking editor open).
        """
        # Refresh status bar — hides trial indicator now that we're licensed.
        self._refresh_status_bar_indicator()

        self.close()

        # If we're running inside Maya, try to open the editor now.
        try:
            from mca_maya.plugin_main import _open_editor_window
            import maya.cmds as cmds
            # Use evalDeferred to open the editor after the dialog closes.
            cmds.evalDeferred(
                "from mca_maya.plugin_main import _open_editor_window; "
                "_open_editor_window()",
                lowestPriority=True,
            )
        except ImportError:
            # Not running in Maya — nothing to do.
            pass

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _populate_activations(self, activations):
        """
        Populate the activations table with data.

        :param list activations: List of activation dicts from the server.
        """
        self._activations_table.setRowCount(len(activations))

        for row, act in enumerate(activations):
            self._activations_table.setItem(
                row, 0, QTableWidgetItem(act.get("platform", ""))
            )
            self._activations_table.setItem(
                row, 1, QTableWidgetItem(act.get("hostname", ""))
            )
            self._activations_table.setItem(
                row, 2, QTableWidgetItem(act.get("activated_at", ""))
            )

            # Deactivate button for non-current machines.
            if not act.get("is_current", False):
                btn = QPushButton("Remove")
                btn.setStyleSheet("color: #f44747; font-size: 11px;")
                machine_id = act.get("machine_id", "")
                btn.clicked.connect(
                    lambda checked, mid=machine_id: self._on_deactivate_other(mid)
                )
                self._activations_table.setCellWidget(row, 3, btn)
            else:
                self._activations_table.setItem(
                    row, 3, QTableWidgetItem("This machine")
                )

    def _mask_key(self, key_str):
        """
        Mask a license key for display, showing only the MCA- prefix.

        :param str key_str: The full license key string.
        :rtype: str
        """
        if not key_str or len(key_str) < 10:
            return key_str

        parts = key_str.strip().upper().split("-")
        if len(parts) != 5:
            return key_str

        return "{}-****-****-****-****".format(parts[0])
