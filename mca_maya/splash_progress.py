"""
MCA Maya - First-Launch Splash Progress.

Custom splash screen shown during first-launch setup.  Displays the
Orange Slice mascot GIF (Logo_InAndOut.gif), a status line showing
what is happening, and rotating orange-themed puns to keep the user
entertained while dependencies install.

The splash is a frameless widget centered on Maya's main window.
No Qt virtual method overrides are used, so this file compiles to
``.pyd`` without Shiboken enum issues.

The blocking setup work (venv creation, pip installs, git clone, MCP
registration) runs on a background ``threading.Thread``.  The main
thread stays in a tight polling loop (~60 fps) that drains status
messages from a ``queue.Queue``, rotates jokes every few seconds, and
calls ``processEvents()`` so the GIF keeps animating smoothly.

Public API::

    result = run_with_splash(setup_fn)   # One-call: show, run, close

Internal helpers (used by run_with_splash)::

    splash = create_splash()
    update_status(splash, "...")
    close_splash(splash)

Dependencies:
    - PySide6 or PySide2 (via Maya)
    - mca_core._package_root (for GIF path resolution)
"""

import os
import logging
import queue
import random
import threading
import time

# Maya 2025+ ships PySide6; older versions use PySide2.
try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui

import mca_core

# Module-level logger.
logger = logging.getLogger(__name__)


# --- GIF Path ----------------------------------------------------------------

# Resolve the mascot GIF from the package root (works for both source
# tree and single-file extraction cache).
_GIFS_DIR = os.path.join(mca_core._package_root, "resources", "gifs")
_SPLASH_GIF = os.path.join(_GIFS_DIR, "Logo_InAndOut.gif")


# --- Orange Puns & Jokes -----------------------------------------------------
# Displayed below the mascot GIF and rotated every few seconds.
# Shuffled per session so the order feels random.

_ORANGE_PUNS = [
    "Orange you glad you installed this?",
    "Freshly squeezed code coming right up!",
    "Peel good about this one...",
    "This setup is un-peel-ievable!",
    "Concentrate... almost there!",
    "Juice a moment, setting things up...",
    "Pulp fiction? No, pulp function!",
    "Zesting things up for you...",
    "Vitamin C++ loading...",
    "Segmenting the dependencies...",
    "This process is really a-peeling!",
    "The zest editor around!",
    "Squeezing out the last bugs...",
    "You're one in a melon... wait, wrong fruit.",
    "Seeds of greatness being planted...",
    "Citrus-ly, this won't take long.",
    "Navel-gazing while we install...",
    "Turning lemons into... wait, we're oranges.",
    "Time to concentrate on the install...",
    "Making fresh-squeezed plugins!",
    "A-peeling to your sense of style...",
    "This code has lots of a-peel!",
    "Don't worry, this is a seedless install.",
    "Just rind-ing up the environment...",
    "Orange you patient! Almost done...",
    "We're on a roll... an orange roll.",
    "Slice, slice, baby!",
    "Finding the zest path forward...",
    "pip install happiness (orange flavored)...",
    "Marmalade? More like marma-LAID out nicely.",
    "Juicing up your Maya workflow...",
    "Tangelo-ing with some dependencies...",
    "Keep calm and carrot on... wait, orange.",
    "Ready to produce some a-peeling code!",
    "May the zest be with you.",
]

# How often to rotate to the next joke (seconds).
_JOKE_INTERVAL = 3.5


# --- Visual Constants --------------------------------------------------------

# Mascot GIF display size (pixels).
_GIF_SIZE = 180

# Splash card dimensions.
_CARD_WIDTH = 440
_CARD_PADDING = 28

# Brand colors.
_ORANGE = "#E8922A"
_DARK_BG = "#1e1e1e"
_CARD_BG = "#252526"
_TEXT_COLOR = "#cccccc"
_STATUS_COLOR = "#ffffff"
_PUN_COLOR = "#c47a1f"


# --- Maya Main Window Helper -------------------------------------------------

def _get_maya_main_window():
    """
    Return Maya's main window as a QWidget, or None.

    Tries shiboken6 first (Maya 2025+), then falls back to shiboken2
    (Maya 2024).

    :return: Maya main window widget.
    :rtype: QtWidgets.QWidget or None
    """
    try:
        from maya.OpenMayaUI import MQtUtil

        # Maya 2025+ uses shiboken6, older versions use shiboken2.
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken

        ptr = MQtUtil.mainWindow()
        if ptr:
            return shiboken.wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        pass
    return None


# --- Main Entry Point --------------------------------------------------------

def run_with_splash(setup_fn):
    """
    Show the splash screen and run *setup_fn* on a background thread.

    The main thread stays in a tight polling loop (~60 fps) that:

    - Drains status messages from the worker via a ``queue.Queue``.
    - Rotates the joke label every ``_JOKE_INTERVAL`` seconds.
    - Calls ``processEvents()`` so the GIF animates and labels repaint.

    When the worker thread finishes, any remaining messages are drained,
    the splash is closed, and the worker's return value is returned.

    *setup_fn* must accept a single keyword argument
    ``status_callback`` — a callable that takes one ``str`` message.

    :param callable setup_fn: Function to run on the background thread.
        Signature: ``setup_fn(status_callback=callable)``.
    :return: Whatever *setup_fn* returns.
    """
    splash = create_splash()

    # Thread-safe queue for status messages from the worker thread.
    msg_queue = queue.Queue()

    # Mutable container so the worker can store its return value.
    result_holder = [None]

    def _worker():
        """Background thread — runs the blocking setup work."""
        def _status(msg):
            msg_queue.put(msg)
        result_holder[0] = setup_fn(status_callback=_status)

    # Launch the worker thread (daemon so it won't block Maya shutdown).
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    # --- Main-thread polling loop -----------------------------------------
    # Keeps Qt responsive so the GIF animates and labels repaint.
    # Runs at ~60 fps (16 ms sleep) to balance smoothness and CPU usage.
    last_joke_time = time.monotonic()

    while thread.is_alive():
        # Drain any pending status messages from the worker.
        while not msg_queue.empty():
            try:
                msg = msg_queue.get_nowait()
                splash._status_label.setText(msg)
            except queue.Empty:
                break

        # Rotate joke on a timer (independent of status updates).
        now = time.monotonic()
        if now - last_joke_time >= _JOKE_INTERVAL:
            splash._pun_index = (splash._pun_index + 1) % len(splash._pun_order)
            splash._joke_label.setText(splash._pun_order[splash._pun_index])
            last_joke_time = now

        # Keep Qt responsive — GIF animation, label repaints.
        QtWidgets.QApplication.processEvents()

        # Brief sleep to avoid busy-wait (~60 fps).
        time.sleep(0.016)

    # --- Worker finished — drain any final messages -----------------------
    while not msg_queue.empty():
        try:
            msg = msg_queue.get_nowait()
            splash._status_label.setText(msg)
        except queue.Empty:
            break

    QtWidgets.QApplication.processEvents()
    close_splash(splash)

    return result_holder[0]


# --- Splash Factory ----------------------------------------------------------

def create_splash(parent=None):
    """
    Create and show the first-launch splash screen.

    The splash is a frameless dark card centered on *parent* (or Maya's
    main window).  It contains:

    - A title bar with "MCA Editor Setup" and an orange accent.
    - A status label that shows the current setup step.
    - The Orange Slice mascot GIF (Logo_InAndOut.gif) animating.
    - A rotating pun/joke label below the GIF.

    Internal references are stored as attributes on the returned widget
    so the polling loop and ``close_splash()`` can access them without
    needing a class.

    :param QtWidgets.QWidget parent: Parent widget (default: Maya main window).
    :return: The splash widget.
    :rtype: QtWidgets.QWidget
    """
    # Fall back to Maya's main window if no parent given.
    if parent is None:
        parent = _get_maya_main_window()

    # --- Build the splash widget (frameless, always on top) ---------------
    splash = QtWidgets.QWidget(parent, QtCore.Qt.Window
                               | QtCore.Qt.FramelessWindowHint
                               | QtCore.Qt.WindowStaysOnTopHint)
    splash.setAttribute(QtCore.Qt.WA_TranslucentBackground)
    splash.setFixedWidth(_CARD_WIDTH)

    # --- Outer layout (holds the card) ------------------------------------
    outer = QtWidgets.QVBoxLayout(splash)
    outer.setContentsMargins(0, 0, 0, 0)

    # --- Card frame (rounded dark rectangle) ------------------------------
    card = QtWidgets.QFrame()
    card.setStyleSheet(
        "QFrame {"
        "  background-color: %s;"
        "  border-radius: 16px;"
        "  border: 2px solid %s;"
        "}" % (_CARD_BG, _ORANGE)
    )
    outer.addWidget(card)

    # --- Card internal layout ---------------------------------------------
    layout = QtWidgets.QVBoxLayout(card)
    layout.setContentsMargins(_CARD_PADDING, _CARD_PADDING,
                              _CARD_PADDING, _CARD_PADDING)
    layout.setSpacing(12)

    # --- Title label ------------------------------------------------------
    title = QtWidgets.QLabel("MCA Editor Setup")
    title.setAlignment(QtCore.Qt.AlignCenter)
    title.setStyleSheet(
        "QLabel {"
        "  color: %s;"
        "  font-size: 18px;"
        "  font-weight: bold;"
        "  font-family: Segoe UI, Helvetica Neue, Arial, sans-serif;"
        "  background: transparent;"
        "  border: none;"
        "  padding-bottom: 4px;"
        "}" % _ORANGE
    )
    layout.addWidget(title)

    # --- Status label (what's currently happening) ------------------------
    status_label = QtWidgets.QLabel("Preparing MCA Editor for first use...")
    status_label.setAlignment(QtCore.Qt.AlignCenter)
    status_label.setWordWrap(True)
    status_label.setStyleSheet(
        "QLabel {"
        "  color: %s;"
        "  font-size: 13px;"
        "  font-family: Segoe UI, Helvetica Neue, Arial, sans-serif;"
        "  background: transparent;"
        "  border: none;"
        "}" % _STATUS_COLOR
    )
    layout.addWidget(status_label)

    # --- Spacer before GIF ------------------------------------------------
    layout.addSpacing(8)

    # --- Mascot GIF -------------------------------------------------------
    gif_label = QtWidgets.QLabel()
    gif_label.setAlignment(QtCore.Qt.AlignCenter)
    gif_label.setFixedSize(_GIF_SIZE, _GIF_SIZE)
    gif_label.setStyleSheet("background: transparent; border: none;")

    # Center the GIF label horizontally.
    gif_container = QtWidgets.QHBoxLayout()
    gif_container.addStretch()
    gif_container.addWidget(gif_label)
    gif_container.addStretch()
    layout.addLayout(gif_container)

    # Load and start the animated GIF if the file exists.
    movie = None
    if os.path.isfile(_SPLASH_GIF):
        movie = QtGui.QMovie(_SPLASH_GIF)
        movie.setScaledSize(QtCore.QSize(_GIF_SIZE, _GIF_SIZE))
        gif_label.setMovie(movie)
        movie.start()
        logger.debug("Splash GIF loaded: %s", _SPLASH_GIF)
    else:
        # Fallback — show text if GIF is missing.
        gif_label.setText("Orange Slice")
        gif_label.setStyleSheet(
            "QLabel {"
            "  color: %s;"
            "  font-size: 32px;"
            "  font-weight: bold;"
            "  font-family: Segoe UI, Helvetica Neue, Arial, sans-serif;"
            "  background: transparent;"
            "  border: none;"
            "}" % _ORANGE
        )
        logger.warning("Splash GIF not found: %s", _SPLASH_GIF)

    # --- Spacer before joke -----------------------------------------------
    layout.addSpacing(8)

    # --- Separator line (thin orange) -------------------------------------
    separator = QtWidgets.QFrame()
    separator.setFixedHeight(1)
    separator.setStyleSheet(
        "background-color: %s; border: none;" % _ORANGE
    )
    layout.addWidget(separator)

    # --- Spacer after separator -------------------------------------------
    layout.addSpacing(4)

    # --- Joke / pun label -------------------------------------------------
    # Shuffle the pun list so each first-launch feels unique.
    pun_order = list(_ORANGE_PUNS)
    random.shuffle(pun_order)

    joke_label = QtWidgets.QLabel(pun_order[0])
    joke_label.setAlignment(QtCore.Qt.AlignCenter)
    joke_label.setWordWrap(True)
    joke_label.setStyleSheet(
        "QLabel {"
        "  color: %s;"
        "  font-size: 12px;"
        "  font-style: italic;"
        "  font-family: Segoe UI, Helvetica Neue, Arial, sans-serif;"
        "  background: transparent;"
        "  border: none;"
        "  padding: 4px;"
        "}" % _PUN_COLOR
    )
    layout.addWidget(joke_label)

    # --- Bottom padding ---------------------------------------------------
    layout.addSpacing(8)

    # --- Store references on the widget for the polling loop / close ------
    splash._status_label = status_label
    splash._joke_label = joke_label
    splash._pun_order = pun_order
    splash._pun_index = 0
    splash._movie = movie  # Keep reference so QMovie isn't garbage collected.

    # --- Size and center --------------------------------------------------
    splash.adjustSize()
    _center_on_parent(splash, parent)

    # --- Show and force an initial paint ----------------------------------
    splash.show()
    splash.raise_()
    QtWidgets.QApplication.processEvents()

    logger.info("First-launch splash shown.")
    return splash


# --- Internal Update / Close -------------------------------------------------

def update_status(splash, msg):
    """
    Update the splash status text and rotate the joke.

    Used internally by ``run_with_splash()`` for direct calls.  When
    running threaded, the polling loop updates labels directly instead.

    :param QtWidgets.QWidget splash: The splash widget from ``create_splash()``.
    :param str msg: New status message to display.
    """
    # Update the status line.
    splash._status_label.setText(msg)

    # Advance to the next pun.
    splash._pun_index = (splash._pun_index + 1) % len(splash._pun_order)
    splash._joke_label.setText(splash._pun_order[splash._pun_index])

    # Pump the event loop so the GIF keeps animating and labels repaint.
    QtWidgets.QApplication.processEvents()


def close_splash(splash):
    """
    Close and clean up the splash screen.

    Stops the GIF movie (if any), hides the widget, and schedules it
    for deletion.

    :param QtWidgets.QWidget splash: The splash widget from ``create_splash()``.
    """
    # Stop the GIF animation.
    if splash._movie is not None:
        splash._movie.stop()

    splash.hide()
    splash.deleteLater()
    QtWidgets.QApplication.processEvents()
    logger.info("First-launch splash closed.")


# --- Internal Helpers --------------------------------------------------------

def _center_on_parent(widget, parent):
    """
    Center *widget* on *parent*'s geometry, or on the primary screen
    if *parent* is None.

    :param QtWidgets.QWidget widget: Widget to center.
    :param QtWidgets.QWidget parent: Reference widget (Maya main window).
    """
    if parent is not None:
        # Center on parent's geometry.
        parent_geo = parent.geometry()
        cx = parent_geo.x() + (parent_geo.width() - widget.width()) // 2
        cy = parent_geo.y() + (parent_geo.height() - widget.height()) // 2
        widget.move(cx, cy)
    else:
        # Fallback — center on primary screen.
        try:
            screen = QtWidgets.QApplication.primaryScreen().geometry()
        except AttributeError:
            # PySide2 (Maya 2024) uses desktop() instead of primaryScreen().
            screen = QtWidgets.QApplication.desktop().screenGeometry()
        cx = (screen.width() - widget.width()) // 2
        cy = (screen.height() - widget.height()) // 2
        widget.move(cx, cy)
