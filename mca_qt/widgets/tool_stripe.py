"""
MCA Qt - Tool Stripe (PyCharm-style edge button bars).

Thin vertical bars (~28px wide) placed on the left and right edges of
the editor window.  Each bar contains icon buttons that toggle tool
panels (Terminal, AI, etc.), exactly like PyCharm/IntelliJ's
"tool window stripes."

Layout::

    ToolStripe(QWidget)
      +-- QVBoxLayout
            +-- ToolStripeButton [terminal icon]
            +-- ToolStripeButton [AI icon]
            +-- ...
            +-- stretch

Dependencies:
    - PySide6 or PySide2 (via mca_qt.qt_compat)
"""

import logging

from mca_qt.qt_compat import (
    QWidget, QVBoxLayout, QPushButton,
    Qt, Signal, QSize,
)

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Styling Constants --------------------------------------------------------

# Width of the stripe bar in pixels.
STRIPE_WIDTH = 28

# Icon size inside stripe buttons (slightly smaller than the bar).
ICON_SIZE = 18

# Colors for active (panel open) and inactive (panel closed) buttons.
ACTIVE_BORDER_COLOR = "#569cd6"
STRIPE_BG = "#333337"


# =============================================================================
# ToolStripeButton — Single Icon Button
# =============================================================================

class ToolStripeButton(QPushButton):
    """
    An icon button for the tool stripe.

    Displays a small icon centered in the button.  Has an "active"
    state indicated by a 2px blue left-border highlight.

    :param QWidget parent: Optional parent widget.
    """

    def __init__(self, parent=None):
        """
        Initialize the stripe button.

        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)

        # Track active/highlighted state.
        self._active = False

        # Fixed size: square-ish button fitting inside the stripe.
        self.setFixedWidth(STRIPE_WIDTH)
        self.setFixedHeight(STRIPE_WIDTH)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Apply the default (inactive) styling.
        self._apply_style()

    def set_active(self, active):
        """
        Set the button's active (highlighted) state.

        :param bool active: True to highlight, False for inactive.
        """
        self._active = active
        self._apply_style()

    def is_active(self):
        """
        Check whether the button is in the active state.

        :return: True if active.
        :rtype: bool
        """
        return self._active

    def _apply_style(self):
        """Apply stylesheet based on the current active state."""
        if self._active:
            self.setStyleSheet("""
                QPushButton {{
                    background-color: {bg};
                    border: none;
                    border-left: 2px solid {border};
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: #3e3e42;
                }}
            """.format(bg=STRIPE_BG, border=ACTIVE_BORDER_COLOR))
        else:
            self.setStyleSheet("""
                QPushButton {{
                    background-color: {bg};
                    border: none;
                    border-left: 2px solid transparent;
                    padding: 4px;
                    opacity: 0.6;
                }}
                QPushButton:hover {{
                    background-color: #3e3e42;
                }}
            """.format(bg=STRIPE_BG))

    def sizeHint(self):
        """
        Return the preferred size (square).

        :return: Preferred size.
        :rtype: QSize
        """
        return QSize(STRIPE_WIDTH, STRIPE_WIDTH)


# =============================================================================
# ToolStripe — Vertical Button Bar
# =============================================================================

class ToolStripe(QWidget):
    """
    Thin vertical bar containing icon tool buttons.

    Place one on the left edge and one on the right edge of the main
    layout.  Each button toggles a tool panel.

    Signals:
        button_clicked(str) — emits the button name when clicked.

    :param QWidget parent: Optional parent widget.
    """

    # Emitted when any button in this stripe is clicked.
    # Arg: the button's registered name (e.g. "terminal", "ai").
    button_clicked = Signal(str)

    def __init__(self, parent=None):
        """
        Initialize the tool stripe.

        :param QWidget parent: Optional parent.
        """
        super().__init__(parent)

        # Button registry: name -> ToolStripeButton.
        self._buttons = {}

        # Fixed width: button width + 4px padding on each side.
        self.setFixedWidth(STRIPE_WIDTH + 8)

        # Vertical layout with buttons at the top, stretch at the bottom.
        # 4px horizontal margins give the buttons breathing room.
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)
        self._layout.addStretch()

        # Background color for the stripe.
        self.setStyleSheet("background-color: {};".format(STRIPE_BG))

    def add_button(self, name, icon, tooltip="", bottom=False):
        """
        Add an icon button to the stripe.

        By default buttons stack at the top (above the stretch).
        Pass ``bottom=True`` to place the button below the stretch,
        pinning it to the bottom of the stripe.

        :param str name: Internal name used to identify the button in
            ``button_clicked`` signals and ``set_button_active()`` calls.
        :param QIcon icon: Icon to display on the button.
        :param str tooltip: Tooltip text shown on hover.
        :param bool bottom: If True, place the button at the bottom of
            the stripe instead of the top.
        :return: The created button widget.
        :rtype: ToolStripeButton
        """
        btn = ToolStripeButton(self)
        btn.setIcon(icon)
        if tooltip:
            btn.setToolTip(tooltip)

        # Connect click to emit the button_clicked signal with its name.
        # QPushButton.clicked emits a bool (checked state) — capture it so
        # the lambda signature matches.
        btn.clicked.connect(lambda _checked=False, n=name: self.button_clicked.emit(n))

        if bottom:
            # Append after the stretch — pins the button to the bottom.
            self._layout.addWidget(btn)
        else:
            # Insert before the stretch so buttons stack at the top.
            stretch_index = self._layout.count() - 1
            self._layout.insertWidget(stretch_index, btn)

        self._buttons[name] = btn
        return btn

    def set_button_active(self, name, active):
        """
        Toggle the highlight state of a button by name.

        :param str name: The button's registered name.
        :param bool active: True for active (highlighted), False for inactive.
        """
        btn = self._buttons.get(name)
        if btn:
            btn.set_active(active)

    def is_button_active(self, name):
        """
        Check whether a button is in the active state.

        :param str name: The button's registered name.
        :return: True if the button is active, False otherwise.
        :rtype: bool
        """
        btn = self._buttons.get(name)
        return btn.is_active() if btn else False

    def get_button(self, name):
        """
        Get a button widget by name.

        :param str name: The button's registered name.
        :return: The button widget, or None.
        :rtype: ToolStripeButton or None
        """
        return self._buttons.get(name)
