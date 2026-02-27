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


# --- Terminal Icon ------------------------------------------------------------

def terminal_icon():
    """
    Terminal/console icon ('>_' prompt in a rounded box).

    :return: Terminal icon.
    :rtype: QIcon
    """
    return _cached("terminal_icon", _paint_terminal_icon)


def _paint_terminal_icon():
    """Paint a terminal prompt icon."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Draw the prompt chevron ">".
    accent = QColor("#569cd6")
    pen = QPen(accent, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(3, 4, 8, 8)
    p.drawLine(8, 8, 3, 12)

    # Draw the underscore "_".
    p.drawLine(9, 12, 14, 12)

    p.end()
    return QIcon(pix)


# --- AI Icon -----------------------------------------------------------------

def ai_icon():
    """
    AI / sparkle icon (four-pointed star).

    :return: AI icon.
    :rtype: QIcon
    """
    return _cached("ai_icon", _paint_ai_icon)


def _paint_ai_icon():
    """Paint an AI sparkle/star icon."""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Four-pointed sparkle shape in purple/violet.
    sparkle_color = QColor("#b48ead")

    # Draw a four-pointed star centered at (8, 8).
    path = QPainterPath()
    path.moveTo(8, 1)     # Top point.
    path.lineTo(10, 6)
    path.lineTo(15, 8)    # Right point.
    path.lineTo(10, 10)
    path.lineTo(8, 15)    # Bottom point.
    path.lineTo(6, 10)
    path.lineTo(1, 8)     # Left point.
    path.lineTo(6, 6)
    path.closeSubpath()

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(sparkle_color)
    p.drawPath(path)

    p.end()
    return QIcon(pix)


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
