"""
MCA Qt - Create Project Dialog.

A dialog shown when the user opens a folder that does not yet have a
``.mca-project`` file. Lets the user confirm the project name and
select which auto-detected Python paths to include on ``sys.path``.

Dependencies:
    - PySide6 (QDialog, QVBoxLayout, etc.)
    - mca_core.project (detect_python_paths)
"""

import os
import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem,
    Qt,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Create Project Dialog ---------------------------------------------------

class CreateProjectDialog(QDialog):
    """
    Dialog for creating a new MCA project from a folder.

    Displays a project name field (defaults to the folder name) and a
    checkable list of auto-detected Python source directories. The user
    can toggle which paths should be added to ``sys.path`` when the
    project is opened.

    Call ``exec()`` and check the return value:
        - ``QDialog.Accepted``: use ``result()`` to get ``(name, paths)``
        - ``QDialog.Rejected``: user cancelled

    :param str folder_path: Absolute path to the project root folder.
    :param list detected_paths: Pre-detected relative Python paths.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, folder_path, detected_paths=None, parent=None):
        """
        Initialize the dialog.

        :param str folder_path: Absolute path to the project root.
        :param list detected_paths: Relative Python paths to pre-select.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._folder_path = folder_path
        self._detected_paths = detected_paths or []
        self._result_name = ""
        self._result_paths = []

        self.setWindowTitle("Create Project")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: name field, path list, buttons."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Info label ---
        info = QLabel(
            "No .mca-project file found in this folder.\n"
            "Create a new project to enable sys.path management."
        )
        info.setStyleSheet("color: #cccccc; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Project name field ---
        name_label = QLabel("Project Name:")
        name_label.setStyleSheet("color: #bbbbbb; font-size: 11px;")
        layout.addWidget(name_label)

        self._name_edit = QLineEdit()
        self._name_edit.setText(os.path.basename(self._folder_path))
        self._name_edit.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """)
        layout.addWidget(self._name_edit)

        # --- Python paths list ---
        paths_label = QLabel("Python Source Paths (added to sys.path):")
        paths_label.setStyleSheet("color: #bbbbbb; font-size: 11px;")
        layout.addWidget(paths_label)

        self._paths_list = QListWidget()
        self._paths_list.setStyleSheet("""
            QListWidget {
                background-color: #2d2d30;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 4px;
            }
        """)
        self._paths_list.setMinimumHeight(120)

        # Populate with detected paths — all checked by default.
        if self._detected_paths:
            for rel_path in self._detected_paths:
                # Show the relative path with a note about what it resolves to.
                display = rel_path if rel_path != "." else ". (project root)"
                item = QListWidgetItem(display)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, rel_path)
                self._paths_list.addItem(item)
        else:
            # No paths detected — add the project root as a default.
            item = QListWidgetItem(". (project root)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, ".")
            self._paths_list.addItem(item)

        layout.addWidget(self._paths_list)

        # --- Button row ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px 12px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #4e4e52; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("Create Project")
        ok_btn.setFixedWidth(120)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #094771;
                color: #ffffff;
                border: 1px solid #094771;
                border-radius: 3px;
                padding: 5px 12px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #0e639c; }
        """)
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _on_accept(self):
        """Collect the name and selected paths, then accept the dialog."""
        self._result_name = self._name_edit.text().strip()
        if not self._result_name:
            self._result_name = os.path.basename(self._folder_path)

        # Collect only checked paths.
        self._result_paths = []
        for i in range(self._paths_list.count()):
            item = self._paths_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                rel_path = item.data(Qt.ItemDataRole.UserRole)
                self._result_paths.append(rel_path)

        self.accept()

    def result(self):
        """
        Return the user's choices after the dialog is accepted.

        :return: Tuple of (project_name, selected_relative_paths), or
            None if the dialog was cancelled.
        :rtype: tuple or None
        """
        return (self._result_name, self._result_paths)
