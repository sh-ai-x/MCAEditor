"""
Forge Editor - Sidebar Panels
Workspace tree, code outline, open editors view.
Mirrors Charcoal Editor 2's sidebar with additions for advanced mode.
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QFileDialog, QStackedWidget, QToolButton,
    QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QFileSystemWatcher, QDir
from PySide6.QtGui import QIcon, QColor, QFont


# =============================================================================
# Code Outline Panel
# =============================================================================

class CodeOutlinePanel(QWidget):
    """
    Displays classes, functions, and methods in the current file.
    Equivalent to Charcoal Editor 2's Code Outline View.
    """
    
    item_clicked = Signal(int)  # line number
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
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
        
        # Tree
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
    
    def update_outline(self, outline_data: list):
        """Update the outline tree from editor data."""
        self._tree.clear()
        
        type_icons = {
            "class": "🔷",
            "function": "🟡",
            "method": "🟢",
            "proc": "🟡",
        }
        
        type_colors = {
            "class": "#4ec9b0",
            "function": "#dcdcaa",
            "method": "#dcdcaa",
            "proc": "#dcdcaa",
        }
        
        class_items = {}
        
        for item in outline_data:
            icon = type_icons.get(item["type"], "•")
            name = f"{icon} {item['name']}"
            color = type_colors.get(item["type"], "#d4d4d4")
            
            tree_item = QTreeWidgetItem()
            tree_item.setText(0, name)
            tree_item.setForeground(0, QColor(color))
            tree_item.setData(0, Qt.ItemDataRole.UserRole, item["line"])
            
            # Nest methods under their class
            if item["type"] == "class":
                self._tree.addTopLevelItem(tree_item)
                class_items[item["name"]] = tree_item
                tree_item.setExpanded(True)
            elif item["type"] == "method" and item["indent"] > 0:
                # Find parent class (last class with lower indent)
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
    """
    
    editor_selected = Signal(int)  # tab index
    editor_close_requested = Signal(int)  # tab index
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
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
    
    def update_editors(self, tabs: list):
        """Update the open editors list.
        
        Args:
            tabs: List of dicts with 'name', 'path', 'modified', 'language'
        """
        self._tree.clear()
        
        lang_icons = {
            "python": "🐍",
            "mel": "📜",
            "csharp": "🔹",
            "lua": "🌙",
        }
        
        for i, tab in enumerate(tabs):
            icon = lang_icons.get(tab.get("language", ""), "📄")
            name = tab.get("name", "Untitled")
            if tab.get("modified", False):
                name = f"● {name}"
            
            item = QTreeWidgetItem()
            item.setText(0, f"{icon} {name}")
            item.setToolTip(0, tab.get("path", "Temporary buffer"))
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)
    
    def _on_item_clicked(self, item, column):
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
    Only visible in Advanced mode.
    """
    
    file_open_requested = Signal(str)     # filepath
    file_created = Signal(str)            # filepath
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workspace_folders = []
        self._watcher = QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3f3f46;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        
        title = QLabel("WORKSPACE")
        title.setStyleSheet("color: #bbbbbb; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
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
        
        # Tree
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
        
        # Empty state
        self._empty_label = QLabel("No workspace folders.\nClick + to add a folder.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #666666; padding: 20px; font-size: 11px;")
        layout.addWidget(self._empty_label)
        
        self._update_empty_state()
    
    def add_folder_dialog(self):
        """Show dialog to add a folder to workspace."""
        folder = QFileDialog.getExistingDirectory(self, "Add Folder to Workspace")
        if folder:
            self.add_folder(folder)
    
    def add_folder(self, folder_path: str):
        """Add a folder to the workspace."""
        if folder_path not in self._workspace_folders:
            self._workspace_folders.append(folder_path)
            self._watcher.addPath(folder_path)
            self._refresh_tree()
            self._update_empty_state()
    
    def remove_folder(self, folder_path: str):
        """Remove a folder from the workspace."""
        if folder_path in self._workspace_folders:
            self._workspace_folders.remove(folder_path)
            self._watcher.removePath(folder_path)
            self._refresh_tree()
            self._update_empty_state()
    
    def _update_empty_state(self):
        has_folders = len(self._workspace_folders) > 0
        self._tree.setVisible(has_folders)
        self._empty_label.setVisible(not has_folders)
    
    def _refresh_tree(self):
        """Rebuild the file tree."""
        self._tree.clear()
        
        file_icons = {
            ".py": "🐍",
            ".mel": "📜",
            ".cs": "🔹",
            ".lua": "🌙",
            ".json": "📋",
            ".yaml": "📋",
            ".yml": "📋",
            ".txt": "📝",
            ".md": "📖",
        }
        
        for folder in self._workspace_folders:
            folder_name = os.path.basename(folder)
            root_item = QTreeWidgetItem()
            root_item.setText(0, f"📁 {folder_name}")
            root_item.setData(0, Qt.ItemDataRole.UserRole, folder)
            root_item.setForeground(0, QColor("#cccccc"))
            root_item.setExpanded(True)
            
            self._populate_folder(root_item, folder, file_icons, depth=0, max_depth=5)
            self._tree.addTopLevelItem(root_item)
    
    def _populate_folder(self, parent_item, folder_path, file_icons, depth, max_depth):
        """Recursively populate folder contents."""
        if depth >= max_depth:
            return
        
        try:
            entries = sorted(os.listdir(folder_path))
        except PermissionError:
            return
        
        # Directories first, then files
        dirs = [e for e in entries if os.path.isdir(os.path.join(folder_path, e)) and not e.startswith(".")]
        files = [e for e in entries if os.path.isfile(os.path.join(folder_path, e)) and not e.startswith(".")]
        
        for d in dirs:
            full_path = os.path.join(folder_path, d)
            item = QTreeWidgetItem()
            item.setText(0, f"📁 {d}")
            item.setData(0, Qt.ItemDataRole.UserRole, full_path)
            item.setForeground(0, QColor("#cccccc"))
            parent_item.addChild(item)
            self._populate_folder(item, full_path, file_icons, depth + 1, max_depth)
        
        for f in files:
            full_path = os.path.join(folder_path, f)
            ext = os.path.splitext(f)[1].lower()
            icon = file_icons.get(ext, "📄")
            
            item = QTreeWidgetItem()
            item.setText(0, f"{icon} {f}")
            item.setData(0, Qt.ItemDataRole.UserRole, full_path)
            
            # Color based on type
            if ext in (".py", ".mel", ".cs", ".lua"):
                item.setForeground(0, QColor("#d4d4d4"))
            else:
                item.setForeground(0, QColor("#969696"))
            
            parent_item.addChild(item)
    
    def _on_item_double_clicked(self, item, column):
        """Handle double-click on tree item."""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.isfile(path):
            self.file_open_requested.emit(path)
    
    def _on_directory_changed(self, path):
        """Refresh tree when watched directory changes."""
        self._refresh_tree()
    
    def get_workspace_folders(self):
        return list(self._workspace_folders)
    
    def set_workspace_folders(self, folders: list):
        self._workspace_folders = list(folders)
        for f in folders:
            self._watcher.addPath(f)
        self._refresh_tree()
        self._update_empty_state()


# =============================================================================
# Combined Sidebar
# =============================================================================

class ForgeSidebar(QWidget):
    """
    Combined sidebar containing all panels.
    In Simple mode: only Outline and Open Editors
    In Advanced mode: adds Workspace tree
    """
    
    file_open_requested = Signal(str)
    outline_item_clicked = Signal(int)
    editor_selected = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        
        # Workspace panel (Advanced mode only)
        self.workspace_panel = WorkspacePanel()
        self.workspace_panel.file_open_requested.connect(self.file_open_requested.emit)
        layout.addWidget(self.workspace_panel, stretch=3)
        
        # Open editors
        self.open_editors_panel = OpenEditorsPanel()
        self.open_editors_panel.editor_selected.connect(self.editor_selected.emit)
        layout.addWidget(self.open_editors_panel, stretch=1)
        
        # Code outline
        self.outline_panel = CodeOutlinePanel()
        self.outline_panel.item_clicked.connect(self.outline_item_clicked.emit)
        layout.addWidget(self.outline_panel, stretch=2)
    
    def set_simple_mode(self):
        """Switch to simple mode - hide workspace."""
        self.workspace_panel.setVisible(False)
    
    def set_advanced_mode(self):
        """Switch to advanced mode - show workspace."""
        self.workspace_panel.setVisible(True)
