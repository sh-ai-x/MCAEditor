"""
MCA Qt - Drag Tab Manager.

Coordinates drag-and-drop tab splitting between EditorGroup instances.
Installed as an event filter on each EditorGroup to intercept drag-enter,
drag-move, drag-leave, and drop events. Owns a DropZoneOverlay for visual
feedback and executes tab moves/splits on drop.

MIME type ``application/x-mca-editor-tab`` carries a JSON payload with
the source group ID and tab index so the drop handler knows where the
tab came from.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_qt.widgets.drop_zone_overlay (DropZoneOverlay, DropZone)
"""

import json
import logging

from mca_qt.qt_compat import (
    QObject, QEvent, Qt,
)
from mca_qt.widgets.drop_zone_overlay import DropZoneOverlay, DropZone

# Module-level logger.
logger = logging.getLogger(__name__)

# Custom MIME type for MCA editor tab drags.
MCA_TAB_MIME_TYPE = "application/x-mca-editor-tab"


# =============================================================================
# Drag Tab Manager
# =============================================================================

class DragTabManager(QObject):
    """
    Event-filter-based coordinator for drag-and-drop tab splitting.

    Manages a single DropZoneOverlay instance and is installed as an
    event filter on each EditorGroup. When a tab is dragged (via QDrag
    from SplittableTabBar), this manager intercepts drag events on the
    target groups, shows/updates the overlay, and executes the tab
    move or split on drop.

    :param EditorGroupContainer container: The container that owns all groups.
    :param QObject parent: Optional parent QObject.
    """

    def __init__(self, container, parent=None):
        """
        Initialize the drag tab manager.

        :param EditorGroupContainer container: The owning container.
        :param QObject parent: Optional parent.
        """
        super().__init__(parent)
        self._container = container

        # The overlay is parented to the container so it can be positioned
        # over any child group widget.
        self._overlay = DropZoneOverlay(container)

    # --- Public API ----------------------------------------------------------

    def install_on_group(self, group):
        """
        Install this manager as an event filter on an EditorGroup so
        it can intercept drag-and-drop events.

        :param EditorGroup group: The group to monitor.
        """
        group.setAcceptDrops(True)
        group.installEventFilter(self)

    def uninstall_from_group(self, group):
        """
        Remove this manager's event filter from a group.

        :param EditorGroup group: The group to stop monitoring.
        """
        group.removeEventFilter(self)

    # --- Event Filter --------------------------------------------------------

    def eventFilter(self, obj, event):
        """
        Intercept drag-and-drop events on monitored EditorGroup widgets.

        :param QObject obj: The object that generated the event.
        :param QEvent event: The event to filter.
        :return: True if the event was consumed.
        :rtype: bool
        """
        event_type = event.type()

        # --- DragEnter: A drag entered an editor group ---
        if event_type == QEvent.Type.DragEnter:
            return self._handle_drag_enter(obj, event)

        # --- DragMove: Cursor moving within a group during drag ---
        if event_type == QEvent.Type.DragMove:
            return self._handle_drag_move(obj, event)

        # --- DragLeave: Drag left the group ---
        if event_type == QEvent.Type.DragLeave:
            return self._handle_drag_leave(obj, event)

        # --- Drop: Tab was dropped on a group ---
        if event_type == QEvent.Type.Drop:
            return self._handle_drop(obj, event)

        return False

    # --- Event Handlers (private) --------------------------------------------

    def _handle_drag_enter(self, group, event):
        """
        Handle drag-enter on an EditorGroup.

        Accept the event if the drag carries our MIME type, and show
        the drop zone overlay over the target group.

        :param EditorGroup group: The target group.
        :param QDragEnterEvent event: The drag-enter event.
        :return: True if handled.
        :rtype: bool
        """
        mime = event.mimeData()
        if mime and mime.hasFormat(MCA_TAB_MIME_TYPE):
            event.acceptProposedAction()
            # Show the overlay on this group.
            self._overlay.show_over(group)
            return True
        return False

    def _handle_drag_move(self, group, event):
        """
        Handle drag-move within an EditorGroup.

        Updates the overlay to highlight the zone under the cursor.

        :param EditorGroup group: The target group.
        :param QDragMoveEvent event: The drag-move event.
        :return: True if handled.
        :rtype: bool
        """
        mime = event.mimeData()
        if mime and mime.hasFormat(MCA_TAB_MIME_TYPE):
            event.acceptProposedAction()
            # Map event position to global coords for overlay hit-testing.
            global_pos = group.mapToGlobal(event.pos())
            self._overlay.update_cursor(global_pos)
            return True
        return False

    def _handle_drag_leave(self, group, event):
        """
        Handle drag-leave from an EditorGroup.

        Hides the overlay when the drag exits the group.

        :param EditorGroup group: The group being left.
        :param QDragLeaveEvent event: The drag-leave event.
        :return: True if handled.
        :rtype: bool
        """
        self._overlay.hide_overlay()
        return True

    def _handle_drop(self, group, event):
        """
        Handle a tab drop on an EditorGroup.

        Reads the MIME payload to find the source group and tab index,
        then executes the appropriate action based on the active drop zone.

        :param EditorGroup group: The target group.
        :param QDropEvent event: The drop event.
        :return: True if handled.
        :rtype: bool
        """
        mime = event.mimeData()
        if not mime or not mime.hasFormat(MCA_TAB_MIME_TYPE):
            return False

        # Parse the JSON payload.
        try:
            raw = bytes(mime.data(MCA_TAB_MIME_TYPE)).decode("utf-8")
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Invalid tab drag MIME data: %s", exc)
            self._overlay.hide_overlay()
            return False

        source_group_id = payload.get("source_group_id")
        tab_index = payload.get("tab_index")

        if source_group_id is None or tab_index is None:
            self._overlay.hide_overlay()
            return False

        # Find the source group by its id().
        source_group = self._container.group_by_id(source_group_id)
        if source_group is None:
            logger.warning("Drag source group not found: %s", source_group_id)
            self._overlay.hide_overlay()
            return False

        # Read the active zone from the overlay.
        zone = self._overlay.active_zone()
        self._overlay.hide_overlay()
        event.acceptProposedAction()

        # Execute the move based on which zone was targeted.
        if zone == DropZone.NONE:
            # Dropped outside any meaningful zone — do nothing.
            logger.debug("Tab dropped on NONE zone, ignoring")
            return True

        if zone == DropZone.CENTER:
            # Merge the tab into the target group.
            self._merge_tab(source_group, tab_index, group)
        elif zone == DropZone.RIGHT:
            self._split_tab(source_group, tab_index, group,
                            Qt.Orientation.Horizontal, before=False)
        elif zone == DropZone.LEFT:
            self._split_tab(source_group, tab_index, group,
                            Qt.Orientation.Horizontal, before=True)
        elif zone == DropZone.BOTTOM:
            self._split_tab(source_group, tab_index, group,
                            Qt.Orientation.Vertical, before=False)
        elif zone == DropZone.TOP:
            self._split_tab(source_group, tab_index, group,
                            Qt.Orientation.Vertical, before=True)

        return True

    # --- Tab Move Operations -------------------------------------------------

    def _merge_tab(self, source_group, tab_index, target_group):
        """
        Move a tab from one group to another (merge/combine).

        Takes the editor from the source group and adds it to the
        target group.

        :param EditorGroup source_group: The group to take the tab from.
        :param int tab_index: Index of the tab in the source group.
        :param EditorGroup target_group: The group to add the tab to.
        """
        # Don't merge into the same group.
        if source_group is target_group:
            logger.debug("Drop on same group CENTER — no-op")
            return

        result = source_group.take_editor(tab_index)
        if result is None:
            return

        editor, tab_name, file_path = result

        # Get the icon based on the editor's language.
        icon = self._get_editor_icon(editor)

        target_group.add_editor(editor, tab_name, file_path, icon)

        # Set the target as the active group.
        self._container.set_active_group(target_group)
        editor.setFocus()

        logger.info("Merged tab '%s' into target group", tab_name)

    def _split_tab(self, source_group, tab_index, target_group,
                   orientation, before):
        """
        Split a tab out of its group into a new group adjacent to the target.

        Takes the editor from the source, creates a new group via
        the container's split_group method, and adds the editor to it.

        :param EditorGroup source_group: The group to take the tab from.
        :param int tab_index: Index of the tab in the source group.
        :param EditorGroup target_group: The group to split relative to.
        :param Qt.Orientation orientation: Horizontal or Vertical.
        :param bool before: If True, insert the new group before the target.
        """
        result = source_group.take_editor(tab_index)
        if result is None:
            return

        editor, tab_name, file_path = result

        # Create a new group adjacent to the target.
        new_group = self._container.split_group(
            target_group, orientation, before
        )
        if new_group is None:
            # Fallback: re-add to source if split somehow failed.
            icon = self._get_editor_icon(editor)
            source_group.add_editor(editor, tab_name, file_path, icon)
            return

        # Add the editor to the newly created group.
        icon = self._get_editor_icon(editor)
        new_group.add_editor(editor, tab_name, file_path, icon)

        # Set the new group as active.
        self._container.set_active_group(new_group)
        editor.setFocus()

        direction = "before" if before else "after"
        orient_str = "H" if orientation == Qt.Orientation.Horizontal else "V"
        logger.info("Split tab '%s' %s target (%s)", tab_name, direction, orient_str)

    # --- Utility -------------------------------------------------------------

    def _get_editor_icon(self, editor):
        """
        Determine the appropriate tab icon for an editor based on its language.

        :param MCACodeEditor editor: The editor widget.
        :return: The icon for the editor's language.
        :rtype: QIcon
        """
        from mca_qt.icons import python_logo, maya_logo, text_icon

        lang = getattr(editor, "language", "python")
        if lang in ("python", "py"):
            return python_logo()
        elif lang == "mel":
            return maya_logo()
        else:
            return text_icon()
