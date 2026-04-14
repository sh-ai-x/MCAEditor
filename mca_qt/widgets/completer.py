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
import sys
import logging
import importlib
import pkgutil

from mca_qt.qt_compat import (
    QFrame, QListWidget, QListWidgetItem, QVBoxLayout,
    QTimer, Qt, QPoint, QWidget, QApplication, QEvent, QObject,
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

# --- Import-Context Regexes -------------------------------------------------
# These match the line before the cursor to detect that the user is typing
# an import statement.  Completion behavior branches based on which context
# fires.

# Matches "from X.Y.Z import " with the cursor positioned at the end
# (possibly after a comma-separated list of previously-imported names).
# Group 1 captures the source module path (e.g. "mca.common.paths").
# Group 2 captures the partial name being typed (may be empty).
_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+([\w\.]+)\s+import\s+(?:[\w\s,]*?,\s*)?(\w*)$"
)

# Matches "from X.Y" or "from X.Y." — cursor is in the source-module
# portion of a "from ... import ..." statement, BEFORE "import".
# Group 1 captures everything after "from " up to the cursor.
_FROM_MODULE_RE = re.compile(r"^\s*from\s+([\w\.]*)$")

# Matches "import X.Y" or "import X.Y." — cursor is in the module path
# of a plain "import ..." statement.
# Group 1 captures the module path up to the cursor.
_IMPORT_MODULE_RE = re.compile(
    r"^\s*import\s+(?:[\w\.\s,]*?,\s*)?([\w\.]*)$"
)


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
        # Optional project-wide symbol index (set when a project is opened).
        self._symbol_index = None
        # Cache of import results so each module is imported at most once
        # per session.  Maps fully-qualified module name to either the
        # imported module object or None (on import failure, to avoid
        # retrying).  Without this, every keystroke in an import line
        # re-runs module-level code in the target package.
        self._module_cache = {}
        # Cache of the per-module name lists so we don't rebuild the
        # list of public attributes + submodules on every keystroke.
        self._module_names_cache = {}

    def _import_module_cached(self, module_name):
        """
        Import a module by fully-qualified name, memoizing the result.

        Running ``importlib.import_module`` on every keystroke would
        re-execute the top-level code of every package the user is
        typing into.  The cache stores both successful imports and
        failures (as None) so repeated lookups are O(1).

        :param str module_name: Dotted module path, e.g. ``"mca.common.paths"``.
        :return: The imported module, or ``None`` if the import failed
            or the name is empty.
        :rtype: module or None
        """
        # Reject empty names up front so we don't poison the cache.
        if not module_name:
            return None

        if module_name in self._module_cache:
            return self._module_cache[module_name]

        try:
            # import_module walks the full dotted path and executes
            # each package's __init__, so "mca.common.paths" loads
            # mca → mca.common → mca.common.paths correctly.
            mod = importlib.import_module(module_name)
        except Exception as exc:
            # Cache the failure so we don't keep retrying.
            logger.debug(
                "Module import failed for %r: %s", module_name, exc
            )
            self._module_cache[module_name] = None
            return None

        self._module_cache[module_name] = mod
        return mod

    def _list_module_names(self, module_name):
        """
        Return all public names offered by a module for completion.

        For a regular module, returns every non-dunder attribute listed
        in ``dir(mod)``.  For a package, also appends the names of all
        direct submodules discovered via ``pkgutil.iter_modules`` — so
        ``mca.common`` offers ``paths`` even before anyone has done
        ``import mca.common.paths``.

        :param str module_name: Dotted module path to inspect.
        :return: Sorted list of unique public names.
        :rtype: list
        """
        # Serve from cache if available — callers hit this once per
        # keystroke while the prefix narrows.
        if module_name in self._module_names_cache:
            return self._module_names_cache[module_name]

        mod = self._import_module_cached(module_name)
        if mod is None:
            self._module_names_cache[module_name] = []
            return []

        names = set()

        # Collect non-dunder attributes that the module already exposes.
        # Skip re-exported submodule proxies — pkgutil picks those up
        # more reliably and marks them with priority correctly.
        for attr in dir(mod):
            if attr.startswith("__"):
                continue
            names.add(attr)

        # If this is a package (has __path__), enumerate its submodules.
        # iter_modules only walks the immediate package — does NOT
        # descend into sub-packages, which is what we want (one dot at
        # a time matches how users type imports).
        pkg_path = getattr(mod, "__path__", None)
        if pkg_path:
            try:
                for finder, name, ispkg in pkgutil.iter_modules(pkg_path):
                    # Filter out private submodules (leading underscore).
                    if name.startswith("_"):
                        continue
                    names.add(name)
            except Exception as exc:
                # Some loaders don't support iter_modules (namespace
                # packages in zip archives, for example) — fall back
                # to just the dir() results.
                logger.debug(
                    "pkgutil.iter_modules failed for %r: %s",
                    module_name, exc
                )

        sorted_names = sorted(names)
        self._module_names_cache[module_name] = sorted_names
        return sorted_names

    def _module_path_completions(self, typed):
        """
        Produce completion items for a dotted module path being typed
        in an ``import`` or ``from ... import`` statement.

        ``typed`` is the raw text the user has keyed so far, e.g.
        ``"mca.common."``, ``"mca.common.pa"``, or ``""``.  This helper
        figures out which package to list submodules of and which
        prefix to filter by.

        :param str typed: The dotted module path the user has typed.
        :return: List of CompletionItem for matching submodules.
        :rtype: list
        """
        # Empty input — nothing to complete.  The caller may still
        # want to offer top-level packages, but we don't have a sane
        # universe to enumerate without scanning sys.path.
        if not typed:
            return []

        # Trailing dot means the user wants to see children of the
        # current package (e.g. "mca.common." → children of mca.common).
        # No trailing dot means they're extending the last segment
        # (e.g. "mca.common.pa" → children of mca.common filtered by "pa").
        if typed.endswith("."):
            parent = typed[:-1]
            name_prefix = ""
        elif "." in typed:
            parent, _, name_prefix = typed.rpartition(".")
        else:
            # Single-segment input (no dot yet).  Can't enumerate
            # top-level packages cheaply, so skip.
            return []

        if not parent:
            return []

        items = []
        for name in self._list_module_names(parent):
            if not name.startswith(name_prefix):
                continue
            items.append(CompletionItem(
                label=name,
                detail="module",
                insert_text=name,
                priority=0,
            ))
        return items

    def set_symbol_index(self, index):
        """
        Attach or detach the project symbol index.

        Called when a project is opened (attach) or closed (detach).
        When attached, completions include class/function/proc names
        from all indexed files in the workspace.

        :param SymbolIndex index: The symbol index, or None to detach.
        """
        self._symbol_index = index

    def get_completions(self, prefix, language, document_text="",
                        known_globals=None, line_before_cursor=""):
        """
        Gather completions from all sources for the given prefix.

        :param str prefix: The full prefix text (e.g. "cmds.pol" or "pri").
        :param str language: Current language ("python" or "mel").
        :param str document_text: Full text of the current document for
            word scanning.
        :param set known_globals: Optional set of names imported in other
            open tabs (cross-tab completion).
        :param str line_before_cursor: Text of the current line from the
            start up to the cursor position.  Used to detect import-
            statement contexts so we can offer module names instead of
            arbitrary attributes.
        :return: Deduplicated, sorted list of CompletionItem instances.
        :rtype: list
        """
        seen = set()
        items = []

        # --- Source 0: Import-statement context (Python only) ------------
        # These branches run BEFORE the adapter so import completions
        # show correctly even when Maya is connected but doesn't know
        # about the user's project modules.  Each branch is mutually
        # exclusive and returns early after adding its completions.
        if language == "python" and line_before_cursor:
            # --- "from X.Y.Z import <cursor>" case -----------------
            # User has fully typed "from MODULE import " and is now
            # typing the name(s) to import.  Offer both public
            # attributes AND submodules of MODULE.
            m = _FROM_IMPORT_RE.match(line_before_cursor)
            if m:
                src_module = m.group(1)
                name_prefix = m.group(2) or ""
                candidate_names = self._list_module_names(src_module)
                for name in candidate_names:
                    if name.startswith(name_prefix) and name not in seen:
                        seen.add(name)
                        items.append(CompletionItem(
                            label=name,
                            detail="from " + src_module,
                            insert_text=name,
                            priority=0,
                        ))
                # Import context is exclusive — skip all other sources
                # so we don't pollute the list with unrelated words.
                items.sort(key=lambda i: (i.priority, i.label.lower()))
                return items

            # --- "from X.Y." or "from X.<partial>" case ------------
            # User is typing the source module path of a "from ..."
            # statement.  Offer submodules that extend the current
            # dotted path.
            m = _FROM_MODULE_RE.match(line_before_cursor)
            if m:
                typed = m.group(1)
                submodule_items = self._module_path_completions(typed)
                for item in submodule_items:
                    if item.label not in seen:
                        seen.add(item.label)
                        items.append(item)
                items.sort(key=lambda i: (i.priority, i.label.lower()))
                return items

            # --- "import X.Y." case --------------------------------
            # Plain "import PATH" — offer submodules of the current
            # dotted path.  Handles comma-separated imports like
            # "import os, sys.pa" by matching only the final segment.
            m = _IMPORT_MODULE_RE.match(line_before_cursor)
            if m:
                typed = m.group(1)
                submodule_items = self._module_path_completions(typed)
                for item in submodule_items:
                    if item.label not in seen:
                        seen.add(item.label)
                        items.append(item)
                items.sort(key=lambda i: (i.priority, i.label.lower()))
                return items

        # --- Source 1: DCC adapter (priority 0) ---
        adapter = self._adapter_manager.get_active_adapter() if self._adapter_manager else None
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

        # --- Source 1b: Module import fallback for dotted prefixes ---
        # When the adapter didn't return results for a dotted prefix
        # (e.g. "os.pa" where os hasn't been executed), resolve the
        # module via importlib (loads the full dotted chain) and list
        # both its public attributes and its submodules.  Works for
        # stdlib and any installed package regardless of adapter state.
        if "." in prefix and language == "python":
            adapter_count = sum(1 for i in items if i.priority == 0)
            if adapter_count == 0:
                obj_part = prefix.rsplit(".", 1)[0]
                attr_prefix = prefix.rsplit(".", 1)[1]
                # _list_module_names handles both attributes and
                # submodules (via pkgutil) and caches the result so
                # this stays cheap across keystrokes.
                candidate_names = self._list_module_names(obj_part)
                matching = [
                    n for n in candidate_names
                    if n.startswith(attr_prefix)
                ]
                for attr in matching[:500]:
                    if attr not in seen:
                        seen.add(attr)
                        items.append(CompletionItem(
                            label=attr, detail="module",
                            insert_text=attr,
                            priority=0,
                        ))

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

        # --- Source 3: Project symbols from SymbolIndex (priority 2) ---
        # Offers class/function/proc names from all .py files in the
        # workspace.  Only active when a project is open and the index
        # has finished building.  Skips dotted prefixes (e.g. "os.pa")
        # since the index stores bare names, not attributes.
        if self._symbol_index and "." not in prefix:
            try:
                for name, kind, filepath in self._symbol_index.find_by_prefix(prefix):
                    if name not in seen:
                        seen.add(name)
                        items.append(CompletionItem(
                            label=name,
                            detail=kind,
                            priority=2,
                        ))
            except Exception as exc:
                logger.debug("Symbol index completions failed: %s", exc)

        # --- Source 4: Cross-tab imported names (priority 2) ---
        # Names imported in other open tabs are offered so autocomplete
        # works across the editing session — e.g. "import os" in tab A
        # makes "os" appear as a suggestion in tab B.
        if known_globals and "." not in prefix:
            filter_prefix = prefix.lower()
            for name in sorted(known_globals):
                if name.lower().startswith(filter_prefix) and name not in seen:
                    seen.add(name)
                    items.append(CompletionItem(
                        label=name, detail="cross-tab",
                        priority=2,
                    ))

        # --- Source 5: Document words (priority 3) ---
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
                        priority=3,
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

        # Current completion items (CompletionItem list) — full unfiltered set.
        self._items = []
        # Currently visible (filtered) items — matches the QListWidget rows.
        self._visible_items = []
        # Whether the popup is currently showing an active completion session.
        self._active = False
        # macOS native window fix — see _show_items() for details.
        self._mac_native_ready = False

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

        # --- Dismiss on click-away ---
        # In Maya's embedded Qt, focusOutEvent and focusChanged don't
        # always fire when the user clicks a different panel.  An
        # application-level event filter catches ALL mouse presses and
        # dismisses the popup if the click lands outside the completer
        # and the editor.
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

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
        self._visible_items = []
        self._list.clear()
        self.hide()

    def eventFilter(self, obj, event):
        """
        Application-level event filter to dismiss on click-away.

        Catches mouse presses anywhere in the application.  If the
        click is outside the completer popup and the editor, dismiss.

        :param QObject obj: The object that received the event.
        :param QEvent event: The event.
        :return: False (never consume the event).
        :rtype: bool
        """
        if not self._active:
            return False

        if event.type() == QEvent.Type.MouseButtonPress:
            # Check if the click target is inside the completer or editor.
            if obj is self or obj is self._list or obj is self._editor:
                return False
            # Also check if obj is a child of the completer (scrollbar, etc.).
            widget = obj if isinstance(obj, QWidget) else None
            if widget:
                parent = widget.parent()
                while parent:
                    if parent is self or parent is self._editor:
                        return False
                    parent = parent.parent()
            # Click landed elsewhere — dismiss the popup.
            self.dismiss()

        return False

    def accept_completion(self):
        """
        Insert the currently selected completion item into the editor
        and dismiss the popup.
        """
        current = self._list.currentItem()
        if not current:
            self.dismiss()
            return

        # Use _visible_items (matches the QListWidget rows) not _items
        # (the full unfiltered set).  Using _items here caused the wrong
        # completion to be inserted after filtering narrowed the list.
        row = self._list.row(current)
        if row < 0 or row >= len(self._visible_items):
            self.dismiss()
            return

        item = self._visible_items[row]
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

        # Collect names imported in other open tabs so autocomplete
        # works across the editing session (e.g. "import os" in tab A
        # makes "os" completable in tab B).
        known_globals = None
        if hasattr(self._editor, '_known_globals_provider') and self._editor._known_globals_provider:
            try:
                known_globals = self._editor._known_globals_provider()
            except Exception:
                pass

        # Gather completions from all sources.
        language = self._editor.language
        document_text = self._editor.toPlainText()

        # Capture the text from the start of the current line up to the
        # cursor so the provider can detect import-statement context
        # ("from X import ...", "import X.Y.", etc.).  Without this,
        # the provider can't tell that a bare "paths" identifier should
        # be resolved against the source module in a from-import line.
        cursor = self._editor.textCursor()
        line_before_cursor = cursor.block().text()[:cursor.positionInBlock()]

        items = self._provider.get_completions(
            full_prefix, language, document_text,
            known_globals=known_globals,
            line_before_cursor=line_before_cursor,
        )

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
        # Track which items are visible so accept_completion() indexes
        # into the right list (not the full unfiltered _items).
        self._visible_items = items

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

        # On macOS, the completer is created during Maya startup before
        # the window system is fully initialized.  The ToolTip-type
        # NSWindow gets created in a state where it never becomes
        # visible.  Re-setting the window flags forces Qt to destroy
        # and recreate the native window, which fixes the issue.
        # Only needed once — after the first recreation, subsequent
        # show/hide cycles work normally.
        if sys.platform == "darwin" and not self._mac_native_ready:
            self.setWindowFlags(self.windowFlags())
            self._mac_native_ready = True

        self._active = True
        self.show()
        self.raise_()

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
        Clean up timers and event filters. Called when the editor tab
        is closed or during panel shutdown.

        Removes the application-level event filter installed in __init__
        and stops the debounce timer.  Without this, orphaned completers
        accumulate on QApplication's event filter chain — during Maya
        shutdown, shiboken destructors fire on these orphaned QWidgets
        and hit freed C++ memory (ACCESS_VIOLATION).
        """
        self._delay_timer.stop()

        # Remove our app-level event filter so QApplication no longer
        # holds a reference to this (possibly orphaned) widget.
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
