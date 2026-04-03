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

import importlib
import io
import os
import stat
import re
import sys
import logging
import traceback
import webbrowser

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QToolBar, QLabel, QComboBox, QPushButton, QFileDialog,
    QMessageBox, QDialog, QInputDialog, QSize, QPlainTextEdit,
    QApplication, QStackedWidget,
    Qt, QTimer, Signal, QEvent, QMenu,
    QAction, QActionGroup, QKeySequence, QTextCursor,
)

from mca_core import __version__ as _APP_VERSION
from mca_qt.constants import SKIP_DIRS, MAX_WALK_DEPTH
from mca_core.config.settings import MCASettings
from mca_core.config.color_scheme import build_scheme_dict
from mca_core.project import (
    MCAProject, has_project_file, detect_python_paths, create_default_project,
)
from mca_core.session_manager import SessionManager
from mca_qt.widgets.code_editor import MCACodeEditor
from mca_qt.widgets.output_window import OutputWindow
from mca_qt.widgets.terminal_tab_panel import TerminalTabPanel
from mca_qt.widgets.terminal_factory import is_terminal_available
from mca_qt.widgets.tool_stripe import ToolStripe
from mca_qt.widgets.sidebar import MCASidebar
from mca_qt.widgets.settings_dialog import SettingsDialog
from mca_qt.widgets.connection_dialog import ConnectionDialog
from mca_qt.widgets.new_tab_dialog import NewTabDialog
from mca_qt.widgets.completer import CodeCompleter, CompletionProvider
from mca_qt.widgets.find_replace_bar import FindReplaceBar
from mca_qt.widgets.find_in_files import FindInFilesDialog
from mca_qt.widgets.quick_open import GoToFilePopup, GoToSymbolPopup, GoToDeclarationPopup
from mca_qt.widgets.editor_group_container import EditorGroupContainer
from mca_core.adapters import AdapterManager, DCCType, ConnectionState
from mca_core.symbol_index import SymbolIndex, IndexWorker
from mca_qt.icons import python_logo, maya_logo, text_icon, terminal_icon, sidebar_icon, settings_icon

# Module-level logger.
logger = logging.getLogger(__name__)

# Sentinel object used by _auto_reload_module to distinguish "attribute
# not present in __main__" from "attribute is None".
_SENTINEL = object()

# --- Module-level symbol index cache ----------------------------------------
# In Maya, closing the dockable panel destroys the MCAEditorPanel instance
# (cleanup -> _stop_symbol_indexing -> clear).  When the user reopens the
# editor, a brand-new instance is created and would re-scan the entire
# project.  Stashing the finished index here lets the new panel reuse it
# instead of re-indexing from scratch every time.
_cached_symbol_index = None      # SymbolIndex instance (ready state).
_cached_indexed_folders = None   # sorted list of folder paths it covers.


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

    # Signal emitted when the symbol index status changes.
    # Args: (status_text) — e.g. "Indexing 45%", "Indexed 120 files", or ""
    index_status_changed = Signal(str)

    # Signal emitted when the user toggles the activity bar (bottom status bar).
    activity_bar_toggled = Signal()

    def __init__(self, settings, adapter_manager=None, dcc_version=None, parent=None):
        """
        Initialize the editor panel and all UI components.

        :param MCASettings settings: Application settings instance.
        :param AdapterManager adapter_manager: Optional adapter manager.
        :param str dcc_version: Optional DCC version tag (e.g. ``"Maya2024"``)
            for per-version session isolation.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._settings = settings
        self._adapter_manager = adapter_manager or AdapterManager()
        # Track whether the editor is embedded inside a DCC (e.g. Maya).
        # When embedded, the DCC menu and toolbar indicator are hidden
        # since the host already provides direct execution access.
        self._embedded_in_dcc = adapter_manager is not None
        self._active_project = None  # MCAProject instance or None.
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

        # Track panel visibility with instance vars so save_window_state()
        # doesn't rely on isVisible(), which returns False when the parent
        # window is already hidden during close.
        self._sidebar_visible = True
        self._output_visible = True

        # DCC version tag (e.g. "Maya2025") — passed to MCAProject for
        # profile selection, and to SessionManager for per-version storage.
        self._dcc_version = dcc_version

        # Session manager for buffer persistence across restarts.
        # When embedded in a DCC, pass the version tag so session.json and
        # output.log are stored per-version while scripts/ stays shared.
        self._session_manager = SessionManager(dcc_version=dcc_version)

        # Background symbol index for instant Go To Declaration lookups.
        self._symbol_index = None   # SymbolIndex instance (created on project open).
        self._index_worker = None   # IndexWorker thread (daemon, cancelled on close).
        self._index_progress_timer = None  # QTimer that polls worker progress.

        # Debounce timer for re-indexing after filesystem changes (git pull, etc.).
        self._reindex_debounce_timer = None

        # Debounce timer for outline refresh — reparse 500ms after the user
        # stops typing, rather than on every keystroke.
        self._outline_timer = QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.setInterval(500)
        self._outline_timer.timeout.connect(self._refresh_outline)

        # Shared completion provider — one instance used by all editor tabs.
        self._completion_provider = CompletionProvider(
            self._settings, self._adapter_manager
        )

        # Menu-dependent action references (set when build_menus is called).
        self._recent_files_menu = None
        self._recent_projects_menu = None

        # Build UI components.
        self._setup_ui()
        self._setup_toolbar()
        self._setup_connections()

        # Migrate buffer files from legacy buffers/ to scripts/ directory.
        # Must happen before session restore so buffer files are found.
        self._session_manager.migrate_buffers_to_scripts()

        # Restore previous session or create default starter tabs.
        restored = False
        if settings.get("restore_session"):
            restored = self._restore_session()
        if not restored:
            # First launch (or no session to restore) — start with a
            # Python and a MEL buffer so both languages are ready to go.
            self._new_python_buffer()
            self._new_mel_buffer()

        # Apply saved appearance settings (font, color scheme, tab size)
        # to all editors that were just created by session restore.
        # Without this, editors use hardcoded defaults until the user
        # opens Settings and saves — the color scheme from settings
        # must be applied on every startup.
        self._apply_settings_to_editors()

        # Ensure the default workspace (scripts + site-packages) exists,
        # and add site-packages to sys.path for user imports.
        self._init_default_workspace()

        # Sidebar always starts visible (the old Simple/Advanced mode toggle
        # is removed — visibility is controlled via the left tool stripe).
        self._sidebar.setVisible(True)
        self._sidebar.set_advanced_mode()
        self._main_splitter.setSizes([240, 800, 0])

        # Override layout defaults with user's last-saved UI state.
        self._restore_ui_state()

        # Splitter setSizes() during __init__ can be overridden when Qt
        # performs the first layout pass on show.  Schedule a deferred
        # re-apply so saved sizes survive the initial layout.
        self._splitter_restore_pending = True

        # Restore the output panel content from the previous session.
        # Skip when embedded in a DCC (e.g. Maya) — the host window
        # loads the DCC's own session history instead.  Loading BOTH
        # caused exponential output duplication across sessions.
        if not self._embedded_in_dcc:
            self._restore_output()

        # Auto-detect running DCCs after a short delay.
        QTimer.singleShot(1000, self._auto_detect_dccs)

        # Auto-open the last project if it has open_on_editor_open enabled.
        # Called synchronously during __init__ (before show()) so the
        # layout rebuild doesn't trigger Qt reflows that collapse splitters.
        self._auto_open_last_project()

        # --- EditorAPI & JSON-RPC Server ------------------------------------
        # Register this panel with the public API singleton so external
        # tools can control the editor programmatically.
        from mca_core.editor_api import register_panel as _register_panel
        _register_panel(self)

        # Start the TCP JSON-RPC server in a daemon thread.
        from mca_core.editor_api_server import start_server, drain_queue
        api_port = self._settings.get("api_port", 7003)
        start_server(port=api_port)

        # A QTimer drains the server's request queue on the main thread
        # every 50ms, executing EditorAPI methods safely.
        self._api_dispatch_timer = QTimer(self)
        self._api_dispatch_timer.setInterval(50)
        self._api_dispatch_timer.timeout.connect(drain_queue)
        self._api_dispatch_timer.start()

        # --- Plugin System ---------------------------------------------------
        # Create plugin objects but don't load yet — plugins need the
        # Plugins menu to exist, which is built by build_menus().
        # Actual loading happens in _init_plugins(), called at the end
        # of build_menus() by the host.
        from mca_core.plugins import PluginManager, MCAPluginAPI
        from mca_core.editor_api import get_api

        self._plugin_api = MCAPluginAPI(get_api())
        self._plugin_api._panel_host = self
        self._plugin_manager = PluginManager()
        self._plugins_menu = None  # Set by _build_plugins_menu()

    # --- Default Workspace Initialization ------------------------------------

    def _init_default_workspace(self):
        """
        Lock the workspace sidebar to the ``scripts/`` directory.

        Creates the default ``mca_preferences/scripts/`` and
        ``mca_preferences/scripts/site-packages/`` directories, adds
        both ``scripts/`` and ``site-packages/`` to ``sys.path`` so
        user scripts and packages can be imported, and locks the
        sidebar tree to show only the ``scripts/`` folder.

        Also configures the Maya adapter with workspace paths so
        scripts can be imported inside Maya as well.
        """
        # Ensure the default dirs exist and site-packages is on sys.path.
        scripts_dir = self._session_manager.ensure_default_workspace()

        # Add scripts/ itself to sys.path so user scripts can import each other.
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            logger.info("Added to sys.path: %s", scripts_dir)

        # Lock the workspace tree to the scripts directory — no user-selectable folders.
        self._sidebar.workspace_panel.set_locked_folder(scripts_dir)

        # Tell the Maya adapter about the workspace paths so it can inject
        # sys.path entries into the Python wrapper sent to Maya.
        maya_adapter = self._adapter_manager.get_adapter(DCCType.MAYA)
        if maya_adapter:
            maya_adapter.set_workspace_paths(
                scripts_dir, self._session_manager.site_packages_dir
            )

    # --- Auto-Open Last Project -----------------------------------------------

    def _auto_open_last_project(self):
        """
        Auto-open the last project if it has ``open_on_editor_open`` enabled.

        Called synchronously during ``__init__`` (before the widget is
        shown) so that ``restore_layout_state()`` inside
        ``_switch_to_manifest()`` runs while Qt is not yet performing
        visible layout recalculations. This avoids the splitter-collapse
        race that occurred when auto-open ran via a deferred timer.

        Only opens if:
            1. A last_project_path is stored in settings
            2. The path and its .mca-project file exist on disk
            3. The project's open_on_editor_open flag is True
        """
        last_path = self._settings.get("last_project_path", "")
        if not last_path or not os.path.isdir(last_path):
            return

        # Check that the .mca-project file exists before loading.
        if not has_project_file(last_path):
            return

        logger.info("Auto-opening last project: %s", last_path)
        self._open_project(last_path)

        # _open_project → _switch_to_manifest → restore_layout_state tears
        # down and rebuilds editor groups inside the splitters, which resets
        # all splitter sizes to 0.  Re-apply saved sizes so sidebar, output,
        # and other panels keep their user-configured dimensions.
        self._restore_splitter_sizes()

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
        """Build the main UI layout with splitters, panels, and tool stripes."""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Left tool stripe (thin vertical button bar) ---
        self._left_stripe = ToolStripe()
        self._left_stripe.add_button("sidebar", sidebar_icon(), "Toggle Sidebar")
        self._left_stripe.add_button("terminal", terminal_icon(), "Terminal (Bottom)", bottom=True)
        self._left_stripe.add_button("settings", settings_icon(), "Settings", bottom=True)
        self._left_stripe.button_clicked.connect(self._on_left_stripe_clicked)
        main_layout.addWidget(self._left_stripe)

        # Main horizontal splitter: sidebar | editor+output | right panel.
        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._main_splitter)

        # --- Sidebar (left panel) ---
        self._sidebar = MCASidebar()
        self._sidebar.setMinimumWidth(180)
        self._sidebar.setMaximumWidth(400)
        self._main_splitter.addWidget(self._sidebar)

        # --- Center: toolbar + output + editor tabs + bottom terminal ---
        center_widget = QWidget()
        self._center_layout = QVBoxLayout(center_widget)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.setSpacing(0)

        # Vertical splitter for output, editor tabs, and bottom terminal.
        self._center_splitter = QSplitter(Qt.Orientation.Vertical)

        # Output window (top panel, like Charcoal Editor 2 layout).
        self._output = OutputWindow()
        self._center_splitter.addWidget(self._output)

        # Editor group container — holds one or more editor groups
        # (each group is a QTabWidget with find bar and tab nav buttons).
        self._group_container = EditorGroupContainer()
        self._group_container.active_editor_changed.connect(self._on_active_editor_changed)
        self._group_container.editors_changed.connect(self._update_open_editors)
        self._group_container.tab_close_requested.connect(self._close_tab_in_group)
        self._group_container.rename_requested.connect(self._rename_tab_in_group)
        self._group_container.new_tab_requested.connect(self._show_new_tab_dialog)
        self._center_splitter.addWidget(self._group_container)

        # Bottom terminal tab panel (hidden by default).
        # Uses TerminalTabPanel which manages multiple terminal tabs
        # internally via the terminal factory.
        terminal_shell = self._settings.get("terminal_shell", "")
        terminal_font = self._settings.get("terminal_font_size", 12)
        self._terminal_available = is_terminal_available()
        self._bottom_terminal_panel = TerminalTabPanel(
            shell=terminal_shell,
            cwd=self._session_manager.scripts_dir,
            font_size=terminal_font,
            parent=self,
        )
        self._bottom_terminal_panel.setVisible(False)
        self._bottom_terminal_panel.all_terminals_closed.connect(self._on_bottom_terminals_closed)
        self._center_splitter.addWidget(self._bottom_terminal_panel)

        if not self._terminal_available:
            logger.info("Terminal unavailable — menu entries will be disabled")

        # Minimum heights so panels never collapse to invisible.
        # 20px is enough to show a title bar / resize handle so the user
        # can always tell the panel exists and drag it back open.
        self._output.setMinimumHeight(20)
        self._group_container.setMinimumHeight(20)
        self._bottom_terminal_panel.setMinimumHeight(20)

        # Disable collapsing on all center splitter children so Qt
        # respects the minimum heights instead of snapping to zero.
        for i in range(self._center_splitter.count()):
            self._center_splitter.setCollapsible(i, False)

        # Default split: 30% output (top), 70% editor (bottom), 0 terminal.
        self._center_splitter.setSizes([250, 600, 0])

        self._center_layout.addWidget(self._center_splitter)
        self._main_splitter.addWidget(center_widget)

        # --- Right panel stack (QStackedWidget holding terminal + plugin panels) ---
        # The right tool stripe buttons select which widget is visible.
        # Index 0 is always the terminal panel; plugin panels are added
        # dynamically via _register_plugin_panel().
        self._right_panel_stack = QStackedWidget()
        self._right_panel_stack.setMinimumWidth(250)

        # Terminal is the first (default) widget in the stack.
        self._right_terminal_panel = TerminalTabPanel(
            shell=terminal_shell,
            cwd=self._session_manager.scripts_dir,
            font_size=terminal_font,
            parent=self,
        )
        self._right_terminal_panel.all_terminals_closed.connect(self._on_right_terminals_closed)
        self._right_panel_stack.addWidget(self._right_terminal_panel)

        # Track registered plugin panels: panel_id -> {widget, index, title}.
        self._plugin_panels = {}

        # Keep references to plugin submenus so PySide6 doesn't GC them.
        # Without this, QMenu objects returned by addMenu() get deleted
        # between calls, causing "Internal C++ object already deleted".
        self._plugin_submenus = {}  # menu_path -> QMenu

        # Right panel starts hidden.
        self._right_panel_stack.setVisible(False)
        self._main_splitter.addWidget(self._right_panel_stack)

        # Minimum widths so panels never collapse to invisible.
        center_widget.setMinimumWidth(20)

        # Disable collapsing on all main splitter children so Qt
        # respects the minimum sizes instead of snapping to zero.
        for i in range(self._main_splitter.count()):
            self._main_splitter.setCollapsible(i, False)

        # Default: sidebar visible, right panel hidden.
        self._main_splitter.setSizes([240, 800, 0])

        # --- Right tool stripe (thin vertical button bar) ---
        self._right_stripe = ToolStripe()
        self._right_stripe.add_button("terminal", terminal_icon(), "Terminal (Right)")
        self._right_stripe.button_clicked.connect(self._on_right_stripe_clicked)
        main_layout.addWidget(self._right_stripe)

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

        # Spacer to push project button to the right.
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        self._toolbar.addWidget(spacer)

        # --- Project button (replaces old mode toggle) ---
        self._project_button = QPushButton("No Project")
        self._project_button.setToolTip("Project menu")
        self._project_button.setStyleSheet("""
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
        self._project_button.clicked.connect(self._show_project_menu)
        self._toolbar.addWidget(self._project_button)

        # --- Project action buttons (visible only when project active) ---
        # Explicitly construct QAction with parent=self so the C++ lifetime
        # is tied to the panel, not the toolbar.  toolbar.addAction("text")
        # returns a weakly-owned wrapper that PySide6 can GC prematurely.
        self._load_action = QAction("Load", self)
        self._load_action.setToolTip("Force-run startup scripts (ignores 'load immediately' flag)")
        self._load_action.triggered.connect(self._on_load_project)
        self._load_action.setVisible(False)
        self._toolbar.addAction(self._load_action)

        self._reload_scripts_action = QAction("Reload Scripts", self)
        self._reload_scripts_action.setToolTip(
            "Re-import all open Python modules in Maya (use after external edits)")
        self._reload_scripts_action.triggered.connect(self._on_reload_scripts)
        self._reload_scripts_action.setVisible(False)
        self._toolbar.addAction(self._reload_scripts_action)

        self._reload_action = QAction("Reload Project", self)
        self._reload_action.setToolTip(
            "Close and re-open the project environment (runs shutdown, then startup scripts)")
        self._reload_action.triggered.connect(self._on_reload_project)
        self._reload_action.setVisible(False)
        self._toolbar.addAction(self._reload_action)

        self._shutdown_action = QAction("Shutdown", self)
        self._shutdown_action.setToolTip("Close the current project (runs shutdown script then tears down)")
        self._shutdown_action.triggered.connect(self._close_project)
        self._shutdown_action.setVisible(False)
        self._toolbar.addAction(self._shutdown_action)

    def _setup_connections(self):
        """Wire up signals between all UI components."""
        # Sidebar signals -> editor navigation.
        self._sidebar.file_open_requested.connect(self._open_file_path)
        self._sidebar.file_created.connect(self._open_file_path)
        self._sidebar.file_renamed.connect(self._on_file_renamed)
        self._sidebar.outline_item_clicked.connect(self._goto_outline_item)
        self._sidebar.editor_selected.connect(self._on_sidebar_editor_selected)

        # Sidebar header buttons -> file operations.
        self._sidebar.new_tab_requested.connect(self._show_new_tab_dialog)
        self._sidebar.open_file_requested.connect(self._open_file)

        # Filesystem change -> debounced re-index of symbol index.
        self._sidebar.directory_changed.connect(self._on_workspace_directory_changed)

        # Output window error/warning counts -> forwarding signal for host windows.
        self._output.counts_changed.connect(self.output_counts_changed.emit)

        # Output verbosity combobox -> sync with panel's verbosity setting.
        self._output.verbosity_changed.connect(self._set_verbosity)
        # Restore the saved verbosity level in the output combobox.
        saved_verbosity = self._settings.get("output_verbosity", "normal")
        self._verbosity_level = saved_verbosity
        self._output.set_verbosity(saved_verbosity)

        # Output font size zoom -> persist to settings.
        self._output.font_size_changed.connect(self._on_output_font_size_changed)
        # Restore saved output font size.
        saved_output_size = self._settings.get("output_font_size", 11)
        if saved_output_size != 11:
            self._output.set_font_size(saved_output_size)

        # Adapter manager -> UI status updates.
        self._adapter_manager.set_connection_callback(self._update_dcc_status)

        # Set output/error callbacks on all adapters.
        # Route through filtering methods so verbosity level is respected.
        for adapter in self._adapter_manager.get_all_adapters().values():
            adapter.set_output_callback(self._filtered_output)
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
        self._build_plugins_menu(menubar)
        # Hide the DCC menu when embedded inside a DCC (already connected).
        if not self._embedded_in_dcc:
            self._build_dcc_menu(menubar)
        self._build_help_menu(menubar)

        # Snapshot the hard-coded default shortcuts BEFORE restoring the
        # user's customizations. The settings dialog needs these originals
        # to know which shortcuts were changed (if it snapshots the live
        # actions after restore, the restored customs look like defaults
        # and get silently dropped on the next save).
        self._default_shortcuts = {}
        for name, action in self._action_registry.items():
            self._default_shortcuts[name] = QKeySequence(action.shortcut())

        # Restore any custom keyboard shortcuts the user saved in settings.
        # Must run after all menus are built so _action_registry is populated.
        self._restore_custom_shortcuts()

        # Load plugins now that the Plugins menu exists and they can
        # register panels and menu actions safely.
        self._init_plugins()

    def _init_plugins(self):
        """
        Load all enabled plugins.

        Called at the end of ``build_menus()`` so the Plugins menu
        exists and plugins can register menu actions and panels.
        """
        if self._plugin_manager and self._plugin_api:
            self._plugin_manager.load_all(self._plugin_api)
            logger.info("Plugin system initialized (%d plugins loaded)",
                        len(self._plugin_manager._loaded_plugins))

    def _restore_custom_shortcuts(self):
        """
        Apply user-customized keyboard shortcuts from settings.

        Reads the ``custom_shortcuts`` dict from settings and overrides
        the hard-coded defaults for any registered action whose name
        matches.  An empty string value means the user explicitly
        removed the shortcut.
        """
        custom = self._settings.get("custom_shortcuts", {})
        if not custom or not isinstance(custom, dict):
            return

        for name, seq_str in custom.items():
            action = self._action_registry.get(name)
            if action:
                action.setShortcut(QKeySequence(seq_str) if seq_str else QKeySequence())
                logger.debug("Restored custom shortcut: '%s' -> '%s'", name, seq_str)

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
                            shortcut="Ctrl+N", callback=self._show_new_tab_dialog)
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

        # --- Project actions ---
        self._create_action(file_menu, "Open Project...",
                            callback=self._open_project_dialog)
        self._recent_projects_menu = file_menu.addMenu("Recent Projects")
        self._build_recent_projects_menu()

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
                            shortcut="Ctrl+Shift+R", callback=self._replace_in_files)

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
        self._create_action(view_menu, "Open Terminal at Bottom", name="Open Terminal at Bottom",
                            shortcut="Ctrl+`", callback=self._open_terminal_bottom)
        self._create_action(view_menu, "Open Terminal at Right", name="Open Terminal at Right",
                            callback=self._open_terminal_right)
        self._toggle_sidebar_action = self._create_action(
            view_menu, "Toggle Side Bar", name="Toggle Side Bar",
            shortcut="Ctrl+Shift+B", callback=self._toggle_sidebar)
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

        # (Simple/Advanced mode toggle removed — sidebar visibility is
        # controlled by the left tool stripe button.)


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

        go_menu.addSeparator()

        self._create_action(go_menu, "Go to Declaration", name="Go to Declaration",
                            shortcut="Ctrl+B", callback=self._go_to_declaration)

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

    def _build_plugins_menu(self, menubar):
        """
        Build the Plugins menu.

        Contains a "Plugin Settings..." action and a separator.
        Plugin-registered actions are appended below the separator
        via ``_register_plugin_menu_action()``.
        """
        menu = menubar.addMenu("Pl&ugins")
        self._plugins_menu = menu

        # "Plugin Settings..." opens the plugin management dialog.
        self._create_action(menu, "Plugin Settings...",
                            callback=self._show_plugin_settings)
        menu.addSeparator()

    def _show_plugin_settings(self):
        """Open the Plugin Settings dialog."""
        from mca_qt.widgets.plugin_settings_dialog import PluginSettingsDialog
        dlg = PluginSettingsDialog(self._plugin_manager, self._settings, parent=self)
        dlg.exec()

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

        # --- Bug report / feedback ---
        self._create_action(help_menu, "Report a Bug...",
                            callback=self._show_feedback_bug)
        self._create_action(help_menu, "Send Feedback...",
                            callback=self._show_feedback)

        help_menu.addSeparator()

        # --- About / licensing ---
        self._create_action(help_menu, "Licensing...",
                            callback=self._show_licensing)
        self._create_action(help_menu, "About MCA Editor",
                            callback=self._show_about)

    # =========================================================================
    # Project System
    # =========================================================================

    def _show_project_menu(self):
        """
        Show the project dropdown menu under the project button.

        Contains "Open Project...", "Recent Projects" submenu, and
        "Close Project" (enabled only when a project is active).
        """
        menu = QMenu(self)

        menu.addAction("Open Project...", self._open_project_dialog)

        # Recent Projects submenu.
        recent_sub = menu.addMenu("Recent Projects")
        self._populate_recent_projects_submenu(recent_sub)

        menu.addSeparator()

        # Refresh re-reads the .mca-project file and re-injects paths.
        refresh_action = menu.addAction("Refresh Project", self._on_refresh_project)
        refresh_action.setEnabled(self._active_project is not None)

        settings_action = menu.addAction("Project Settings...", self._show_project_settings)
        settings_action.setEnabled(self._active_project is not None)

        close_action = menu.addAction("Close Project", self._close_project)
        close_action.setEnabled(self._active_project is not None)

        # Show the menu below the project button.
        menu.exec(self._project_button.mapToGlobal(
            self._project_button.rect().bottomLeft()
        ))

    def _open_project_dialog(self):
        """Open a folder picker and then open the selected folder as a project."""
        folder = QFileDialog.getExistingDirectory(self, "Open Project Folder")
        if folder:
            self._open_project(folder)

    def _open_project(self, folder_path):
        """
        Open a folder as a project.

        If a ``.mca-project`` file already exists, loads it. Otherwise
        shows the creation dialog so the user can configure the project.
        Saves the current context's tabs before switching, then restores
        the project's saved tabs (or creates default buffers).

        :param str folder_path: Absolute path to the project root.
        """
        # Guard: don't re-initialize the same project that's already open.
        if self._active_project:
            if os.path.normpath(self._active_project.project_root) == os.path.normpath(folder_path):
                self._output.write_info("Project '{}' is already open.".format(
                    self._active_project.name))
                return

        # Close any existing project first (saves its tabs, restores default).
        if self._active_project:
            self._close_project()

        if has_project_file(folder_path):
            # Load the existing project file, selecting the DCC-specific profile.
            project = MCAProject(folder_path, dcc_tag=self._dcc_version)
        else:
            # Show creation dialog for the user to confirm name and paths.
            from mca_qt.widgets.create_project_dialog import CreateProjectDialog
            detected = detect_python_paths(folder_path)
            dialog = CreateProjectDialog(folder_path, detected, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            name, selected_paths = dialog.result()
            project = create_default_project(
                folder_path, name, selected_paths, dcc_tag=self._dcc_version
            )

        # Validate the project.
        warnings = project.validate()
        for w in warnings:
            self._output.write_warning("Project: {}".format(w))

        # Save the current (default) context's tabs before switching.
        self._save_context_session()

        # Store and apply project mode (workspace tree, paths, env vars).
        self._active_project = project
        self._apply_project_mode()

        # Load the project's saved tabs (or create a fresh buffer).
        manifest = self._session_manager.load_manifest_from(
            project.session_file_path
        )
        self._switch_to_manifest(manifest)

        # Persist to settings.
        self._settings.add_recent_project(folder_path)
        self._settings.set_last_project_path(folder_path)

        self._output.write_info("Opened project: {}".format(project.name))

    def _close_project(self):
        """
        Close the active project and return to the default workspace.

        Runs the shutdown script/code, removes project paths from
        sys.path, re-locks the workspace tree to the scripts/ directory,
        hides the project action buttons, and resets the project button.

        Wrapped in try/except because an uncaught exception here tears
        down the entire Maya workspace control (Shiboken destroys the
        widget tree on unhandled Python errors in signal dispatch).
        """
        if not self._active_project:
            return

        project_name = self._active_project.name

        try:
            # Stop background indexing but keep the finished index and
            # folder list so reopening the same project skips re-indexing.
            self._stop_symbol_indexing(clear_index=False)

            # Save the project's tabs before tearing down.
            self._save_context_session()

            # Persist the workspace tree state (expanded folders, selection) for
            # this project so it can be restored when the project is reopened.
            self._sidebar.workspace_panel.save_tree_state_to_settings(
                self._settings, self._active_project.project_root
            )

            # Run shutdown script/code while paths and env vars are still active.
            self._run_shutdown_script()

            # Remove project env vars and paths.
            self._remove_env_vars()
            self._remove_project_paths()

            # Clear the project reference BEFORE loading default tabs so
            # _save_session_manifest (called inside _switch_to_manifest)
            # routes to the default session.json, not the project file.
            self._active_project = None

            # Re-lock workspace to the default scripts directory.
            scripts_dir = self._session_manager.scripts_dir
            self._sidebar.workspace_panel.set_locked_folder(scripts_dir)

            self._sidebar.set_workspace_title("WORKSPACE")

            self._sidebar.set_excluded_folders(set())

            # Reset UI elements.
            self._project_button.setText("No Project")
            self._load_action.setVisible(False)
            self._reload_scripts_action.setVisible(False)
            self._reload_action.setVisible(False)
            self._shutdown_action.setVisible(False)

            # Reset terminal cwd back to scripts directory.
            self._bottom_terminal_panel._cwd = scripts_dir
            self._right_terminal_panel._cwd = scripts_dir

            # Restore the default workspace tabs.
            default_manifest = self._session_manager.load_manifest()
            self._switch_to_manifest(default_manifest)

            # Clear last project path so it doesn't auto-reopen.
            self._settings.set_last_project_path("")

            # Emit signal for host windows (empty string = no project).
            self.mode_changed.emit("")

            self._output.write_info("Closed project: {}".format(project_name))

        except Exception as exc:
            logger.error("Error during project close: %s", exc, exc_info=True)
            # Ensure the project reference is cleared even on error so
            # the editor doesn't stay in a half-closed state.
            self._active_project = None

    def _apply_project_mode(self):
        """
        Apply the active project's settings to the UI.

        Unlocks the workspace tree to the project root, sets excluded
        folders, updates the header and button text, shows project toolbar
        buttons, injects paths, and emits the mode_changed signal.
        """
        project = self._active_project
        if not project:
            return

        # Set the project root as the primary workspace folder.
        # Use _set_locked_folder_no_refresh to avoid rebuilding the tree
        # three times — we do a single _refresh_tree at the end after
        # all state (folders, excluded, expanded paths) is configured.
        wp = self._sidebar.workspace_panel
        wp._set_locked_folder_no_refresh(project.project_root)

        # Update header to show project name.
        self._sidebar.set_workspace_title("PROJECT: {}".format(project.name))

        # Set excluded folders (without triggering a tree rebuild).
        wp._excluded_folders = set(project.excluded_folders)

        # Restore saved workspace folders (user-added extras beyond
        # project root), expanded paths, and selected item.
        wp.restore_tree_state_from_settings(
            self._settings, project.project_root
        )

        # Single tree rebuild with all state configured.
        wp._refresh_tree()
        wp._update_empty_state()

        # Update toolbar button and show project action buttons.
        self._project_button.setText(project.name)
        self._load_action.setVisible(True)
        self._reload_scripts_action.setVisible(True)
        self._reload_action.setVisible(True)
        self._shutdown_action.setVisible(True)

        # Inject project paths into adapters and local sys.path.
        self._inject_project_paths()

        # Apply environment variables to os.environ.
        self._apply_env_vars()

        # Set terminal cwd to project root.
        self._bottom_terminal_panel._cwd = project.project_root
        self._right_terminal_panel._cwd = project.project_root

        # Emit signal for host windows (project name for title bar).
        self.mode_changed.emit(project.name)

        # Start background symbol indexing for Go To Declaration.
        self._start_symbol_indexing()

        # Decide whether to run startup scripts. Skip if the user
        # explicitly wants immediate loading, or if the project's
        # environment is already active (avoids double-loading in Maya).
        skip_startup = (
            project.load_immediately
            or self._is_project_already_active(project)
        )
        if skip_startup:
            reason = ("load_immediately" if project.load_immediately
                      else "environment already active")
            self._output.write_info(
                "Project '{}' -- skipping startup ({}).".format(
                    project.name, reason))
        else:
            self._run_startup_script()

    def _inject_project_paths(self):
        """
        Add the active project's resolved Python paths to sys.path
        and tell all adapters about them.
        """
        project = self._active_project
        if not project:
            return

        paths = project.resolved_python_paths

        # Add to local sys.path so the editor's own Python can import.
        for p in reversed(paths):
            if p not in sys.path:
                sys.path.insert(0, p)
                logger.info("Added project path to sys.path: %s", p)

        # Tell adapters so DCC execution also has these paths.
        for adapter in self._adapter_manager.get_all_adapters().values():
            if hasattr(adapter, "set_project_paths"):
                adapter.set_project_paths(paths)

    def _remove_project_paths(self):
        """
        Remove the active project's resolved Python paths from sys.path
        and tell all adapters to clear them.
        """
        project = self._active_project
        if not project:
            return

        paths = project.resolved_python_paths

        # Remove from local sys.path.
        for p in paths:
            while p in sys.path:
                sys.path.remove(p)
                logger.info("Removed project path from sys.path: %s", p)

        # Tell adapters to clear project paths.
        for adapter in self._adapter_manager.get_all_adapters().values():
            if hasattr(adapter, "clear_project_paths"):
                adapter.clear_project_paths()

    def _apply_env_vars(self):
        """
        Set the active project's environment variables in ``os.environ``.

        Stores the original values (or a sentinel for keys that didn't
        exist) so ``_remove_env_vars()`` can restore them on close.
        """
        project = self._active_project
        if not project or not project.env_vars:
            return

        # Track originals for clean removal later.
        self._saved_env_originals = {}
        for key, value in project.env_vars.items():
            # Remember what was there before (None = key didn't exist).
            self._saved_env_originals[key] = os.environ.get(key)
            os.environ[key] = value
            logger.info("Set env var: %s=%s", key, value)

    def _remove_env_vars(self):
        """
        Restore environment variables to their pre-project state.

        Keys that existed before the project was opened are restored to
        their original values. Keys that were newly created by the
        project are removed entirely.
        """
        originals = getattr(self, "_saved_env_originals", {})
        for key, original_value in originals.items():
            if original_value is None:
                # Key didn't exist before — remove it.
                os.environ.pop(key, None)
                logger.info("Removed env var: %s", key)
            else:
                # Restore the original value.
                os.environ[key] = original_value
                logger.info("Restored env var: %s=%s", key, original_value)
        self._saved_env_originals = {}

    def _is_project_already_active(self, project):
        """
        Check whether the project's environment is already set up.

        Returns True if every env var is present with the correct value
        AND every resolved Python path is already in sys.path. This
        prevents double-loading when Maya (or another host) has already
        set up the project's environment before MCA Editor opens.

        :param MCAProject project: The project to check.
        :return: True if the environment is already fully active.
        :rtype: bool
        """
        # Check that every project env var is already set correctly.
        for key, value in project.env_vars.items():
            if os.environ.get(key) != value:
                return False

        # Check that every resolved Python path is already on sys.path.
        for p in project.resolved_python_paths:
            if p not in sys.path:
                return False

        # Both checks passed — environment is already active.
        return True

    def _on_load_project(self):
        """
        Force-run the startup script regardless of the load_immediately
        flag or environment state.

        Called when the user clicks the Load button in the toolbar.
        """
        if not self._active_project:
            return
        self._output.write_info("Running project startup...")
        self._run_startup_script()

    def _on_reload_scripts(self):
        """
        Reload all open Python modules so external edits are picked up.

        Walks every open editor tab and forces a module reload for each
        ``.py`` file, regardless of the project's auto-reload toggle.
        Useful when files have been edited outside the editor (e.g. by
        Claude or another tool) and the user wants Maya to pick up the
        changes without re-saving each file.
        """
        reloaded = 0
        for editor, name, path in self._group_container.all_editors():
            if path and path.endswith(".py"):
                self._auto_reload_module(path, force=True)
                reloaded += 1

        if reloaded:
            self._output.write_info("Reloaded {} module(s)".format(reloaded))
        else:
            self._output.write_info("No open .py files to reload.")

    def _on_refresh_project(self):
        """
        Re-read the ``.mca-project`` file and re-inject paths.

        Called from the MCA dropdown menu.
        """
        if not self._active_project:
            return

        # Remove old env vars and paths first.
        self._remove_env_vars()
        self._remove_project_paths()

        # Reload the project file from disk.
        self._active_project.load()

        # Re-apply everything.
        self._apply_project_mode()

        self._output.write_info("Project refreshed: {}".format(
            self._active_project.name))

    def _run_startup_script(self):
        """
        Execute the project's startup script and/or inline startup code.

        The script file runs first, then the inline code. Both run after
        paths are injected so imports from the project's python_paths are
        available. Execution is routed through the active DCC adapter
        (if connected) or the local Python interpreter, matching the
        normal "Execute" behavior.

        The editor window is protected from external close attempts during
        execution (see ``_run_shutdown_script`` for details).
        """
        project = self._active_project
        if not project:
            return

        # Nothing to run if neither a script file nor inline code is set.
        has_script = bool(project.startup_script)
        has_code = bool(project.startup_code and project.startup_code.strip())
        if not has_script and not has_code:
            return

        # Protect the editor from frameworks that close all "MCA" windows
        # during startup (e.g. MCACloud's startup_init calls restart which
        # calls shutdown → close_all_mca_windows).
        host = self.parent()
        saved_title = None
        if host:
            host._shutdown_script_running = True
            saved_title = host.windowTitle()
            host.setWindowTitle("_mca_editor_startup_guard_")

        adapter = self._adapter_manager.get_active_adapter()

        try:
            # --- Run the script file first (if configured) ---
            if has_script:
                script_path = project.resolved_startup_script
                if not os.path.isfile(script_path):
                    self._output.write_warning(
                        "Startup script not found: {}".format(project.startup_script))
                else:
                    self._output.write_info("Running startup script: {}".format(
                        project.startup_script))
                    try:
                        with open(script_path, "r", encoding="utf-8") as f:
                            file_code = f.read()
                    except OSError as exc:
                        self._output.write_error(
                            "Could not read startup script: {}".format(exc))
                        file_code = None

                    if file_code:
                        if adapter and adapter.is_connected:
                            adapter.execute(file_code, "python")
                        else:
                            self._execute_locally(file_code)

            # --- Run inline startup code (if configured) ---
            if has_code:
                lang = project.startup_language
                self._output.write_info("Running inline startup code ({})...".format(lang))
                if adapter and adapter.is_connected:
                    adapter.execute(project.startup_code, lang)
                else:
                    self._execute_locally(project.startup_code)
        finally:
            # Restore the title and clear the guard flag.
            if host:
                if saved_title is not None:
                    host.setWindowTitle(saved_title)
                host._shutdown_script_running = False

    def _run_shutdown_script(self):
        """
        Execute the project's shutdown script and/or inline shutdown code.

        The script file runs first, then the inline code. Both run while
        paths and env vars are still active so the shutdown code can use
        project imports and environment. Execution is routed through the
        active DCC adapter (if connected) or the local Python interpreter.

        Sets ``_shutdown_script_running`` on the host window so that
        ``dockCloseEventTriggered`` can block external close attempts
        during execution.  Some project frameworks (e.g. MCACloud's
        ``close_all_mca_windows()``) close every window whose title
        contains "MCA", which would destroy the editor mid-shutdown.
        """
        project = self._active_project
        if not project:
            return

        # Nothing to run if neither a script file nor inline code is set.
        has_script = bool(project.shutdown_script)
        has_code = bool(project.shutdown_code and project.shutdown_code.strip())
        if not has_script and not has_code:
            return

        # Protect the editor from being destroyed by user shutdown scripts.
        # Some frameworks (e.g. MCACloud) call close_all_mca_windows() which
        # finds windows by matching "MCA" in the title, then calls .close()
        # and .deleteLater() on each.  To survive this:
        #   1. Set a flag so dockCloseEventTriggered ignores the close.
        #   2. Temporarily change the window title so it doesn't match the
        #      "MCA" filter.  Restored in the finally block.
        host = self.parent()
        saved_title = None
        if host:
            host._shutdown_script_running = True
            saved_title = host.windowTitle()
            host.setWindowTitle("_mca_editor_shutdown_guard_")

        adapter = self._adapter_manager.get_active_adapter()

        try:
            # --- Run the script file first (if configured) ---
            if has_script:
                script_path = project.resolved_shutdown_script
                if not os.path.isfile(script_path):
                    self._output.write_warning(
                        "Shutdown script not found: {}".format(project.shutdown_script))
                else:
                    self._output.write_info("Running shutdown script: {}".format(
                        project.shutdown_script))
                    try:
                        with open(script_path, "r", encoding="utf-8") as f:
                            file_code = f.read()
                    except OSError as exc:
                        self._output.write_error(
                            "Could not read shutdown script: {}".format(exc))
                        file_code = None

                    if file_code:
                        if adapter and adapter.is_connected:
                            adapter.execute(file_code, "python")
                        else:
                            self._execute_locally(file_code)

            # --- Run inline shutdown code (if configured) ---
            if has_code:
                lang = project.shutdown_language
                self._output.write_info("Running inline shutdown code ({})...".format(lang))
                if adapter and adapter.is_connected:
                    adapter.execute(project.shutdown_code, lang)
                else:
                    self._execute_locally(project.shutdown_code)
        finally:
            # Always restore the title and clear the guard flag so
            # normal close works again.
            if host:
                if saved_title is not None:
                    host.setWindowTitle(saved_title)
                host._shutdown_script_running = False

    def _on_reload_project(self):
        """
        Reload the active project's environment without switching tabs.

        Runs the shutdown sequence (script + env teardown + path removal),
        re-reads the .mca-project file from disk, then re-applies paths,
        env vars, and runs the startup sequence.  Unlike close+open, this
        keeps the current editor tabs untouched and always forces startup
        scripts to run (bypasses the ``_is_project_already_active`` check).

        Wrapped in try/except because an uncaught exception during
        reload tears down the Maya workspace control.
        """
        if not self._active_project:
            return

        try:
            project_root = self._active_project.project_root

            # --- Shutdown ---
            self._run_shutdown_script()
            self._remove_env_vars()
            self._remove_project_paths()

            # Re-read the project file from disk so any manual edits are
            # picked up (same as what _on_refresh_project does).
            self._active_project = MCAProject(project_root, dcc_tag=self._dcc_version)

            # --- Startup ---
            self._inject_project_paths()
            self._apply_env_vars()
            self._run_startup_script()

            self._output.write_info("Reloaded project: {}".format(
                self._active_project.name))

        except Exception as exc:
            logger.error("Error during project reload: %s", exc, exc_info=True)

    def _show_project_settings(self):
        """
        Open the Project Settings dialog for the active project.

        On accept, updates the MCAProject, saves the file, and re-applies
        the project mode so changes take effect immediately.
        """
        if not self._active_project:
            return

        try:
            from mca_qt.widgets.project_settings_dialog import ProjectSettingsDialog
        except ImportError:
            # Package root may have fallen off sys.path — re-add and retry.
            import mca_core
            mca_core.ensure_on_path()
            try:
                from mca_qt.widgets.project_settings_dialog import ProjectSettingsDialog
            except ImportError as exc:
                logger.error("Could not import ProjectSettingsDialog: %s", exc)
                self._output.write_error(
                    "Failed to open project settings: {}".format(exc))
                return
        dialog = ProjectSettingsDialog(
            self._active_project, dcc_tag=self._dcc_version,
            settings=self._settings, parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        result = dialog.result()
        if not result:
            return

        # Remove old env vars and paths before applying changes.
        self._remove_env_vars()
        self._remove_project_paths()

        # Apply the user's changes to the project model.
        # Shared settings.
        self._active_project.name = result["name"]
        self._active_project.python_paths = result["python_paths"]
        self._active_project.excluded_folders = result["excluded_folders"]
        self._active_project.open_on_editor_open = result.get("open_on_editor_open", False)
        self._active_project.auto_reload_modules = result.get("auto_reload_modules", True)

        # Profile-specific settings — replace all profiles at once
        # since the dialog allows editing any/all profiles.
        if "profiles" in result:
            self._active_project.set_profiles(result["profiles"])

        # Save the updated .mca-project file.
        self._active_project.save()

        # Re-apply everything (paths, tree, title, etc.).
        self._apply_project_mode()

        self._output.write_info("Project settings saved: {}".format(
            self._active_project.name))

    def _build_recent_projects_menu(self):
        """Rebuild the Recent Projects submenu in the File menu."""
        if not self._recent_projects_menu:
            return
        self._populate_recent_projects_submenu(self._recent_projects_menu)

    def _populate_recent_projects_submenu(self, menu):
        """
        Fill a QMenu with recent project entries.

        :param QMenu menu: The menu to populate.
        """
        try:
            menu.clear()
        except RuntimeError:
            return

        recent = self._settings.get_recent_projects()
        if recent:
            for project_path in recent:
                # Read the project name from the .mca-project file so
                # entries are distinguishable even when folder names match.
                if has_project_file(project_path):
                    display_name = MCAProject(project_path).name
                else:
                    display_name = os.path.basename(project_path)
                act = menu.addAction(display_name)
                act.setToolTip(project_path)
                act.triggered.connect(
                    lambda checked=False, p=project_path: self._open_project(p)
                )
        else:
            empty = menu.addAction("No recent projects")
            empty.setEnabled(False)

    def showEvent(self, event):
        """
        Re-apply saved splitter sizes after the first show.

        Qt's initial layout pass can override ``setSizes()`` calls made
        during ``__init__`` before the widget has a non-zero size.  This
        one-shot re-apply ensures the user's last-saved positions stick.

        :param QShowEvent event: The show event.
        """
        super().showEvent(event)

        if getattr(self, "_splitter_restore_pending", False):
            self._splitter_restore_pending = False
            # Defer slightly so the layout pass fully completes first.
            QTimer.singleShot(0, self._restore_splitter_sizes)

    def _restore_splitter_sizes(self):
        """
        Re-apply saved splitter sizes from settings.

        Called once after the first show event to ensure sizes survive
        Qt's initial layout pass.
        """
        s = self._settings

        saved_main = s.get("splitter_sizes")
        if saved_main:
            try:
                self._main_splitter.setSizes([int(v) for v in saved_main])
            except (TypeError, ValueError):
                pass

        saved_center = s.get("center_splitter_sizes")
        if saved_center:
            try:
                self._center_splitter.setSizes([int(v) for v in saved_center])
            except (TypeError, ValueError):
                pass

        saved_sidebar = s.get("sidebar_splitter_sizes")
        if saved_sidebar:
            try:
                self._sidebar.set_splitter_sizes([int(v) for v in saved_sidebar])
            except (TypeError, ValueError):
                pass

    def _restore_ui_state(self):
        """
        Restore saved UI state from settings, overriding mode defaults.

        Must be called AFTER the initial sidebar setup because it
        resets splitter sizes and panel visibility to defaults. This
        method layers the user's last-saved state on top.
        """
        s = self._settings

        saved_main = s.get("splitter_sizes")
        if saved_main:
            try:
                self._main_splitter.setSizes([int(v) for v in saved_main])
            except (TypeError, ValueError):
                pass

        saved_center = s.get("center_splitter_sizes")
        if saved_center:
            try:
                self._center_splitter.setSizes([int(v) for v in saved_center])
            except (TypeError, ValueError):
                pass

        saved_sidebar = s.get("sidebar_splitter_sizes")
        if saved_sidebar:
            try:
                self._sidebar.set_splitter_sizes([int(v) for v in saved_sidebar])
            except (TypeError, ValueError):
                pass

        sidebar_vis = s.get("sidebar_visible", True)
        self._sidebar.setVisible(sidebar_vis)
        self._sidebar_visible = sidebar_vis
        self._left_stripe.set_button_active("sidebar", sidebar_vis)

        output_vis = s.get("output_visible", True)
        self._output.setVisible(output_vis)
        self._output_visible = output_vis

        legacy_term = s.get("terminal_visible", None)
        if legacy_term is not None:
            if s.get("bottom_terminal_visible", None) is None:
                s.set("bottom_terminal_visible", legacy_term)

        bottom_vis = s.get("bottom_terminal_visible", False)
        if bottom_vis and self._terminal_available:
            self._bottom_terminal_panel.setVisible(True)
            sizes = self._center_splitter.sizes()
            if len(sizes) >= 3 and sizes[2] < 50:
                total = sum(sizes)
                terminal_height = min(200, total // 4)
                sizes[2] = terminal_height
                sizes[1] = max(100, sizes[1] - terminal_height)
                self._center_splitter.setSizes(sizes)
            QTimer.singleShot(500, self._bottom_terminal_panel.ensure_terminal)
            self._left_stripe.set_button_active("terminal", True)

        right_term_vis = s.get("right_terminal_visible", False)
        if right_term_vis:
            # Show the right panel stack and switch to the terminal widget.
            self._right_panel_stack.setVisible(True)
            self._right_panel_stack.setCurrentWidget(self._right_terminal_panel)
            sizes = self._main_splitter.sizes()
            last = len(sizes) - 1
            if sizes[last] == 0:
                total = sum(sizes)
                sizes[last] = 300
                sizes[1] = total - sizes[0] - sizes[last]
                self._main_splitter.setSizes(sizes)
            QTimer.singleShot(500, self._right_terminal_panel.ensure_terminal)
            self._right_stripe.set_button_active("terminal", True)
        else:
            self._right_panel_stack.setVisible(False)

        show_ws = s.get("show_whitespace", False)
        if show_ws:
            self._whitespace_action.setChecked(True)
            for editor, name, path in self._group_container.all_editors():
                editor.set_show_whitespace(True)

        if self._default_font_size != 12:
            self._apply_font_size(notify=False)

        # Restore workspace tree expanded folders from settings and rebuild
        # so the loaded paths take effect.
        project_root = (self._active_project.project_root
                        if self._active_project else None)
        wp = self._sidebar.workspace_panel
        wp.restore_tree_state_from_settings(s, project_root)
        wp._refresh_tree()

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

    def _toggle_sidebar(self):
        """Toggle sidebar visibility and persist the choice."""
        visible = not self._sidebar_visible
        self._sidebar.setVisible(visible)
        self._sidebar_visible = visible
        self._left_stripe.set_button_active("sidebar", visible)
        self._settings.set("sidebar_visible", visible)

    def _toggle_output(self):
        """Toggle output window visibility and persist the choice."""
        visible = not self._output_visible
        self._output.setVisible(visible)
        self._output_visible = visible
        self._settings.set("output_visible", visible)

    def _open_terminal_bottom(self):
        """Add a new terminal tab in the bottom panel (Ctrl+`)."""
        if not self._terminal_available:
            return

        # Show the panel if hidden.
        if not self._bottom_terminal_panel.isVisible():
            self._bottom_terminal_panel.setVisible(True)
            self._settings.set("bottom_terminal_visible", True)
            self._left_stripe.set_button_active("terminal", True)

            # Give the terminal panel space in the center splitter.
            # Restore the last height the user set, or fall back to 1/4 of total.
            sizes = self._center_splitter.sizes()
            if len(sizes) >= 3 and sizes[2] < 50:
                saved_height = self._settings.get("bottom_terminal_height", 0)
                total = sum(sizes)
                terminal_height = int(saved_height) if saved_height else min(200, total // 4)
                terminal_height = min(terminal_height, total // 2)
                sizes[2] = terminal_height
                sizes[1] = max(100, sizes[1] - terminal_height)
                self._center_splitter.setSizes(sizes)

        # Always add a new terminal tab.
        self._bottom_terminal_panel.add_terminal()
        self._bottom_terminal_panel.focus_current()

    def _open_terminal_right(self):
        """Add a new terminal tab in the right panel."""
        if not self._terminal_available:
            return

        # Show the right panel stack and switch to the terminal widget.
        self._show_right_panel(self._right_terminal_panel)
        self._right_stripe.set_button_active("terminal", True)
        self._settings.set("right_terminal_visible", True)

        # Always add a new terminal tab.
        self._right_terminal_panel.add_terminal()
        self._right_terminal_panel.focus_current()

    def _show_right_panel(self, widget):
        """
        Show the right panel stack and switch to a specific widget.

        Expands the splitter if the right panel is currently collapsed.
        Uses the last user-set width so the panel remembers its size
        across open/close toggles.

        :param QWidget widget: The widget to show in the stack.
        """
        # Switch the stack to the requested widget.
        self._right_panel_stack.setCurrentWidget(widget)

        # Show the stack if it's hidden.
        if not self._right_panel_stack.isVisible():
            self._right_panel_stack.setVisible(True)

            # Expand the right panel in the main splitter if needed.
            sizes = self._main_splitter.sizes()
            if sizes[-1] == 0:
                # Restore the last width the user set, or fall back to 300.
                saved_width = self._settings.get("right_panel_width", 300)
                total = sum(sizes)
                sizes[-1] = min(int(saved_width), total // 2)
                sizes[1] = total - sizes[0] - sizes[-1]
                self._main_splitter.setSizes(sizes)

    def _hide_right_panel(self):
        """
        Hide the right panel stack entirely.

        Saves the current width so it can be restored next time the
        panel is shown.  Deactivates all right stripe buttons.
        """
        # Remember the panel width before hiding (hiding sets it to 0).
        sizes = self._main_splitter.sizes()
        if sizes[-1] > 0:
            self._settings.set("right_panel_width", sizes[-1])

        self._right_panel_stack.setVisible(False)
        self._right_stripe.set_button_active("terminal", False)
        self._settings.set("right_terminal_visible", False)
        # Deactivate any plugin panel stripe buttons.
        for panel_id in self._plugin_panels:
            self._right_stripe.set_button_active(panel_id, False)

    # --- Tool Stripe Callbacks -----------------------------------------------

    def _on_left_stripe_clicked(self, name):
        """
        Dispatch left tool stripe button clicks.

        :param str name: The button name that was clicked.
        """
        if name == "sidebar":
            self._toggle_sidebar()
        elif name == "terminal":
            self._open_terminal_bottom()
        elif name == "settings":
            self._show_settings()

    def _on_right_stripe_clicked(self, name):
        """
        Dispatch right tool stripe button clicks.

        Handles the built-in terminal button as well as dynamically
        registered plugin panel buttons.  Clicking an active button
        hides the right panel; clicking an inactive button shows the
        corresponding panel.

        :param str name: The button name that was clicked.
        """
        if name == "terminal":
            # Toggle: if terminal is already showing, hide the right panel.
            if (self._right_panel_stack.isVisible()
                    and self._right_panel_stack.currentWidget() is self._right_terminal_panel):
                self._hide_right_panel()
            else:
                self._open_terminal_right()
            return

        # Check if this is a plugin panel button.
        if name in self._plugin_panels:
            panel_info = self._plugin_panels[name]
            widget = panel_info["widget"]

            # Toggle: if already showing this plugin panel, hide the right panel.
            if (self._right_panel_stack.isVisible()
                    and self._right_panel_stack.currentWidget() is widget):
                self._hide_right_panel()
            else:
                # Deactivate all other right stripe buttons.
                self._right_stripe.set_button_active("terminal", False)
                for pid in self._plugin_panels:
                    self._right_stripe.set_button_active(pid, False)
                # Show the plugin panel.
                self._show_right_panel(widget)
                self._right_stripe.set_button_active(name, True)

    def _on_bottom_terminals_closed(self):
        """Auto-hide the bottom terminal panel when all tabs are closed."""
        # Remember the panel height before hiding (hiding sets it to 0).
        sizes = self._center_splitter.sizes()
        if len(sizes) >= 3 and sizes[2] > 0:
            self._settings.set("bottom_terminal_height", sizes[2])

        self._bottom_terminal_panel.setVisible(False)
        self._settings.set("bottom_terminal_visible", False)
        self._left_stripe.set_button_active("terminal", False)

    def _on_right_terminals_closed(self):
        """Hide the right panel when all terminal tabs are closed."""
        self._right_stripe.set_button_active("terminal", False)
        self._settings.set("right_terminal_visible", False)
        # Only hide the whole stack if the terminal was the visible panel.
        if self._right_panel_stack.currentWidget() is self._right_terminal_panel:
            self._hide_right_panel()

    # =========================================================================
    # Plugin Panel Registration
    # =========================================================================

    def _register_plugin_panel(self, panel_id, title, widget, icon, location):
        """
        Register a plugin widget as a panel in the right-side stack.

        Called by MCAPluginAPI.add_panel().  Adds the widget to the
        QStackedWidget and creates a corresponding tool stripe button.

        :param str panel_id: Unique identifier for this panel.
        :param str title: Display title / tooltip for the stripe button.
        :param QWidget widget: The panel widget to show.
        :param QIcon icon: Optional icon for the stripe button.
        :param str location: Panel location (only "right" supported).
        """
        # Guard against calls before UI is fully built.
        if self._right_panel_stack is None:
            logger.warning("Cannot register panel '%s' — UI not ready", panel_id)
            return

        # Don't register the same panel twice.
        if panel_id in self._plugin_panels:
            logger.warning("Plugin panel '%s' already registered", panel_id)
            return

        # Add widget to the stack.
        index = self._right_panel_stack.addWidget(widget)

        # Create a stripe button for this panel.
        # Use a default plugin icon if none provided.
        if icon is None:
            from mca_qt.icons import plugin_icon
            icon = plugin_icon()
        self._right_stripe.add_button(panel_id, icon, title)

        # Track the registration.
        self._plugin_panels[panel_id] = {
            "widget": widget,
            "index": index,
            "title": title,
        }
        logger.info("Registered plugin panel: %s (index %d)", panel_id, index)

    def _unregister_plugin_panel(self, panel_id):
        """
        Remove a previously registered plugin panel.

        Removes the widget from the stack, removes the stripe button,
        and hides the right panel if the removed panel was active.

        :param str panel_id: The panel identifier to remove.
        """
        panel_info = self._plugin_panels.pop(panel_id, None)
        if panel_info is None:
            logger.warning("Cannot unregister unknown panel: %s", panel_id)
            return

        widget = panel_info["widget"]

        # If this panel is currently visible, hide the right panel.
        if (self._right_panel_stack.isVisible()
                and self._right_panel_stack.currentWidget() is widget):
            self._hide_right_panel()

        # Remove from the stack and stripe.
        self._right_panel_stack.removeWidget(widget)
        widget.setParent(None)
        self._right_stripe.remove_button(panel_id)
        logger.info("Unregistered plugin panel: %s", panel_id)

    def _register_plugin_menu_action(self, menu_path, label, callback, shortcut):
        """
        Register a plugin menu action under the Plugins menu.

        If ``menu_path`` is provided, a submenu with that name is created
        (or reused) under the Plugins menu, and the action is added there.

        Guards against dead C++ objects — Maya's workspace control system
        can destroy QMenu objects when reparenting the editor panel, leaving
        Python references pointing at freed memory.

        :param str menu_path: Submenu name (e.g. "Hello World"), or None/empty
            for a top-level action under Plugins.
        :param str label: Display label for the action.
        :param callable callback: Function to call when activated.
        :param str shortcut: Optional keyboard shortcut string.
        :return: The created QAction, or None.
        :rtype: QAction or None
        """
        if not hasattr(self, "_plugins_menu") or self._plugins_menu is None:
            logger.warning("Plugins menu not available — cannot add '%s'", label)
            return None

        # Verify the C++ backing of _plugins_menu is still alive.
        # Maya's workspace control reparenting can destroy QMenu objects
        # while Python references still exist, causing RuntimeError on access.
        if not self._is_menu_alive(self._plugins_menu):
            logger.warning(
                "Plugins menu C++ object was deleted — rebuilding for '%s'", label
            )
            self._rebuild_plugins_menu()
            if self._plugins_menu is None:
                return None

        # Determine which menu to add the action to.
        target_menu = self._plugins_menu
        if menu_path:
            # Find or create a submenu with this name.
            # Use the _plugin_submenus dict to keep a Python reference
            # alive — PySide6 GC deletes QMenu objects returned by
            # addMenu() if nothing holds a reference.
            if menu_path in self._plugin_submenus:
                # Verify the cached submenu is still alive.
                if self._is_menu_alive(self._plugin_submenus[menu_path]):
                    target_menu = self._plugin_submenus[menu_path]
                else:
                    # Stale reference — recreate the submenu.
                    del self._plugin_submenus[menu_path]
                    target_menu = self._plugins_menu.addMenu(menu_path)
                    self._plugin_submenus[menu_path] = target_menu
            else:
                target_menu = self._plugins_menu.addMenu(menu_path)
                self._plugin_submenus[menu_path] = target_menu

        # Create the action.
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        if callback:
            action.triggered.connect(callback)
        target_menu.addAction(action)
        self.addAction(action)
        return action

    @staticmethod
    def _is_menu_alive(menu):
        """
        Check whether a QMenu's C++ backing object is still alive.

        PySide6 does not invalidate Python references when Qt deletes the
        underlying C++ widget (e.g. during reparenting).  Accessing a dead
        wrapper raises ``RuntimeError``.

        :param QMenu menu: The menu to check.
        :return: True if the C++ object is valid.
        :rtype: bool
        """
        try:
            # Any property access will raise if the C++ object is deleted.
            menu.objectName()
            return True
        except RuntimeError:
            return False

    def _rebuild_plugins_menu(self):
        """
        Rebuild the Plugins menu after its C++ object was destroyed.

        Finds the current menu bar (walking up the widget tree) and
        re-adds the Plugins menu.  Clears stale submenu references.
        """
        # Clear stale submenu references.
        self._plugin_submenus.clear()

        # Walk up the parent chain to find a valid QMenuBar.
        menubar = None
        parent = self.parent()
        while parent is not None:
            # Look for the menubar attribute set by the host window.
            if hasattr(parent, "_menubar"):
                candidate = parent._menubar
                if self._is_menu_alive(candidate):
                    menubar = candidate
                    break
            # Also try QMainWindow's built-in menuBar().
            if hasattr(parent, "menuBar"):
                try:
                    candidate = parent.menuBar()
                    if candidate and self._is_menu_alive(candidate):
                        menubar = candidate
                        break
                except RuntimeError:
                    pass
            parent = parent.parent() if hasattr(parent, "parent") else None

        if menubar is None:
            logger.warning("Cannot rebuild Plugins menu — no valid menu bar found")
            self._plugins_menu = None
            return

        # Create a fresh Plugins menu on the existing menu bar.
        self._plugins_menu = menubar.addMenu("Pl&ugins")
        self._create_action(self._plugins_menu, "Plugin Settings...",
                            callback=self._show_plugin_settings)
        self._plugins_menu.addSeparator()
        logger.info("Rebuilt Plugins menu on recovered menu bar")

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

    def _new_buffer(self, language="python"):
        """
        Create a new buffer file in the active workspace directory.

        When a project is active, the buffer is placed in the project
        root so it's visible in the project tree. Otherwise it goes
        into the default ``scripts/`` directory.

        The file is written to disk immediately so it appears in the
        workspace tree and is searchable by Find in Files / Go to
        Declaration from the moment it's created.

        :param str language: Language for the buffer ('python', 'mel', 'text').
        :return: The newly created editor widget.
        :rtype: MCACodeEditor
        """
        editor = MCACodeEditor()

        # Set language BEFORE saving so the buffer gets the correct
        # filename and extension (e.g. MEL_2.mel instead of Python_2.py).
        editor.set_language(language)

        # Allocate a buffer ID and immediately save an empty file to disk.
        editor._buffer_id = self._session_manager.allocate_buffer_id()
        editor._buffer_filename = self._session_manager.save_buffer(
            editor._buffer_id, "", editor.language
        )

        # Place the buffer in the project root when a project is open,
        # otherwise in the default scripts/ directory.
        if self._active_project:
            target_dir = self._active_project.project_root
        else:
            target_dir = self._session_manager.scripts_dir

        # Build the full on-disk path so this is a file-backed tab.
        filepath = os.path.join(target_dir, editor._buffer_filename)

        # If the target is the project root, copy the empty file there
        # (save_buffer always writes to scripts/).
        if self._active_project:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("")
            except OSError as exc:
                logger.warning("Could not create project buffer: %s", exc)
                # Fall back to scripts/ directory.
                filepath = os.path.join(
                    self._session_manager.scripts_dir, editor._buffer_filename
                )

        editor.file_path = filepath

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))
        editor.zoom_requested.connect(self._on_zoom_requested)
        # Refresh the outline panel after a typing pause.
        editor.document().contentsChanged.connect(self._on_editor_content_changed)

        # Attach a code completer to the new buffer.
        self._attach_completer(editor)

        # Inherit current font size and whitespace setting so new tabs match.
        self._apply_editor_state(editor)

        # Tab name = filename without extension (e.g. "Python_1").
        tab_name = os.path.splitext(editor._buffer_filename)[0]

        icon = self._icon_for_language(editor.language)
        self._group_container.add_editor(editor, tab_name, filepath, icon)

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

        # Detect language from file extension so .mel files get MEL
        # highlighting and Python analysis doesn't run on them.
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".mel":
            editor.set_language("mel")
        elif ext == ".py":
            editor.set_language("python")
        else:
            editor.set_language("text")

        # File-backed tabs don't use buffer persistence.
        editor._buffer_id = None
        editor._buffer_filename = None

        editor.execute_requested.connect(self._execute_all)
        editor.execute_selected_requested.connect(self._execute_selected)
        editor.execute_line_requested.connect(self._execute_line)
        editor.cursor_position_changed_info.connect(self._update_cursor_pos)
        editor.file_modified.connect(lambda mod: self._on_editor_modified(editor, mod))
        editor.zoom_requested.connect(self._on_zoom_requested)
        # Refresh the outline panel after a typing pause.
        editor.document().contentsChanged.connect(self._on_editor_content_changed)

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

    def _on_file_renamed(self, old_path, new_path):
        """
        Handle a file rename from the workspace tree.

        If the renamed file is open in a tab, update the tab name,
        the editor's file_path, and the internal tracking entry so
        the editor stays in sync with the file on disk.

        For buffer tabs (no file_path), also updates the buffer_filename
        tracking so the session manifest stays correct.

        :param str old_path: The original file path before the rename.
        :param str new_path: The new file path after the rename.
        """
        # Search all groups for an editor matching the old path.
        group, idx, editor = self._group_container.find_editor_by_path(old_path)

        if group is None:
            # File not open — also check buffer tabs by matching buffer_filename.
            for ed, name, path in self._group_container.all_editors():
                if path is None and hasattr(ed, "_buffer_filename") and ed._buffer_filename:
                    old_filename = os.path.basename(old_path)
                    if ed._buffer_filename == old_filename:
                        # Found the buffer tab — update tracking.
                        ed._buffer_filename = os.path.basename(new_path)
                        new_name = os.path.splitext(ed._buffer_filename)[0]
                        # Find the group and index for this editor.
                        for g in self._group_container.groups():
                            i = g.index_of_editor(ed)
                            if i >= 0:
                                g.set_tab_text(i, new_name)
                                g.update_editor_entry(i, ed, new_name, None)
                                break
                        self._update_open_editors()
                        self._save_session_manifest()
                        logger.info("Buffer tab renamed: %s -> %s", old_filename, ed._buffer_filename)
                        return
            return

        # File-backed tab — update the editor's file path and tab name.
        editor.file_path = new_path
        new_tab_name = os.path.basename(new_path)
        group.set_tab_text(idx, new_tab_name)
        group.set_tab_icon(idx, self._icon_for_language(editor.language))
        group.update_editor_entry(idx, editor, new_tab_name, new_path)

        self._update_open_editors()
        self._save_session_manifest()
        logger.info("Tab renamed: %s -> %s", os.path.basename(old_path), new_tab_name)

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

        # If the editor is locked (read-only), saving implies the user
        # wants to edit — unlock it so subsequent keystrokes don't bounce.
        if editor.isReadOnly():
            editor.setReadOnly(False)
            self._show_status("File unlocked")

        if editor.file_path:
            self._write_file(editor, editor.file_path)
            # Auto-reload the module in both local and DCC environments
            # so the project runs with the updated code immediately.
            self._auto_reload_module(editor.file_path)
            # Incrementally update the symbol index for this file so
            # Go To Declaration reflects the latest changes immediately.
            if self._symbol_index is not None:
                self._symbol_index.update_file(editor.file_path)
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

        If the file is read-only on disk (e.g. Perforce marks checked-in
        files as read-only), the read-only attribute is cleared before
        writing so the save succeeds without requiring a manual checkout.

        :param MCACodeEditor editor: The editor to save.
        :param str filepath: The file path to write to.
        """
        try:
            # Clear the OS read-only flag if set (common with Perforce
            # and other VCS that mark files read-only on disk).
            if os.path.exists(filepath) and not os.access(filepath, os.W_OK):
                os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)
                logger.debug("Cleared read-only attribute: %s", filepath)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(editor.toPlainText())
            editor.document().setModified(False)
            logger.debug("Saved file: %s", filepath)
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

        # Clean up the completer's app-level event filter before
        # removing the editor.  Without this, orphaned completers
        # (parent=None) accumulate on QApplication and cause
        # shiboken crashes during shutdown.
        if hasattr(editor, "_completer") and editor._completer is not None:
            try:
                editor._completer.cleanup()
            except Exception as exc:
                logger.warning("Completer cleanup on tab close failed: %s", exc)

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

        # Give the editor a way to query names imported in other open
        # tabs so pyflakes can suppress false-positive "undefined name"
        # errors for cross-tab imports and forced-import globals.
        editor._known_globals_provider = lambda ed=editor: self._collect_known_globals(ed)

    def _collect_known_globals(self, requesting_editor):
        """
        Collect names that are known to be defined at runtime but are not
        imported in *requesting_editor*'s file.

        Sources:
            1. Import statements in every *other* open Python tab.
            2. The ``py_forced_imports`` setting (comma-separated names).

        The result is passed to ``analyze_python(known_globals=...)`` so
        pyflakes suppresses false-positive "undefined name" errors for
        these names.

        :param MCACodeEditor requesting_editor: The editor being analyzed.
        :return: Set of known global name strings.
        :rtype: set
        """
        import re
        names = set()

        # --- Source 1: imports from other open tabs ---
        # Re-use the same regex patterns as PythonHighlighter to keep
        # parsing consistent.
        re_import = re.compile(r"^\s*import\s+(.+)")
        re_from_import = re.compile(r"^\s*from\s+\S+\s+import\s+(.+)")

        for editor, tab_name, path in self._group_container.all_editors():
            # Skip the editor that is requesting analysis — it only needs
            # names from *other* tabs.
            if editor is requesting_editor:
                continue
            # Only scan Python tabs.
            if editor.language != "python":
                continue

            code = editor.toPlainText()
            for line in code.splitlines():
                # Try "from X import ..." first.
                m = re_from_import.match(line)
                if m:
                    for part in m.group(1).split(","):
                        part = part.strip()
                        if not part or part.startswith("#"):
                            break
                        tokens = part.split()
                        if len(tokens) >= 3 and tokens[-2] == "as":
                            names.add(tokens[-1])
                        else:
                            names.add(tokens[0])
                    continue

                m = re_import.match(line)
                if m:
                    for part in m.group(1).split(","):
                        part = part.strip()
                        if not part or part.startswith("#"):
                            break
                        tokens = part.split()
                        if len(tokens) >= 3 and tokens[-2] == "as":
                            names.add(tokens[-1])
                        else:
                            names.add(tokens[0].split(".")[0])

        # --- Source 2: forced imports from settings ---
        forced = self._settings.get("py_forced_imports") if self._settings else ""
        if forced:
            for name in forced.split(","):
                name = name.strip()
                if name:
                    names.add(name)

        return names

    def _on_editor_content_changed(self):
        """
        Handle editor content changes by scheduling an outline refresh.

        Restarts the debounce timer so the outline is reparsed 500ms
        after the user stops typing, avoiding expensive re-parsing on
        every single keystroke.
        """
        self._outline_timer.start()

    def _refresh_outline(self):
        """
        Refresh the outline panel from the current editor.

        Called by the debounce timer after a typing pause.
        """
        editor = self._current_editor()
        if editor:
            self._update_outline(editor)

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
                        # Include the buffer ID in the tab name so it matches
                        # the on-disk filename (e.g. "Python_1", "MEL_2").
                        bid = getattr(e, "_buffer_id", None)
                        new_name = "{}_{}".format(language, bid) if bid else language
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

        Buffer IDs are allocated eagerly in ``_new_buffer()`` so the
        tab name always matches the filename.  This method just writes
        the content to disk.

        :param MCACodeEditor editor: The editor whose content to persist.
        """
        # Only persist temp buffers (no file_path).
        if editor.file_path:
            return

        # Fallback: allocate an ID if somehow missing (e.g. restored session).
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

        # Route the save to the correct file: project session file if a
        # project is active, otherwise the default session.json.
        if self._active_project:
            self._session_manager.save_manifest_to(
                self._active_project.session_file_path,
                layout_tree, active_group_idx,
            )
        else:
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

    def _save_context_session(self):
        """
        Flush all editor content to disk and save the session manifest.

        Called during context switches (open/close project) to ensure
        the outgoing context's tabs are fully persisted before the
        incoming context replaces them.
        """
        # Flush every temp buffer to disk so nothing is lost.
        all_editors = self._group_container.all_editors()
        for editor, name, path in all_editors:
            if not path:
                self._save_buffer_content(editor)

        # Write the manifest to the correct file (project or default).
        self._save_session_manifest()

    def _switch_to_manifest(self, manifest):
        """
        Tear down all existing tabs and rebuild from a manifest.

        If *manifest* is a valid session dict, the layout is rebuilt
        and tabs are populated from it. If *manifest* is None (e.g.
        first time opening a project with no saved session), all
        existing tabs are removed and a single fresh buffer is created.

        This is the single entry-point for context switches (open/close
        project). It always goes through ``restore_layout_state`` so the
        old group widgets are destroyed and new ones are created.

        :param dict manifest: A v3 session manifest dict, or None.
        """
        if manifest:
            # Delegate to _restore_session which calls restore_layout_state
            # internally — this tears down old groups and rebuilds new ones.
            restored = self._restore_session(manifest)
        else:
            restored = False

        if not restored:
            # No manifest or it had no tabs — build a blank single-group
            # layout so the old tabs are removed, then add one fresh buffer.
            blank_layout = {
                "layout": {
                    "type": "splitter",
                    "orientation": "horizontal",
                    "sizes": [],
                    "children": [
                        {"type": "group", "tabs": [], "active_tab": 0},
                    ],
                },
                "active_group": 0,
            }
            self._group_container.restore_layout_state(blank_layout)
            self._new_buffer()

        # After rebuilding the layout, force the active group to re-sync
        # its current tab index.  During _restore_session, tabs are added
        # while QTabWidget signals are blocked, so currentWidget() can
        # return None even though tabs exist.  Re-setting the index with
        # signals live fixes the internal QTabWidget state.
        # After rebuilding the layout, force the active group to re-sync
        # its current tab index and give keyboard focus to the editor.
        active_group = self._group_container.active_group()
        if active_group and active_group.count() > 0:
            idx = active_group.current_index()
            if idx < 0 or idx >= active_group.count():
                idx = 0
            active_group.set_current_index(idx)

        # Grab the editor directly from the QTabWidget to avoid the
        # isinstance() check in current_editor(), which can fail after
        # plugin reloads due to class identity mismatch.
        if active_group:
            editor = active_group._tab_widget.currentWidget()
        else:
            editor = None
        if editor:
            editor.setFocus()

    def _restore_session(self, manifest=None):
        """
        Restore tabs from a session manifest.

        If *manifest* is provided, uses it directly (e.g. from a
        per-project session file). Otherwise loads the default
        ``session.json`` manifest.

        Supports v1, v2, and v3 manifest formats (auto-upgrades to v3).
        For file-backed tabs, re-opens the file from disk. For buffer
        tabs, loads content from the buffers directory.

        V3 manifests use a recursive layout tree that supports nested
        horizontal/vertical splits.

        :param dict manifest: Pre-loaded manifest dict, or None to load
            from the default session.json.
        :return: True if at least one tab was restored.
        :rtype: bool
        """
        if manifest is None:
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
                    # Filename formats: "Python_1.py", "MEL_2.mel", or legacy "buffer_1.py".
                    # The numeric ID is always the part after the last underscore.
                    # Since buffers now live in scripts_dir, set file_path so the
                    # tab is treated as file-backed (searchable, saveable).
                    buf_filepath = None
                    if buffer_file:
                        try:
                            basename = os.path.splitext(buffer_file)[0]
                            editor._buffer_id = int(basename.rsplit("_", 1)[1])
                        except (IndexError, ValueError):
                            editor._buffer_id = self._session_manager.allocate_buffer_id()
                        editor._buffer_filename = buffer_file
                        buf_filepath = os.path.join(
                            self._session_manager.scripts_dir, buffer_file
                        )
                        editor.file_path = buf_filepath

                    icon = self._icon_for_language(language)
                    group.add_editor(editor, title, buf_filepath, icon)
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
        # Refresh the outline panel after a typing pause.
        editor.document().contentsChanged.connect(self._on_editor_content_changed)
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
        so the tab title drops the '*' indicator. For .py files, the
        module is auto-reloaded locally and in the connected DCC.

        :param MCACodeEditor editor: The editor to save.
        """
        if editor.file_path:
            self._write_file(editor, editor.file_path)
            # Auto-reload so the DCC and local env have the latest code.
            self._auto_reload_module(editor.file_path)
        else:
            self._save_buffer_content(editor)
        editor.document().setModified(False)

    def _resolve_module_name(self, filepath):
        """
        Convert a .py file path to its dotted module name.

        Searches ``sys.path`` for the longest parent directory of
        *filepath* and converts the relative remainder to a dotted
        module name.  Handles edge cases:

        - Empty string (``""``) and dot (``"."``) in ``sys.path`` are
          resolved to the actual current working directory so they can
          be compared against absolute file paths.
        - Case-insensitive comparison on Windows via ``os.path.normcase``.

        If no ``sys.path`` entry matches, falls back to a reverse lookup
        through ``sys.modules`` — checking each module's ``__file__``
        attribute for a match.  This catches modules imported via CWD
        or other mechanisms that don't have an explicit ``sys.path``
        entry.

        :param str filepath: Absolute path to the .py file.
        :return: Dotted module name, or None if not resolvable.
        :rtype: str or None
        """
        norm = os.path.normcase(os.path.normpath(filepath))

        # --- Strategy 1: find longest sys.path prefix ---
        module_name = None
        for sp in sys.path:
            # Resolve empty string / dot to the real CWD so we can
            # compare against the absolute file path.
            if sp in ("", "."):
                sp = os.getcwd()
            sp_norm = os.path.normcase(os.path.normpath(sp))
            if not norm.startswith(sp_norm + os.sep):
                continue
            # Build dotted name from the relative path (strip .py).
            rel = os.path.relpath(norm, sp_norm)
            parts = rel.replace(os.sep, "/").split("/")
            parts[-1] = parts[-1][:-3]  # strip .py
            # __init__ means the package itself, drop it.
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                # Skip if any part is not a valid Python identifier
                # (e.g. "mca-maya" has a hyphen and can't be a module).
                if not all(p.isidentifier() for p in parts):
                    continue
                candidate = ".".join(parts)
                # Prefer the longest (most specific) match.
                if module_name is None or len(candidate) > len(module_name):
                    module_name = candidate

        if module_name:
            return module_name

        # --- Strategy 2: reverse-lookup via sys.modules __file__ ---
        # Some modules are imported via CWD or path hooks that don't
        # leave an obvious sys.path prefix.  Walk sys.modules and
        # compare each module's __file__ to find a match.
        for mod_name, mod in sys.modules.items():
            mod_file = getattr(mod, "__file__", None)
            if not mod_file:
                continue
            mod_norm = os.path.normcase(os.path.normpath(mod_file))
            if mod_norm == norm:
                return mod_name

        # --- Strategy 3: use the bare filename as module name ---
        # Last resort — if the file is a simple script like
        # ``node_util.py``, assume the module name is ``node_util``.
        # This won't match packages, but covers the common case of
        # single-file scripts in the user's project.
        basename = os.path.basename(filepath)
        if basename.endswith(".py"):
            bare = basename[:-3]
            if bare and bare != "__init__":
                return bare

        return None

    def _auto_reload_module(self, filepath, force=False):
        """
        Reload the Python module corresponding to *filepath* if it has
        already been imported, both locally and in the connected DCC.

        Resolves the file path to a dotted module name, then reloads it
        in both the editor's local Python and the connected DCC.  After
        reloading, patches stale ``from module import func`` references
        in ``__main__.__dict__``.

        Shows a message in the output panel on success so the user can
        confirm the reload happened.

        Skips silently for non-.py files or temp buffers.

        :param str filepath: Absolute path to the saved .py file.
        :param bool force: When True, skip the project/auto-reload
            checks and reload unconditionally. Used by the "Reload
            Scripts" toolbar button.
        """
        if not filepath or not filepath.endswith(".py"):
            return

        # Auto-reload is a project-only feature.  In default mode (no
        # active project) we skip it entirely.  In project mode, respect
        # the project's toggle (which defaults to True / on).
        # When force=True, bypass these checks so the user can trigger
        # reloads manually via the toolbar button.
        if not force:
            if not self._active_project or not self._active_project.auto_reload_modules:
                return

        # Resolve the file path to a dotted module name.
        module_name = self._resolve_module_name(filepath)

        if not module_name:
            logger.debug("Auto-reload: could not resolve module name for %s", filepath)
            return

        # --- Reload locally (if the module has been imported here) ---
        reloaded_locally = False
        if module_name in sys.modules:
            try:
                mod = sys.modules[module_name]

                # Snapshot attribute values BEFORE reload.  importlib.reload
                # modifies the module object in-place, so after reload() the
                # module's attributes are the NEW values.  We need the old
                # values to find stale references in __main__.__dict__.
                old_attrs = {
                    name: getattr(mod, name, None) for name in dir(mod)
                }

                importlib.reload(mod)
                reloaded_locally = True
                logger.info("Auto-reloaded local module: %s", module_name)

                # Patch stale references in __main__.__dict__.
                # When the user did  "from my_module import func"  the
                # name 'func' in __main__ still points at the old function
                # object.  Walk the snapshot and replace any __main__ refs
                # that still hold the old value with the new one.
                try:
                    import __main__
                    for attr_name, old_val in old_attrs.items():
                        if old_val is None:
                            continue
                        new_val = getattr(mod, attr_name, None)
                        if new_val is old_val:
                            continue  # Unchanged attribute — skip.
                        main_val = getattr(__main__, attr_name, _SENTINEL)
                        if main_val is old_val:
                            setattr(__main__, attr_name, new_val)
                except Exception:
                    pass

                # Show confirmation in the output panel so the user
                # can verify the reload happened.
                self._output.write_info("Auto-reloaded: {}".format(module_name))

            except Exception as exc:
                logger.warning("Failed to auto-reload %s locally: %s", module_name, exc)
                self._output.write_warning(
                    "Auto-reload failed for {}: {}".format(module_name, exc))
        else:
            logger.debug("Auto-reload: %s not in local sys.modules", module_name)

        # --- Reload in the connected DCC ---
        # Always attempt the DCC reload even if the local lookup failed —
        # the module may be imported in Maya's interpreter but not in the
        # editor's own Python (standalone editor case).
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            # The DCC reload code snapshots old attribute values before
            # reload, then patches __main__ references that still hold the
            # old function/class objects.  Uses _mca_ prefixed temporaries
            # to avoid polluting the user's namespace.
            reload_code = (
                "import importlib, sys\n"
                "if '{mod}' in sys.modules:\n"
                "    _mca_m = sys.modules['{mod}']\n"
                "    _mca_snap = {{n: getattr(_mca_m, n, None) for n in dir(_mca_m)}}\n"
                "    importlib.reload(_mca_m)\n"
                "    import __main__ as _mca_main\n"
                "    for _mca_n, _mca_ov in _mca_snap.items():\n"
                "        if _mca_ov is None: continue\n"
                "        _mca_nv = getattr(_mca_m, _mca_n, None)\n"
                "        if _mca_nv is _mca_ov: continue\n"
                "        if getattr(_mca_main, _mca_n, None) is _mca_ov:\n"
                "            setattr(_mca_main, _mca_n, _mca_nv)\n"
                "    print('Auto-reloaded: {mod}')\n"
            ).format(mod=module_name)
            try:
                adapter.execute(reload_code, "python")
                logger.info("Sent auto-reload to DCC for module: %s", module_name)
            except Exception as exc:
                logger.warning("Failed to auto-reload %s in DCC: %s", module_name, exc)

    def _write_adapter_output(self, text):
        """
        Write captured adapter output to the output panel.

        The internal Maya adapter captures stdout during exec via a
        temporary tee and returns the captured text.  This method routes
        each line to the appropriate output method based on content:
          - ``# Result: ... #`` → ``write_result()`` (yellow)
          - Everything else → ``write_output()`` (white)

        Respects the verbosity level — "minimal" suppresses normal output
        but still shows result lines.

        Warnings and errors from Maya commands (``cmds.warning()``,
        ``cmds.error()``, etc.) arrive via MCommandMessage and are NOT
        included in the adapter's return value — they're handled by
        ``_on_maya_output()`` in ``maya_window.py``.

        :param str text: Captured stdout text from adapter execution.
        """
        if not text or not text.strip():
            return

        for line in text.splitlines():
            if not line.strip():
                continue
            stripped = line.strip()
            # Route result-formatted lines to write_result for coloring.
            if stripped.startswith("# Result:") and stripped.endswith("#"):
                self._output.write_result(line)
            elif self._verbosity_level != "minimal":
                self._output.write_output(line)

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
        # Echo the executed code in blue so the user sees what ran.
        # Only suppressed in "minimal" verbosity mode.
        if self._verbosity_level != "minimal":
            self._output.write_code_echo(code.strip())
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            # The adapter captures stdout via a temporary tee during
            # exec and returns the captured text.  Write it to the panel.
            result = adapter.execute(code, editor.language)
            self._write_adapter_output(result)
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
        # Echo the executed code in blue so the user sees what ran.
        # Only suppressed in "minimal" verbosity mode.
        if self._verbosity_level != "minimal":
            self._output.write_code_echo(code.strip())
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            result = adapter.execute(code, editor.language)
            self._write_adapter_output(result)
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
        # Echo the executed code in blue so the user sees what ran.
        # Only suppressed in "minimal" verbosity mode.
        if self._verbosity_level != "minimal":
            self._output.write_code_echo(code.strip())
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            result = adapter.execute(code, editor.language)
            self._write_adapter_output(result)
        else:
            if editor.language == "python":
                self._execute_locally(code)
            else:
                self._output.write_warning("No DCC connected.")

    def _execute_locally(self, code):
        """Execute Python code locally when no DCC is connected."""
        # [UE_OUTPUT_DEBUG] Log entry with DCC context for debugging output routing.
        logger.info("[UE_OUTPUT_DEBUG] _execute_locally called, dcc_version=%s", self._dcc_version)

        # Ensure scripts/ and site-packages/ are on sys.path so imports work.
        scripts_dir = self._session_manager.scripts_dir
        site_pkg_dir = self._session_manager.site_packages_dir
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        if site_pkg_dir not in sys.path:
            sys.path.insert(0, site_pkg_dir)

        # Use plain exec() with stdout/stderr redirection for ALL local
        # execution — including UE.  We previously tried UE's
        # execute_python_command_ex() API, but it does NOT capture print()
        # output reliably (log_entries come back empty for print calls).
        # Since we're already inside UE's Python interpreter, exec()
        # works and `import unreal` is available in the namespace.
        # Redirecting sys.stdout BEFORE exec() captures print() at the
        # Python level before UE's C-level hook can intercept it.

        # Echo the executed code to UE's Output Log so the user can see
        # what was run from both the MCA Editor and UE's log panel.
        if self._dcc_version and self._dcc_version.startswith("UE"):
            try:
                import unreal as _ue
                # Show a compact preview of the code being executed.
                preview = code.strip().split('\n')[0]
                if len(code.strip().split('\n')) > 1:
                    preview += f"  (+{len(code.strip().split(chr(10))) - 1} more lines)"
                _ue.log(f"[MCAEditor] Exec: {preview}")
            except ImportError:
                pass

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        _in_ue = self._dcc_version and self._dcc_version.startswith("UE")

        # Redirect stdout to capture print() output.
        sys.stdout = io.StringIO()

        # In UE, do NOT redirect stderr. Python's logging module and
        # UE's C-level stderr hook both write to the original stderr,
        # and the UE log tailer picks those up with proper severity
        # coloring. Redirecting stderr here would cause double output
        # (once from our capture, once from the log tailer).
        if not _in_ue:
            sys.stderr = io.StringIO()

        try:
            # Try eval mode first — if the code is a single expression
            # (variable name, function call, etc.), eval returns its value.
            # This lets the user highlight a variable and execute to see its
            # value, matching UE Blueprint / Maya Script Editor behavior.
            try:
                compiled = compile(code, "<mca_editor>", "eval")
                result = eval(compiled, self._local_namespace)
                if result is not None:
                    print("# Result: {} #".format(repr(result)))
            except SyntaxError:
                # Not a single expression — execute as statements.
                exec(code, self._local_namespace)

            output = sys.stdout.getvalue()
            # Respect verbosity: "minimal" suppresses normal stdout output.
            if output and self._verbosity_level != "minimal":
                self._output.write_output(output.rstrip())

            # Stderr handling — only when we redirected it (non-UE).
            if not _in_ue:
                errors = sys.stderr.getvalue()
                if errors:
                    # Route each stderr line based on content: ERROR-level
                    # lines go red, WARNING-level lines go yellow, and
                    # untagged lines default to warning (amber).
                    for err_line in errors.rstrip().splitlines():
                        stripped = err_line.strip()
                        if not stripped:
                            continue
                        if "ERROR" in stripped or "Error" in stripped:
                            self._output.write_error(err_line)
                        else:
                            self._output.write_warning(err_line)

            # Show success message unless in minimal mode or running in UE
            # (UE executions are frequent and the message adds noise).
            if self._verbosity_level != "minimal":
                if not _in_ue:
                    self._output.write_success("Executed locally (no DCC)")

            # Echo stdout to UE's Output Log for cross-reference.
            # Prefix EVERY line with [MCAEditor] so the log tailer's
            # skip filter catches all of them (prevents white dupes).
            if _in_ue:
                try:
                    import unreal as _ue
                    if output:
                        for _out_line in output.rstrip().splitlines():
                            _ue.log("[MCAEditor] {}".format(_out_line))
                except ImportError:
                    pass
        except Exception:
            tb = traceback.format_exc()
            self._output.write_error(tb.rstrip())
            # Echo a single-line error summary to UE's Output Log.
            # Do NOT echo the full multi-line traceback — each line
            # appears as a separate UE log entry, and only the first
            # has the [MCAEditor] prefix.  The log tailer misses the
            # subsequent lines, which then show as white duplicates.
            if _in_ue:
                try:
                    import unreal as _ue
                    # Extract just the final exception line.
                    last_line = tb.rstrip().splitlines()[-1]
                    _ue.log_error("[MCAEditor] {}".format(last_line))
                except (ImportError, IndexError):
                    pass
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            # Force-flush in UE so output appears immediately instead of
            # waiting for the next Qt event pump from the UE tick cycle.
            if self._dcc_version and self._dcc_version.startswith("UE"):
                self._output.flush()

    def _api_execute_code(self, code, language="python"):
        """
        Execute code via the API — takes explicit code + language params.

        For DCC execution, sends code through the active adapter and returns
        the socket response.  For local execution, redirects stdout/stderr
        and uses the persistent namespace.

        Called by ``EditorAPI.execute_in_dcc()`` — not intended for direct
        UI use (the regular ``_execute_all`` reads from the active editor).

        :param str code: Source code to execute.
        :param str language: 'python' or 'mel' (default 'python').
        :return: Dict with ``success``, ``output``, ``error``.
        :rtype: dict
        """
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            try:
                result = adapter.execute(code, language)
                # Write captured stdout to the panel and pass through
                # for API callers who need a return value.
                self._write_adapter_output(result)
                return {"success": True, "output": result or "", "error": None}
            except Exception as exc:
                return {"success": False, "output": "", "error": str(exc)}
        else:
            # No DCC connected — fall back to local execution for Python.
            if language != "python":
                return {
                    "success": False,
                    "output": "",
                    "error": "No DCC connected. Cannot execute {} code.".format(language),
                }
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                exec(code, self._local_namespace)
                output = sys.stdout.getvalue()
                errors = sys.stderr.getvalue()
                return {
                    "success": True,
                    "output": output.rstrip() if output else "",
                    "error": errors.rstrip() if errors else None,
                }
            except Exception:
                tb = traceback.format_exc()
                return {"success": False, "output": "", "error": tb.rstrip()}
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

                # Trigger MCP server setup when connecting to Maya.
                # This runs in the background so it won't block the UI.
                if info["dcc_type"] == DCCType.MAYA:
                    try:
                        from mca_core import mcp_setup
                        mcp_setup.ensure_maya_mcp(
                            background=True,
                            status_callback=lambda msg: QTimer.singleShot(
                                0, lambda m=msg: self._show_status(m, 5000)
                            ),
                        )
                    except Exception as exc:
                        logger.warning("MCP setup trigger failed: %s", exc)

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
        editor = self._new_buffer("mel")
        tab_name = "MEL_{}".format(editor._buffer_id)
        group = self._group_container.active_group()
        if group:
            idx = group.index_of_editor(editor)
            if idx >= 0:
                group.set_tab_text(idx, tab_name)
                group.set_tab_icon(idx, self._icon_for_language("mel"))
                group.update_editor_entry(idx, editor, tab_name, None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _new_python_buffer(self):
        """Create a new Python buffer."""
        editor = self._new_buffer("python")
        tab_name = "Python_{}".format(editor._buffer_id)
        group = self._group_container.active_group()
        if group:
            idx = group.index_of_editor(editor)
            if idx >= 0:
                group.set_tab_text(idx, tab_name)
                group.set_tab_icon(idx, self._icon_for_language("python"))
                group.update_editor_entry(idx, editor, tab_name, None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _new_text_buffer(self):
        """Create a new plain text buffer."""
        editor = self._new_buffer("text")
        tab_name = "Text_{}".format(editor._buffer_id)
        group = self._group_container.active_group()
        if group:
            idx = group.index_of_editor(editor)
            if idx >= 0:
                group.set_tab_text(idx, tab_name)
                group.set_tab_icon(idx, self._icon_for_language("text"))
                group.update_editor_entry(idx, editor, tab_name, None)
        self._update_language_combo(editor)
        self._update_open_editors()

    def _build_recent_files_menu(self):
        """Rebuild the Recent Files submenu."""
        if not self._recent_files_menu:
            return

        # Guard against Qt having destroyed the C++ QMenu while the
        # Python reference still exists (e.g. after menu bar rebuild).
        try:
            self._recent_files_menu.clear()
        except RuntimeError:
            self._recent_files_menu = None
            return
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
                # On Windows, case-only renames (File.py -> file.py) fail because
                # the filesystem treats them as the same path.  Work around by
                # renaming through a temporary intermediate name.
                if old_path.lower() == new_path.lower() and old_path != new_path:
                    import tempfile
                    tmp = old_path + ".mca_rename_tmp"
                    os.rename(old_path, tmp)
                    os.rename(tmp, new_path)
                else:
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

    def _rename_tab_in_group(self, group, idx):
        """
        Rename the file for a specific tab (triggered from tab context menu).

        :param EditorGroup group: The group containing the tab.
        :param int idx: Tab index within the group.
        """
        if idx < 0:
            return
        # Retrieve the editor widget from the group's internal editors list.
        editors = group.editors()
        if idx >= len(editors):
            return
        editor = editors[idx][0]
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
                # On Windows, case-only renames (File.py -> file.py) fail because
                # the filesystem treats them as the same path.  Work around by
                # renaming through a temporary intermediate name.
                if old_path.lower() == new_path.lower() and old_path != new_path:
                    tmp = old_path + ".mca_rename_tmp"
                    os.rename(old_path, tmp)
                    os.rename(tmp, new_path)
                else:
                    os.rename(old_path, new_path)
                editor.file_path = new_path
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
        """
        Open the Find in Files dialog (Ctrl+Shift+F).

        Searches across all workspace folders for text matches and
        displays results in a tree.  Double-clicking navigates.
        """
        folders = self._get_workspace_folders()
        if not folders:
            self._show_status("No workspace folders — add one first")
            return

        dlg = FindInFilesDialog(self, folders, self._navigate_to_file_line, mode="find")
        dlg.show()

    def _replace_in_files(self):
        """
        Open the Replace in Files dialog (Ctrl+Shift+R).

        Same as Find in Files but with an additional replace input row
        and a Replace All button.
        """
        folders = self._get_workspace_folders()
        if not folders:
            self._show_status("No workspace folders — add one first")
            return

        dlg = FindInFilesDialog(
            self, folders, self._navigate_to_file_line,
            mode="replace",
            replace_done_callback=self._reload_editors_for_paths,
        )
        dlg.show()

    def _reload_editors_for_paths(self, filepaths):
        """
        Reload open editor tabs whose files were modified on disk.

        Called after Replace All so the editor content matches the
        updated file.  Preserves the cursor position in each editor.

        :param list filepaths: Absolute paths of files that changed.
        """
        # Normalize for reliable comparison.
        norm_paths = {os.path.normpath(fp) for fp in filepaths}

        for editor, _name, stored_path in self._group_container.all_editors():
            # Check both the stored path and the editor's file_path attribute.
            ep = getattr(editor, "file_path", None)
            check_path = ep or stored_path
            if not check_path:
                continue
            if os.path.normpath(check_path) not in norm_paths:
                continue

            # Re-read the file content from disk.
            try:
                with open(check_path, "r", encoding="utf-8") as f:
                    new_content = f.read()
            except Exception:
                continue

            # Save cursor position, replace content, restore cursor.
            cursor = editor.textCursor()
            pos = cursor.position()
            editor.setPlainText(new_content)
            editor.document().setModified(False)
            cursor = editor.textCursor()
            cursor.setPosition(min(pos, len(new_content)))
            editor.setTextCursor(cursor)

        logger.info("Reloaded %d editor(s) after Replace All", len(norm_paths))

    def _get_workspace_folders(self):
        """
        Collect workspace folders from the sidebar.

        :return: List of workspace folder paths, or empty list.
        :rtype: list
        """
        folders = []
        if hasattr(self, "_sidebar") and self._sidebar:
            panel = getattr(self._sidebar, "workspace_panel", None)
            if panel:
                folders = panel.get_workspace_folders()
        return folders

    def _navigate_to_file_line(self, filepath, line_number):
        """
        Open a file and jump to a specific line number.

        Used as the navigation callback for Find in Files and
        Go to Declaration popups.  If the file is already open in
        any tab (matched by either the tab's stored path or the
        editor's ``file_path`` attribute), switches to that tab
        instead of opening a duplicate.

        :param str filepath: Absolute path to the file.
        :param int line_number: 1-based line number to navigate to.
        """
        norm_path = os.path.normpath(filepath)

        # First, try the standard path lookup (handles file-backed tabs).
        group, idx, existing = self._group_container.find_editor_by_path(filepath)

        # If the file IS found, switch to that tab so _current_editor()
        # returns the correct widget below.  Without this, navigating to
        # a file that's already open in a non-active tab silently does
        # nothing — go_to_line() runs on the wrong editor.
        if group is not None and idx >= 0:
            group.set_current_index(idx)
            self._group_container._on_group_activated(group)

        # If not found, also check each editor's file_path attribute.
        # Buffer tabs store path=None in the group, but editor.file_path
        # may be set if the buffer was saved or loaded from a file.
        if group is None:
            for editor, _name, _stored_path in self._group_container.all_editors():
                ep = getattr(editor, "file_path", None)
                if ep and os.path.normpath(ep) == norm_path:
                    # Found a match — switch to that editor's group and tab.
                    for g in self._group_container.groups():
                        idx2, found = g.find_editor_by_path(_stored_path)
                        # find_editor_by_path won't match None paths,
                        # so search by identity instead.
                        if idx2 < 0:
                            for i, (ed, _n, _p) in enumerate(g.editors()):
                                if ed is editor:
                                    idx2 = i
                                    break
                        if idx2 >= 0:
                            g.set_current_index(idx2)
                            self._group_container._on_group_activated(g)
                            group = g
                            break
                    break

        if group is None:
            # Not open in any tab — open it normally.
            self._open_file_path(filepath)

        # Jump to the target line after the file is loaded / switched.
        editor = self._current_editor()
        if editor:
            editor.go_to_line(line_number)

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
        # Hide MEL-related settings when the host doesn't support MEL
        # (e.g. running inside Unreal Engine). Check whether "MEL" is
        # still present in the language combo — ue_editor_host strips it.
        mel_available = any(
            self._lang_combo.itemText(i) == "MEL"
            for i in range(self._lang_combo.count())
        )
        dlg = SettingsDialog(
            self._settings,
            action_registry=self._action_registry,
            default_shortcuts=self._default_shortcuts,
            hide_mel=not mel_available,
            parent=self,
        )
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
        if hasattr(self._output, "set_line_wrap_mode"):
            wrap_mode = (
                QPlainTextEdit.LineWrapMode.WidgetWidth if output_wrap
                else QPlainTextEdit.LineWrapMode.NoWrap
            )
            self._output.set_line_wrap_mode(wrap_mode)
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
        Apply the current font, color scheme, and whitespace setting to a
        single editor.

        Called when a new tab is created so it inherits the active zoom
        level, color scheme, and whitespace rendering state from the session.

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

        # Apply the saved color scheme so new tabs match existing ones.
        scheme = build_scheme_dict(self._settings)
        editor.set_color_scheme(scheme)

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

    def _on_output_font_size_changed(self, size):
        """
        Persist the output panel font size when the user Ctrl+scrolls.

        :param int size: The new font point size.
        """
        self._settings.set("output_font_size", size)
        self._settings.sync()

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

    # --- Background Symbol Index -----------------------------------------------

    def _start_symbol_indexing(self):
        """
        Create a fresh ``SymbolIndex`` and launch an ``IndexWorker`` thread.

        Called when a project is opened.  A 500 ms QTimer polls the worker
        for progress and updates the status bar until indexing finishes.

        If the index is already populated and ready for the same set of
        workspace folders, it is reused without re-scanning.  This avoids
        the expensive full re-index when the editor is closed and reopened
        within the same Maya session.
        """
        folders = self._get_workspace_folders()
        if not folders:
            return

        # Determine excluded folders from the active project config.
        excluded = set()
        if self._active_project:
            excluded = set(self._active_project.excluded_folders)

        # Reuse the existing index if it is ready and covers the same folders.
        # Check both the instance-level cache (same panel, project reopen)
        # and the module-level cache (panel destroyed and recreated in Maya).
        # On Windows, folder paths may differ only in drive-letter case
        # (e.g. "E:\\" vs "e:\\"), so we normalize to lowercase there.
        global _cached_symbol_index, _cached_indexed_folders
        normalized = sorted(os.path.normpath(f) for f in folders)
        if sys.platform == "win32":
            normalized = [f.lower() for f in normalized]

        # First check: instance still has a live, ready index.
        if (self._symbol_index is not None
                and self._symbol_index.get_state() == "ready"
                and getattr(self, "_indexed_folders", None) == normalized):
            logger.info("Symbol index still valid — skipping re-index")
            file_count = self._symbol_index.get_file_count()
            self.index_status_changed.emit(
                "Indexed {} files".format(file_count)
            )
            return

        # Second check: module-level cache from a previous panel instance.
        # The index is stashed eagerly in _poll_index_progress when
        # indexing completes, so this covers both the normal close/reopen
        # cycle AND the startup race where _do_auto_open_editor discards
        # the uiScript panel without calling cleanup().
        if (_cached_symbol_index is not None
                and _cached_symbol_index.get_state() == "ready"
                and _cached_indexed_folders == normalized):
            logger.info("Restoring symbol index from module cache — skipping re-index")
            self._symbol_index = _cached_symbol_index
            self._indexed_folders = normalized
            self._completion_provider.set_symbol_index(self._symbol_index)
            file_count = self._symbol_index.get_file_count()
            self.index_status_changed.emit(
                "Indexed {} files".format(file_count)
            )
            return

        # Cancel any previous indexing run first.
        self._stop_symbol_indexing()

        # Remember which folders this index covers so we can skip next time.
        self._indexed_folders = normalized

        self._symbol_index = SymbolIndex()
        self._completion_provider.set_symbol_index(self._symbol_index)
        self._index_worker = IndexWorker(self._symbol_index, folders, excluded)
        self._index_worker.start()

        # Poll progress every 500 ms from the main thread (no cross-thread signals).
        self._index_progress_timer = QTimer(self)
        self._index_progress_timer.setInterval(500)
        self._index_progress_timer.timeout.connect(self._poll_index_progress)
        self._index_progress_timer.start()

        logger.info("Started background symbol indexing")

    def _stop_symbol_indexing(self, clear_index=True):
        """
        Cancel the running worker, join with a short timeout, and stop the
        progress timer.

        When *clear_index* is False the finished index and cached folder
        list are preserved so that ``_start_symbol_indexing`` can detect
        that the same project is being reopened and skip the expensive
        re-scan.  Pass ``clear_index=True`` (the default) only on full
        panel shutdown or when the index data is no longer useful.

        :param bool clear_index: If True, destroy the index data and
            clear the cached folder list.  If False, only cancel the
            worker and timers.
        """
        # Stop the progress polling timer.
        if self._index_progress_timer is not None:
            self._index_progress_timer.stop()
            self._index_progress_timer = None

        # Stop the debounce timer if running.
        if self._reindex_debounce_timer is not None:
            self._reindex_debounce_timer.stop()
            self._reindex_debounce_timer = None

        # Cancel the worker thread and wait briefly for it to finish.
        if self._index_worker is not None:
            self._index_worker.cancel()
            self._index_worker.join(timeout=2.0)
            self._index_worker = None

        if clear_index:
            # The index is stashed eagerly in _poll_index_progress as
            # soon as it reaches "ready" state.  This block just detaches
            # the reference from the panel instance.  If for some reason
            # the eager stash didn't fire (e.g. timer stopped early),
            # do a last-chance stash here.
            global _cached_symbol_index, _cached_indexed_folders
            if (self._symbol_index is not None
                    and self._symbol_index.get_state() == "ready"):
                _cached_symbol_index = self._symbol_index
                _cached_indexed_folders = getattr(self, "_indexed_folders", None)

            # Detach from this instance but don't destroy the data (it
            # lives on in the module-level cache now).
            self._symbol_index = None
            self._completion_provider.set_symbol_index(None)
            self._indexed_folders = None

        # Clear the action bar indicator.
        self.index_status_changed.emit("")

    def _poll_index_progress(self):
        """
        Called by the progress QTimer every 500 ms.

        Reads the worker's progress and updates the status bar.  When
        indexing is complete, stops the timer and shows the final count.
        """
        if self._symbol_index is None:
            return

        state = self._symbol_index.get_state()
        done, total = self._symbol_index.get_progress()

        if state == "indexing" and total > 0:
            # Update the action bar indicator only — avoid _show_status()
            # because each log line to the output slows Maya noticeably.
            pct = int(done * 100 / total)
            self.index_status_changed.emit("Indexing {}%".format(pct))

        elif state == "ready":
            # Indexing is done — show final stats and stop the timer.
            file_count = self._symbol_index.get_file_count()
            sym_count = self._symbol_index.get_symbol_count()
            msg = "Indexed {} files ({} symbols)".format(file_count, sym_count)
            self._show_status(msg, duration_ms=10000)
            self._output.write_info(msg)
            # Emit persistent index status for the action bar indicator.
            self.index_status_changed.emit(
                "Indexed {} files".format(file_count)
            )
            if self._index_progress_timer is not None:
                self._index_progress_timer.stop()
                self._index_progress_timer = None

            # Eagerly stash the finished index at module level so it
            # survives panel destruction.  _do_auto_open_editor() in
            # plugin_main discards the uiScript panel WITHOUT calling
            # cleanup(), so we can't rely on cleanup() alone to stash.
            global _cached_symbol_index, _cached_indexed_folders
            _cached_symbol_index = self._symbol_index
            _cached_indexed_folders = getattr(self, "_indexed_folders", None)
            logger.info("Stashed symbol index in module cache (%d files)",
                        file_count)

    def _on_workspace_directory_changed(self, path):
        """
        Handle filesystem changes detected by the workspace file watcher.

        Debounces for 3 seconds, then re-indexes the workspace.  This
        catches external changes like git pull, branch switch, etc.

        :param str path: The directory that changed (unused — we re-index all folders).
        """
        # Only re-index if we have an active index.
        if self._symbol_index is None:
            return

        # Reset the debounce timer — 3 seconds after the last change.
        if self._reindex_debounce_timer is None:
            self._reindex_debounce_timer = QTimer(self)
            self._reindex_debounce_timer.setSingleShot(True)
            self._reindex_debounce_timer.setInterval(3000)
            self._reindex_debounce_timer.timeout.connect(self._start_symbol_indexing)

        # Restart the debounce window.
        self._reindex_debounce_timer.start()

    # --- Go to Declaration / Find Usages (Ctrl+B) -----------------------------

    # Regex patterns that match symbol definitions in Python and MEL.
    _DEFINITION_PATTERNS = [
        r"^\s*class\s+{symbol}\b",
        r"^\s*def\s+{symbol}\b",
        r"^\s*global\s+proc\s+\w*\s*{symbol}\b",
        r"^\s*proc\s+\w*\s*{symbol}\b",
    ]

    # Directories to skip during workspace scanning (imported from constants).
    _DECL_SKIP_DIRS = SKIP_DIRS

    # Maximum directory depth for workspace scanning (imported from constants).
    _DECL_MAX_DEPTH = MAX_WALK_DEPTH

    # Binary / non-text extensions to skip.
    _DECL_SKIP_EXTS = {
        ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".png", ".jpg",
        ".jpeg", ".gif", ".bmp", ".ico", ".ttf", ".otf", ".woff", ".woff2",
        ".zip", ".gz", ".tar", ".7z", ".rar", ".db", ".sqlite",
    }

    def _go_to_declaration(self):
        """
        Go to Declaration or Find Usages for the word under the cursor.

        If the cursor is on a definition (class/def/proc), searches the
        workspace for all **usages** of that symbol.  If the cursor is
        on a usage, searches for the symbol's **definition**.

        Single result: navigates directly.
        Multiple results: shows a ``GoToDeclarationPopup``.
        """
        editor = self._current_editor()
        if not editor:
            self._show_status("No active editor")
            return

        # Get the word under the cursor.  WordUnderCursor can sometimes
        # grab punctuation (e.g. "():" if the cursor is on parentheses),
        # so we validate the result is a valid identifier.
        cursor = editor.textCursor()

        # Save the original column BEFORE WordUnderCursor moves the
        # cursor position to the end of the selection.
        original_col = cursor.positionInBlock()

        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()

        # If the selection isn't a clean identifier, try extracting one
        # from the line text at the original cursor position instead.
        if not word or not re.match(r'^[A-Za-z_]\w*$', word):
            line_text = cursor.block().text()
            col = original_col
            # Walk backward to find the start of the identifier.
            start = col
            while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == '_'):
                start -= 1
            # Walk forward to find the end.
            end = col
            while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == '_'):
                end += 1
            word = line_text[start:end].strip()

        if not word or not re.match(r'^[A-Za-z_]\w*$', word):
            self._show_status("No symbol under cursor")
            return

        # Determine whether cursor is on a definition or a usage.
        line_text = cursor.block().text()
        on_definition = self._is_on_definition(word, line_text)

        folders = self._get_workspace_folders()
        if not folders:
            self._show_status("No workspace folders — add one first")
            return

        # Use the background symbol index if it's ready (instant O(1) lookup).
        # Otherwise fall back to the synchronous filesystem scan.
        use_index = (self._symbol_index is not None and self._symbol_index.is_ready())

        if on_definition:
            # Cursor is on a definition — find all usages of this symbol.
            if use_index:
                results = self._symbol_index.find_usages(word)
            else:
                results = self._find_symbol_usages(word, folders)
            popup_title = "Usages of '{}'".format(word)
        else:
            # Cursor is on a usage — find the definition.
            if use_index:
                results = self._symbol_index.find_definitions(word)
            else:
                results = self._find_symbol_definition(word, folders)
            popup_title = "Definition of '{}'".format(word)

        if not results:
            if on_definition:
                self._show_status("No usages of '{}' found in workspace".format(word))
            else:
                self._show_status("No definition of '{}' found in workspace".format(word))
            return

        if len(results) == 1:
            # Single result — navigate directly.
            filepath, line_num, _ = results[0]
            self._navigate_to_file_line(filepath, line_num)
        else:
            # Multiple results — show popup.
            popup = GoToDeclarationPopup(self, results, self._navigate_to_file_line, popup_title)
            popup.exec()

    def _is_on_definition(self, word, line_text):
        """
        Check whether the given line contains a definition of *word*.

        Looks for Python ``class`` / ``def`` and MEL ``proc`` keywords
        preceding the symbol name on the same line.

        :param str word: The symbol name.
        :param str line_text: The full text of the current line.
        :return: True if the line defines the symbol.
        :rtype: bool
        """
        for pat_template in self._DEFINITION_PATTERNS:
            pat = pat_template.format(symbol=re.escape(word))
            if re.search(pat, line_text):
                return True
        return False

    def _find_symbol_definition(self, symbol, folders):
        """
        Search workspace files for definitions of *symbol*.

        Scans for ``class symbol``, ``def symbol``, and ``proc symbol``
        patterns across all workspace files.

        :param str symbol: The symbol name to find definitions for.
        :param list folders: Workspace folder paths.
        :return: List of (filepath, line_number, line_text) tuples.
        :rtype: list
        """
        # Build a combined regex matching any definition form.
        patterns = []
        for pat_template in self._DEFINITION_PATTERNS:
            patterns.append(pat_template.format(symbol=re.escape(symbol)))
        combined = "|".join("({})".format(p) for p in patterns)
        regex = re.compile(combined)

        return self._scan_files_for_patterns(regex, folders)

    def _find_symbol_usages(self, symbol, folders):
        """
        Search workspace files for usages of *symbol*.

        Uses a word-boundary regex to find all occurrences, excluding
        lines that are definitions of the symbol.

        :param str symbol: The symbol name to find usages for.
        :param list folders: Workspace folder paths.
        :return: List of (filepath, line_number, line_text) tuples.
        :rtype: list
        """
        # Match the symbol as a whole word.
        usage_regex = re.compile(r"\b" + re.escape(symbol) + r"\b")

        # Also compile definition patterns so we can exclude them.
        def_patterns = []
        for pat_template in self._DEFINITION_PATTERNS:
            def_patterns.append(re.compile(pat_template.format(symbol=re.escape(symbol))))

        all_matches = self._scan_files_for_patterns(usage_regex, folders)

        # Filter out lines that are definitions.
        results = []
        for filepath, line_num, line_text in all_matches:
            is_def = any(dp.search(line_text) for dp in def_patterns)
            if not is_def:
                results.append((filepath, line_num, line_text))

        return results

    def _scan_files_for_patterns(self, regex, folders):
        """
        Walk workspace folders and search each file for *regex* matches.

        Synchronous scan — suitable for small-to-medium workspaces.

        :param re.Pattern regex: Compiled regex to search for.
        :param list folders: Workspace folder paths to scan.
        :return: List of (filepath, line_number, line_text) tuples.
        :rtype: list
        """
        results = []

        for folder in folders:
            folder = os.path.normpath(folder)
            self._scan_dir(folder, folder, 0, regex, results)

        return results

    def _scan_dir(self, root, current, depth, regex, results):
        """
        Recursively scan a directory for regex matches in files.

        :param str root: Workspace root folder.
        :param str current: Current directory being scanned.
        :param int depth: Current recursion depth.
        :param re.Pattern regex: Compiled search regex.
        :param list results: Accumulator for (filepath, line_number, line_text) tuples.
        """
        if depth > self._DECL_MAX_DEPTH:
            return

        try:
            entries = os.listdir(current)
        except PermissionError:
            return

        for entry in sorted(entries):
            full_path = os.path.join(current, entry)

            if os.path.isdir(full_path):
                if entry in self._DECL_SKIP_DIRS:
                    continue
                self._scan_dir(root, full_path, depth + 1, regex, results)

            elif os.path.isfile(full_path):
                _, ext = os.path.splitext(entry)
                if ext.lower() in self._DECL_SKIP_EXTS:
                    continue
                self._scan_single_file(full_path, regex, results)

    def _scan_single_file(self, filepath, regex, results):
        """
        Search a single file line-by-line for regex matches.

        :param str filepath: Absolute path to the file.
        :param re.Pattern regex: Compiled search pattern.
        :param list results: Accumulator for (filepath, line_number, line_text) tuples.
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, start=1):
                    if regex.search(line):
                        results.append((filepath, i, line.rstrip("\n\r")))
        except (OSError, IOError):
            pass

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

    def _filtered_output(self, text):
        """
        Route adapter output through verbosity filtering before display.

        Used as the adapter output callback so that "minimal" mode
        suppresses normal stdout lines from the DCC.

        :param str text: Output text from a DCC adapter.
        """
        # Minimal verbosity suppresses normal stdout output.
        if self._verbosity_level == "minimal":
            return
        self._output.write_output(text)

    def _toggle_line_numbers_in_errors(self, checked):
        """
        Toggle whether error output includes source line numbers.

        :param bool checked: True to show line numbers, False to hide.
        """
        self._settings.set("line_numbers_in_errors", checked)
        self._show_status("Line numbers in errors: {}".format("on" if checked else "off"))

    def _toggle_stack_trace(self, checked):
        """
        Toggle full stack trace display in the output panel.

        :param bool checked: True to show full stack traces, False to hide.
        """
        self._settings.set("show_stack_trace", checked)
        self._show_status("Stack trace: {}".format("on" if checked else "off"))

    def _toggle_suppress_stack(self, checked):
        """
        Toggle suppression of the Maya stack trace popup window.

        :param bool checked: True to suppress the popup, False to allow.
        """
        self._settings.set("suppress_stack_window", checked)
        self._show_status("Suppress stack window: {}".format("on" if checked else "off"))

    def _write_output_to_file(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Write Output to File", "",
            "Text Files (*.txt);;Log Files (*.log);;All Files (*.*)"
        )
        if filepath:
            try:
                text = self._output.get_plain_text()
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
        """Open the Autodesk MEL Command Reference in the default browser."""
        webbrowser.open("https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Commands/")

    def _open_python_reference(self):
        """Open the Autodesk Maya Python Command Reference in the default browser."""
        webbrowser.open("https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/")

    def _open_node_reference(self):
        """Open the Autodesk Maya Node Reference in the default browser."""
        webbrowser.open("https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Nodes/")

    def _show_feedback_bug(self):
        """Open the feedback dialog pre-set to Bug Report."""
        from mca_qt.widgets.feedback_dialog import FeedbackDialog
        dialog = FeedbackDialog(app_version=_APP_VERSION, parent=self)
        # Pre-select "Bug Report" in the category combo.
        dialog._category_combo.setCurrentIndex(0)
        dialog.exec()

    def _show_feedback(self):
        """Open the feedback dialog pre-set to General Feedback."""
        from mca_qt.widgets.feedback_dialog import FeedbackDialog
        dialog = FeedbackDialog(app_version=_APP_VERSION, parent=self)
        # Pre-select "General Feedback" in the category combo.
        dialog._category_combo.setCurrentIndex(2)
        dialog.exec()

    def _show_licensing(self):
        """Open the new 3-tab licensing dialog from Help > Licensing."""
        from mca_qt.widgets.licensing_dialog import LicensingDialog
        LicensingDialog.open_from_menu(parent=self, settings=self._settings)

    def _show_about(self):
        """Display the About dialog with version and feature info."""
        # Tailor the tagline to the host DCC.
        if self._dcc_version and self._dcc_version.startswith("UE"):
            tagline = "A Python code editor for Unreal Engine."
        else:
            tagline = "A better Maya script editor."

        QMessageBox.about(
            self, "About MCA Editor",
            f"<h3>MCA Editor v{_APP_VERSION}</h3>"
            f"<p style='font-size: 11pt; color: #ccc;'>"
            f"{tagline}</p>"
            "<p><b>Features</b></p>"
            "<ul style='margin-top: 0;'>"
            "<li>Dual mode &mdash; Script Editor &amp; Project Mode</li>"
            "<li>AI integration (Orange Slice)</li>"
            "<li>Plugin architecture for extensions</li>"
            "</ul>"
            "<hr>"
            "<p style='color: #888;'>Built by Nathan Comes</p>"
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

        # Save individual panel sizes so they survive hide/show toggles.
        # If the panel is visible its current size is the right one to save;
        # if hidden, the size is 0 so we keep whatever was saved when it was
        # last hidden (already written by _hide_right_panel / _on_bottom_terminals_closed).
        main_sizes = self._main_splitter.sizes()
        if main_sizes[-1] > 0:
            settings.set("right_panel_width", main_sizes[-1])
        center_sizes = self._center_splitter.sizes()
        if len(center_sizes) >= 3 and center_sizes[2] > 0:
            settings.set("bottom_terminal_height", center_sizes[2])
        settings.set("sidebar_splitter_sizes", self._sidebar.splitter_sizes())

        # Panel visibility — use tracked instance vars instead of isVisible()
        # because the parent window may already be hidden during close,
        # which causes isVisible() to return False for all children.
        settings.set("output_visible", self._output_visible)
        settings.set("bottom_terminal_visible", self._bottom_terminal_panel.isVisible())
        settings.set("right_terminal_visible",
                      self._right_stripe.is_button_active("terminal"))
        settings.set("sidebar_visible", self._sidebar_visible)

        # Persist workspace folders (scripts/ or project root when active).
        folders = self._sidebar.workspace_panel.get_workspace_folders()
        settings.set("workspace_folders", folders)

        # Persist workspace tree expanded folders and selection.
        project_root = (self._active_project.project_root
                        if self._active_project else None)
        self._sidebar.workspace_panel.save_tree_state_to_settings(
            settings, project_root
        )

        settings.sync()

    def cleanup(self):
        """
        Clean up resources (called by host on close).

        Saves all temp buffer contents, the session manifest, and the
        output panel content so the editor can restore them on next launch.
        """
        # Save modified file-backed tabs to disk before shutting down.
        # Only writes tabs whose document has been modified to avoid
        # permission errors on read-only files that were just viewed.
        for editor, name, path in self._group_container.all_editors():
            if editor.file_path and editor.document().isModified():
                try:
                    # Clear OS read-only flag if set (Perforce, etc.)
                    if os.path.exists(editor.file_path) and not os.access(editor.file_path, os.W_OK):
                        os.chmod(editor.file_path, stat.S_IWRITE | stat.S_IREAD)
                    with open(editor.file_path, "w", encoding="utf-8") as f:
                        f.write(editor.toPlainText())
                except Exception as exc:
                    logger.warning("Failed to save tab on close: %s", exc)
            elif not path:
                self._save_buffer_content(editor)
        self._save_session_manifest()

        # Persist the output panel content so it survives restarts.
        output_text = self._output.get_plain_text()
        if output_text.strip():
            self._session_manager.save_output(output_text)

        # Persist workspace tree state so expanded folders survive restarts.
        project_root = (self._active_project.project_root
                        if self._active_project else None)
        self._sidebar.workspace_panel.save_tree_state_to_settings(
            self._settings, project_root
        )

        # Clean up all CodeCompleter instances before the widget tree is
        # destroyed.  Completers are created with parent=None (so they
        # float as tooltips) and install an app-level event filter on
        # QApplication.  If not removed here, the orphaned completers
        # survive shiboken6.delete() and cause ACCESS_VIOLATION during
        # Maya's atexit phase when Qt dispatches events through the
        # dangling filter references.
        for editor, _name, _path in self._group_container.all_editors():
            if hasattr(editor, "_completer") and editor._completer is not None:
                try:
                    editor._completer.cleanup()
                except Exception as exc:
                    logger.warning("Completer cleanup failed: %s", exc)

        # Unload all plugins before shutting down.
        if hasattr(self, "_plugin_manager") and self._plugin_manager:
            self._plugin_manager.unload_all()

        # Stop background symbol indexing before shutdown.
        self._stop_symbol_indexing()

        # Terminate all terminal processes in both panels.
        self._bottom_terminal_panel.cleanup()
        self._right_terminal_panel.cleanup()

        self._adapter_manager.disconnect_all()

        # Stop the API dispatch timer and shut down the JSON-RPC server.
        if hasattr(self, "_api_dispatch_timer"):
            self._api_dispatch_timer.stop()
        try:
            from mca_core.editor_api_server import stop_server
            stop_server()
        except Exception as exc:
            logger.warning("Failed to stop API server: %s", exc)

        logger.info("MCA Editor panel cleaning up")
