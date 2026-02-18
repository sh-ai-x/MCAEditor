"""
MCA Editor - Settings Dialog.

Full-featured settings/preferences dialog with a category list on the left
and stacked content pages on the right.  Mirrors the layout and options of
Charcoal Editor 2's Preferences window, re-branded as "Settings".

Pages:
    General, Keyboard, Tabs and Spacing, Fonts and Colors,
    Code Editor, Output, MEL, Python, Pylint

Dependencies:
    - PySide6 (QDialog, QListWidget, QStackedWidget, etc.)

Side Effects:
    - Reads and writes to MCASettings on Apply / OK.
"""

import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QListWidget,
    QStackedWidget, QGroupBox, QCheckBox, QSpinBox, QComboBox,
    QLabel, QLineEdit, QPushButton, QListWidgetItem, QFileDialog,
    QAbstractItemView, QFontComboBox, QTextEdit,
    Qt, QSize, Signal, QKeyCombination,
    QFont, QFontDatabase, QKeySequence,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Minimum dialog dimensions -----------------------------------------------

DIALOG_MIN_WIDTH = 720
DIALOG_MIN_HEIGHT = 520


# =============================================================================
# Shortcut Recorder Widget
# =============================================================================

class ShortcutRecorderWidget(QLineEdit):
    """
    Custom line edit that captures key combinations when focused.

    When the user presses a key combo (e.g. Ctrl+Shift+F), this widget
    displays the human-readable string and emits ``shortcutRecorded``
    with the corresponding QKeySequence.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when a valid shortcut is captured.
    shortcutRecorded = Signal(QKeySequence)

    def __init__(self, parent=None):
        """
        Initialize the shortcut recorder.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Click here, then press a key combination...")
        self._recorded_sequence = QKeySequence()

    def keyPressEvent(self, event):
        """
        Capture the key + modifiers and display them as a shortcut string.

        Ignores bare modifier keys (Shift, Ctrl, Alt, Meta) since they
        are not complete shortcuts by themselves.

        :param QKeyEvent event: The key press event.
        """
        key = event.key()

        # Ignore standalone modifier keys — wait for the actual key.
        modifier_keys = (
            Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
            Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
        )
        if key in modifier_keys:
            return

        # Combine modifiers with the pressed key.
        modifiers = event.modifiers()

        # Build the key combination using QKeyCombination (PySide6 / Qt6).
        key_combo = QKeyCombination(modifiers, Qt.Key(key))

        # Create the sequence and display it.
        seq = QKeySequence(key_combo)
        self._recorded_sequence = seq
        self.setText(seq.toString(QKeySequence.SequenceFormat.NativeText))

        # Let listeners know a shortcut was captured.
        self.shortcutRecorded.emit(seq)

    def recorded_sequence(self):
        """
        Return the most recently recorded QKeySequence.

        :return: The captured key sequence, or an empty sequence.
        :rtype: QKeySequence
        """
        return self._recorded_sequence

    def clear_recorded(self):
        """Clear the recorded shortcut and the display text."""
        self._recorded_sequence = QKeySequence()
        self.clear()


# =============================================================================
# Settings Dialog
# =============================================================================

class SettingsDialog(QDialog):
    """
    Application-wide settings dialog.

    Layout::

        +--------+-------------------------------+
        | List   |  Stacked pages                |
        | panel  |  (one per category)           |
        |        |                               |
        |        |                               |
        +--------+-------------------------------+
        |            Apply | OK | Cancel         |
        +--------------------------------------------+

    :param MCASettings settings: The application settings manager.
    :param QWidget parent: Optional parent widget.
    """

    # Ordered list of category names shown in the left panel.
    CATEGORIES = [
        "General",
        "Keyboard",
        "Tabs and Spacing",
        "Fonts and Colors",
        "Code Editor",
        "Output",
        "MEL",
        "Python",
        "Pylint",
    ]

    def __init__(self, settings, action_registry=None, parent=None):
        """
        Initialize the settings dialog and populate all pages.

        :param MCASettings settings: Application settings instance.
        :param dict action_registry: Mapping of command name -> QAction
            from the main window, used by the Keyboard page.
        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._settings = settings

        # Action registry for the keyboard shortcut editor.
        # Keys are clean command names, values are live QAction objects.
        self._action_registry = action_registry or {}

        # Snapshot of original shortcuts so Restore Defaults can revert.
        self._default_shortcuts = {}
        for name, action in self._action_registry.items():
            self._default_shortcuts[name] = QKeySequence(action.shortcut())

        self.setWindowTitle("Settings")
        self.setMinimumSize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
        self.resize(750, 560)

        # Build the dialog layout.
        self._setup_ui()

        # Load current values from settings into all widgets.
        self._load_settings()

    # -----------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------

    def _setup_ui(self):
        """Build the top-level layout: category list + stacked pages + buttons."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # --- Top section: list + pages side-by-side ---
        body = QHBoxLayout()
        body.setSpacing(8)

        # Category list on the left.
        self._category_list = QListWidget()
        self._category_list.setFixedWidth(140)
        self._category_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Style the category list to match the dark Charcoal look.
        self._category_list.setStyleSheet(
            "QListWidget { background-color: #2d2d30; border: 1px solid #3f3f46; }"
            "QListWidget::item { padding: 5px 8px; color: #d0d0d0; }"
            "QListWidget::item:selected { background-color: #094771; color: #ffffff; }"
            "QListWidget::item:hover:!selected { background-color: #3e3e42; }"
        )

        # Populate the category list.
        for name in self.CATEGORIES:
            self._category_list.addItem(name)

        body.addWidget(self._category_list)

        # Stacked widget holds one page per category.
        self._pages = QStackedWidget()
        body.addWidget(self._pages, 1)

        root_layout.addLayout(body, 1)

        # --- Build each page and add to the stack ---
        self._build_general_page()
        self._build_keyboard_page()
        self._build_tabs_spacing_page()
        self._build_fonts_colors_page()
        self._build_code_editor_page()
        self._build_output_page()
        self._build_mel_page()
        self._build_python_page()
        self._build_pylint_page()

        # Connect list selection to page switching.
        self._category_list.currentRowChanged.connect(self._pages.setCurrentIndex)
        # Start on General page.
        self._category_list.setCurrentRow(0)

        # --- Bottom buttons: Apply | OK | Cancel ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedWidth(80)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._apply_btn)

        self._ok_btn = QPushButton("OK")
        self._ok_btn.setFixedWidth(80)
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedWidth(80)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        root_layout.addLayout(btn_layout)

    # =================================================================
    # Page Builders
    # =================================================================

    # --- General Page -------------------------------------------------

    def _build_general_page(self):
        """Build the General settings page (Main Window + Tab Bar groups)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # -- Main Window group --
        mw_group = QGroupBox("Main Window")
        mw_layout = QVBoxLayout(mw_group)
        mw_layout.setSpacing(6)

        # Row 1: two checkboxes side-by-side.
        row1 = QHBoxLayout()
        self._chk_save_on_execute = QCheckBox("Save all on execute")
        self._chk_save_on_exit = QCheckBox("Save all on exit")
        row1.addWidget(self._chk_save_on_execute)
        row1.addWidget(self._chk_save_on_exit)
        mw_layout.addLayout(row1)

        # Row 2: two checkboxes.
        row2 = QHBoxLayout()
        self._chk_check_modified = QCheckBox("Check for modified files")
        self._chk_override_script_editor = QCheckBox("Override Script Editor button")
        row2.addWidget(self._chk_check_modified)
        row2.addWidget(self._chk_override_script_editor)
        mw_layout.addLayout(row2)

        # Full-width checkboxes.
        self._chk_always_show = QCheckBox("Always show Code Editor and Output on startup")
        mw_layout.addWidget(self._chk_always_show)

        self._chk_confirm_close_buffer = QCheckBox(
            "Display confirmation dialog when closing an internal buffer"
        )
        mw_layout.addWidget(self._chk_confirm_close_buffer)

        self._chk_confirm_unsaved = QCheckBox(
            "Display unsaved files dialog when exiting"
        )
        mw_layout.addWidget(self._chk_confirm_unsaved)

        layout.addWidget(mw_group)

        # -- Tab Bar group --
        tb_group = QGroupBox("Tab Bar")
        tb_layout = QVBoxLayout(tb_group)
        tb_layout.setSpacing(6)

        # Row 1.
        tb_row1 = QHBoxLayout()
        self._chk_show_tab_bar = QCheckBox("Show Tab Bar")
        self._chk_show_close_btn = QCheckBox("Show close button on each tab")
        tb_row1.addWidget(self._chk_show_tab_bar)
        tb_row1.addWidget(self._chk_show_close_btn)
        tb_layout.addLayout(tb_row1)

        # Row 2.
        tb_row2 = QHBoxLayout()
        self._chk_mini_toolbar = QCheckBox("Show mini toolbar")
        self._chk_mouse_wheel_tabs = QCheckBox("Mouse wheel changes active tab")
        tb_row2.addWidget(self._chk_mini_toolbar)
        tb_row2.addWidget(self._chk_mouse_wheel_tabs)
        tb_layout.addLayout(tb_row2)

        self._chk_lock_tabs = QCheckBox("Lock tabs")
        tb_layout.addWidget(self._chk_lock_tabs)

        layout.addWidget(tb_group)
        layout.addStretch()

        self._pages.addWidget(page)

    # --- Keyboard Page ------------------------------------------------

    def _build_keyboard_page(self):
        """Build the Keyboard shortcuts page with action list and assignment controls."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # Action list showing all available commands from the registry.
        self._action_list = QListWidget()
        self._action_list.setStyleSheet(
            "QListWidget { background-color: #2d2d30; border: 1px solid #3f3f46; }"
            "QListWidget::item { padding: 3px 6px; color: #d0d0d0; }"
            "QListWidget::item:selected { background-color: #094771; color: #ffffff; }"
        )

        # Build the sorted list of command names from the action registry.
        self._keyboard_command_names = sorted(self._action_registry.keys())
        for cmd in self._keyboard_command_names:
            self._action_list.addItem(cmd)

        self._action_list.currentRowChanged.connect(self._on_keyboard_action_changed)
        layout.addWidget(self._action_list, 1)

        # -- Assigned Shortcut row --
        layout.addWidget(QLabel("Assigned Shortcut:"))
        sc_row = QHBoxLayout()
        self._shortcut_display = QComboBox()
        self._shortcut_display.setMinimumWidth(300)
        self._shortcut_display.setEnabled(False)  # Read-only display of current shortcut.
        sc_row.addWidget(self._shortcut_display, 1)

        self._remove_shortcut_btn = QPushButton("Remove")
        self._remove_shortcut_btn.setFixedWidth(80)
        self._remove_shortcut_btn.clicked.connect(self._on_remove_shortcut)
        sc_row.addWidget(self._remove_shortcut_btn)
        layout.addLayout(sc_row)

        # -- Press Shortcut Keys row --
        layout.addWidget(QLabel("Press Shortcut Keys:"))
        press_row = QHBoxLayout()
        self._shortcut_recorder = ShortcutRecorderWidget()
        self._shortcut_recorder.shortcutRecorded.connect(self._on_shortcut_recorded)
        press_row.addWidget(self._shortcut_recorder, 1)

        self._assign_btn = QPushButton("Assign")
        self._assign_btn.setFixedWidth(80)
        self._assign_btn.clicked.connect(self._on_assign_shortcut)
        press_row.addWidget(self._assign_btn)
        layout.addLayout(press_row)

        # -- Shortcut currently used by --
        layout.addWidget(QLabel("Shortcut currently used by:"))
        self._used_by_label = QLineEdit()
        self._used_by_label.setReadOnly(True)
        layout.addWidget(self._used_by_label)

        # Restore Defaults button.
        self._restore_defaults_btn = QPushButton("Restore Defaults")
        self._restore_defaults_btn.clicked.connect(self._on_restore_default_shortcuts)
        layout.addWidget(self._restore_defaults_btn)

        self._pages.addWidget(page)

    # --- Keyboard Page Handlers ---

    def _on_keyboard_action_changed(self, row):
        """
        Update the shortcut display when a different command is selected.

        Shows the currently assigned shortcut for the selected action
        in the Assigned Shortcut combo.

        :param int row: The selected row index in the command list.
        """
        self._shortcut_display.clear()
        self._shortcut_recorder.clear_recorded()
        self._used_by_label.clear()

        if row < 0 or row >= len(self._keyboard_command_names):
            return

        name = self._keyboard_command_names[row]
        action = self._action_registry.get(name)
        if not action:
            return

        # Show the current shortcut (or "None" if unassigned).
        shortcut = action.shortcut()
        if shortcut.isEmpty():
            self._shortcut_display.addItem("(none)")
        else:
            self._shortcut_display.addItem(
                shortcut.toString(QKeySequence.SequenceFormat.NativeText)
            )

    def _on_shortcut_recorded(self, sequence):
        """
        Check for conflicts when a new shortcut is recorded.

        Searches the action registry for any other command already
        using the recorded key combination and shows it in the
        "Shortcut currently used by" field.

        :param QKeySequence sequence: The newly recorded key sequence.
        """
        self._used_by_label.clear()

        if sequence.isEmpty():
            return

        seq_str = sequence.toString()

        # Find which (if any) existing action uses this shortcut.
        for name, action in self._action_registry.items():
            if action.shortcut().toString() == seq_str:
                self._used_by_label.setText(name)
                return

    def _on_assign_shortcut(self):
        """
        Assign the recorded shortcut to the currently selected command.

        If another command already uses this shortcut, that command's
        shortcut is removed first to prevent duplicates.
        """
        row = self._action_list.currentRow()
        if row < 0 or row >= len(self._keyboard_command_names):
            return

        sequence = self._shortcut_recorder.recorded_sequence()
        if sequence.isEmpty():
            return

        name = self._keyboard_command_names[row]
        target_action = self._action_registry.get(name)
        if not target_action:
            return

        seq_str = sequence.toString()

        # Remove the shortcut from any other action that currently owns it.
        for other_name, other_action in self._action_registry.items():
            if other_name != name and other_action.shortcut().toString() == seq_str:
                other_action.setShortcut(QKeySequence())
                logger.info("Removed shortcut '%s' from '%s'", seq_str, other_name)

        # Assign the new shortcut.
        target_action.setShortcut(sequence)
        logger.info("Assigned shortcut '%s' to '%s'", seq_str, name)

        # Refresh the display.
        self._on_keyboard_action_changed(row)

    def _on_remove_shortcut(self):
        """Remove the shortcut from the currently selected command."""
        row = self._action_list.currentRow()
        if row < 0 or row >= len(self._keyboard_command_names):
            return

        name = self._keyboard_command_names[row]
        action = self._action_registry.get(name)
        if not action:
            return

        action.setShortcut(QKeySequence())
        logger.info("Removed shortcut from '%s'", name)

        # Refresh the display.
        self._on_keyboard_action_changed(row)

    def _on_restore_default_shortcuts(self):
        """
        Restore all shortcuts to their original values.

        Uses the snapshot taken when the dialog was created.
        """
        for name, default_seq in self._default_shortcuts.items():
            action = self._action_registry.get(name)
            if action:
                action.setShortcut(default_seq)

        logger.info("All shortcuts restored to defaults")

        # Refresh the display for the currently selected item.
        row = self._action_list.currentRow()
        if row >= 0:
            self._on_keyboard_action_changed(row)

    # --- Tabs and Spacing Page ----------------------------------------

    def _build_tabs_spacing_page(self):
        """Build the Tabs and Spacing page (language selector, tab size, indent)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Language selector.
        lang_group = QGroupBox("Language")
        lang_layout = QVBoxLayout(lang_group)
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["Default", "MEL", "Python"])
        lang_layout.addWidget(self._lang_combo)
        layout.addWidget(lang_group)

        # Tab group.
        tab_group = QGroupBox("Tab")
        tab_layout = QVBoxLayout(tab_group)

        # Tab Size spinner.
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Tab Size:"))
        self._tab_size_spin = QSpinBox()
        self._tab_size_spin.setRange(1, 16)
        self._tab_size_spin.setFixedWidth(60)
        size_row.addWidget(self._tab_size_spin)
        size_row.addStretch()
        tab_layout.addLayout(size_row)

        self._chk_replace_tabs = QCheckBox("Replace tabs with spaces")
        tab_layout.addWidget(self._chk_replace_tabs)

        layout.addWidget(tab_group)

        # Indenting group.
        indent_group = QGroupBox("Indenting")
        indent_layout = QVBoxLayout(indent_group)
        self._chk_auto_indent = QCheckBox("Auto-indent")
        indent_layout.addWidget(self._chk_auto_indent)
        layout.addWidget(indent_group)

        layout.addStretch()
        self._pages.addWidget(page)

    # --- Fonts and Colors Page ----------------------------------------

    def _build_fonts_colors_page(self):
        """Build the Fonts and Colors page (font picker, display items, color pickers)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # "Show settings for" dropdown.
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Show settings for:"))
        self._fc_target_combo = QComboBox()
        self._fc_target_combo.addItems(["Code Editor", "Output"])
        top_row.addWidget(self._fc_target_combo, 1)
        self._fc_defaults_btn = QPushButton("Use Defaults")
        self._fc_defaults_btn.setFixedWidth(100)
        top_row.addWidget(self._fc_defaults_btn)
        layout.addLayout(top_row)

        # Font row.
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font:"))
        self._fc_font_combo = QFontComboBox()
        font_row.addWidget(self._fc_font_combo, 1)

        font_row.addWidget(QLabel("Size:"))
        self._fc_font_size = QComboBox()
        self._fc_font_size.setEditable(True)
        # Populate with common sizes.
        for sz in [7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24]:
            self._fc_font_size.addItem(str(sz))
        self._fc_font_size.setFixedWidth(60)
        font_row.addWidget(self._fc_font_size)
        layout.addLayout(font_row)

        # Show only fixed width checkbox.
        self._chk_fixed_width = QCheckBox("Show only fixed width")
        self._chk_fixed_width.stateChanged.connect(self._on_fixed_width_changed)
        layout.addWidget(self._chk_fixed_width)

        # Display items list + color pickers side-by-side.
        items_row = QHBoxLayout()
        items_row.setSpacing(12)

        # Display items list.
        self._display_items_list = QListWidget()
        self._display_items_list.setFixedWidth(220)
        self._display_items_list.setStyleSheet(
            "QListWidget { background-color: #2d2d30; border: 1px solid #3f3f46; }"
            "QListWidget::item { padding: 3px 6px; color: #d0d0d0; }"
            "QListWidget::item:selected { background-color: #094771; color: #ffffff; }"
        )
        # All the display item categories matching CE2.
        display_items = [
            "Plain Text", "Selected Text", "Matching Selection",
            "Find/Replace Selected", "Find/Replace Matching",
            "Find/Replace Selection", "Current Line", "Matching Braces",
            "Whitespaces", "Indentation Guides", "Line Numbers", "Gutter",
            "MEL Keywords", "MEL Commands", "MEL Strings",
            "Python Keywords", "Python Built-ins", "Python Strings",
            "Python Decorators", "Python Numbers", "Comments",
        ]
        for item_name in display_items:
            self._display_items_list.addItem(item_name)
        items_row.addWidget(self._display_items_list)

        # Right side: Foreground, Background, Bold/Italic/Underline, Sample.
        right_col = QVBoxLayout()
        right_col.setSpacing(6)

        # Foreground color.
        right_col.addWidget(QLabel("Foreground:"))
        self._fg_color_btn = QPushButton()
        self._fg_color_btn.setFixedSize(80, 24)
        self._fg_color_btn.setStyleSheet("background-color: #d0d0d0; border: 1px solid #555;")
        right_col.addWidget(self._fg_color_btn)

        # Background color.
        right_col.addWidget(QLabel("Background:"))
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setFixedSize(80, 24)
        self._bg_color_btn.setStyleSheet("background-color: #1e1e1e; border: 1px solid #555;")
        right_col.addWidget(self._bg_color_btn)

        # Bold / Italic / Underline checkboxes.
        style_row = QHBoxLayout()
        self._chk_bold = QCheckBox("Bold")
        self._chk_italic = QCheckBox("Italic")
        self._chk_underline = QCheckBox("Underline")
        style_row.addWidget(self._chk_bold)
        style_row.addWidget(self._chk_italic)
        style_row.addWidget(self._chk_underline)
        right_col.addLayout(style_row)

        # Sample preview.
        right_col.addWidget(QLabel("Sample:"))
        self._sample_preview = QLabel("ij = I:oO(0xB8l1);")
        self._sample_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sample_preview.setFixedHeight(40)
        self._sample_preview.setStyleSheet(
            "background-color: #1e1e1e; color: #d0d0d0; border: 1px solid #3f3f46;"
            "font-family: Consolas; font-size: 12px; padding: 8px;"
        )
        right_col.addWidget(self._sample_preview)

        right_col.addStretch()
        items_row.addLayout(right_col)

        layout.addLayout(items_row, 1)
        self._pages.addWidget(page)

    def _on_fixed_width_changed(self, state):
        """
        Filter the font combo to only show monospaced fonts when checked.

        :param int state: The checkbox state (Qt.CheckState value).
        """
        if state == Qt.CheckState.Checked.value:
            self._fc_font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        else:
            self._fc_font_combo.setFontFilters(QFontComboBox.FontFilter.AllFonts)

    # --- Code Editor Page ---------------------------------------------

    def _build_code_editor_page(self):
        """Build the Code Editor settings page (behavioral options)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        options_group = QGroupBox("Options")
        opt_layout = QVBoxLayout(options_group)
        opt_layout.setSpacing(6)

        self._chk_backspace_tab = QCheckBox("Backspace to tab stop")
        opt_layout.addWidget(self._chk_backspace_tab)

        self._chk_indent_guides = QCheckBox("Display Indentation Guides")
        opt_layout.addWidget(self._chk_indent_guides)

        self._chk_ctrl_wheel = QCheckBox("Ctrl+Mouse Wheel changes font size")
        opt_layout.addWidget(self._chk_ctrl_wheel)

        self._chk_limit_match = QCheckBox("Limit matching selection highlight to words")
        opt_layout.addWidget(self._chk_limit_match)

        layout.addWidget(options_group)
        layout.addStretch()
        self._pages.addWidget(page)

    # --- Output Page --------------------------------------------------

    def _build_output_page(self):
        """Build the Output settings page (buffer size, options, highlighting)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Buffer Size.
        buf_group = QGroupBox("Buffer Size")
        buf_layout = QHBoxLayout(buf_group)
        self._output_buffer_spin = QSpinBox()
        self._output_buffer_spin.setRange(100, 100000)
        self._output_buffer_spin.setSingleStep(500)
        self._output_buffer_spin.setFixedWidth(80)
        buf_layout.addWidget(self._output_buffer_spin)
        buf_layout.addStretch()
        layout.addWidget(buf_group)

        # Options group.
        opt_group = QGroupBox("Options")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setSpacing(6)

        self._chk_out_ctrl_wheel = QCheckBox("Ctrl+Mouse Wheel changes font size")
        opt_layout.addWidget(self._chk_out_ctrl_wheel)

        self._chk_out_limit_match = QCheckBox("Limit matching selection highlight to words")
        opt_layout.addWidget(self._chk_out_limit_match)

        self._chk_out_double_click = QCheckBox(
            "Double-click selection includes leading $ (e.g. MEL variables)"
        )
        opt_layout.addWidget(self._chk_out_double_click)

        self._chk_out_disable_echo = QCheckBox("Disable Echo All Commands on startup")
        opt_layout.addWidget(self._chk_out_disable_echo)

        self._chk_out_word_wrap = QCheckBox("Word wrap")
        opt_layout.addWidget(self._chk_out_word_wrap)

        layout.addWidget(opt_group)

        # Highlighting group.
        hl_group = QGroupBox("Highlighting")
        hl_layout = QVBoxLayout(hl_group)
        hl_layout.setSpacing(6)

        self._chk_enable_highlighting = QCheckBox("Enable Highlighting")
        hl_layout.addWidget(self._chk_enable_highlighting)

        # Highlighting items list with checkboxes.
        self._highlight_list = QListWidget()
        self._highlight_list.setStyleSheet(
            "QListWidget { background-color: #2d2d30; border: 1px solid #3f3f46; }"
            "QListWidget::item { padding: 3px 6px; color: #d0d0d0; }"
            "QListWidget::item:selected { background-color: #094771; color: #ffffff; }"
        )
        self._highlight_list.setFixedHeight(140)

        # Each highlight item is checkable to match CE2's toggleable list.
        highlight_items = [
            ("Errors (Python)", "output_highlight_errors_py"),
            ("Errors (MEL)", "output_highlight_errors_mel"),
            ("Warnings (Python)", "output_highlight_warnings_py"),
            ("Warnings (MEL)", "output_highlight_warnings_mel"),
            ("Results (Python)", "output_highlight_results_py"),
            ("Results (MEL)", "output_highlight_results_mel"),
        ]
        # Store mapping from list row to setting key for save/load.
        self._highlight_items_map = []
        for label, key in highlight_items:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._highlight_list.addItem(item)
            self._highlight_items_map.append(key)

        hl_layout.addWidget(self._highlight_list)
        layout.addWidget(hl_group)

        layout.addStretch()
        self._pages.addWidget(page)

    # --- MEL Page -----------------------------------------------------

    def _build_mel_page(self):
        """Build the MEL language settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # General group.
        gen_group = QGroupBox("General")
        gen_layout = QVBoxLayout(gen_group)
        gen_layout.setSpacing(6)

        self._chk_mel_errors = QCheckBox("Display errors and warnings")
        gen_layout.addWidget(self._chk_mel_errors)

        self._chk_mel_smart_indent = QCheckBox("Smart indent (requires auto-indent)")
        gen_layout.addWidget(self._chk_mel_smart_indent)

        self._chk_mel_indent_bracket = QCheckBox("Indent to bracket (requires auto-indent)")
        gen_layout.addWidget(self._chk_mel_indent_bracket)

        self._chk_mel_close_bracket = QCheckBox("Insert closing bracket")
        gen_layout.addWidget(self._chk_mel_close_bracket)

        self._chk_mel_close_quotes = QCheckBox("Insert closing quotes")
        gen_layout.addWidget(self._chk_mel_close_quotes)

        self._chk_mel_trim_ws = QCheckBox("Trim trailing whitespace on save")
        gen_layout.addWidget(self._chk_mel_trim_ws)

        self._chk_mel_newline = QCheckBox("Ensure newline at end of file on save")
        gen_layout.addWidget(self._chk_mel_newline)

        self._chk_mel_dollar = QCheckBox("Double-click selection includes leading $")
        gen_layout.addWidget(self._chk_mel_dollar)

        self._chk_mel_ac_quickhelp = QCheckBox("Auto-complete updates Quick Help")
        gen_layout.addWidget(self._chk_mel_ac_quickhelp)

        layout.addWidget(gen_group)

        # Auto-Complete group.
        ac_group = QGroupBox("Auto-Complete")
        ac_layout = QHBoxLayout(ac_group)

        self._chk_mel_ac_ctrl = QCheckBox("CTRL + Space")
        ac_layout.addWidget(self._chk_mel_ac_ctrl)

        self._chk_mel_ac_letters = QCheckBox("On letters and '_'")
        ac_layout.addWidget(self._chk_mel_ac_letters)

        layout.addWidget(ac_group)

        layout.addStretch()
        self._pages.addWidget(page)

    # --- Python Page --------------------------------------------------

    def _build_python_page(self):
        """Build the Python language settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # General group.
        gen_group = QGroupBox("General")
        gen_layout = QVBoxLayout(gen_group)
        gen_layout.setSpacing(6)

        self._chk_py_errors = QCheckBox("Display errors and warnings")
        gen_layout.addWidget(self._chk_py_errors)

        self._chk_py_smart_indent = QCheckBox("Smart indent (requires auto-indent)")
        gen_layout.addWidget(self._chk_py_smart_indent)

        self._chk_py_indent_bracket = QCheckBox("Indent to bracket (requires auto-indent)")
        gen_layout.addWidget(self._chk_py_indent_bracket)

        self._chk_py_close_bracket = QCheckBox("Insert closing bracket")
        gen_layout.addWidget(self._chk_py_close_bracket)

        self._chk_py_close_quotes = QCheckBox("Insert closing quotes")
        gen_layout.addWidget(self._chk_py_close_quotes)

        self._chk_py_trim_ws = QCheckBox("Trim trailing whitespace on save")
        gen_layout.addWidget(self._chk_py_trim_ws)

        self._chk_py_newline = QCheckBox("Ensure newline at end of file on save")
        gen_layout.addWidget(self._chk_py_newline)

        self._chk_py_hide_pyc = QCheckBox("Hide .pyc files in workspace (__pycache__)")
        gen_layout.addWidget(self._chk_py_hide_pyc)

        self._chk_py_pymel = QCheckBox("Import PyMEL on load")
        gen_layout.addWidget(self._chk_py_pymel)

        self._chk_py_ac_quickhelp = QCheckBox("Auto-complete updates Quick Help")
        gen_layout.addWidget(self._chk_py_ac_quickhelp)

        self._chk_py_confirm_module = QCheckBox(
            "Show confirm dialog before overwriting Python module state"
        )
        gen_layout.addWidget(self._chk_py_confirm_module)

        self._chk_py_disable_revert = QCheckBox(
            'Disable "Revert Module State on Execute" on startup'
        )
        gen_layout.addWidget(self._chk_py_disable_revert)

        layout.addWidget(gen_group)

        # Auto-Complete group.
        ac_group = QGroupBox("Auto-Complete")
        ac_layout = QHBoxLayout(ac_group)

        self._chk_py_ac_ctrl = QCheckBox("CTRL + Space")
        ac_layout.addWidget(self._chk_py_ac_ctrl)

        self._chk_py_ac_letters = QCheckBox("On letters and '_'")
        ac_layout.addWidget(self._chk_py_ac_letters)

        self._chk_py_ac_dot = QCheckBox("On '.'")
        ac_layout.addWidget(self._chk_py_ac_dot)

        layout.addWidget(ac_group)

        # Auto-Complete Options group.
        aco_group = QGroupBox("Auto-Complete Options")
        aco_layout = QHBoxLayout(aco_group)

        self._chk_py_ac_keywords = QCheckBox("Include Keywords")
        aco_layout.addWidget(self._chk_py_ac_keywords)

        self._chk_py_ac_builtins = QCheckBox("Include Built-ins")
        aco_layout.addWidget(self._chk_py_ac_builtins)

        self._chk_py_native_maya = QCheckBox("Native Maya Fallback")
        aco_layout.addWidget(self._chk_py_native_maya)

        layout.addWidget(aco_group)

        # Forced Imports.
        fi_group = QGroupBox("Forced Imports")
        fi_layout = QVBoxLayout(fi_group)
        self._py_forced_imports = QLineEdit()
        self._py_forced_imports.setPlaceholderText("Comma-separated module names...")
        fi_layout.addWidget(self._py_forced_imports)
        layout.addWidget(fi_group)

        layout.addStretch()
        self._pages.addWidget(page)

    # --- Pylint Page --------------------------------------------------

    def _build_pylint_page(self):
        """Build the Pylint settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        # Pylint Code Analysis group.
        analysis_group = QGroupBox("Pylint Code Analysis")
        analysis_layout = QVBoxLayout(analysis_group)
        self._chk_pylint_enabled = QCheckBox("Enable Pylint")
        analysis_layout.addWidget(self._chk_pylint_enabled)
        layout.addWidget(analysis_group)

        # Executable Path group.
        exe_group = QGroupBox("Pylint Executable Path")
        exe_layout = QHBoxLayout(exe_group)
        self._pylint_exe_input = QLineEdit()
        self._pylint_exe_input.setPlaceholderText("Path to pylint executable...")
        exe_layout.addWidget(self._pylint_exe_input, 1)
        self._pylint_exe_browse = QPushButton("...")
        self._pylint_exe_browse.setFixedWidth(30)
        self._pylint_exe_browse.clicked.connect(self._browse_pylint_exe)
        exe_layout.addWidget(self._pylint_exe_browse)
        layout.addWidget(exe_group)

        # Configuration Path group.
        cfg_group = QGroupBox("Configuration Path (pylintrc)")
        cfg_layout = QHBoxLayout(cfg_group)
        self._pylint_cfg_input = QLineEdit()
        self._pylint_cfg_input.setPlaceholderText("Path to pylintrc file...")
        cfg_layout.addWidget(self._pylint_cfg_input, 1)
        self._pylint_cfg_browse = QPushButton("...")
        self._pylint_cfg_browse.setFixedWidth(30)
        self._pylint_cfg_browse.clicked.connect(self._browse_pylint_cfg)
        cfg_layout.addWidget(self._pylint_cfg_browse)
        self._pylint_cfg_default = QPushButton("Default")
        self._pylint_cfg_default.setFixedWidth(60)
        self._pylint_cfg_default.clicked.connect(lambda: self._pylint_cfg_input.clear())
        cfg_layout.addWidget(self._pylint_cfg_default)
        layout.addWidget(cfg_group)

        # Additional Python Paths group.
        paths_group = QGroupBox("Additional Python Paths")
        paths_layout = QVBoxLayout(paths_group)
        self._pylint_paths_input = QLineEdit()
        self._pylint_paths_input.setPlaceholderText("Semicolon-separated additional paths...")
        paths_layout.addWidget(self._pylint_paths_input)
        layout.addWidget(paths_group)

        # Options group.
        opts_group = QGroupBox("Options")
        opts_layout = QVBoxLayout(opts_group)
        opts_layout.setSpacing(6)

        self._chk_pylint_minimal = QCheckBox("Use minimal checkers (overrides pylintrc)")
        opts_layout.addWidget(self._chk_pylint_minimal)

        self._chk_pylint_log = QCheckBox("Log output errors (debug)")
        opts_layout.addWidget(self._chk_pylint_log)

        layout.addWidget(opts_group)
        layout.addStretch()
        self._pages.addWidget(page)

    def _browse_pylint_exe(self):
        """Open a file dialog to pick the Pylint executable path."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Pylint Executable", "", "All Files (*)"
        )
        if path:
            self._pylint_exe_input.setText(path)

    def _browse_pylint_cfg(self):
        """Open a file dialog to pick the Pylint configuration file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Pylint Configuration", "",
            "Config Files (*.cfg *.ini *.pylintrc);;All Files (*)"
        )
        if path:
            self._pylint_cfg_input.setText(path)

    # =================================================================
    # Load / Save Settings
    # =================================================================

    def _load_settings(self):
        """Populate all widgets from the current MCASettings values."""
        s = self._settings

        # --- General ---
        self._chk_save_on_execute.setChecked(s.get("auto_save_on_execute"))
        self._chk_save_on_exit.setChecked(s.get("save_all_on_exit"))
        self._chk_check_modified.setChecked(s.get("check_modified_files"))
        self._chk_override_script_editor.setChecked(s.get("override_script_editor"))
        self._chk_always_show.setChecked(s.get("always_show_editor_output"))
        self._chk_confirm_close_buffer.setChecked(s.get("confirm_close_buffer"))
        self._chk_confirm_unsaved.setChecked(s.get("confirm_unsaved_on_exit"))

        # Tab Bar.
        self._chk_show_tab_bar.setChecked(s.get("show_tab_bar"))
        self._chk_show_close_btn.setChecked(s.get("show_close_button_on_tab"))
        self._chk_mini_toolbar.setChecked(s.get("show_mini_toolbar"))
        self._chk_mouse_wheel_tabs.setChecked(s.get("mouse_wheel_changes_tab"))
        self._chk_lock_tabs.setChecked(s.get("lock_tabs"))

        # --- Tabs and Spacing ---
        self._tab_size_spin.setValue(s.get("tab_size"))
        self._chk_replace_tabs.setChecked(s.get("use_spaces"))
        self._chk_auto_indent.setChecked(s.get("auto_indent"))

        # --- Fonts and Colors ---
        font_family = s.get("font_family")
        self._fc_font_combo.setCurrentFont(QFont(font_family))
        self._fc_font_size.setCurrentText(str(s.get("font_size")))
        self._chk_fixed_width.setChecked(s.get("show_fixed_width_only"))

        # --- Code Editor ---
        self._chk_backspace_tab.setChecked(s.get("backspace_to_tab_stop"))
        self._chk_indent_guides.setChecked(s.get("show_indent_guides"))
        self._chk_ctrl_wheel.setChecked(s.get("ctrl_wheel_font_size"))
        self._chk_limit_match.setChecked(s.get("limit_match_highlight"))

        # --- Output ---
        self._output_buffer_spin.setValue(s.get("output_buffer_size"))
        self._chk_out_ctrl_wheel.setChecked(s.get("output_ctrl_wheel_font"))
        self._chk_out_limit_match.setChecked(s.get("output_limit_match_highlight"))
        self._chk_out_double_click.setChecked(s.get("output_double_click_dollar"))
        self._chk_out_disable_echo.setChecked(s.get("output_disable_echo_all"))
        self._chk_out_word_wrap.setChecked(s.get("output_word_wrap"))
        self._chk_enable_highlighting.setChecked(s.get("output_enable_highlighting"))

        # Load per-item highlighting toggles.
        for i, key in enumerate(self._highlight_items_map):
            checked = s.get(key)
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            self._highlight_list.item(i).setCheckState(state)

        # --- MEL ---
        self._chk_mel_errors.setChecked(s.get("mel_display_errors"))
        self._chk_mel_smart_indent.setChecked(s.get("mel_smart_indent"))
        self._chk_mel_indent_bracket.setChecked(s.get("mel_indent_to_bracket"))
        self._chk_mel_close_bracket.setChecked(s.get("mel_close_bracket"))
        self._chk_mel_close_quotes.setChecked(s.get("mel_close_quotes"))
        self._chk_mel_trim_ws.setChecked(s.get("mel_trim_whitespace"))
        self._chk_mel_newline.setChecked(s.get("mel_ensure_newline"))
        self._chk_mel_dollar.setChecked(s.get("mel_double_click_dollar"))
        self._chk_mel_ac_quickhelp.setChecked(s.get("mel_autocomplete_quickhelp"))
        self._chk_mel_ac_ctrl.setChecked(s.get("mel_autocomplete_ctrlspace"))
        self._chk_mel_ac_letters.setChecked(s.get("mel_autocomplete_on_letters"))

        # --- Python ---
        self._chk_py_errors.setChecked(s.get("py_display_errors"))
        self._chk_py_smart_indent.setChecked(s.get("py_smart_indent"))
        self._chk_py_indent_bracket.setChecked(s.get("py_indent_to_bracket"))
        self._chk_py_close_bracket.setChecked(s.get("py_close_bracket"))
        self._chk_py_close_quotes.setChecked(s.get("py_close_quotes"))
        self._chk_py_trim_ws.setChecked(s.get("py_trim_whitespace"))
        self._chk_py_newline.setChecked(s.get("py_ensure_newline"))
        self._chk_py_hide_pyc.setChecked(s.get("py_hide_pyc"))
        self._chk_py_pymel.setChecked(s.get("py_import_pymel"))
        self._chk_py_ac_quickhelp.setChecked(s.get("py_autocomplete_quickhelp"))
        self._chk_py_confirm_module.setChecked(s.get("py_confirm_overwrite_module"))
        self._chk_py_disable_revert.setChecked(s.get("py_disable_revert_module"))
        self._chk_py_ac_ctrl.setChecked(s.get("py_autocomplete_ctrlspace"))
        self._chk_py_ac_letters.setChecked(s.get("py_autocomplete_on_letters"))
        self._chk_py_ac_dot.setChecked(s.get("py_autocomplete_on_dot"))
        self._chk_py_ac_keywords.setChecked(s.get("py_autocomplete_keywords"))
        self._chk_py_ac_builtins.setChecked(s.get("py_autocomplete_builtins"))
        self._chk_py_native_maya.setChecked(s.get("py_native_maya_fallback"))
        self._chk_py_forced_imports = self._py_forced_imports  # alias for clarity
        self._py_forced_imports.setText(s.get("py_forced_imports"))

        # --- Pylint ---
        self._chk_pylint_enabled.setChecked(s.get("pylint_enabled"))
        self._pylint_exe_input.setText(s.get("pylint_executable"))
        self._pylint_cfg_input.setText(s.get("pylint_config"))
        self._pylint_paths_input.setText(s.get("pylint_additional_paths"))
        self._chk_pylint_minimal.setChecked(s.get("pylint_minimal_checkers"))
        self._chk_pylint_log.setChecked(s.get("pylint_log_errors"))

    def _save_settings(self):
        """Write all widget values back to MCASettings."""
        s = self._settings

        # --- General ---
        s.set("auto_save_on_execute", self._chk_save_on_execute.isChecked())
        s.set("save_all_on_exit", self._chk_save_on_exit.isChecked())
        s.set("check_modified_files", self._chk_check_modified.isChecked())
        s.set("override_script_editor", self._chk_override_script_editor.isChecked())
        s.set("always_show_editor_output", self._chk_always_show.isChecked())
        s.set("confirm_close_buffer", self._chk_confirm_close_buffer.isChecked())
        s.set("confirm_unsaved_on_exit", self._chk_confirm_unsaved.isChecked())

        # Tab Bar.
        s.set("show_tab_bar", self._chk_show_tab_bar.isChecked())
        s.set("show_close_button_on_tab", self._chk_show_close_btn.isChecked())
        s.set("show_mini_toolbar", self._chk_mini_toolbar.isChecked())
        s.set("mouse_wheel_changes_tab", self._chk_mouse_wheel_tabs.isChecked())
        s.set("lock_tabs", self._chk_lock_tabs.isChecked())

        # --- Tabs and Spacing ---
        s.set("tab_size", self._tab_size_spin.value())
        s.set("use_spaces", self._chk_replace_tabs.isChecked())
        s.set("auto_indent", self._chk_auto_indent.isChecked())

        # --- Fonts and Colors ---
        s.set("font_family", self._fc_font_combo.currentFont().family())
        # Parse font size, fall back to current if invalid.
        try:
            font_size = int(self._fc_font_size.currentText())
        except ValueError:
            font_size = s.get("font_size")
        s.set("font_size", font_size)
        s.set("show_fixed_width_only", self._chk_fixed_width.isChecked())

        # --- Code Editor ---
        s.set("backspace_to_tab_stop", self._chk_backspace_tab.isChecked())
        s.set("show_indent_guides", self._chk_indent_guides.isChecked())
        s.set("ctrl_wheel_font_size", self._chk_ctrl_wheel.isChecked())
        s.set("limit_match_highlight", self._chk_limit_match.isChecked())

        # --- Output ---
        s.set("output_buffer_size", self._output_buffer_spin.value())
        s.set("output_ctrl_wheel_font", self._chk_out_ctrl_wheel.isChecked())
        s.set("output_limit_match_highlight", self._chk_out_limit_match.isChecked())
        s.set("output_double_click_dollar", self._chk_out_double_click.isChecked())
        s.set("output_disable_echo_all", self._chk_out_disable_echo.isChecked())
        s.set("output_word_wrap", self._chk_out_word_wrap.isChecked())
        s.set("output_enable_highlighting", self._chk_enable_highlighting.isChecked())

        # Save per-item highlighting toggles.
        for i, key in enumerate(self._highlight_items_map):
            checked = self._highlight_list.item(i).checkState() == Qt.CheckState.Checked
            s.set(key, checked)

        # --- MEL ---
        s.set("mel_display_errors", self._chk_mel_errors.isChecked())
        s.set("mel_smart_indent", self._chk_mel_smart_indent.isChecked())
        s.set("mel_indent_to_bracket", self._chk_mel_indent_bracket.isChecked())
        s.set("mel_close_bracket", self._chk_mel_close_bracket.isChecked())
        s.set("mel_close_quotes", self._chk_mel_close_quotes.isChecked())
        s.set("mel_trim_whitespace", self._chk_mel_trim_ws.isChecked())
        s.set("mel_ensure_newline", self._chk_mel_newline.isChecked())
        s.set("mel_double_click_dollar", self._chk_mel_dollar.isChecked())
        s.set("mel_autocomplete_quickhelp", self._chk_mel_ac_quickhelp.isChecked())
        s.set("mel_autocomplete_ctrlspace", self._chk_mel_ac_ctrl.isChecked())
        s.set("mel_autocomplete_on_letters", self._chk_mel_ac_letters.isChecked())

        # --- Python ---
        s.set("py_display_errors", self._chk_py_errors.isChecked())
        s.set("py_smart_indent", self._chk_py_smart_indent.isChecked())
        s.set("py_indent_to_bracket", self._chk_py_indent_bracket.isChecked())
        s.set("py_close_bracket", self._chk_py_close_bracket.isChecked())
        s.set("py_close_quotes", self._chk_py_close_quotes.isChecked())
        s.set("py_trim_whitespace", self._chk_py_trim_ws.isChecked())
        s.set("py_ensure_newline", self._chk_py_newline.isChecked())
        s.set("py_hide_pyc", self._chk_py_hide_pyc.isChecked())
        s.set("py_import_pymel", self._chk_py_pymel.isChecked())
        s.set("py_autocomplete_quickhelp", self._chk_py_ac_quickhelp.isChecked())
        s.set("py_confirm_overwrite_module", self._chk_py_confirm_module.isChecked())
        s.set("py_disable_revert_module", self._chk_py_disable_revert.isChecked())
        s.set("py_autocomplete_ctrlspace", self._chk_py_ac_ctrl.isChecked())
        s.set("py_autocomplete_on_letters", self._chk_py_ac_letters.isChecked())
        s.set("py_autocomplete_on_dot", self._chk_py_ac_dot.isChecked())
        s.set("py_autocomplete_keywords", self._chk_py_ac_keywords.isChecked())
        s.set("py_autocomplete_builtins", self._chk_py_ac_builtins.isChecked())
        s.set("py_native_maya_fallback", self._chk_py_native_maya.isChecked())
        s.set("py_forced_imports", self._py_forced_imports.text())

        # --- Pylint ---
        s.set("pylint_enabled", self._chk_pylint_enabled.isChecked())
        s.set("pylint_executable", self._pylint_exe_input.text())
        s.set("pylint_config", self._pylint_cfg_input.text())
        s.set("pylint_additional_paths", self._pylint_paths_input.text())
        s.set("pylint_minimal_checkers", self._chk_pylint_minimal.isChecked())
        s.set("pylint_log_errors", self._chk_pylint_log.isChecked())

        # Flush to persistent storage.
        s.sync()
        logger.info("Settings saved")

    # =================================================================
    # Button Handlers
    # =================================================================

    def _on_apply(self):
        """Save settings without closing the dialog."""
        self._save_settings()

    def _on_ok(self):
        """Save settings and close the dialog."""
        self._save_settings()
        self.accept()
