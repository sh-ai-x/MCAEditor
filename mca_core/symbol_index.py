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
import pickle
import re
import threading
import time

from collections import namedtuple

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Data Structures ---------------------------------------------------

# A single symbol definition found during indexing.
#
# NOTE: we explicitly pin ``__module__`` to the real module name after
# construction.  When this file is imported as a ``.pyc`` via the
# SourcelessFileLoader used by the single-file Maya plugin wrapper,
# ``namedtuple``'s ``sys._getframe`` lookup can land on the importer's
# frame and set ``__module__`` to ``importlib._bootstrap``.  That makes
# ``pickle.dump`` fail at save_to_disk with ``attribute lookup
# SymbolEntry on importlib._bootstrap failed``.  Pinning the module
# attribute ensures pickle can resolve the class on reload.
SymbolEntry = namedtuple(
    "SymbolEntry",
    ["name", "kind", "filepath", "line", "line_text", "indent"],
)
SymbolEntry.__module__ = __name__

# --- Constants ---------------------------------------------------------

# Directories to skip during filesystem walk.
# Covers: Python tooling (__pycache__, .venv, site-packages), JS/TS tooling
# (node_modules, bower_components, .next, .nuxt), vendored dependencies
# (vendor, third_party), build outputs (build, dist, out, target, bin, obj),
# UE/Unity engine caches (Binaries, Intermediate, DerivedDataCache, Saved,
# Library), and IDE metadata (.git, .idea, .vs, .vscode).  Skipping these
# avoids indexing generated or vendored code that users rarely "goto-def"
# into and that dominates the file count in game / web projects.
_SKIP_DIRS = {
    # Python
    "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    ".tox", ".eggs", "site-packages",
    # JavaScript / TypeScript
    "node_modules", "bower_components", ".next", ".nuxt",
    # Vendored deps
    "vendor", "third_party",
    # Build outputs
    "build", "dist", "out", "target", "bin", "obj",
    # Unreal Engine per-project caches
    "Binaries", "Intermediate", "DerivedDataCache", "Saved",
    # Unity per-project caches
    "Library", "Temp",
    # Version control + IDE
    ".git", ".hg", ".svn", ".idea", ".vs", ".vscode",
}

# File extensions to skip (binary / non-source).
_SKIP_EXTS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".png", ".jpg",
    ".jpeg", ".gif", ".bmp", ".ico", ".ttf", ".otf", ".woff", ".woff2",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".db", ".sqlite",
}

# Maximum directory depth to recurse into.
_MAX_DEPTH = 15

# Skip files larger than this many bytes — generated code, minified
# bundles, vendored single-file libraries, and lockfiles can be multiple
# megabytes and dominate indexing time for zero user-visible benefit
# (symbols in these files are almost never "goto-def" targets).
_MAX_FILE_SIZE = 512 * 1024  # 512 KB

# --- Indexer responsiveness knobs --------------------------------------
#
# The indexer runs as a background daemon thread, but CPython's GIL
# serializes Python bytecode across threads.  When the indexer is busy
# scanning thousands of files, Maya's main-thread Python (scriptJobs,
# idle callbacks, plug-in events) gets starved.  Combined with disk I/O
# contention from reading every source file, this has historically
# made Maya feel unusable for several minutes after project open.
#
# These constants tune the trade-off between total indexing time and
# main-thread responsiveness.  Defaults err toward responsiveness — it's
# fine if indexing takes an extra 20% as long, so long as Maya stays
# interactive the whole time.

# Delay (seconds) before the indexer begins walking folders after being
# started.  Gives Maya's own startup reads (UI fonts, workspace restore,
# plug-in autoload) time to finish before we start hammering the disk.
# Checked cooperatively against ``_cancelled`` in short slices so a
# quick project close doesn't leave the thread sleeping.
_STARTUP_DELAY_SECS = 3.0

# Release the GIL every N files parsed in Phase 2.  A small ``sleep()``
# (not ``sleep(0)``, which can be a near-no-op under heavy load) yields
# to the main thread's Python callbacks.  Total indexer overhead is
# ``(file_count / _YIELD_EVERY_N_FILES) * _YIELD_SLEEP_SECS``.
_YIELD_EVERY_N_FILES = 20
_YIELD_SLEEP_SECS = 0.005  # 5 ms

# --- Disk cache format -------------------------------------------------
#
# The index is expensive to build (minutes for large workspaces) but
# almost trivial to reload from a pickle.  We persist the finished
# index to disk so re-opening the editor — or even restarting Maya —
# doesn't force the user to sit through another full scan when
# nothing has actually changed on disk.
#
# The cache key is derived from the sorted workspace-folder list, so
# different projects get different cache files and there's no chance
# of loading an index that covers the wrong folders.

# Magic header to identify our cache format.  Protects against
# accidentally unpickling an unrelated file with the same extension.
_CACHE_MAGIC = b"MCAIDX\x00"

# Bump this whenever the pickled structures change shape (e.g. adding
# a new field to SymbolEntry, changing which dicts we persist, etc.).
# Old caches with a mismatching version are silently discarded.
#
# v2: SymbolEntry serialized as plain tuples instead of the namedtuple
#     class.  Needed because the Cython/.pyc import path can mis-pin
#     ``SymbolEntry.__module__`` to ``importlib._bootstrap``, making
#     pickle unable to resolve the class name on save.  Plain tuples
#     sidestep the whole class-lookup path.
_CACHE_SCHEMA_VERSION = 2

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

# Regex matching any Python-ish identifier in a line.  Used at index time
# to build a per-file word set so ``find_usages`` can skip files whose
# contents don't include the target symbol at all — a massive speedup
# when the target only appears in a handful of files.
_IDENT_REGEX = re.compile(r"[A-Za-z_]\w*")


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

        # "/path/file.py" -> frozenset of identifiers seen in that file.
        # Populated at index time; used by find_usages to skip files
        # that cannot possibly contain the target symbol (O(1) set
        # membership vs. reading the entire file).
        self._file_words = {}

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

    def find_by_prefix(self, prefix, limit=50):
        """
        Return symbol names that start with *prefix* (case-insensitive).

        Used by the code completer to offer project-wide suggestions
        drawn from class, function, and proc definitions across all
        indexed files.

        :param str prefix: Prefix to match (e.g. ``"rig"``).
        :param int limit: Maximum number of results to return.
        :return: List of ``(name, kind, filepath)`` tuples, deduplicated
            by name and sorted alphabetically.
        :rtype: list[tuple]
        """
        prefix_lower = prefix.lower()
        seen = set()
        results = []
        with self._lock:
            for name, entries in self._symbols_by_name.items():
                if name.lower().startswith(prefix_lower) and name not in seen:
                    seen.add(name)
                    # Use the first entry's kind and filepath as representative.
                    entry = entries[0]
                    results.append((name, entry.kind, entry.filepath))
                    if len(results) >= limit:
                        break
        results.sort(key=lambda r: r[0].lower())
        return results

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

        # Snapshot the file list and per-file word sets under lock,
        # then release for I/O.
        with self._lock:
            files = list(self._all_files)
            file_words = dict(self._file_words)

        # Pre-filter files by the cached word sets — only files whose
        # index-time word set contains *name* can possibly have usages.
        # This turns an O(N * file_size) scan into O(N) dict lookups
        # plus a few reads of the files that actually matter.
        candidate_files = []
        for filepath in files:
            words = file_words.get(filepath)
            if words is None:
                # No cached word set (indexing didn't see the file fully)
                # — fall back to re-reading it, preserving correctness.
                candidate_files.append(filepath)
            elif name in words:
                candidate_files.append(filepath)

        results = []
        for filepath in candidate_files:
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

        # Re-scan and insert new entries + refreshed word set.
        entries, word_set = _parse_file(filepath)
        if entries is None:
            return

        with self._lock:
            self._symbols_by_file[filepath] = entries
            self._file_words[filepath] = word_set

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
            self._file_words.clear()
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

    def get_all_files(self):
        """
        Return a snapshot of the indexed file paths.

        Callers (e.g. Find in Files) can use this pre-built list to
        skip re-walking the filesystem on every search.

        :return: Copy of the indexed file-path list.
        :rtype: list[str]
        """
        # Snapshot under lock so callers get a stable list.
        with self._lock:
            return list(self._all_files)

    def get_files_with_word(self, name):
        """
        Return the subset of indexed files whose cached word set contains *name*.

        Mirrors the pre-filter used inside ``find_usages``: any file
        whose index-time word set does NOT include *name* cannot
        contain a whole-word occurrence of it, so the caller can skip
        opening/reading it entirely.  Files that were not fully word-
        indexed (``_file_words`` miss) are included to preserve
        correctness — the caller is expected to scan them anyway.

        :param str name: The identifier to look up.  Caller should
            verify this is a plain word (no regex metacharacters) since
            the word set stores raw identifiers.
        :return: Candidate file paths.  Empty list if *name* is empty.
        :rtype: list[str]
        """
        if not name:
            return []

        # Snapshot under lock so the returned list is stable even if
        # the indexer continues updating ``_file_words`` in the
        # background after we release the lock.
        with self._lock:
            files = list(self._all_files)
            file_words = dict(self._file_words)

        candidates = []
        for filepath in files:
            words = file_words.get(filepath)
            # No word set recorded -> be conservative and include the
            # file; the search worker will open it and decide.
            if words is None or name in words:
                candidates.append(filepath)
        return candidates

    def get_files_containing_substring(self, substring, case_sensitive=True):
        """
        Return files whose cached word set has an identifier containing *substring*.

        Used by Find-in-Files substring searches when the pattern is
        a pure identifier fragment (e.g. ``"Curves"`` matching
        ``"AnimatedCurvesComponent"``).  Because the indexer extracts
        every ``[A-Za-z_]\\w*`` token into the word set, a substring
        match against that set is equivalent to a substring match
        against the file's code — minus string-literal text that
        spans whitespace or punctuation, which the optimization
        intentionally leaves to the full filesystem walker.

        Files without a cached word set are included to preserve
        correctness — callers will open and scan them anyway.

        :param str substring: The fragment to look up.  Caller must
            guarantee this is pure-identifier text (letters, digits,
            underscore) or the match will silently miss legitimate
            hits that cross token boundaries.
        :param bool case_sensitive: When False, compares lowercased.
        :return: Candidate absolute file paths.
        :rtype: list[str]
        """
        if not substring:
            return []

        # Snapshot the index state once; the big identifier sets may
        # be large and we want to release the lock before the loop
        # below does any substring work.
        with self._lock:
            files = list(self._all_files)
            file_words = dict(self._file_words)

        # Case-insensitive lookups compare lowercased forms.  This is
        # a few percent slower than direct ``in`` checks but avoids
        # maintaining two word caches per file.
        if case_sensitive:
            needle = substring
        else:
            needle = substring.lower()

        candidates = []
        for filepath in files:
            words = file_words.get(filepath)
            if words is None:
                # Conservative fallback -- index didn't capture the
                # file fully, so we let the caller open it.
                candidates.append(filepath)
                continue

            # Short-circuit as soon as we find any matching token.
            # The word set is typically a few hundred entries, and
            # Python's ``in`` on strings is implemented in C.
            if case_sensitive:
                found = any(needle in w for w in words)
            else:
                found = any(needle in w.lower() for w in words)

            if found:
                candidates.append(filepath)
        return candidates

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

    def is_fresh_for(self, folders, excluded_folders=None):
        """
        Check whether the current index still matches the files on disk.

        Walks *folders* using the same rules as ``IndexWorker`` and
        compares the resulting file set + per-file mtimes against what
        the index already holds.  Returns True only when every eligible
        file on disk has an entry in the index AND the mtimes agree AND
        the index doesn't know about extra files that have been deleted.

        Intended for validating a disk-loaded cache before reusing it:
        a stat-only walk of a large project is far cheaper than a full
        reparse, so we can afford to verify freshness on every open.

        :param list folders: Workspace folder paths to validate against.
        :param set excluded_folders: Folder names to skip (from project
            config), mirroring ``IndexWorker.__init__``.
        :return: True if the cache is still valid, False otherwise.
        :rtype: bool
        """
        excluded_folders = excluded_folders or set()

        # Walk the disk with the same filters the indexer uses.
        file_list = []
        for folder in folders:
            folder = os.path.normpath(folder)
            _walk_folder_for_freshness(
                folder, folder, 0, file_list, excluded_folders,
            )
        disk_files = set(file_list)

        with self._lock:
            # File-set mismatch means something was added or deleted.
            cached_files = set(self._file_mtimes.keys())
            if disk_files != cached_files:
                return False

            # Compare mtimes with a small tolerance (FAT32 / network
            # shares round to 2s; os.path.getmtime can jitter slightly
            # between reads).
            tol = 1.0
            for filepath in disk_files:
                try:
                    disk_mtime = os.path.getmtime(filepath)
                except OSError:
                    return False
                cached_mtime = self._file_mtimes.get(filepath, 0.0)
                if abs(disk_mtime - cached_mtime) > tol:
                    return False

        return True

    # --- Disk persistence ----------------------------------------------

    def save_to_disk(self, path):
        """
        Write a pickled snapshot of the ready index to *path*.

        Only saves when ``get_state() == "ready"`` — partial progress
        is intentionally not persisted because the caller has no safe
        way to tell whether the missing files were skipped (size cap,
        read error) or simply not reached before cancellation.  A
        partial snapshot would reload as "ready" and silently hide
        real goto-def targets.

        The write is atomic: serialize into ``<path>.tmp`` first, then
        rename on top of *path*.  A crash mid-write leaves the old
        cache file intact rather than producing a half-written pickle.

        :param str path: Destination cache file path.  Parent directory
            is created if it doesn't exist.
        :return: *True* on success, *False* on any failure (error is
            logged, caller can carry on with the in-memory index).
        :rtype: bool
        """
        # Snapshot the in-memory state under the lock so concurrent
        # update_file() / _bulk_insert() can't change a dict while
        # pickle is walking it.  ``SymbolEntry`` is a namedtuple, but
        # we flatten every instance to a plain tuple here so pickle
        # doesn't need to resolve the class name -- the Cython/.pyc
        # import path can mis-pin ``SymbolEntry.__module__`` to
        # ``importlib._bootstrap``, which breaks pickle lookup.
        with self._lock:
            if self._state != "ready":
                return False
            symbols_by_name = {
                name: [tuple(e) for e in entries]
                for name, entries in self._symbols_by_name.items()
            }
            symbols_by_file = {
                fp: [tuple(e) for e in entries]
                for fp, entries in self._symbols_by_file.items()
            }
            data = {
                "magic": _CACHE_MAGIC,
                "version": _CACHE_SCHEMA_VERSION,
                "symbols_by_name": symbols_by_name,
                "symbols_by_file": symbols_by_file,
                "file_mtimes": dict(self._file_mtimes),
                "file_words": dict(self._file_words),
                "all_files": list(self._all_files),
            }

        # Ensure the cache dir exists (first run on a fresh install).
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create symbol-index cache dir: %s", exc)
            return False

        # Atomic write: temp then rename.  ``os.replace`` is atomic on
        # both POSIX and Windows (unlike the older ``os.rename``).
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, path)
            logger.info(
                "Saved symbol index to disk: %d files (%s)",
                len(data["all_files"]), path,
            )
            return True
        except (OSError, pickle.PickleError) as exc:
            logger.warning("Failed to save symbol index to %s: %s", path, exc)
            # Best-effort cleanup of the abandoned temp file.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False

    @classmethod
    def load_from_disk(cls, path):
        """
        Reconstruct a ready ``SymbolIndex`` from a pickled snapshot.

        Returns *None* on any failure — missing file, wrong magic,
        schema mismatch, corruption.  The caller should fall through
        to a full scan in that case.

        :param str path: Cache file path created by ``save_to_disk``.
        :return: Populated ``SymbolIndex`` in ``"ready"`` state, or
                 ``None`` if the cache is unusable.
        :rtype: SymbolIndex or None
        """
        if not os.path.isfile(path):
            return None

        # Any exception here (corrupted pickle, truncated file, class
        # renamed since the pickle was written, etc.) means we can't
        # trust the cache — return None so the caller rebuilds fresh.
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError,
                ImportError, ValueError) as exc:
            logger.warning("Failed to load symbol index from %s: %s", path, exc)
            return None

        # Shape check first: if the file doesn't even look like our
        # format, silently ignore it.
        if not isinstance(data, dict):
            return None
        if data.get("magic") != _CACHE_MAGIC:
            return None
        if data.get("version") != _CACHE_SCHEMA_VERSION:
            logger.info(
                "Symbol index cache schema %s != current %s — rebuilding",
                data.get("version"), _CACHE_SCHEMA_VERSION,
            )
            return None

        # All required keys present?  Guard against truncated caches
        # that happened to land on a valid magic + version by chance.
        required_keys = (
            "symbols_by_name", "symbols_by_file", "file_mtimes",
            "file_words", "all_files",
        )
        for key in required_keys:
            if key not in data:
                logger.warning("Symbol index cache missing key %r", key)
                return None

        # Rehydrate plain tuples back into SymbolEntry namedtuples so
        # callers can keep using attribute access (``entry.name``,
        # ``entry.line``, etc.) without knowing the cache stored them
        # as tuples.  A defensive try/except protects against weirdly
        # shaped entries in a cache from a future schema.
        try:
            symbols_by_name = {
                name: [SymbolEntry(*t) for t in entries]
                for name, entries in data["symbols_by_name"].items()
            }
            symbols_by_file = {
                fp: [SymbolEntry(*t) for t in entries]
                for fp, entries in data["symbols_by_file"].items()
            }
        except (TypeError, ValueError) as exc:
            logger.warning("Symbol index cache has malformed entries: %s", exc)
            return None

        # Reconstruct the index in "ready" state so callers see it as
        # a finished index and don't kick off a redundant IndexWorker.
        index = cls()
        with index._lock:
            index._symbols_by_name = symbols_by_name
            index._symbols_by_file = symbols_by_file
            index._file_mtimes = data["file_mtimes"]
            index._file_words = data["file_words"]
            index._all_files = data["all_files"]
            index._state = "ready"
            file_count = len(index._all_files)
            index._progress = (file_count, file_count)

        logger.info(
            "Loaded symbol index from disk: %d files (%s)",
            file_count, path,
        )
        return index

    # --- Internal helpers (called under lock or by worker) -------------

    def _remove_file(self, filepath):
        """
        Remove all entries for *filepath* from both dicts.

        :param str filepath: Normalized absolute path.
        """
        with self._lock:
            old_entries = self._symbols_by_file.pop(filepath, [])
            self._file_mtimes.pop(filepath, None)
            self._file_words.pop(filepath, None)

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

    def _bulk_insert(self, filepath, entries, mtime, word_set=None):
        """
        Insert entries for a single file during initial indexing.

        Called by the worker thread.  Acquires the lock internally.

        :param str filepath: Normalized absolute path.
        :param list entries: List of ``SymbolEntry`` namedtuples.
        :param float mtime: File modification time.
        :param frozenset word_set: Identifiers seen in the file (used by
            ``find_usages`` to skip files that cannot contain the target).
        """
        with self._lock:
            self._symbols_by_file[filepath] = entries
            self._file_mtimes[filepath] = mtime
            if word_set is not None:
                self._file_words[filepath] = word_set

            for entry in entries:
                bucket = self._symbols_by_name.setdefault(entry.name, [])
                bucket.append(entry)

            if filepath not in self._all_files:
                self._all_files.append(filepath)


# --- Freshness Walk (used by SymbolIndex.is_fresh_for) -----------------

def _walk_folder_for_freshness(root, current, depth, file_list, excluded_folders):
    """
    Recursively enumerate eligible source files under *current*.

    Mirrors ``IndexWorker._walk_folder`` but without cancellation,
    progress, or parsing -- it is meant to be called from the main
    thread before indexing starts, solely to compare the disk state
    against a cached index's file set and mtimes.

    :param str root: Top-level workspace folder (for logging context).
    :param str current: Directory currently being walked.
    :param int depth: Current recursion depth.
    :param list file_list: Accumulator for normalized file paths.
    :param set excluded_folders: Folder names to skip (from project config).
    """
    if depth > _MAX_DEPTH:
        return

    try:
        entries = os.listdir(current)
    except (PermissionError, OSError):
        return

    for entry in entries:
        full_path = os.path.join(current, entry)
        if os.path.isdir(full_path):
            if entry in _SKIP_DIRS:
                continue
            if entry in excluded_folders:
                continue
            _walk_folder_for_freshness(
                root, full_path, depth + 1, file_list, excluded_folders,
            )
        elif os.path.isfile(full_path):
            _, ext = os.path.splitext(entry)
            if ext.lower() in _SKIP_EXTS:
                continue
            file_list.append(os.path.normpath(full_path))


# --- File Parsing (module-level, no lock needed) -----------------------

def _parse_file(filepath):
    """
    Parse a single file and return definitions plus a word set.

    Walks the file once, extracting both the list of ``SymbolEntry``
    for class/def/proc lines and a frozenset of every identifier
    in the file.  The identifier set powers the fast word-filter in
    ``SymbolIndex.find_usages``.

    :param str filepath: Absolute path to the file.
    :return: ``(entries, word_set)`` tuple, or ``(None, None)`` on read failure.
    :rtype: tuple
    """
    # Size gate — skip generated/bundled files that would dominate
    # indexing time without contributing useful "goto-def" targets.
    # Keeping the check here (not in the walker) means the single-file
    # ``update_file()`` path also benefits when the user saves a huge
    # generated file into an indexed folder.
    try:
        if os.path.getsize(filepath) > _MAX_FILE_SIZE:
            return (None, None)
    except OSError:
        # Broken symlink, permission denied, or race with a delete —
        # treat like a read failure.
        return (None, None)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except (OSError, IOError):
        return (None, None)

    entries = []
    # Build the per-file identifier set.  Using a plain set for
    # construction, frozen at the end for immutability + slightly
    # better lookup performance.
    words = set()

    for i, raw_line in enumerate(lines, start=1):
        # Collect all identifiers on this line for the word set.
        for tok in _IDENT_REGEX.findall(raw_line):
            words.add(tok)

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

    return (entries, frozenset(words))


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

    def _interruptible_sleep(self, total_secs):
        """
        Sleep for *total_secs* but check the cancel flag every 100 ms
        so project-close doesn't leave the thread blocked in sleep.

        :param float total_secs: Total duration to sleep.
        """
        slice_secs = 0.1
        remaining = total_secs
        while remaining > 0 and not self._cancelled:
            chunk = slice_secs if remaining > slice_secs else remaining
            time.sleep(chunk)
            remaining -= chunk

    def run(self):
        """
        Entry point for the background thread.

        Phase 0: Wait a short startup grace period so Maya's own init
                 disk I/O doesn't collide with ours.
        Phase 1: Walk folders and collect file paths.
        Phase 2: Parse each file and insert definitions into the index,
                 yielding the GIL periodically so the main thread can
                 run Python callbacks responsively.
        """
        # Phase 0 -- startup delay.  When Maya auto-opens the editor
        # with a large project, this thread starts while Maya is still
        # finishing its own load.  Wait a few seconds before hitting
        # the disk so Maya's startup reads have room to finish.
        self._interruptible_sleep(_STARTUP_DELAY_SECS)
        if self._cancelled:
            return

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

        # Phase 2 -- parse each file for definitions + word set.
        # ``yield_counter`` tracks files processed since the last GIL
        # yield so we sleep briefly every _YIELD_EVERY_N_FILES files.
        yield_counter = 0
        for i, filepath in enumerate(file_list):
            if self._cancelled:
                logger.info("Symbol indexing cancelled at file %d/%d", i, total)
                break

            entries, word_set = _parse_file(filepath)
            if entries is not None:
                try:
                    mtime = os.path.getmtime(filepath)
                except OSError:
                    mtime = 0.0
                self._index._bulk_insert(filepath, entries, mtime, word_set)

            # Update progress after each file.
            self._index._set_progress(i + 1, total)

            # GIL-yield throttle — every N files, briefly sleep so
            # Maya's main-thread Python callbacks can actually run.
            # Without this, the indexer holds the GIL across tight
            # regex loops and Maya's scriptJobs / idle callbacks get
            # starved until the whole index is done.
            yield_counter += 1
            if yield_counter >= _YIELD_EVERY_N_FILES:
                yield_counter = 0
                time.sleep(_YIELD_SLEEP_SECS)

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
