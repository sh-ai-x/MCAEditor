#!/usr/bin/env python3
"""
Forge Editor - Cross-DCC Script IDE
built for the modern pipeline.
Supports Maya, Blender, Unreal Engine, Unity, and more.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QIcon, QPalette, QColor

from config.settings import ForgeSettings
from ui.main_window import ForgeMainWindow


def create_dark_palette():
    """Create a dark theme palette similar to Charcoal Editor's aesthetic."""
    palette = QPalette()
    
    # Base colors
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
    
    # Highlight
    palette.setColor(QPalette.ColorRole.Highlight, QColor(38, 79, 120))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    
    # Disabled
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))
    
    return palette


def main():
    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Forge Editor")
    app.setOrganizationName("ForgeTools")
    app.setOrganizationDomain("forgetools.dev")
    app.setApplicationVersion("0.1.0")
    
    # Apply dark theme
    app.setStyle("Fusion")
    app.setPalette(create_dark_palette())
    
    # Global stylesheet refinements
    app.setStyleSheet("""
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
        QTabBar::tab {
            background-color: #2d2d30;
            color: #969696;
            padding: 6px 16px;
            border: none;
            border-bottom: 2px solid transparent;
            min-width: 80px;
        }
        QTabBar::tab:selected {
            color: #ffffff;
            border-bottom: 2px solid #569cd6;
            background-color: #1e1e1e;
        }
        QTabBar::tab:hover:!selected {
            color: #d0d0d0;
            background-color: #383838;
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
        QTreeView {
            background-color: #252526;
            border: none;
            outline: none;
        }
        QTreeView::item {
            padding: 3px 0px;
        }
        QTreeView::item:selected {
            background-color: #094771;
        }
        QTreeView::item:hover:!selected {
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
    """)
    
    # Load settings
    settings = ForgeSettings()
    
    # Create and show main window
    window = ForgeMainWindow(settings)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
