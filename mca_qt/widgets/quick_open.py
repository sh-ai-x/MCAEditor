"""
MCA Qt - Quick Open Popups (VS Code-style).

Provides Go to File (Ctrl+P) and Go to Symbol (Ctrl+Shift+O) dialogs.
Each popup appears at the top-center of the parent window as a frameless
dark-themed dialog with a text filter field and a results list.

Classes:
    QuickOpenPopup  — abstract base (filter field + list + keyboard nav)
    GoToFilePopup   — recursive workspace file discovery
    GoToSymbolPopup — symbol navigation from get_code_outline()

Dependencies:
    - PySide6 (or PySide2 via qt_compat shim)
"""

import os
import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    Qt, QEvent, QPoint, QColor,
)

# --- Extra Qt imports for the custom item delegate --------------------------
# QStyledItemDelegate and QStyle are not in qt_compat (only used here).
try:
    from PySide6.QtWidgets import QStyledItemDelegate, QStyle
except ImportError:
    from PySide2.QtWidgets import QStyledItemDelegate, QStyle

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Fuzzy Matching ----------------------------------------------------------

def _fuzzy_match(pattern, text):
    """
    Test whether *pattern* is a fuzzy subsequence of *text*.

    Characters in the pattern must appear in order within the text,
    but not necessarily contiguously.  Case-insensitive.

    :param str pattern: The user's filter string.
    :param str text: The candidate string to match against.
    :return: True if pattern is a subsequence of text.
    :rtype: bool
    """
    pattern_lower = pattern.lower()
    text_lower = text.lower()
    p_idx = 0

    for ch in text_lower:
        if p_idx < len(pattern_lower) and ch == pattern_lower[p_idx]:
            p_idx += 1

    # All pattern characters were found in order.
    return p_idx == len(pattern_lower)


# --- Shared Stylesheet -------------------------------------------------------

# Dark theme matching the editor's completer and find/replace bar.
_QUICK_OPEN_STYLE = """
    QDialog {
        background-color: #252526;
        border: 1px solid #454545;
        border-radius: 4px;
    }
    QLineEdit {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 6px 8px;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 1px solid #007acc;
    }
    QListWidget {
        background-color: #252526;
        color: #d4d4d4;
        border: none;
        outline: none;
        font-size: 12px;
    }
    QListWidget::item {
        padding: 4px 8px;
    }
    QListWidget::item:selected {
        background-color: #094771;
        color: #ffffff;
    }
"""

# Maximum visible rows before scrolling.
_MAX_VISIBLE_ROWS = 12

# Popup width in pixels.
_POPUP_WIDTH = 550


# =============================================================================
# QuickOpenPopup (Base Class)
# =============================================================================

class QuickOpenPopup(QDialog):
    """
    Abstract base for VS Code-style quick-open popups.

    Subclasses must implement ``_get_items()`` and ``_on_confirm(item_data)``.

    Features:
        - Frameless, dark-themed dialog positioned at top-center of parent
        - QLineEdit filter + QListWidget results
        - Fuzzy subsequence matching (case-insensitive)
        - Keyboard: Escape=close, Enter=confirm, Up/Down=navigate

    :param QWidget parent: The parent window (used for positioning).
    :param str placeholder: Placeholder text for the filter field.
    """

    def __init__(self, parent, placeholder="Search..."):
        """
        Initialize the quick-open popup.

        :param QWidget parent: Parent window for positioning.
        :param str placeholder: Placeholder text for the filter field.
        """
        super().__init__(parent)

        # Popup window that auto-closes when the user clicks outside.
        # Popup grabs mouse/keyboard input so clicking anywhere else
        # dismisses it — no need for setModal().
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
        )

        # --- Build the layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Filter input field at the top.
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText(placeholder)
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._on_filter_changed)
        # Intercept Enter/Escape/Up/Down before QLineEdit handles them.
        self._filter_input.installEventFilter(self)
        layout.addWidget(self._filter_input)

        # Results list below the filter.
        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        self.setStyleSheet(_QUICK_OPEN_STYLE)
        self.setFixedWidth(_POPUP_WIDTH)

        # --- All items and their backing data ---
        # Each entry is a tuple: (display_text, search_text, item_data)
        self._all_items = []

    # --- Subclass Interface ---------------------------------------------------

    def _get_items(self):
        """
        Return the full list of items for the popup.

        Must be implemented by subclasses.

        :return: List of tuples (display_text, search_text, item_data).
            display_text — shown in the list widget.
            search_text  — matched against the filter (fuzzy).
            item_data    — arbitrary data passed to _on_confirm().
        :rtype: list
        """
        raise NotImplementedError

    def _on_confirm(self, item_data):
        """
        Called when the user confirms (Enter/double-click) a selected item.

        Must be implemented by subclasses.

        :param item_data: The data associated with the confirmed item.
        """
        raise NotImplementedError

    # --- Lifecycle ------------------------------------------------------------

    def exec(self):
        """
        Populate items, position the popup, and show it modally.

        :return: Dialog result code.
        :rtype: int
        """
        # Gather items from the subclass.
        self._all_items = self._get_items()

        # Show all items initially (no filter).
        self._populate_list(self._all_items)

        # Position at the top-center of the parent window.
        self._position_popup()

        # Focus the filter input so the user can type immediately.
        self._filter_input.setFocus()

        return super().exec()

    # --- Positioning ----------------------------------------------------------

    def _position_popup(self):
        """
        Center the popup horizontally at the top of the parent widget,
        with a small vertical offset (60px from top).

        Uses ``mapToGlobal()`` so the position is correct regardless
        of whether the parent is a top-level window or a docked panel
        inside Maya.
        """
        parent = self.parentWidget()
        if not parent:
            return

        # Get the parent's top-left corner in screen (global) coordinates.
        parent_global_tl = parent.mapToGlobal(QPoint(0, 0))
        parent_center_x = parent_global_tl.x() + parent.width() // 2
        popup_x = parent_center_x - self.width() // 2
        # 60px below the top of the parent widget.
        popup_y = parent_global_tl.y() + 60

        self.move(popup_x, popup_y)

    # --- Filtering ------------------------------------------------------------

    def _on_filter_changed(self, text):
        """
        Re-filter the item list when the user types in the filter field.

        :param str text: Current filter text.
        """
        if not text:
            # Show everything when the filter is empty.
            self._populate_list(self._all_items)
            return

        # Fuzzy match against the search_text of each item.
        filtered = [
            (display, search, data)
            for display, search, data in self._all_items
            if _fuzzy_match(text, search)
        ]
        self._populate_list(filtered)

    def _populate_list(self, items):
        """
        Fill the list widget with the given items and resize to fit.

        :param list items: List of (display_text, search_text, item_data) tuples.
        """
        self._list.clear()
        self._visible_items = items

        for display, _search, _data in items:
            list_item = QListWidgetItem(display)
            self._list.addItem(list_item)

        # Select the first item by default.
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

        # Resize popup height to fit visible rows (capped).
        row_count = min(self._list.count(), _MAX_VISIBLE_ROWS)
        if row_count == 0:
            row_count = 1  # Keep at least one row of height.
        row_height = self._list.sizeHintForRow(0) if self._list.count() > 0 else 24
        # Account for the filter input, margins, and border.
        list_height = row_count * row_height + 4
        # Total height = filter (~34px) + spacing + list + margins.
        total_height = 34 + 2 + list_height + 8
        self.setFixedHeight(total_height)

    # --- Confirmation ---------------------------------------------------------

    def _confirm_selection(self):
        """Confirm the currently selected item and close the popup."""
        row = self._list.currentRow()
        if row < 0 or row >= len(self._visible_items):
            return

        _display, _search, data = self._visible_items[row]
        # Navigate BEFORE closing the dialog.  Calling accept() first
        # hides the popup and returns focus to the parent, which can
        # trigger state changes (tab switches, focus handlers) that
        # make _current_editor() return the wrong widget.
        self._on_confirm(data)
        self.accept()

    def _on_item_double_clicked(self, list_item):
        """
        Handle double-click on a list item.

        :param QListWidgetItem list_item: The double-clicked item.
        """
        self._confirm_selection()

    # --- Keyboard Handling ----------------------------------------------------

    def eventFilter(self, obj, event):
        """
        Intercept key events on the filter input for navigation and confirm.

        - Up/Down: move selection in the list
        - Enter/Return: confirm the current selection
        - Escape: close the popup

        :param QObject obj: The watched object.
        :param QEvent event: The event.
        :return: True if the event was consumed.
        :rtype: bool
        """
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(obj, event)

        key = event.key()

        # Navigate up in the list.
        if key == Qt.Key.Key_Up:
            row = self._list.currentRow()
            if row > 0:
                self._list.setCurrentRow(row - 1)
            return True

        # Navigate down in the list.
        if key == Qt.Key.Key_Down:
            row = self._list.currentRow()
            if row < self._list.count() - 1:
                self._list.setCurrentRow(row + 1)
            return True

        # Confirm selection.
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_selection()
            return True

        # Close the popup.
        if key == Qt.Key.Key_Escape:
            self.reject()
            return True

        return super().eventFilter(obj, event)


# =============================================================================
# GoToFilePopup
# =============================================================================

# Import shared skip rules and depth limit from the central constants module.
from mca_qt.constants import SKIP_DIRS as _SKIP_DIRS, MAX_WALK_DEPTH as _MAX_DEPTH


class GoToFilePopup(QuickOpenPopup):
    """
    Go to File popup (Ctrl+P) — quick file opener by name.

    Recursively walks workspace folders to discover files, then presents
    them in a filterable list.  On confirm, opens the selected file.

    :param QWidget parent: Parent window.
    :param list workspace_folders: List of workspace folder paths to scan.
    :param callable open_callback: Function to call with the selected filepath.
    """

    def __init__(self, parent, workspace_folders, open_callback,
                 symbol_index=None):
        """
        Initialize the Go to File popup.

        :param QWidget parent: Parent window for positioning.
        :param list workspace_folders: Paths to scan for files.
        :param callable open_callback: Called with the absolute filepath on confirm.
        :param SymbolIndex symbol_index: Optional symbol index used to skip
            the filesystem walk — the popup builds its list from the index's
            cached file paths when the index is ready.
        """
        super().__init__(parent, placeholder="Go to File (type to filter)...")
        self._workspace_folders = workspace_folders
        self._open_callback = open_callback
        self._symbol_index = symbol_index

    def _get_items(self):
        """
        Build the candidate file list.

        Prefers the pre-built symbol index file list (fast path — no
        filesystem I/O) and falls back to a recursive walk when no
        index is ready.

        :return: List of (display_text, search_text, filepath) tuples.
        :rtype: list
        """
        items = []

        # Fast path: use the pre-built symbol index when it's ready.
        if (self._symbol_index is not None
                and self._symbol_index.is_ready()):
            index_files = self._symbol_index.get_all_files()
            items = self._items_from_files(index_files)
            logger.debug("GoToFilePopup: %d files from index", len(items))
        else:
            # Fallback: walk the filesystem (used before indexing finishes).
            seen = set()
            for folder in self._workspace_folders:
                folder = os.path.normpath(folder)
                self._walk_folder(folder, folder, 0, items, seen)
            logger.debug("GoToFilePopup: %d files from walk", len(items))

        # Sort by search text for consistent ordering.
        items.sort(key=lambda x: x[1].lower())
        return items

    def _items_from_files(self, file_paths):
        """
        Convert an absolute-path list into popup item tuples.

        Each file is displayed as "filename    relative/path" where the
        relative path is resolved against the first workspace folder the
        file lives under.

        :param list file_paths: Absolute file paths.
        :return: List of (display, search, abs_path) tuples.
        :rtype: list
        """
        # Normalize workspace folders once for fast prefix matching.
        norm_folders = [os.path.normpath(f) for f in self._workspace_folders]

        items = []
        for abs_path in file_paths:
            filename = os.path.basename(abs_path)

            # Find the matching workspace root for the relative display.
            rel_path = filename
            for folder in norm_folders:
                try:
                    if abs_path.startswith(folder):
                        rel_path = os.path.relpath(abs_path, folder)
                        break
                except ValueError:
                    # Different drive on Windows — skip.
                    continue

            display = "{}    {}".format(filename, rel_path)
            search_text = filename + " " + rel_path
            items.append((display, search_text, abs_path))

        return items

    def _walk_folder(self, root, current, depth, items, seen):
        """
        Recursively walk a directory tree and collect files.

        :param str root: The workspace root folder (for relative path display).
        :param str current: Current directory being scanned.
        :param int depth: Current recursion depth.
        :param list items: Accumulator for discovered (display, search, path) tuples.
        :param set seen: Set of absolute paths already seen (deduplication).
        """
        if depth > _MAX_DEPTH:
            return

        try:
            entries = os.listdir(current)
        except PermissionError:
            return

        for entry in entries:
            full_path = os.path.join(current, entry)

            if os.path.isdir(full_path):
                # Skip ignored directories.
                if entry in _SKIP_DIRS:
                    continue
                # Recurse into subdirectories.
                self._walk_folder(root, full_path, depth + 1, items, seen)

            elif os.path.isfile(full_path):
                abs_path = os.path.normpath(full_path)
                if abs_path in seen:
                    continue
                seen.add(abs_path)

                # Build display: "filename    relative/path"
                filename = os.path.basename(abs_path)
                rel_path = os.path.relpath(abs_path, root)
                display = "{}    {}".format(filename, rel_path)
                # Search against both filename and relative path.
                search_text = filename + " " + rel_path

                items.append((display, search_text, abs_path))

    def _on_confirm(self, item_data):
        """
        Open the confirmed file via the provided callback.

        :param str item_data: Absolute filepath to open.
        """
        logger.info("GoToFile: opening %s", item_data)
        self._open_callback(item_data)


# =============================================================================
# GoToSymbolPopup
# =============================================================================

# Symbol type prefixes for the display list.
_SYMBOL_PREFIXES = {
    "class": "[C]",
    "function": "[f]",
    "method": "[m]",
    "proc": "[p]",
}


class GoToSymbolPopup(QuickOpenPopup):
    """
    Go to Symbol popup (Ctrl+Shift+O) — jump to functions/classes in the
    current file.

    Takes outline data from ``editor.get_code_outline()`` and displays
    symbols in a filterable list.  On confirm, navigates to the symbol's
    line number.

    :param QWidget parent: Parent window.
    :param list outline: Outline data from get_code_outline().
    :param MCACodeEditor editor: The editor to navigate within.
    """

    def __init__(self, parent, outline, editor):
        """
        Initialize the Go to Symbol popup.

        :param QWidget parent: Parent window for positioning.
        :param list outline: List of outline dicts with 'type', 'name', 'line', 'indent'.
        :param MCACodeEditor editor: Editor to navigate to the selected symbol.
        """
        super().__init__(parent, placeholder="Go to Symbol (type to filter)...")
        self._outline = outline
        self._editor = editor

    def _get_items(self):
        """
        Convert outline data to popup items.

        :return: List of (display_text, search_text, line_number) tuples.
        :rtype: list
        """
        items = []

        for entry in self._outline:
            sym_type = entry.get("type", "function")
            name = entry.get("name", "")
            line = entry.get("line", 1)
            indent = entry.get("indent", 0)

            # Build a type prefix like [C], [f], [m].
            prefix = _SYMBOL_PREFIXES.get(sym_type, "[?]")

            # Indent nested symbols slightly for visual hierarchy.
            indent_str = "  " * indent
            display = "{}{}  {}    :{}".format(indent_str, prefix, name, line)
            # Search by name and type for flexible matching.
            search_text = name + " " + sym_type

            items.append((display, search_text, line))

        logger.debug("GoToSymbolPopup: %d symbols", len(items))
        return items

    def _on_confirm(self, item_data):
        """
        Navigate to the confirmed symbol's line.

        :param int item_data: Line number to jump to.
        """
        logger.info("GoToSymbol: jumping to line %d", item_data)
        self._editor.go_to_line(item_data)


# =============================================================================
# GoToDeclarationPopup — Custom Item Delegate
# =============================================================================

class _DeclarationItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for Go to Declaration list items.

    Paints each row as two aligned columns:
        1. **Location** (filename:line) in yellow, fixed-width
        2. **Code preview** in dim gray, filling the remaining space

    The fixed-width location column ensures all rows line up uniformly
    regardless of filename length.

    :param int location_col_width: Pixel width of the location column.
    :param QWidget parent: Parent widget (usually the QListWidget).
    """

    # VS Code-style yellow for identifiers / filenames.
    _LOCATION_COLOR = QColor("#dcdcaa")

    # Dim gray for the code preview text.
    _CODE_COLOR = QColor("#9a9a9a")

    # Selection highlight matching the popup stylesheet.
    _SELECTED_BG = QColor("#094771")

    def __init__(self, location_col_width, parent=None):
        """
        Initialize the delegate.

        :param int location_col_width: Pixel width reserved for the
            filename:line column (computed from the widest entry).
        :param QWidget parent: Parent widget.
        """
        super().__init__(parent)
        self._location_col_width = location_col_width

    def paint(self, painter, option, index):
        """
        Paint a single list row with colored, aligned columns.

        Reads ``(location_str, code_str)`` from ``Qt.UserRole`` on
        the item.  Falls back to the default delegate if no structured
        data is present.

        :param QPainter painter: The painter to draw with.
        :param QStyleOptionViewItem option: Style options for the item.
        :param QModelIndex index: Index of the item being painted.
        """
        painter.save()

        # Draw selection background when this row is highlighted.
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, self._SELECTED_BG)

        # Read the structured data stored in UserRole.
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            painter.restore()
            return super().paint(painter, option, index)

        location_text, code_text = data

        # Left padding matches the stylesheet's QListWidget::item padding.
        left_pad = 8

        # --- Location column (yellow) ---
        loc_rect = option.rect.adjusted(left_pad, 0, 0, 0)
        loc_rect.setWidth(self._location_col_width)
        painter.setPen(self._LOCATION_COLOR)
        painter.drawText(
            loc_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            location_text,
        )

        # --- Code preview column (gray) ---
        code_x = left_pad + self._location_col_width + 16
        code_rect = option.rect.adjusted(code_x, 0, -left_pad, 0)
        painter.setPen(self._CODE_COLOR)
        painter.drawText(
            code_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            code_text,
        )

        painter.restore()


# =============================================================================
# GoToDeclarationPopup
# =============================================================================

class GoToDeclarationPopup(QuickOpenPopup):
    """
    Go to Declaration / Find Usages popup (Ctrl+B).

    Shows a list of pre-computed results (definitions or usages) with
    file path, line number, and the matching line text.  On confirm,
    navigates to the selected location via the provided callback.

    Uses a custom delegate to render the filename:line in yellow with
    uniform column alignment across all rows.

    :param QWidget parent: Parent window.
    :param list results: List of (filepath, line_number, line_text) tuples.
    :param callable navigate_callback: ``fn(filepath, line_number)`` to open results.
    :param str title: Placeholder text describing what the popup shows.
    """

    def __init__(self, parent, results, navigate_callback, title="Go to Declaration"):
        """
        Initialize the Go to Declaration popup.

        :param QWidget parent: Parent window for positioning.
        :param list results: Pre-computed (filepath, line_number, line_text) tuples.
        :param callable navigate_callback: Called with (filepath, line_number) on confirm.
        :param str title: Placeholder / title text for the filter field.
        """
        super().__init__(parent, placeholder=title)
        self._results = results
        self._navigate_callback = navigate_callback

    def exec(self):
        """
        Compute column width from results and install the custom delegate
        before the base class populates the list.

        :return: Dialog result code.
        :rtype: int
        """
        # Measure the widest "filename:line" string to set a uniform
        # column width.  This runs before super().exec() which calls
        # _populate_list → _get_items.
        font_metrics = self._list.fontMetrics()
        max_loc_width = 0
        for filepath, line_num, _line_text in self._results:
            filename = os.path.basename(filepath)
            location = "{}:{}".format(filename, line_num)
            width = font_metrics.horizontalAdvance(location)
            if width > max_loc_width:
                max_loc_width = width

        # Install the delegate so it's active when items are painted.
        self._list.setItemDelegate(
            _DeclarationItemDelegate(max_loc_width, self._list)
        )

        return super().exec()

    def _get_items(self):
        """
        Convert pre-computed results to popup items.

        Item data includes the location and code strings so
        ``_populate_list`` can attach them to each QListWidgetItem
        for the custom delegate.

        :return: List of (display_text, search_text, item_data) tuples.
        :rtype: list
        """
        items = []

        for filepath, line_num, line_text in self._results:
            filename = os.path.basename(filepath)
            location = "{}:{}".format(filename, line_num)
            code = line_text.strip()[:120]

            # Display text is used for fuzzy filtering only (not painted
            # directly — the delegate reads from UserRole instead).
            display = "{}  {}".format(location, code)
            search_text = filename + " " + line_text

            # Pack location + code into item_data alongside the nav coords.
            items.append((display, search_text, (filepath, line_num, location, code)))

        return items

    def _populate_list(self, items):
        """
        Populate the list and attach structured data for the delegate.

        After the base class creates QListWidgetItems, this stores
        ``(location_str, code_str)`` in each item's UserRole so the
        custom delegate can paint the two-column layout.

        :param list items: Filtered (display, search, item_data) tuples.
        """
        super()._populate_list(items)

        # Attach structured display data to each list item.
        for i, (_display, _search, data) in enumerate(items):
            if i < self._list.count():
                _fp, _ln, location, code = data
                self._list.item(i).setData(
                    Qt.ItemDataRole.UserRole, (location, code)
                )

    def _on_confirm(self, item_data):
        """
        Navigate to the confirmed location.

        :param tuple item_data: (filepath, line_number, location, code) tuple.
        """
        filepath, line_num = item_data[0], item_data[1]
        logger.info("GoToDeclaration: navigating to %s:%d", filepath, line_num)
        self._navigate_callback(filepath, line_num)
