"""
MCA Qt - Code Completion Widget.

Provides a custom auto-complete popup for the code editor. Uses a QFrame
with ToolTip window flags so it floats above the editor without stealing
focus. Completions are gathered from three sources:

    1. DCC adapter (``get_completions()``) — Maya commands, ``dir()`` results
    2. Static keyword/builtin lists — same word lists the syntax highlighters use
    3. Document words — regex scan of identifiers in the current buffer

Dependencies:
    - PySide6 (QFrame, QListWidget, QTimer, etc.)
    - mca_core.config.settings.MCASettings (for auto-complete toggles)
"""

import re
import logging

from mca_qt.qt_compat import (
    QFrame, QListWidget, QListWidgetItem, QVBoxLayout,
    QTimer, Qt, QPoint, QWidget,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Static Word Lists -------------------------------------------------------
# These mirror the exact lists used by PythonHighlighter and MELHighlighter
# in code_editor.py. Kept as module-level tuples for fast filtering.

PYTHON_KEYWORDS = (
    "and", "as", "assert", "async", "await", "break", "class",
    "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda",
    "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
)

PYTHON_BUILTINS = (
    "True", "False", "None", "self", "cls",
    "print", "range", "len", "type", "int", "float", "str",
    "list", "dict", "tuple", "set", "bool", "bytes",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "super", "property", "staticmethod", "classmethod",
    "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "open", "input", "abs", "all", "any", "min", "max", "sum",
)

MEL_KEYWORDS = (
    "if", "else", "for", "while", "do", "in", "break", "continue",
    "return", "switch", "case", "default", "proc", "global", "local",
    "string", "int", "float", "vector", "matrix", "source", "catch",
    "true", "false", "yes", "no", "on", "off",
)

# Regex to extract identifiers from document text (3+ chars, word boundary).
_WORD_RE = re.compile(r"\b[a-zA-Z_]\w{2,}\b")


# =============================================================================
# Completion Item
# =============================================================================

class CompletionItem:
    """
    Simple data holder for a single completion suggestion.

    :param str label: Display text shown in the popup (e.g. "print").
    :param str detail: Short category text shown dimmed (e.g. "builtin").
    :param str insert_text: Text actually inserted on accept. Defaults to label.
    :param int priority: Sort bucket — lower numbers sort first.
        0 = DCC adapter, 1 = keywords/builtins, 2 = document words.
    """

    def __init__(self, label, detail="", insert_text=None, priority=2):
        """
        Initialize a completion item.

        :param str label: Display text.
        :param str detail: Category text.
        :param str insert_text: Text to insert (defaults to label).
        :param int priority: Sort priority (lower = higher rank).
        """
        self.label = label
        self.detail = detail
        self.insert_text = insert_text or label
        self.priority = priority


# =============================================================================
# Completion Provider
# =============================================================================

class CompletionProvider:
    """
    Gathers and merges completions from all available sources.

    Sources queried (in priority order):
        - DCC adapter (``get_completions()``) — priority 0
        - Static keywords/builtins — priority 1
        - Document words (regex scan) — priority 2

    Deduplicates by label, sorts by (priority, alphabetical).
    Stateless — safe to share across multiple editors.

    :param MCASettings settings: Settings instance for toggle checks.
    :param AdapterManager adapter_manager: For DCC adapter completions.
    """

    def __init__(self, settings, adapter_manager):
        """
        Initialize the provider with settings and adapter access.

        :param MCASettings settings: Settings for toggle checks.
        :param AdapterManager adapter_manager: For DCC completions.
        """
        self._settings = settings
        self._adapter_manager = adapter_manager

    def get_completions(self, prefix, language, document_text=""):
        """
        Gather completions from all sources for the given prefix.

        :param str prefix: The full prefix text (e.g. "cmds.pol" or "pri").
        :param str language: Current language ("python" or "mel").
        :param str document_text: Full text of the current document for
            word scanning.
        :return: Deduplicated, sorted list of CompletionItem instances.
        :rtype: list
        """
        seen = set()
        items = []

        # --- Source 1: DCC adapter (priority 0) ---
        adapter = self._adapter_manager.get_active_adapter()
        if adapter and adapter.is_connected:
            try:
                raw = adapter.get_completions(prefix, language)
                for entry in raw:
                    label = entry.get("label", "")
                    if label and label not in seen:
                        seen.add(label)
                        items.append(CompletionItem(
                            label=label,
                            detail=entry.get("detail", "DCC"),
                            insert_text=entry.get("insert_text", label),
                            priority=0,
                        ))
            except Exception as exc:
                logger.debug("Adapter completions failed: %s", exc)

        # --- Source 2: Static keywords/builtins (priority 1) ---
        # Figure out which part of the prefix to match against static words.
        # For dotted prefixes (e.g. "os.pa"), static keywords don't apply.
        if "." not in prefix:
            filter_prefix = prefix.lower()

            if language == "python":
                # Keywords (gated by setting).
                if self._settings.get("py_autocomplete_keywords"):
                    for kw in PYTHON_KEYWORDS:
                        if kw.lower().startswith(filter_prefix) and kw not in seen:
                            seen.add(kw)
                            items.append(CompletionItem(
                                label=kw, detail="keyword",
                                priority=1,
                            ))

                # Builtins (gated by setting).
                if self._settings.get("py_autocomplete_builtins"):
                    for bi in PYTHON_BUILTINS:
                        if bi.lower().startswith(filter_prefix) and bi not in seen:
                            seen.add(bi)
                            items.append(CompletionItem(
                                label=bi, detail="builtin",
                                priority=1,
                            ))

            elif language == "mel":
                for kw in MEL_KEYWORDS:
                    if kw.lower().startswith(filter_prefix) and kw not in seen:
                        seen.add(kw)
                        items.append(CompletionItem(
                            label=kw, detail="keyword",
                            priority=1,
                        ))

        # --- Source 3: Document words (priority 2) ---
        # Always available regardless of DCC connection. Scan the current
        # document for identifiers that match the insert prefix.
        if "." in prefix:
            # For dotted access, match the part after the last dot.
            insert_prefix = prefix.rsplit(".", 1)[1]
        else:
            insert_prefix = prefix

        if insert_prefix:
            ip_lower = insert_prefix.lower()
            for match in _WORD_RE.finditer(document_text):
                word = match.group()
                # Skip the prefix itself and words already seen from other sources.
                if word == insert_prefix or word in seen:
                    continue
                if word.lower().startswith(ip_lower):
                    seen.add(word)
                    items.append(CompletionItem(
                        label=word, detail="document",
                        priority=2,
                    ))

        # Sort by priority first, then alphabetically within each bucket.
        items.sort(key=lambda item: (item.priority, item.label.lower()))

        return items


# =============================================================================
# Code Completer (Popup Widget)
# =============================================================================

# Dark stylesheet matching the editor theme.
_COMPLETER_STYLESHEET = """
    QFrame {
        background-color: #252526;
        border: 1px solid #454545;
    }
    QListWidget {
        background-color: #252526;
        color: #d4d4d4;
        border: none;
        outline: none;
    }
    QListWidget::item {
        padding: 2px 6px;
    }
    QListWidget::item:selected {
        background-color: #094771;
        color: #ffffff;
    }
"""

# Maximum number of visible rows before scrolling.
_MAX_VISIBLE_ROWS = 10

# Width of the popup in pixels.
_POPUP_WIDTH = 380


class CodeCompleter(QFrame):
    """
    Visual auto-complete popup for the code editor.

    Appears below the text cursor, shows matching completions in a
    scrollable list, and inserts the selected item on accept. Uses
    ToolTip + FramelessWindowHint flags so the popup floats above the
    editor without stealing keyboard focus.

    :param MCACodeEditor editor: The code editor this completer is attached to.
    :param CompletionProvider provider: Shared provider that gathers completions.
    :param MCASettings settings: Settings instance for toggle checks.
    """

    def __init__(self, editor, provider, settings):
        """
        Initialize the completer popup.

        :param MCACodeEditor editor: The parent code editor widget.
        :param CompletionProvider provider: Completion provider.
        :param MCASettings settings: Settings instance.
        """
        # Parent to None so it can float as a top-level tooltip window.
        super().__init__(None)
        self._editor = editor
        self._provider = provider
        self._settings = settings

        # Current completion items (CompletionItem list).
        self._items = []
        # Whether the popup is currently showing an active completion session.
        self._active = False

        # --- Window flags: float like a tooltip, don't steal focus ---
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Double-click on an item accepts the completion.
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        self.setStyleSheet(_COMPLETER_STYLESHEET)
        self.setFixedWidth(_POPUP_WIDTH)

        # --- Debounce timer for auto-triggered completions ---
        self._delay_timer = QTimer()
        self._delay_timer.setSingleShot(True)
        self._delay_timer.timeout.connect(self._fetch_and_show)

    # --- Properties -----------------------------------------------------------

    @property
    def is_active(self):
        """
        Whether the popup is currently visible and in a completion session.

        :rtype: bool
        """
        return self._active

    # --- Public Methods -------------------------------------------------------

    def trigger(self, manual=False):
        """
        Start a completion session.

        If *manual* is True (e.g. Ctrl+Space), fetch immediately.
        Otherwise, use the debounce delay from settings.

        :param bool manual: True for manual (instant) triggering.
        """
        # Global kill switch — respect the auto_complete setting.
        if not manual and not self._settings.get("auto_complete"):
            return

        if manual:
            # Cancel any pending delayed trigger and fetch right away.
            self._delay_timer.stop()
            self._fetch_and_show()
        else:
            # Restart the debounce timer so rapid keystrokes don't spam queries.
            delay = self._settings.get("auto_complete_delay_ms")
            self._delay_timer.start(delay)

    def dismiss(self):
        """Hide the popup and end the current completion session."""
        self._delay_timer.stop()
        self._active = False
        self._items = []
        self._list.clear()
        self.hide()

    def accept_completion(self):
        """
        Insert the currently selected completion item into the editor
        and dismiss the popup.
        """
        current = self._list.currentItem()
        if not current:
            self.dismiss()
            return

        row = self._list.row(current)
        if row < 0 or row >= len(self._items):
            self.dismiss()
            return

        item = self._items[row]
        self._insert_completion(item)
        self.dismiss()

    def handle_key_event(self, event):
        """
        Process a key event while the popup is active.

        Consumes navigation keys (Up, Down, Enter, Tab, Escape) and
        returns True if the event was handled (caller should not
        propagate it further).

        :param QKeyEvent event: The key press event.
        :return: True if the event was consumed.
        :rtype: bool
        """
        if not self._active:
            return False

        key = event.key()

        # --- Navigate up in the list ---
        if key == Qt.Key.Key_Up:
            row = self._list.currentRow()
            if row > 0:
                self._list.setCurrentRow(row - 1)
            return True

        # --- Navigate down in the list ---
        if key == Qt.Key.Key_Down:
            row = self._list.currentRow()
            if row < self._list.count() - 1:
                self._list.setCurrentRow(row + 1)
            return True

        # --- Accept on Tab or Enter ---
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_completion()
            return True

        # --- Dismiss on Escape ---
        if key == Qt.Key.Key_Escape:
            self.dismiss()
            return True

        return False

    def update_filter(self):
        """
        Re-filter the current completion list after the user types more
        characters. If nothing matches, dismiss the popup.
        """
        prefix_info = self._get_completion_prefix()
        if not prefix_info:
            self.dismiss()
            return

        full_prefix, insert_prefix = prefix_info

        # If the prefix is gone (e.g. user deleted all chars), dismiss.
        if not insert_prefix and "." not in full_prefix:
            self.dismiss()
            return

        # Filter existing items by the updated insert prefix.
        ip_lower = insert_prefix.lower()
        filtered = [
            item for item in self._items
            if item.label.lower().startswith(ip_lower)
        ]

        if not filtered:
            self.dismiss()
            return

        self._show_items(filtered)

    # --- Internal Methods -----------------------------------------------------

    def _fetch_and_show(self):
        """
        Extract the completion prefix at the cursor, query the provider,
        and display results.
        """
        prefix_info = self._get_completion_prefix()
        if not prefix_info:
            self.dismiss()
            return

        full_prefix, insert_prefix = prefix_info

        # Need at least 1 character to complete (unless dot-triggered).
        if not insert_prefix and "." not in full_prefix:
            self.dismiss()
            return

        # Gather completions from all sources.
        language = self._editor.language
        document_text = self._editor.toPlainText()
        items = self._provider.get_completions(full_prefix, language, document_text)

        if not items:
            self.dismiss()
            return

        # Store the full item list (for re-filtering as user types).
        self._items = items

        # Filter down to items matching the insert prefix.
        if insert_prefix:
            ip_lower = insert_prefix.lower()
            visible = [i for i in items if i.label.lower().startswith(ip_lower)]
        else:
            visible = items

        if not visible:
            self.dismiss()
            return

        self._show_items(visible)

    def _show_items(self, items):
        """
        Populate the list widget and position/show the popup.

        :param list items: List of CompletionItem instances to display.
        """
        # Match the editor's current font so the popup feels native.
        self._list.setFont(self._editor.font())

        self._list.clear()
        for item in items:
            # Format: "label    detail" with detail right-aligned via padding.
            if item.detail:
                display = "{}    ({})".format(item.label, item.detail)
            else:
                display = item.label
            list_item = QListWidgetItem(display)
            self._list.addItem(list_item)

        # Select the first item by default.
        self._list.setCurrentRow(0)

        # Size the popup to fit the number of rows (capped at max).
        row_count = min(self._list.count(), _MAX_VISIBLE_ROWS)
        row_height = self._list.sizeHintForRow(0) if self._list.count() > 0 else 20
        # Add a small margin for the border.
        popup_height = row_count * row_height + 4
        self.setFixedHeight(popup_height)

        # Position below the cursor, flipping above if near screen bottom.
        self._position_popup()

        self._active = True
        self.show()

    def _position_popup(self):
        """
        Position the popup below the text cursor. Flips above if the
        popup would extend past the bottom edge of the screen.
        """
        cursor_rect = self._editor.cursorRect()
        # Map the cursor's bottom-left corner to global screen coordinates.
        global_pos = self._editor.mapToGlobal(
            QPoint(cursor_rect.left(), cursor_rect.bottom())
        )

        # Check if the popup would go off the bottom of the screen.
        # QWidget.screen() was added in Qt 5.14; Maya 2022 uses Qt 5.12
        # so we fall back to QApplication.primaryScreen() which is Qt 5.0+.
        screen = None
        try:
            screen = self._editor.screen()
        except AttributeError:
            pass

        if screen:
            screen_rect = screen.availableGeometry()
        else:
            from mca_qt.qt_compat import QApplication
            primary = QApplication.primaryScreen()
            screen_rect = primary.availableGeometry() if primary else None

        if screen_rect and (global_pos.y() + self.height()) > screen_rect.bottom():
            # Flip above the cursor line.
            global_pos = self._editor.mapToGlobal(
                QPoint(cursor_rect.left(), cursor_rect.top() - self.height())
            )

        # Also clamp horizontal position so it doesn't go off-screen right.
        if screen_rect and (global_pos.x() + self.width()) > screen_rect.right():
            global_pos = QPoint(
                screen_rect.right() - self.width(),
                global_pos.y()
            )

        self.move(global_pos)

    def _get_completion_prefix(self):
        """
        Extract the completion prefix at the current cursor position.

        Walks backward from the cursor collecting identifier characters
        (letters, digits, underscores) and dots.

        :return: Tuple of (full_prefix, insert_prefix) where insert_prefix
            is the part after the last dot, or None if no valid prefix.
        :rtype: tuple or None
        """
        cursor = self._editor.textCursor()
        block_text = cursor.block().text()
        col = cursor.positionInBlock()

        # Walk backward from cursor to find the start of the identifier chain.
        start = col
        while start > 0:
            ch = block_text[start - 1]
            if ch.isalnum() or ch == "_" or ch == ".":
                start -= 1
            else:
                break

        full_prefix = block_text[start:col]

        # Don't complete if we have nothing.
        if not full_prefix:
            return None

        # The insert prefix is the part after the last dot (what we'll
        # actually replace when inserting). For "cmds.pol", insert_prefix
        # is "pol"; for "pri", insert_prefix is "pri".
        if "." in full_prefix:
            insert_prefix = full_prefix.rsplit(".", 1)[1]
        else:
            insert_prefix = full_prefix

        return (full_prefix, insert_prefix)

    def _insert_completion(self, item):
        """
        Replace the insert prefix with the completion item's text.

        :param CompletionItem item: The selected completion.
        """
        prefix_info = self._get_completion_prefix()
        if not prefix_info:
            return

        full_prefix, insert_prefix = prefix_info

        cursor = self._editor.textCursor()

        # Select the insert_prefix portion (the characters to replace).
        if insert_prefix:
            cursor.movePosition(
                cursor.MoveOperation.Left,
                cursor.MoveMode.KeepAnchor,
                len(insert_prefix)
            )

        cursor.insertText(item.insert_text)
        self._editor.setTextCursor(cursor)

    def _on_item_double_clicked(self, list_item):
        """
        Handle double-click on a list item — accept the completion.

        :param QListWidgetItem list_item: The double-clicked item.
        """
        self.accept_completion()

    def cleanup(self):
        """
        Clean up timers. Called when the editor tab is closed.
        """
        self._delay_timer.stop()
