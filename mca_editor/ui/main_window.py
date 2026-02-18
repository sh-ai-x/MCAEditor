"""
MCA Editor - Main Window.

Central application window with dual-mode UI:
    - Simple Mode: Charcoal Editor 2 style (tabs + editor + output)
    - Advanced Mode: Full IDE (+ sidebar, AI panel, project folders)

This module ties all UI components together: tab management, menu bar,
toolbar, status bar, execution routing, and DCC connection dialogs.

Dependencies:
    - PySide6 (QMainWindow, QSplitter, QTabWidget, etc.)

Side Effects:
    - Reads/writes window geometry to QSettings on open/close.
"""

import io
import os
import sys
import logging
import traceback
import webbrowser

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QToolBar, QStatusBar, QLabel, QComboBox, QPushButton,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QLineEdit,
    QSpinBox, QDialogButtonBox, QInputDialog
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QTextCursor

from mca_editor.config.settings import MCASettings, EditorMode
from mca_editor.ui.code_editor import MCACodeEditor
from mca_editor.ui.output_window import OutputWindow
from mca_editor.ui.sidebar import MCASidebar
from mca_editor.ui.ai_panel import AIPanel
from mca_editor.ui.settings_dialog import SettingsDialog
from mca_editor.adapters import AdapterManager, DCCType, ConnectionState

# Module-level logger for main window operations.
logger = logging.getLogger(__name__)


# =============================================================================
# DCC Connection Dialog
# =============================================================================

class ConnectionDialog(QDialog):
    """
    Dialog for connecting to a DCC application.

    Presents a dropdown of registered adapters (Maya-only for now),
    host/port fields, and auto-detection results.

    :param AdapterManager adapter_manager: The adapter manager instance.
    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, adapter_manager, parent=None):
        """
        Initialize the connection dialog.

        :param AdapterManager adapter_manager: The adapter manager.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Connect to DCC Application")
        self.setMinimumWidth(350)
        self._adapter_manager = adapter_manager
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog layout: DCC selection, host, port, buttons."""
        layout = QFormLayout(self)
        layout.setSpacing(8)

        # DCC application dropdown (shows connection status).
        self._dcc_combo = QComboBox()
        for dcc_type, adapter in self._adapter_manager.get_all_adapters().items():
            status = " [Connected]" if adapter.is_connected else ""
            self._dcc_combo.addItem(
                "{}{}".format(adapter.display_name, status),
                dcc_type
            )
        layout.addRow("Application:", self._dcc_combo)

        # Host input field.
        self._host_input = QLineEdit("localhost")
        layout.addRow("Host:", self._host_input)

        # Port input with auto-update when DCC selection changes.
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(7001)
        self._dcc_combo.currentIndexChanged.connect(self._on_dcc_changed)
        self._on_dcc_changed(0)
        layout.addRow("Port:", self._port_input)

        # Show auto-detected DCC processes.
        detected = self._adapter_manager.detect_running_dccs()
        if detected:
            names = ", ".join(d["name"] for d in detected)
            detect_label = QLabel("Detected: {}".format(names))
            detect_label.setStyleSheet("color: #4ec9b0; font-size: 11px;")
            layout.addRow("", detect_label)

        # OK/Cancel buttons.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_dcc_changed(self, index):
        """
        Update the port field when the DCC selection changes.

        :param int index: The new combo box index.
        """
        dcc_type = self._dcc_combo.currentData()
        adapter = self._adapter_manager.get_adapter(dcc_type)
        if adapter:
            self._port_input.setValue(adapter.default_port)

    def get_connection_info(self):
        """
        Get the user's connection settings.

        :return: Dict with 'dcc_type', 'host', and 'port' keys.
        :rtype: dict
        """
        return {
            "dcc_type": self._dcc_combo.currentData(),
            "host": self._host_input.text(),
            "port": self._port_input.value(),
        }


# =============================================================================
# Main Window
# =============================================================================

class MCAMainWindow(QMainWindow):
    """
    Main application window for MCA Editor.

    Layout (Simple Mode)::

        +---------------------------------------+
        |  Menu Bar                             |
        |  Toolbar                              |
        |---------------------------------------|
        |  +-------------------------------+    |
        |  |  Output Window                |    |
        |  +-------------------------------+    |
        |  Tab Bar (Python, MEL, ...)           |
        |  +-------------------------------+    |
        |  |  Code Editor                  |    |
        |  +-------------------------------+    |
        |---------------------------------------|
        |  Status Bar                           |
        +---------------------------------------+

    Layout (Advanced Mode)::

        +----------------------------------------------+
        |  Menu Bar                                    |
        |  Toolbar                                     |
        +----------+--------------------------+--------+
        |          |  Output Window           |        |
        | Sidebar  |--------------------------| AI     |
        | (tree,   |  Tab Bar                 | Panel  |
        |  outline)|  Code Editor             |        |
        +----------+--------------------------+--------+
        |  Status Bar                                  |
        +----------------------------------------------+

    :param MCASettings settings: Application settings instance.
    """

    def __init__(self, settings):
        """
        Initialize the main window and all UI components.

        :param MCASettings settings: Application settings instance.
        """
        super().__init__()
        self._settings = settings
        self._adapter_manager = AdapterManager()
        self._editors = []  # List of (editor, tab_name, file_path) tuples
        self._editor_mode = settings.get_editor_mode()
        self._closed_files = []  # Track recently closed files for reopen feature.
        self._default_font_size = 12  # Base font size for zoom calculations.
        self._verbosity_level = "normal"  # Output verbosity: echo_all, normal, minimal.
        self._action_registry = {}  # name -> QAction, for keyboard shortcut editor.
        # Persistent namespace for local Python execution so variables survive
        # across multiple Execute calls (same behavior as Maya's interpreter).
        self._local_namespace = {"__builtins__": __builtins__}

        self.setWindowTitle("MCA Editor")
        self.setMinimumSize(900, 600)
        self.resize(1400, 850)

        # Build UI components in order.
        self._setup_ui()
        self._setup_menus()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_connections()

        # Create the first empty buffer (like Charcoal Editor 2).
        self._new_buffer()

        # Apply the saved editor mode.
        self._apply_editor_mode()

        # Auto-detect running DCCs after a short delay.
        QTimer.singleShot(1000, self._auto_detect_dccs)

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the main UI layout with splitters and panels."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Main horizontal splitter: sidebar | editor+output | AI panel.
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._main_splitter)

        # --- Sidebar (left panel) ---
        self._sidebar = MCASidebar()
        self._sidebar.setMinimumWidth(180)
        self._sidebar.setMaximumWidth(400)
        self._main_splitter.addWidget(self._sidebar)

        # --- Center: editor tabs + output ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # Vertical splitter for output and editor tabs (output on top, like CE2).
        self._center_splitter = QSplitter(Qt.Orientation.Vertical)

        # Output window (top panel, like Charcoal Editor 2 layout).
        self._output = OutputWindow()
        self._center_splitter.addWidget(self._output)

        # Tab widget for code editor buffers (below output).
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._center_splitter.addWidget(self._tab_widget)

        # Default split: 30% output (top), 70% editor (bottom).
        self._center_splitter.setSizes([250, 600])

        center_layout.addWidget(self._center_splitter)
        self._main_splitter.addWidget(center_widget)

        # --- AI Panel (right panel) ---
        self._ai_panel = AIPanel(self._settings)
        self._ai_panel.setMinimumWidth(250)
        self._ai_panel.setMaximumWidth(500)
        self._main_splitter.addWidget(self._ai_panel)

        # Default: sidebar visible, AI panel hidden.
        self._main_splitter.setSizes([240, 800, 0])

    def _setup_menus(self):
        """Build the menu bar with all menus and actions matching CE2 layout."""
        menubar = self.menuBar()

        # =================================================================
        # File Menu
        # =================================================================
        file_menu = menubar.addMenu("&File")

        new_action = file_menu.addAction("New...")
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self._new_buffer)
        self._register_action("New Buffer", new_action)

        new_mel = file_menu.addAction("New MEL Buffer")
        new_mel.setShortcut(QKeySequence("Ctrl+Alt+N"))
        new_mel.triggered.connect(self._new_mel_buffer)
        self._register_action("New MEL Buffer", new_mel)

        new_py = file_menu.addAction("New Python Buffer")
        new_py.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_py.triggered.connect(self._new_python_buffer)
        self._register_action("New Python Buffer", new_py)

        open_action = file_menu.addAction("Open File...")
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._open_file)
        self._register_action("Open File", open_action)

        # Recent Files submenu (rebuilt dynamically).
        self._recent_files_menu = file_menu.addMenu("Recent Files")
        self._build_recent_files_menu()

        file_menu.addSeparator()

        open_ws = file_menu.addAction("Open Workspace...")
        open_ws.triggered.connect(self._open_workspace)

        add_folder = file_menu.addAction("Add Folder to Workspace...")
        add_folder.triggered.connect(self._add_folder_to_workspace)

        save_ws = file_menu.addAction("Save Workspace As...")
        save_ws.triggered.connect(
            lambda: self._statusbar.showMessage("Save Workspace As: coming soon", 3000)
        )

        file_menu.addSeparator()

        save_action = file_menu.addAction("Save")
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self._save_file)
        self._register_action("Save", save_action)

        save_as_action = file_menu.addAction("Save As...")
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self._save_file_as)
        self._register_action("Save As", save_as_action)

        save_all = file_menu.addAction("Save All")
        save_all.triggered.connect(self._save_all)
        self._register_action("Save All", save_all)

        rename = file_menu.addAction("Rename...")
        rename.triggered.connect(self._rename_file)
        self._register_action("Rename", rename)

        file_menu.addSeparator()

        save_shelf = file_menu.addAction("Save Script to Shelf...")
        save_shelf.triggered.connect(self._save_to_shelf)
        self._register_action("Save Script to Shelf", save_shelf)

        source = file_menu.addAction("Source Script...")
        source.triggered.connect(self._source_script)
        self._register_action("Source Script", source)

        file_menu.addSeparator()

        revert = file_menu.addAction("Revert File")
        revert.triggered.connect(self._revert_file)
        self._register_action("Revert File", revert)

        close_action = file_menu.addAction("Close File")
        close_action.setShortcut(QKeySequence("Ctrl+W"))
        close_action.triggered.connect(lambda: self._close_tab(self._tab_widget.currentIndex()))
        self._register_action("Close File", close_action)

        close_all = file_menu.addAction("Close All Files")
        close_all.triggered.connect(self._close_all_files)
        self._register_action("Close All Files", close_all)

        save_state = file_menu.addAction("Save State")
        save_state.triggered.connect(self._save_state)
        self._register_action("Save State", save_state)

        # =================================================================
        # Edit Menu
        # =================================================================
        edit_menu = menubar.addMenu("&Edit")

        undo = edit_menu.addAction("Undo")
        undo.setShortcut(QKeySequence("Ctrl+Z"))
        undo.triggered.connect(lambda: self._current_editor() and self._current_editor().undo())
        self._register_action("Undo", undo)

        redo = edit_menu.addAction("Redo")
        redo.setShortcut(QKeySequence("Ctrl+Y"))
        redo.triggered.connect(lambda: self._current_editor() and self._current_editor().redo())
        self._register_action("Redo", redo)

        edit_menu.addSeparator()

        # NOTE: Cut/Copy/Paste/Select All do NOT register global shortcuts.
        # Qt widgets (editor, output) handle Ctrl+C/X/V/A natively based on
        # which widget has focus. Registering them on QActions would hijack
        # the keys away from the output window and other widgets.
        cut = edit_menu.addAction("Cut\tCtrl+X")
        cut.triggered.connect(lambda: self._current_editor() and self._current_editor().cut())

        copy = edit_menu.addAction("Copy\tCtrl+C")
        copy.triggered.connect(lambda: self._current_editor() and self._current_editor().copy())

        paste = edit_menu.addAction("Paste\tCtrl+V")
        paste.triggered.connect(lambda: self._current_editor() and self._current_editor().paste())

        select_all = edit_menu.addAction("Select All\tCtrl+A")
        select_all.triggered.connect(
            lambda: self._current_editor() and self._current_editor().selectAll()
        )

        edit_menu.addSeparator()

        # Line operations submenu.
        line_menu = edit_menu.addMenu("Line")

        inc_indent = line_menu.addAction("Increase Indent")
        inc_indent.setShortcut(QKeySequence("Ctrl+]"))
        inc_indent.triggered.connect(self._increase_indent)
        self._register_action("Increase Indent", inc_indent)

        dec_indent = line_menu.addAction("Decrease Indent")
        dec_indent.setShortcut(QKeySequence("Ctrl+["))
        dec_indent.triggered.connect(self._decrease_indent)
        self._register_action("Decrease Indent", dec_indent)

        copy_up = line_menu.addAction("Copy Line Up")
        copy_up.setShortcut(QKeySequence("Alt+Shift+Up"))
        copy_up.triggered.connect(self._copy_line_up)
        self._register_action("Copy Line Up", copy_up)

        copy_down = line_menu.addAction("Copy Line Down")
        copy_down.setShortcut(QKeySequence("Alt+Shift+Down"))
        copy_down.triggered.connect(self._copy_line_down)
        self._register_action("Copy Line Down", copy_down)

        move_up = line_menu.addAction("Move Line Up")
        move_up.setShortcut(QKeySequence("Alt+Up"))
        move_up.triggered.connect(self._move_line_up)
        self._register_action("Move Line Up", move_up)

        move_down = line_menu.addAction("Move Line Down")
        move_down.setShortcut(QKeySequence("Alt+Down"))
        move_down.triggered.connect(self._move_line_down)
        self._register_action("Move Line Down", move_down)

        del_line = line_menu.addAction("Delete Line")
        del_line.setShortcut(QKeySequence("Ctrl+Shift+K"))
        del_line.triggered.connect(self._delete_line)
        self._register_action("Delete Line", del_line)

        # Comment submenu.
        comment_menu = edit_menu.addMenu("Comment")

        # NOTE: No shortcut registered here because code_editor.py's keyPressEvent
        # already handles Ctrl+/ directly. A menu shortcut would double-trigger.
        toggle_comment = comment_menu.addAction("Toggle Line Comment\tCtrl+/")
        toggle_comment.triggered.connect(self._toggle_comment_action)
        self._register_action("Toggle Line Comment", toggle_comment)

        block_comment = comment_menu.addAction("Toggle Block Comment")
        block_comment.triggered.connect(self._toggle_block_comment)
        self._register_action("Toggle Block Comment", block_comment)

        convert_tabs = edit_menu.addAction("Convert Tabs to Spaces")
        convert_tabs.triggered.connect(self._convert_tabs_to_spaces)
        self._register_action("Convert Tabs to Spaces", convert_tabs)

        edit_menu.addSeparator()

        find_action = edit_menu.addAction("Find...")
        find_action.setShortcut(QKeySequence("Ctrl+F"))
        find_action.triggered.connect(self._show_find)
        self._register_action("Find", find_action)

        replace_action = edit_menu.addAction("Replace...")
        replace_action.setShortcut(QKeySequence("Ctrl+H"))
        replace_action.triggered.connect(self._show_replace)
        self._register_action("Replace", replace_action)

        find_files = edit_menu.addAction("Find in Files...")
        find_files.setShortcut(QKeySequence("Ctrl+Shift+F"))
        find_files.triggered.connect(self._find_in_files)
        self._register_action("Find in Files", find_files)

        replace_files = edit_menu.addAction("Replace in Files...")
        replace_files.setShortcut(QKeySequence("Ctrl+Shift+H"))
        replace_files.triggered.connect(self._replace_in_files)
        self._register_action("Replace in Files", replace_files)

        edit_menu.addSeparator()

        insert_path = edit_menu.addAction("Insert Path...")
        insert_path.triggered.connect(self._insert_path)
        self._register_action("Insert Path", insert_path)

        clear_output = edit_menu.addAction("Clear Output")
        clear_output.setShortcut(QKeySequence("Ctrl+Shift+1"))
        clear_output.triggered.connect(self._clear_output)
        self._register_action("Clear Output", clear_output)

        edit_menu.addSeparator()

        prefs = edit_menu.addAction("Settings...")
        prefs.setShortcut(QKeySequence("Ctrl+Shift+P"))
        prefs.triggered.connect(self._show_settings)

        # =================================================================
        # View Menu
        # =================================================================
        view_menu = menubar.addMenu("&View")

        explorer = view_menu.addAction("Explorer")
        explorer.setShortcut(QKeySequence("Ctrl+Shift+E"))
        explorer.triggered.connect(self._toggle_sidebar)
        self._register_action("Explorer", explorer)

        search_view = view_menu.addAction("Search")
        search_view.triggered.connect(
            lambda: self._statusbar.showMessage("Search panel: coming soon", 3000)
        )

        quick_help = view_menu.addAction("Quick Help")
        quick_help.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        quick_help.triggered.connect(
            lambda: self._statusbar.showMessage("Quick Help: coming soon", 3000)
        )

        view_menu.addSeparator()

        toggle_editor = view_menu.addAction("Toggle Code Editor")
        toggle_editor.setShortcut(QKeySequence("Ctrl+K"))
        toggle_editor.triggered.connect(self._toggle_code_editor)
        self._register_action("Toggle Code Editor", toggle_editor)

        self._toggle_output_action = view_menu.addAction("Toggle Output")
        self._toggle_output_action.setShortcut(QKeySequence("Ctrl+J"))
        self._toggle_output_action.triggered.connect(self._toggle_output)
        self._register_action("Toggle Output", self._toggle_output_action)

        self._toggle_sidebar_action = view_menu.addAction("Toggle Side Bar")
        self._toggle_sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        self._toggle_sidebar_action.triggered.connect(self._toggle_sidebar)
        self._register_action("Toggle Side Bar", self._toggle_sidebar_action)

        hide_activity = view_menu.addAction("Hide Activity Bar")
        hide_activity.triggered.connect(
            lambda: self._statusbar.showMessage("Hide Activity Bar: coming soon", 3000)
        )

        hide_statusbar = view_menu.addAction("Hide Status Bar")
        hide_statusbar.triggered.connect(self._toggle_statusbar)

        view_menu.addSeparator()

        toggle_layout = view_menu.addAction("Toggle Code Editor Layout")
        toggle_layout.setShortcut(QKeySequence("Alt+Shift+1"))
        toggle_layout.triggered.connect(
            lambda: self._statusbar.showMessage("Code Editor Layout: coming soon", 3000)
        )

        move_sidebar = view_menu.addAction("Move Side Bar Right")
        move_sidebar.triggered.connect(
            lambda: self._statusbar.showMessage("Move Side Bar: coming soon", 3000)
        )

        # Output Position submenu (stub).
        output_pos_menu = view_menu.addMenu("Output Position")
        for pos in ["Top", "Bottom", "Left", "Right"]:
            act = output_pos_menu.addAction(pos)
            act.triggered.connect(
                lambda checked, p=pos: self._statusbar.showMessage(
                    "Output Position {}: coming soon".format(p), 3000
                )
            )

        view_menu.addSeparator()

        # Toggle Render Whitespaces (checkable stub).
        self._whitespace_action = view_menu.addAction("Toggle Render Whitespaces")
        self._whitespace_action.setCheckable(True)
        self._whitespace_action.triggered.connect(self._toggle_whitespace)

        # Toggle Word Wrap (functional checkable).
        self._word_wrap_action = view_menu.addAction("Toggle Word Wrap")
        self._word_wrap_action.setCheckable(True)
        self._word_wrap_action.setChecked(self._settings.get("word_wrap", False))
        self._word_wrap_action.triggered.connect(self._toggle_word_wrap)

        view_menu.addSeparator()

        inc_font = view_menu.addAction("Increase Font Size")
        inc_font.setShortcut(QKeySequence("Ctrl+="))
        inc_font.triggered.connect(self._increase_font_size)
        self._register_action("Increase Font Size", inc_font)

        dec_font = view_menu.addAction("Decrease Font Size")
        dec_font.setShortcut(QKeySequence("Ctrl+-"))
        dec_font.triggered.connect(self._decrease_font_size)
        self._register_action("Decrease Font Size", dec_font)

        reset_font = view_menu.addAction("Reset Font Size")
        reset_font.setShortcut(QKeySequence("Ctrl+0"))
        reset_font.triggered.connect(self._reset_font_size)
        self._register_action("Reset Font Size", reset_font)

        view_menu.addSeparator()

        self._simple_mode_action = view_menu.addAction("Simple Mode")
        self._simple_mode_action.setCheckable(True)
        self._simple_mode_action.triggered.connect(lambda: self._set_editor_mode(EditorMode.SIMPLE))

        self._advanced_mode_action = view_menu.addAction("Advanced Mode")
        self._advanced_mode_action.setCheckable(True)
        self._advanced_mode_action.triggered.connect(lambda: self._set_editor_mode(EditorMode.ADVANCED))

        self._toggle_ai_action = view_menu.addAction("Toggle AI Panel")
        self._toggle_ai_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self._toggle_ai_action.triggered.connect(self._toggle_ai_panel)

        # =================================================================
        # Go Menu
        # =================================================================
        go_menu = menubar.addMenu("&Go")

        # Switch Editor submenu.
        switch_menu = go_menu.addMenu("Switch Editor")

        next_ed = switch_menu.addAction("Next Editor")
        next_ed.setShortcut(QKeySequence("Ctrl+PgDown"))
        next_ed.triggered.connect(self._next_editor)
        self._register_action("Next Editor", next_ed)

        prev_ed = switch_menu.addAction("Previous Editor")
        prev_ed.setShortcut(QKeySequence("Ctrl+PgUp"))
        prev_ed.triggered.connect(self._prev_editor)
        self._register_action("Previous Editor", prev_ed)

        # NOTE: Ctrl+Tab and Ctrl+Shift+Tab are not registered as QAction
        # shortcuts because they conflict with Qt's built-in tab widget
        # navigation and can disrupt keyboard event handling.
        next_used = switch_menu.addAction("Next Used Editor\tCtrl+Tab")
        next_used.triggered.connect(self._next_editor)

        prev_used = switch_menu.addAction("Previous Used Editor\tCtrl+Shift+Tab")
        prev_used.triggered.connect(self._prev_editor)

        # Switch Group submenu (stub).
        switch_group = go_menu.addMenu("Switch Group")
        sg_stub = switch_group.addAction("No groups")
        sg_stub.setEnabled(False)

        go_menu.addSeparator()

        go_file = go_menu.addAction("Go to File...")
        go_file.setShortcut(QKeySequence("Ctrl+P"))
        go_file.triggered.connect(self._go_to_file)
        self._register_action("Go to File", go_file)

        go_symbol = go_menu.addAction("Go to Symbol in File...")
        go_symbol.setShortcut(QKeySequence("Ctrl+Shift+O"))
        go_symbol.triggered.connect(self._go_to_symbol)
        self._register_action("Go to Symbol in File", go_symbol)

        goto_line = go_menu.addAction("Go to Line...")
        goto_line.setShortcut(QKeySequence("Ctrl+G"))
        goto_line.triggered.connect(self._show_goto_line)
        self._register_action("Go to Line", goto_line)

        # =================================================================
        # Output Menu
        # =================================================================
        output_menu = menubar.addMenu("&Output")

        # Verbosity submenu with radio-button group.
        verbosity_menu = output_menu.addMenu("Verbosity")
        self._verbosity_group = QActionGroup(self)
        for label, level in [("Echo All", "echo_all"), ("Normal", "normal"), ("Minimal", "minimal")]:
            act = verbosity_menu.addAction(label)
            act.setCheckable(True)
            act.setData(level)
            self._verbosity_group.addAction(act)
            if level == self._verbosity_level:
                act.setChecked(True)
        self._verbosity_group.triggered.connect(
            lambda action: self._set_verbosity(action.data())
        )

        output_menu.addSeparator()

        self._line_numbers_action = output_menu.addAction("Line Numbers in Errors")
        self._line_numbers_action.setCheckable(True)
        self._line_numbers_action.setChecked(True)
        self._line_numbers_action.triggered.connect(self._toggle_line_numbers_in_errors)

        self._stack_trace_action = output_menu.addAction("Show Stack Trace")
        self._stack_trace_action.setCheckable(True)
        self._stack_trace_action.setChecked(True)
        self._stack_trace_action.triggered.connect(self._toggle_stack_trace)

        self._suppress_stack_action = output_menu.addAction("Suppress Stack Window")
        self._suppress_stack_action.setCheckable(True)
        self._suppress_stack_action.triggered.connect(self._toggle_suppress_stack)

        output_menu.addSeparator()

        write_output = output_menu.addAction("Write Output to File...")
        write_output.triggered.connect(self._write_output_to_file)

        # =================================================================
        # Command Menu (replaces Execute)
        # =================================================================
        cmd_menu = menubar.addMenu("&Command")

        exec_sel = cmd_menu.addAction("Execute")
        exec_sel.setShortcut(QKeySequence("Ctrl+Return"))
        exec_sel.triggered.connect(self._execute_selected)
        self._register_action("Execute", exec_sel)

        exec_line = cmd_menu.addAction("Execute Line")
        exec_line.setShortcut(QKeySequence("Ctrl+Alt+Return"))
        exec_line.triggered.connect(self._execute_line)
        self._register_action("Execute Line", exec_line)

        exec_all = cmd_menu.addAction("Execute All")
        exec_all.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        exec_all.triggered.connect(self._execute_all)
        self._register_action("Execute All", exec_all)

        cmd_menu.addSeparator()

        # Environment Variables submenu.
        env_menu = cmd_menu.addMenu("Environment Variables")
        env_vars = [
            "MAYA_SCRIPT_PATH", "MAYA_PLUG_IN_PATH", "MAYA_MODULE_PATH",
            "MAYA_SHELF_PATH", "XBMLANGPATH", "PYTHONPATH",
        ]
        for var in env_vars:
            act = env_menu.addAction(var)
            act.triggered.connect(lambda checked, v=var: self._show_env_var(v))

        cmd_menu.addSeparator()

        # Python submenu (stub).
        python_menu = cmd_menu.addMenu("Python")
        py_stub = python_menu.addAction("Python settings coming soon")
        py_stub.setEnabled(False)

        # Pylint submenu (stub).
        pylint_menu = cmd_menu.addMenu("Pylint")
        pl_stub = pylint_menu.addAction("Pylint integration coming soon")
        pl_stub.setEnabled(False)

        # =================================================================
        # DCC Menu (unchanged)
        # =================================================================
        dcc_menu = menubar.addMenu("&DCC")

        connect_action = dcc_menu.addAction("Connect to DCC...")
        connect_action.triggered.connect(self._show_connect_dialog)

        disconnect_action = dcc_menu.addAction("Disconnect")
        disconnect_action.triggered.connect(self._disconnect_dcc)

        dcc_menu.addSeparator()

        detect_action = dcc_menu.addAction("Detect Running DCCs")
        detect_action.triggered.connect(self._auto_detect_dccs)

        # =================================================================
        # Help Menu
        # =================================================================
        help_menu = menubar.addMenu("&Help")

        mel_ref = help_menu.addAction("MEL Command Reference")
        mel_ref.triggered.connect(self._open_mel_reference)

        py_ref = help_menu.addAction("Python Command Reference")
        py_ref.triggered.connect(self._open_python_reference)

        node_ref = help_menu.addAction("Node and Attribute Reference")
        node_ref.triggered.connect(self._open_node_reference)

        help_menu.addSeparator()

        licensing = help_menu.addAction("Licensing...")
        licensing.triggered.connect(self._show_licensing)

        about_action = help_menu.addAction("About MCA Editor")
        about_action.triggered.connect(self._show_about)

    def _register_action(self, name, action):
        """
        Add an action to the keyboard shortcut registry.

        :param str name: Clean display name for the command.
        :param QAction action: The QAction to register.
        """
        self._action_registry[name] = action

    def _setup_toolbar(self):
        """Build the main toolbar with file, execution, and mode controls."""
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

        # --- File operations ---
        toolbar.addAction("New").triggered.connect(self._new_buffer)
        toolbar.addAction("Open").triggered.connect(self._open_file)
        toolbar.addAction("Save").triggered.connect(self._save_file)

        toolbar.addSeparator()

        # --- Execution buttons (like Charcoal Editor 2) ---
        exec_all_btn = toolbar.addAction("Execute")
        exec_all_btn.setToolTip("Execute entire script (Ctrl+Shift+Enter)")
        exec_all_btn.triggered.connect(self._execute_all)

        exec_sel_btn = toolbar.addAction("Selected")
        exec_sel_btn.setToolTip("Execute selected text (Ctrl+Enter)")
        exec_sel_btn.triggered.connect(self._execute_selected)

        exec_line_btn = toolbar.addAction("Line")
        exec_line_btn.setToolTip("Execute current line (Ctrl+Alt+Enter)")
        exec_line_btn.triggered.connect(self._execute_line)

        toolbar.addSeparator()

        # --- Language selector ---
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

        # --- DCC connection indicator ---
        self._dcc_indicator = QPushButton("* No DCC")
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

        # Spacer to push mode toggle to the right.
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)

        # --- Mode toggle button ---
        self._mode_toggle = QPushButton("Advanced")
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
        """Build the status bar with cursor position and language info."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # Cursor position display.
        self._pos_label = QLabel("Ln 1, Col 1")
        self._pos_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(self._pos_label)

        # Current language display.
        self._lang_label = QLabel("Python")
        self._lang_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(self._lang_label)

        # Encoding display.
        encoding_label = QLabel("UTF-8")
        encoding_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(encoding_label)

        # Mode indicator.
        self._mode_label = QLabel("Simple")
        self._mode_label.setStyleSheet("color: white; padding: 0 8px; font-size: 11px;")
        self._statusbar.addPermanentWidget(self._mode_label)

    def _setup_connections(self):
        """Wire up signals between all UI components."""
        # Sidebar signals -> editor navigation.
        self._sidebar.file_open_requested.connect(self._open_file_path)
        self._sidebar.outline_item_clicked.connect(self._goto_outline_item)
        self._sidebar.editor_selected.connect(self._tab_widget.setCurrentIndex)

        # Adapter manager -> UI status updates.
        self._adapter_manager.set_connection_callback(self._update_dcc_status)

        # Set output/error callbacks on all adapters.
        for adapter in self._adapter_manager.get_all_adapters().values():
            adapter.set_output_callback(self._output.write_output)
            adapter.set_error_callback(self._output.write_error)

    # =========================================================================
    # Editor Mode (Simple / Advanced)
    # =========================================================================

    def _set_editor_mode(self, mode):
        """
        Switch between simple and advanced mode.

        :param EditorMode mode: The mode to activate.
        """
        self._editor_mode = mode
        self._settings.set_editor_mode(mode)
        self._apply_editor_mode()

    def _apply_editor_mode(self):
        """Apply the current editor mode to the UI layout."""
        is_simple = self._editor_mode == EditorMode.SIMPLE

        if is_simple:
            # Simple mode: hide sidebar and AI panel.
            self._sidebar.setVisible(False)
            self._ai_panel.setVisible(False)
            self._main_splitter.setSizes([0, 1000, 0])
            self._mode_toggle.setText("Advanced")
            self._mode_label.setText("Simple")
            self._simple_mode_action.setChecked(True)
            self._advanced_mode_action.setChecked(False)
        else:
            # Advanced mode: show sidebar, AI panel hidden by default.
            self._sidebar.setVisible(True)
            self._sidebar.set_advanced_mode()
            self._ai_panel.setVisible(False)
            self._main_splitter.setSizes([240, 800, 0])
            self._mode_toggle.setText("Simple")
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
        """Toggle sidebar visibility."""
        self._sidebar.setVisible(not self._sidebar.isVisible())

    def _toggle_output(self):
        """Toggle output window visibility."""
        self._output.setVisible(not self._output.isVisible())

    def _toggle_ai_panel(self):
        """Toggle AI panel visibility, expanding it if needed."""
        visible = not self._ai_panel.isVisible()
        self._ai_panel.setVisible(visible)
        if visible:
            # Expand the AI panel if it was collapsed.
            sizes = self._main_splitter.sizes()
            if sizes[-1] == 0:
                total = sum(sizes)
                sizes[-1] = 300
                sizes[1] = total - sizes[0] - sizes[-1]
                self._main_splitter.setSizes(sizes)

    # =========================================================================
    # Tab / Buffer Management (like Charcoal Editor 2)
    # =========================================================================

    def _current_editor(self):
        """
        Get the currently active code editor.

        :return: The active editor widget, or None.
        :rtype: MCACodeEditor or None
        """
        widget = self._tab_widget.currentWidget()
        if isinstance(widget, MCACodeEditor):
            return widget
        return None

    def _new_buffer(self):
        """
        Create a new temporary buffer (like CE2's temp buffers).

        :return: The newly created editor widget.
        :rtype: MCACodeEditor
        """
        editor = MCACodeEditor()

        # Connect editor signals for execution and status.
        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))

        # Name temp buffer tabs by language (like Charcoal Editor 2).
        lang_map = {"python": "Python", "mel": "MEL"}
        tab_name = lang_map.get(editor.language, "Python")

        idx = self._tab_widget.addTab(editor, tab_name)
        self._editors.append((editor, tab_name, None))
        self._tab_widget.setCurrentIndex(idx)

        self._update_open_editors()
        return editor

    def _open_file(self):
        """Open a file from disk via file dialog."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "Script Files (*.py *.mel *.cs *.lua);;Python Files (*.py);;"
            "MEL Files (*.mel);;All Files (*.*)"
        )
        if filepath:
            self._open_file_path(filepath)

    def _open_file_path(self, filepath):
        """
        Open a specific file. If already open, switch to its tab.

        :param str filepath: Absolute path to the file to open.
        """
        # Check if the file is already open in a tab.
        for i, (editor, name, path) in enumerate(self._editors):
            if path == filepath:
                self._tab_widget.setCurrentIndex(i)
                return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            QMessageBox.warning(self, "Error", "Could not open file:\n{}".format(str(exc)))
            return

        editor = MCACodeEditor()
        editor.file_path = filepath
        editor.setPlainText(content)
        editor.document().setModified(False)

        # Connect signals.
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
        self._build_recent_files_menu()
        self._update_open_editors()
        self._update_language_combo(editor)

    def _save_file(self):
        """Save the current file (or prompt Save As for temp buffers)."""
        editor = self._current_editor()
        if not editor:
            return

        if editor.file_path:
            self._write_file(editor, editor.file_path)
        else:
            self._save_file_as()

    def _save_file_as(self):
        """Save the current file with a new name via file dialog."""
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

            # Update tab name and tracking.
            idx = self._tab_widget.currentIndex()
            tab_name = os.path.basename(filepath)
            self._tab_widget.setTabText(idx, tab_name)
            self._editors[idx] = (editor, tab_name, filepath)
            self._settings.add_recent_file(filepath)
            self._update_open_editors()

    def _write_file(self, editor, filepath):
        """
        Write editor content to a file.

        :param MCACodeEditor editor: The editor to save.
        :param str filepath: The file path to write to.
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(editor.toPlainText())
            editor.document().setModified(False)
            self._output.write_info("Saved: {}".format(filepath))
            logger.info("Saved file: %s", filepath)
        except Exception as exc:
            QMessageBox.warning(self, "Error", "Could not save file:\n{}".format(str(exc)))

    def _close_tab(self, index):
        """
        Close a tab/buffer, prompting to save if modified.

        Always keeps at least one buffer open.

        :param int index: Tab index to close.
        """
        if index < 0 or index >= len(self._editors):
            return

        editor, name, path = self._editors[index]

        # Prompt for unsaved changes.
        if editor.document().isModified():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "'{}' has unsaved changes. Save before closing?".format(name),
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

        # Track closed file for "reopen closed file" feature.
        if path:
            self._closed_files.append(path)

        self._update_open_editors()

        # Ensure at least one buffer is always open (CE2 behavior).
        if self._tab_widget.count() == 0:
            self._new_buffer()

    def _on_tab_changed(self, index):
        """
        Handle tab selection changes.

        Updates the outline, language combo, and cursor position.

        :param int index: The new active tab index.
        """
        editor = self._current_editor()
        if editor:
            self._update_outline(editor)
            self._update_language_combo(editor)
            self._update_cursor_pos(
                editor.textCursor().blockNumber() + 1,
                editor.textCursor().columnNumber() + 1
            )

    def _on_editor_modified(self, editor, modified):
        """
        Handle editor modification state changes.

        Updates the tab title to show a modification indicator.

        :param MCACodeEditor editor: The modified editor.
        :param bool modified: Whether the editor has unsaved changes.
        """
        for i, (e, name, path) in enumerate(self._editors):
            if e is editor:
                display = "[*] {}".format(name) if modified else name
                self._tab_widget.setTabText(i, display)
                break
        self._update_open_editors()

    def _update_open_editors(self):
        """Update the sidebar's open editors panel."""
        tabs = []
        for editor, name, path in self._editors:
            tabs.append({
                "name": name,
                "path": path,
                "modified": editor.document().isModified(),
                "language": editor.language,
            })
        self._sidebar.open_editors_panel.update_editors(tabs)

    def _update_outline(self, editor):
        """
        Update the code outline panel from the current editor.

        :param MCACodeEditor editor: The editor to extract outline from.
        """
        outline = editor.get_code_outline()
        self._sidebar.outline_panel.update_outline(outline)

    def _goto_outline_item(self, line):
        """
        Jump to a line from the outline panel.

        :param int line: The line number to navigate to.
        """
        editor = self._current_editor()
        if editor:
            editor.go_to_line(line)

    def _update_language_combo(self, editor):
        """
        Sync the toolbar language combo with the editor's language.

        :param MCACodeEditor editor: The editor to read language from.
        """
        lang_map = {"python": "Python", "mel": "MEL"}
        display = lang_map.get(editor.language, "Python")
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentText(display)
        self._lang_combo.blockSignals(False)
        self._lang_label.setText(display)

    def _on_language_changed(self, language):
        """
        Handle toolbar language combo changes.

        Updates the editor's highlighter and, for temp buffers, renames
        the tab to match the new language (like Charcoal Editor 2).

        :param str language: The selected language display name.
        """
        editor = self._current_editor()
        if editor:
            editor.set_language(language.lower())
            self._lang_label.setText(language)

            # Rename the tab for temp buffers to reflect the language.
            idx = self._tab_widget.currentIndex()
            if idx >= 0 and idx < len(self._editors):
                e, name, path = self._editors[idx]
                if path is None:
                    # Temp buffer: update tab name to the language.
                    new_name = language
                    modified = e.document().isModified()
                    display = "[*] {}".format(new_name) if modified else new_name
                    self._tab_widget.setTabText(idx, display)
                    self._editors[idx] = (e, new_name, path)
                    self._update_open_editors()

    def _update_cursor_pos(self, line, col):
        """
        Update the status bar cursor position display.

        :param int line: Current line number (1-based).
        :param int col: Current column number (1-based).
        """
        self._pos_label.setText("Ln {}, Col {}".format(line, col))

    # =========================================================================
    # Execution (Critical CE2 feature: NEVER deletes code on execute)
    # =========================================================================

    def _execute_all(self):
        """Execute the entire script in the connected DCC or locally."""
        editor = self._current_editor()
        if not editor:
            return

        code = editor.get_all_text()
        if not code.strip():
            return

        # Auto-save before execute (like CE2).
        if self._settings.get("auto_save_on_execute") and editor.file_path:
            self._write_file(editor, editor.file_path)

        # Echo the code to the output window (like Charcoal / Maya Script Editor).
        self._output.write_code_echo(code.strip())

        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            adapter.execute(code, editor.language)
        else:
            # Local execution fallback for Python.
            if editor.language == "python":
                self._execute_locally(code)
            else:
                self._output.write_warning("No DCC connected. Connect to a DCC to execute.")

    def _execute_selected(self):
        """Execute selected text (or all if nothing is selected)."""
        editor = self._current_editor()
        if not editor:
            return

        code = editor.get_selected_text()
        if not code.strip():
            return

        # Echo the code to the output window (like Charcoal / Maya Script Editor).
        self._output.write_code_echo(code.strip())

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

        # Echo the code to the output window (like Charcoal / Maya Script Editor).
        self._output.write_code_echo(code.strip())

        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            adapter.execute(code, editor.language)
        else:
            if editor.language == "python":
                self._execute_locally(code)
            else:
                self._output.write_warning("No DCC connected.")

    def _execute_locally(self, code):
        """
        Execute Python code locally when no DCC is connected.

        Uses a persistent namespace (self._local_namespace) so that
        variables, functions, and imports survive across multiple calls,
        matching Maya's interpreter behavior.

        Captures stdout/stderr and displays results in the output window.

        :param str code: Python source code to execute.
        """
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        try:
            # Use the persistent namespace so variables survive between runs.
            exec(code, self._local_namespace)
            output = sys.stdout.getvalue()
            errors = sys.stderr.getvalue()

            if output:
                self._output.write_output(output.rstrip())
            if errors:
                self._output.write_warning(errors.rstrip())

            self._output.write_success("Executed locally (no DCC)")
        except Exception:
            tb = traceback.format_exc()
            self._output.write_error(tb.rstrip())
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    # =========================================================================
    # DCC Connection
    # =========================================================================

    def _show_connect_dialog(self):
        """Show the DCC connection dialog."""
        dialog = ConnectionDialog(self._adapter_manager, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            info = dialog.get_connection_info()
            self._output.write_info(
                "Connecting to {} at {}:{}...".format(
                    info["dcc_type"].value, info["host"], info["port"]
                )
            )
            success = self._adapter_manager.connect(
                info["dcc_type"], info["host"], info["port"]
            )
            if success:
                self._output.write_success("Connected to {}!".format(info["dcc_type"].value))

    def _disconnect_dcc(self):
        """Disconnect from all active DCC connections."""
        self._adapter_manager.disconnect_all()

    def _update_dcc_status(self):
        """Update the toolbar DCC connection indicator."""
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            self._dcc_indicator.setText("* {}".format(adapter.display_name))
            self._dcc_indicator.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #4ec9b0;
                    border: none; padding: 4px 8px; font-size: 11px;
                }
                QPushButton:hover { background-color: #3e3e42; }
            """)
        else:
            self._dcc_indicator.setText("* No DCC")
            self._dcc_indicator.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #666666;
                    border: none; padding: 4px 8px; font-size: 11px;
                }
                QPushButton:hover { background-color: #3e3e42; }
            """)

    def _auto_detect_dccs(self):
        """Auto-detect running DCC applications and report findings."""
        detected = self._adapter_manager.detect_running_dccs()
        if detected:
            names = ", ".join(d["name"] for d in detected)
            self._output.write_info("Detected running DCCs: {}".format(names))
            self._statusbar.showMessage("Detected: {}".format(names), 5000)

    def _get_active_dcc_name(self):
        """
        Get the display name of the active DCC or 'Local Python'.

        :return: Active DCC name or fallback.
        :rtype: str
        """
        adapter = self._adapter_manager.get_active_adapter()
        return adapter.display_name if adapter else "Local Python"

    # =========================================================================
    # Find / Go To
    # =========================================================================

    def _show_find(self):
        """Show find dialog (placeholder for full implementation)."""
        self._statusbar.showMessage("Find: Ctrl+F (full search coming soon)", 3000)

    def _show_goto_line(self):
        """Show go-to-line dialog and navigate to the chosen line."""
        editor = self._current_editor()
        if not editor:
            return

        line, ok = QInputDialog.getInt(
            self, "Go to Line", "Line number:",
            editor.textCursor().blockNumber() + 1,
            1, editor.document().blockCount()
        )
        if ok:
            editor.go_to_line(line)

    # =========================================================================
    # File Menu Handlers
    # =========================================================================

    def _new_mel_buffer(self):
        """Create a new temporary buffer set to MEL language."""
        editor = self._new_buffer()
        editor.set_language("mel")
        # Update the tab name and tracking to reflect MEL language.
        idx = self._tab_widget.currentIndex()
        self._tab_widget.setTabText(idx, "MEL")
        self._editors[idx] = (editor, "MEL", None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _new_python_buffer(self):
        """Create a new temporary buffer set to Python language."""
        editor = self._new_buffer()
        editor.set_language("python")
        # Update the tab name and tracking to reflect Python language.
        idx = self._tab_widget.currentIndex()
        self._tab_widget.setTabText(idx, "Python")
        self._editors[idx] = (editor, "Python", None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _build_recent_files_menu(self):
        """Rebuild the Recent Files submenu from settings."""
        self._recent_files_menu.clear()

        # Add "Reopen Closed File" action at the top.
        reopen = self._recent_files_menu.addAction("Reopen Closed File")
        reopen.triggered.connect(self._reopen_closed_file)
        reopen.setEnabled(len(self._closed_files) > 0)

        clear = self._recent_files_menu.addAction("Clear Items")
        clear.triggered.connect(self._clear_recent_files)

        self._recent_files_menu.addSeparator()

        # Populate with recent files from settings.
        recent = self._settings.get_recent_files()
        if recent:
            for filepath in recent:
                act = self._recent_files_menu.addAction(filepath)
                act.triggered.connect(
                    lambda checked, p=filepath: self._open_file_path(p)
                )
        else:
            empty = self._recent_files_menu.addAction("No recent files")
            empty.setEnabled(False)

    def _reopen_closed_file(self):
        """Reopen the most recently closed file."""
        if self._closed_files:
            filepath = self._closed_files.pop()
            if os.path.isfile(filepath):
                self._open_file_path(filepath)
            else:
                self._output.write_warning("File no longer exists: {}".format(filepath))
                self._build_recent_files_menu()

    def _clear_recent_files(self):
        """Clear the recent files list and rebuild the submenu."""
        self._settings.set("recent_files", [])
        self._closed_files.clear()
        self._build_recent_files_menu()
        self._statusbar.showMessage("Recent files cleared", 3000)

    def _open_workspace(self):
        """Open a folder as the workspace root via file dialog."""
        folder = QFileDialog.getExistingDirectory(self, "Open Workspace")
        if folder:
            self._sidebar.workspace_panel.add_folder(folder)
            self._output.write_info("Opened workspace: {}".format(folder))

    def _add_folder_to_workspace(self):
        """Add a folder to the sidebar workspace via file dialog."""
        folder = QFileDialog.getExistingDirectory(self, "Add Folder to Workspace")
        if folder:
            self._sidebar.workspace_panel.add_folder(folder)
            self._output.write_info("Added folder to workspace: {}".format(folder))

    def _save_all(self):
        """Save all editors that have associated file paths."""
        saved_count = 0
        for editor, name, path in self._editors:
            if path and editor.document().isModified():
                self._write_file(editor, path)
                saved_count += 1
        self._statusbar.showMessage("Saved {} file(s)".format(saved_count), 3000)

    def _rename_file(self):
        """Rename the current file on disk and update the tab."""
        editor = self._current_editor()
        if not editor or not editor.file_path:
            self._statusbar.showMessage("No file to rename (save first)", 3000)
            return

        old_path = editor.file_path
        new_name, ok = QInputDialog.getText(
            self, "Rename File",
            "New file name:",
            text=os.path.basename(old_path)
        )
        if ok and new_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            try:
                os.rename(old_path, new_path)
                editor.file_path = new_path
                # Update tab name and tracking.
                idx = self._tab_widget.currentIndex()
                self._tab_widget.setTabText(idx, new_name)
                self._editors[idx] = (editor, new_name, new_path)
                self._settings.add_recent_file(new_path)
                self._update_open_editors()
                self._output.write_info("Renamed: {} -> {}".format(old_path, new_path))
            except Exception as exc:
                QMessageBox.warning(
                    self, "Error", "Could not rename file:\n{}".format(str(exc))
                )

    def _save_to_shelf(self):
        """Save current script to a DCC shelf (requires DCC connection)."""
        self._statusbar.showMessage(
            "Save to Shelf: requires DCC connection (coming soon)", 3000
        )

    def _source_script(self):
        """Open a script file and execute its contents."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Source Script", "",
            "Script Files (*.py *.mel);;Python Files (*.py);;"
            "MEL Files (*.mel);;All Files (*.*)"
        )
        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                self._output.write_info("Sourcing: {}".format(filepath))
                # Determine language from file extension.
                lang = "mel" if filepath.endswith(".mel") else "python"
                # Execute via adapter or locally.
                adapter = self._adapter_manager.get_active_adapter()
                if adapter and adapter.is_connected:
                    adapter.execute(code, lang)
                elif lang == "python":
                    self._execute_locally(code)
                else:
                    self._output.write_warning(
                        "No DCC connected. Cannot source MEL scripts locally."
                    )
            except Exception as exc:
                QMessageBox.warning(
                    self, "Error", "Could not source script:\n{}".format(str(exc))
                )

    def _revert_file(self):
        """Reload the current file from disk, discarding changes."""
        editor = self._current_editor()
        if not editor or not editor.file_path:
            self._statusbar.showMessage("No file to revert", 3000)
            return

        # Confirm before discarding changes.
        if editor.document().isModified():
            reply = QMessageBox.question(
                self, "Revert File",
                "Discard all changes and reload from disk?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            with open(editor.file_path, "r", encoding="utf-8") as f:
                content = f.read()
            editor.setPlainText(content)
            editor.document().setModified(False)
            self._output.write_info("Reverted: {}".format(editor.file_path))
        except Exception as exc:
            QMessageBox.warning(
                self, "Error", "Could not revert file:\n{}".format(str(exc))
            )

    def _close_all_files(self):
        """Close all open tabs, prompting for unsaved changes."""
        # Work backwards; _close_tab ensures at least one buffer stays open.
        while self._tab_widget.count() > 0:
            self._close_tab(0)
            # If _close_tab created a new empty buffer (last tab), stop.
            if self._tab_widget.count() == 1:
                break

    def _save_state(self):
        """Persist the list of open file paths to settings for session restore."""
        open_files = []
        for editor, name, path in self._editors:
            if path:
                open_files.append(path)
        self._settings.set("open_files", open_files)
        self._settings.sync()
        self._statusbar.showMessage(
            "State saved ({} files)".format(len(open_files)), 3000
        )

    # =========================================================================
    # Edit Menu Handlers
    # =========================================================================

    def _increase_indent(self):
        """Increase indent of the current line or selection."""
        editor = self._current_editor()
        if editor:
            editor._indent_selection()

    def _decrease_indent(self):
        """Decrease indent of the current line or selection."""
        editor = self._current_editor()
        if editor:
            editor._unindent_selection()

    def _copy_line_up(self):
        """Duplicate the current line above."""
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        # Select the entire current line text.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        line_text = cursor.selectedText()
        # Insert a copy above the current line.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(line_text + "\n")
        # Move cursor up to the duplicated line.
        cursor.movePosition(QTextCursor.MoveOperation.Up)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _copy_line_down(self):
        """Duplicate the current line below."""
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        # Select the entire current line text.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        line_text = cursor.selectedText()
        # Insert a copy below.
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + line_text)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _move_line_up(self):
        """Move the current line up one position."""
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if cursor.blockNumber() == 0:
            return  # Already at the top.
        cursor.beginEditBlock()
        # Select and store the current line text.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        current = cursor.selectedText()
        # Delete the current line text and the preceding newline.
        cursor.removeSelectedText()
        cursor.deletePreviousChar()
        # Insert the line before the now-current line.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(current + "\n")
        # Move cursor to the inserted line.
        cursor.movePosition(QTextCursor.MoveOperation.Up)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _move_line_down(self):
        """Move the current line down one position."""
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if cursor.blockNumber() >= editor.document().blockCount() - 1:
            return  # Already at the bottom.
        cursor.beginEditBlock()
        # Select and store the current line text.
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        current = cursor.selectedText()
        # Delete the current line text and the trailing newline.
        cursor.removeSelectedText()
        cursor.deleteChar()
        # Move to end of the next line and insert below.
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + current)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _delete_line(self):
        """Delete the current line entirely."""
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        # Remove the trailing newline (or preceding if at last line).
        if not cursor.atEnd():
            cursor.deleteChar()
        elif cursor.blockNumber() > 0:
            cursor.deletePreviousChar()
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _toggle_comment_action(self):
        """Toggle line comment on the current line or selection."""
        editor = self._current_editor()
        if editor:
            editor._toggle_comment()

    def _toggle_block_comment(self):
        """Toggle block comment on the selection (language-dependent)."""
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            self._statusbar.showMessage("Select text to block-comment", 3000)
            return
        # Wrap selection in block comment delimiters.
        selected = cursor.selectedText().replace("\u2029", "\n")
        cursor.beginEditBlock()
        if editor.language == "python":
            cursor.insertText('"""\n' + selected + '\n"""')
        elif editor.language == "mel":
            cursor.insertText("/*\n" + selected + "\n*/")
        else:
            cursor.insertText('"""\n' + selected + '\n"""')
        cursor.endEditBlock()

    def _convert_tabs_to_spaces(self):
        """Convert all tab characters to spaces in the current editor."""
        editor = self._current_editor()
        if not editor:
            return
        text = editor.toPlainText()
        converted = text.replace("\t", " " * editor._tab_size)
        if converted != text:
            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(converted)
            cursor.endEditBlock()
            self._statusbar.showMessage("Tabs converted to spaces", 3000)
        else:
            self._statusbar.showMessage("No tabs to convert", 3000)

    def _show_replace(self):
        """Show replace dialog (placeholder)."""
        self._statusbar.showMessage("Replace: Ctrl+H (coming soon)", 3000)

    def _find_in_files(self):
        """Show find-in-files dialog (placeholder)."""
        self._statusbar.showMessage("Find in Files: coming soon", 3000)

    def _replace_in_files(self):
        """Show replace-in-files dialog (placeholder)."""
        self._statusbar.showMessage("Replace in Files: coming soon", 3000)

    def _insert_path(self):
        """Open a file dialog and insert the selected path at the cursor."""
        editor = self._current_editor()
        if not editor:
            return
        filepath, _ = QFileDialog.getOpenFileName(self, "Select File to Insert Path")
        if filepath:
            editor.insertPlainText(filepath)

    def _clear_output(self):
        """Clear the output window."""
        self._output.clear()

    def _show_settings(self):
        """Open the Settings dialog and apply any changes on accept."""
        dlg = SettingsDialog(self._settings, action_registry=self._action_registry, parent=self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            # Apply changed settings to the running editor instances.
            self._apply_settings_to_editors()

    def _apply_settings_to_editors(self):
        """
        Push current settings values into all open editors and output.

        Called after the Settings dialog is accepted so that font,
        tab size, word wrap, and other visual options take effect
        immediately without requiring a restart.
        """
        s = self._settings

        # Read the relevant appearance/behavior settings.
        font_family = s.get("font_family")
        font_size = s.get("font_size")
        tab_size = s.get("tab_size")
        use_spaces = s.get("use_spaces")
        word_wrap = s.get("word_wrap")
        show_indent_guides = s.get("show_indent_guides")

        # Apply to every open code editor tab.
        for editor, _name, _path in self._editors:
            font = editor.font()
            font.setFamily(font_family)
            font.setPointSize(font_size)
            editor.setFont(font)
            editor.setTabStopDistance(font_size * tab_size)

        # Apply word wrap to the output window.
        output_wrap = s.get("output_word_wrap")
        if hasattr(self._output, "_output"):
            from PySide6.QtWidgets import QPlainTextEdit
            wrap_mode = (
                QPlainTextEdit.LineWrapMode.WidgetWidth if output_wrap
                else QPlainTextEdit.LineWrapMode.NoWrap
            )
            self._output._output.setLineWrapMode(wrap_mode)

        # Apply tab bar visibility settings.
        self._tab_widget.tabBar().setVisible(s.get("show_tab_bar"))
        self._tab_widget.setTabsClosable(s.get("show_close_button_on_tab"))
        self._tab_widget.setMovable(not s.get("lock_tabs"))

        logger.info("Settings applied to running editors")

    # =========================================================================
    # View Menu Handlers
    # =========================================================================

    def _toggle_code_editor(self):
        """Toggle visibility of the code editor tab widget."""
        self._tab_widget.setVisible(not self._tab_widget.isVisible())

    def _toggle_statusbar(self):
        """Toggle visibility of the status bar."""
        self._statusbar.setVisible(not self._statusbar.isVisible())

    def _toggle_word_wrap(self, checked):
        """
        Toggle word wrap on all open editors.

        :param bool checked: Whether word wrap should be enabled.
        """
        from PySide6.QtWidgets import QPlainTextEdit
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth if checked
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        # Apply to all open editors.
        for editor, name, path in self._editors:
            editor.setLineWrapMode(mode)
        self._settings.set("word_wrap", checked)

    def _toggle_whitespace(self, checked):
        """
        Toggle whitespace rendering (placeholder for full implementation).

        :param bool checked: Whether whitespace rendering is enabled.
        """
        self._settings.set("show_whitespace", checked)
        self._statusbar.showMessage(
            "Whitespace rendering: {}".format("on" if checked else "off"), 3000
        )

    def _increase_font_size(self):
        """Increase font size on all open editors by 1pt."""
        self._default_font_size += 1
        self._apply_font_size()

    def _decrease_font_size(self):
        """Decrease font size on all open editors by 1pt (minimum 6pt)."""
        if self._default_font_size > 6:
            self._default_font_size -= 1
            self._apply_font_size()

    def _reset_font_size(self):
        """Reset font size to the default 12pt on all open editors."""
        self._default_font_size = 12
        self._apply_font_size()

    def _apply_font_size(self):
        """
        Apply the current font size to all open editors and update the status bar.

        Reads ``self._default_font_size`` and sets it on every editor widget.
        """
        for editor, name, path in self._editors:
            font = editor.font()
            font.setPointSize(self._default_font_size)
            editor.setFont(font)
            # Recalculate tab stop distance for new font metrics.
            editor.setTabStopDistance(
                editor.fontMetrics().horizontalAdvance(" ") * editor._tab_size
            )
        self._settings.set("font_size", self._default_font_size)
        self._statusbar.showMessage(
            "Font size: {}pt".format(self._default_font_size), 3000
        )

    # =========================================================================
    # Go Menu Handlers
    # =========================================================================

    def _next_editor(self):
        """Switch to the next editor tab."""
        count = self._tab_widget.count()
        if count > 1:
            idx = (self._tab_widget.currentIndex() + 1) % count
            self._tab_widget.setCurrentIndex(idx)

    def _prev_editor(self):
        """Switch to the previous editor tab."""
        count = self._tab_widget.count()
        if count > 1:
            idx = (self._tab_widget.currentIndex() - 1) % count
            self._tab_widget.setCurrentIndex(idx)

    def _go_to_file(self):
        """Go to file by name (placeholder)."""
        self._statusbar.showMessage("Go to File: coming soon", 3000)

    def _go_to_symbol(self):
        """Go to symbol in file (placeholder)."""
        self._statusbar.showMessage("Go to Symbol: coming soon", 3000)

    # =========================================================================
    # Output Menu Handlers
    # =========================================================================

    def _set_verbosity(self, level):
        """
        Set the output verbosity level.

        :param str level: One of 'echo_all', 'normal', or 'minimal'.
        """
        self._verbosity_level = level
        self._settings.set("output_verbosity", level)
        self._statusbar.showMessage("Verbosity: {}".format(level), 3000)

    def _toggle_line_numbers_in_errors(self, checked):
        """
        Toggle whether line numbers appear in error output.

        :param bool checked: Whether the option is enabled.
        """
        self._settings.set("line_numbers_in_errors", checked)
        self._statusbar.showMessage(
            "Line numbers in errors: {}".format("on" if checked else "off"), 3000
        )

    def _toggle_stack_trace(self, checked):
        """
        Toggle whether stack traces are shown in error output.

        :param bool checked: Whether the option is enabled.
        """
        self._settings.set("show_stack_trace", checked)
        self._statusbar.showMessage(
            "Stack trace: {}".format("on" if checked else "off"), 3000
        )

    def _toggle_suppress_stack(self, checked):
        """
        Toggle whether the stack window is suppressed.

        :param bool checked: Whether the option is enabled.
        """
        self._settings.set("suppress_stack_window", checked)
        self._statusbar.showMessage(
            "Suppress stack window: {}".format("on" if checked else "off"), 3000
        )

    def _write_output_to_file(self):
        """Save the current output window contents to a text file."""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Write Output to File", "",
            "Text Files (*.txt);;Log Files (*.log);;All Files (*.*)"
        )
        if filepath:
            try:
                text = self._output._output.toPlainText()
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                self._output.write_info("Output written to: {}".format(filepath))
            except Exception as exc:
                QMessageBox.warning(
                    self, "Error",
                    "Could not write output:\n{}".format(str(exc))
                )

    # =========================================================================
    # Command Menu Handlers
    # =========================================================================

    def _show_env_var(self, var_name):
        """
        Display the value of an environment variable in the output window.

        :param str var_name: The environment variable name to look up.
        """
        value = os.environ.get(var_name, "")
        if value:
            self._output.write_info("{} = {}".format(var_name, value))
        else:
            self._output.write_warning("{} is not set".format(var_name))

    # =========================================================================
    # Help Menu Handlers
    # =========================================================================

    def _open_mel_reference(self):
        """Open the Autodesk MEL Command Reference in the default browser."""
        webbrowser.open(
            "https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/"
        )

    def _open_python_reference(self):
        """Open the Autodesk Python Command Reference in the default browser."""
        webbrowser.open(
            "https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/"
        )

    def _open_node_reference(self):
        """Open the Autodesk Node and Attribute Reference in the default browser."""
        webbrowser.open(
            "https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Nodes/"
        )

    def _show_licensing(self):
        """Show licensing information dialog."""
        QMessageBox.information(
            self, "Licensing",
            "<h3>MCA Editor Licensing</h3>"
            "<p><b>Current Tier:</b> Free / Open Source</p>"
            "<p>MCA Editor is currently in early development.<br>"
            "Future licensing tiers (Standard, Pro, Studio) are planned.</p>"
            "<hr>"
            "<p style='color: #888;'>Contact: support@mcatools.com</p>"
        )

    # =========================================================================
    # About
    # =========================================================================

    def _show_about(self):
        """Show the About dialog."""
        QMessageBox.about(
            self, "About MCA Editor",
            "<h3>MCA Editor v0.1.0</h3>"
            "<p>Cross-DCC Script IDE</p>"
            "<p>Spiritual successor to Charcoal Editor 2.<br>"
            "Supports Maya (with future expansion to Blender, Unreal, Unity, and more).</p>"
            "<p><b>Features:</b><br>"
            "- Dual mode: Simple (script editor) &amp; Advanced (IDE)<br>"
            "- Multi-DCC connection via adapters<br>"
            "- AI integration (BYOK or managed)<br>"
            "- Plugin architecture for extensions</p>"
            "<hr>"
            "<p style='color: #888;'>Built with PySide6 (Qt6)</p>"
        )

    # =========================================================================
    # Window State
    # =========================================================================

    def closeEvent(self, event):
        """
        Save state on close and check for unsaved changes.

        :param QCloseEvent event: The close event.
        """
        # Check for unsaved changes across all tabs.
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

        # Persist window geometry and state.
        self._settings.set("window_geometry", self.saveGeometry())
        self._settings.set("window_state", self.saveState())
        self._settings.sync()

        # Disconnect from all DCCs on exit.
        self._adapter_manager.disconnect_all()

        logger.info("MCA Editor closing")
        event.accept()
