"""
MCA Core - Background Symbol Index.

Provides a thread-safe in-memory index of symbol definitions (class, def,
proc) across workspace files, plus on-demand usage search.  Built in a
background thread so the UI never blocks.

Architecture:
    - ``SymbolIndex``  -- data structure with lock-protected dicts.
    - ``IndexWorker``  -- daemon thread that walks folders and parses files.

No Qt dependency -- this module is pure Python so it compiles to .pyd safely.

Dependencies:
    - None (stdlib only)
"""

import logging
import os
import re
import threading

from collections import namedtuple

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Data Structures ---------------------------------------------------

# A single symbol definition found during indexing.
SymbolEntry = namedtuple(
    "SymbolEntry",
    ["name", "kind", "filepath", "line", "line_text", "indent"],
)

# --- Constants ---------------------------------------------------------

# Directories to skip during filesystem walk.
_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".tox", ".eggs", "dist",
    "build", ".idea", ".vs", ".vscode",
}

# File extensions to skip (binary / non-source).
_SKIP_EXTS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".png", ".jpg",
    ".jpeg", ".gif", ".bmp", ".ico", ".ttf", ".otf", ".woff", ".woff2",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".db", ".sqlite",
}

# Maximum directory depth to recurse into.
_MAX_DEPTH = 5

# Regex templates for definition lines.  ``{symbol}`` is replaced with a
# concrete name during lookup; during indexing we use a generic capture
# group to grab every definition in a file at once.
_DEFINITION_PATTERNS = [
    r"^\s*class\s+{symbol}\b",
    r"^\s*def\s+{symbol}\b",
    r"^\s*global\s+proc\s+\w*\s*{symbol}\b",
    r"^\s*proc\s+\w*\s*{symbol}\b",
]

# Single combined regex that captures any definition name in a line.
# Groups: 1=class name, 2=def name, 3=global-proc name, 4=proc name.
_INDEX_REGEX = re.compile(
    r"^\s*class\s+([A-Za-z_]\w*)\b"
    r"|^\s*def\s+([A-Za-z_]\w*)\b"
    r"|^\s*global\s+proc\s+\w*\s*([A-Za-z_]\w*)\b"
    r"|^\s*proc\s+\w*\s*([A-Za-z_]\w*)\b",
    re.MULTILINE,
)

# Map from regex group index to human-readable kind string.
_GROUP_TO_KIND = {
    1: "class",
    2: "function",
    3: "global_proc",
    4: "proc",
}


# --- SymbolIndex -------------------------------------------------------

class SymbolIndex:
    """
    Thread-safe in-memory index of symbol definitions.

    Definitions are pre-indexed at project load (class/def/proc patterns).
    Usages are scanned on demand against the known file list, which avoids
    the expensive filesystem walk every time.

    All public methods acquire ``_lock`` so callers don't need to worry
    about threading.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # "MyClass" -> [SymbolEntry, ...]  (O(1) definition lookup).
        self._symbols_by_name = {}

        # "/path/file.py" -> [SymbolEntry, ...]  (O(1) per-file removal).
        self._symbols_by_file = {}

        # "/path/file.py" -> float mtime  (skip unchanged files on re-index).
        self._file_mtimes = {}

        # All indexed file paths (used by find_usages to avoid re-walking).
        self._all_files = []

        # Current indexer state: "idle" | "indexing" | "ready".
        self._state = "idle"

        # Progress tuple: (files_done, files_total).
        self._progress = (0, 0)

    # --- Query API -----------------------------------------------------

    def find_definitions(self, name):
        """
        Look up definitions of *name* by exact match.

        :param str name: The symbol name (e.g. ``"MyClass"``).
        :return: List of ``(filepath, line, line_text)`` tuples.
        :rtype: list[tuple]
        """
        with self._lock:
            entries = self._symbols_by_name.get(name, [])
            return [(e.filepath, e.line, e.line_text) for e in entries]

    def find_usages(self, name, definition_patterns=None):
        """
        Scan all indexed files for usages of *name*, excluding definition lines.

        This avoids the filesystem walk -- only files already known to the
        index are scanned, which is the expensive part.

        :param str name: The symbol name to search for.
        :param list definition_patterns: Optional compiled regex list to
            identify (and exclude) definition lines.  If ``None``, the
            default ``_DEFINITION_PATTERNS`` templates are compiled.
        :return: List of ``(filepath, line, line_text)`` tuples.
        :rtype: list[tuple]
        """
        # Build the usage regex (word-boundary match).
        usage_re = re.compile(r"\b" + re.escape(name) + r"\b")

        # Build definition regexes so we can exclude def lines.
        if definition_patterns is None:
            definition_patterns = []
            for tmpl in _DEFINITION_PATTERNS:
                definition_patterns.append(
                    re.compile(tmpl.format(symbol=re.escape(name)))
                )

        # Snapshot the file list under lock, then release for I/O.
        with self._lock:
            files = list(self._all_files)

        results = []
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if usage_re.search(line):
                            # Skip definition lines -- we only want usages.
                            is_def = any(dp.search(line) for dp in definition_patterns)
                            if not is_def:
                                results.append((filepath, i, line.rstrip("\n\r")))
            except (OSError, IOError):
                pass

        return results

    def update_file(self, filepath):
        """
        Incrementally update the index for a single file.

        Removes old entries then re-scans the file.  Called on file save.

        :param str filepath: Absolute path to the file that changed.
        """
        filepath = os.path.normpath(filepath)

        # Remove old entries for this file.
        self._remove_file(filepath)

        # Re-scan and insert new entries.
        entries = _parse_file(filepath)
        if entries is None:
            return

        with self._lock:
            self._symbols_by_file[filepath] = entries

            # Update the mtime cache.
            try:
                self._file_mtimes[filepath] = os.path.getmtime(filepath)
            except OSError:
                pass

            # Insert into by-name dict.
            for entry in entries:
                bucket = self._symbols_by_name.setdefault(entry.name, [])
                bucket.append(entry)

            # Ensure file is in the all-files list.
            if filepath not in self._all_files:
                self._all_files.append(filepath)

    def clear(self):
        """
        Wipe the entire index.  Called on project close.
        """
        with self._lock:
            self._symbols_by_name.clear()
            self._symbols_by_file.clear()
            self._file_mtimes.clear()
            self._all_files = []
            self._state = "idle"
            self._progress = (0, 0)

    def is_ready(self):
        """
        Return ``True`` when the initial background indexing is complete.

        :rtype: bool
        """
        with self._lock:
            return self._state == "ready"

    def get_state(self):
        """
        Return the current indexer state string.

        :return: One of ``"idle"``, ``"indexing"``, ``"ready"``.
        :rtype: str
        """
        with self._lock:
            return self._state

    def get_progress(self):
        """
        Return progress as ``(files_done, files_total)``.

        :rtype: tuple[int, int]
        """
        with self._lock:
            return self._progress

    def get_symbol_count(self):
        """
        Return the total number of indexed symbol entries.

        :rtype: int
        """
        with self._lock:
            return sum(len(v) for v in self._symbols_by_name.values())

    def get_file_count(self):
        """
        Return the number of indexed files.

        :rtype: int
        """
        with self._lock:
            return len(self._symbols_by_file)

    # --- Internal helpers (called under lock or by worker) -------------

    def _remove_file(self, filepath):
        """
        Remove all entries for *filepath* from both dicts.

        :param str filepath: Normalized absolute path.
        """
        with self._lock:
            old_entries = self._symbols_by_file.pop(filepath, [])
            self._file_mtimes.pop(filepath, None)

            # Remove from by-name dict.
            for entry in old_entries:
                bucket = self._symbols_by_name.get(entry.name)
                if bucket:
                    # Filter out entries for this file.
                    bucket[:] = [e for e in bucket if e.filepath != filepath]
                    # Clean up empty buckets.
                    if not bucket:
                        del self._symbols_by_name[entry.name]

    def _set_state(self, state):
        """
        Update the indexer state.

        :param str state: One of ``"idle"``, ``"indexing"``, ``"ready"``.
        """
        with self._lock:
            self._state = state

    def _set_progress(self, done, total):
        """
        Update the progress tuple.

        :param int done: Number of files processed so far.
        :param int total: Total number of files to process.
        """
        with self._lock:
            self._progress = (done, total)

    def _bulk_insert(self, filepath, entries, mtime):
        """
        Insert entries for a single file during initial indexing.

        Called by the worker thread.  Acquires the lock internally.

        :param str filepath: Normalized absolute path.
        :param list entries: List of ``SymbolEntry`` namedtuples.
        :param float mtime: File modification time.
        """
        with self._lock:
            self._symbols_by_file[filepath] = entries
            self._file_mtimes[filepath] = mtime

            for entry in entries:
                bucket = self._symbols_by_name.setdefault(entry.name, [])
                bucket.append(entry)

            if filepath not in self._all_files:
                self._all_files.append(filepath)


# --- File Parsing (module-level, no lock needed) -----------------------

def _parse_file(filepath):
    """
    Parse a single file and return a list of ``SymbolEntry`` for every
    definition found.

    :param str filepath: Absolute path to the file.
    :return: List of ``SymbolEntry`` or ``None`` on read failure.
    :rtype: list[SymbolEntry] or None
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except (OSError, IOError):
        return None

    entries = []
    for i, raw_line in enumerate(lines, start=1):
        match = _INDEX_REGEX.search(raw_line)
        if not match:
            continue

        # Determine which group matched to get name and kind.
        for group_idx, kind in _GROUP_TO_KIND.items():
            name = match.group(group_idx)
            if name:
                # Measure leading whitespace for indent level.
                stripped = raw_line.lstrip()
                indent = len(raw_line) - len(stripped)

                entry = SymbolEntry(
                    name=name,
                    kind=kind,
                    filepath=filepath,
                    line=i,
                    line_text=raw_line.rstrip("\n\r"),
                    indent=indent,
                )
                entries.append(entry)
                break

    return entries


# --- IndexWorker -------------------------------------------------------

class IndexWorker(threading.Thread):
    """
    Background daemon thread that walks workspace folders and populates
    a ``SymbolIndex``.

    Supports cooperative cancellation via ``cancel()``.

    :param SymbolIndex index: The index to populate.
    :param list folders: Workspace folder paths to walk.
    :param set excluded_folders: Folder names to skip (from project config).
    """

    def __init__(self, index, folders, excluded_folders=None):
        super().__init__(daemon=True, name="MCA-SymbolIndexer")
        self._index = index
        self._folders = [os.path.normpath(f) for f in folders]
        self._excluded_folders = excluded_folders or set()
        self._cancelled = False

    def cancel(self):
        """
        Request cooperative cancellation.  The worker checks this flag
        between files and will stop promptly.
        """
        self._cancelled = True

    def run(self):
        """
        Entry point for the background thread.

        Phase 1: Walk folders and collect file paths.
        Phase 2: Parse each file and insert definitions into the index.
        """
        self._index._set_state("indexing")
        logger.info("Symbol indexing started for %d folder(s)", len(self._folders))

        # Phase 1 -- enumerate all eligible source files.
        file_list = []
        for folder in self._folders:
            if self._cancelled:
                break
            self._walk_folder(folder, folder, 0, file_list)

        total = len(file_list)
        self._index._set_progress(0, total)
        logger.info("Symbol indexer found %d files to scan", total)

        # Phase 2 -- parse each file for definitions.
        for i, filepath in enumerate(file_list):
            if self._cancelled:
                logger.info("Symbol indexing cancelled at file %d/%d", i, total)
                break

            entries = _parse_file(filepath)
            if entries is not None:
                try:
                    mtime = os.path.getmtime(filepath)
                except OSError:
                    mtime = 0.0
                self._index._bulk_insert(filepath, entries, mtime)

            # Update progress after each file.
            self._index._set_progress(i + 1, total)

        # Mark indexing as complete (unless cancelled).
        if not self._cancelled:
            self._index._set_state("ready")
            done, total = self._index.get_progress()
            sym_count = self._index.get_symbol_count()
            logger.info(
                "Symbol indexing complete: %d files, %d symbols",
                total, sym_count,
            )

    def _walk_folder(self, root, current, depth, file_list):
        """
        Recursively walk *current* and append eligible files to *file_list*.

        :param str root: The top-level workspace folder (for context).
        :param str current: The directory currently being walked.
        :param int depth: Current recursion depth.
        :param list file_list: Accumulator list of file paths.
        """
        if depth > _MAX_DEPTH:
            return
        if self._cancelled:
            return

        try:
            entries = os.listdir(current)
        except PermissionError:
            return

        for entry in sorted(entries):
            if self._cancelled:
                return

            full_path = os.path.join(current, entry)

            if os.path.isdir(full_path):
                # Skip standard non-source directories.
                if entry in _SKIP_DIRS:
                    continue
                # Skip project-level excluded folders.
                if entry in self._excluded_folders:
                    continue
                self._walk_folder(root, full_path, depth + 1, file_list)

            elif os.path.isfile(full_path):
                _, ext = os.path.splitext(entry)
                if ext.lower() in _SKIP_EXTS:
                    continue
                file_list.append(os.path.normpath(full_path))
