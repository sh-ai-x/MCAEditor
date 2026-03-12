"""
MCA Qt - PySide2/PySide6 Compatibility Shim.

Detects which PySide version is available (prefers PySide6) and provides
a unified import surface. All Qt-using modules in the MCA Editor should
import from this module instead of PySide directly.

Key compatibility patches applied when running under PySide2:
    - Scoped enum aliases (e.g. QPalette.ColorRole.Window)
    - QAction location (QtGui in PySide6 vs QtWidgets in PySide2)
    - QKeyCombination shim
    - QApplication.exec() alias for PySide2's exec_()
    - Missing enum entries added where needed

Dependencies:
    - PySide6 >= 6.5.0 (preferred)
    - OR PySide2 >= 5.15.0 (Maya 2024 and earlier)
"""

import logging

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Detect available PySide version ----------------------------------------

# Prefer PySide6, fall back to PySide2 for older Maya.
PYSIDE_VERSION = None

try:
    import PySide6
    PYSIDE_VERSION = 6
    logger.debug("Using PySide6 (%s)", PySide6.__version__)
except ImportError:
    try:
        import PySide2
        PYSIDE_VERSION = 2
        logger.debug("Using PySide2 (%s)", PySide2.__version__)
    except ImportError:
        raise ImportError(
            "MCA Editor requires PySide6 or PySide2. "
            "Install with: pip install PySide6"
        )


# --- PySide6 imports (direct passthrough) -----------------------------------

if PYSIDE_VERSION == 6:
    # QtWidgets
    from PySide6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QHBoxLayout, QWidget,
        QListWidget, QStackedWidget, QGroupBox, QCheckBox, QSpinBox,
        QComboBox, QLabel, QLineEdit, QPushButton, QListWidgetItem,
        QFileDialog, QAbstractItemView, QFontComboBox, QTextEdit,
        QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QMainWindow,
        QSplitter, QTabWidget, QTabBar, QToolBar, QStatusBar, QMessageBox,
        QFormLayout, QDialogButtonBox, QInputDialog, QScrollArea,
        QFrame, QMenuBar, QMenu, QToolTip, QColorDialog,
    )

    # QtCore
    from PySide6.QtCore import (
        Qt, QSize, QPoint, Signal, QRect, QTimer, QFileSystemWatcher,
        QEvent, QObject, QThread,
    )

    # QKeyCombination exists natively in PySide6.
    from PySide6.QtCore import QKeyCombination

    # QtGui — in PySide6, QAction lives in QtGui.
    from PySide6.QtGui import (
        QPalette, QColor, QFont, QFontDatabase, QFontMetricsF, QKeySequence,
        QPainter, QTextFormat, QSyntaxHighlighter, QTextCharFormat,
        QTextCursor, QAction, QActionGroup,
        QIcon, QPixmap, QPen, QPainterPath, QTextOption,
        QDrag, QMovie,
    )

    # Additional QtCore imports for drag-and-drop support.
    from PySide6.QtCore import QMimeData, QByteArray


# --- PySide2 imports with compat patches ------------------------------------

else:
    # QtWidgets — most imports are identical.
    from PySide2.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QHBoxLayout, QWidget,
        QListWidget, QStackedWidget, QGroupBox, QCheckBox, QSpinBox,
        QComboBox, QLabel, QLineEdit, QPushButton, QListWidgetItem,
        QFileDialog, QAbstractItemView, QFontComboBox, QTextEdit,
        QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QMainWindow,
        QSplitter, QTabWidget, QTabBar, QToolBar, QStatusBar, QMessageBox,
        QFormLayout, QDialogButtonBox, QInputDialog, QScrollArea,
        QFrame, QMenuBar, QMenu, QToolTip, QColorDialog,
    )

    # In PySide2, QAction and QActionGroup live in QtWidgets.
    from PySide2.QtWidgets import QAction, QActionGroup

    # QtCore
    from PySide2.QtCore import (
        Qt, QSize, QPoint, Signal, QRect, QTimer, QFileSystemWatcher,
        QEvent, QObject, QThread,
    )

    # QtGui
    from PySide2.QtGui import (
        QPalette, QColor, QFont, QFontDatabase, QFontMetricsF, QKeySequence,
        QPainter, QTextFormat, QSyntaxHighlighter, QTextCharFormat,
        QTextCursor,
        QIcon, QPixmap, QPen, QPainterPath, QTextOption,
        QDrag, QMovie,
    )

    # Additional QtCore imports for drag-and-drop support.
    from PySide2.QtCore import QMimeData, QByteArray

    # -----------------------------------------------------------------------
    # PySide2 Compatibility Patches
    # -----------------------------------------------------------------------

    # --- QKeyCombination shim -----------------------------------------------
    # PySide6 requires QKeyCombination(modifiers, key) for keyboard combos.
    # PySide2 doesn't have this class, so we provide a thin wrapper that
    # returns a QKeySequence-compatible value using the old int-OR approach.

    class QKeyCombination:
        """
        Shim for PySide6's QKeyCombination on PySide2.

        :param modifiers: Qt.KeyboardModifier flags.
        :param key: Qt.Key value.
        """
        def __init__(self, modifiers, key):
            self._combined = int(modifiers) | int(key)

        def toCombined(self):
            """Return the combined integer value."""
            return self._combined

        def __int__(self):
            return self._combined

    # --- Patch exec() aliases -----------------------------------------------
    # PySide2 uses exec_() because 'exec' was a keyword in Python 2.
    # PySide6 uses exec().  We add exec() as a thin wrapper that calls
    # exec_() on the instance.  Must call via self.exec_() (bound method),
    # NOT via an unbound class method reference — Shiboken2 doesn't handle
    # explicit self passing for C++ methods.
    if not hasattr(QApplication, "exec"):
        QApplication.exec = lambda self=None: QApplication.exec_()

    if not hasattr(QDialog, "exec"):
        QDialog.exec = lambda self: self.exec_()

    if not hasattr(QMenu, "exec"):
        QMenu.exec = lambda self, *args: self.exec_(*args)

    # QDrag.exec() also needs patching (used in drag-and-drop).
    try:
        from PySide2.QtGui import QDrag as _QDrag
        if not hasattr(_QDrag, "exec"):
            _QDrag.exec = lambda self, *args: self.exec_(*args)
    except (ImportError, AttributeError):
        pass

    # --- Scoped Enum Patches ------------------------------------------------
    # PySide6 uses scoped enums (e.g. Qt.AlignmentFlag.AlignLeft) while
    # PySide2 uses flat enums (Qt.AlignLeft). We patch PySide2 classes to
    # accept the PySide6 scoped style so code can be written once.

    _patch_applied = False

    def _apply_enum_patches():
        """
        Add PySide6-style scoped enum aliases to PySide2 classes.

        This function is idempotent — calling it multiple times is safe.
        """
        global _patch_applied
        if _patch_applied:
            return
        _patch_applied = True

        # --- Qt namespace enums ---
        _patch_enum_group(Qt, "AlignmentFlag", [
            "AlignLeft", "AlignRight", "AlignHCenter", "AlignVCenter",
            "AlignTop", "AlignBottom", "AlignCenter",
        ])
        _patch_enum_group(Qt, "Orientation", ["Horizontal", "Vertical"])
        _patch_enum_group(Qt, "ItemFlag", [
            "NoItemFlags",
            "ItemIsSelectable", "ItemIsEditable", "ItemIsEnabled",
            "ItemIsUserCheckable", "ItemIsDragEnabled", "ItemIsDropEnabled",
        ])
        _patch_enum_group(Qt, "ItemDataRole", [
            "DisplayRole", "EditRole", "DecorationRole", "ToolTipRole",
            "StatusTipRole", "WhatsThisRole", "UserRole",
        ])
        _patch_enum_group(Qt, "KeyboardModifier", [
            "NoModifier", "ShiftModifier", "ControlModifier", "AltModifier",
            "MetaModifier", "KeypadModifier", "GroupSwitchModifier",
        ])
        _patch_enum_group(Qt, "Key", [
            "Key_Return", "Key_Enter", "Key_Tab", "Key_Backtab",
            "Key_Backspace", "Key_Escape", "Key_Delete", "Key_Insert",
            "Key_Home", "Key_End", "Key_Left", "Key_Up", "Key_Right",
            "Key_Down", "Key_PageUp", "Key_PageDown", "Key_Slash",
            "Key_Space", "Key_BracketLeft", "Key_BracketRight",
            "Key_BraceLeft", "Key_BraceRight", "Key_ParenLeft",
            "Key_ParenRight", "Key_QuoteDbl", "Key_Apostrophe",
        ])
        _patch_enum_group(Qt, "WidgetAttribute", [
            "WA_DeleteOnClose", "WA_DontShowOnScreen",
            "WA_TransparentForMouseEvents", "WA_NoSystemBackground",
        ])
        _patch_enum_group(Qt, "WindowType", [
            "Window", "Dialog", "Widget", "Popup", "ToolTip", "FramelessWindowHint",
        ])
        _patch_enum_group(Qt, "ScrollBarPolicy", [
            "ScrollBarAsNeeded", "ScrollBarAlwaysOff", "ScrollBarAlwaysOn",
        ])
        _patch_enum_group(Qt, "FocusPolicy", [
            "NoFocus", "TabFocus", "ClickFocus", "StrongFocus", "WheelFocus",
        ])
        _patch_enum_group(Qt, "FocusReason", [
            "MouseFocusReason", "TabFocusReason", "BacktabFocusReason",
            "ActiveWindowFocusReason", "PopupFocusReason", "ShortcutFocusReason",
            "MenuBarFocusReason", "OtherFocusReason",
        ])
        _patch_enum_group(Qt, "CheckState", [
            "Unchecked", "PartiallyChecked", "Checked",
        ])
        _patch_enum_group(Qt, "CursorShape", [
            "ArrowCursor", "UpArrowCursor", "CrossCursor", "WaitCursor",
            "IBeamCursor", "SizeVerCursor", "SizeHorCursor", "SizeBDiagCursor",
            "SizeFDiagCursor", "SizeAllCursor", "BlankCursor", "SplitVCursor",
            "SplitHCursor", "PointingHandCursor", "ForbiddenCursor",
            "WhatsThisCursor", "BusyCursor", "OpenHandCursor", "ClosedHandCursor",
        ])
        _patch_enum_group(Qt, "GlobalColor", [
            "color0", "color1", "black", "white", "darkGray", "gray",
            "lightGray", "red", "green", "blue", "cyan", "magenta", "yellow",
            "darkRed", "darkGreen", "darkBlue", "darkCyan", "darkMagenta",
            "darkYellow", "transparent",
        ])
        _patch_enum_group(Qt, "ShortcutContext", [
            "WidgetShortcut", "WindowShortcut", "ApplicationShortcut",
            "WidgetWithChildrenShortcut",
        ])
        _patch_enum_group(Qt, "MouseButton", [
            "NoButton", "LeftButton", "RightButton", "MiddleButton",
        ])
        _patch_enum_group(Qt, "TextInteractionFlag", [
            "TextSelectableByMouse", "TextSelectableByKeyboard",
            "LinksAccessibleByMouse", "LinksAccessibleByKeyboard",
            "TextEditable", "TextEditorInteraction", "TextBrowserInteraction",
        ])
        _patch_enum_group(Qt, "HighDpiScaleFactorRoundingPolicy", [
            "PassThrough", "Round", "Ceil", "Floor", "RoundPreferFloor",
        ])
        _patch_enum_group(Qt, "ContextMenuPolicy", [
            "NoContextMenu", "DefaultContextMenu", "ActionsContextMenu",
            "CustomContextMenu", "PreventContextMenu",
        ])
        _patch_enum_group(Qt, "TextElideMode", [
            "ElideLeft", "ElideRight", "ElideMiddle", "ElideNone",
        ])
        _patch_enum_group(Qt, "TextFormat", [
            "PlainText", "RichText", "AutoText", "MarkdownText",
        ])
        _patch_enum_group(Qt, "Corner", [
            "TopLeftCorner", "TopRightCorner",
            "BottomLeftCorner", "BottomRightCorner",
        ])

        # --- QPalette enums ---
        _patch_enum_group(QPalette, "ColorRole", [
            "Window", "WindowText", "Base", "AlternateBase",
            "ToolTipBase", "ToolTipText", "Text", "Button",
            "ButtonText", "BrightText", "Link", "Highlight",
            "HighlightedText", "PlaceholderText",
        ])
        _patch_enum_group(QPalette, "ColorGroup", [
            "Active", "Disabled", "Inactive", "Normal",
        ])

        # --- QTextCursor enums ---
        _patch_enum_group(QTextCursor, "MoveOperation", [
            "NoMove", "Start", "Up", "StartOfLine", "StartOfBlock",
            "StartOfWord", "PreviousBlock", "PreviousCharacter",
            "PreviousWord", "Left", "WordLeft", "End", "Down",
            "EndOfLine", "EndOfWord", "EndOfBlock", "NextBlock",
            "NextCharacter", "NextWord", "Right", "WordRight",
        ])
        _patch_enum_group(QTextCursor, "MoveMode", [
            "MoveAnchor", "KeepAnchor",
        ])
        _patch_enum_group(QTextCursor, "SelectionType", [
            "WordUnderCursor", "LineUnderCursor", "BlockUnderCursor",
            "Document",
        ])

        # --- QTextFormat enum ---
        _patch_enum_group(QTextFormat, "Property", [
            "FullWidthSelection",
        ])

        # --- QPlainTextEdit enums ---
        _patch_enum_group(QPlainTextEdit, "LineWrapMode", [
            "NoWrap", "WidgetWidth",
        ])

        # --- QMessageBox enums ---
        _patch_enum_group(QMessageBox, "StandardButton", [
            "Ok", "Cancel", "Yes", "No", "Save", "Discard",
            "Close", "Apply", "Reset", "Help",
        ])

        # --- QDialogButtonBox enums ---
        _patch_enum_group(QDialogButtonBox, "StandardButton", [
            "Ok", "Cancel", "Apply", "Close", "Help", "Yes", "No",
            "Save", "Discard", "Reset",
        ])

        # --- QDialog enums ---
        _patch_enum_group(QDialog, "DialogCode", [
            "Accepted", "Rejected",
        ])

        # --- QAbstractItemView enums ---
        _patch_enum_group(QAbstractItemView, "SelectionMode", [
            "NoSelection", "SingleSelection", "MultiSelection",
            "ExtendedSelection", "ContiguousSelection",
        ])

        # --- QSplitter enums (via QFrame base) ---
        # These are inherited but we patch them directly.

        # --- QKeySequence enums ---
        _patch_enum_group(QKeySequence, "StandardKey", [
            "Copy", "Cut", "Paste", "Undo", "Redo", "SelectAll",
            "Find", "FindNext", "FindPrevious", "Save", "New", "Open",
            "Close", "Print", "ZoomIn", "ZoomOut",
        ])

        # --- Qt.AspectRatioMode / Qt.TransformationMode (used by icon scaling) ---
        _patch_enum_group(Qt, "AspectRatioMode", [
            "IgnoreAspectRatio", "KeepAspectRatio", "KeepAspectRatioByExpanding",
        ])
        _patch_enum_group(Qt, "TransformationMode", [
            "FastTransformation", "SmoothTransformation",
        ])

        # --- QPainter.RenderHint (used by diagnostic gutter dots for anti-aliasing) ---
        _patch_enum_group(QPainter, "RenderHint", [
            "Antialiasing", "TextAntialiasing", "SmoothPixmapTransform",
        ])

        # --- Qt.PenStyle enums (used by diagnostic gutter dots) ---
        _patch_enum_group(Qt, "PenStyle", [
            "NoPen", "SolidLine", "DashLine", "DotLine",
        ])

        # --- QTextCharFormat.UnderlineStyle (used by diagnostic underlines) ---
        _patch_enum_group(QTextCharFormat, "UnderlineStyle", [
            "NoUnderline", "SingleUnderline", "DashUnderline",
            "DotLine", "DashDotLine", "DashDotDotLine", "WaveUnderline",
            "SpellCheckUnderline",
        ])

        # --- QEvent.Type enums (used by diagnostic tooltip hover and drag-drop) ---
        _patch_enum_group(QEvent, "Type", [
            "ToolTip", "MouseMove", "KeyPress", "KeyRelease",
            "FocusIn", "FocusOut", "Enter", "Leave",
            "DragEnter", "DragMove", "DragLeave", "Drop",
            "MouseButtonDblClick", "MouseButtonPress", "MouseButtonRelease",
            "Resize", "ShortcutOverride", "WindowActivate",
        ])

        # --- Qt.DropAction enums (used by drag-and-drop tab splitting) ---
        _patch_enum_group(Qt, "DropAction", [
            "MoveAction", "IgnoreAction", "CopyAction",
        ])

        logger.debug("PySide2 enum compatibility patches applied")

    def _patch_enum_group(cls, group_name, members):
        """
        Add a scoped enum namespace to a PySide2 class.

        Creates a simple namespace object on *cls* named *group_name*
        containing all *members* looked up from *cls* (or Qt for
        inherited enums).

        :param type cls: The class to patch (e.g. Qt, QPalette).
        :param str group_name: Name for the enum group (e.g. "ColorRole").
        :param list members: Attribute names to include.
        """
        # Skip if already patched.
        if hasattr(cls, group_name):
            existing = getattr(cls, group_name)
            # If it's already a proper enum group (not a single value), skip.
            if hasattr(existing, "__dict__") and any(hasattr(existing, m) for m in members[:1]):
                return

        # Build a namespace object with all the enum values.
        ns = type(group_name, (), {})
        for member in members:
            val = getattr(cls, member, None)
            if val is not None:
                setattr(ns, member, val)

        setattr(cls, group_name, ns)

    # Apply patches immediately on import.
    _apply_enum_patches()
