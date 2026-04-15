"""
MCA Qt - Drop Zone Overlay.

Provides a transparent overlay widget that paints visual drop zone
indicators over an EditorGroup during tab drag operations. Supports
five zones: LEFT, RIGHT, TOP, BOTTOM, and CENTER. The zone under the
cursor is highlighted with a semi-transparent blue fill.

This is used by DragTabManager to give the user visual feedback about
where a dragged tab will land when dropped.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QRect,
    Qt, QPainter, QColor, QPen,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Drop Zone Highlight Colors -------------------------------------------

# Fill color for the highlighted drop zone (semi-transparent blue).
ZONE_FILL_COLOR = QColor(30, 120, 220, 75)  # ~30% opacity blue.

# Border color for the highlighted drop zone.
ZONE_BORDER_COLOR = QColor(30, 120, 220, 200)

# Border width in pixels.
ZONE_BORDER_WIDTH = 2


# =============================================================================
# Drop Zone Enum
# =============================================================================

class DropZone:
    """
    Enumeration of drop zone positions within an editor group.

    Zones divide the group area into three regions (vertical splits
    were removed — the tab header/content layout doesn't have a
    meaningful top-vs-bottom axis, and drops there were error-prone):
        - LEFT: left 25% of the widget (split left)
        - RIGHT: right 25% of the widget (split right)
        - CENTER: remaining central area (merge into existing group)
        - NONE: cursor is not over any valid zone
    """
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


# =============================================================================
# Drop Zone Overlay Widget
# =============================================================================

class DropZoneOverlay(QWidget):
    """
    Transparent overlay that draws drop zone highlights over a target widget.

    The overlay is parented to the EditorGroupContainer and manually
    positioned over whichever EditorGroup the cursor is currently hovering.
    It computes five zone rectangles from the target's geometry and
    highlights the zone under the cursor.

    :param QWidget parent: The EditorGroupContainer that owns this overlay.
    """

    def __init__(self, parent=None):
        """
        Initialize the overlay. Starts hidden.

        :param QWidget parent: Parent widget (typically EditorGroupContainer).
        """
        super().__init__(parent)
        # Make the overlay transparent to mouse events so drops pass
        # through to the underlying editor group widgets.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        # The currently highlighted zone.
        self._active_zone = DropZone.NONE

        # Cached zone rectangles (in overlay-local coordinates).
        self._zone_rects = {}

        # The target group we're currently shown over.
        self._target_group = None

        # Start hidden.
        self.hide()

    # --- Public API ----------------------------------------------------------

    def show_over(self, target_group):
        """
        Position the overlay on top of a target EditorGroup and show it.

        Computes the five zone rectangles from the target's geometry
        relative to the shared parent container.

        :param EditorGroup target_group: The group widget to overlay.
        """
        if target_group is None:
            self.hide_overlay()
            return

        self._target_group = target_group

        # Map the target group's geometry to the parent container coords.
        parent = self.parentWidget()
        if parent is None:
            return

        # Get the target's top-left corner in parent coordinates.
        top_left = target_group.mapTo(parent, target_group.rect().topLeft())
        w = target_group.width()
        h = target_group.height()

        # Position and resize the overlay to cover the target group.
        self.setGeometry(top_left.x(), top_left.y(), w, h)

        # Compute the five zone rectangles within the overlay's local coords.
        self._compute_zone_rects(w, h)

        # Reset active zone and show.
        self._active_zone = DropZone.NONE
        self.show()
        self.raise_()

    def update_cursor(self, global_pos):
        """
        Hit-test the cursor against zone rectangles and update the highlight.

        :param QPoint global_pos: Cursor position in global (screen) coords.
        :return: The drop zone under the cursor.
        :rtype: str (DropZone constant)
        """
        # Convert global position to overlay-local coordinates.
        local_pos = self.mapFromGlobal(global_pos)

        # Test zones in priority order: LEFT/RIGHT first (side splits
        # are the common want), then CENTER for merge.
        new_zone = DropZone.NONE
        for zone_name in (DropZone.LEFT, DropZone.RIGHT, DropZone.CENTER):
            rect = self._zone_rects.get(zone_name)
            if rect and rect.contains(local_pos):
                new_zone = zone_name
                break

        # Only repaint if the zone actually changed.
        if new_zone != self._active_zone:
            self._active_zone = new_zone
            self.update()

        return new_zone

    def active_zone(self):
        """
        Return the currently highlighted drop zone.

        :return: Active zone constant.
        :rtype: str
        """
        return self._active_zone

    def hide_overlay(self):
        """Hide the overlay and reset all state."""
        self._active_zone = DropZone.NONE
        self._target_group = None
        self._zone_rects.clear()
        self.hide()

    def target_group(self):
        """
        Return the EditorGroup this overlay is currently shown over.

        :return: The target group, or None.
        :rtype: EditorGroup or None
        """
        return self._target_group

    # --- Zone Geometry -------------------------------------------------------

    def _compute_zone_rects(self, w, h):
        """
        Compute the three drop zone rectangles for a given size.

        Layout:
            - LEFT: left 25% of width, FULL height
            - RIGHT: right 25% of width, FULL height
            - CENTER: the remaining middle column, FULL height

        Vertical (TOP/BOTTOM) splits were removed — they conflicted with
        the tab bar at the top and the editor's normal scroll/footer
        area at the bottom, and drops there raised errors.

        :param int w: Overlay width in pixels.
        :param int h: Overlay height in pixels.
        """
        # Horizontal edge bands run the FULL height so side drops work
        # even when the cursor is near the tab bar or bottom of panel.
        left_w = int(w * 0.25)
        right_x = w - int(w * 0.25)
        mid_col_w = right_x - left_w

        self._zone_rects = {
            DropZone.LEFT: QRect(0, 0, left_w, h),
            DropZone.RIGHT: QRect(right_x, 0, w - right_x, h),
            DropZone.CENTER: QRect(left_w, 0, mid_col_w, h),
        }

    # --- Painting ------------------------------------------------------------

    def paintEvent(self, event):
        """
        Draw the semi-transparent highlight over the active drop zone.

        :param QPaintEvent event: The paint event.
        """
        if self._active_zone == DropZone.NONE:
            return

        rect = self._zone_rects.get(self._active_zone)
        if not rect:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Fill the zone with a translucent blue.
        painter.fillRect(rect, ZONE_FILL_COLOR)

        # Draw a solid border around the zone.
        pen = QPen(ZONE_BORDER_COLOR, ZONE_BORDER_WIDTH)
        painter.setPen(pen)
        # Inset the border slightly so it's fully visible.
        border_rect = rect.adjusted(1, 1, -1, -1)
        painter.drawRect(border_rect)

        painter.end()
