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
    QApplication,
    Qt, QTimer, Signal, QEvent, QMenu,
    QAction, QActionGroup, QKeySequence, QTextCursor,
)

from mca_core.config.settings import MCASettings, EditorMode
from mca_core.session_manager import SessionManager
from mca_qt.widgets.code_editor import MCACodeEditor
from mca_qt.widgets.output_window import OutputWindow
from mca_qt.widgets.sidebar import MCASidebar
from mca_qt.widgets.ai_panel import AIPanel
from mca_qt.widgets.settings_dialog import SettingsDialog
from mca_qt.widgets.connection_dialog import ConnectionDialog
from mca_qt.widgets.new_tab_dialog import NewTabDialog
from mca_qt.widgets.completer import CodeCompleter, CompletionProvider
from mca_qt.widgets.find_replace_bar import FindReplaceBar
from mca_qt.widgets.quick_open import GoToFilePopup, GoToSymbolPopup
from mca_qt.widgets.editor_group_container import EditorGroupContainer
from mca_core.adapters import AdapterManager, DCCType, ConnectionState
from mca_qt.icons import python_logo, maya_logo, text_icon

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

    # Signal forwarding error/warning counts from the output window.
    # Args: (error_count, warning_count)
    output_counts_changed = Signal(int, int)

    # Signal emitted when the user toggles the activity bar (bottom status bar).
    activity_bar_toggled = Signal()

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
        # Track whether the editor is embedded inside a DCC (e.g. Maya).
        # When embedded, the DCC menu and toolbar indicator are hidden
        # since the host already provides direct execution access.
        self._embedded_in_dcc = adapter_manager is not None
        # NOTE: _editors list is no longer maintained here — editors are
        # tracked inside EditorGroupContainer -> EditorGroup instances.
        self._editor_mode = settings.get_editor_mode()
        self._closed_files = []  # Track recently closed files for reopen feature.
        # Restore saved font size (falls back to 12 if never changed).
        self._default_font_size = settings.get("font_size", 12)
        self._verbosity_level = "normal"  # Output verbosity: echo_all, normal, minimal.
        self._action_registry = {}  # name -> QAction, for keyboard shortcut editor.
        # Persistent namespace for local Python execution so variables survive
        # across multiple Execute calls (same behavior as Maya's interpreter).
        self._local_namespace = {"__builtins__": __builtins__}
        # Status callback — set by the host window.
        self._status_callback = None

        # Session manager for buffer persistence across restarts.
        self._session_manager = SessionManager()

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

        # Restore previous session or create a fresh buffer.
        restored = False
        if settings.get("restore_session"):
            restored = self._restore_session()
        if not restored:
            self._new_buffer()

        # Ensure the default workspace (scripts + site-packages) exists,
        # and add site-packages to sys.path for user imports.
        self._init_default_workspace()

        # Apply the saved editor mode.
        self._apply_editor_mode()

        # Override mode defaults with user's last-saved UI state.
        self._restore_ui_state()

        # Restore the output panel content from the previous session.
        self._restore_output()

        # Auto-detect running DCCs after a short delay.
        QTimer.singleShot(1000, self._auto_detect_dccs)

    # --- Default Workspace Initialization ------------------------------------

    def _init_default_workspace(self):
        """
        Set up the workspace sidebar with saved or default folders.

        On first launch (no saved folders), creates the default
        ``mca_preferences/scripts/`` workspace and adds it to the
        sidebar. On subsequent launches, restores the previously
        saved workspace folders from settings.

        Also ensures the ``scripts/site-packages/`` directory exists
        and is on ``sys.path`` so user packages can be imported.
        """
        # Always ensure the default dirs exist and site-packages is on sys.path.
        default_scripts = self._session_manager.ensure_default_workspace()

        # Try to restore saved workspace folders from settings.
        saved = self._settings.get("workspace_folders", [])

        if saved and isinstance(saved, list):
            # Restore only folders that still exist on disk.
            valid = [f for f in saved if os.path.isdir(f)]
            if valid:
                self._sidebar.workspace_panel.set_workspace_folders(valid)
                return

        # First launch — seed the workspace with the default scripts folder.
        self._sidebar.workspace_panel.add_folder(default_scripts)

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

        # Editor group container — holds one or more editor groups
        # (each group is a QTabWidget with find bar and tab nav buttons).
        # Replaces the old single _tab_widget with split/side-by-side support.
        self._group_container = EditorGroupContainer()
        self._group_container.active_editor_changed.connect(self._on_active_editor_changed)
        self._group_container.editors_changed.connect(self._update_open_editors)
        self._group_container.tab_close_requested.connect(self._close_tab_in_group)
        self._center_splitter.addWidget(self._group_container)

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
        """Build the embedded toolbar with search, save, language, and mode controls."""
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

        # --- Language selector ---
        lang_label = QLabel("  Language: ")
        lang_label.setStyleSheet("color: #969696; font-size: 11px;")
        self._toolbar.addWidget(lang_label)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["Python", "MEL", "Text"])
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

        # --- DCC connection indicator (only visible when a DCC host is available) ---
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
        self._dcc_indicator.setVisible(not self._embedded_in_dcc)
        self._toolbar.addWidget(self._dcc_indicator)

        # --- Settings gear button ---
        settings_btn = QPushButton("\u2699")
        settings_btn.setToolTip("Settings")
        settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #969696;
                border: none;
                padding: 4px 8px;
                font-size: 16px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: #3e3e42;
            }
        """)
        settings_btn.clicked.connect(self._show_settings)
        self._toolbar.addWidget(settings_btn)

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
        self._sidebar.file_created.connect(self._open_file_path)
        self._sidebar.outline_item_clicked.connect(self._goto_outline_item)
        self._sidebar.editor_selected.connect(self._on_sidebar_editor_selected)

        # Sidebar header buttons -> file operations.
        self._sidebar.new_tab_requested.connect(self._show_new_tab_dialog)
        self._sidebar.open_file_requested.connect(self._open_file)

        # Output window error/warning counts -> forwarding signal for host windows.
        self._output.counts_changed.connect(self.output_counts_changed.emit)

        # Output verbosity combobox -> sync with panel's verbosity setting.
        self._output.verbosity_changed.connect(self._set_verbosity)
        # Restore the saved verbosity level in the output combobox.
        saved_verbosity = self._settings.get("output_verbosity", "normal")
        self._verbosity_level = saved_verbosity
        self._output.set_verbosity(saved_verbosity)

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
        # Hide the DCC menu when embedded inside a DCC (already connected).
        if not self._embedded_in_dcc:
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
        self._create_action(file_menu, "New Text Buffer", name="New Text Buffer",
                            callback=self._new_text_buffer)

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
        self._create_action(file_menu, "Unlock File", name="Unlock File",
                            callback=self._unlock_file)
        self._create_action(file_menu, "Close File", name="Close File",
                            shortcut="Ctrl+W",
                            callback=self._close_current_tab)
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
                            shortcut="Ctrl+D", callback=self._copy_line_down)
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
        # Activity bar toggle — emits signal so the host window can toggle its status bar.
        self._create_action(view_menu, "Toggle Activity Bar",
                            callback=lambda: self.activity_bar_toggled.emit())

        view_menu.addSeparator()

        # --- Split editor ---
        self._create_action(view_menu, "Split Editor Right", name="Split Editor Right",
                            shortcut="Ctrl+\\", callback=self._split_editor_right)

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

        self._create_action(go_menu, "Focus Next Group", name="Focus Next Group",
                            shortcut="Ctrl+K Ctrl+Right",
                            callback=self._group_container.focus_next_group)
        self._create_action(go_menu, "Focus Previous Group", name="Focus Previous Group",
                            shortcut="Ctrl+K Ctrl+Left",
                            callback=self._group_container.focus_previous_group)

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

    def _restore_ui_state(self):
        """
        Restore saved UI state from settings, overriding mode defaults.

        Must be called AFTER ``_apply_editor_mode()`` because mode
        application resets splitter sizes and panel visibility to
        defaults. This method layers the user's last-saved state on top.
        """
        s = self._settings

        # --- Main splitter (sidebar | editor | AI) ---
        saved_main = s.get("splitter_sizes")
        if saved_main:
            # QSettings may return strings — coerce to int.
            try:
                self._main_splitter.setSizes([int(v) for v in saved_main])
            except (TypeError, ValueError):
                pass

        # --- Center splitter (output | editor tabs) ---
        saved_center = s.get("center_splitter_sizes")
        if saved_center:
            try:
                self._center_splitter.setSizes([int(v) for v in saved_center])
            except (TypeError, ValueError):
                pass

        # --- Panel visibility ---
        # Only restore sidebar visibility in Advanced mode (Simple always hides it).
        if self._editor_mode == EditorMode.ADVANCED:
            sidebar_vis = s.get("sidebar_visible", True)
            self._sidebar.setVisible(sidebar_vis)

        output_vis = s.get("output_visible", True)
        self._output.setVisible(output_vis)

        ai_vis = s.get("ai_panel_visible", False)
        self._ai_panel.setVisible(ai_vis)

        # --- Whitespace rendering ---
        show_ws = s.get("show_whitespace", False)
        if show_ws:
            self._whitespace_action.setChecked(True)
            for editor, name, path in self._group_container.all_editors():
                editor.set_show_whitespace(True)

        # --- Font size (apply saved zoom level to all open editors) ---
        if self._default_font_size != 12:
            self._apply_font_size(notify=False)

    def _restore_output(self):
        """
        Restore the output panel content from the previous session.

        Loads the saved ``output.log`` file and inserts it into the
        output window using ``write_bulk()`` for efficiency.
        """
        saved_text = self._session_manager.load_output()
        if saved_text:
            self._output.write_bulk(saved_text)
            logger.info("Restored output log (%d chars)", len(saved_text))

    def _toggle_mode(self):
        """Toggle between simple and advanced mode."""
        if self._editor_mode == EditorMode.SIMPLE:
            self._set_editor_mode(EditorMode.ADVANCED)
        else:
            self._set_editor_mode(EditorMode.SIMPLE)

    def _toggle_sidebar(self):
        """Toggle sidebar visibility and persist the choice."""
        visible = not self._sidebar.isVisible()
        self._sidebar.setVisible(visible)
        self._settings.set("sidebar_visible", visible)

    def _toggle_output(self):
        """Toggle output window visibility and persist the choice."""
        visible = not self._output.isVisible()
        self._output.setVisible(visible)
        self._settings.set("output_visible", visible)

    def _toggle_ai_panel(self):
        """Toggle AI panel visibility, expanding it if needed, and persist."""
        visible = not self._ai_panel.isVisible()
        self._ai_panel.setVisible(visible)
        self._settings.set("ai_panel_visible", visible)
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
        return self._group_container.current_editor()

    def _new_buffer(self):
        """
        Create a new temporary buffer.

        :return: The newly created editor widget.
        :rtype: MCACodeEditor
        """
        editor = MCACodeEditor()

        # Buffer tracking — these attrs let us persist temp tabs to disk.
        # Allocated lazily on first save so we don't create files for
        # buffers that are never modified.
        editor._buffer_id = None
        editor._buffer_filename = None

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))
        editor.zoom_requested.connect(self._on_zoom_requested)

        # Attach a code completer to the new buffer.
        self._attach_completer(editor)

        # Inherit current font size and whitespace setting so new tabs match.
        self._apply_editor_state(editor)

        lang_map = {"python": "Python", "mel": "MEL", "text": "Text"}
        tab_name = lang_map.get(editor.language, "Python")

        icon = self._icon_for_language(editor.language)
        self._group_container.add_editor(editor, tab_name, None, icon)

        self._update_open_editors()
        return editor

    def _open_file(self):
        """Open a file from disk via file dialog."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "Script Files (*.py *.mel *.txt *.cs *.lua);;Python Files (*.py);;"
            "MEL Files (*.mel);;Text Files (*.txt);;All Files (*.*)"
        )
        if filepath:
            self._open_file_path(filepath)

    def _open_file_path(self, filepath):
        """
        Open a specific file. If already open, switch to its tab.

        :param str filepath: Absolute path to the file to open.
        """
        # Check if the file is already open in any group.
        group, idx, existing = self._group_container.find_editor_by_path(filepath)
        if group is not None:
            group.set_current_index(idx)
            # Activate that group.
            self._group_container._on_group_activated(group)
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

        # File-backed tabs don't use buffer persistence.
        editor._buffer_id = None
        editor._buffer_filename = None

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))
        editor.zoom_requested.connect(self._on_zoom_requested)

        # Attach a code completer to the opened file's editor.
        self._attach_completer(editor)

        # Inherit current font size and whitespace setting so opened tabs match.
        self._apply_editor_state(editor)

        tab_name = os.path.basename(filepath)
        icon = self._icon_for_language(editor.language)
        self._group_container.add_editor(editor, tab_name, filepath, icon)

        self._settings.add_recent_file(filepath)
        self._build_recent_files_menu()
        self._update_open_editors()
        self._update_language_combo(editor)

    def _save_file(self):
        """
        Save the current file.

        For file-backed tabs, writes to the file on disk.
        For temp buffers, saves content to the session buffers directory
        and clears the modified indicator (no Save As dialog).
        """
        editor = self._current_editor()
        if not editor:
            return
        if editor.file_path:
            self._write_file(editor, editor.file_path)
        else:
            # Temp buffer — persist to the buffers directory.
            self._save_buffer_content(editor)
            editor.document().setModified(False)
            self._show_status("Buffer saved")
        # Always keep the manifest in sync after any save.
        self._save_session_manifest()

    def _save_file_as(self):
        """Save the current file with a new name via file dialog."""
        editor = self._current_editor()
        if not editor:
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save File", "",
            "Python Files (*.py);;MEL Files (*.mel);;Text Files (*.txt);;All Files (*.*)"
        )
        if filepath:
            # If this was a temp buffer, remove its buffer file now
            # that it's becoming a real file on disk.
            if editor._buffer_filename:
                self._session_manager.remove_buffer(editor._buffer_filename)
                editor._buffer_id = None
                editor._buffer_filename = None

            self._write_file(editor, filepath)
            editor.file_path = filepath
            tab_name = os.path.basename(filepath)
            # Update the tab text and internal tracking in the active group.
            group = self._group_container.active_group()
            if group:
                idx = group.index_of_editor(editor)
                if idx >= 0:
                    group.set_tab_text(idx, tab_name)
                    group.update_editor_entry(idx, editor, tab_name, filepath)
            self._settings.add_recent_file(filepath)
            self._update_open_editors()
            self._save_session_manifest()

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

    def _close_tab_in_group(self, group, index):
        """
        Close a tab in a specific group, prompting to save if modified.

        This is the primary close handler, connected to the container's
        ``tab_close_requested`` signal.

        :param EditorGroup group: The group containing the tab.
        :param int index: Tab index to close.
        """
        editors = group.editors()
        if index < 0 or index >= len(editors):
            return
        editor, name, path = editors[index]
        if editor.document().isModified():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "'{}' has unsaved changes. Save before closing?".format(name),
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Save:
                group.set_current_index(index)
                self._save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        # Clean up the buffer file if this was a temp buffer.
        if editor._buffer_filename:
            self._session_manager.remove_buffer(editor._buffer_filename)

        if path:
            self._closed_files.append(path)

        group.remove_editor(index)
        self._update_open_editors()

        # Keep manifest in sync after closing a tab.
        self._save_session_manifest()

        # If the active group is now empty and it's the only group,
        # create a fresh buffer so the UI is never blank.
        active = self._group_container.active_group()
        if active and active.count() == 0 and self._group_container.group_count() == 1:
            self._new_buffer()

    def _close_current_tab(self):
        """Close the current tab in the active group."""
        group = self._group_container.active_group()
        if group:
            self._close_tab_in_group(group, group.current_index())

    def _on_active_editor_changed(self, editor):
        """
        Handle active editor changes (tab switch or group switch).

        :param object editor: The newly active editor.
        """
        if editor:
            self._update_outline(editor)
            self._update_language_combo(editor)
            self._update_cursor_pos(
                editor.textCursor().blockNumber() + 1,
                editor.textCursor().columnNumber() + 1
            )

    def _on_editor_modified(self, editor, modified):
        """Handle editor modification state changes."""
        # Find the editor across all groups and update its tab text.
        for group in self._group_container.groups():
            idx = group.index_of_editor(editor)
            if idx >= 0:
                editors = group.editors()
                _, name, _ = editors[idx]
                display = "* {}".format(name) if modified else name
                group.set_tab_text(idx, display)
                break
        self._update_open_editors()

    def _update_open_editors(self):
        """Update the sidebar's open editors panel."""
        groups = self._group_container.groups()
        # When there are multiple groups, show grouped data with headers.
        if len(groups) > 1:
            groups_data = []
            for gi, group in enumerate(groups):
                group_tabs = []
                for editor, name, path in group.editors():
                    group_tabs.append({
                        "name": name,
                        "path": path,
                        "modified": editor.document().isModified(),
                        "language": editor.language,
                    })
                groups_data.append(group_tabs)
            self._sidebar.open_editors_panel.update_editors_grouped(groups_data)
        else:
            # Single group — flat list, no headers.
            tabs = []
            for editor, name, path in self._group_container.all_editors():
                tabs.append({
                    "name": name,
                    "path": path,
                    "modified": editor.document().isModified(),
                    "language": editor.language,
                })
            self._sidebar.open_editors_panel.update_editors(tabs)

    def _icon_for_language(self, language):
        """
        Return the appropriate tab icon for a language identifier.

        :param str language: Language string (python, mel, text).
        :return: The matching QIcon.
        :rtype: QIcon
        """
        lang = language.lower() if language else ""
        if lang in ("python", "py"):
            return python_logo()
        elif lang in ("mel",):
            return maya_logo()
        else:
            return text_icon()

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
        lang_map = {"python": "Python", "mel": "MEL", "text": "Text"}
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
            # Re-run analysis for the new language (or clear diagnostics
            # if switching away from Python).
            editor._run_analysis()
            self.language_changed.emit(language)
            # Update tab icon and name in the active group.
            group = self._group_container.active_group()
            if group:
                idx = group.index_of_editor(editor)
                if idx >= 0:
                    group.set_tab_icon(idx, self._icon_for_language(language))
                    editors = group.editors()
                    e, name, path = editors[idx]
                    if path is None:
                        new_name = language
                        modified = e.document().isModified()
                        display = "* {}".format(new_name) if modified else new_name
                        group.set_tab_text(idx, display)
                        group.update_editor_entry(idx, e, new_name, path)
                        self._update_open_editors()

    def _update_cursor_pos(self, line, col):
        """Emit cursor position so the host can update its status bar."""
        self.cursor_position_changed.emit(line, col)

    # =========================================================================
    # Buffer Persistence & Session Restore
    # =========================================================================

    def _save_buffer_content(self, editor):
        """
        Save a temp buffer's content to the buffers directory.

        Allocates a buffer ID on first save so we don't create files for
        buffers that are opened but never modified.

        :param MCACodeEditor editor: The editor whose content to persist.
        """
        # Only persist temp buffers (no file_path).
        if editor.file_path:
            return

        # Allocate an ID on first save.
        if editor._buffer_id is None:
            editor._buffer_id = self._session_manager.allocate_buffer_id()

        editor._buffer_filename = self._session_manager.save_buffer(
            editor._buffer_id, editor.toPlainText(), editor.language
        )

    def _save_session_manifest(self):
        """
        Build the recursive layout tree and write the v3 session manifest.

        Called after every tab open/close/save so the manifest stays
        in sync with the editor state. Uses v3 recursive layout format
        that supports nested horizontal/vertical splits.
        """
        # Get the recursive layout tree from the container.
        layout_state = self._group_container.get_layout_state()
        layout_tree = layout_state.get("layout", {})
        active_group_idx = layout_state.get("active_group", 0)

        # Walk the layout tree and fill in tab data for each group node.
        # Groups appear in DFS order matching self._group_container.groups().
        groups = self._group_container.groups()
        group_iter = iter(groups)
        self._fill_layout_tabs(layout_tree, group_iter)

        self._session_manager.save_manifest_v3(layout_tree, active_group_idx)

    def _fill_layout_tabs(self, node, group_iter):
        """
        Recursively fill in tab data for group nodes in the layout tree.

        Each "group" node gets its tabs and active_tab populated from
        the corresponding EditorGroup (consumed from the iterator).

        :param dict node: Layout tree node.
        :param iterator group_iter: Iterator over EditorGroup instances.
        """
        if not node:
            return

        if node.get("type") == "group":
            # Consume the next group from the iterator.
            try:
                group = next(group_iter)
            except StopIteration:
                return

            group_tabs = []
            for editor, name, path in group.editors():
                if path:
                    group_tabs.append({
                        "type": "file",
                        "file_path": path,
                        "language": editor.language,
                        "title": name,
                    })
                else:
                    group_tabs.append({
                        "type": "buffer",
                        "buffer_file": editor._buffer_filename,
                        "language": editor.language,
                        "title": name,
                    })
            node["tabs"] = group_tabs
            node["active_tab"] = group.current_index()

        elif node.get("type") == "splitter":
            for child in node.get("children", []):
                self._fill_layout_tabs(child, group_iter)

    def _restore_session(self):
        """
        Restore tabs from the session manifest saved on last exit.

        Supports v1, v2, and v3 manifest formats (auto-upgrades to v3).
        For file-backed tabs, re-opens the file from disk. For buffer
        tabs, loads content from the buffers directory.

        V3 manifests use a recursive layout tree that supports nested
        horizontal/vertical splits.

        :return: True if at least one tab was restored.
        :rtype: bool
        """
        manifest = self._session_manager.load_manifest()
        if not manifest:
            return False

        # Auto-upgrade v1/v2 to v3 format.
        manifest = self._session_manager.upgrade_manifest(manifest)

        layout_tree = manifest.get("layout")
        if not layout_tree:
            return False

        # Collect all group nodes from the layout tree in DFS order.
        group_nodes = []
        self._collect_group_nodes(layout_tree, group_nodes)
        if not group_nodes:
            return False

        # Rebuild the splitter tree structure in the container.
        # This returns the new groups in DFS order.
        layout_state = {
            "layout": layout_tree,
            "active_group": manifest.get("active_group", 0),
        }
        restored_groups = self._group_container.restore_layout_state(layout_state)

        # Now populate tabs into each group from the matching node data.
        restored_count = 0
        lang_map = {"python": "Python", "mel": "MEL", "text": "Text"}

        for gi, group_node in enumerate(group_nodes):
            if gi >= len(restored_groups):
                break
            group = restored_groups[gi]

            # Block signals during bulk restore.
            group.block_signals(True)

            for tab_info in group_node.get("tabs", []):
                tab_type = tab_info.get("type", "buffer")
                language = tab_info.get("language", "python")
                title = tab_info.get("title", lang_map.get(language, "Python"))

                if tab_type == "file":
                    file_path = tab_info.get("file_path", "")
                    if file_path and os.path.isfile(file_path):
                        # Create editor directly to avoid signal cascade.
                        editor = self._create_editor_for_restore(language)
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                content = f.read()
                            editor.file_path = file_path
                            editor.setPlainText(content)
                            editor.document().setModified(False)
                        except Exception as exc:
                            logger.warning("Session restore: %s", exc)
                            continue
                        icon = self._icon_for_language(language)
                        group.add_editor(editor, title, file_path, icon)
                        self._settings.add_recent_file(file_path)
                        restored_count += 1
                    else:
                        logger.warning("Session restore: file not found: %s",
                                       tab_info.get("file_path", ""))

                elif tab_type == "buffer":
                    buffer_file = tab_info.get("buffer_file")
                    content = ""
                    if buffer_file:
                        loaded = self._session_manager.load_buffer(buffer_file)
                        if loaded is not None:
                            content = loaded

                    editor = self._create_editor_for_restore(language)
                    if content:
                        editor.setPlainText(content)
                    editor.document().setModified(False)

                    # Restore buffer tracking.
                    if buffer_file:
                        try:
                            basename = os.path.splitext(buffer_file)[0]
                            editor._buffer_id = int(basename.split("_")[1])
                        except (IndexError, ValueError):
                            editor._buffer_id = self._session_manager.allocate_buffer_id()
                        editor._buffer_filename = buffer_file

                    icon = self._icon_for_language(language)
                    group.add_editor(editor, title, None, icon)
                    restored_count += 1

            # Unblock signals and set active tab within this group.
            group.block_signals(False)
            active_tab = group_node.get("active_tab", 0)
            if 0 <= active_tab < group.count():
                group.set_current_index(active_tab)

        # Single UI sync now that all tabs are in place.
        self._update_open_editors()
        editor = self._current_editor()
        if editor:
            self._update_language_combo(editor)

        total_groups = len(group_nodes)
        logger.info("Session restored: %d tab(s) in %d group(s)",
                     restored_count, total_groups)
        return restored_count > 0

    def _collect_group_nodes(self, node, result):
        """
        Recursively collect all group nodes from a layout tree in DFS order.

        :param dict node: Layout tree node.
        :param list result: Accumulator list for group node dicts.
        """
        if not node:
            return
        if node.get("type") == "group":
            result.append(node)
        elif node.get("type") == "splitter":
            for child in node.get("children", []):
                self._collect_group_nodes(child, result)

    def _create_editor_for_restore(self, language):
        """
        Create a bare editor for session restore (no signal cascade).

        :param str language: Language identifier.
        :return: Configured editor widget.
        :rtype: MCACodeEditor
        """
        editor = MCACodeEditor()
        editor._buffer_id = None
        editor._buffer_filename = None
        editor.set_language(language)

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(
            lambda mod, e=editor: self._on_editor_modified(e, mod)
        )
        editor.zoom_requested.connect(self._on_zoom_requested)
        self._attach_completer(editor)
        self._apply_editor_state(editor)

        return editor

    # =========================================================================
    # Tab Bar Events (double-click, right-click context menu)
    # =========================================================================

    def _show_new_tab_dialog(self):
        """
        Show the New Tab language-picker dialog and create a buffer
        with the chosen language.
        """
        dialog = NewTabDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            language = dialog.get_language()
            if language == "python":
                self._new_python_buffer()
            elif language == "mel":
                self._new_mel_buffer()
            elif language == "text":
                self._new_text_buffer()

    # =========================================================================
    # Execution
    # =========================================================================

    def _save_on_execute(self, editor):
        """
        Auto-save the current tab on execute.

        File-backed tabs are written to disk; temp buffers are persisted
        to the session buffers directory. The modified flag is cleared
        so the tab title drops the '*' indicator.

        :param MCACodeEditor editor: The editor to save.
        """
        if editor.file_path:
            self._write_file(editor, editor.file_path)
        else:
            self._save_buffer_content(editor)
        editor.document().setModified(False)

    def _execute_all(self):
        """Execute the entire script."""
        editor = self._current_editor()
        if not editor:
            return
        code = editor.get_all_text()
        if not code.strip():
            return
        # Always save before executing so content is never lost.
        self._save_on_execute(editor)
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
        # Always save before executing so content is never lost.
        self._save_on_execute(editor)
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
        # Always save before executing so content is never lost.
        self._save_on_execute(editor)
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

        Runs the process scan in a background thread so ``tasklist``
        (which can take 3-5 seconds on Windows) doesn't freeze the UI.

        Skips detection if we already have an active, connected adapter
        (e.g., InternalMayaAdapter when running inside Maya).
        """
        # No need to scan processes if we're already connected to a DCC.
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            return

        # Run detection off the main thread. Results are delivered via
        # a callback that posts a QTimer.singleShot(0, ...) to marshal
        # the UI update back onto the main thread.
        self._adapter_manager.detect_running_dccs(
            callback=self._on_dccs_detected
        )

    def _on_dccs_detected(self, detected):
        """
        Handle DCC detection results from the background thread.

        Uses QTimer.singleShot(0) to marshal the UI update back onto
        the main thread (Qt widgets must only be touched from the
        thread that created them).

        :param list detected: List of detected DCC info dicts.
        """
        if detected:
            # Marshal onto the main thread via a zero-delay timer.
            QTimer.singleShot(0, lambda: self._show_detected_dccs(detected))

    def _show_detected_dccs(self, detected):
        """
        Display detected DCCs in the output window and status bar.

        Must be called on the main thread.

        :param list detected: List of detected DCC info dicts.
        """
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
        group = self._group_container.active_group()
        if group:
            idx = group.index_of_editor(editor)
            if idx >= 0:
                group.set_tab_text(idx, "MEL")
                group.set_tab_icon(idx, self._icon_for_language("mel"))
                group.update_editor_entry(idx, editor, "MEL", None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _new_python_buffer(self):
        """Create a new Python buffer."""
        editor = self._new_buffer()
        editor.set_language("python")
        group = self._group_container.active_group()
        if group:
            idx = group.index_of_editor(editor)
            if idx >= 0:
                group.set_tab_text(idx, "Python")
                group.set_tab_icon(idx, self._icon_for_language("python"))
                group.update_editor_entry(idx, editor, "Python", None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _new_text_buffer(self):
        """Create a new plain text buffer."""
        editor = self._new_buffer()
        editor.set_language("text")
        group = self._group_container.active_group()
        if group:
            idx = group.index_of_editor(editor)
            if idx >= 0:
                group.set_tab_text(idx, "Text")
                group.set_tab_icon(idx, self._icon_for_language("text"))
                group.update_editor_entry(idx, editor, "Text", None)
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
        for editor, name, path in self._group_container.all_editors():
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
                # Update tab text and tracking in the active group.
                group = self._group_container.active_group()
                if group:
                    idx = group.index_of_editor(editor)
                    if idx >= 0:
                        group.set_tab_text(idx, new_name)
                        group.update_editor_entry(idx, editor, new_name, new_path)
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

    def _unlock_file(self):
        """Toggle the current editor out of read-only mode so it can be edited."""
        editor = self._current_editor()
        if not editor:
            self._show_status("No editor open")
            return

        if not editor.isReadOnly():
            self._show_status("File is already editable")
            return

        # Unlock the editor for editing.
        editor.setReadOnly(False)
        self._show_status("File unlocked for editing")
        self._output.write_info("Unlocked: {}".format(
            editor.file_path or "untitled buffer"
        ))

    def _close_all_files(self):
        """Close all tabs in all groups."""
        for group in list(self._group_container.groups()):
            while group.count() > 0:
                self._close_tab_in_group(group, 0)
                # If the last group has 1 tab left, that's the auto-created buffer.
                if (self._group_container.group_count() == 1
                        and group.count() == 1):
                    break

    def _save_state(self):
        """Save all temp buffers and session manifest to disk."""
        all_editors = self._group_container.all_editors()
        for editor, name, path in all_editors:
            if not path:
                self._save_buffer_content(editor)
        self._save_session_manifest()
        self._show_status("State saved ({} tabs)".format(len(all_editors)))

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
        """
        Show the find bar in find-only mode, pre-filled with any selection.

        Routes Ctrl+F to the output search bar if focus is currently
        inside the output window, so each panel has its own search.
        """
        # If focus is inside the output panel, route to its search bar.
        focus_widget = QApplication.focusWidget()
        if focus_widget and self._output.isAncestorOf(focus_widget):
            self._output.toggle_search_bar()
            return

        group = self._group_container.active_group()
        if not group:
            return
        editor = group.current_editor()
        if not editor:
            return
        # Pre-fill with selected text if there's a single-line selection.
        selected = ""
        cursor = editor.textCursor()
        if cursor.hasSelection():
            sel = cursor.selectedText()
            if "\u2029" not in sel:
                selected = sel
        group.show_find(selected)

    def _show_replace(self):
        """Show the find bar in find+replace mode."""
        group = self._group_container.active_group()
        if not group:
            return
        editor = group.current_editor()
        if not editor:
            return
        selected = ""
        cursor = editor.textCursor()
        if cursor.hasSelection():
            sel = cursor.selectedText()
            if "\u2029" not in sel:
                selected = sel
        group.show_replace(selected)

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
        # Push settings to every group.
        for group in self._group_container.groups():
            group.apply_settings(s)
        # Output word wrap.
        output_wrap = s.get("output_word_wrap")
        if hasattr(self._output, "_output"):
            wrap_mode = (
                QPlainTextEdit.LineWrapMode.WidgetWidth if output_wrap
                else QPlainTextEdit.LineWrapMode.NoWrap
            )
            self._output._output.setLineWrapMode(wrap_mode)
        logger.info("Settings applied to running editors")

    # --- View handlers ---

    def _toggle_code_editor(self):
        self._group_container.setVisible(not self._group_container.isVisible())

    def _toggle_word_wrap(self, checked):
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth if checked
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        for editor, name, path in self._group_container.all_editors():
            editor.setLineWrapMode(mode)
        self._settings.set("word_wrap", checked)

    def _toggle_whitespace(self, checked):
        """
        Toggle whitespace rendering on all open editors.

        Shows dots for spaces and arrows for tabs when enabled.

        :param bool checked: Whether whitespace rendering is enabled.
        """
        self._settings.set("show_whitespace", checked)
        # Apply to all open editor tabs.
        for editor, name, path in self._group_container.all_editors():
            editor.set_show_whitespace(checked)
        self._show_status("Whitespace rendering: {}".format("on" if checked else "off"))

    def _apply_editor_state(self, editor):
        """
        Apply the current font size and whitespace setting to a single editor.

        Called when a new tab is created so it inherits the active zoom
        level and whitespace rendering state from the session.

        :param MCACodeEditor editor: The editor to configure.
        """
        # Inherit font size if user has zoomed.
        if self._default_font_size != 12:
            font = editor.font()
            font.setPointSize(self._default_font_size)
            editor.setFont(font)
            editor.setTabStopDistance(
                editor.fontMetrics().horizontalAdvance(" ") * editor._tab_size
            )

        # Inherit whitespace rendering.
        if self._settings.get("show_whitespace", False):
            editor.set_show_whitespace(True)

    def _on_zoom_requested(self, direction):
        """
        Handle Ctrl+scroll wheel zoom from any editor tab.

        Applies universally across all tabs.

        :param int direction: +1 to zoom in, -1 to zoom out.
        """
        if direction > 0:
            self._increase_font_size()
        elif direction < 0:
            self._decrease_font_size()

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

    def _apply_font_size(self, notify=True):
        """
        Apply the current font size to all editors and persist it.

        :param bool notify: If True, show a status bar message and save
            to settings. Pass False during startup restore to avoid
            unnecessary status messages and redundant writes.
        """
        for editor, name, path in self._group_container.all_editors():
            font = editor.font()
            font.setPointSize(self._default_font_size)
            editor.setFont(font)
            editor.setTabStopDistance(
                editor.fontMetrics().horizontalAdvance(" ") * editor._tab_size
            )
        if notify:
            # Save immediately so the zoom level survives a crash or force-close.
            self._settings.set("font_size", self._default_font_size)
            self._settings.sync()
            self._show_status("Font size: {}pt".format(self._default_font_size))

    # --- Go handlers ---

    def _next_editor(self):
        """Cycle to the next editor within the active group."""
        group = self._group_container.active_group()
        if group and group.count() > 1:
            idx = (group.current_index() + 1) % group.count()
            group.set_current_index(idx)

    def _prev_editor(self):
        """Cycle to the previous editor within the active group."""
        group = self._group_container.active_group()
        if group and group.count() > 1:
            idx = (group.current_index() - 1) % group.count()
            group.set_current_index(idx)

    def _go_to_file(self):
        """
        Open the Go to File popup (Ctrl+P).

        Scans workspace folders from the sidebar for files, then presents
        a fuzzy-filtered list. Selecting a file opens it in the editor.
        """
        # Collect workspace folders from the sidebar's workspace panel.
        folders = []
        if hasattr(self, "_sidebar") and self._sidebar:
            panel = getattr(self._sidebar, "workspace_panel", None)
            if panel:
                folders = panel.get_workspace_folders()

        if not folders:
            self._show_status("No workspace folders — add one first")
            return

        # Show the popup; on confirm it calls _open_file_path.
        popup = GoToFilePopup(self, folders, self._open_file_path)
        popup.exec()

    def _go_to_symbol(self):
        """
        Open the Go to Symbol popup (Ctrl+Shift+O).

        Reads the code outline from the current editor and presents a
        fuzzy-filtered list of classes, functions, and methods.
        """
        editor = self._current_editor()
        if not editor:
            self._show_status("No active editor")
            return

        # Get the outline from the editor's built-in parser.
        outline = editor.get_code_outline()
        if not outline:
            self._show_status("No symbols found in current file")
            return

        # Show the popup; on confirm it calls editor.go_to_line().
        popup = GoToSymbolPopup(self, outline, editor)
        popup.exec()

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

    # --- Split / Group handlers -----------------------------------------------

    def _split_editor_right(self):
        """Split the current tab into a new group on the right."""
        group = self._group_container.active_group()
        if group and group.count() > 0:
            self._group_container.split_right(group, group.current_index())

    def _on_sidebar_editor_selected(self, index):
        """
        Handle a click on an editor entry in the sidebar.

        When there's only one group, ``index`` maps directly to a tab.
        When there are multiple groups, we need to find the right group.

        :param int index: Flat index across all groups.
        """
        # Walk the groups to find which one contains this flat index.
        remaining = index
        for group in self._group_container.groups():
            if remaining < group.count():
                group.set_current_index(remaining)
                self._group_container._on_group_activated(group)
                return
            remaining -= group.count()

    # --- Output handlers ---

    def _set_verbosity(self, level):
        """
        Apply the given output verbosity level.

        Syncs the output header combobox, the Output menu action group,
        and persists the setting.

        :param str level: One of "echo_all", "normal", or "minimal".
        """
        self._verbosity_level = level
        self._settings.set("output_verbosity", level)
        # Keep the output header combobox in sync.
        self._output.set_verbosity(level)
        # Keep the Output menu radio group in sync.
        for act in self._verbosity_group.actions():
            if act.data() == level:
                act.setChecked(True)
                break
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
            "<p style='color: #888;'>Contact: info@mechart.org</p>"
        )

    def _show_about(self):
        QMessageBox.about(
            self, "About MCA Editor",
            "<h3>MCA Editor v0.1.0</h3>"
            "<p>Cross-DCC Script IDE</p>"
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
        for editor, name, path in self._group_container.all_editors():
            if editor.document().isModified():
                return True
        return False

    def save_window_state(self, settings):
        """
        Save splitter sizes, panel visibility, and workspace folders to settings.

        Called by the host window on close so the next launch can
        restore the exact layout.

        :param MCASettings settings: Settings to save to.
        """
        # Splitter positions.
        settings.set("splitter_sizes", self._main_splitter.sizes())
        settings.set("center_splitter_sizes", self._center_splitter.sizes())

        # Panel visibility.
        settings.set("output_visible", self._output.isVisible())
        settings.set("sidebar_visible", self._sidebar.isVisible())
        settings.set("ai_panel_visible", self._ai_panel.isVisible())

        # Persist workspace folders so they're restored on next launch.
        folders = self._sidebar.workspace_panel.get_workspace_folders()
        settings.set("workspace_folders", folders)

        settings.sync()

    def cleanup(self):
        """
        Clean up resources (called by host on close).

        Saves all temp buffer contents, the session manifest, and the
        output panel content so the editor can restore them on next launch.
        """
        # Persist all temp buffers to disk before shutting down.
        for editor, name, path in self._group_container.all_editors():
            if not path:
                self._save_buffer_content(editor)
        self._save_session_manifest()

        # Persist the output panel content so it survives restarts.
        output_text = self._output._output.toPlainText()
        if output_text.strip():
            self._session_manager.save_output(output_text)

        self._adapter_manager.disconnect_all()
        logger.info("MCA Editor panel cleaning up")
