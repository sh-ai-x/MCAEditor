"""
MCA Editor - Sidebar Panels.

Workspace tree, code outline, and open editors view.
Mirrors Charcoal Editor 2's sidebar with additions for advanced mode.

Dependencies:
    - PySide6 (QWidget, QTreeWidget, QFileSystemWatcher, etc.)
"""

import os
import logging

import shutil
import subprocess
import platform

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QFileDialog, QLineEdit, QSplitter,
    QMenu, QApplication, QInputDialog, QMessageBox,
    QAbstractItemView,
    Qt, Signal, QFileSystemWatcher,
    QColor,
)
from mca_qt.icons import folder_closed, folder_open, python_logo, maya_logo, text_icon

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

        # Map language identifiers to their icons.
        lang_icons = {
            "python": python_logo,
            "mel": maya_logo,
            "text": text_icon,
        }

        for i, tab in enumerate(tabs):
            name = tab.get("name", "Untitled")
            # Show a dot for modified buffers.
            if tab.get("modified", False):
                name = "* {}".format(name)

            item = QTreeWidgetItem()
            item.setText(0, name)
            item.setToolTip(0, tab.get("path", "Temporary buffer"))
            item.setData(0, Qt.ItemDataRole.UserRole, i)

            # Set the language icon (falls back to text icon for unknown languages).
            language = tab.get("language", "")
            icon_fn = lang_icons.get(language, text_icon)
            item.setIcon(0, icon_fn())

            self._tree.addTopLevelItem(item)

    def update_editors_grouped(self, groups_data):
        """
        Update the open editors list with group headers.

        Shows a "Group N" header for each group when there are
        multiple groups. Each editor item stores a flat index so
        the sidebar's ``editor_selected`` signal works with the
        panel's flat-index lookup.

        :param list groups_data: List of lists, where each inner list
            contains tab dicts (same format as ``update_editors``).
        """
        self._tree.clear()

        lang_icons = {
            "python": python_logo,
            "mel": maya_logo,
            "text": text_icon,
        }

        flat_index = 0
        for gi, group_tabs in enumerate(groups_data):
            # Add a group header item.
            header = QTreeWidgetItem()
            header.setText(0, "Group {}".format(gi + 1))
            header.setForeground(0, QColor("#888888"))
            # Headers are not selectable — no UserRole data.
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._tree.addTopLevelItem(header)

            for tab in group_tabs:
                name = tab.get("name", "Untitled")
                if tab.get("modified", False):
                    name = "* {}".format(name)

                item = QTreeWidgetItem()
                item.setText(0, "  {}".format(name))
                item.setToolTip(0, tab.get("path", "Temporary buffer"))
                # Store flat index for the panel's lookup.
                item.setData(0, Qt.ItemDataRole.UserRole, flat_index)

                language = tab.get("language", "")
                icon_fn = lang_icons.get(language, text_icon)
                item.setIcon(0, icon_fn())

                self._tree.addTopLevelItem(item)
                flat_index += 1

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
# Drag-and-Drop Workspace Tree
# =============================================================================

class _WorkspaceTree(QTreeWidget):
    """
    QTreeWidget subclass that supports drag-and-drop to move files and folders.

    Dragging a file or folder onto another folder moves it on disk via
    ``shutil.move``, then emits ``file_moved`` so the parent panel can
    refresh the tree.
    """

    # Emitted after a successful move: (old_path, new_path).
    file_moved = Signal(str, str)

    def __init__(self, parent=None):
        """
        Initialize the drag-drop-enabled workspace tree.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)

        # Enable internal drag-and-drop rearrangement.
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    # --- Drag-and-Drop Handlers ----------------------------------------------

    def dragEnterEvent(self, event):
        """
        Accept the drag if the source item carries a valid path.

        :param QDragEnterEvent event: The drag-enter event.
        """
        # Only accept drags originating from within this tree.
        if event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """
        Accept the drag when hovering over a folder (or tree background).

        :param QDragMoveEvent event: The drag-move event.
        """
        # Determine what item is under the cursor.
        target_item = self.itemAt(event.position().toPoint())

        if target_item is None:
            # Hovering over empty tree background — reject (no root-level drop).
            event.ignore()
            return

        target_path = target_item.data(0, Qt.ItemDataRole.UserRole)
        if not target_path:
            event.ignore()
            return

        # Accept drops on folders, or on files (we'll resolve to the parent folder).
        if os.path.exists(target_path):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """
        Move the dragged file/folder to the target location on disk.

        If the drop target is a file, the item is moved into that file's
        parent directory. Validates that the move is safe before proceeding.

        :param QDropEvent event: The drop event.
        """
        # --- Identify source item and path ---
        source_item = self.currentItem()
        if source_item is None:
            event.ignore()
            return

        source_path = source_item.data(0, Qt.ItemDataRole.UserRole)
        if not source_path or not os.path.exists(source_path):
            event.ignore()
            return

        # --- Identify target item and resolve to a folder ---
        target_item = self.itemAt(event.position().toPoint())
        if target_item is None:
            event.ignore()
            return

        target_path = target_item.data(0, Qt.ItemDataRole.UserRole)
        if not target_path:
            event.ignore()
            return

        # If the target is a file, use its parent folder.
        if os.path.isfile(target_path):
            target_folder = os.path.dirname(target_path)
        elif os.path.isdir(target_path):
            target_folder = target_path
        else:
            event.ignore()
            return

        # --- Compute destination path ---
        basename = os.path.basename(source_path)
        dest_path = os.path.join(target_folder, basename)

        # --- Validation checks ---

        # No-op: source and destination are in the same folder already.
        if os.path.dirname(source_path) == target_folder:
            event.ignore()
            return

        # Prevent moving a folder into itself or a subdirectory of itself.
        if os.path.isdir(source_path):
            # Normalize paths for reliable comparison.
            norm_source = os.path.normpath(source_path) + os.sep
            norm_target = os.path.normpath(target_folder) + os.sep
            if norm_target.startswith(norm_source):
                logger.warning("Cannot move a folder into itself: %s -> %s", source_path, target_folder)
                event.ignore()
                return

        # Destination already exists — warn and abort.
        if os.path.exists(dest_path):
            QMessageBox.warning(
                self, "Cannot Move",
                "'{}' already exists in the target folder.".format(basename)
            )
            event.ignore()
            return

        # --- Perform the move ---
        try:
            shutil.move(source_path, dest_path)
            logger.debug("Moved '%s' -> '%s'", source_path, dest_path)
            self.file_moved.emit(source_path, dest_path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Move Failed",
                "Could not move '{}':\n{}".format(basename, str(exc))
            )

        # Ignore the default QTreeWidget drop behavior — we handle the move ourselves.
        event.ignore()


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
    # Emitted when a file or folder is renamed. Args: (old_path, new_path).
    file_renamed = Signal(str, str)
    # Emitted when the user clicks the "New" header button.
    new_tab_requested = Signal()
    # Emitted when the user clicks the "Open" header button.
    open_file_requested = Signal()

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

        # Shared style for the small header buttons.
        _header_btn_style = """
            QPushButton {
                background: transparent;
                color: #969696;
                border: none;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #3e3e42;
            }
        """

        # "New" button — requests a new tab from the editor panel.
        new_btn = QPushButton("New")
        new_btn.setFixedSize(32, 22)
        new_btn.setToolTip("New Tab")
        new_btn.setStyleSheet(_header_btn_style)
        new_btn.clicked.connect(self.new_tab_requested.emit)
        header_layout.addWidget(new_btn)

        # "Open" button — requests a file-open dialog from the editor panel.
        open_btn = QPushButton("Open")
        open_btn.setFixedSize(36, 22)
        open_btn.setToolTip("Open File")
        open_btn.setStyleSheet(_header_btn_style)
        open_btn.clicked.connect(self.open_file_requested.emit)
        header_layout.addWidget(open_btn)

        # Refresh button — manually re-scan the workspace tree.
        refresh_btn = QPushButton("R")
        refresh_btn.setFixedSize(22, 22)
        refresh_btn.setToolTip("Refresh Workspace")
        refresh_btn.setStyleSheet(_header_btn_style)
        refresh_btn.clicked.connect(self._refresh_tree)
        header_layout.addWidget(refresh_btn)

        layout.addWidget(header)

        # --- Search field (filters the file tree by name) ---
        self._search_field = QLineEdit()
        self._search_field.setPlaceholderText("Search files...")
        self._search_field.setFixedHeight(24)
        self._search_field.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: none;
                border-bottom: 1px solid #3f3f46;
                padding: 3px 8px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-bottom-color: #007acc;
            }
        """)
        self._search_field.textChanged.connect(self.filter_files)
        layout.addWidget(self._search_field)

        # --- Tree widget for file browsing (with drag-and-drop support) ---
        self._tree = _WorkspaceTree()
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
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)

        # Refresh the tree after a drag-and-drop move.
        self._tree.file_moved.connect(self._on_file_moved)

        # Enable right-click context menus on the tree.
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self._tree)

        # --- Empty state message ---
        self._empty_label = QLabel("No workspace folder.\nScripts directory loading...")
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
            root_item.setText(0, folder_name)
            root_item.setIcon(0, folder_open())
            root_item.setData(0, Qt.ItemDataRole.UserRole, folder)
            root_item.setForeground(0, QColor("#cccccc"))

            self._populate_folder(root_item, folder, depth=0)
            self._tree.addTopLevelItem(root_item)

            # Expand AFTER adding to the tree — Qt silently ignores
            # setExpanded() on items that aren't in a tree yet.
            root_item.setExpanded(True)

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
            item.setText(0, d)
            item.setIcon(0, folder_closed())
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

    def _on_item_expanded(self, item):
        """
        Swap to the open folder icon when a folder is expanded.

        :param QTreeWidgetItem item: The expanded item.
        """
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            item.setIcon(0, folder_open())

    def _on_item_collapsed(self, item):
        """
        Swap to the closed folder icon when a folder is collapsed.

        :param QTreeWidgetItem item: The collapsed item.
        """
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            item.setIcon(0, folder_closed())

    def _on_directory_changed(self, path):
        """
        Refresh the tree when a watched directory changes.

        :param str path: The directory that changed.
        """
        self._refresh_tree()

    def _on_file_moved(self, old_path, new_path):
        """
        Handle a file or folder moved via drag-and-drop.

        Refreshes the workspace tree to reflect the new layout.

        :param str old_path: The original path before the move.
        :param str new_path: The new path after the move.
        """
        logger.debug("Drag-drop move complete: '%s' -> '%s'", old_path, new_path)
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

    def set_locked_folder(self, folder_path):
        """
        Lock the workspace to a single folder.

        Clears any existing folders, sets the given folder as the sole
        workspace root, adds it to the file watcher, and refreshes the
        tree.  Used in Default mode to pin the workspace to the
        ``scripts/`` directory.

        :param str folder_path: Absolute path to the folder.
        """
        # Remove all existing watched folders.
        for f in self._workspace_folders:
            self._watcher.removePath(f)

        # Set the single locked folder.
        self._workspace_folders = [folder_path]
        self._watcher.addPath(folder_path)
        self._refresh_tree()
        self._update_empty_state()
        logger.info("Workspace locked to: %s", folder_path)

    # --- File Search Filtering -----------------------------------------------

    def filter_files(self, text):
        """
        Show/hide tree items based on a filename search string.

        When *text* is empty, all items are unhidden (full tree restored).
        Otherwise, file items whose name does not contain *text*
        (case-insensitive) are hidden. Folder items are hidden only if
        none of their descendants match; folders with visible children
        are auto-expanded so matches are obvious.

        Uses ``QTreeWidgetItem.setHidden()`` for speed — no tree rebuild.

        :param str text: The search filter text.
        """
        root = self._tree.invisibleRootItem()

        if not text:
            # Empty search — unhide everything.
            self._set_all_visible(root)
            return

        # Filter each top-level workspace folder independently.
        # We never call setHidden on the invisible root itself.
        search = text.lower()
        for i in range(root.childCount()):
            self._apply_filter(root.child(i), search)

    def _set_all_visible(self, parent):
        """
        Recursively unhide all descendant items.

        :param QTreeWidgetItem parent: The parent item to start from
            (typically the invisible root).
        """
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setHidden(False)
            self._set_all_visible(child)

    # --- Context Menu ---------------------------------------------------------

    def _on_context_menu(self, pos):
        """
        Show a context menu on right-click in the tree widget.

        Shows different menus for folders vs files. If no item is
        clicked, no menu is shown.

        :param QPoint pos: Click position in tree widget coordinates.
        """
        item = self._tree.itemAt(pos)
        if item is None:
            return

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2d2d30;
                color: #cccccc;
                border: 1px solid #3f3f46;
                padding: 4px 0;
            }
            QMenu::item {
                padding: 4px 24px 4px 12px;
            }
            QMenu::item:selected {
                background-color: #094771;
            }
            QMenu::item:disabled {
                color: #666666;
            }
            QMenu::separator {
                height: 1px;
                background: #3f3f46;
                margin: 4px 8px;
            }
        """)

        if os.path.isdir(path):
            self._build_folder_context_menu(menu, item, path)
        elif os.path.isfile(path):
            self._build_file_context_menu(menu, item, path)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _build_folder_context_menu(self, menu, item, folder_path):
        """
        Build the context menu for a folder item.

        Actions: New File, New Folder, Show in Explorer,
        Find in Folder, Paste, Copy Path, Delete.

        :param QMenu menu: The menu to populate.
        :param QTreeWidgetItem item: The clicked tree item.
        :param str folder_path: Absolute path to the folder.
        """
        # --- New File ---
        new_file_action = menu.addAction("New File")
        new_file_action.triggered.connect(
            lambda: self._new_file_in_folder(folder_path)
        )

        # --- New Folder ---
        new_folder_action = menu.addAction("New Folder")
        new_folder_action.triggered.connect(
            lambda: self._new_folder_in_folder(folder_path)
        )

        # --- Show in Explorer ---
        reveal_action = menu.addAction("Show in Explorer")
        reveal_action.triggered.connect(
            lambda: self._reveal_in_explorer(folder_path)
        )

        menu.addSeparator()

        # --- Find in Folder ---
        find_action = menu.addAction("Find in Folder...")
        find_action.setEnabled(False)  # Placeholder for future implementation.

        menu.addSeparator()

        # --- Paste ---
        paste_action = menu.addAction("Paste")
        # Only enable if the clipboard has a file path that exists.
        clipboard = QApplication.instance().clipboard()
        clipboard_text = clipboard.text().strip() if clipboard else ""
        can_paste = bool(clipboard_text) and os.path.exists(clipboard_text)
        paste_action.setEnabled(can_paste)
        if can_paste:
            paste_action.triggered.connect(
                lambda: self._paste_into_folder(folder_path, clipboard_text)
            )

        # --- Copy Path ---
        copy_path_action = menu.addAction("Copy Path")
        copy_path_action.triggered.connect(
            lambda: self._copy_path(folder_path)
        )

        menu.addSeparator()

        # --- Delete ---
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(
            lambda: self._delete_path(folder_path, is_folder=True)
        )

    def _build_file_context_menu(self, menu, item, file_path):
        """
        Build the context menu for a file item.

        Actions: Open, Show in Explorer, Copy, Copy Path, Rename, Delete.

        :param QMenu menu: The menu to populate.
        :param QTreeWidgetItem item: The clicked tree item.
        :param str file_path: Absolute path to the file.
        """
        # --- Open ---
        open_action = menu.addAction("Open")
        open_action.triggered.connect(
            lambda: self.file_open_requested.emit(file_path)
        )

        # --- Show in Explorer ---
        reveal_action = menu.addAction("Show in Explorer")
        reveal_action.triggered.connect(
            lambda: self._reveal_in_explorer(file_path)
        )

        menu.addSeparator()

        # --- Copy (file path to clipboard for paste operations) ---
        copy_action = menu.addAction("Copy")
        copy_action.triggered.connect(
            lambda: self._copy_path(file_path)
        )

        # --- Copy Path ---
        copy_path_action = menu.addAction("Copy Path")
        copy_path_action.triggered.connect(
            lambda: self._copy_path(file_path)
        )

        menu.addSeparator()

        # --- Rename ---
        rename_action = menu.addAction("Rename")
        rename_action.triggered.connect(
            lambda: self._rename_path(file_path)
        )

        # --- Delete ---
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(
            lambda: self._delete_path(file_path, is_folder=False)
        )

    # --- Context Menu Actions ------------------------------------------------

    def _new_file_in_folder(self, folder_path):
        """
        Create a new file inside the given folder.

        Prompts the user for a filename, creates the file, and emits
        file_created so the editor can open it.

        :param str folder_path: The folder to create the file in.
        """
        name, ok = QInputDialog.getText(
            self, "New File", "File name:",
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        new_path = os.path.join(folder_path, name)

        # Don't overwrite existing files.
        if os.path.exists(new_path):
            QMessageBox.warning(
                self, "File Exists",
                "A file or folder named '{}' already exists.".format(name)
            )
            return

        try:
            # Create an empty file.
            with open(new_path, "w", encoding="utf-8") as f:
                f.write("")
            logger.info("Created new file: %s", new_path)
            self._refresh_tree()

            # Emit so the editor opens the new file.
            self.file_created.emit(new_path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Could not create file:\n{}".format(str(exc))
            )

    def _new_folder_in_folder(self, folder_path):
        """
        Create a new subfolder inside the given folder.

        :param str folder_path: The parent folder.
        """
        name, ok = QInputDialog.getText(
            self, "New Folder", "Folder name:",
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        new_path = os.path.join(folder_path, name)

        if os.path.exists(new_path):
            QMessageBox.warning(
                self, "Folder Exists",
                "A file or folder named '{}' already exists.".format(name)
            )
            return

        try:
            os.makedirs(new_path, exist_ok=True)
            logger.info("Created new folder: %s", new_path)
            self._refresh_tree()
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Could not create folder:\n{}".format(str(exc))
            )

    def _reveal_in_explorer(self, path):
        """
        Open the system file explorer and highlight the given path.

        :param str path: Absolute path to reveal.
        """
        try:
            if platform.system() == "Windows":
                # Normalize to backslashes — Explorer ignores forward slashes.
                native_path = os.path.normpath(path)
                # /select, highlights the file.  Must be passed as a single
                # command string — list form splits the args and Explorer
                # can't parse them correctly.
                if os.path.isfile(native_path):
                    subprocess.Popen(
                        'explorer /select,"{}"'.format(native_path),
                        shell=True,
                    )
                else:
                    subprocess.Popen(["explorer", native_path])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                # Linux — open the containing folder.
                folder = path if os.path.isdir(path) else os.path.dirname(path)
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            logger.warning("Could not reveal in explorer: %s", exc)

    def _copy_path(self, path):
        """
        Copy a file or folder path to the system clipboard.

        :param str path: The path to copy.
        """
        clipboard = QApplication.instance().clipboard()
        clipboard.setText(path)

    def _paste_into_folder(self, folder_path, source_path):
        """
        Copy a file or folder from the clipboard path into the target folder.

        :param str folder_path: Destination folder.
        :param str source_path: Source file or folder path from clipboard.
        """
        basename = os.path.basename(source_path)
        dest_path = os.path.join(folder_path, basename)

        # Avoid overwriting.
        if os.path.exists(dest_path):
            QMessageBox.warning(
                self, "Already Exists",
                "'{}' already exists in the target folder.".format(basename)
            )
            return

        try:
            if os.path.isdir(source_path):
                shutil.copytree(source_path, dest_path)
            else:
                shutil.copy2(source_path, dest_path)
            logger.info("Pasted '%s' into '%s'", basename, folder_path)
            self._refresh_tree()
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Could not paste:\n{}".format(str(exc))
            )

    def _rename_path(self, path):
        """
        Rename a file or folder.

        :param str path: Absolute path to the item to rename.
        """
        old_name = os.path.basename(path)
        new_name, ok = QInputDialog.getText(
            self, "Rename", "New name:", text=old_name,
        )
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return

        new_name = new_name.strip()
        parent_dir = os.path.dirname(path)
        new_path = os.path.join(parent_dir, new_name)

        if os.path.exists(new_path):
            QMessageBox.warning(
                self, "Already Exists",
                "'{}' already exists.".format(new_name)
            )
            return

        try:
            os.rename(path, new_path)
            logger.info("Renamed '%s' -> '%s'", old_name, new_name)
            self._refresh_tree()
            # Notify listeners so open tabs can update their name and path.
            self.file_renamed.emit(path, new_path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Could not rename:\n{}".format(str(exc))
            )

    def _delete_path(self, path, is_folder):
        """
        Delete a file or folder after user confirmation.

        :param str path: Absolute path to delete.
        :param bool is_folder: True if deleting a folder.
        """
        name = os.path.basename(path)
        kind = "folder" if is_folder else "file"

        reply = QMessageBox.question(
            self, "Delete {}".format(kind.title()),
            "Are you sure you want to delete '{}'?".format(name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            if is_folder:
                shutil.rmtree(path)
            else:
                os.remove(path)
            logger.info("Deleted %s: %s", kind, path)
            self._refresh_tree()
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Could not delete {}:\n{}".format(kind, str(exc))
            )

    # --- Item Helpers --------------------------------------------------------

    def _is_folder_item(self, item):
        """
        Check whether a tree item represents a directory.

        Uses the stored file path in UserRole rather than childCount,
        because empty folders have childCount == 0 but are still folders.

        :param QTreeWidgetItem item: The tree item to check.
        :return: True if the item represents a directory.
        :rtype: bool
        """
        path = item.data(0, Qt.ItemDataRole.UserRole)
        return path is not None and os.path.isdir(path)

    def _apply_filter(self, item, search):
        """
        Recursively hide/show items based on filename match.

        Files are matched by name. Folders are shown if any descendant
        file matches (and auto-expanded), hidden otherwise.

        :param QTreeWidgetItem item: Current tree item.
        :param str search: Lowercase search string.
        :return: True if this item or any descendant is visible.
        :rtype: bool
        """
        if self._is_folder_item(item):
            # Folder — visible only if a descendant matches.
            any_child_visible = False
            for i in range(item.childCount()):
                if self._apply_filter(item.child(i), search):
                    any_child_visible = True

            item.setHidden(not any_child_visible)
            # Expand folders that contain matches so the user sees them.
            if any_child_visible:
                item.setExpanded(True)
            return any_child_visible

        # File leaf — match against the display text (includes name).
        visible = search in item.text(0).lower()
        item.setHidden(not visible)
        return visible


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
    file_created = Signal(str)
    file_renamed = Signal(str, str)
    outline_item_clicked = Signal(int)
    editor_selected = Signal(int)
    new_tab_requested = Signal()
    open_file_requested = Signal()

    def __init__(self, parent=None):
        """
        Initialize the combined sidebar.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the sidebar layout with a vertical splitter for resizable panels."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Vertical splitter lets the user drag to resize panels.
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(3)
        self._splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3f3f46;
            }
        """)

        # Workspace panel (visible in Advanced mode only).
        self.workspace_panel = WorkspacePanel()
        self.workspace_panel.file_open_requested.connect(self.file_open_requested.emit)
        self.workspace_panel.file_created.connect(self.file_created.emit)
        self.workspace_panel.file_renamed.connect(self.file_renamed.emit)
        self.workspace_panel.new_tab_requested.connect(self.new_tab_requested.emit)
        self.workspace_panel.open_file_requested.connect(self.open_file_requested.emit)
        self._splitter.addWidget(self.workspace_panel)

        # Open editors panel (always visible).
        self.open_editors_panel = OpenEditorsPanel()
        self.open_editors_panel.editor_selected.connect(self.editor_selected.emit)
        self._splitter.addWidget(self.open_editors_panel)

        # Code outline panel (always visible).
        self.outline_panel = CodeOutlinePanel()
        self.outline_panel.item_clicked.connect(self.outline_item_clicked.emit)
        self._splitter.addWidget(self.outline_panel)

        # Default sizes: workspace gets most space, editors and outline smaller.
        self._splitter.setSizes([300, 100, 200])

        layout.addWidget(self._splitter)

    def set_simple_mode(self):
        """Switch to simple mode - hide the workspace panel."""
        self.workspace_panel.setVisible(False)

    def set_advanced_mode(self):
        """Switch to advanced mode - show the workspace panel."""
        self.workspace_panel.setVisible(True)

    def splitter_sizes(self):
        """
        Return the current sizes of the sidebar's internal splitter.

        :return: List of pixel sizes for each panel [workspace, open editors, outline].
        :rtype: list
        """
        return self._splitter.sizes()

    def set_splitter_sizes(self, sizes):
        """
        Restore the sidebar's internal splitter sizes.

        :param list sizes: List of pixel sizes for each panel.
        """
        self._splitter.setSizes(sizes)
