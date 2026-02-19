"""
MCA Qt - Editor Panel.

The core MCA Editor as a standalone QWidget, suitable for embedding
inside any host window (standalone QMainWindow, Maya dockable, etc.).

Contains: splitters, tab widget, output, sidebar, AI panel, and all
editing/execution logic.

Does NOT contain: QMainWindow, menuBar(), toolBar(), statusBar(),
closeEvent, or geometry save. Those belong to the host.

The host provides:
    - A menu bar (via ``build_menus(menubar)``)
    - A status bar (via ``set_status_callback(callback)``)

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_qt.widgets (code editor, output, sidebar, AI panel)
    - mca_core (adapters, settings)
"""

import io
import os
import sys
import logging
import traceback
import webbrowser

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QToolBar, QLabel, QComboBox, QPushButton, QFileDialog,
    QMessageBox, QDialog, QInputDialog, QSize, QPlainTextEdit,
    Qt, QTimer, Signal,
    QAction, QActionGroup, QKeySequence, QTextCursor,
)

from mca_core.config.settings import MCASettings, EditorMode
from mca_qt.widgets.code_editor import MCACodeEditor
from mca_qt.widgets.output_window import OutputWindow
from mca_qt.widgets.sidebar import MCASidebar
from mca_qt.widgets.ai_panel import AIPanel
from mca_qt.widgets.settings_dialog import SettingsDialog
from mca_qt.widgets.connection_dialog import ConnectionDialog
from mca_qt.widgets.completer import CodeCompleter, CompletionProvider
from mca_core.adapters import AdapterManager, DCCType, ConnectionState

# Module-level logger.
logger = logging.getLogger(__name__)


# =============================================================================
# MCA Editor Panel (embeddable QWidget)
# =============================================================================

class MCAEditorPanel(QWidget):
    """
    Core MCA Editor panel as a standalone QWidget.

    Contains all editing, execution, tab management, and DCC connection
    logic. Designed to be embedded in any host window:
        - Standalone: wrapped by StandaloneWindow (QMainWindow)
        - Maya: wrapped by MCAMayaWindow (MayaQWidgetDockableMixin)

    The host is responsible for providing a menu bar and status bar.
    Call ``build_menus(menubar)`` to populate the host's menu bar.
    Call ``set_status_callback(fn)`` so the panel can display status messages.

    :param MCASettings settings: Application settings instance.
    :param AdapterManager adapter_manager: The adapter manager. If None,
        a default one with built-in adapters is created.
    :param QWidget parent: Optional parent widget.
    """

    # Signal emitted when the panel wants to show a status message.
    # Args: (message, duration_ms)
    status_message = Signal(str, int)

    # Signal emitted when cursor position changes. Args: (line, col)
    cursor_position_changed = Signal(int, int)

    # Signal emitted when the active language changes. Args: (language_display)
    language_changed = Signal(str)

    # Signal emitted when the editor mode changes. Args: (mode_label)
    mode_changed = Signal(str)

    def __init__(self, settings, adapter_manager=None, parent=None):
        """
        Initialize the editor panel and all UI components.

        :param MCASettings settings: Application settings instance.
        :param AdapterManager adapter_manager: Optional adapter manager.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._settings = settings
        self._adapter_manager = adapter_manager or AdapterManager()
        self._editors = []  # List of (editor, tab_name, file_path) tuples
        self._editor_mode = settings.get_editor_mode()
        self._closed_files = []  # Track recently closed files for reopen feature.
        self._default_font_size = 12  # Base font size for zoom calculations.
        self._verbosity_level = "normal"  # Output verbosity: echo_all, normal, minimal.
        self._action_registry = {}  # name -> QAction, for keyboard shortcut editor.
        # Persistent namespace for local Python execution so variables survive
        # across multiple Execute calls (same behavior as Maya's interpreter).
        self._local_namespace = {"__builtins__": __builtins__}
        # Status callback — set by the host window.
        self._status_callback = None

        # Shared completion provider — one instance used by all editor tabs.
        self._completion_provider = CompletionProvider(
            self._settings, self._adapter_manager
        )

        # Menu-dependent action references (set when build_menus is called).
        # Initialized here so _apply_editor_mode doesn't crash before menus exist.
        self._simple_mode_action = None
        self._advanced_mode_action = None
        self._recent_files_menu = None

        # Build UI components.
        self._setup_ui()
        self._setup_toolbar()
        self._setup_connections()

        # Create the first empty buffer (like Charcoal Editor 2).
        self._new_buffer()

        # Apply the saved editor mode.
        self._apply_editor_mode()

        # Auto-detect running DCCs after a short delay.
        QTimer.singleShot(1000, self._auto_detect_dccs)

    # --- Status Message Helper -----------------------------------------------

    def _show_status(self, message, duration_ms=3000):
        """
        Show a status message via the host's status bar.

        :param str message: The message to display.
        :param int duration_ms: How long to display (milliseconds).
        """
        self.status_message.emit(message, duration_ms)
        if self._status_callback:
            self._status_callback(message, duration_ms)

    def set_status_callback(self, callback):
        """
        Set a callback for status messages.

        :param callable callback: Function accepting (message, duration_ms).
        """
        self._status_callback = callback

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the main UI layout with splitters and panels."""
        main_layout = QHBoxLayout(self)
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

        # --- Center: toolbar + editor tabs + output ---
        center_widget = QWidget()
        self._center_layout = QVBoxLayout(center_widget)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.setSpacing(0)

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

        self._center_layout.addWidget(self._center_splitter)
        self._main_splitter.addWidget(center_widget)

        # --- AI Panel (right panel) ---
        self._ai_panel = AIPanel(self._settings)
        self._ai_panel.setMinimumWidth(250)
        self._ai_panel.setMaximumWidth(500)
        self._main_splitter.addWidget(self._ai_panel)

        # Default: sidebar visible, AI panel hidden.
        self._main_splitter.setSizes([240, 800, 0])

    def _setup_toolbar(self):
        """Build the embedded toolbar with execution and mode controls."""
        self._toolbar = QToolBar("Main Toolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(20, 20))
        self._toolbar.setStyleSheet("""
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
        # Insert toolbar at the top of center layout.
        self._center_layout.insertWidget(0, self._toolbar)

        # --- File operations ---
        self._toolbar.addAction("New").triggered.connect(self._new_buffer)
        self._toolbar.addAction("Open").triggered.connect(self._open_file)
        self._toolbar.addAction("Save").triggered.connect(self._save_file)

        self._toolbar.addSeparator()

        # --- Execution buttons (like Charcoal Editor 2) ---
        exec_all_btn = self._toolbar.addAction("Execute")
        exec_all_btn.setToolTip("Execute entire script (Ctrl+Shift+Enter)")
        exec_all_btn.triggered.connect(self._execute_all)

        exec_sel_btn = self._toolbar.addAction("Selected")
        exec_sel_btn.setToolTip("Execute selected text (Ctrl+Enter)")
        exec_sel_btn.triggered.connect(self._execute_selected)

        exec_line_btn = self._toolbar.addAction("Line")
        exec_line_btn.setToolTip("Execute current line (Ctrl+Alt+Enter)")
        exec_line_btn.triggered.connect(self._execute_line)

        self._toolbar.addSeparator()

        # --- Language selector ---
        lang_label = QLabel("  Language: ")
        lang_label.setStyleSheet("color: #969696; font-size: 11px;")
        self._toolbar.addWidget(lang_label)

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
        self._toolbar.addWidget(self._lang_combo)

        self._toolbar.addSeparator()

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
        self._toolbar.addWidget(self._dcc_indicator)

        # Spacer to push mode toggle to the right.
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        self._toolbar.addWidget(spacer)

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
        self._toolbar.addWidget(self._mode_toggle)

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

    # --- Menu Building (called by the host) ----------------------------------

    def build_menus(self, menubar):
        """
        Populate a menu bar with all MCA Editor menus.

        Called by the host window (standalone or Maya) to build the
        complete menu structure. The host provides the QMenuBar.

        :param QMenuBar menubar: The menu bar to populate.
        """
        self._build_file_menu(menubar)
        self._build_edit_menu(menubar)
        self._build_view_menu(menubar)
        self._build_go_menu(menubar)
        self._build_output_menu(menubar)
        self._build_command_menu(menubar)
        self._build_dcc_menu(menubar)
        self._build_help_menu(menubar)

    def _create_action(self, menu, text, name=None, shortcut=None, callback=None):
        """
        Create a QAction owned by the panel, add it to a menu, and
        optionally register it in the keyboard shortcut registry.

        Actions are parented to ``self`` (the panel) instead of the menu
        so PySide6 cannot garbage-collect the C++ QAction when the host
        window's menu bar is rebuilt or destroyed.

        :param QMenu menu: The menu to add the action to.
        :param str text: Display text for the action.
        :param str name: Registry name for keyboard shortcuts. If None,
            the action is not registered.
        :param str shortcut: Key sequence string (e.g., "Ctrl+N").
        :param callable callback: Slot to connect to ``triggered``.
        :return: The newly created QAction.
        :rtype: QAction
        """
        # Parent to self so the C++ object lives as long as the panel.
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            # Scope the shortcut to our widget tree only. This prevents
            # Maya's window-level hotkeys (Ctrl+D = Duplicate, etc.) from
            # intercepting keys that should go to our editor actions.
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        if callback:
            action.triggered.connect(callback)
        menu.addAction(action)
        # Also add to the panel's own action list. Qt's shortcut matching
        # only checks a widget's actions() list for WidgetWithChildrenShortcut
        # context — just being parented isn't enough. Without this, our
        # Ctrl+D never fires because Qt can't find it during matching.
        self.addAction(action)
        if name:
            self._action_registry[name] = action
        return action

    def _build_file_menu(self, menubar):
        """Build the File menu."""
        file_menu = menubar.addMenu("&File")

        # --- New buffer actions ---
        self._create_action(file_menu, "New...", name="New Buffer",
                            shortcut="Ctrl+N", callback=self._new_buffer)
        self._create_action(file_menu, "New MEL Buffer", name="New MEL Buffer",
                            shortcut="Ctrl+Alt+N", callback=self._new_mel_buffer)
        self._create_action(file_menu, "New Python Buffer", name="New Python Buffer",
                            shortcut="Ctrl+Shift+N", callback=self._new_python_buffer)

        # --- Open ---
        self._create_action(file_menu, "Open File...", name="Open File",
                            shortcut="Ctrl+O", callback=self._open_file)

        # Recent Files submenu (rebuilt dynamically).
        self._recent_files_menu = file_menu.addMenu("Recent Files")
        self._build_recent_files_menu()

        file_menu.addSeparator()

        # --- Workspace actions (no registration, no shortcut) ---
        self._create_action(file_menu, "Open Workspace...",
                            callback=self._open_workspace)
        self._create_action(file_menu, "Add Folder to Workspace...",
                            callback=self._add_folder_to_workspace)
        self._create_action(file_menu, "Save Workspace As...",
                            callback=lambda: self._show_status("Save Workspace As: coming soon"))

        file_menu.addSeparator()

        # --- Save actions ---
        self._create_action(file_menu, "Save", name="Save",
                            shortcut="Ctrl+S", callback=self._save_file)
        self._create_action(file_menu, "Save As...", name="Save As",
                            shortcut="Ctrl+Shift+S", callback=self._save_file_as)
        self._create_action(file_menu, "Save All", name="Save All",
                            callback=self._save_all)
        self._create_action(file_menu, "Rename...", name="Rename",
                            callback=self._rename_file)

        file_menu.addSeparator()

        # --- Shelf and source ---
        self._create_action(file_menu, "Save Script to Shelf...", name="Save Script to Shelf",
                            callback=self._save_to_shelf)
        self._create_action(file_menu, "Source Script...", name="Source Script",
                            callback=self._source_script)

        file_menu.addSeparator()

        # --- File management ---
        self._create_action(file_menu, "Revert File", name="Revert File",
                            callback=self._revert_file)
        self._create_action(file_menu, "Close File", name="Close File",
                            shortcut="Ctrl+W",
                            callback=lambda: self._close_tab(self._tab_widget.currentIndex()))
        self._create_action(file_menu, "Close All Files", name="Close All Files",
                            callback=self._close_all_files)
        self._create_action(file_menu, "Save State", name="Save State",
                            callback=self._save_state)

    def _build_edit_menu(self, menubar):
        """Build the Edit menu."""
        edit_menu = menubar.addMenu("&Edit")

        # --- Undo / Redo ---
        self._create_action(edit_menu, "Undo", name="Undo",
                            shortcut="Ctrl+Z",
                            callback=lambda: self._current_editor() and self._current_editor().undo())
        self._create_action(edit_menu, "Redo", name="Redo",
                            shortcut="Ctrl+Y",
                            callback=lambda: self._current_editor() and self._current_editor().redo())

        edit_menu.addSeparator()

        # Clipboard actions use tab-based display text (shortcut is display-only).
        self._create_action(edit_menu, "Cut\tCtrl+X",
                            callback=lambda: self._current_editor() and self._current_editor().cut())
        self._create_action(edit_menu, "Copy\tCtrl+C",
                            callback=lambda: self._current_editor() and self._current_editor().copy())
        self._create_action(edit_menu, "Paste\tCtrl+V",
                            callback=lambda: self._current_editor() and self._current_editor().paste())
        self._create_action(edit_menu, "Select All\tCtrl+A",
                            callback=lambda: self._current_editor() and self._current_editor().selectAll())

        edit_menu.addSeparator()

        # Line operations submenu.
        line_menu = edit_menu.addMenu("Line")

        self._create_action(line_menu, "Increase Indent", name="Increase Indent",
                            shortcut="Ctrl+]", callback=self._increase_indent)
        self._create_action(line_menu, "Decrease Indent", name="Decrease Indent",
                            shortcut="Ctrl+[", callback=self._decrease_indent)
        self._create_action(line_menu, "Copy Line Up", name="Copy Line Up",
                            shortcut="Alt+Shift+Up", callback=self._copy_line_up)
        self._create_action(line_menu, "Copy Line Down", name="Copy Line Down",
                            shortcut="Alt+Shift+Down", callback=self._copy_line_down)
        self._create_action(line_menu, "Move Line Up", name="Move Line Up",
                            shortcut="Alt+Up", callback=self._move_line_up)
        self._create_action(line_menu, "Move Line Down", name="Move Line Down",
                            shortcut="Alt+Down", callback=self._move_line_down)
        self._create_action(line_menu, "Delete Line", name="Delete Line",
                            shortcut="Ctrl+Shift+K", callback=self._delete_line)

        # Comment submenu.
        comment_menu = edit_menu.addMenu("Comment")

        # Toggle Line Comment uses tab-based display text (shortcut is display-only).
        self._create_action(comment_menu, "Toggle Line Comment\tCtrl+/",
                            name="Toggle Line Comment",
                            callback=self._toggle_comment_action)
        self._create_action(comment_menu, "Toggle Block Comment", name="Toggle Block Comment",
                            callback=self._toggle_block_comment)

        self._create_action(edit_menu, "Convert Tabs to Spaces", name="Convert Tabs to Spaces",
                            callback=self._convert_tabs_to_spaces)

        edit_menu.addSeparator()

        # --- Find / Replace ---
        self._create_action(edit_menu, "Find...", name="Find",
                            shortcut="Ctrl+F", callback=self._show_find)
        self._create_action(edit_menu, "Replace...", name="Replace",
                            shortcut="Ctrl+H", callback=self._show_replace)
        self._create_action(edit_menu, "Find in Files...", name="Find in Files",
                            shortcut="Ctrl+Shift+F", callback=self._find_in_files)
        self._create_action(edit_menu, "Replace in Files...", name="Replace in Files",
                            shortcut="Ctrl+Shift+H", callback=self._replace_in_files)

        edit_menu.addSeparator()

        # --- Misc edit actions ---
        self._create_action(edit_menu, "Insert Path...", name="Insert Path",
                            callback=self._insert_path)
        self._create_action(edit_menu, "Clear Output", name="Clear Output",
                            shortcut="Ctrl+Shift+1", callback=self._clear_output)

        edit_menu.addSeparator()

        # Settings action (not registered — no name).
        self._create_action(edit_menu, "Settings...",
                            shortcut="Ctrl+Shift+P", callback=self._show_settings)

    def _build_view_menu(self, menubar):
        """Build the View menu."""
        view_menu = menubar.addMenu("&View")

        # --- Panel visibility ---
        self._create_action(view_menu, "Explorer", name="Explorer",
                            shortcut="Ctrl+Shift+E", callback=self._toggle_sidebar)
        self._create_action(view_menu, "Search",
                            callback=lambda: self._show_status("Search panel: coming soon"))
        self._create_action(view_menu, "Quick Help",
                            shortcut="Ctrl+Shift+Q",
                            callback=lambda: self._show_status("Quick Help: coming soon"))

        view_menu.addSeparator()

        # --- Toggle actions (stored as instance vars for external access) ---
        self._create_action(view_menu, "Toggle Code Editor", name="Toggle Code Editor",
                            shortcut="Ctrl+K", callback=self._toggle_code_editor)
        self._toggle_output_action = self._create_action(
            view_menu, "Toggle Output", name="Toggle Output",
            shortcut="Ctrl+J", callback=self._toggle_output)
        self._toggle_sidebar_action = self._create_action(
            view_menu, "Toggle Side Bar", name="Toggle Side Bar",
            shortcut="Ctrl+B", callback=self._toggle_sidebar)
        self._create_action(view_menu, "Hide Activity Bar",
                            callback=lambda: self._show_status("Hide Activity Bar: coming soon"))

        view_menu.addSeparator()

        self._create_action(view_menu, "Toggle Code Editor Layout",
                            shortcut="Alt+Shift+1",
                            callback=lambda: self._show_status("Code Editor Layout: coming soon"))

        view_menu.addSeparator()

        # --- Checkable whitespace / word-wrap toggles ---
        self._whitespace_action = self._create_action(
            view_menu, "Toggle Render Whitespaces",
            callback=self._toggle_whitespace)
        self._whitespace_action.setCheckable(True)

        self._word_wrap_action = self._create_action(
            view_menu, "Toggle Word Wrap",
            callback=self._toggle_word_wrap)
        self._word_wrap_action.setCheckable(True)
        self._word_wrap_action.setChecked(self._settings.get("word_wrap", False))

        view_menu.addSeparator()

        # --- Font size ---
        self._create_action(view_menu, "Increase Font Size", name="Increase Font Size",
                            shortcut="Ctrl+=", callback=self._increase_font_size)
        self._create_action(view_menu, "Decrease Font Size", name="Decrease Font Size",
                            shortcut="Ctrl+-", callback=self._decrease_font_size)
        self._create_action(view_menu, "Reset Font Size", name="Reset Font Size",
                            shortcut="Ctrl+0", callback=self._reset_font_size)

        view_menu.addSeparator()

        # --- Editor mode toggles (checkable, stored for _apply_editor_mode) ---
        self._simple_mode_action = self._create_action(
            view_menu, "Simple Mode",
            callback=lambda: self._set_editor_mode(EditorMode.SIMPLE))
        self._simple_mode_action.setCheckable(True)

        self._advanced_mode_action = self._create_action(
            view_menu, "Advanced Mode",
            callback=lambda: self._set_editor_mode(EditorMode.ADVANCED))
        self._advanced_mode_action.setCheckable(True)

        # --- AI panel toggle (stored for external access) ---
        self._toggle_ai_action = self._create_action(
            view_menu, "Toggle AI Panel",
            shortcut="Ctrl+Shift+A", callback=self._toggle_ai_panel)

    def _build_go_menu(self, menubar):
        """Build the Go menu."""
        go_menu = menubar.addMenu("&Go")

        # --- Switch Editor submenu ---
        switch_menu = go_menu.addMenu("Switch Editor")

        self._create_action(switch_menu, "Next Editor", name="Next Editor",
                            shortcut="Ctrl+PgDown", callback=self._next_editor)
        self._create_action(switch_menu, "Previous Editor", name="Previous Editor",
                            shortcut="Ctrl+PgUp", callback=self._prev_editor)

        # Tab-based display text (shortcut is display-only).
        self._create_action(switch_menu, "Next Used Editor\tCtrl+Tab",
                            callback=self._next_editor)
        self._create_action(switch_menu, "Previous Used Editor\tCtrl+Shift+Tab",
                            callback=self._prev_editor)

        # --- Switch Group submenu (stub) ---
        switch_group = go_menu.addMenu("Switch Group")
        sg_stub = switch_group.addAction("No groups")
        sg_stub.setEnabled(False)

        go_menu.addSeparator()

        # --- Navigation ---
        self._create_action(go_menu, "Go to File...", name="Go to File",
                            shortcut="Ctrl+P", callback=self._go_to_file)
        self._create_action(go_menu, "Go to Symbol in File...", name="Go to Symbol in File",
                            shortcut="Ctrl+Shift+O", callback=self._go_to_symbol)
        self._create_action(go_menu, "Go to Line...", name="Go to Line",
                            shortcut="Ctrl+G", callback=self._show_goto_line)

    def _build_output_menu(self, menubar):
        """Build the Output menu."""
        output_menu = menubar.addMenu("&Output")

        # --- Verbosity submenu with exclusive action group ---
        verbosity_menu = output_menu.addMenu("Verbosity")
        self._verbosity_group = QActionGroup(self)
        for label, level in [("Echo All", "echo_all"), ("Normal", "normal"), ("Minimal", "minimal")]:
            # Create the action via helper, then configure group membership and data.
            act = self._create_action(verbosity_menu, label)
            act.setCheckable(True)
            act.setData(level)
            self._verbosity_group.addAction(act)
            if level == self._verbosity_level:
                act.setChecked(True)
        self._verbosity_group.triggered.connect(
            lambda action: self._set_verbosity(action.data())
        )

        output_menu.addSeparator()

        # --- Checkable output toggles (stored as instance vars) ---
        self._line_numbers_action = self._create_action(
            output_menu, "Line Numbers in Errors",
            callback=self._toggle_line_numbers_in_errors)
        self._line_numbers_action.setCheckable(True)
        self._line_numbers_action.setChecked(True)

        self._stack_trace_action = self._create_action(
            output_menu, "Show Stack Trace",
            callback=self._toggle_stack_trace)
        self._stack_trace_action.setCheckable(True)
        self._stack_trace_action.setChecked(True)

        self._suppress_stack_action = self._create_action(
            output_menu, "Suppress Stack Window",
            callback=self._toggle_suppress_stack)
        self._suppress_stack_action.setCheckable(True)

        output_menu.addSeparator()

        self._create_action(output_menu, "Write Output to File...",
                            callback=self._write_output_to_file)

    def _build_command_menu(self, menubar):
        """Build the Command menu."""
        cmd_menu = menubar.addMenu("&Command")

        # --- Execution actions ---
        self._create_action(cmd_menu, "Execute", name="Execute",
                            shortcut="Ctrl+Return", callback=self._execute_selected)
        self._create_action(cmd_menu, "Execute Line", name="Execute Line",
                            shortcut="Ctrl+Alt+Return", callback=self._execute_line)
        self._create_action(cmd_menu, "Execute All", name="Execute All",
                            shortcut="Ctrl+Shift+Return", callback=self._execute_all)

        cmd_menu.addSeparator()

        # --- Environment Variables submenu ---
        env_menu = cmd_menu.addMenu("Environment Variables")
        env_vars = [
            "MAYA_SCRIPT_PATH", "MAYA_PLUG_IN_PATH", "MAYA_MODULE_PATH",
            "MAYA_SHELF_PATH", "XBMLANGPATH", "PYTHONPATH",
        ]
        for var in env_vars:
            # Each env var action uses a lambda with captured variable.
            self._create_action(env_menu, var,
                                callback=lambda checked, v=var: self._show_env_var(v))

        cmd_menu.addSeparator()

        # --- Stub submenus ---
        python_menu = cmd_menu.addMenu("Python")
        py_stub = python_menu.addAction("Python settings coming soon")
        py_stub.setEnabled(False)

        pylint_menu = cmd_menu.addMenu("Pylint")
        pl_stub = pylint_menu.addAction("Pylint integration coming soon")
        pl_stub.setEnabled(False)

    def _build_dcc_menu(self, menubar):
        """Build the DCC menu."""
        dcc_menu = menubar.addMenu("&DCC")

        # --- DCC connection actions (no registration needed) ---
        self._create_action(dcc_menu, "Connect to DCC...",
                            callback=self._show_connect_dialog)
        self._create_action(dcc_menu, "Disconnect",
                            callback=self._disconnect_dcc)

        dcc_menu.addSeparator()

        self._create_action(dcc_menu, "Detect Running DCCs",
                            callback=self._auto_detect_dccs)

    def _build_help_menu(self, menubar):
        """Build the Help menu."""
        help_menu = menubar.addMenu("&Help")

        # --- Reference links ---
        self._create_action(help_menu, "MEL Command Reference",
                            callback=self._open_mel_reference)
        self._create_action(help_menu, "Python Command Reference",
                            callback=self._open_python_reference)
        self._create_action(help_menu, "Node and Attribute Reference",
                            callback=self._open_node_reference)

        help_menu.addSeparator()

        # --- About / licensing ---
        self._create_action(help_menu, "Licensing...",
                            callback=self._show_licensing)
        self._create_action(help_menu, "About MCA Editor",
                            callback=self._show_about)

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
            self._sidebar.setVisible(False)
            self._ai_panel.setVisible(False)
            self._main_splitter.setSizes([0, 1000, 0])
            self._mode_toggle.setText("Advanced")
            if self._simple_mode_action:
                self._simple_mode_action.setChecked(True)
            if self._advanced_mode_action:
                self._advanced_mode_action.setChecked(False)
            self.mode_changed.emit("Simple")
        else:
            self._sidebar.setVisible(True)
            self._sidebar.set_advanced_mode()
            self._ai_panel.setVisible(False)
            self._main_splitter.setSizes([240, 800, 0])
            self._mode_toggle.setText("Simple")
            if self._simple_mode_action:
                self._simple_mode_action.setChecked(False)
            if self._advanced_mode_action:
                self._advanced_mode_action.setChecked(True)
            self.mode_changed.emit("Advanced")

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
            sizes = self._main_splitter.sizes()
            if sizes[-1] == 0:
                total = sum(sizes)
                sizes[-1] = 300
                sizes[1] = total - sizes[0] - sizes[-1]
                self._main_splitter.setSizes(sizes)

    # =========================================================================
    # Tab / Buffer Management
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
        Create a new temporary buffer.

        :return: The newly created editor widget.
        :rtype: MCACodeEditor
        """
        editor = MCACodeEditor()

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))

        # Attach a code completer to the new buffer.
        self._attach_completer(editor)

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

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))

        # Attach a code completer to the opened file's editor.
        self._attach_completer(editor)

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

        :param int index: Tab index to close.
        """
        if index < 0 or index >= len(self._editors):
            return
        editor, name, path = self._editors[index]
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
        if path:
            self._closed_files.append(path)
        self._update_open_editors()
        if self._tab_widget.count() == 0:
            self._new_buffer()

    def _on_tab_changed(self, index):
        """Handle tab selection changes."""
        editor = self._current_editor()
        if editor:
            self._update_outline(editor)
            self._update_language_combo(editor)
            self._update_cursor_pos(
                editor.textCursor().blockNumber() + 1,
                editor.textCursor().columnNumber() + 1
            )

    def _on_editor_modified(self, editor, modified):
        """Handle editor modification state changes."""
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

    def _attach_completer(self, editor):
        """
        Create a CodeCompleter for an editor and wire up the signal.

        Each editor tab gets its own completer widget, but all share
        the same CompletionProvider so adapter/settings state is consistent.

        :param MCACodeEditor editor: The editor to attach a completer to.
        """
        completer = CodeCompleter(editor, self._completion_provider, self._settings)
        editor._settings = self._settings
        editor.set_completer(completer)
        # Connect the editor's completion_requested signal to the completer.
        editor.completion_requested.connect(
            lambda manual: completer.trigger(manual=manual)
        )

    def _update_outline(self, editor):
        """Update the code outline panel."""
        outline = editor.get_code_outline()
        self._sidebar.outline_panel.update_outline(outline)

    def _goto_outline_item(self, line):
        """Jump to a line from the outline panel."""
        editor = self._current_editor()
        if editor:
            editor.go_to_line(line)

    def _update_language_combo(self, editor):
        """Sync the toolbar language combo with the editor's language."""
        lang_map = {"python": "Python", "mel": "MEL"}
        display = lang_map.get(editor.language, "Python")
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentText(display)
        self._lang_combo.blockSignals(False)
        self.language_changed.emit(display)

    def _on_language_changed(self, language):
        """Handle toolbar language combo changes."""
        editor = self._current_editor()
        if editor:
            editor.set_language(language.lower())
            self.language_changed.emit(language)
            idx = self._tab_widget.currentIndex()
            if idx >= 0 and idx < len(self._editors):
                e, name, path = self._editors[idx]
                if path is None:
                    new_name = language
                    modified = e.document().isModified()
                    display = "[*] {}".format(new_name) if modified else new_name
                    self._tab_widget.setTabText(idx, display)
                    self._editors[idx] = (e, new_name, path)
                    self._update_open_editors()

    def _update_cursor_pos(self, line, col):
        """Emit cursor position so the host can update its status bar."""
        self.cursor_position_changed.emit(line, col)

    # =========================================================================
    # Execution
    # =========================================================================

    def _execute_all(self):
        """Execute the entire script."""
        editor = self._current_editor()
        if not editor:
            return
        code = editor.get_all_text()
        if not code.strip():
            return
        if self._settings.get("auto_save_on_execute") and editor.file_path:
            self._write_file(editor, editor.file_path)
        self._output.write_code_echo(code.strip())
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            adapter.execute(code, editor.language)
        else:
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
        """Execute Python code locally when no DCC is connected."""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
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
        """Auto-detect running DCC applications.

        Skips detection if we already have an active, connected adapter
        (e.g., InternalMayaAdapter when running inside Maya).
        """
        # No need to scan processes if we're already connected to a DCC.
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            return

        detected = self._adapter_manager.detect_running_dccs()
        if detected:
            names = ", ".join(d["name"] for d in detected)
            self._output.write_info("Detected running DCCs: {}".format(names))
            self._show_status("Detected: {}".format(names), 5000)

    # =========================================================================
    # Edit/View/Go/Output/Command/Help handlers
    # (Identical logic to MCAMainWindow, using _show_status instead of statusBar)
    # =========================================================================

    def _new_mel_buffer(self):
        """Create a new MEL buffer."""
        editor = self._new_buffer()
        editor.set_language("mel")
        idx = self._tab_widget.currentIndex()
        self._tab_widget.setTabText(idx, "MEL")
        self._editors[idx] = (editor, "MEL", None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _new_python_buffer(self):
        """Create a new Python buffer."""
        editor = self._new_buffer()
        editor.set_language("python")
        idx = self._tab_widget.currentIndex()
        self._tab_widget.setTabText(idx, "Python")
        self._editors[idx] = (editor, "Python", None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _build_recent_files_menu(self):
        """Rebuild the Recent Files submenu."""
        if not self._recent_files_menu:
            return
        self._recent_files_menu.clear()
        reopen = self._recent_files_menu.addAction("Reopen Closed File")
        reopen.triggered.connect(self._reopen_closed_file)
        reopen.setEnabled(len(self._closed_files) > 0)
        clear = self._recent_files_menu.addAction("Clear Items")
        clear.triggered.connect(self._clear_recent_files)
        self._recent_files_menu.addSeparator()
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
        """Clear the recent files list."""
        self._settings.set("recent_files", [])
        self._closed_files.clear()
        self._build_recent_files_menu()
        self._show_status("Recent files cleared")

    def _open_workspace(self):
        """Open a folder as workspace."""
        folder = QFileDialog.getExistingDirectory(self, "Open Workspace")
        if folder:
            self._sidebar.workspace_panel.add_folder(folder)
            self._output.write_info("Opened workspace: {}".format(folder))

    def _add_folder_to_workspace(self):
        """Add a folder to the workspace."""
        folder = QFileDialog.getExistingDirectory(self, "Add Folder to Workspace")
        if folder:
            self._sidebar.workspace_panel.add_folder(folder)
            self._output.write_info("Added folder to workspace: {}".format(folder))

    def _save_all(self):
        """Save all modified files."""
        saved_count = 0
        for editor, name, path in self._editors:
            if path and editor.document().isModified():
                self._write_file(editor, path)
                saved_count += 1
        self._show_status("Saved {} file(s)".format(saved_count))

    def _rename_file(self):
        """Rename the current file."""
        editor = self._current_editor()
        if not editor or not editor.file_path:
            self._show_status("No file to rename (save first)")
            return
        old_path = editor.file_path
        new_name, ok = QInputDialog.getText(
            self, "Rename File", "New file name:", text=os.path.basename(old_path)
        )
        if ok and new_name:
            new_path = os.path.join(os.path.dirname(old_path), new_name)
            try:
                os.rename(old_path, new_path)
                editor.file_path = new_path
                idx = self._tab_widget.currentIndex()
                self._tab_widget.setTabText(idx, new_name)
                self._editors[idx] = (editor, new_name, new_path)
                self._settings.add_recent_file(new_path)
                self._update_open_editors()
                self._output.write_info("Renamed: {} -> {}".format(old_path, new_path))
            except Exception as exc:
                QMessageBox.warning(self, "Error", "Could not rename file:\n{}".format(str(exc)))

    def _save_to_shelf(self):
        """Save to shelf (stub)."""
        self._show_status("Save to Shelf: requires DCC connection (coming soon)")

    def _source_script(self):
        """Source a script file."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Source Script", "",
            "Script Files (*.py *.mel);;Python Files (*.py);;MEL Files (*.mel);;All Files (*.*)"
        )
        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                self._output.write_info("Sourcing: {}".format(filepath))
                lang = "mel" if filepath.endswith(".mel") else "python"
                adapter = self._adapter_manager.get_active_adapter()
                if adapter and adapter.is_connected:
                    adapter.execute(code, lang)
                elif lang == "python":
                    self._execute_locally(code)
                else:
                    self._output.write_warning("No DCC connected. Cannot source MEL scripts locally.")
            except Exception as exc:
                QMessageBox.warning(self, "Error", "Could not source script:\n{}".format(str(exc)))

    def _revert_file(self):
        """Revert file from disk."""
        editor = self._current_editor()
        if not editor or not editor.file_path:
            self._show_status("No file to revert")
            return
        if editor.document().isModified():
            reply = QMessageBox.question(
                self, "Revert File", "Discard all changes and reload from disk?",
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
            QMessageBox.warning(self, "Error", "Could not revert file:\n{}".format(str(exc)))

    def _close_all_files(self):
        """Close all tabs."""
        while self._tab_widget.count() > 0:
            self._close_tab(0)
            if self._tab_widget.count() == 1:
                break

    def _save_state(self):
        """Save open files to settings."""
        open_files = [path for _, _, path in self._editors if path]
        self._settings.set("open_files", open_files)
        self._settings.sync()
        self._show_status("State saved ({} files)".format(len(open_files)))

    # --- Edit handlers ---

    def _increase_indent(self):
        editor = self._current_editor()
        if editor:
            editor._indent_selection()

    def _decrease_indent(self):
        editor = self._current_editor()
        if editor:
            editor._unindent_selection()

    def _copy_line_up(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        line_text = cursor.selectedText()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(line_text + "\n")
        cursor.movePosition(QTextCursor.MoveOperation.Up)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _copy_line_down(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        line_text = cursor.selectedText()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + line_text)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _move_line_up(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if cursor.blockNumber() == 0:
            return
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        current = cursor.selectedText()
        cursor.removeSelectedText()
        cursor.deletePreviousChar()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(current + "\n")
        cursor.movePosition(QTextCursor.MoveOperation.Up)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _move_line_down(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if cursor.blockNumber() >= editor.document().blockCount() - 1:
            return
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        current = cursor.selectedText()
        cursor.removeSelectedText()
        cursor.deleteChar()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cursor.insertText("\n" + current)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _delete_line(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        if not cursor.atEnd():
            cursor.deleteChar()
        elif cursor.blockNumber() > 0:
            cursor.deletePreviousChar()
        cursor.endEditBlock()
        editor.setTextCursor(cursor)

    def _toggle_comment_action(self):
        editor = self._current_editor()
        if editor:
            editor._toggle_comment()

    def _toggle_block_comment(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            self._show_status("Select text to block-comment")
            return
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
            self._show_status("Tabs converted to spaces")
        else:
            self._show_status("No tabs to convert")

    def _show_find(self):
        self._show_status("Find: Ctrl+F (full search coming soon)")

    def _show_replace(self):
        self._show_status("Replace: Ctrl+H (coming soon)")

    def _find_in_files(self):
        self._show_status("Find in Files: coming soon")

    def _replace_in_files(self):
        self._show_status("Replace in Files: coming soon")

    def _insert_path(self):
        editor = self._current_editor()
        if not editor:
            return
        filepath, _ = QFileDialog.getOpenFileName(self, "Select File to Insert Path")
        if filepath:
            editor.insertPlainText(filepath)

    def _clear_output(self):
        self._output.clear()

    def _show_settings(self):
        dlg = SettingsDialog(self._settings, action_registry=self._action_registry, parent=self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._apply_settings_to_editors()

    def _apply_settings_to_editors(self):
        """Push current settings to all open editors."""
        s = self._settings
        font_family = s.get("font_family")
        font_size = s.get("font_size")
        tab_size = s.get("tab_size")
        for editor, _name, _path in self._editors:
            font = editor.font()
            font.setFamily(font_family)
            font.setPointSize(font_size)
            editor.setFont(font)
            editor.setTabStopDistance(font_size * tab_size)
        output_wrap = s.get("output_word_wrap")
        if hasattr(self._output, "_output"):
            wrap_mode = (
                QPlainTextEdit.LineWrapMode.WidgetWidth if output_wrap
                else QPlainTextEdit.LineWrapMode.NoWrap
            )
            self._output._output.setLineWrapMode(wrap_mode)
        self._tab_widget.tabBar().setVisible(s.get("show_tab_bar"))
        self._tab_widget.setTabsClosable(s.get("show_close_button_on_tab"))
        self._tab_widget.setMovable(not s.get("lock_tabs"))
        logger.info("Settings applied to running editors")

    # --- View handlers ---

    def _toggle_code_editor(self):
        self._tab_widget.setVisible(not self._tab_widget.isVisible())

    def _toggle_word_wrap(self, checked):
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth if checked
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        for editor, name, path in self._editors:
            editor.setLineWrapMode(mode)
        self._settings.set("word_wrap", checked)

    def _toggle_whitespace(self, checked):
        self._settings.set("show_whitespace", checked)
        self._show_status("Whitespace rendering: {}".format("on" if checked else "off"))

    def _increase_font_size(self):
        self._default_font_size += 1
        self._apply_font_size()

    def _decrease_font_size(self):
        if self._default_font_size > 6:
            self._default_font_size -= 1
            self._apply_font_size()

    def _reset_font_size(self):
        self._default_font_size = 12
        self._apply_font_size()

    def _apply_font_size(self):
        for editor, name, path in self._editors:
            font = editor.font()
            font.setPointSize(self._default_font_size)
            editor.setFont(font)
            editor.setTabStopDistance(
                editor.fontMetrics().horizontalAdvance(" ") * editor._tab_size
            )
        self._settings.set("font_size", self._default_font_size)
        self._show_status("Font size: {}pt".format(self._default_font_size))

    # --- Go handlers ---

    def _next_editor(self):
        count = self._tab_widget.count()
        if count > 1:
            idx = (self._tab_widget.currentIndex() + 1) % count
            self._tab_widget.setCurrentIndex(idx)

    def _prev_editor(self):
        count = self._tab_widget.count()
        if count > 1:
            idx = (self._tab_widget.currentIndex() - 1) % count
            self._tab_widget.setCurrentIndex(idx)

    def _go_to_file(self):
        self._show_status("Go to File: coming soon")

    def _go_to_symbol(self):
        self._show_status("Go to Symbol: coming soon")

    def _show_goto_line(self):
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

    # --- Output handlers ---

    def _set_verbosity(self, level):
        self._verbosity_level = level
        self._settings.set("output_verbosity", level)
        self._show_status("Verbosity: {}".format(level))

    def _toggle_line_numbers_in_errors(self, checked):
        self._settings.set("line_numbers_in_errors", checked)
        self._show_status("Line numbers in errors: {}".format("on" if checked else "off"))

    def _toggle_stack_trace(self, checked):
        self._settings.set("show_stack_trace", checked)
        self._show_status("Stack trace: {}".format("on" if checked else "off"))

    def _toggle_suppress_stack(self, checked):
        self._settings.set("suppress_stack_window", checked)
        self._show_status("Suppress stack window: {}".format("on" if checked else "off"))

    def _write_output_to_file(self):
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
                QMessageBox.warning(self, "Error", "Could not write output:\n{}".format(str(exc)))

    # --- Command handlers ---

    def _show_env_var(self, var_name):
        value = os.environ.get(var_name, "")
        if value:
            self._output.write_info("{} = {}".format(var_name, value))
        else:
            self._output.write_warning("{} is not set".format(var_name))

    # --- Help handlers ---

    def _open_mel_reference(self):
        webbrowser.open("https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/")

    def _open_python_reference(self):
        webbrowser.open("https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/")

    def _open_node_reference(self):
        webbrowser.open("https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Nodes/")

    def _show_licensing(self):
        QMessageBox.information(
            self, "Licensing",
            "<h3>MCA Editor Licensing</h3>"
            "<p><b>Current Tier:</b> Free / Open Source</p>"
            "<p>MCA Editor is currently in early development.<br>"
            "Future licensing tiers (Standard, Pro, Studio) are planned.</p>"
            "<hr>"
            "<p style='color: #888;'>Contact: support@mcatools.com</p>"
        )

    def _show_about(self):
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
    # Public API for hosts
    # =========================================================================

    def check_unsaved_changes(self):
        """
        Check if any editors have unsaved changes.

        :return: True if there are unsaved changes.
        :rtype: bool
        """
        for editor, name, path in self._editors:
            if editor.document().isModified():
                return True
        return False

    def save_window_state(self, settings):
        """
        Save splitter sizes to settings (called by host on close).

        :param MCASettings settings: Settings to save to.
        """
        settings.set("splitter_sizes", self._main_splitter.sizes())
        settings.sync()

    def cleanup(self):
        """Clean up resources (called by host on close)."""
        self._adapter_manager.disconnect_all()
        logger.info("MCA Editor panel cleaning up")
