"""
MCA Qt - Dark Theme.

Provides the dark palette and global stylesheet for MCA Editor,
matching the Charcoal Editor 2 aesthetic. Both standalone and
Maya-embedded modes use these same theme definitions.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
"""

import logging

from mca_qt.qt_compat import QPalette, QColor

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Dark Theme Palette -----------------------------------------------------

def create_dark_palette():
    """
    Create a dark theme palette matching the Charcoal Editor 2 aesthetic.

    :return: Configured dark palette for the application.
    :rtype: QPalette
    """
    palette = QPalette()

    # Base window colors.
    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 60))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.Text, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.Button, QColor(51, 51, 55))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(208, 208, 208))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(86, 156, 214))

    # Selection / highlight colors.
    palette.setColor(QPalette.ColorRole.Highlight, QColor(38, 79, 120))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

    # Disabled state colors (dimmed text).
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))

    return palette


# --- Global Stylesheet ------------------------------------------------------

# QSS stylesheet for fine-grained widget styling beyond the palette.
GLOBAL_STYLESHEET = """
    QToolTip {
        background-color: #3a3a3c;
        color: #d0d0d0;
        border: 1px solid #555;
        padding: 4px;
    }
    QMenuBar {
        background-color: #2d2d30;
        border-bottom: 1px solid #3f3f46;
    }
    QMenuBar::item:selected {
        background-color: #3e3e42;
    }
    QMenu {
        background-color: #2d2d30;
        border: 1px solid #3f3f46;
    }
    QMenu::item:selected {
        background-color: #3e3e42;
    }
    QMenu::separator {
        height: 1px;
        background: #3f3f46;
        margin: 4px 8px;
    }
    QTabBar {
        background-color: #2d2d30;
    }
    QTabBar::tab {
        background-color: #3c3c3c;
        color: #b0b0b0;
        padding: 6px 16px;
        border: none;
        border-bottom: 2px solid transparent;
        min-width: 80px;
    }
    QTabBar::tab:selected {
        color: #ffffff;
        border-bottom: 2px solid #569cd6;
        background-color: #2d2d30;
    }
    QTabBar::tab:hover:!selected {
        color: #d0d0d0;
        background-color: #454545;
    }
    QStatusBar {
        background-color: #007acc;
        color: white;
        font-size: 12px;
    }
    QSplitter::handle {
        background-color: #3f3f46;
    }
    QSplitter::handle:horizontal { width: 2px; }
    QSplitter::handle:vertical { height: 2px; }
    QTreeView, QTreeWidget, QListView, QListWidget {
        background-color: #252526;
        border: none;
        outline: none;
    }
    QTreeView::item, QTreeWidget::item,
    QListView::item, QListWidget::item {
        padding: 3px 0px;
        outline: none;
        border: none;
    }
    QTreeView::item:selected, QTreeWidget::item:selected,
    QListView::item:selected, QListWidget::item:selected {
        background-color: #094771;
    }
    QTreeView::item:hover:!selected, QTreeWidget::item:hover:!selected,
    QListView::item:hover:!selected, QListWidget::item:hover:!selected {
        background-color: #2a2d2e;
    }
    QScrollBar:vertical {
        background: #1e1e1e;
        width: 12px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #5a5a5a;
        min-height: 20px;
        border-radius: 3px;
        margin: 2px;
    }
    QScrollBar::handle:vertical:hover {
        background: #787878;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        background: #1e1e1e;
        height: 12px;
        margin: 0;
    }
    QScrollBar::handle:horizontal {
        background: #5a5a5a;
        min-width: 20px;
        border-radius: 3px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #787878;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QDockWidget {
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }
    QDockWidget::title {
        background-color: #252526;
        text-align: left;
        padding: 6px 8px;
        font-size: 11px;
        font-weight: bold;
        color: #bbbbbb;
    }
"""
