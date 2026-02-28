"""
MCA Qt - Editor Group Widget.

Encapsulates a single tab group (QTabWidget + find bar overlay + tab nav
buttons + editor list).  Multiple EditorGroup instances live inside an
EditorGroupContainer to provide VS Code-style split editors.

The ``SplittableTabBar`` subclass initiates QDrag operations when a tab
is dragged far enough outside the bar. Drop zones and tab merging are
handled by the DragTabManager event filter and the DropZoneOverlay.

The tab bar also accepts drops from other groups — dropping on the bar
itself merges the tab into this group at the cursor position.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_qt.widgets.find_replace_bar (FindReplaceBar overlay)
"""

import json
import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QTabWidget, QTabBar,
    QPushButton, QMenu, QApplication,
    Qt, Signal, QEvent, QPoint, QTimer, QRect,
    QDrag, QMimeData, QByteArray, QPixmap, QColor, QPainter,
)
from mca_qt.widgets.find_replace_bar import FindReplaceBar

# Module-level logger.
logger = logging.getLogger(__name__)

# Distance in pixels the cursor must travel outside the tab bar
# vertically before initiating a QDrag operation.
DRAG_OUT_THRESHOLD = 20

# MIME type for tab drag payloads (shared with drag_tab_manager).
MCA_TAB_MIME_TYPE = "application/x-mca-editor-tab"


# =============================================================================
# Splittable Tab Bar
# =============================================================================

class SplittableTabBar(QTabBar):
    """
    Custom tab bar that initiates QDrag when a tab is dragged outside its bounds.

    Works alongside Qt's built-in ``setMovable(True)`` tab reordering.
    When the cursor exits the bar by more than ``DRAG_OUT_THRESHOLD``
    pixels vertically, a QDrag is started with MIME data identifying
    the source group and tab index. The drag is blocking — exec()
    returns when the user releases the mouse.

    The tab bar also accepts drops: when a tab from another group is
    dropped onto the bar, it is merged into this group at the cursor
    insertion position.

    Signals:
        drag_started(int): Emitted with the tab index when a QDrag begins.
            Used by the container to record the drag source.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when a QDrag is initiated from this tab bar.
    # Args: (tab_index,)
    drag_started = Signal(int)

    def __init__(self, parent=None):
        """
        Initialize the splittable tab bar.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        # Track the drag start state.
        self._drag_start_pos = None
        self._drag_tab_index = -1
        self._drag_triggered = False

        # Drop indicator position for when a tab is being dragged over us.
        # -1 means no indicator shown.
        self._drop_indicator_index = -1

        # Accept drops so tabs can be merged onto this bar.
        self.setAcceptDrops(True)

    # --- Mouse Events (drag initiation) --------------------------------------

    def mousePressEvent(self, event):
        """
        Record the drag start position and which tab was clicked.

        :param QMouseEvent event: The mouse press event.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_tab_index = self.tabAt(event.pos())
            self._drag_triggered = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Check if the cursor has moved far enough from the press point
        to initiate a QDrag operation.

        Uses manhattan distance from the press point so the drag triggers
        in any direction — horizontal, vertical, or diagonal. This means
        dragging a tab sideways to an adjacent panel works without having
        to drag down first.

        IMPORTANT: We intentionally do NOT call super().mouseMoveEvent()
        when we have a drag candidate. This prevents Qt's built-in
        movable-tab reorder from activating, which would change the tab
        index under us and cause the MIME payload to carry a stale index.
        All tab movement (reorder within the same bar AND split to other
        groups) goes through our QDrag + drop handler system instead.

        :param QMouseEvent event: The mouse move event.
        """
        # Only process left-button drags on a valid tab.
        if (self._drag_start_pos is not None
                and self._drag_tab_index >= 0
                and not self._drag_triggered):
            # Manhattan distance from the original press point.
            # This works in all directions — no need for the cursor
            # to leave the tab bar bounds.
            delta = event.pos() - self._drag_start_pos
            manhattan = abs(delta.x()) + abs(delta.y())

            if manhattan >= DRAG_OUT_THRESHOLD:
                self._drag_triggered = True
                tab_index = self._drag_tab_index

                # Reset tracking before starting drag (exec is blocking).
                self._drag_start_pos = None
                self._drag_tab_index = -1

                # Notify listeners that a drag is starting.
                self.drag_started.emit(tab_index)

                # Find the owning EditorGroup to get the group_id.
                editor_group = self._find_parent_editor_group()
                if editor_group is None:
                    return

                # Build the MIME payload.
                payload = json.dumps({
                    "source_group_id": editor_group.group_id(),
                    "tab_index": tab_index,
                })
                mime_data = QMimeData()
                mime_data.setData(
                    MCA_TAB_MIME_TYPE,
                    QByteArray(payload.encode("utf-8")),
                )

                # Create a small pixmap showing the tab text as drag cursor.
                drag_pixmap = self._create_drag_pixmap(tab_index)

                # Start the QDrag (this blocks until drop or cancel).
                drag = QDrag(self)
                drag.setMimeData(mime_data)
                drag.setPixmap(drag_pixmap)
                drag.exec(Qt.DropAction.MoveAction)
                return

            # Below threshold — suppress super() to prevent Qt's internal
            # tab reorder from activating and changing tab indices.
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """
        Reset the drag state on mouse release.

        :param QMouseEvent event: The mouse release event.
        """
        self._drag_start_pos = None
        self._drag_tab_index = -1
        self._drag_triggered = False
        super().mouseReleaseEvent(event)

    # --- Drop Events (tab merge onto bar) ------------------------------------

    def dragEnterEvent(self, event):
        """
        Accept tab drags entering this tab bar for merge operations.

        :param QDragEnterEvent event: The drag-enter event.
        """
        if event.mimeData() and event.mimeData().hasFormat(MCA_TAB_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """
        Track the insertion position as a tab is dragged over the bar.

        Updates the drop indicator so paintEvent can draw a blue line
        showing where the tab would be inserted.

        :param QDragMoveEvent event: The drag-move event.
        """
        if event.mimeData() and event.mimeData().hasFormat(MCA_TAB_MIME_TYPE):
            event.acceptProposedAction()
            # Figure out which tab slot the cursor is over.
            self._drop_indicator_index = self._insertion_index_at(event.pos())
            self.update()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        """
        Clear the drop indicator when the drag leaves the bar.

        :param QDragLeaveEvent event: The drag-leave event.
        """
        self._drop_indicator_index = -1
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """
        Handle a tab drop on the bar — merge into this group.

        :param QDropEvent event: The drop event.
        """
        mime = event.mimeData()
        if not mime or not mime.hasFormat(MCA_TAB_MIME_TYPE):
            super().dropEvent(event)
            return

        # Clear the indicator.
        insert_index = self._drop_indicator_index
        self._drop_indicator_index = -1
        self.update()

        # Parse the payload.
        try:
            raw = bytes(mime.data(MCA_TAB_MIME_TYPE)).decode("utf-8")
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        source_group_id = payload.get("source_group_id")
        tab_index = payload.get("tab_index")

        if source_group_id is None or tab_index is None:
            return

        event.acceptProposedAction()

        # Find the container and execute the merge.
        editor_group = self._find_parent_editor_group()
        if editor_group is None:
            return

        # Walk up to find the EditorGroupContainer.
        from mca_qt.widgets.editor_group_container import EditorGroupContainer
        container = editor_group.parentWidget()
        while container and not isinstance(container, EditorGroupContainer):
            container = container.parentWidget()
        if container is None:
            return

        # Find the source group.
        source_group = container.group_by_id(source_group_id)
        if source_group is None:
            return

        # Same-group reorder: check if the drop position is actually different.
        if source_group is editor_group:
            if insert_index < 0:
                return
            # insert_index == tab_index means "before this tab" (same spot).
            # insert_index == tab_index + 1 means "after this tab" (also same
            # effective position after removal shifts indices down).
            if insert_index == tab_index or insert_index == tab_index + 1:
                return

        # Take the editor from the source group.
        result = source_group.take_editor(tab_index)
        if result is None:
            return

        editor_widget, tab_name, file_path = result

        # Get icon for the editor.
        from mca_qt.icons import python_logo, maya_logo, text_icon
        lang = getattr(editor_widget, "language", "python")
        if lang in ("python", "py"):
            icon = python_logo()
        elif lang == "mel":
            icon = maya_logo()
        else:
            icon = text_icon()

        # Adjust insertion index for same-group reorder: after take_editor
        # removed the tab, all indices above it shifted down by one.
        if source_group is editor_group and insert_index > tab_index:
            insert_index -= 1

        # Clamp to valid range.
        if insert_index < 0:
            insert_index = editor_group.count()
        insert_index = min(insert_index, editor_group.count())

        # Use the QTabWidget's insertTab for positional insertion.
        tw = editor_group.tab_widget()
        actual_idx = tw.insertTab(insert_index, editor_widget, tab_name)
        if icon:
            tw.setTabIcon(actual_idx, icon)
        # Update internal tracking list.
        editor_group._editors.insert(actual_idx, (editor_widget, tab_name, file_path))
        tw.setCurrentIndex(actual_idx)
        editor_group.editors_changed.emit()

        # Set this group as active.
        container.set_active_group(editor_group)
        editor_widget.setFocus()

        logger.info("Merged tab '%s' into group at position %d", tab_name, actual_idx)

    # --- Paint (drop indicator) ----------------------------------------------

    def paintEvent(self, event):
        """
        Draw the standard tab bar plus a blue insertion indicator during
        drag-over operations.

        :param QPaintEvent event: The paint event.
        """
        super().paintEvent(event)

        # Draw the insertion indicator if a drag is in progress.
        if self._drop_indicator_index < 0:
            return

        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(30, 120, 220))

        # Compute the x position of the indicator line.
        x = self._insertion_x(self._drop_indicator_index)
        # Draw a thin vertical line (3px wide).
        indicator_rect = QRect(x - 1, 2, 3, self.height() - 4)
        painter.drawRect(indicator_rect)
        painter.end()

    # --- Utilities -----------------------------------------------------------

    def _find_parent_editor_group(self):
        """
        Walk up the widget tree to find the owning EditorGroup.

        :return: The parent EditorGroup, or None.
        :rtype: EditorGroup or None
        """
        from mca_qt.widgets.editor_group import EditorGroup
        parent = self.parentWidget()
        while parent:
            if isinstance(parent, EditorGroup):
                return parent
            parent = parent.parentWidget()
        return None

    def _insertion_index_at(self, pos):
        """
        Determine the tab insertion index for a given position.

        Returns the index where a new tab would be inserted if
        dropped at ``pos``. Based on which existing tab rect the
        cursor falls within (left half = before, right half = after).

        :param QPoint pos: Position in tab bar coordinates.
        :return: Insertion index.
        :rtype: int
        """
        for i in range(self.count()):
            rect = self.tabRect(i)
            # If cursor is in the left half, insert before this tab.
            if rect.contains(pos):
                if pos.x() < rect.center().x():
                    return i
                else:
                    return i + 1
        # Past all tabs — append at the end.
        return self.count()

    def _insertion_x(self, index):
        """
        Get the x pixel coordinate for drawing the insertion indicator.

        :param int index: The insertion index.
        :return: X coordinate.
        :rtype: int
        """
        if index <= 0:
            if self.count() > 0:
                return self.tabRect(0).left()
            return 0
        if index >= self.count():
            if self.count() > 0:
                return self.tabRect(self.count() - 1).right()
            return 0
        return self.tabRect(index).left()

    def _create_drag_pixmap(self, tab_index):
        """
        Create a small pixmap showing the tab text, used as the drag cursor.

        :param int tab_index: Index of the tab being dragged.
        :return: A pixmap representing the tab.
        :rtype: QPixmap
        """
        tab_text = self.tabText(tab_index)
        if not tab_text:
            tab_text = "Tab"

        # Create a simple text pixmap.
        from mca_qt.qt_compat import QFont
        font = self.font()
        from mca_qt.qt_compat import QPixmap as QP
        # Estimate size.
        width = max(80, len(tab_text) * 8 + 20)
        height = 28
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor(45, 45, 48, 200))

        painter = QPainter(pixmap)
        painter.setPen(QColor(204, 204, 204))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, tab_text)
        painter.end()

        return pixmap


# =============================================================================
# Editor Group
# =============================================================================

class EditorGroup(QWidget):
    """
    A single group of editor tabs.

    Encapsulates a QTabWidget (using SplittableTabBar), a FindReplaceBar
    overlay, tab navigation buttons, and the list of open editors.

    Signals:
        activated(): Emitted when any child widget gains focus.
        current_editor_changed(object): Emitted when the active tab changes.
        editors_changed(): Emitted when tabs are added or removed.
        empty(): Emitted when the last tab in the group is closed.
        cursor_position_changed(int, int): Forwarded from the active editor.
        drag_started(int): Forwarded from SplittableTabBar when a QDrag begins.
        split_requested(int): Emitted when "Split Right" context menu is chosen.
        split_left_requested(int): Emitted for "Split Left" context menu action.
        split_down_requested(int): Emitted for "Split Down" context menu action.
        split_up_requested(int): Emitted for "Split Up" context menu action.

    :param QWidget parent: Optional parent widget.
    """

    # --- Signals ---
    activated = Signal()
    current_editor_changed = Signal(object)
    editors_changed = Signal()
    empty = Signal()
    cursor_position_changed = Signal(int, int)
    drag_started = Signal(int)
    split_requested = Signal(int)
    split_left_requested = Signal(int)
    split_down_requested = Signal(int)
    split_up_requested = Signal(int)
    # Emitted when the user double-clicks empty space on the tab bar.
    new_tab_requested = Signal()

    def __init__(self, parent=None):
        """
        Initialize the editor group.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        # List of (editor, tab_name, file_path) tuples.
        self._editors = []
        self._setup_ui()
        self._setup_find_bar()

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the group layout: tab widget + overlay buttons."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create a QTabWidget with our custom SplittableTabBar.
        self._tab_widget = QTabWidget()
        self._splittable_bar = SplittableTabBar(self._tab_widget)
        self._tab_widget.setTabBar(self._splittable_bar)

        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.setUsesScrollButtons(True)
        self._tab_widget.setElideMode(Qt.TextElideMode.ElideNone)
        # Offset the tab bar to the right so overlay nav buttons don't overlap.
        self._tab_widget.setStyleSheet("QTabWidget::tab-bar { left: 60px; }")
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # Forward the drag_started signal from the custom tab bar.
        self._splittable_bar.drag_started.connect(self.drag_started.emit)

        # --- Tab bar overlay buttons ---
        _tab_btn_style = """
            QPushButton {{
                background: transparent;
                color: {color};
                border: none;
                border-radius: 3px;
                font-size: {size};
                font-weight: bold;
                padding: {padding};
            }}
            QPushButton:hover {{
                background-color: #3e3e42;
            }}
            QPushButton:pressed {{
                background-color: #094771;
            }}
        """

        # Left/right scroll arrows.
        self._scroll_left_btn = QPushButton("\u2039", self._tab_widget)
        self._scroll_left_btn.setToolTip("Scroll tabs left")
        self._scroll_left_btn.setFixedSize(28, 28)
        self._scroll_left_btn.setStyleSheet(_tab_btn_style.format(
            color="#999999", size="24px", padding="0 0 4px 0"))
        self._scroll_left_btn.clicked.connect(self._scroll_tabs_left)

        self._scroll_right_btn = QPushButton("\u203a", self._tab_widget)
        self._scroll_right_btn.setToolTip("Scroll tabs right")
        self._scroll_right_btn.setFixedSize(28, 28)
        self._scroll_right_btn.setStyleSheet(_tab_btn_style.format(
            color="#999999", size="24px", padding="0 0 4px 0"))
        self._scroll_right_btn.clicked.connect(self._scroll_tabs_right)

        # "..." tab list dropdown button.
        self._tab_list_btn = QPushButton("\u22ee", self._tab_widget)
        self._tab_list_btn.setToolTip("List all open tabs")
        self._tab_list_btn.setFixedSize(28, 28)
        self._tab_list_btn.setStyleSheet(_tab_btn_style.format(
            color="#999999", size="18px", padding="0"))
        self._tab_list_btn.clicked.connect(self._show_tab_list_menu)

        # Install event filter for double-click on empty tab bar space
        # and for resize-based overlay repositioning.
        self._tab_widget.tabBar().installEventFilter(self)
        self._tab_widget.installEventFilter(self)

        # Enable right-click context menu on the tab bar.
        self._tab_widget.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._tab_widget.tabBar().customContextMenuRequested.connect(
            self._show_tab_context_menu
        )

        layout.addWidget(self._tab_widget)

        # Position overlay buttons after the widget has its initial geometry.
        QTimer.singleShot(0, self._reposition_tab_nav_buttons)

    def _setup_find_bar(self):
        """
        Create the find/replace bar as an overlay inside the tab widget.

        The bar is a direct child of the QTabWidget and is positioned
        right below the tab bar using geometry management.
        """
        self._find_bar = FindReplaceBar(self._tab_widget)
        self._find_bar.search_selections_changed.connect(
            self._on_search_selections_changed
        )
        self._find_bar.closed.connect(self._on_find_bar_closed)
        self._find_bar.geometry_changed.connect(self._reposition_find_bar)
        self._find_bar.hide()

    # --- Public API ----------------------------------------------------------

    def group_id(self):
        """
        Return a unique identifier for this group instance.

        Uses Python's id() which is guaranteed unique for the lifetime
        of the object. Used in drag-and-drop MIME payloads.

        :return: Unique group identifier.
        :rtype: int
        """
        return id(self)

    def tab_widget(self):
        """
        Return the underlying QTabWidget.

        :return: The tab widget.
        :rtype: QTabWidget
        """
        return self._tab_widget

    def splittable_bar(self):
        """
        Return the custom SplittableTabBar.

        :return: The tab bar.
        :rtype: SplittableTabBar
        """
        return self._splittable_bar

    def add_editor(self, editor, tab_name, file_path, icon=None):
        """
        Add an editor tab to this group.

        :param MCACodeEditor editor: The editor widget.
        :param str tab_name: Display name for the tab.
        :param str file_path: File path (None for temp buffers).
        :param QIcon icon: Optional tab icon.
        :return: The new tab index.
        :rtype: int
        """
        idx = self._tab_widget.addTab(editor, tab_name)
        if icon:
            self._tab_widget.setTabIcon(idx, icon)
        self._editors.append((editor, tab_name, file_path))
        self._tab_widget.setCurrentIndex(idx)
        self.editors_changed.emit()
        return idx

    def take_editor(self, index):
        """
        Remove an editor from the group without closing it.

        Used when moving a tab between groups. The editor widget is
        reparented (removed from the tab widget) but NOT destroyed.

        :param int index: Tab index to remove.
        :return: Tuple of (editor, tab_name, file_path).
        :rtype: tuple
        """
        if index < 0 or index >= len(self._editors):
            return None

        editor, tab_name, file_path = self._editors[index]
        # Remove from tab widget (reparents widget out).
        self._tab_widget.removeTab(index)
        self._editors.pop(index)
        self.editors_changed.emit()

        # If the group is now empty, emit the empty signal.
        if len(self._editors) == 0:
            self.empty.emit()

        return (editor, tab_name, file_path)

    def remove_editor(self, index):
        """
        Close an editor at the given index. Does NOT prompt for save —
        the caller should handle save prompts before calling this.

        :param int index: Tab index to remove.
        """
        if index < 0 or index >= len(self._editors):
            return

        self._tab_widget.removeTab(index)
        self._editors.pop(index)
        self.editors_changed.emit()

        # If the group is now empty, emit the empty signal.
        if len(self._editors) == 0:
            self.empty.emit()

    def current_editor(self):
        """
        Return the currently active editor widget.

        :return: The active MCACodeEditor, or None.
        :rtype: MCACodeEditor or None
        """
        widget = self._tab_widget.currentWidget()
        # Use class-name check instead of isinstance() so this survives
        # plugin reloads.  After a reload the class object is re-created,
        # causing isinstance() to fail on editors from the prior load.
        if widget is not None and type(widget).__name__ == "MCACodeEditor":
            return widget
        return None

    def current_index(self):
        """
        Return the index of the currently active tab.

        :return: Current tab index.
        :rtype: int
        """
        return self._tab_widget.currentIndex()

    def set_current_index(self, index):
        """
        Set the currently active tab.

        :param int index: Tab index to activate.
        """
        self._tab_widget.setCurrentIndex(index)

    def editors(self):
        """
        Return the list of (editor, tab_name, file_path) tuples.

        :return: List of editor tuples.
        :rtype: list
        """
        return list(self._editors)

    def count(self):
        """
        Return the number of tabs in this group.

        :return: Tab count.
        :rtype: int
        """
        return self._tab_widget.count()

    def set_tab_text(self, index, text):
        """
        Set the display text for a tab.

        :param int index: Tab index.
        :param str text: New tab text.
        """
        self._tab_widget.setTabText(index, text)

    def set_tab_icon(self, index, icon):
        """
        Set the icon for a tab.

        :param int index: Tab index.
        :param QIcon icon: New icon.
        """
        self._tab_widget.setTabIcon(index, icon)

    def set_tab_tooltip(self, index, tooltip):
        """
        Set the tooltip for a tab.

        :param int index: Tab index.
        :param str tooltip: Tooltip text.
        """
        self._tab_widget.setTabToolTip(index, tooltip)

    def tab_text(self, index):
        """
        Get the display text for a tab.

        :param int index: Tab index.
        :return: Tab display text.
        :rtype: str
        """
        return self._tab_widget.tabText(index)

    def update_editor_entry(self, index, editor, tab_name, file_path):
        """
        Update the internal editor tracking entry at the given index.

        :param int index: Editor index.
        :param MCACodeEditor editor: Editor widget.
        :param str tab_name: Tab display name.
        :param str file_path: File path (or None).
        """
        if 0 <= index < len(self._editors):
            self._editors[index] = (editor, tab_name, file_path)

    def index_of_editor(self, editor):
        """
        Find the index of a specific editor in this group.

        :param MCACodeEditor editor: The editor to find.
        :return: Tab index, or -1 if not found.
        :rtype: int
        """
        for i, (e, _name, _path) in enumerate(self._editors):
            if e is editor:
                return i
        return -1

    def find_editor_by_path(self, filepath):
        """
        Find an editor by its file path.

        :param str filepath: The file path to search for.
        :return: Tuple of (index, editor) or (-1, None).
        :rtype: tuple
        """
        for i, (editor, _name, path) in enumerate(self._editors):
            if path == filepath:
                return (i, editor)
        return (-1, None)

    def block_signals(self, block):
        """
        Block or unblock signals on the underlying tab widget.

        :param bool block: True to block, False to unblock.
        """
        self._tab_widget.blockSignals(block)

    # --- Find Bar API --------------------------------------------------------

    def show_find(self, selected_text=""):
        """
        Show the find bar in find-only mode.

        :param str selected_text: Text to pre-fill in the search field.
        """
        editor = self.current_editor()
        if not editor:
            return
        self._find_bar.show_find(editor, selected_text)
        self._reposition_find_bar()

    def show_replace(self, selected_text=""):
        """
        Show the find bar in find+replace mode.

        :param str selected_text: Text to pre-fill in the search field.
        """
        editor = self.current_editor()
        if not editor:
            return
        self._find_bar.show_replace(editor, selected_text)
        self._reposition_find_bar()

    def find_bar(self):
        """
        Return the find bar widget.

        :return: The FindReplaceBar instance.
        :rtype: FindReplaceBar
        """
        return self._find_bar

    # --- Apply settings to all editors in this group -------------------------

    def apply_settings(self, settings):
        """
        Push settings to all editors in this group.

        :param MCASettings settings: Settings instance.
        """
        # Build the color scheme once and share across all editors.
        from mca_core.config.color_scheme import build_scheme_dict
        scheme = build_scheme_dict(settings)

        font_family = settings.get("font_family")
        font_size = settings.get("font_size")
        tab_size = settings.get("tab_size")
        for editor, _name, _path in self._editors:
            font = editor.font()
            font.setFamily(font_family)
            font.setPointSize(font_size)
            editor.setFont(font)
            editor.setTabStopDistance(
                editor.fontMetrics().horizontalAdvance(" ") * tab_size
            )
            # Push the color scheme so highlighters pick up any changes.
            editor.set_color_scheme(scheme)

        # Apply tab bar settings.
        self._tab_widget.tabBar().setVisible(settings.get("show_tab_bar"))
        self._tab_widget.setTabsClosable(settings.get("show_close_button_on_tab"))
        self._tab_widget.setMovable(not settings.get("lock_tabs"))

    # --- Internal Event Handling ---------------------------------------------

    def eventFilter(self, obj, event):
        """
        Event filter for focus detection, tab bar double-click, and resize.

        :param QObject obj: The object that generated the event.
        :param QEvent event: The event to filter.
        :return: True if the event was handled.
        :rtype: bool
        """
        # Double-click on empty tab bar space -> emit for new tab creation.
        if obj is self._tab_widget.tabBar():
            if event.type() == QEvent.Type.MouseButtonDblClick:
                tab_index = self._tab_widget.tabBar().tabAt(event.pos())
                if tab_index == -1:
                    self.new_tab_requested.emit()
                    return True

        # Reposition overlay widgets when the tab widget resizes.
        if obj is self._tab_widget and event.type() == QEvent.Type.Resize:
            self._reposition_find_bar()
            self._reposition_tab_nav_buttons()

        # Detect focus-in on any child widget to mark this group as active.
        if event.type() == QEvent.Type.FocusIn:
            self.activated.emit()

        return super().eventFilter(obj, event)

    def focusInEvent(self, event):
        """
        Emit activated when the group itself receives focus.

        :param QFocusEvent event: The focus event.
        """
        self.activated.emit()
        super().focusInEvent(event)

    def _on_tab_changed(self, index):
        """
        Handle tab selection changes within this group.

        :param int index: New active tab index.
        """
        editor = self.current_editor()
        if editor:
            # Re-search in the new tab if the find bar is open.
            if self._find_bar.isVisible():
                self._find_bar.set_editor(editor)
            self.current_editor_changed.emit(editor)

    def _on_tab_close_requested(self, index):
        """
        Handle the close button on a tab. Delegates to the panel
        by emitting editors_changed after removal. The panel wires
        this up to its save-prompt logic.

        We don't directly close here — the panel's _close_tab handles
        save prompts and cleanup. So we just forward the request.
        Since EditorGroup is inside the container, the container's
        host (editor_panel) connects tabCloseRequested indirectly.

        For simplicity, we let the tab widget's tabCloseRequested
        propagate — the panel listens via the container.

        :param int index: Tab index requested for close.
        """
        # This is wired at the panel level through the container.
        # The panel's _close_tab already handles save prompts.
        pass

    # --- Overlay Positioning -------------------------------------------------

    def _reposition_tab_nav_buttons(self):
        """
        Position scroll arrows and tab list button on the tab bar.
        """
        tab_bar = self._tab_widget.tabBar()
        bar_y = tab_bar.y()
        bar_h = tab_bar.height()

        # Left arrow.
        lw = self._scroll_left_btn.width()
        lh = self._scroll_left_btn.height()
        self._scroll_left_btn.move(2, bar_y + (bar_h - lh) // 2)
        self._scroll_left_btn.raise_()

        # Right arrow (next to left arrow).
        rh = self._scroll_right_btn.height()
        self._scroll_right_btn.move(2 + lw, bar_y + (bar_h - rh) // 2)
        self._scroll_right_btn.raise_()

        # "..." button on the far right.
        tw = self._tab_list_btn.width()
        th = self._tab_list_btn.height()
        x = self._tab_widget.width() - tw - 2
        self._tab_list_btn.move(x, bar_y + (bar_h - th) // 2)
        self._tab_list_btn.raise_()

    def _reposition_find_bar(self):
        """
        Position the overlay find bar right below the tab bar, right-aligned.
        """
        if not self._find_bar.isVisible():
            return

        tab_bar = self._tab_widget.tabBar()
        y_offset = (tab_bar.y() + tab_bar.height()) if tab_bar.isVisible() else 0

        bar_height = self._find_bar.sizeHint().height()
        parent_width = self._tab_widget.width()

        # Compact width: use sizeHint but cap between min and max bounds.
        min_bar_width = 450
        max_bar_width = 580
        bar_width = max(min_bar_width, min(max_bar_width, parent_width - 40))

        # Right-align with a small margin from the edge.
        right_margin = 8
        x_offset = parent_width - bar_width - right_margin

        self._find_bar.setGeometry(x_offset, y_offset, bar_width, bar_height)
        self._find_bar.raise_()

    # --- Tab Scrolling -------------------------------------------------------

    def _scroll_tabs_left(self):
        """Scroll the tab bar left via Qt's internal scroll button."""
        try:
            from PySide6.QtWidgets import QToolButton
        except ImportError:
            from PySide2.QtWidgets import QToolButton
        for child in self._tab_widget.findChildren(QToolButton):
            if child.objectName() == "ScrollLeftButton" and child.isVisible():
                child.click()
                return

    def _scroll_tabs_right(self):
        """Scroll the tab bar right via Qt's internal scroll button."""
        try:
            from PySide6.QtWidgets import QToolButton
        except ImportError:
            from PySide2.QtWidgets import QToolButton
        for child in self._tab_widget.findChildren(QToolButton):
            if child.objectName() == "ScrollRightButton" and child.isVisible():
                child.click()
                return

    # --- Tab List Menu -------------------------------------------------------

    def _show_tab_list_menu(self):
        """
        Show a dropdown menu listing all open tabs for quick navigation.
        """
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
            QMenu::indicator {
                width: 12px;
                height: 12px;
                margin-left: 4px;
            }
        """)

        current_idx = self._tab_widget.currentIndex()
        for i in range(self._tab_widget.count()):
            tab_text = self._tab_widget.tabText(i)
            action = menu.addAction(tab_text)
            action.setCheckable(True)
            action.setChecked(i == current_idx)
            action.triggered.connect(
                lambda _checked=None, idx=i: self._tab_widget.setCurrentIndex(idx)
            )

        menu.exec(self._tab_list_btn.mapToGlobal(
            self._tab_list_btn.rect().bottomLeft()
        ))

    # --- Tab Context Menu ----------------------------------------------------

    def _show_tab_context_menu(self, pos):
        """
        Show a context menu on right-click on the tab bar.

        Includes a "Split Editor" submenu with directional split options.

        :param QPoint pos: Position of the right-click in tab bar coords.
        """
        menu = QMenu(self)

        # Figure out which tab was right-clicked.
        clicked_index = self._tab_widget.tabBar().tabAt(pos)

        # --- Split submenu (only for valid tabs) ---
        if clicked_index >= 0:
            split_menu = menu.addMenu("Split Editor")
            split_right = split_menu.addAction("Split Right")
            split_left = split_menu.addAction("Split Left")
            split_down = split_menu.addAction("Split Down")
            split_up = split_menu.addAction("Split Up")

            split_right.triggered.connect(
                lambda: self.split_requested.emit(clicked_index)
            )
            split_left.triggered.connect(
                lambda: self.split_left_requested.emit(clicked_index)
            )
            split_down.triggered.connect(
                lambda: self.split_down_requested.emit(clicked_index)
            )
            split_up.triggered.connect(
                lambda: self.split_up_requested.emit(clicked_index)
            )
            menu.addSeparator()

        # --- File actions (only for file-backed tabs) ---
        has_file = False
        if 0 <= clicked_index < len(self._editors):
            _, _, tab_path = self._editors[clicked_index]
            has_file = tab_path is not None

        copy_path_action = menu.addAction("Copy Path")
        copy_path_action.setEnabled(has_file)
        if has_file:
            copy_path_action.triggered.connect(
                lambda: self._copy_tab_path(clicked_index)
            )

        menu.addSeparator()

        # --- Close actions ---
        close_action = menu.addAction("Close Tab")
        close_action.setEnabled(clicked_index >= 0)
        if clicked_index >= 0:
            # Emit the tabCloseRequested signal so the panel handles it.
            close_action.triggered.connect(
                lambda: self._tab_widget.tabCloseRequested.emit(clicked_index)
            )

        close_others_action = menu.addAction("Close Other Tabs")
        close_others_action.setEnabled(
            clicked_index >= 0 and self._tab_widget.count() > 1
        )

        close_all_action = menu.addAction("Close All Tabs")

        menu.exec(self._tab_widget.tabBar().mapToGlobal(pos))

    def _copy_tab_path(self, index):
        """
        Copy the file path of a tab to the system clipboard.

        :param int index: Tab index whose path to copy.
        """
        if index < 0 or index >= len(self._editors):
            return
        _, _, path = self._editors[index]
        if not path:
            return
        clipboard = QApplication.instance().clipboard()
        clipboard.setText(path)

    # --- Find Bar Signal Handlers --------------------------------------------

    def _on_search_selections_changed(self, selections):
        """
        Apply search-match highlights to the active editor.

        :param list selections: List of QTextEdit.ExtraSelection items.
        """
        editor = self.current_editor()
        if editor:
            editor.set_search_selections(selections)

    def _on_find_bar_closed(self):
        """Return focus to the editor when the find bar is dismissed."""
        editor = self.current_editor()
        if editor:
            editor.set_search_selections([])
            editor.setFocus()
