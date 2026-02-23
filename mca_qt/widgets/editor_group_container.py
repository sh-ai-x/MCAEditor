"""
MCA Qt - Editor Group Container.

Manages one or more EditorGroup instances in a recursive QSplitter tree,
providing VS Code / PyCharm-style split editors in any direction
(horizontal and vertical, nested arbitrarily deep).

When only one group exists, the UI looks identical to a single tab widget.
Dragging a tab to a drop zone or using "Split Editor" creates new groups
in the requested direction.  The splitter tree automatically simplifies
itself when groups are removed (single-child splitters collapse up).

Dependencies:
    - mca_qt.widgets.editor_group (EditorGroup)
    - mca_qt.widgets.drag_tab_manager (DragTabManager)
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QSplitter,
    Qt, Signal,
)
from mca_qt.widgets.editor_group import EditorGroup
from mca_qt.widgets.drag_tab_manager import DragTabManager

# Module-level logger.
logger = logging.getLogger(__name__)


# =============================================================================
# Editor Group Container
# =============================================================================

class EditorGroupContainer(QWidget):
    """
    Container that holds one or more EditorGroup instances in a
    recursive QSplitter tree (supports both horizontal and vertical splits).

    Tracks which group is "active" (has focus) and forwards editor
    change signals to the host panel.

    Signals:
        active_editor_changed(object): Emitted when the active editor
            changes (due to tab switch or group switch).
        editors_changed(): Emitted when any group's tab list changes.
        cursor_position_changed(int, int): Forwarded from active editor.
        tab_close_requested(object, int): Emitted when a tab close is
            requested. Args: (group, tab_index).

    :param QWidget parent: Optional parent widget.
    """

    # --- Signals ---
    active_editor_changed = Signal(object)
    editors_changed = Signal()
    cursor_position_changed = Signal(int, int)
    tab_close_requested = Signal(object, int)

    def __init__(self, parent=None):
        """
        Initialize the container with a single empty editor group.

        :param QWidget parent: Optional parent widget.
        """
        super().__init__(parent)
        self._groups = []
        self._active_group = None
        self._setup_ui()

        # The drag tab manager coordinates all drag-and-drop operations.
        self._drag_manager = DragTabManager(self)

        # Create the initial (default) group.
        self._create_group()

    # --- UI Setup ------------------------------------------------------------

    def _setup_ui(self):
        """Build the container layout with a root horizontal splitter."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Root splitter — starts horizontal, but nested splitters can be
        # any orientation.
        self._root_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._root_splitter)

    # --- Group Management ----------------------------------------------------

    def _create_group(self, parent_splitter=None):
        """
        Create a new EditorGroup and add it to a splitter.

        :param QSplitter parent_splitter: The splitter to add the group to.
            Defaults to the root splitter.
        :return: The newly created group.
        :rtype: EditorGroup
        """
        target_splitter = parent_splitter or self._root_splitter
        group = EditorGroup()
        self._groups.append(group)
        target_splitter.addWidget(group)

        # Wire group signals.
        group.activated.connect(lambda g=group: self._on_group_activated(g))
        group.current_editor_changed.connect(self._on_current_editor_changed)
        group.editors_changed.connect(self._on_editors_changed)
        group.empty.connect(lambda g=group: self._on_group_empty(g))

        # Wire split direction signals from context menu.
        group.split_requested.connect(
            lambda idx, g=group: self._on_split_right(g, idx)
        )
        group.split_left_requested.connect(
            lambda idx, g=group: self._on_split_left(g, idx)
        )
        group.split_down_requested.connect(
            lambda idx, g=group: self._on_split_down(g, idx)
        )
        group.split_up_requested.connect(
            lambda idx, g=group: self._on_split_up(g, idx)
        )

        # Forward tab close requests from the group's tab widget.
        group.tab_widget().tabCloseRequested.connect(
            lambda idx, g=group: self.tab_close_requested.emit(g, idx)
        )

        # Install the drag tab manager as event filter on the new group.
        self._drag_manager.install_on_group(group)

        # Set as active if it's the only group.
        if self._active_group is None:
            self._active_group = group

        logger.debug("Created editor group (total: %d)", len(self._groups))
        return group

    def _on_group_activated(self, group):
        """
        Handle a group gaining focus.

        :param EditorGroup group: The group that was activated.
        """
        if self._active_group is not group:
            self._active_group = group
            # Notify the host that the active editor may have changed.
            editor = group.current_editor()
            if editor:
                self.active_editor_changed.emit(editor)

    def _on_current_editor_changed(self, editor):
        """
        Forward the active editor change from the currently focused group.

        :param object editor: The newly active editor.
        """
        # Only forward if this came from the active group.
        sender_group = self.sender()
        if sender_group is self._active_group:
            self.active_editor_changed.emit(editor)

    def _on_editors_changed(self):
        """Forward editors_changed from any group."""
        self.editors_changed.emit()

    def _on_group_empty(self, group):
        """
        Remove an empty group from the splitter tree.

        If this was the last group, do NOT remove it — the panel
        will create a new buffer in it. After removal, simplifies
        the splitter tree to collapse single-child splitters.

        :param EditorGroup group: The empty group.
        """
        # Never remove the last group.
        if len(self._groups) <= 1:
            return

        # Find the parent splitter before removing.
        parent_splitter = group.parentWidget()

        # Remove the group from our list and the splitter.
        if group in self._groups:
            self._groups.remove(group)
            # Uninstall event filter before deletion.
            self._drag_manager.uninstall_from_group(group)
            group.setParent(None)
            group.deleteLater()
            logger.debug("Removed empty group (remaining: %d)", len(self._groups))

        # Simplify the splitter tree after removal.
        if isinstance(parent_splitter, QSplitter):
            self._simplify_splitter(parent_splitter)

        # If the active group was removed, switch to the first remaining.
        if self._active_group is group or self._active_group not in self._groups:
            self._active_group = self._groups[0] if self._groups else None
            if self._active_group:
                editor = self._active_group.current_editor()
                if editor:
                    self.active_editor_changed.emit(editor)

    # --- Split Direction Handlers (context menu) -----------------------------

    def _on_split_right(self, source_group, tab_index):
        """
        Split a tab to a new group to the right of the source.

        :param EditorGroup source_group: The group containing the tab.
        :param int tab_index: Index of the tab to split.
        """
        self._split_tab_from_group(
            source_group, tab_index, Qt.Orientation.Horizontal, before=False
        )

    def _on_split_left(self, source_group, tab_index):
        """
        Split a tab to a new group to the left of the source.

        :param EditorGroup source_group: The group containing the tab.
        :param int tab_index: Index of the tab to split.
        """
        self._split_tab_from_group(
            source_group, tab_index, Qt.Orientation.Horizontal, before=True
        )

    def _on_split_down(self, source_group, tab_index):
        """
        Split a tab to a new group below the source.

        :param EditorGroup source_group: The group containing the tab.
        :param int tab_index: Index of the tab to split.
        """
        self._split_tab_from_group(
            source_group, tab_index, Qt.Orientation.Vertical, before=False
        )

    def _on_split_up(self, source_group, tab_index):
        """
        Split a tab to a new group above the source.

        :param EditorGroup source_group: The group containing the tab.
        :param int tab_index: Index of the tab to split.
        """
        self._split_tab_from_group(
            source_group, tab_index, Qt.Orientation.Vertical, before=True
        )

    def _split_tab_from_group(self, source_group, tab_index, orientation, before):
        """
        Take a tab from source_group and split it into a new group.

        :param EditorGroup source_group: The group containing the tab.
        :param int tab_index: Index of the tab to move.
        :param Qt.Orientation orientation: Split direction.
        :param bool before: Insert before (left/top) or after (right/bottom).
        """
        result = source_group.take_editor(tab_index)
        if result is None:
            return

        editor, tab_name, file_path = result

        # Create a new group adjacent to the source.
        new_group = self.split_group(source_group, orientation, before)
        if new_group is None:
            # Re-add the editor if split failed.
            from mca_qt.icons import python_logo, maya_logo, text_icon
            lang = getattr(editor, "language", "python")
            icon = python_logo() if lang in ("python", "py") else (
                maya_logo() if lang == "mel" else text_icon()
            )
            source_group.add_editor(editor, tab_name, file_path, icon)
            return

        # Add the editor to the new group with the appropriate icon.
        from mca_qt.icons import python_logo, maya_logo, text_icon
        lang = getattr(editor, "language", "python")
        if lang in ("python", "py"):
            icon = python_logo()
        elif lang == "mel":
            icon = maya_logo()
        else:
            icon = text_icon()

        new_group.add_editor(editor, tab_name, file_path, icon)

        # Set the new group as active.
        self._active_group = new_group
        editor.setFocus()

        self.active_editor_changed.emit(editor)
        self.editors_changed.emit()

        logger.info("Split tab '%s' to new group", tab_name)

    # --- Core Split Logic (recursive splitter tree) --------------------------

    def split_group(self, target_group, orientation, before):
        """
        Create a new EditorGroup adjacent to target_group.

        This is the core splitting method. It handles two cases:

        1. The target's parent splitter already has the matching
           orientation: insert the new group adjacent to the target
           within that splitter.

        2. The parent splitter has a different orientation: wrap the
           target in a new nested splitter with the desired orientation,
           then insert the new group alongside.

        After splitting, sizes are equalized.

        :param EditorGroup target_group: The group to split relative to.
        :param Qt.Orientation orientation: Horizontal or Vertical.
        :param bool before: If True, insert new group before the target.
        :return: The newly created EditorGroup.
        :rtype: EditorGroup
        """
        parent_splitter = target_group.parentWidget()

        # Ensure the parent is actually a QSplitter.
        if not isinstance(parent_splitter, QSplitter):
            logger.warning("Target group parent is not a QSplitter")
            return None

        # Case 1: Parent splitter matches the desired orientation.
        if parent_splitter.orientation() == orientation:
            # Find the target's index within its parent splitter.
            target_idx = parent_splitter.indexOf(target_group)
            insert_idx = target_idx if before else target_idx + 1

            # Create a new group directly in this splitter.
            new_group = self._create_group_bare()
            parent_splitter.insertWidget(insert_idx, new_group)

            # Equalize sizes across all children.
            self._equalize_sizes(parent_splitter)

            return new_group

        # Case 2: Orientation mismatch — need to nest.
        # Save the target's index and the current sizes.
        target_idx = parent_splitter.indexOf(target_group)
        old_sizes = parent_splitter.sizes()

        # Create a new sub-splitter with the desired orientation.
        sub_splitter = QSplitter(orientation)

        # Insert the sub-splitter at the target's position.
        parent_splitter.insertWidget(target_idx, sub_splitter)

        # Move the target group into the sub-splitter.
        sub_splitter.addWidget(target_group)

        # Create the new group inside the sub-splitter.
        new_group = self._create_group_bare()
        if before:
            sub_splitter.insertWidget(0, new_group)
        else:
            sub_splitter.addWidget(new_group)

        # Equalize sizes within the sub-splitter.
        self._equalize_sizes(sub_splitter)

        # Restore the parent splitter's sizes (the sub-splitter takes
        # the same slot the target_group had).
        if old_sizes and len(old_sizes) == parent_splitter.count():
            parent_splitter.setSizes(old_sizes)

        return new_group

    def _create_group_bare(self):
        """
        Create a new EditorGroup with full signal wiring but without
        adding it to any splitter (caller handles placement).

        :return: The newly created group.
        :rtype: EditorGroup
        """
        group = EditorGroup()
        self._groups.append(group)

        # Wire group signals.
        group.activated.connect(lambda g=group: self._on_group_activated(g))
        group.current_editor_changed.connect(self._on_current_editor_changed)
        group.editors_changed.connect(self._on_editors_changed)
        group.empty.connect(lambda g=group: self._on_group_empty(g))

        # Wire split direction signals.
        group.split_requested.connect(
            lambda idx, g=group: self._on_split_right(g, idx)
        )
        group.split_left_requested.connect(
            lambda idx, g=group: self._on_split_left(g, idx)
        )
        group.split_down_requested.connect(
            lambda idx, g=group: self._on_split_down(g, idx)
        )
        group.split_up_requested.connect(
            lambda idx, g=group: self._on_split_up(g, idx)
        )

        # Forward tab close requests.
        group.tab_widget().tabCloseRequested.connect(
            lambda idx, g=group: self.tab_close_requested.emit(g, idx)
        )

        # Install drag manager.
        self._drag_manager.install_on_group(group)

        # Set as active if it's the only group.
        if self._active_group is None:
            self._active_group = group

        logger.debug("Created bare editor group (total: %d)", len(self._groups))
        return group

    def _equalize_sizes(self, splitter):
        """
        Set all children of a splitter to equal sizes.

        :param QSplitter splitter: The splitter to equalize.
        """
        count = splitter.count()
        if count <= 0:
            return
        total = sum(splitter.sizes()) or splitter.width() or 600
        equal = total // count
        splitter.setSizes([equal] * count)

    def _simplify_splitter(self, splitter):
        """
        Collapse single-child splitters up the tree.

        After a group is removed, a splitter may have only one child.
        That child should be promoted up to the grandparent splitter
        to avoid unnecessary nesting. Recurses up the tree.

        :param QSplitter splitter: The splitter to simplify.
        """
        # Don't simplify the root splitter even if it has 1 child.
        if splitter is self._root_splitter:
            return

        # If the splitter has more than one child, no simplification needed.
        if splitter.count() != 1:
            return

        # Get the single remaining child.
        child = splitter.widget(0)
        if child is None:
            return

        # Find the grandparent splitter.
        grandparent = splitter.parentWidget()
        if not isinstance(grandparent, QSplitter):
            return

        # Replace the splitter with its single child in the grandparent.
        splitter_idx = grandparent.indexOf(splitter)
        grandparent.insertWidget(splitter_idx, child)

        # Remove and delete the now-empty splitter.
        splitter.setParent(None)
        splitter.deleteLater()

        logger.debug("Simplified single-child splitter")

        # Recurse up in case the grandparent now also has a single child.
        self._simplify_splitter(grandparent)

    # --- Public API ----------------------------------------------------------

    def active_group(self):
        """
        Return the currently focused editor group.

        :return: The active group.
        :rtype: EditorGroup
        """
        return self._active_group

    def set_active_group(self, group):
        """
        Set a group as the active (focused) group.

        :param EditorGroup group: The group to activate.
        """
        if group in self._groups:
            self._active_group = group
            editor = group.current_editor()
            if editor:
                self.active_editor_changed.emit(editor)

    def current_editor(self):
        """
        Return the active editor from the active group.

        :return: The active MCACodeEditor, or None.
        :rtype: MCACodeEditor or None
        """
        if self._active_group:
            return self._active_group.current_editor()
        return None

    def groups(self):
        """
        Return the list of all editor groups.

        :return: List of EditorGroup instances.
        :rtype: list
        """
        return list(self._groups)

    def group_count(self):
        """
        Return the number of editor groups.

        :return: Number of groups.
        :rtype: int
        """
        return len(self._groups)

    def group_by_id(self, group_id):
        """
        Find a group by its Python id() value.

        Used by the drag-and-drop system to locate the source group
        from the MIME payload.

        :param int group_id: The id() of the target group.
        :return: The matching group, or None.
        :rtype: EditorGroup or None
        """
        for group in self._groups:
            if id(group) == group_id:
                return group
        return None

    def all_editors(self):
        """
        Return a flat list of all (editor, name, path) tuples across
        all groups.

        :return: List of editor tuples.
        :rtype: list
        """
        result = []
        for group in self._groups:
            result.extend(group.editors())
        return result

    def add_editor(self, editor, tab_name, file_path, icon=None, group=None):
        """
        Add an editor to the specified group (or the active group).

        :param MCACodeEditor editor: The editor widget.
        :param str tab_name: Display name for the tab.
        :param str file_path: File path (None for temp buffers).
        :param QIcon icon: Optional tab icon.
        :param EditorGroup group: Target group (defaults to active).
        :return: The new tab index.
        :rtype: int
        """
        target = group or self._active_group
        if target is None:
            target = self._create_group()
        return target.add_editor(editor, tab_name, file_path, icon)

    def find_editor_by_path(self, filepath):
        """
        Search all groups for an editor with the given file path.

        :param str filepath: The file path to search for.
        :return: Tuple of (group, index, editor) or (None, -1, None).
        :rtype: tuple
        """
        for group in self._groups:
            idx, editor = group.find_editor_by_path(filepath)
            if idx >= 0:
                return (group, idx, editor)
        return (None, -1, None)

    def split_right(self, source_group, tab_index):
        """
        Move a tab from source_group to a new group on the right.

        Backward-compatible wrapper around the new split_group method.

        :param EditorGroup source_group: The group containing the tab.
        :param int tab_index: Index of the tab to move.
        """
        self._split_tab_from_group(
            source_group, tab_index, Qt.Orientation.Horizontal, before=False
        )

    def focus_next_group(self):
        """
        Move focus to the next editor group (wraps around).
        """
        if len(self._groups) <= 1:
            return
        idx = self._groups.index(self._active_group)
        next_idx = (idx + 1) % len(self._groups)
        self._active_group = self._groups[next_idx]
        editor = self._active_group.current_editor()
        if editor:
            editor.setFocus()
            self.active_editor_changed.emit(editor)

    def focus_previous_group(self):
        """
        Move focus to the previous editor group (wraps around).
        """
        if len(self._groups) <= 1:
            return
        idx = self._groups.index(self._active_group)
        prev_idx = (idx - 1) % len(self._groups)
        self._active_group = self._groups[prev_idx]
        editor = self._active_group.current_editor()
        if editor:
            editor.setFocus()
            self.active_editor_changed.emit(editor)

    def focus_group(self, index):
        """
        Move focus to the group at the given index.

        :param int index: Group index.
        """
        if 0 <= index < len(self._groups):
            self._active_group = self._groups[index]
            editor = self._active_group.current_editor()
            if editor:
                editor.setFocus()
                self.active_editor_changed.emit(editor)

    # --- Layout State Persistence (Recursive) --------------------------------

    def get_layout_state(self):
        """
        Serialize the recursive splitter tree to a nested dict.

        Returns a layout tree suitable for saving in the v3 session
        manifest.  Groups are represented as ``{"type": "group"}``
        nodes and splitters as ``{"type": "splitter", ...}`` nodes.

        :return: Dict with 'layout' tree and 'active_group' index.
        :rtype: dict
        """
        active_idx = 0
        if self._active_group in self._groups:
            active_idx = self._groups.index(self._active_group)

        layout_tree = self._serialize_node(self._root_splitter)

        return {
            "layout": layout_tree,
            "active_group": active_idx,
        }

    def _serialize_node(self, node):
        """
        Recursively serialize a splitter tree node.

        :param QWidget node: A QSplitter or EditorGroup.
        :return: Serialized dict.
        :rtype: dict
        """
        if isinstance(node, EditorGroup):
            return {"type": "group"}

        if isinstance(node, QSplitter):
            orient = "horizontal" if node.orientation() == Qt.Orientation.Horizontal else "vertical"
            children = []
            for i in range(node.count()):
                child = node.widget(i)
                children.append(self._serialize_node(child))
            return {
                "type": "splitter",
                "orientation": orient,
                "sizes": node.sizes(),
                "children": children,
            }

        # Fallback for unknown widget types (shouldn't happen).
        return {"type": "unknown"}

    def restore_layout_state(self, state):
        """
        Rebuild the splitter tree from a saved layout state dict.

        This method is called during session restore. It tears down
        the existing splitter tree and rebuilds it from the serialized
        layout. Returns the groups in DFS order so the caller can
        populate tabs into each group.

        :param dict state: Previously saved layout state from get_layout_state().
        :return: List of EditorGroup instances in DFS order.
        :rtype: list
        """
        if not state:
            return self._groups

        layout = state.get("layout")
        if not layout:
            return self._groups

        # Check if this is a v2 compat state (flat splitter_sizes).
        if "splitter_sizes" in state and "layout" not in state:
            # Legacy v2 — just restore sizes on the root splitter.
            sizes = state.get("splitter_sizes", [])
            if sizes and len(sizes) == self._root_splitter.count():
                try:
                    self._root_splitter.setSizes([int(s) for s in sizes])
                except (TypeError, ValueError):
                    pass
            active_idx = state.get("active_group", 0)
            if 0 <= active_idx < len(self._groups):
                self._active_group = self._groups[active_idx]
            return self._groups

        # --- Full recursive rebuild ---
        # Remove all existing groups from the tree.
        old_groups = list(self._groups)
        self._groups.clear()
        for g in old_groups:
            self._drag_manager.uninstall_from_group(g)
            g.setParent(None)
            g.deleteLater()

        # Clear the root splitter.
        while self._root_splitter.count() > 0:
            w = self._root_splitter.widget(0)
            w.setParent(None)
            if isinstance(w, QSplitter):
                w.deleteLater()

        # Rebuild from the layout tree.
        self._rebuild_node(self._root_splitter, layout)

        # Restore the active group index.
        active_idx = state.get("active_group", 0)
        if 0 <= active_idx < len(self._groups):
            self._active_group = self._groups[active_idx]
        elif self._groups:
            self._active_group = self._groups[0]

        logger.debug("Restored layout with %d groups", len(self._groups))
        return list(self._groups)

    def _rebuild_node(self, parent_splitter, node_data):
        """
        Recursively rebuild the splitter tree from serialized data.

        For "group" nodes, creates a new EditorGroup and adds it to
        the parent splitter. For "splitter" nodes, creates a nested
        QSplitter and recurses into its children.

        :param QSplitter parent_splitter: The splitter to add children to.
        :param dict node_data: Serialized node data.
        """
        node_type = node_data.get("type", "group")

        if node_type == "group":
            # Create a new editor group in this splitter.
            self._create_group(parent_splitter)
            return

        if node_type == "splitter":
            orient_str = node_data.get("orientation", "horizontal")
            orientation = (Qt.Orientation.Horizontal
                          if orient_str == "horizontal"
                          else Qt.Orientation.Vertical)

            # If the parent splitter is empty and matches orientation,
            # reuse it (avoids unnecessary nesting at the root).
            if (parent_splitter.count() == 0
                    and parent_splitter.orientation() == orientation):
                target = parent_splitter
            else:
                # Create a nested splitter.
                target = QSplitter(orientation)
                parent_splitter.addWidget(target)

            # Rebuild children.
            for child_data in node_data.get("children", []):
                self._rebuild_node(target, child_data)

            # Restore sizes.
            sizes = node_data.get("sizes", [])
            if sizes and len(sizes) == target.count():
                try:
                    target.setSizes([int(s) for s in sizes])
                except (TypeError, ValueError):
                    pass

    # --- Backward Compat: ensure_group_count / group_at ----------------------

    def ensure_group_count(self, count):
        """
        Ensure at least ``count`` groups exist in a flat horizontal layout.

        Used during v2 session restore to pre-create groups before adding
        tabs. Adds groups to the root splitter.

        :param int count: Desired number of groups.
        """
        while len(self._groups) < count:
            self._create_group()

    def group_at(self, index):
        """
        Return the group at the given index (DFS order).

        :param int index: Group index.
        :return: The group, or None if out of bounds.
        :rtype: EditorGroup or None
        """
        if 0 <= index < len(self._groups):
            return self._groups[index]
        return None
