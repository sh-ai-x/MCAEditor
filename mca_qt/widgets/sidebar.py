"""
MCA Editor - Sidebar Panels.

Workspace tree, code outline, and open editors view.
Mirrors Charcoal Editor 2's sidebar with additions for advanced mode.

Dependencies:
    - PySide6 (QWidget, QTreeWidget, QFileSystemWatcher, etc.)
"""

import os
import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QFileDialog,
    Qt, Signal, QFileSystemWatcher,
    QColor,
)

# Module-level logger for sidebar operations.
logger = logging.getLogger(__name__)


# --- File Icon Constants ----------------------------------------------------

# Map file extensions to unicode icons for the workspace tree.
FILE_ICONS = {
    ".py": "Py",
    ".mel": "MEL",
    ".cs": "C#",
    ".lua": "Lua",
    ".json": "{}",
    ".yaml": "YML",
    ".yml": "YML",
    ".txt": "TXT",
    ".md": "MD",
}

MAX_TREE_DEPTH = 5  # Maximum depth for recursive folder traversal


# =============================================================================
# Code Outline Panel
# =============================================================================

class CodeOutlinePanel(QWidget):
    """
    Displays classes, functions, and methods in the current file.

    Equivalent to Charcoal Editor 2's Code Outline View. Clicking an
    item emits the line number for navigation.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when a user clicks an outline item (carries line number).
    item_clicked = Signal(int)

    def __init__(self, parent=None):
        """
        Initialize the outline panel.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the outline panel layout: header + tree."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3f3f46;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)

        title = QLabel("OUTLINE")
        title.setStyleSheet("color: #bbbbbb; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addWidget(header)

        # --- Tree widget for outline items ---
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background-color: #252526;
                border: none;
                font-size: 12px;
            }
        """)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

    def update_outline(self, outline_data):
        """
        Update the outline tree from editor data.

        Methods are nested under their parent class when possible.

        :param list outline_data: List of dicts with 'type', 'name',
                                  'line', and 'indent' keys.
        """
        self._tree.clear()

        # Color coding by symbol type.
        type_colors = {
            "class": "#4ec9b0",
            "function": "#dcdcaa",
            "method": "#dcdcaa",
            "proc": "#dcdcaa",
        }

        # Type label prefixes.
        type_labels = {
            "class": "C",
            "function": "f",
            "method": "m",
            "proc": "p",
        }

        # Track class items so methods can be nested under them.
        class_items = {}

        for item in outline_data:
            label = type_labels.get(item["type"], "-")
            name = "[{}] {}".format(label, item["name"])
            color = type_colors.get(item["type"], "#d4d4d4")

            tree_item = QTreeWidgetItem()
            tree_item.setText(0, name)
            tree_item.setForeground(0, QColor(color))
            tree_item.setData(0, Qt.ItemDataRole.UserRole, item["line"])

            # Nest methods under their parent class.
            if item["type"] == "class":
                self._tree.addTopLevelItem(tree_item)
                class_items[item["name"]] = tree_item
                tree_item.setExpanded(True)
            elif item["type"] == "method" and item["indent"] > 0:
                # Find the most recent class as the parent.
                parent = None
                for cls_name, cls_item in class_items.items():
                    parent = cls_item
                if parent:
                    parent.addChild(tree_item)
                else:
                    self._tree.addTopLevelItem(tree_item)
            else:
                self._tree.addTopLevelItem(tree_item)

    def _on_item_clicked(self, item, column):
        """
        Handle click on an outline item.

        :param QTreeWidgetItem item: The clicked item.
        :param int column: The clicked column.
        """
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line:
            self.item_clicked.emit(line)


# =============================================================================
# Open Editors Panel
# =============================================================================

class OpenEditorsPanel(QWidget):
    """
    Lists all open editor tabs.

    Equivalent to Charcoal Editor 2's Open Editors View.
    Clicking an entry selects the corresponding tab.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the user selects an editor (tab index).
    editor_selected = Signal(int)
    # Emitted when the user requests to close an editor (tab index).
    editor_close_requested = Signal(int)

    def __init__(self, parent=None):
        """
        Initialize the open editors panel.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the open editors layout: header + list."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3f3f46;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)

        title = QLabel("OPEN EDITORS")
        title.setStyleSheet("color: #bbbbbb; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addWidget(header)

        # --- Tree for editor list ---
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(8)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background-color: #252526;
                border: none;
                font-size: 12px;
            }
        """)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

    def update_editors(self, tabs):
        """
        Update the open editors list.

        :param list tabs: List of dicts with 'name', 'path', 'modified',
                          and 'language' keys.
        """
        self._tree.clear()

        # Language-to-label mapping for display.
        lang_labels = {
            "python": "Py",
            "mel": "MEL",
            "csharp": "C#",
            "lua": "Lua",
        }

        for i, tab in enumerate(tabs):
            label = lang_labels.get(tab.get("language", ""), "?")
            name = tab.get("name", "Untitled")
            # Show a dot for modified buffers.
            if tab.get("modified", False):
                name = "[*] {}".format(name)

            item = QTreeWidgetItem()
            item.setText(0, "[{}] {}".format(label, name))
            item.setToolTip(0, tab.get("path", "Temporary buffer"))
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)

    def _on_item_clicked(self, item, column):
        """
        Handle click on an editor entry.

        :param QTreeWidgetItem item: The clicked item.
        :param int column: The clicked column.
        """
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.editor_selected.emit(idx)


# =============================================================================
# Workspace Tree Panel (Advanced Mode)
# =============================================================================

class WorkspacePanel(QWidget):
    """
    Project file browser / workspace tree.

    Equivalent to Charcoal Editor 2's Workspace View.
    Only visible in Advanced mode. Supports adding/removing folders
    and watches the filesystem for live updates.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when the user double-clicks a file to open it.
    file_open_requested = Signal(str)
    # Emitted when a new file is created.
    file_created = Signal(str)

    def __init__(self, parent=None):
        """
        Initialize the workspace panel.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._workspace_folders = []
        self._watcher = QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._setup_ui()

    def _setup_ui(self):
        """Build the workspace panel layout: header + tree + empty state."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3f3f46;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)

        title = QLabel("WORKSPACE")
        title.setStyleSheet("color: #bbbbbb; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Add folder button.
        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 22)
        add_btn.setToolTip("Add Folder to Workspace")
        add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #969696;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #3e3e42;
            }
        """)
        add_btn.clicked.connect(self.add_folder_dialog)
        header_layout.addWidget(add_btn)

        layout.addWidget(header)

        # --- Tree widget for file browsing ---
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setDragEnabled(False)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background-color: #252526;
                border: none;
                font-size: 12px;
            }
        """)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree)

        # --- Empty state message ---
        self._empty_label = QLabel("No workspace folders.\nClick + to add a folder.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #666666; padding: 20px; font-size: 11px;")
        layout.addWidget(self._empty_label)

        self._update_empty_state()

    def add_folder_dialog(self):
        """Show a dialog to let the user pick a folder to add."""
        folder = QFileDialog.getExistingDirectory(self, "Add Folder to Workspace")
        if folder:
            self.add_folder(folder)

    def add_folder(self, folder_path):
        """
        Add a folder to the workspace.

        :param str folder_path: Absolute path to the folder.
        """
        if folder_path not in self._workspace_folders:
            self._workspace_folders.append(folder_path)
            self._watcher.addPath(folder_path)
            self._refresh_tree()
            self._update_empty_state()
            logger.info("Added workspace folder: %s", folder_path)

    def remove_folder(self, folder_path):
        """
        Remove a folder from the workspace.

        :param str folder_path: The folder to remove.
        """
        if folder_path in self._workspace_folders:
            self._workspace_folders.remove(folder_path)
            self._watcher.removePath(folder_path)
            self._refresh_tree()
            self._update_empty_state()

    def _update_empty_state(self):
        """Show or hide the empty-state label based on folder count."""
        has_folders = len(self._workspace_folders) > 0
        self._tree.setVisible(has_folders)
        self._empty_label.setVisible(not has_folders)

    def _refresh_tree(self):
        """Rebuild the entire file tree from workspace folders."""
        self._tree.clear()

        for folder in self._workspace_folders:
            folder_name = os.path.basename(folder)
            root_item = QTreeWidgetItem()
            root_item.setText(0, "[DIR] {}".format(folder_name))
            root_item.setData(0, Qt.ItemDataRole.UserRole, folder)
            root_item.setForeground(0, QColor("#cccccc"))
            root_item.setExpanded(True)

            self._populate_folder(root_item, folder, depth=0)
            self._tree.addTopLevelItem(root_item)

    def _populate_folder(self, parent_item, folder_path, depth):
        """
        Recursively populate folder contents in the tree.

        Directories are listed first, then files. Hidden entries
        (starting with '.') are skipped.

        :param QTreeWidgetItem parent_item: Parent tree item.
        :param str folder_path: Path to scan.
        :param int depth: Current recursion depth.
        """
        if depth >= MAX_TREE_DEPTH:
            return

        try:
            entries = sorted(os.listdir(folder_path))
        except PermissionError:
            return

        # Sort directories first, then files.
        dirs = [e for e in entries
                if os.path.isdir(os.path.join(folder_path, e)) and not e.startswith(".")]
        files = [e for e in entries
                 if os.path.isfile(os.path.join(folder_path, e)) and not e.startswith(".")]

        for d in dirs:
            full_path = os.path.join(folder_path, d)
            item = QTreeWidgetItem()
            item.setText(0, "[DIR] {}".format(d))
            item.setData(0, Qt.ItemDataRole.UserRole, full_path)
            item.setForeground(0, QColor("#cccccc"))
            parent_item.addChild(item)
            self._populate_folder(item, full_path, depth + 1)

        for f in files:
            full_path = os.path.join(folder_path, f)
            ext = os.path.splitext(f)[1].lower()
            icon_label = FILE_ICONS.get(ext, "---")

            item = QTreeWidgetItem()
            item.setText(0, "[{}] {}".format(icon_label, f))
            item.setData(0, Qt.ItemDataRole.UserRole, full_path)

            # Script files get brighter text than data files.
            if ext in (".py", ".mel", ".cs", ".lua"):
                item.setForeground(0, QColor("#d4d4d4"))
            else:
                item.setForeground(0, QColor("#969696"))

            parent_item.addChild(item)

    def _on_item_double_clicked(self, item, column):
        """
        Handle double-click on a tree item (opens files).

        :param QTreeWidgetItem item: The double-clicked item.
        :param int column: The clicked column.
        """
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.isfile(path):
            self.file_open_requested.emit(path)

    def _on_directory_changed(self, path):
        """
        Refresh the tree when a watched directory changes.

        :param str path: The directory that changed.
        """
        self._refresh_tree()

    def get_workspace_folders(self):
        """
        Get the list of workspace folder paths.

        :return: Copy of the workspace folders list.
        :rtype: list
        """
        return list(self._workspace_folders)

    def set_workspace_folders(self, folders):
        """
        Set the workspace folders (e.g. restoring from settings).

        :param list folders: List of folder path strings.
        """
        self._workspace_folders = list(folders)
        for f in folders:
            self._watcher.addPath(f)
        self._refresh_tree()
        self._update_empty_state()


# =============================================================================
# Combined Sidebar
# =============================================================================

class MCASidebar(QWidget):
    """
    Combined sidebar containing all panels.

    In Simple mode: only Outline and Open Editors are shown.
    In Advanced mode: the Workspace tree is also visible.

    :param QWidget parent: Optional parent widget.
    """

    # Forwarded signals from child panels.
    file_open_requested = Signal(str)
    outline_item_clicked = Signal(int)
    editor_selected = Signal(int)

    def __init__(self, parent=None):
        """
        Initialize the combined sidebar.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the sidebar layout with all three panels."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        # Workspace panel (visible in Advanced mode only).
        self.workspace_panel = WorkspacePanel()
        self.workspace_panel.file_open_requested.connect(self.file_open_requested.emit)
        layout.addWidget(self.workspace_panel, stretch=3)

        # Open editors panel (always visible).
        self.open_editors_panel = OpenEditorsPanel()
        self.open_editors_panel.editor_selected.connect(self.editor_selected.emit)
        layout.addWidget(self.open_editors_panel, stretch=1)

        # Code outline panel (always visible).
        self.outline_panel = CodeOutlinePanel()
        self.outline_panel.item_clicked.connect(self.outline_item_clicked.emit)
        layout.addWidget(self.outline_panel, stretch=2)

    def set_simple_mode(self):
        """Switch to simple mode - hide the workspace panel."""
        self.workspace_panel.setVisible(False)

    def set_advanced_mode(self):
        """Switch to advanced mode - show the workspace panel."""
        self.workspace_panel.setVisible(True)
