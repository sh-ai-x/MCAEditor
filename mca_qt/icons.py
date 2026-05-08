"""
MCA Qt - Programmatic Icon Generation.

Creates all editor icons via QPainter at runtime so no external
image files are needed. Icons are cached after first creation.

Available icons:
    - ``folder_closed()`` / ``folder_open()`` — workspace tree folders
    - ``python_logo()`` — Python file / tab icon (blue + yellow)
    - ``maya_logo()`` — MEL / Maya tab icon (teal M)
    - ``text_icon()`` — plain text tab icon (gray)

Dependencies:
    - mca_qt.qt_compat (QPixmap, QPainter, QColor, etc.)
"""

import os
import logging

from mca_qt.qt_compat import (
    QPixmap, QIcon, QPainter, QColor, QFont, QPen, QPainterPath,
    Qt,
)

# Base directory for image resources (relative to this file's package root).
_RESOURCES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "images")

# Module-level logger.
logger = logging.getLogger(__name__)

# Icon cache — avoids re-painting on every call.
_cache = {}

# Default icon size (pixels). Small enough for tree items and tabs.
ICON_SIZE = 16


# --- Helper ------------------------------------------------------------------

def _cached(name, painter_fn):
    """
    Return a cached QIcon, creating it on first access.

    :param str name: Cache key.
    :param callable painter_fn: Function that paints onto a QPixmap and
        returns a QIcon.
    :return: The cached icon.
    :rtype: QIcon
    """
    if name not in _cache:
        _cache[name] = painter_fn()
    return _cache[name]


# --- Folder Icons ------------------------------------------------------------

def folder_closed():
    """
    Closed folder icon (yellow-orange folder shape).

    :return: Folder-closed icon.
    :rtype: QIcon
    """
    return _cached("folder_closed", _paint_folder_closed)


def folder_open():
    """
    Open folder icon (same shape with open-top indication).

    :return: Folder-open icon.
    :rtype: QIcon
    """
    return _cached("folder_open", _paint_folder_open)


def _paint_folder_closed():
    """Paint a closed folder icon."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Folder body — warm tan/yellow matching VS Code's default.
    body_color = QColor("#c09553")
    tab_color = QColor("#c09553")

    # Folder tab (the small ear at top-left).
    tab = QPainterPath()
    tab.moveTo(1, 4)
    tab.lineTo(1, 2)
    tab.lineTo(6, 2)
    tab.lineTo(7, 4)
    tab.closeSubpath()
    p.fillPath(tab, tab_color)

    # Folder body rectangle.
    body = QPainterPath()
    body.addRoundedRect(1, 4, 14, 10, 1.5, 1.5)
    p.fillPath(body, body_color)

    p.end()
    return QIcon(pix)


def _paint_folder_open():
    """Paint an open folder icon."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    body_color = QColor("#c09553")
    front_color = QColor("#d4a55c")

    # Folder tab (the small ear at top-left).
    tab = QPainterPath()
    tab.moveTo(1, 4)
    tab.lineTo(1, 2)
    tab.lineTo(6, 2)
    tab.lineTo(7, 4)
    tab.closeSubpath()
    p.fillPath(tab, body_color)

    # Folder body (back).
    back = QPainterPath()
    back.addRoundedRect(1, 4, 14, 10, 1.5, 1.5)
    p.fillPath(back, body_color)

    # Open front flap (shifted right/down to give an "open" look).
    front = QPainterPath()
    front.moveTo(2, 7)
    front.lineTo(5, 7)
    front.lineTo(15, 7)
    front.lineTo(13, 14)
    front.lineTo(1, 14)
    front.closeSubpath()
    p.fillPath(front, front_color)

    p.end()
    return QIcon(pix)


# --- MCA Logo ----------------------------------------------------------------

def mca_logo(size=None):
    """
    MCA Editor logo loaded from ``resources/images/mca.png``.

    Returns a QIcon at the requested *size* (defaults to 20px for title bars).

    :param int size: Desired icon size in pixels.  Defaults to 20.
    :return: MCA logo icon.
    :rtype: QIcon
    """
    if size is None:
        size = 20
    # Cache per size so callers can request different dimensions.
    cache_key = "mca_logo_{}".format(size)
    return _cached(cache_key, lambda: _load_mca_logo(size))


def _load_mca_logo(size):
    """
    Load the MCA logo PNG and scale to the requested size.

    :param int size: Target pixel size (square).
    :return: Scaled QIcon.
    :rtype: QIcon
    """
    logo_path = os.path.join(_RESOURCES_DIR, "mca.png")
    pix = QPixmap(logo_path)
    if pix.isNull():
        logger.warning("Could not load MCA logo from %s", logo_path)
        # Fall back to a colored square so the icon isn't blank.
        pix = QPixmap(size, size)
        pix.fill(QColor("#E8922A"))
    else:
        pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return QIcon(pix)


# --- Python Logo -------------------------------------------------------------

def python_logo():
    """
    Python logo loaded from ``resources/images/python_logo.png``.

    :return: Python logo icon.
    :rtype: QIcon
    """
    return _cached("python_logo", _load_python_logo)


def _load_python_logo():
    """Load the Python logo from the resources PNG file."""
    logo_path = os.path.join(_RESOURCES_DIR, "python_logo.png")
    pix = QPixmap(logo_path)
    if pix.isNull():
        logger.warning("Could not load Python logo from %s", logo_path)
        # Fall back to a simple colored square so the icon isn't blank.
        pix = QPixmap(ICON_SIZE, ICON_SIZE)
        pix.fill(QColor("#3572A5"))
    else:
        # Scale to icon size for consistent display in trees and tabs.
        pix = pix.scaled(ICON_SIZE, ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return QIcon(pix)


# --- Maya / MEL Logo ---------------------------------------------------------

def maya_logo():
    """
    Simplified Maya logo (teal M).

    :return: Maya icon.
    :rtype: QIcon
    """
    return _cached("maya_logo", _paint_maya_logo)


def _paint_maya_logo():
    """Paint a simplified Maya M logo."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Maya teal color.
    teal = QColor("#00B4C5")

    # Draw a bold "M" shape as a path.
    pen = QPen(teal, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    path = QPainterPath()
    path.moveTo(2, 13)
    path.lineTo(2, 3)
    path.lineTo(8, 9)
    path.lineTo(14, 3)
    path.lineTo(14, 13)
    p.drawPath(path)

    p.end()
    return QIcon(pix)


# --- Text File Icon ----------------------------------------------------------

def text_icon():
    """
    Plain text file icon (gray document).

    :return: Text file icon.
    :rtype: QIcon
    """
    return _cached("text_icon", _paint_text_icon)


# --- Sidebar Icon ------------------------------------------------------------

def sidebar_icon():
    """
    Sidebar toggle icon (panel layout with left sidebar highlighted).

    :return: Sidebar icon.
    :rtype: QIcon
    """
    return _cached("sidebar_icon", _paint_sidebar_icon)


def _paint_sidebar_icon():
    """Paint a sidebar/panel layout icon."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Outer frame representing the editor window.
    frame_color = QColor("#969696")
    p.setPen(QPen(frame_color, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(1, 2, 14, 12, 1.5, 1.5)

    # Left sidebar panel (filled to indicate sidebar area).
    sidebar_color = QColor("#569cd6")
    sidebar = QPainterPath()
    sidebar.addRoundedRect(1, 2, 5, 12, 1.0, 1.0)
    p.fillPath(sidebar, sidebar_color)

    # Vertical divider between sidebar and main area.
    p.setPen(QPen(frame_color, 1.0))
    p.drawLine(6, 2, 6, 14)

    p.end()
    return QIcon(pix)


def settings_icon():
    """
    Settings / gear icon for the tool stripe.

    :return: Gear icon.
    :rtype: QIcon
    """
    return _cached("settings_icon", _paint_settings_icon)


def _paint_settings_icon():
    """Paint a gear icon with 8 teeth using a QPainterPath outline."""
    import math

    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    color = QColor("#969696")
    cx, cy = 8.0, 8.0

    # Build gear outline: 8 teeth alternating between inner and outer radii.
    inner_r = 4.2
    outer_r = 6.5
    teeth = 8
    # Each tooth spans half a step (raised) then half a step (valley).
    step = 2.0 * math.pi / teeth
    half_tooth = step * 0.28  # Width of each tooth at the tip.

    gear = QPainterPath()
    for i in range(teeth):
        base_angle = i * step
        # Outer tooth corners.
        a1 = base_angle - half_tooth
        a2 = base_angle + half_tooth
        # Inner valley corners (midway between teeth).
        a3 = base_angle + half_tooth
        a4 = base_angle + step - half_tooth

        ox1 = cx + outer_r * math.cos(a1)
        oy1 = cy + outer_r * math.sin(a1)
        ox2 = cx + outer_r * math.cos(a2)
        oy2 = cy + outer_r * math.sin(a2)
        ix1 = cx + inner_r * math.cos(a3)
        iy1 = cy + inner_r * math.sin(a3)
        ix2 = cx + inner_r * math.cos(a4)
        iy2 = cy + inner_r * math.sin(a4)

        if i == 0:
            gear.moveTo(ox1, oy1)
        else:
            gear.lineTo(ox1, oy1)
        gear.lineTo(ox2, oy2)
        gear.lineTo(ix1, iy1)
        gear.lineTo(ix2, iy2)

    gear.closeSubpath()

    # Hollow center — subtract an inner circle.
    center_hole = QPainterPath()
    center_hole.addEllipse(cx - 2.2, cy - 2.2, 4.4, 4.4)
    gear = gear.subtracted(center_hole)

    # Draw the gear shape.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(gear)

    p.end()
    return QIcon(pix)


# --- Plugin Icon -------------------------------------------------------------

def plugin_icon():
    """
    Plugin/puzzle-piece icon for the plugin system.

    :return: Plugin icon.
    :rtype: QIcon
    """
    return _cached("plugin_icon", _paint_plugin_icon)


def _paint_plugin_icon():
    """Paint a puzzle piece icon representing a plugin."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Draw a simple puzzle piece shape using a path.
    accent = QColor("#569cd6")
    pen = QPen(accent, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(86, 156, 214, 60))

    # Puzzle piece outline — simplified block with a tab on top and right.
    path = QPainterPath()
    path.moveTo(3, 5)
    # Top edge with tab notch.
    path.lineTo(6, 5)
    path.lineTo(6, 3)
    path.lineTo(9, 3)
    path.lineTo(9, 5)
    path.lineTo(13, 5)
    # Right edge with tab notch.
    path.lineTo(13, 8)
    path.lineTo(15, 8)
    path.lineTo(15, 11)
    path.lineTo(13, 11)
    path.lineTo(13, 14)
    # Bottom and left.
    path.lineTo(3, 14)
    path.closeSubpath()
    p.drawPath(path)

    p.end()
    return QIcon(pix)


def _paint_text_icon():
    """Paint a simple text/document icon."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    gray = QColor("#969696")

    # Document outline with folded corner.
    doc = QPainterPath()
    doc.moveTo(3, 1)
    doc.lineTo(10, 1)
    doc.lineTo(13, 4)
    doc.lineTo(13, 15)
    doc.lineTo(3, 15)
    doc.closeSubpath()
    p.setPen(QPen(gray, 1.0))
    p.setBrush(QColor("#2d2d30"))
    p.drawPath(doc)

    # Folded corner triangle.
    fold = QPainterPath()
    fold.moveTo(10, 1)
    fold.lineTo(10, 4)
    fold.lineTo(13, 4)
    fold.closeSubpath()
    p.fillPath(fold, gray)

    # Text lines inside the document.
    p.setPen(QPen(QColor("#666666"), 1.0))
    p.drawLine(5, 7, 11, 7)
    p.drawLine(5, 9, 11, 9)
    p.drawLine(5, 11, 9, 11)

    p.end()
    return QIcon(pix)
