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

from mca_qt.qt_compat import QApplication, QDialog, Qt
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
    # Root logger stays at WARNING so routine MCA INFO/DEBUG messages
    # don't clutter the output window.  Warnings and errors still appear.
    # To enable verbose output for debugging, run:
    #     import logging; logging.getLogger("mca_core").setLevel(logging.DEBUG)
    logging.basicConfig(
        level=logging.WARNING,
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

    # --- One-time update check -----------------------------------------------
    # Check if a newer version is available (background thread, non-blocking).
    # If online and an update exists, show a yellow warning in the output panel.
    # If offline or up-to-date, nothing is printed.
    try:
        from mca_core.version_check import check_for_update
        from mca_qt.qt_compat import QTimer

        _update_win = window

        def _on_update_available(version, url):
            """Write update notification to the output panel from the main thread."""
            QTimer.singleShot(0, lambda: _update_win._panel._output.write_warning(
                "MCA Editor v{} is available.  Download at: {}".format(version, url)
            ))

        check_for_update(_on_update_available)
    except Exception as exc:
        logger.debug("Update check setup failed: %s", exc)

    logger.info("MCA Editor window opened")
    sys.exit(app.exec())


# Script guard for direct execution.
if __name__ == "__main__":
    main()
