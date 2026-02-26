"""
MCA Standalone - Application Bootstrap.

Entry point for the MCA Editor standalone application. Sets up the Qt
application, applies the dark theme palette and stylesheet, loads
settings, and launches the standalone window.

Dependencies:
    - mca_qt.qt_compat (PySide2/6 compatibility layer)
    - mca_qt.theme (dark palette and stylesheet)
    - mca_core (version metadata, settings)
    - mca_standalone.standalone_window (StandaloneWindow)

Usage:
    python -m mca_standalone.main
    # or via the top-level run.py launcher
"""

import sys
import logging

from mca_core.venv_manager import setup_venv

from mca_qt.qt_compat import QApplication, Qt
from mca_qt.theme import create_dark_palette, GLOBAL_STYLESHEET
from mca_core import __version__, __app_name__, __org_name__, __org_domain__
from mca_core.config.settings import MCASettings
from mca_standalone.standalone_window import StandaloneWindow

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Main Entry Point -------------------------------------------------------

def main():
    """
    Launch the MCA Editor standalone application.

    Sets up logging, configures the Qt application with dark theme,
    loads user settings, creates the standalone window, and enters
    the Qt event loop.
    """
    # Configure logging for the entire application.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("Starting %s v%s", __app_name__, __version__)

    # Set up the managed venv and install/inject dependencies before any
    # imports that rely on venv packages (pywinpty, pyflakes, etc.).
    # This is fast on subsequent launches — just a sys.path.insert().
    setup_venv()

    # Enable high DPI scaling (passthrough for crisp rendering).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName(__org_name__)
    app.setOrganizationDomain(__org_domain__)
    app.setApplicationVersion(__version__)

    # Apply the dark Fusion theme.
    app.setStyle("Fusion")
    app.setPalette(create_dark_palette())
    app.setStyleSheet(GLOBAL_STYLESHEET)

    # Load persistent settings.
    settings = MCASettings()

    # Create and show the standalone window.
    window = StandaloneWindow(settings)
    window.show()

    logger.info("MCA Editor window opened")
    sys.exit(app.exec())


# Script guard for direct execution.
if __name__ == "__main__":
    main()
