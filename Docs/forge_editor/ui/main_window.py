"""
Forge Editor - Main Window
Central application window with dual-mode UI:
- Simple Mode: Charcoal Editor 2 style (tabs + editor + output)
- Advanced Mode: Full IDE (+ sidebar, AI panel, project folders)
"""

import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QToolBar, QStatusBar, QLabel, QComboBox, QPushButton,
    QFileDialog, QMessageBox, QDockWidget, QMenuBar, QMenu,
    QDialog, QFormLayout, QLineEdit, QSpinBox, QDialogButtonBox
)
from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QAction, QKeySequence, QFont, QIcon

from config.settings import ForgeSettings, EditorMode
from ui.code_editor import ForgeCodeEditor
from ui.output_window import OutputWindow
from ui.sidebar import ForgeSidebar
from ui.ai_panel import AIPanel
from adapters import AdapterManager, DCCType, ConnectionState


class ConnectionDialog(QDialog):
    """Dialog for connecting to a DCC application."""
    
    def __init__(self, adapter_manager: AdapterManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect to DCC Application")
        self.setMinimumWidth(350)
        self._adapter_manager = adapter_manager
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(8)
        
        self._dcc_combo = QComboBox()
        for dcc_type, adapter in self._adapter_manager.get_all_adapters().items():
            status = " ✓" if adapter.is_connected else ""
            self._dcc_combo.addItem(f"{adapter.display_name}{status}", dcc_type)
        layout.addRow("Application:", self._dcc_combo)
        
        self._host_input = QLineEdit("localhost")
        layout.addRow("Host:", self._host_input)
        
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(7001)
        self._dcc_combo.currentIndexChanged.connect(self._on_dcc_changed)
        self._on_dcc_changed(0)
        layout.addRow("Port:", self._port_input)
        
        # Auto-detect info
        detected = self._adapter_manager.detect_running_dccs()
        if detected:
            names = ", ".join(d["name"] for d in detected)
            detect_label = QLabel(f"Detected: {names}")
            detect_label.setStyleSheet("color: #4ec9b0; font-size: 11px;")
            layout.addRow("", detect_label)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def _on_dcc_changed(self, index):
        dcc_type = self._dcc_combo.currentData()
        adapter = self._adapter_manager.get_adapter(dcc_type)
        if adapter:
            self._port_input.setValue(adapter.default_port)
    
    def get_connection_info(self):
        return {
            "dcc_type": self._dcc_combo.currentData(),
            "host": self._host_input.text(),
            "port": self._port_input.value(),
        }


class ForgeMainWindow(QMainWindow):
    """
    Main application window.
    
    Layout (Simple Mode):
    ┌─────────────────────────────────────────┐
    │  Menu Bar                               │
    │  Toolbar                                │
    ├─────────────────────────────────────────┤
    │  ┌─────────────────────────────────────┐│
    │  │  Tab Bar (buffers)                  ││
    │  │  ┌─────────────────────────────────┐││
    │  │  │                                 │││
    │  │  │  Code Editor                    │││
    │  │  │                                 │││
    │  │  └─────────────────────────────────┘││
    │  └─────────────────────────────────────┘│
    │  ┌─────────────────────────────────────┐│
    │  │  Output Window                      ││
    │  └─────────────────────────────────────┘│
    ├─────────────────────────────────────────┤
    │  Status Bar                             │
    └─────────────────────────────────────────┘
    
    Layout (Advanced Mode):
    ┌──────────────────────────────────────────────────┐
    │  Menu Bar                                        │
    │  Toolbar                                         │
    ├──────────┬───────────────────────────┬───────────┤
    │          │  Tab Bar                  │           │
    │ Sidebar  │  ┌───────────────────────┐│ AI Panel  │
    │ (tree,   │  │  Code Editor          ││ (chat,    │
    │  outline,│  │                       ││  config)  │
    │  editors)│  └───────────────────────┘│           │
    │          │  ┌───────────────────────┐│           │
    │          │  │  Output Window        ││           │
    │          │  └───────────────────────┘│           │
    ├──────────┴───────────────────────────┴───────────┤
    │  Status Bar                                      │
    └──────────────────────────────────────────────────┘
    """
    
    def __init__(self, settings: ForgeSettings):
        super().__init__()
        self._settings = settings
        self._adapter_manager = AdapterManager()
        self._editors = []  # List of (editor, tab_name, file_path)
        self._editor_mode = settings.get_editor_mode()
        
        self.setWindowTitle("Forge Editor")
        self.setMinimumSize(900, 600)
        self.resize(1400, 850)
        
        self._setup_ui()
        self._setup_menus()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_connections()
        
        # Create initial buffer
        self._new_buffer()
        
        # Apply mode
        self._apply_editor_mode()
        
        # Auto-detect DCCs
        QTimer.singleShot(1000, self._auto_detect_dccs)
    
    def _setup_ui(self):
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Main horizontal splitter (sidebar | editor+output | ai panel)
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._main_splitter)
        
        # --- Sidebar ---
        self._sidebar = ForgeSidebar()
        self._sidebar.setMinimumWidth(180)
        self._sidebar.setMaximumWidth(400)
        self._main_splitter.addWidget(self._sidebar)
        
        # --- Center: Editor + Output ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        
        # Vertical splitter for editor tabs and output
        self._center_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Tab widget for code editors
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._center_splitter.addWidget(self._tab_widget)
        
        # Output window
        self._output = OutputWindow()
        self._center_splitter.addWidget(self._output)
        
        # Default split: 70% editor, 30% output
        self._center_splitter.setSizes([600, 250])
        
        center_layout.addWidget(self._center_splitter)
        self._main_splitter.addWidget(center_widget)
        
        # --- AI Panel ---
        self._ai_panel = AIPanel(self._settings)
        self._ai_panel.setMinimumWidth(250)
        self._ai_panel.setMaximumWidth(500)
        self._main_splitter.addWidget(self._ai_panel)
        
        # Default splitter sizes
        self._main_splitter.setSizes([240, 800, 0])
    
    def _setup_menus(self):
        """Build the menu bar."""
        menubar = self.menuBar()
        
        # ---- File Menu ----
        file_menu = menubar.addMenu("&File")
        
        new_action = file_menu.addAction("New Buffer")
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self._new_buffer)
        
        open_action = file_menu.addAction("Open File...")
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._open_file)
        
        file_menu.addSeparator()
        
        save_action = file_menu.addAction("Save")
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self._save_file)
        
        save_as_action = file_menu.addAction("Save As...")
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self._save_file_as)
        
        file_menu.addSeparator()
        
        close_action = file_menu.addAction("Close Tab")
        close_action.setShortcut(QKeySequence("Ctrl+W"))
        close_action.triggered.connect(lambda: self._close_tab(self._tab_widget.currentIndex()))
        
        # ---- Edit Menu ----
        edit_menu = menubar.addMenu("&Edit")
        
        undo = edit_menu.addAction("Undo")
        undo.setShortcut(QKeySequence("Ctrl+Z"))
        undo.triggered.connect(lambda: self._current_editor() and self._current_editor().undo())
        
        redo = edit_menu.addAction("Redo")
        redo.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        redo.triggered.connect(lambda: self._current_editor() and self._current_editor().redo())
        
        edit_menu.addSeparator()
        
        find_action = edit_menu.addAction("Find...")
        find_action.setShortcut(QKeySequence("Ctrl+F"))
        find_action.triggered.connect(self._show_find)
        
        goto_action = edit_menu.addAction("Go to Line...")
        goto_action.setShortcut(QKeySequence("Ctrl+G"))
        goto_action.triggered.connect(self._show_goto_line)
        
        # ---- Execute Menu ----
        exec_menu = menubar.addMenu("E&xecute")
        
        exec_all = exec_menu.addAction("Execute Script")
        exec_all.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        exec_all.triggered.connect(self._execute_all)
        
        exec_sel = exec_menu.addAction("Execute Selected")
        exec_sel.setShortcut(QKeySequence("Ctrl+Return"))
        exec_sel.triggered.connect(self._execute_selected)
        
        exec_line = exec_menu.addAction("Execute Current Line")
        exec_line.setShortcut(QKeySequence("Ctrl+Alt+Return"))
        exec_line.triggered.connect(self._execute_line)
        
        # ---- View Menu ----
        view_menu = menubar.addMenu("&View")
        
        self._simple_mode_action = view_menu.addAction("Simple Mode")
        self._simple_mode_action.setCheckable(True)
        self._simple_mode_action.triggered.connect(lambda: self._set_editor_mode(EditorMode.SIMPLE))
        
        self._advanced_mode_action = view_menu.addAction("Advanced Mode")
        self._advanced_mode_action.setCheckable(True)
        self._advanced_mode_action.triggered.connect(lambda: self._set_editor_mode(EditorMode.ADVANCED))
        
        view_menu.addSeparator()
        
        self._toggle_sidebar_action = view_menu.addAction("Toggle Sidebar")
        self._toggle_sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        self._toggle_sidebar_action.triggered.connect(self._toggle_sidebar)
        
        self._toggle_output_action = view_menu.addAction("Toggle Output")
        self._toggle_output_action.setShortcut(QKeySequence("Ctrl+`"))
        self._toggle_output_action.triggered.connect(self._toggle_output)
        
        self._toggle_ai_action = view_menu.addAction("Toggle AI Panel")
        self._toggle_ai_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self._toggle_ai_action.triggered.connect(self._toggle_ai_panel)
        
        # ---- DCC Menu ----
        dcc_menu = menubar.addMenu("&DCC")
        
        connect_action = dcc_menu.addAction("Connect to DCC...")
        connect_action.triggered.connect(self._show_connect_dialog)
        
        disconnect_action = dcc_menu.addAction("Disconnect")
        disconnect_action.triggered.connect(self._disconnect_dcc)
        
        dcc_menu.addSeparator()
        
        detect_action = dcc_menu.addAction("Detect Running DCCs")
        detect_action.triggered.connect(self._auto_detect_dccs)
        
        # ---- Help Menu ----
        help_menu = menubar.addMenu("&Help")
        about_action = help_menu.addAction("About Forge Editor")
        about_action.triggered.connect(self._show_about)
    
    def _setup_toolbar(self):
        """Build the main toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #2d2d30;
                border-bottom: 1px solid #3f3f46;
                padding: 2px 4px;
                spacing: 2px;
            }
            QToolButton {
                background: transparent;
                color: #cccccc;
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QToolButton:hover {
                background-color: #3e3e42;
            }
            QToolButton:pressed {
                background-color: #094771;
            }
        """)
        self.addToolBar(toolbar)
        
        # File operations
        toolbar.addAction("📄 New").triggered.connect(self._new_buffer)
        toolbar.addAction("📂 Open").triggered.connect(self._open_file)
        toolbar.addAction("💾 Save").triggered.connect(self._save_file)
        
        toolbar.addSeparator()
        
        # Execution buttons (like Charcoal Editor 2)
        exec_all_btn = toolbar.addAction("▶ Execute")
        exec_all_btn.setToolTip("Execute entire script (Ctrl+Shift+Enter)")
        exec_all_btn.triggered.connect(self._execute_all)
        
        exec_sel_btn = toolbar.addAction("▶| Selected")
        exec_sel_btn.setToolTip("Execute selected text (Ctrl+Enter)")
        exec_sel_btn.triggered.connect(self._execute_selected)
        
        exec_line_btn = toolbar.addAction("▶_ Line")
        exec_line_btn.setToolTip("Execute current line (Ctrl+Alt+Enter)")
        exec_line_btn.triggered.connect(self._execute_line)
        
        toolbar.addSeparator()
        
        # Language selector
        lang_label = QLabel("  Language: ")
        lang_label.setStyleSheet("color: #969696; font-size: 11px;")
        toolbar.addWidget(lang_label)
        
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["Python", "MEL"])
        self._lang_combo.setFixedWidth(90)
        self._lang_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: #d4d4d4;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }
        """)
        self._lang_combo.currentTextChanged.connect(self._on_language_changed)
        toolbar.addWidget(self._lang_combo)
        
        toolbar.addSeparator()
        
        # DCC connection indicator
        self._dcc_indicator = QPushButton("● No DCC")
        self._dcc_indicator.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #666666;
                border: none;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3e3e42;
            }
        """)
        self._dcc_indicator.clicked.connect(self._show_connect_dialog)
        toolbar.addWidget(self._dcc_indicator)
        
        # Spacer
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)
        
        # Mode toggle
        self._mode_toggle = QPushButton("☰ Advanced")
        self._mode_toggle.setToolTip("Toggle Simple/Advanced mode")
        self._mode_toggle.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4e4e52;
            }
        """)
        self._mode_toggle.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self._mode_toggle)
    
    def _setup_statusbar(self):
        """Build the status bar."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        
        # Cursor position
        self._pos_label = QLabel("Ln 1, Col 1")
        self._pos_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(self._pos_label)
        
        # Language
        self._lang_label = QLabel("Python")
        self._lang_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(self._lang_label)
        
        # Encoding
        encoding_label = QLabel("UTF-8")
        encoding_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(encoding_label)
        
        # Mode indicator
        self._mode_label = QLabel("Simple")
        self._mode_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(self._mode_label)
    
    def _setup_connections(self):
        """Wire up signals between components."""
        # Sidebar signals
        self._sidebar.file_open_requested.connect(self._open_file_path)
        self._sidebar.outline_item_clicked.connect(self._goto_outline_item)
        self._sidebar.editor_selected.connect(self._tab_widget.setCurrentIndex)
        
        # Adapter manager
        self._adapter_manager.set_connection_callback(self._update_dcc_status)
        
        # Set output callbacks for adapters
        for adapter in self._adapter_manager.get_all_adapters().values():
            adapter.set_output_callback(self._output.write_output)
            adapter.set_error_callback(self._output.write_error)
    
    # ======================================================================
    # Editor Mode (Simple / Advanced)
    # ======================================================================
    
    def _set_editor_mode(self, mode: EditorMode):
        """Switch between simple and advanced mode."""
        self._editor_mode = mode
        self._settings.set_editor_mode(mode)
        self._apply_editor_mode()
    
    def _apply_editor_mode(self):
        """Apply the current editor mode to the UI."""
        is_simple = self._editor_mode == EditorMode.SIMPLE
        
        if is_simple:
            # Simple mode: hide sidebar and AI panel
            self._sidebar.setVisible(False)
            self._ai_panel.setVisible(False)
            self._main_splitter.setSizes([0, 1000, 0])
            self._mode_toggle.setText("☰ Advanced")
            self._mode_label.setText("Simple")
            self._simple_mode_action.setChecked(True)
            self._advanced_mode_action.setChecked(False)
        else:
            # Advanced mode: show sidebar, AI panel hidden by default
            self._sidebar.setVisible(True)
            self._sidebar.set_advanced_mode()
            self._ai_panel.setVisible(False)
            self._main_splitter.setSizes([240, 800, 0])
            self._mode_toggle.setText("☰ Simple")
            self._mode_label.setText("Advanced")
            self._simple_mode_action.setChecked(False)
            self._advanced_mode_action.setChecked(True)
    
    def _toggle_mode(self):
        """Toggle between simple and advanced mode."""
        if self._editor_mode == EditorMode.SIMPLE:
            self._set_editor_mode(EditorMode.ADVANCED)
        else:
            self._set_editor_mode(EditorMode.SIMPLE)
    
    def _toggle_sidebar(self):
        self._sidebar.setVisible(not self._sidebar.isVisible())
    
    def _toggle_output(self):
        self._output.setVisible(not self._output.isVisible())
    
    def _toggle_ai_panel(self):
        visible = not self._ai_panel.isVisible()
        self._ai_panel.setVisible(visible)
        if visible:
            sizes = self._main_splitter.sizes()
            if sizes[-1] == 0:
                total = sum(sizes)
                sizes[-1] = 300
                sizes[1] = total - sizes[0] - sizes[-1]
                self._main_splitter.setSizes(sizes)
    
    # ======================================================================
    # Tab / Buffer Management (like Charcoal Editor 2)
    # ======================================================================
    
    def _current_editor(self) -> ForgeCodeEditor:
        """Get the currently active code editor."""
        widget = self._tab_widget.currentWidget()
        if isinstance(widget, ForgeCodeEditor):
            return widget
        return None
    
    def _new_buffer(self):
        """Create a new temporary buffer (like CE2's temp buffers)."""
        editor = ForgeCodeEditor()
        
        # Connect editor signals
        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))
        
        # Determine tab name
        buffer_num = len([e for e in self._editors if e[2] is None]) + 1
        tab_name = f"Buffer {buffer_num}"
        
        idx = self._tab_widget.addTab(editor, tab_name)
        self._editors.append((editor, tab_name, None))
        self._tab_widget.setCurrentIndex(idx)
        
        self._update_open_editors()
        return editor
    
    def _open_file(self):
        """Open a file from disk."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "Script Files (*.py *.mel *.cs *.lua);;Python Files (*.py);;MEL Files (*.mel);;All Files (*.*)"
        )
        if filepath:
            self._open_file_path(filepath)
    
    def _open_file_path(self, filepath: str):
        """Open a specific file."""
        # Check if already open
        for i, (editor, name, path) in enumerate(self._editors):
            if path == filepath:
                self._tab_widget.setCurrentIndex(i)
                return
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{str(e)}")
            return
        
        editor = ForgeCodeEditor()
        editor.file_path = filepath
        editor.setPlainText(content)
        editor.document().setModified(False)
        
        # Connect signals
        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))
        
        tab_name = os.path.basename(filepath)
        idx = self._tab_widget.addTab(editor, tab_name)
        self._editors.append((editor, tab_name, filepath))
        self._tab_widget.setCurrentIndex(idx)
        
        self._settings.add_recent_file(filepath)
        self._update_open_editors()
        self._update_language_combo(editor)
    
    def _save_file(self):
        """Save the current file."""
        editor = self._current_editor()
        if not editor:
            return
        
        if editor.file_path:
            self._write_file(editor, editor.file_path)
        else:
            self._save_file_as()
    
    def _save_file_as(self):
        """Save the current file with a new name."""
        editor = self._current_editor()
        if not editor:
            return
        
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save File", "",
            "Python Files (*.py);;MEL Files (*.mel);;All Files (*.*)"
        )
        if filepath:
            self._write_file(editor, filepath)
            editor.file_path = filepath
            
            # Update tab and tracking
            idx = self._tab_widget.currentIndex()
            tab_name = os.path.basename(filepath)
            self._tab_widget.setTabText(idx, tab_name)
            self._editors[idx] = (editor, tab_name, filepath)
            self._settings.add_recent_file(filepath)
            self._update_open_editors()
    
    def _write_file(self, editor: ForgeCodeEditor, filepath: str):
        """Write editor content to file."""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(editor.toPlainText())
            editor.document().setModified(False)
            self._output.write_info(f"Saved: {filepath}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save file:\n{str(e)}")
    
    def _close_tab(self, index):
        """Close a tab/buffer."""
        if index < 0 or index >= len(self._editors):
            return
        
        editor, name, path = self._editors[index]
        
        if editor.document().isModified():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                f"'{name}' has unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                self._tab_widget.setCurrentIndex(index)
                self._save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        self._tab_widget.removeTab(index)
        self._editors.pop(index)
        self._update_open_editors()
        
        # Ensure at least one buffer
        if self._tab_widget.count() == 0:
            self._new_buffer()
    
    def _on_tab_changed(self, index):
        """Handle tab selection change."""
        editor = self._current_editor()
        if editor:
            self._update_outline(editor)
            self._update_language_combo(editor)
            self._update_cursor_pos(
                editor.textCursor().blockNumber() + 1,
                editor.textCursor().columnNumber() + 1
            )
    
    def _on_editor_modified(self, editor: ForgeCodeEditor, modified: bool):
        """Handle editor modification state change."""
        for i, (e, name, path) in enumerate(self._editors):
            if e is editor:
                display = f"● {name}" if modified else name
                self._tab_widget.setTabText(i, display)
                break
        self._update_open_editors()
    
    def _update_open_editors(self):
        """Update the sidebar's open editors list."""
        tabs = []
        for editor, name, path in self._editors:
            tabs.append({
                "name": name,
                "path": path,
                "modified": editor.document().isModified(),
                "language": editor.language,
            })
        self._sidebar.open_editors_panel.update_editors(tabs)
    
    def _update_outline(self, editor: ForgeCodeEditor):
        """Update the code outline from the current editor."""
        outline = editor.get_code_outline()
        self._sidebar.outline_panel.update_outline(outline)
    
    def _goto_outline_item(self, line: int):
        """Jump to a line from the outline panel."""
        editor = self._current_editor()
        if editor:
            editor.go_to_line(line)
    
    def _update_language_combo(self, editor: ForgeCodeEditor):
        """Sync the language combo with the editor's language."""
        lang_map = {"python": "Python", "mel": "MEL"}
        display = lang_map.get(editor.language, "Python")
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentText(display)
        self._lang_combo.blockSignals(False)
        self._lang_label.setText(display)
    
    def _on_language_changed(self, language: str):
        """Handle language combo change."""
        editor = self._current_editor()
        if editor:
            editor.set_language(language.lower())
            self._lang_label.setText(language)
    
    def _update_cursor_pos(self, line: int, col: int):
        """Update status bar cursor position."""
        self._pos_label.setText(f"Ln {line}, Col {col}")
    
    # ======================================================================
    # Execution (Critical CE2 feature: NEVER deletes code on execute)
    # ======================================================================
    
    def _execute_all(self):
        """Execute the entire script in the connected DCC."""
        editor = self._current_editor()
        if not editor:
            return
        
        code = editor.get_all_text()
        if not code.strip():
            return
        
        # Auto-save before execute (like CE2)
        if self._settings.get("auto_save_on_execute") and editor.file_path:
            self._write_file(editor, editor.file_path)
        
        self._output.write_execution_header(
            "Full Script",
            self._get_active_dcc_name()
        )
        
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            adapter.execute(code, editor.language)
        else:
            # Local execution fallback for Python
            if editor.language == "python":
                self._execute_locally(code)
            else:
                self._output.write_warning("No DCC connected. Connect to a DCC to execute.")
    
    def _execute_selected(self):
        """Execute selected text (or all if nothing selected)."""
        editor = self._current_editor()
        if not editor:
            return
        
        code = editor.get_selected_text()
        if not code.strip():
            return
        
        self._output.write_execution_header(
            "Selected Text",
            self._get_active_dcc_name()
        )
        
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            adapter.execute(code, editor.language)
        else:
            if editor.language == "python":
                self._execute_locally(code)
            else:
                self._output.write_warning("No DCC connected. Connect to a DCC to execute.")
    
    def _execute_line(self):
        """Execute the current line."""
        editor = self._current_editor()
        if not editor:
            return
        
        code = editor.get_current_line_text()
        if not code.strip():
            return
        
        self._output.write_execution_header(
            "Current Line",
            self._get_active_dcc_name()
        )
        
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            adapter.execute(code, editor.language)
        else:
            if editor.language == "python":
                self._execute_locally(code)
            else:
                self._output.write_warning("No DCC connected.")
    
    def _execute_locally(self, code: str):
        """Execute Python code locally (when no DCC connected)."""
        import io
        import sys
        import traceback
        
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        
        try:
            exec(code, {"__builtins__": __builtins__})
            output = sys.stdout.getvalue()
            errors = sys.stderr.getvalue()
            
            if output:
                self._output.write_output(output.rstrip())
            if errors:
                self._output.write_warning(errors.rstrip())
            
            self._output.write_success("✓ Executed locally (no DCC)")
        except Exception:
            tb = traceback.format_exc()
            self._output.write_error(tb.rstrip())
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    # ======================================================================
    # DCC Connection
    # ======================================================================
    
    def _show_connect_dialog(self):
        """Show the DCC connection dialog."""
        dialog = ConnectionDialog(self._adapter_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            info = dialog.get_connection_info()
            self._output.write_info(
                f"Connecting to {info['dcc_type'].value} at {info['host']}:{info['port']}..."
            )
            success = self._adapter_manager.connect(
                info["dcc_type"], info["host"], info["port"]
            )
            if success:
                self._output.write_success(f"Connected to {info['dcc_type'].value}!")
    
    def _disconnect_dcc(self):
        """Disconnect from the active DCC."""
        self._adapter_manager.disconnect_all()
    
    def _update_dcc_status(self):
        """Update the DCC connection indicator."""
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            self._dcc_indicator.setText(f"● {adapter.display_name}")
            self._dcc_indicator.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #4ec9b0;
                    border: none; padding: 4px 8px; font-size: 11px;
                }
                QPushButton:hover { background-color: #3e3e42; }
            """)
        else:
            self._dcc_indicator.setText("● No DCC")
            self._dcc_indicator.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #666666;
                    border: none; padding: 4px 8px; font-size: 11px;
                }
                QPushButton:hover { background-color: #3e3e42; }
            """)
    
    def _auto_detect_dccs(self):
        """Auto-detect running DCC applications."""
        detected = self._adapter_manager.detect_running_dccs()
        if detected:
            names = ", ".join(d["name"] for d in detected)
            self._output.write_info(f"Detected running DCCs: {names}")
            self._statusbar.showMessage(f"Detected: {names}", 5000)
    
    def _get_active_dcc_name(self) -> str:
        adapter = self._adapter_manager.get_active_adapter()
        return adapter.display_name if adapter else "Local Python"
    
    # ======================================================================
    # Find / Go To
    # ======================================================================
    
    def _show_find(self):
        """Show find dialog (placeholder for full implementation)."""
        self._statusbar.showMessage("Find: Ctrl+F (full search coming soon)", 3000)
    
    def _show_goto_line(self):
        """Show go-to-line dialog."""
        editor = self._current_editor()
        if not editor:
            return
        
        from PySide6.QtWidgets import QInputDialog
        line, ok = QInputDialog.getInt(
            self, "Go to Line", "Line number:",
            editor.textCursor().blockNumber() + 1,
            1, editor.document().blockCount()
        )
        if ok:
            editor.go_to_line(line)
    
    # ======================================================================
    # About
    # ======================================================================
    
    def _show_about(self):
        QMessageBox.about(
            self, "About Forge Editor",
            "<h3>Forge Editor v0.1.0</h3>"
            "<p>Cross-DCC Script IDE</p>"
            "<p>Spiritual successor to Charcoal Editor 2.<br>"
            "Supports Maya, Blender, Unreal Engine, Unity, and more.</p>"
            "<p><b>Features:</b><br>"
            "• Dual mode: Simple (script editor) &amp; Advanced (IDE)<br>"
            "• Multi-DCC connection via adapters<br>"
            "• AI integration (BYOK or managed)<br>"
            "• Plugin architecture for extensions</p>"
            "<hr>"
            "<p style='color: #888;'>Built with PySide6 (Qt6)</p>"
        )
    
    # ======================================================================
    # Window State
    # ======================================================================
    
    def closeEvent(self, event):
        """Save state on close."""
        # Check for unsaved changes
        for editor, name, path in self._editors:
            if editor.document().isModified():
                reply = QMessageBox.question(
                    self, "Unsaved Changes",
                    "You have unsaved changes. Quit anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    event.ignore()
                    return
                break
        
        # Save window state
        self._settings.set("window_geometry", self.saveGeometry())
        self._settings.set("window_state", self.saveState())
        self._settings.sync()
        
        # Disconnect from DCCs
        self._adapter_manager.disconnect_all()
        
        event.accept()
