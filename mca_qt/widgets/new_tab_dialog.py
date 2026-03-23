"""
MCA Qt - New Tab Language Picker Dialog.

Modal dialog that lets the user choose a language when creating a new tab.
Follows the same dark-themed style as ConnectionDialog.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
"""

import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- New Tab Dialog ----------------------------------------------------------

class NewTabDialog(QDialog):
    """
    Modal dialog for choosing a language when creating a new tab.

    Displays language buttons and a Cancel button. By default shows
    Python, MEL, and Text. The ``languages`` parameter can override
    which languages are offered (e.g. UE excludes MEL).

    After the dialog closes, call ``get_language()`` to retrieve the
    selected language string.

    :param QWidget parent: Optional parent widget.
    :param list languages: List of (display_name, language_id) tuples.
        Defaults to [("Python", "python"), ("MEL", "mel"), ("Text", "text")].
    """

    # Default language choices.
    DEFAULT_LANGUAGES = [("Python", "python"), ("MEL", "mel"), ("Text", "text")]

    def __init__(self, parent=None, languages=None):
        """
        Initialize the New Tab dialog.

        :param QWidget parent: Optional parent widget.
        :param list languages: Optional override for which languages to offer.
        """
        super().__init__(parent)
        self.setWindowTitle("New Tab")
        self.setMinimumWidth(320)
        self._selected_language = None
        self._languages = languages or self.DEFAULT_LANGUAGES
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: label, language buttons, cancel."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # --- Header label ---
        label = QLabel("Choose a language for the new tab.")
        label.setStyleSheet("color: #cccccc; font-size: 13px;")
        layout.addWidget(label)

        # --- Language buttons row ---
        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        # Style shared by all language buttons.
        lang_button_style = """
            QPushButton {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 12px;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #4e4e52;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #094771;
            }
        """

        # One button per language, each stores its language string on click.
        for display_name, language_id in self._languages:
            btn = QPushButton(display_name)
            btn.setStyleSheet(lang_button_style)
            # Capture language_id in the lambda via default argument.
            btn.clicked.connect(lambda checked=False, lang=language_id: self._on_language_chosen(lang))
            button_row.addWidget(btn)

        layout.addLayout(button_row)

        # --- Cancel button ---
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d30;
                color: #999999;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3e3e42;
                color: #cccccc;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        # Dark background for the dialog itself.
        self.setStyleSheet("""
            QDialog {
                background-color: #252526;
            }
        """)

    def _on_language_chosen(self, language):
        """
        Handle a language button click — store the choice and accept.

        :param str language: The language identifier ("python", "mel", "text").
        """
        self._selected_language = language
        self.accept()

    def get_language(self):
        """
        Get the language selected by the user.

        :return: Language identifier ("python", "mel", "text"), or None if cancelled.
        :rtype: str or None
        """
        return self._selected_language
