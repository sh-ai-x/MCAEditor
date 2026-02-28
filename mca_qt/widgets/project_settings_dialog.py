"""
MCA Qt - Project Settings Dialog.

A dialog for editing an existing project's configuration without
hand-editing the ``.mca-project`` JSON file. Editable fields:

    - Project name
    - Python source paths (add/remove relative directories)
    - Excluded folders (add/remove folder names)
    - Startup script file (relative path to a .py file)
    - Startup inline code (Python code typed directly into the dialog)
    - Shutdown script file (relative path to a .py file run on close)
    - Shutdown inline code (Python code run before teardown on close)
    - Environment variables (key=value pairs set in os.environ)

Dependencies:
    - PySide6 (QDialog, QVBoxLayout, etc.)
    - mca_core.project (MCAProject)
"""

import os
import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QTabWidget, QWidget, QGroupBox, QFormLayout,
    QPlainTextEdit,
    Qt,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Shared Styles -----------------------------------------------------------

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

_LIST_STYLE = """
    QListWidget {
        background-color: #2d2d30;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        font-size: 12px;
    }
    QListWidget::item {
        padding: 3px;
    }
    QListWidget::item:selected {
        background-color: #094771;
    }
"""

_BTN_STYLE = """
    QPushButton {
        background-color: #3c3c3c;
        color: #cccccc;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 4px 10px;
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

_CODE_EDIT_STYLE = """
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

_GROUP_STYLE = """
    QGroupBox {
        color: #cccccc;
        font-size: 11px;
        font-weight: bold;
        border: 1px solid #3f3f46;
        border-radius: 3px;
        margin-top: 8px;
        padding-top: 14px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }
"""


# --- Environment Variable Name/Value Dialog -----------------------------------

class _EnvVarDialog(QDialog):
    """
    Small dialog with separate Name and Value fields for an env var.

    If the value looks like a filesystem path (contains slashes or
    backslashes), it is normalized to a valid path string on accept.

    :param str initial_key: Pre-fill for the Name field.
    :param str initial_value: Pre-fill for the Value field.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, initial_key="", initial_value="", parent=None):
        """
        Initialize the env var dialog.

        :param str initial_key: Pre-fill for the Name field.
        :param str initial_value: Pre-fill for the Value field.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._result_key = ""
        self._result_value = ""

        title = "Edit Environment Variable" if initial_key else "Add Environment Variable"
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Name field ---
        name_label = QLabel("Name:")
        name_label.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(name_label)

        self._key_edit = QLineEdit()
        self._key_edit.setText(initial_key)
        self._key_edit.setPlaceholderText("e.g. PYTHONDONTWRITEBYTECODE")
        self._key_edit.setStyleSheet(_INPUT_STYLE)
        layout.addWidget(self._key_edit)

        # --- Value field ---
        value_label = QLabel("Value:")
        value_label.setStyleSheet(_LABEL_STYLE)
        layout.addWidget(value_label)

        self._value_edit = QLineEdit()
        self._value_edit.setText(initial_value)
        self._value_edit.setPlaceholderText("e.g. 1  or  C:/tools/bin")
        self._value_edit.setStyleSheet(_INPUT_STYLE)
        layout.addWidget(self._value_edit)

        # --- Browse button for path values ---
        browse_btn = QPushButton("Browse Path...")
        browse_btn.setToolTip("Pick a file or folder and insert its normalized path as the value")
        browse_btn.setStyleSheet(_BTN_STYLE)
        browse_btn.clicked.connect(self._browse_path)
        layout.addWidget(browse_btn)

        # --- OK / Cancel ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.setStyleSheet(_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(80)
        ok_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _browse_path(self):
        """
        Open a file/folder picker and set the value field to the
        normalized path.
        """
        # Try folder first — most env var paths are directories.
        path = QFileDialog.getExistingDirectory(self, "Select Path")
        if not path:
            # Fall back to file picker if the user cancelled the folder dialog.
            path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self._value_edit.setText(os.path.normpath(path))

    def _on_accept(self):
        """Validate, normalize path values, and accept."""
        key = self._key_edit.text().strip()
        value = self._value_edit.text().strip()

        if not key:
            return

        # If the value looks like a filesystem path, normalize it.
        # Heuristic: contains a slash, backslash, or starts with a drive letter.
        if value and _looks_like_path(value):
            value = os.path.normpath(value)

        self._result_key = key
        self._result_value = value
        self.accept()

    def result(self):
        """
        Return the key and value after the dialog is accepted.

        :return: Tuple of (key, value).
        :rtype: tuple
        """
        return (self._result_key, self._result_value)


def _looks_like_path(value):
    """
    Heuristic check for whether a string looks like a filesystem path.

    Returns True if the value contains path separators or starts with
    a drive letter (e.g. ``C:``), suggesting it should be normalized.

    :param str value: The string to test.
    :return: True if the value appears to be a path.
    :rtype: bool
    """
    # Contains forward or backslash.
    if "/" in value or "\\" in value:
        return True
    # Starts with a Windows drive letter (e.g. "C:" or "D:").
    if len(value) >= 2 and value[1] == ":" and value[0].isalpha():
        return True
    # Starts with ~ (home directory shorthand).
    if value.startswith("~"):
        return True
    return False


# --- Project Settings Dialog --------------------------------------------------

class ProjectSettingsDialog(QDialog):
    """
    Dialog for editing an active project's configuration.

    Reads the current values from the ``MCAProject`` instance and
    presents them in an editable form. On accept, the caller can
    retrieve the updated values via ``result()`` and apply them.

    :param MCAProject project: The active project to edit.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, project, parent=None):
        """
        Initialize the dialog with the project's current values.

        :param MCAProject project: The active project instance.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._project = project
        self._result = None

        self.setWindowTitle("Project Settings -- {}".format(project.name))
        self.setMinimumSize(500, 600)
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout with tabs for different setting groups."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Project name ---
        name_group = QGroupBox("General")
        name_group.setStyleSheet(_GROUP_STYLE)
        name_layout = QFormLayout(name_group)
        name_layout.setSpacing(6)

        self._name_edit = QLineEdit()
        self._name_edit.setText(self._project.name)
        self._name_edit.setStyleSheet(_INPUT_STYLE)
        name_layout.addRow(self._make_label("Project Name:"), self._name_edit)

        # Project root (read-only display).
        root_label = QLineEdit()
        root_label.setText(self._project.project_root)
        root_label.setReadOnly(True)
        root_label.setStyleSheet(
            _INPUT_STYLE.replace("#3c3c3c", "#2d2d30")
        )
        name_layout.addRow(self._make_label("Project Root:"), root_label)

        layout.addWidget(name_group)

        # --- Python Paths ---
        paths_group = QGroupBox("Python Source Paths (added to sys.path)")
        paths_group.setStyleSheet(_GROUP_STYLE)
        paths_layout = QVBoxLayout(paths_group)

        self._paths_list = QListWidget()
        self._paths_list.setStyleSheet(_LIST_STYLE)
        self._paths_list.setMinimumHeight(90)
        # Populate with current paths.
        for rel_path in self._project.python_paths:
            self._paths_list.addItem(rel_path)
        paths_layout.addWidget(self._paths_list)

        # Add/Remove buttons for paths.
        paths_btn_row = QHBoxLayout()
        paths_btn_row.addStretch()

        add_path_btn = QPushButton("Add...")
        add_path_btn.setStyleSheet(_BTN_STYLE)
        add_path_btn.clicked.connect(self._add_python_path)
        paths_btn_row.addWidget(add_path_btn)

        remove_path_btn = QPushButton("Remove")
        remove_path_btn.setStyleSheet(_BTN_STYLE)
        remove_path_btn.clicked.connect(self._remove_python_path)
        paths_btn_row.addWidget(remove_path_btn)

        paths_layout.addLayout(paths_btn_row)
        layout.addWidget(paths_group)

        # --- Excluded Folders ---
        excl_group = QGroupBox("Excluded Folders (hidden in workspace tree)")
        excl_group.setStyleSheet(_GROUP_STYLE)
        excl_layout = QVBoxLayout(excl_group)

        self._excluded_list = QListWidget()
        self._excluded_list.setStyleSheet(_LIST_STYLE)
        self._excluded_list.setMinimumHeight(80)
        # Populate with current excluded folders.
        for folder_name in sorted(self._project.excluded_folders):
            self._excluded_list.addItem(folder_name)
        excl_layout.addWidget(self._excluded_list)

        # Add/Remove buttons for excluded folders.
        excl_btn_row = QHBoxLayout()
        excl_btn_row.addStretch()

        add_excl_btn = QPushButton("Add...")
        add_excl_btn.setStyleSheet(_BTN_STYLE)
        add_excl_btn.clicked.connect(self._add_excluded_folder)
        excl_btn_row.addWidget(add_excl_btn)

        remove_excl_btn = QPushButton("Remove")
        remove_excl_btn.setStyleSheet(_BTN_STYLE)
        remove_excl_btn.clicked.connect(self._remove_excluded_folder)
        excl_btn_row.addWidget(remove_excl_btn)

        excl_layout.addLayout(excl_btn_row)
        layout.addWidget(excl_group)

        # --- Scripts (Startup / Shutdown tabs) ---
        scripts_group = QGroupBox("Scripts")
        scripts_group.setStyleSheet(_GROUP_STYLE)
        scripts_group_layout = QVBoxLayout(scripts_group)

        # Tab widget to separate Startup and Shutdown into distinct pages.
        self._scripts_tabs = QTabWidget()
        self._scripts_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3f3f46;
                background-color: #2d2d30;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                color: #969696;
                border: 1px solid #3f3f46;
                padding: 4px 14px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border-bottom-color: #1e1e1e;
            }
            QTabBar::tab:hover {
                color: #d4d4d4;
            }
        """)

        # --- Startup tab ---
        startup_tab = QWidget()
        startup_layout = QVBoxLayout(startup_tab)
        startup_layout.setContentsMargins(8, 8, 8, 8)

        # File path row — point to an external .py file.
        file_label = QLabel("Script file (relative to project root):")
        file_label.setStyleSheet(_LABEL_STYLE)
        startup_layout.addWidget(file_label)

        file_row = QHBoxLayout()
        self._script_edit = QLineEdit()
        self._script_edit.setText(self._project.startup_script)
        self._script_edit.setPlaceholderText("e.g. scripts/startup.py")
        self._script_edit.setStyleSheet(_INPUT_STYLE)
        file_row.addWidget(self._script_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.setStyleSheet(_BTN_STYLE)
        browse_btn.clicked.connect(self._browse_startup_script)
        file_row.addWidget(browse_btn)
        startup_layout.addLayout(file_row)

        # Inline code editor — small script typed directly.
        code_label = QLabel("Inline code (runs after the script file, if any):")
        code_label.setStyleSheet(_LABEL_STYLE)
        startup_layout.addWidget(code_label)

        self._code_edit = QPlainTextEdit()
        self._code_edit.setPlainText(self._project.startup_code)
        self._code_edit.setPlaceholderText("# Python code to run on project open...")
        self._code_edit.setStyleSheet(_CODE_EDIT_STYLE)
        self._code_edit.setMinimumHeight(120)
        self._code_edit.setTabStopDistance(28.0)  # ~4 spaces at 12px font.
        startup_layout.addWidget(self._code_edit)

        startup_layout.addStretch()
        self._scripts_tabs.addTab(startup_tab, "Startup")

        # --- Shutdown tab ---
        shutdown_tab = QWidget()
        shutdown_layout = QVBoxLayout(shutdown_tab)
        shutdown_layout.setContentsMargins(8, 8, 8, 8)

        # File path row — point to an external .py file.
        shutdown_file_label = QLabel("Script file (relative to project root):")
        shutdown_file_label.setStyleSheet(_LABEL_STYLE)
        shutdown_layout.addWidget(shutdown_file_label)

        shutdown_file_row = QHBoxLayout()
        self._shutdown_script_edit = QLineEdit()
        self._shutdown_script_edit.setText(self._project.shutdown_script)
        self._shutdown_script_edit.setPlaceholderText("e.g. scripts/shutdown.py")
        self._shutdown_script_edit.setStyleSheet(_INPUT_STYLE)
        shutdown_file_row.addWidget(self._shutdown_script_edit)

        shutdown_browse_btn = QPushButton("Browse...")
        shutdown_browse_btn.setStyleSheet(_BTN_STYLE)
        shutdown_browse_btn.clicked.connect(self._browse_shutdown_script)
        shutdown_file_row.addWidget(shutdown_browse_btn)
        shutdown_layout.addLayout(shutdown_file_row)

        # Inline code editor — small script typed directly.
        shutdown_code_label = QLabel("Inline code (runs after the script file, if any):")
        shutdown_code_label.setStyleSheet(_LABEL_STYLE)
        shutdown_layout.addWidget(shutdown_code_label)

        self._shutdown_code_edit = QPlainTextEdit()
        self._shutdown_code_edit.setPlainText(self._project.shutdown_code)
        self._shutdown_code_edit.setPlaceholderText("# Python code to run on project close...")
        self._shutdown_code_edit.setStyleSheet(_CODE_EDIT_STYLE)
        self._shutdown_code_edit.setMinimumHeight(120)
        self._shutdown_code_edit.setTabStopDistance(28.0)  # ~4 spaces at 12px font.
        shutdown_layout.addWidget(self._shutdown_code_edit)

        shutdown_layout.addStretch()
        self._scripts_tabs.addTab(shutdown_tab, "Shutdown")

        scripts_group_layout.addWidget(self._scripts_tabs)
        layout.addWidget(scripts_group)

        # --- Environment Variables ---
        env_group = QGroupBox("Environment Variables (set in os.environ on open)")
        env_group.setStyleSheet(_GROUP_STYLE)
        env_layout = QVBoxLayout(env_group)

        self._env_list = QListWidget()
        self._env_list.setStyleSheet(_LIST_STYLE)
        self._env_list.setMinimumHeight(80)
        # Populate with current env vars as "KEY=VALUE" entries.
        for key in sorted(self._project.env_vars):
            value = self._project.env_vars[key]
            self._env_list.addItem("{}={}".format(key, value))
        env_layout.addWidget(self._env_list)

        # Add/Remove buttons for env vars.
        env_btn_row = QHBoxLayout()
        env_btn_row.addStretch()

        add_env_btn = QPushButton("Add...")
        add_env_btn.setStyleSheet(_BTN_STYLE)
        add_env_btn.clicked.connect(self._add_env_var)
        env_btn_row.addWidget(add_env_btn)

        edit_env_btn = QPushButton("Edit...")
        edit_env_btn.setStyleSheet(_BTN_STYLE)
        edit_env_btn.clicked.connect(self._edit_env_var)
        env_btn_row.addWidget(edit_env_btn)

        remove_env_btn = QPushButton("Remove")
        remove_env_btn.setStyleSheet(_BTN_STYLE)
        remove_env_btn.clicked.connect(self._remove_env_var)
        env_btn_row.addWidget(remove_env_btn)

        env_layout.addLayout(env_btn_row)
        layout.addWidget(env_group)

        # --- OK / Cancel ---
        layout.addStretch()
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.setStyleSheet(_BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(80)
        save_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    # --- Helpers --------------------------------------------------------------

    def _make_label(self, text):
        """
        Create a styled label for form rows.

        :param str text: Label text.
        :return: Styled QLabel.
        :rtype: QLabel
        """
        label = QLabel(text)
        label.setStyleSheet(_LABEL_STYLE)
        return label

    # --- Python Paths Actions -------------------------------------------------

    def _add_python_path(self):
        """Prompt for a directory and add it as a relative Python path."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Python Source Directory",
            self._project.project_root
        )
        if not folder:
            return

        # Convert to relative path from the project root.
        try:
            rel = os.path.relpath(folder, self._project.project_root)
        except ValueError:
            # Different drive on Windows — can't make relative.
            rel = folder

        # Normalize to forward slashes for cross-platform consistency.
        rel = rel.replace("\\", "/")

        # Avoid duplicates.
        for i in range(self._paths_list.count()):
            if self._paths_list.item(i).text() == rel:
                return
        self._paths_list.addItem(rel)

    def _remove_python_path(self):
        """Remove the currently selected Python path from the list."""
        current = self._paths_list.currentRow()
        if current >= 0:
            self._paths_list.takeItem(current)

    # --- Excluded Folders Actions ---------------------------------------------

    def _add_excluded_folder(self):
        """Prompt for a folder name and add it to the exclusion list."""
        from mca_qt.qt_compat import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Add Excluded Folder",
            "Folder name to exclude (e.g. __pycache__):"
        )
        if ok and name.strip():
            name = name.strip()
            # Avoid duplicates.
            for i in range(self._excluded_list.count()):
                if self._excluded_list.item(i).text() == name:
                    return
            self._excluded_list.addItem(name)

    def _remove_excluded_folder(self):
        """Remove the currently selected excluded folder from the list."""
        current = self._excluded_list.currentRow()
        if current >= 0:
            self._excluded_list.takeItem(current)

    # --- Startup Script -------------------------------------------------------

    def _browse_startup_script(self):
        """Open a file picker for the startup script."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Startup Script",
            self._project.project_root,
            "Python Files (*.py);;All Files (*)"
        )
        if not filepath:
            return

        # Convert to relative path from the project root.
        try:
            rel = os.path.relpath(filepath, self._project.project_root)
        except ValueError:
            rel = filepath
        rel = rel.replace("\\", "/")
        self._script_edit.setText(rel)

    # --- Shutdown Script ------------------------------------------------------

    def _browse_shutdown_script(self):
        """Open a file picker for the shutdown script."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Shutdown Script",
            self._project.project_root,
            "Python Files (*.py);;All Files (*)"
        )
        if not filepath:
            return

        # Convert to relative path from the project root.
        try:
            rel = os.path.relpath(filepath, self._project.project_root)
        except ValueError:
            rel = filepath
        rel = rel.replace("\\", "/")
        self._shutdown_script_edit.setText(rel)

    # --- Environment Variables Actions ----------------------------------------

    def _add_env_var(self):
        """Open the Name/Value dialog to add a new environment variable."""
        dialog = _EnvVarDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key, value = dialog.result()
        if not key:
            return

        # Avoid duplicate keys — replace if the key already exists.
        for i in range(self._env_list.count()):
            existing = self._env_list.item(i).text()
            if existing.split("=", 1)[0].strip() == key:
                self._env_list.item(i).setText("{}={}".format(key, value))
                return
        self._env_list.addItem("{}={}".format(key, value))

    def _edit_env_var(self):
        """Open the Name/Value dialog to edit the selected env var."""
        current = self._env_list.currentRow()
        if current < 0:
            return

        # Parse the existing entry.
        old_text = self._env_list.item(current).text()
        old_key, old_value = "", ""
        if "=" in old_text:
            old_key, old_value = old_text.split("=", 1)

        dialog = _EnvVarDialog(
            initial_key=old_key.strip(),
            initial_value=old_value.strip(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key, value = dialog.result()
        if not key:
            return
        self._env_list.item(current).setText("{}={}".format(key, value))

    def _remove_env_var(self):
        """Remove the currently selected env var from the list."""
        current = self._env_list.currentRow()
        if current >= 0:
            self._env_list.takeItem(current)

    # --- Save -----------------------------------------------------------------

    def _on_save(self):
        """Collect all field values and accept the dialog."""
        # Gather python paths from the list widget.
        python_paths = []
        for i in range(self._paths_list.count()):
            python_paths.append(self._paths_list.item(i).text())

        # Gather excluded folders from the list widget.
        excluded = []
        for i in range(self._excluded_list.count()):
            excluded.append(self._excluded_list.item(i).text())

        # Gather env vars from the list widget — parse "KEY=VALUE" entries.
        env_vars = {}
        for i in range(self._env_list.count()):
            entry = self._env_list.item(i).text()
            if "=" in entry:
                key, value = entry.split("=", 1)
                env_vars[key.strip()] = value.strip()

        self._result = {
            "name": self._name_edit.text().strip() or self._project.name,
            "python_paths": python_paths,
            "excluded_folders": excluded,
            "startup_script": self._script_edit.text().strip(),
            "startup_code": self._code_edit.toPlainText(),
            "shutdown_script": self._shutdown_script_edit.text().strip(),
            "shutdown_code": self._shutdown_code_edit.toPlainText(),
            "env_vars": env_vars,
        }
        self.accept()

    def result(self):
        """
        Return the user's edited values after the dialog is accepted.

        :return: Dictionary with keys: name, python_paths, excluded_folders,
            startup_script, startup_code, shutdown_script, shutdown_code,
            env_vars. Or None if cancelled.
        :rtype: dict or None
        """
        return self._result
