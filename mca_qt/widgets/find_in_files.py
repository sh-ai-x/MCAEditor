"""
MCA Qt - Find in Files / Replace in Files Dialog (PyCharm-style).

Provides a persistent results dialog for searching (and optionally replacing)
text across all files in the workspace.  A background ``SearchWorker`` thread
walks workspace folders, reads files as UTF-8, and emits per-file matches
to a QTreeWidget.  Double-clicking a match navigates to the file and line.

Classes:
    SearchWorker        — QThread background file search
    FindInFilesDialog   — QDialog with search controls + results tree

Dependencies:
    - PySide6 (or PySide2 via qt_compat shim)
"""

import os
import re
import logging

from mca_qt.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QCheckBox, QComboBox, QLabel, QTreeWidget, QTreeWidgetItem,
    Qt, Signal, QThread, QApplication,
)

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Shared Skip Rules -------------------------------------------------------

# Directories to skip during recursive file search (matches quick_open.py).
_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".tox", ".eggs", "dist",
    "build", ".idea", ".vs", ".vscode",
}

# Maximum directory depth for recursive scanning.
_MAX_DEPTH = 5

# Binary / non-text extensions to skip entirely.
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".png", ".jpg",
    ".jpeg", ".gif", ".bmp", ".ico", ".ttf", ".otf", ".woff", ".woff2",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".db", ".sqlite",
}


# =============================================================================
# SearchWorker (Background Thread)
# =============================================================================

class SearchWorker(QThread):
    """
    Background worker that walks workspace folders and searches files.

    For each file containing matches it emits ``match_found`` with the
    filepath and a list of (line_number, line_text) tuples.  When all
    files have been scanned, ``search_finished`` fires with the total
    match count.

    :param list workspace_folders: Folder paths to search.
    :param str pattern: The search string or regex.
    :param bool case_sensitive: Whether the search is case-sensitive.
    :param bool whole_word: Whether to match whole words only.
    :param bool use_regex: Whether *pattern* is a regular expression.
    :param str file_filter: Comma-separated glob patterns (e.g. ``"*.py, *.mel"``).
    """

    # Emitted per file: (filepath, [(line_number, line_text), ...])
    match_found = Signal(str, list)

    # Emitted at the end: (total_match_count)
    search_finished = Signal(int)

    def __init__(self, workspace_folders, pattern, case_sensitive=False,
                 whole_word=False, use_regex=False, file_filter=""):
        """
        Initialize the search worker.

        :param list workspace_folders: Folder paths to search.
        :param str pattern: Search text or regex.
        :param bool case_sensitive: Case-sensitive matching.
        :param bool whole_word: Whole-word matching.
        :param bool use_regex: Interpret pattern as regex.
        :param str file_filter: Comma-separated extension globs (e.g. ``"*.py, *.mel"``).
        """
        super().__init__()
        self._folders = workspace_folders
        self._pattern = pattern
        self._case_sensitive = case_sensitive
        self._whole_word = whole_word
        self._use_regex = use_regex
        self._file_filter = file_filter
        self._cancelled = False

    # --- Public API -----------------------------------------------------------

    def cancel(self):
        """
        Request cancellation of the running search.

        The worker checks this flag between files and will stop promptly.
        """
        self._cancelled = True

    # --- Thread Entry Point ---------------------------------------------------

    def run(self):
        """
        Walk workspace folders, search each file, and emit results.

        Builds a compiled regex from the search parameters, then iterates
        files line-by-line.  Skips binary extensions and directories listed
        in ``_SKIP_DIRS``.
        """
        # Build the regex from user parameters.
        regex = self._build_regex()
        if regex is None:
            # Invalid regex — abort with zero results.
            self.search_finished.emit(0)
            return

        # Parse file filter into a set of allowed extensions (empty = all).
        allowed_exts = self._parse_file_filter()

        total_matches = 0

        for folder in self._folders:
            folder = os.path.normpath(folder)
            total_matches += self._walk_and_search(folder, folder, 0, regex, allowed_exts)
            if self._cancelled:
                break

        self.search_finished.emit(total_matches)

    # --- Internal Helpers -----------------------------------------------------

    def _build_regex(self):
        """
        Compile a regex from the user's search parameters.

        :return: Compiled regex, or None if the pattern is invalid.
        :rtype: re.Pattern or None
        """
        pat = self._pattern

        if not self._use_regex:
            # Escape special regex characters for a literal search.
            pat = re.escape(pat)

        if self._whole_word:
            # Wrap in word-boundary anchors.
            pat = r"\b" + pat + r"\b"

        flags = 0 if self._case_sensitive else re.IGNORECASE

        try:
            return re.compile(pat, flags)
        except re.error as exc:
            logger.warning("Invalid search regex: %s", exc)
            return None

    def _parse_file_filter(self):
        """
        Parse the file filter string into a set of lowercase extensions.

        E.g. ``"*.py, *.mel"`` → ``{".py", ".mel"}``.
        An empty filter means "all files".

        :return: Set of allowed extensions (empty = no filter).
        :rtype: set
        """
        if not self._file_filter.strip():
            return set()

        exts = set()
        for part in self._file_filter.split(","):
            part = part.strip()
            if part.startswith("*."):
                exts.add(part[1:].lower())  # ".py"
            elif part.startswith("."):
                exts.add(part.lower())
        return exts

    def _walk_and_search(self, root, current, depth, regex, allowed_exts):
        """
        Recursively walk a directory and search matching files.

        :param str root: Workspace root (for relative path display).
        :param str current: Current directory.
        :param int depth: Current recursion depth.
        :param re.Pattern regex: Compiled search regex.
        :param set allowed_exts: Allowed extensions (empty = all).
        :return: Number of matches found in this subtree.
        :rtype: int
        """
        if depth > _MAX_DEPTH or self._cancelled:
            return 0

        try:
            entries = os.listdir(current)
        except PermissionError:
            return 0

        total = 0

        for entry in sorted(entries):
            if self._cancelled:
                break

            full_path = os.path.join(current, entry)

            if os.path.isdir(full_path):
                if entry in _SKIP_DIRS:
                    continue
                total += self._walk_and_search(root, full_path, depth + 1, regex, allowed_exts)

            elif os.path.isfile(full_path):
                # Skip binary / non-text extensions.
                _, ext = os.path.splitext(entry)
                if ext.lower() in _SKIP_EXTENSIONS:
                    continue

                # Apply file filter if set.
                if allowed_exts and ext.lower() not in allowed_exts:
                    continue

                total += self._search_file(full_path, regex)

        return total

    def _search_file(self, filepath, regex):
        """
        Search a single file line-by-line and emit matches.

        :param str filepath: Absolute path to the file.
        :param re.Pattern regex: Compiled search pattern.
        :return: Number of matches in this file.
        :rtype: int
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except (OSError, IOError):
            return 0

        matches = []
        for i, line in enumerate(lines, start=1):
            if regex.search(line):
                # Trim trailing newline for display.
                matches.append((i, line.rstrip("\n\r")))

        if matches:
            self.match_found.emit(filepath, matches)

        return len(matches)


# =============================================================================
# FindInFilesDialog
# =============================================================================

# Stylesheet matching the dark editor theme.
_DIALOG_STYLE = """
    QDialog {
        background-color: #252526;
        color: #d4d4d4;
    }
    QLineEdit {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 4px 6px;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 1px solid #007acc;
    }
    QPushButton {
        background-color: #0e639c;
        color: #ffffff;
        border: none;
        border-radius: 3px;
        padding: 5px 14px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #1177bb;
    }
    QPushButton:pressed {
        background-color: #094771;
    }
    QPushButton:disabled {
        background-color: #3c3c3c;
        color: #888;
    }
    QCheckBox {
        color: #d4d4d4;
        spacing: 4px;
        font-size: 12px;
    }
    QComboBox {
        background-color: #3c3c3c;
        color: #d4d4d4;
        border: 1px solid #555;
        border-radius: 3px;
        padding: 3px 6px;
    }
    QLabel {
        color: #d4d4d4;
        font-size: 12px;
    }
    QTreeWidget {
        background-color: #1e1e1e;
        color: #d4d4d4;
        border: 1px solid #333;
        outline: none;
        font-size: 12px;
    }
    QTreeWidget::item {
        padding: 2px 4px;
    }
    QTreeWidget::item:selected {
        background-color: #094771;
        color: #ffffff;
    }
    QTreeWidget::branch {
        background-color: #1e1e1e;
    }
"""


class FindInFilesDialog(QDialog):
    """
    PyCharm-style Find in Files / Replace in Files dialog.

    Displays search controls at the top with option toggles for
    case-sensitive, whole-word, and regex matching.  Results appear
    in a QTreeWidget grouped by file.  Double-clicking a match
    navigates to the file and line via the provided callback.

    :param QWidget parent: Parent window.
    :param list workspace_folders: Folders to search.
    :param callable open_callback: ``fn(filepath, line_number)`` to open results.
    :param str mode: ``"find"`` or ``"replace"`` (controls Replace row visibility).
    """

    def __init__(self, parent, workspace_folders, open_callback, mode="find",
                 replace_done_callback=None):
        """
        Initialize the Find in Files dialog.

        :param QWidget parent: Parent window.
        :param list workspace_folders: Workspace folder paths.
        :param callable open_callback: Called with (filepath, line_number) on navigate.
        :param str mode: ``"find"`` for search-only, ``"replace"`` to show replace row.
        :param callable replace_done_callback: Called with a list of modified file paths
            after Replace All so the host can reload open editors.
        """
        super().__init__(parent)
        self._workspace_folders = workspace_folders
        self._open_callback = open_callback
        self._replace_done_callback = replace_done_callback
        self._mode = mode
        self._worker = None

        # Window setup.
        title = "Replace in Files" if mode == "replace" else "Find in Files"
        self.setWindowTitle(title)
        self.setMinimumSize(700, 450)
        self.resize(800, 550)
        self.setStyleSheet(_DIALOG_STYLE)

        self._build_ui()

    # --- UI Construction ------------------------------------------------------

    def _build_ui(self):
        """Build all dialog widgets and lay them out."""
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- Search row ---
        search_row = QHBoxLayout()
        search_row.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search text...")
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, 1)

        # Toggle buttons for search options.
        self._chk_case = QCheckBox("Cc")
        self._chk_case.setToolTip("Match Case")
        search_row.addWidget(self._chk_case)

        self._chk_word = QCheckBox("W")
        self._chk_word.setToolTip("Whole Word")
        search_row.addWidget(self._chk_word)

        self._chk_regex = QCheckBox(".*")
        self._chk_regex.setToolTip("Regular Expression")
        search_row.addWidget(self._chk_regex)

        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self._search_btn)

        layout.addLayout(search_row)

        # --- Replace row (only visible in replace mode) ---
        self._replace_row = QHBoxLayout()
        self._replace_row.setSpacing(4)

        self._replace_input = QLineEdit()
        self._replace_input.setPlaceholderText("Replace with...")
        self._replace_row.addWidget(self._replace_input, 1)

        self._replace_all_btn = QPushButton("Replace All")
        self._replace_all_btn.clicked.connect(self._on_replace_all)
        self._replace_row.addWidget(self._replace_all_btn)

        # Wrap in a widget so we can toggle visibility.
        replace_widget = QLabel()  # Invisible spacer if hidden.
        replace_layout_widget = QHBoxLayout()
        replace_layout_widget.setContentsMargins(0, 0, 0, 0)

        # We add the replace row as a sub-layout.
        layout.addLayout(self._replace_row)

        # Hide replace controls in find-only mode.
        if self._mode != "replace":
            self._replace_input.setVisible(False)
            self._replace_all_btn.setVisible(False)

        # --- Filter row ---
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        filter_row.addWidget(QLabel("Scope:"))
        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["Project"])
        filter_row.addWidget(self._scope_combo)

        filter_row.addWidget(QLabel("File filter:"))
        self._file_filter_input = QLineEdit()
        self._file_filter_input.setPlaceholderText("e.g. *.py, *.mel")
        self._file_filter_input.setMaximumWidth(200)
        filter_row.addWidget(self._file_filter_input)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # --- Results tree ---
        self._results_tree = QTreeWidget()
        self._results_tree.setHeaderHidden(True)
        self._results_tree.setRootIsDecorated(True)
        self._results_tree.setIndentation(16)
        self._results_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        # Enter key also navigates.
        self._results_tree.itemActivated.connect(self._on_item_double_clicked)
        layout.addWidget(self._results_tree, 1)

        # --- Status label ---
        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

    # --- Search Logic ---------------------------------------------------------

    def _on_search(self):
        """
        Start a new search using the current input values.

        Cancels any running worker, clears previous results, and
        launches a new ``SearchWorker`` thread.
        """
        pattern = self._search_input.text().strip()
        if not pattern:
            return

        # Cancel any in-progress search.
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)

        # Clear previous results.
        self._results_tree.clear()
        self._file_count = 0
        self._match_count = 0
        self._status_label.setText("Searching...")
        self._search_btn.setEnabled(False)

        # Launch background search.
        self._worker = SearchWorker(
            workspace_folders=self._workspace_folders,
            pattern=pattern,
            case_sensitive=self._chk_case.isChecked(),
            whole_word=self._chk_word.isChecked(),
            use_regex=self._chk_regex.isChecked(),
            file_filter=self._file_filter_input.text().strip(),
        )
        self._worker.match_found.connect(self._on_match_found)
        self._worker.search_finished.connect(self._on_search_finished)
        self._worker.start()

    def _on_match_found(self, filepath, matches):
        """
        Add a file's matches to the results tree.

        Creates a top-level tree item for the file, with child items
        for each matching line.

        :param str filepath: Absolute path to the file with matches.
        :param list matches: List of (line_number, line_text) tuples.
        """
        self._file_count += 1
        self._match_count += len(matches)

        # Determine a short display name from workspace root.
        display_path = filepath
        for folder in self._workspace_folders:
            folder = os.path.normpath(folder)
            if filepath.startswith(folder):
                display_path = os.path.relpath(filepath, folder)
                break

        # File node: "relative/path  (N matches)"
        file_item = QTreeWidgetItem(self._results_tree)
        file_item.setText(0, "{}  ({} matches)".format(display_path, len(matches)))
        # Store the filepath for navigation.
        file_item.setData(0, Qt.ItemDataRole.UserRole, filepath)

        # One child per matching line.
        for line_num, line_text in matches:
            child = QTreeWidgetItem(file_item)
            # Truncate long lines for readability.
            display_line = line_text[:200]
            child.setText(0, "  {}:  {}".format(line_num, display_line))
            # Store (filepath, line_number) for navigation.
            child.setData(0, Qt.ItemDataRole.UserRole, (filepath, line_num))

        # Auto-expand the file node.
        file_item.setExpanded(True)

        # Update status.
        self._status_label.setText(
            "{} matches in {} files (searching...)".format(self._match_count, self._file_count)
        )

    def _on_search_finished(self, total):
        """
        Handle search completion.

        Updates the status label with final counts and re-enables the
        Search button.

        :param int total: Total match count (from the worker).
        """
        self._status_label.setText(
            "{} matches in {} files".format(self._match_count, self._file_count)
        )
        self._search_btn.setEnabled(True)
        logger.info("Find in Files: %d matches in %d files", self._match_count, self._file_count)

    # --- Navigation -----------------------------------------------------------

    def _on_item_double_clicked(self, item, column=0):
        """
        Navigate to the file and line when a match item is double-clicked.

        File-level items navigate to line 1.  Match-level items navigate
        to the matched line number.

        :param QTreeWidgetItem item: The clicked tree item.
        :param int column: Column index (unused).
        """
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return

        if isinstance(data, tuple):
            # Child item: (filepath, line_number).
            filepath, line_num = data
            self._open_callback(filepath, line_num)
        elif isinstance(data, str):
            # File-level item: open at line 1.
            self._open_callback(data, 1)

    # --- Replace Logic --------------------------------------------------------

    def _on_replace_all(self):
        """
        Replace all occurrences of the search pattern in matched files.

        Reads each file, performs the replacement, and writes it back.
        Updates the status label with the number of replacements made.
        """
        search_text = self._search_input.text().strip()
        replace_text = self._replace_input.text()
        if not search_text:
            return

        # Build the same regex the search worker would use.
        use_regex = self._chk_regex.isChecked()
        case_sensitive = self._chk_case.isChecked()
        whole_word = self._chk_word.isChecked()

        pat = search_text
        if not use_regex:
            pat = re.escape(pat)
        if whole_word:
            pat = r"\b" + pat + r"\b"

        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            regex = re.compile(pat, flags)
        except re.error as exc:
            self._status_label.setText("Invalid regex: {}".format(exc))
            return

        # Collect unique file paths from the results tree.
        file_paths = []
        for i in range(self._results_tree.topLevelItemCount()):
            file_item = self._results_tree.topLevelItem(i)
            fp = file_item.data(0, Qt.ItemDataRole.UserRole)
            if fp and isinstance(fp, str):
                file_paths.append(fp)

        if not file_paths:
            self._status_label.setText("No files to replace in — run a search first")
            return

        total_replacements = 0
        files_modified = 0
        modified_paths = []

        for filepath in file_paths:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()

                new_content, count = regex.subn(replace_text, content)

                if count > 0:
                    with open(filepath, "w", encoding="utf-8") as fh:
                        fh.write(new_content)
                    total_replacements += count
                    files_modified += 1
                    modified_paths.append(filepath)

            except (OSError, IOError) as exc:
                logger.warning("Could not replace in %s: %s", filepath, exc)

        self._status_label.setText(
            "Replaced {} occurrences in {} files".format(total_replacements, files_modified)
        )
        logger.info("Replace All: %d replacements in %d files", total_replacements, files_modified)

        if total_replacements > 0:
            # Notify the host so it can reload any open editors whose
            # files were modified on disk.
            if self._replace_done_callback:
                self._replace_done_callback(modified_paths)

            # Re-run the search to refresh results (matches should be gone now).
            self._on_search()

    # --- Cleanup --------------------------------------------------------------

    def closeEvent(self, event):
        """
        Cancel any running search worker before closing.

        :param QCloseEvent event: The close event.
        """
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)
