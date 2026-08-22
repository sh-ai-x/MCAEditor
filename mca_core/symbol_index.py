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
import sys
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
    # Compiled / linked binaries.  ".pyd" and ".mll" in particular used to
    # slip through and were only rejected later by the size gate, which
    # meant every walk still paid to stat them.
    ".pyc", ".pyo", ".pyd", ".exe", ".dll", ".so", ".dylib", ".lib",
    ".a", ".o", ".obj", ".pdb", ".mll", ".bundle",
    # Images / fonts / media.
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".tga", ".tif",
    ".tiff", ".psd", ".exr", ".hdr", ".dds", ".ttf", ".otf", ".woff",
    ".woff2", ".mp3", ".mp4", ".mov", ".wav", ".avi",
    # Archives and packaged distributions.
    ".zip", ".gz", ".tar", ".7z", ".rar", ".whl", ".jar", ".egg",
    # Opaque data blobs and documents.
    ".db", ".sqlite", ".pkl", ".pickle", ".pak", ".bin", ".dat",
    ".pdf", ".docx", ".xlsx", ".pptx",
    # DCC scene / asset files -- text-ish in places but never a source
    # of symbol definitions, and frequently enormous.
    ".fbx", ".abc", ".uasset", ".umap",
}

# Filename prefixes that are never indexed.  The editor writes its own
# project and session metadata into the workspace root, and rewrites the
# session manifests on a 400ms debounce while the user works.  Indexing
# them meant every launch found "changed files" and rewrote the entire
# multi-megabyte cache for no reason.
_SKIP_FILE_PREFIXES = (".mca-",)

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
#
# Tuned down from 3.0s -- the editor opens long after Maya's startup is
# done in 99% of cases, so a 3 second pause was just dead air.  0.5s is
# enough cushion for the rare cold-launch case.
_STARTUP_DELAY_SECS = 0.5

# Release the GIL every N files parsed in Phase 2.  A small ``sleep()``
# (not ``sleep(0)``, which can be a near-no-op under heavy load) yields
# to the main thread's Python callbacks.  Total indexer overhead is
# ``(file_count / _YIELD_EVERY_N_FILES) * _YIELD_SLEEP_SECS``.
#
# Tuning history:
#   * Original: 20 / 5ms -- responsive but slow on large projects.
#   * v1.0.26:  200 / 1ms -- fast but Maya froze for ~2s when the
#               user executed code or switched tabs while indexing.
#   * Now:      40 / 2ms -- 5x more frequent yields than v1.0.26 caps
#               max main-thread stall around 200ms while costing only
#               ~1 second of total throughput on a 25k-file index.
_YIELD_EVERY_N_FILES = 40
_YIELD_SLEEP_SECS = 0.002  # 2 ms

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

# Pickle protocol used for the cache.  Pinned to 5 rather than
# ``HIGHEST_PROTOCOL`` so the on-disk format does not silently change
# shape when the interpreter is upgraded.  Protocol 5 is available on
# every Python we ship against (3.8+), covering Maya 2024 (3.10),
# Maya 2025/2026 (3.11), and the standalone build.
_CACHE_PICKLE_PROTOCOL = 5

# Bump this whenever the pickled structures change shape (e.g. adding
# a new field to SymbolEntry, changing which dicts we persist, etc.).
# Old caches with a mismatching version are silently discarded.
#
# v2: SymbolEntry serialized as plain tuples instead of the namedtuple
#     class.  Needed because the Cython/.pyc import path can mis-pin
#     ``SymbolEntry.__module__`` to ``importlib._bootstrap``, making
#     pickle unable to resolve the class name on save.  Plain tuples
#     sidestep the whole class-lookup path.
# v3: Dropped the ``symbols_by_name`` and ``all_files`` blobs -- both are
#     pure derivations of ``symbols_by_file`` and were doubling the file
#     size (and the unpickle time) for no information gain.  Strings are
#     interned at parse time so pickle's memo table collapses the millions
#     of duplicate identifiers into one copy each.  Written with protocol
#     5 instead of the default.
# v4: Payload split into a header plus bounded chunks written through one
#     shared Pickler.  A single 50 MB ``pickle.load`` held the GIL for
#     over a second, freezing the UI even though the read happens on a
#     background thread; chunking caps each uninterruptible read at about
#     80 ms.  The shared memo keeps the file the same size it was.
_CACHE_SCHEMA_VERSION = 4

# How many files' worth of data go into a single pickled chunk.  This is
# the knob that bounds how long one ``pickle.load`` call can hold the
# GIL: at 1000 files a chunk lands around 2 MB, which reads in roughly
# 80 ms.  Lower it if the editor still feels sticky while a cache loads.
_CACHE_CHUNK_FILES = 1000

# Sleep inserted between chunks while reading the cache.  ``sleep(0)`` is
# close to a no-op under load, so use a real (tiny) duration to guarantee
# the reading thread actually surrenders the GIL.
_CACHE_LOAD_YIELD_SECS = 0.001

# Older schema versions that can be read and upgraded in place rather than
# thrown away.  A cache written by any of these holds the same symbol data
# in a different container, so converting it is vastly cheaper than
# re-reading the whole workspace off disk.
_CACHE_LEGACY_VERSIONS = (2, 3)

# Version of the *parser*, independent of the cache container format.
# Bump this whenever ``_parse_file`` or the regexes it uses change what
# they extract, and teach ``_paths_needing_reparse`` which files the
# change affects.  A cache written by an older parser is still perfectly
# good for every file the change cannot touch, so this lets a parser fix
# cost a handful of file reads instead of the whole workspace.
#
# v1: original.
# v2: MEL proc regex fixed (see the note on ``_INDEX_REGEX``).
_PARSER_VERSION = 2

# Extensions always reparsed when the parser version moves, on top of
# whatever ``_paths_needing_reparse`` works out from the cached entries.
_REPARSE_ON_UPGRADE_EXTS = {".mel"}

# Tolerance (seconds) when comparing a cached mtime against the value
# currently on disk.  FAT32 and SMB shares round timestamps to 2s and
# ``st_mtime`` can jitter slightly between reads, so an exact compare
# would report perfectly good cache entries as stale.
_MTIME_TOLERANCE_SECS = 1.0

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
# NOTE on the MEL alternatives: the return type is matched as an
# *optional* group followed by a required "(".  The previous form
# ("proc" + r"\s+\w*\s*" + name) looked equivalent but was not --
# on a proc with no return type ("global proc doThing()") the greedy
# \w* swallowed the name, backtracked one character, and indexed the
# symbol as "g".  Requiring the open paren removes the ambiguity.
_INDEX_REGEX = re.compile(
    r"^\s*class\s+([A-Za-z_]\w*)\b"
    r"|^\s*def\s+([A-Za-z_]\w*)\b"
    r"|^\s*global\s+proc\s+(?:\w+(?:\s*\[\s*\]\s*)?\s+)?([A-Za-z_]\w*)\s*\("
    r"|^\s*proc\s+(?:\w+(?:\s*\[\s*\]\s*)?\s+)?([A-Za-z_]\w*)\s*\(",
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

        # NOTE: there is deliberately no separate ``_all_files`` list.
        # ``_symbols_by_file`` already has one key per indexed file, so a
        # parallel list was pure duplication -- and keeping it de-duplicated
        # cost an O(n) ``in`` scan on every single insert, which worked out
        # to ~1.6 seconds of pure list-scanning on a 26k-file workspace.

        # "/path/file.py" -> frozenset of identifiers seen in that file.
        # Populated at index time; used by find_usages to skip files
        # that cannot possibly contain the target symbol (O(1) set
        # membership vs. reading the entire file).
        self._file_words = {}

        # Current indexer state: "idle" | "indexing" | "ready".
        self._state = "idle"

        # Progress tuple: (files_done, files_total).
        self._progress = (0, 0)

        # True when the in-memory index has diverged from the pickle on
        # disk.  Lets callers skip re-serializing tens of megabytes when
        # nothing has actually changed since the cache was written.
        self._dirty = False

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
            files = list(self._symbols_by_file)
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

            # The in-memory index no longer matches the pickle on disk.
            self._dirty = True

    def clear(self):
        """
        Wipe the entire index.  Called on project close.
        """
        with self._lock:
            self._symbols_by_name.clear()
            self._symbols_by_file.clear()
            self._file_mtimes.clear()
            self._file_words.clear()
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
            return list(self._symbols_by_file)

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
            files = list(self._symbols_by_file)
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
            files = list(self._symbols_by_file)
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

        Enumerates *folders* with :func:`enumerate_source_files` -- the
        exact same filter set the indexer uses -- and compares the result
        against what the index already holds.  Returns True only when the
        two file sets are identical and every mtime agrees.

        .. warning::
           This walks the entire workspace.  Never call it from the Qt
           main thread; ``IndexWorker`` runs it (via :meth:`plan_refresh`)
           on its own daemon thread precisely so the editor can open
           without waiting for a full directory walk.

        :param list folders: Workspace folder paths to validate against.
        :param set excluded_folders: Folder names to skip (from project
            config), mirroring ``IndexWorker.__init__``.
        :return: True if the cache is still valid, False otherwise.
        :rtype: bool
        """
        disk_files = enumerate_source_files(folders, excluded_folders)

        with self._lock:
            cached = self._file_mtimes

            # File-set mismatch means something was added or deleted.
            if set(disk_files) != set(cached):
                return False

            for filepath, disk_mtime in disk_files.items():
                cached_mtime = cached.get(filepath, 0.0)
                if abs(disk_mtime - cached_mtime) > _MTIME_TOLERANCE_SECS:
                    return False

        return True

    def plan_refresh(self, disk_files):
        """
        Work out the minimum amount of parsing needed to bring this index
        in line with *disk_files*.

        This is what makes reopening the editor cheap.  The old behaviour
        was all-or-nothing: one changed file anywhere in the workspace
        invalidated the entire cache and forced a full rescan of every
        file.  Here we reuse everything whose mtime still matches and
        only touch what actually moved.

        :param dict disk_files: ``{normalized_path: mtime}`` as returned
            by :func:`enumerate_source_files`.
        :return: ``(stale, deleted)`` -- paths that need (re)parsing and
            paths that are in the index but no longer on disk.
        :rtype: tuple[list, list]
        """
        with self._lock:
            cached = dict(self._file_mtimes)

        # A file is stale when we have never seen it (``-1.0`` sentinel
        # guarantees the tolerance check fails) or its mtime moved.
        stale = [
            filepath for filepath, mtime in disk_files.items()
            if abs(mtime - cached.get(filepath, -1.0)) > _MTIME_TOLERANCE_SECS
        ]

        deleted = [
            filepath for filepath in cached
            if filepath not in disk_files
        ]

        return stale, deleted

    def adopt(self, other):
        """
        Take over *other*'s indexed data wholesale.

        Used to seed a live index from a cache freshly loaded off disk so
        Go To Declaration works within milliseconds of the worker
        starting, instead of only once a full rescan finishes.

        References are moved, not copied -- *other* is expected to be a
        throwaway ``load_from_disk`` result that nothing else holds.

        :param SymbolIndex other: Index to absorb.
        """
        with other._lock:
            symbols_by_name = other._symbols_by_name
            symbols_by_file = other._symbols_by_file
            file_mtimes = other._file_mtimes
            file_words = other._file_words
            dirty = other._dirty

        with self._lock:
            self._symbols_by_name = symbols_by_name
            self._symbols_by_file = symbols_by_file
            self._file_mtimes = file_mtimes
            self._file_words = file_words
            # Freshly adopted data usually matches what is on disk, so we
            # inherit the source's flag rather than forcing it clean -- an
            # index upgraded from an older cache format is dirty on
            # arrival and must be rewritten in the current format.
            self._dirty = dirty

    def is_dirty(self):
        """
        Return True when the in-memory index has changed since the last
        successful :meth:`save_to_disk` (or :meth:`adopt`).

        :rtype: bool
        """
        with self._lock:
            return self._dirty

    # --- Disk persistence ----------------------------------------------

    def save_to_disk(self, path):
        """
        Write a snapshot of the ready index to *path*.

        Only saves when ``get_state() == "ready"`` -- partial progress is
        intentionally not persisted because the caller has no safe way to
        tell whether the missing files were skipped (size cap, read
        error) or simply not reached before cancellation.  A partial
        snapshot would reload as "ready" and silently hide real goto-def
        targets.

        The payload is written as a header followed by a series of
        bounded chunks rather than one giant pickle.  See
        :meth:`load_from_disk` for why that shape matters.  All chunks go
        through a single ``Pickler``, so its memo table is shared across
        them and the millions of duplicate identifier strings still
        collapse to one copy in the file.

        The write is atomic: serialize into a unique temp file first,
        then rename on top of *path*.  A crash mid-write leaves the old
        cache intact rather than producing a half-written pickle.

        :param str path: Destination cache file path.  Parent directory
            is created if it doesn't exist.
        :return: *True* on success, *False* on any failure (error is
            logged, caller can carry on with the in-memory index).
        :rtype: bool
        """
        # Snapshot the in-memory state under the lock so concurrent
        # update_file() / _bulk_insert() can't change a dict while
        # pickle is walking it.  ``SymbolEntry`` is a namedtuple, but we
        # flatten every instance to a plain tuple here so pickle doesn't
        # need to resolve the class name -- the Cython/.pyc import path
        # can mis-pin ``SymbolEntry.__module__`` to
        # ``importlib._bootstrap``, which breaks pickle lookup.
        #
        # Only ``symbols_by_file`` is persisted.  ``symbols_by_name`` is
        # rebuilt from it at load time; writing both made the cache
        # roughly twice the size (and twice as slow to read) while
        # carrying no extra information.
        with self._lock:
            if self._state != "ready":
                return False
            symbols_by_file = {
                fp: [tuple(e) for e in entries]
                for fp, entries in self._symbols_by_file.items()
            }
            file_mtimes = dict(self._file_mtimes)
            file_words = dict(self._file_words)

        file_count = len(symbols_by_file)
        symbol_chunks = _chunk_dict(symbols_by_file, _CACHE_CHUNK_FILES)
        word_chunks = _chunk_dict(file_words, _CACHE_CHUNK_FILES)

        # Ensure the cache dir exists (first run on a fresh install).
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create symbol-index cache dir: %s", exc)
            return False

        # Atomic write: temp then rename.  ``os.replace`` is atomic on
        # both POSIX and Windows (unlike the older ``os.rename``).
        #
        # Two writers can race here (the indexer thread and the close-time
        # cleanup thread).  If they both opened the same ``.tmp`` filename,
        # Windows raised WinError 32 ("file is being used by another
        # process") on rename.  Make the temp suffix unique per call so
        # concurrent writers don't collide -- both eventually call
        # ``os.replace`` against the same final path, and whichever lands
        # second simply overwrites the first (still atomic).
        tmp_path = "{}.tmp.{}.{}".format(
            path, os.getpid(), threading.get_ident()
        )
        try:
            with open(tmp_path, "wb") as handle:
                pickler = pickle.Pickler(handle, protocol=_CACHE_PICKLE_PROTOCOL)
                pickler.dump({
                    "magic": _CACHE_MAGIC,
                    "version": _CACHE_SCHEMA_VERSION,
                    "parser_version": _PARSER_VERSION,
                    "file_count": file_count,
                    "symbol_chunks": len(symbol_chunks),
                    "word_chunks": len(word_chunks),
                })
                pickler.dump(file_mtimes)
                for chunk in symbol_chunks:
                    pickler.dump(chunk)
                for chunk in word_chunks:
                    pickler.dump(chunk)

            os.replace(tmp_path, path)

            # The pickle matches memory again, so a later close-time save
            # can skip rewriting tens of megabytes for nothing.
            with self._lock:
                self._dirty = False

            logger.info(
                "Saved symbol index to disk: %d files (%s)",
                file_count, path,
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
        Reconstruct a ready ``SymbolIndex`` from a snapshot on disk.

        Returns *None* on any failure -- missing file, wrong magic,
        schema mismatch, corruption.  The caller should fall through to a
        full scan in that case.

        **Why this reads in chunks:** ``pickle.load`` is a single C call
        that holds the GIL for its entire duration.  Reading a 50 MB
        index as one object froze the editor's main thread for well over
        a second even though this runs on a background thread -- the
        indexer thread simply never let go.  Reading a bounded number of
        files per ``load()`` call caps each uninterruptible stretch at
        roughly 80 ms, and the short sleep between chunks hands the GIL
        back so the UI stays responsive while the cache loads.

        :param str path: Cache file path created by ``save_to_disk``.
        :return: Populated ``SymbolIndex`` in ``"ready"`` state, or
                 ``None`` if the cache is unusable.
        :rtype: SymbolIndex or None
        """
        if not os.path.isfile(path):
            return None

        # Any exception here (corrupted pickle, truncated file, class
        # renamed since the pickle was written, etc.) means we can't
        # trust the cache -- return None so the caller rebuilds fresh.
        try:
            with open(path, "rb") as handle:
                unpickler = pickle.Unpickler(handle)
                header = unpickler.load()

                # Shape check first: if the file doesn't even look like
                # our format, silently ignore it.
                if not isinstance(header, dict):
                    return None
                if header.get("magic") != _CACHE_MAGIC:
                    return None
                version = header.get("version")

                # Older single-blob formats hold the same symbol data in
                # a different container, so upgrade them in place rather
                # than discarding them.  Throwing the cache away meant
                # re-reading every file in the workspace off disk -- over
                # three minutes on a large project on a cold filesystem
                # cache -- purely because the file layout changed.
                if version in _CACHE_LEGACY_VERSIONS:
                    return cls._from_legacy_payload(header, path)

                if version != _CACHE_SCHEMA_VERSION:
                    logger.info(
                        "Symbol index cache schema %s != current %s - rebuilding",
                        version, _CACHE_SCHEMA_VERSION,
                    )
                    return None

                symbol_chunk_count = header.get("symbol_chunks")
                word_chunk_count = header.get("word_chunks")
                if not isinstance(symbol_chunk_count, int):
                    return None
                if not isinstance(word_chunk_count, int):
                    return None

                file_mtimes = unpickler.load()

                # Rehydrate plain tuples back into SymbolEntry namedtuples
                # so callers keep attribute access (``entry.name``,
                # ``entry.line``) without knowing the cache stored tuples.
                # The by-name lookup is rebuilt here rather than read back
                # -- re-deriving 200k+ entries is a fast in-memory loop,
                # unpickling a second copy of them was not.
                symbols_by_file = {}
                symbols_by_name = {}
                for _ in range(symbol_chunk_count):
                    chunk = unpickler.load()
                    for filepath, raw_entries in chunk.items():
                        entries = [SymbolEntry(*t) for t in raw_entries]
                        symbols_by_file[filepath] = entries
                        for entry in entries:
                            symbols_by_name.setdefault(entry.name, []).append(entry)
                    time.sleep(_CACHE_LOAD_YIELD_SECS)

                file_words = {}
                for _ in range(word_chunk_count):
                    file_words.update(unpickler.load())
                    time.sleep(_CACHE_LOAD_YIELD_SECS)

            # A cache written by an older parser is still good for every
            # file that parser change cannot affect.  Drop only the ones
            # it can, so they reparse on the refresh pass.
            stale_paths = _paths_needing_reparse(
                header.get("parser_version"), symbols_by_file,
            )
            for filepath in stale_paths:
                for entry in symbols_by_file.pop(filepath, ()):
                    bucket = symbols_by_name.get(entry.name)
                    if not bucket:
                        continue
                    bucket[:] = [e for e in bucket if e.filepath != filepath]
                    if not bucket:
                        del symbols_by_name[entry.name]
                file_mtimes.pop(filepath, None)
                file_words.pop(filepath, None)

        except (OSError, pickle.UnpicklingError, EOFError, AttributeError,
                ImportError, IndexError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to load symbol index from %s: %s", path, exc)
            return None

        # Reconstruct the index in "ready" state so callers see it as a
        # finished index and don't kick off a redundant full scan.
        index = cls()
        with index._lock:
            index._symbols_by_name = symbols_by_name
            index._symbols_by_file = symbols_by_file
            index._file_mtimes = file_mtimes
            index._file_words = file_words
            index._state = "ready"
            # Dropping stale entries means the file on disk no longer
            # matches memory, so it has to be rewritten.
            index._dirty = bool(stale_paths)
            file_count = len(symbols_by_file)
            index._progress = (file_count, file_count)

        if stale_paths:
            logger.info(
                "Loaded symbol index from disk: %d files, %d queued for "
                "reparse after a parser change (%s)",
                file_count, len(stale_paths), path,
            )
        else:
            logger.info(
                "Loaded symbol index from disk: %d files (%s)",
                file_count, path,
            )
        return index

    @classmethod
    def _from_legacy_payload(cls, data, path):
        """
        Build an index from a pre-v4 cache blob.

        Schemas 2 and 3 wrote the whole index as one pickled dict rather
        than a header plus chunks, but the symbol data itself is
        identical in shape.  Converting it costs a couple of seconds;
        discarding it costs a full re-read of every file in the
        workspace, which on a large project over a slow drive is several
        minutes of the DCC feeling hung.  So we upgrade rather than
        rebuild.

        The returned index is marked dirty so the worker rewrites it in
        the current format -- otherwise the old blob would sit there and
        be re-converted on every single launch.

        :param dict data: The single dict read from the legacy cache.
        :param str path: Cache path, for logging only.
        :return: Populated ``SymbolIndex`` in ``"ready"`` state, or
                 ``None`` if the blob is missing anything we need.
        :rtype: SymbolIndex or None
        """
        required_keys = ("symbols_by_file", "file_mtimes", "file_words")
        for key in required_keys:
            if key not in data:
                logger.warning("Legacy symbol index cache missing key %r", key)
                return None

        # Intern while converting.  Legacy caches predate the
        # intern-at-parse-time change, so their strings are millions of
        # distinct objects; carrying them straight over would leave
        # pickle's memo table nothing to collapse and bake a permanently
        # oversized cache into place (measured: 85 MB instead of 51 MB,
        # and correspondingly slower to load, forever).  Interning here
        # costs a couple of seconds once, on a background thread.
        intern = sys.intern

        try:
            symbols_by_file = {}
            for filepath, entries in data["symbols_by_file"].items():
                filepath = intern(filepath)
                symbols_by_file[filepath] = [
                    SymbolEntry(
                        intern(t[0]), intern(t[1]), filepath, t[3], t[4], t[5],
                    )
                    for t in entries
                ]
        except (TypeError, ValueError, IndexError) as exc:
            logger.warning("Legacy symbol index cache is malformed: %s", exc)
            return None

        file_mtimes = {
            intern(fp): mtime for fp, mtime in data["file_mtimes"].items()
        }
        file_words = {
            intern(fp): frozenset(intern(word) for word in words)
            for fp, words in data["file_words"].items()
        }

        # Drop entries the current parser would extract differently, so
        # ``plan_refresh`` treats them as new and rereads them.  Legacy
        # caches predate the ``parser_version`` field entirely, hence None.
        stale_paths = _paths_needing_reparse(None, symbols_by_file)
        for filepath in stale_paths:
            symbols_by_file.pop(filepath, None)
            file_mtimes.pop(filepath, None)
            file_words.pop(filepath, None)

        # Rebuild the by-name lookup from what survived.
        symbols_by_name = {}
        for entries in symbols_by_file.values():
            for entry in entries:
                symbols_by_name.setdefault(entry.name, []).append(entry)

        index = cls()
        with index._lock:
            index._symbols_by_name = symbols_by_name
            index._symbols_by_file = symbols_by_file
            index._file_mtimes = file_mtimes
            index._file_words = file_words
            index._state = "ready"
            # Force a rewrite in the current format.
            index._dirty = True
            file_count = len(symbols_by_file)
            index._progress = (file_count, file_count)

        logger.info(
            "Upgraded symbol index cache v%s -> v%s: kept %d files, "
            "reparsing %d (%s)",
            data.get("version"), _CACHE_SCHEMA_VERSION,
            file_count, len(stale_paths), path,
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

            self._dirty = True

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
        Set the index's entries for a single file, replacing whatever was
        there before.

        Called by the worker thread.  Acquires the lock internally.

        The replace semantics matter on the incremental-refresh path: the
        worker re-parses files whose mtime moved, and those files are
        already present in an index adopted from the cache.  Appending to
        ``_symbols_by_name`` without dropping the previous entries first
        would leave every reparsed symbol listed twice, so Go To
        Declaration would offer the same line as two separate results.

        :param str filepath: Normalized absolute path.
        :param list entries: List of ``SymbolEntry`` namedtuples.
        :param float mtime: File modification time.
        :param frozenset word_set: Identifiers seen in the file (used by
            ``find_usages`` to skip files that cannot contain the target).
        """
        with self._lock:
            # Drop any previous entries for this file from the by-name
            # lookup.  On a cold index this pops nothing and costs a
            # single dict lookup.
            for entry in self._symbols_by_file.get(filepath, ()):
                bucket = self._symbols_by_name.get(entry.name)
                if not bucket:
                    continue
                bucket[:] = [e for e in bucket if e.filepath != filepath]
                if not bucket:
                    del self._symbols_by_name[entry.name]

            self._symbols_by_file[filepath] = entries
            self._file_mtimes[filepath] = mtime
            if word_set is not None:
                self._file_words[filepath] = word_set

            for entry in entries:
                bucket = self._symbols_by_name.setdefault(entry.name, [])
                bucket.append(entry)

            self._dirty = True


def _paths_needing_reparse(parser_version, symbols_by_file):
    """
    Work out which cached files the *current* parser would read differently.

    A cache carries the version of the parser that produced it.  When that
    version is behind, the honest-but-expensive answer is to reparse
    everything; the useful answer is to reparse only the files the specific
    parser change could possibly affect.  Each bump of ``_PARSER_VERSION``
    adds a branch here saying what it touched.

    Getting this wrong is silent: stale entries survive and Go To
    Declaration keeps pointing at symbols that no longer exist.  When in
    doubt, return everything.

    :param int parser_version: ``parser_version`` recorded in the cache,
        or ``None`` for caches written before the field existed.
    :param dict symbols_by_file: ``{path: [SymbolEntry, ...]}`` as loaded.
    :return: Paths to drop so the refresh pass reparses them.
    :rtype: list[str]
    """
    if parser_version == _PARSER_VERSION:
        return []

    # Always reparse these regardless of what the entries look like -- a
    # file that produced no entries at all under the old parser wouldn't
    # be caught by the kind check below.
    paths = {
        filepath for filepath in symbols_by_file
        if os.path.splitext(filepath)[1].lower() in _REPARSE_ON_UPGRADE_EXTS
    }

    if parser_version is None or parser_version < 2:
        # v1 -> v2 fixed the MEL proc regex, which only governs what gets
        # extracted from ``proc`` / ``global proc`` lines.  Every other
        # symbol in the cache is unaffected, so only files that produced a
        # proc entry need rereading.
        #
        # Note this is deliberately keyed off the *entry kind*, not the
        # file extension: MEL source shows up embedded in .py files
        # (generators, MEL parsers, Tcl templates), and an
        # extension-based rule left stale symbols behind in exactly those
        # files.
        paths.update(
            filepath for filepath, entries in symbols_by_file.items()
            if any(e.kind in ("proc", "global_proc") for e in entries)
        )
        return list(paths)

    # Cache from an unknown or newer parser -- take the safe route.
    logger.info(
        "Symbol index cache parser v%s is unrecognised (current v%s) "
        "- reparsing everything",
        parser_version, _PARSER_VERSION,
    )
    return list(symbols_by_file)


# --- Cache chunking ----------------------------------------------------

def _chunk_dict(source, chunk_size):
    """
    Split *source* into a list of smaller dicts of at most *chunk_size*
    items each.

    Used so the on-disk cache is written as a series of bounded pickles
    instead of one enormous one -- see :meth:`SymbolIndex.load_from_disk`
    for why the read side cares.

    :param dict source: Dictionary to split.  Not modified.
    :param int chunk_size: Maximum number of items per chunk.  Values
        below 1 are treated as 1.
    :return: List of dicts whose contents concatenate back to *source*.
        Empty input yields an empty list.
    :rtype: list[dict]
    """
    if chunk_size < 1:
        chunk_size = 1

    chunks = []
    current = {}
    for key, value in source.items():
        current[key] = value
        if len(current) >= chunk_size:
            chunks.append(current)
            current = {}

    # Trailing partial chunk.
    if current:
        chunks.append(current)

    return chunks


# --- Filesystem Enumeration --------------------------------------------

def enumerate_source_files(folders, excluded_folders=None, cancel_cb=None):
    """
    Walk *folders* and return every file the indexer considers eligible.

    This is the single source of truth for "which files belong in the
    index".  Both the initial scan and the cache-freshness comparison go
    through it, which matters more than it sounds: when the two used
    slightly different filters, the freshness check saw files the indexer
    had silently skipped, concluded the cache was stale, and forced a
    full rescan on *every* editor open.  The size gate below is exactly
    that missing filter -- oversized files are dropped here rather than
    later in :func:`_parse_file`, so a path that never makes it into the
    index never shows up on the disk side of the comparison either.

    Uses ``os.scandir`` rather than ``listdir`` + ``isdir`` + ``isfile``
    + ``getmtime``.  Windows hands back the file attributes as part of
    the directory enumeration, so ``entry.stat()`` is answered from
    cached data instead of costing three extra syscalls per file.

    :param list folders: Top-level workspace folders to walk.
    :param set excluded_folders: Folder names to skip (from project
        config), on top of the built-in ``_SKIP_DIRS`` set.
    :param callable cancel_cb: Optional zero-arg callable returning True
        when the walk should stop early (used for project close).
    :return: ``{normalized_absolute_path: mtime}`` for every eligible file.
    :rtype: dict
    """
    excluded_folders = excluded_folders or set()
    result = {}

    # Explicit stack instead of recursion -- deep asset trees can exceed
    # Python's recursion limit long before they exceed ``_MAX_DEPTH``.
    stack = [(os.path.normpath(folder), 0) for folder in folders]

    while stack:
        if cancel_cb is not None and cancel_cb():
            break

        current, depth = stack.pop()
        if depth > _MAX_DEPTH:
            continue

        try:
            scanner = os.scandir(current)
        except OSError:
            # Permission denied, path vanished mid-walk, offline share.
            continue

        with scanner:
            for entry in scanner:
                try:
                    if entry.is_dir():
                        # Skip generated / vendored / VCS directories and
                        # anything the project config excludes.
                        if entry.name in _SKIP_DIRS:
                            continue
                        if entry.name in excluded_folders:
                            continue
                        stack.append((entry.path, depth + 1))
                        continue

                    if not entry.is_file():
                        continue

                    # Editor-generated metadata (see _SKIP_FILE_PREFIXES).
                    if entry.name.startswith(_SKIP_FILE_PREFIXES):
                        continue

                    # Binary and non-source extensions never carry symbols.
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in _SKIP_EXTS:
                        continue

                    stat_result = entry.stat()

                    # Size gate -- generated bundles, autocomplete stubs
                    # and vendored single-file libraries dominate scan
                    # time and are never useful goto-def targets.
                    if stat_result.st_size > _MAX_FILE_SIZE:
                        continue

                    result[os.path.normpath(entry.path)] = stat_result.st_mtime

                except OSError:
                    # Broken junction / symlink, or a race with a delete.
                    continue

    return result


# --- File Parsing (module-level, no lock needed) -----------------------

def _parse_file(filepath):
    """
    Parse a single file and return definitions plus a word set.

    Reads the file once as a single string and runs two regex passes over
    it: one ``findall`` to collect every identifier for the word set, and
    one ``finditer`` for class/def/proc definitions.  Doing this on the
    whole buffer rather than line-by-line keeps the scanning inside the
    C regex engine instead of a Python loop over every line in the
    workspace.

    Identifiers and symbol names are interned.  A large workspace yields
    millions of duplicate identifier strings across files; interning
    collapses them to one object each, which cuts live memory and lets
    pickle's memo table shrink the on-disk cache dramatically.

    :param str filepath: Absolute path to the file.
    :return: ``(entries, word_set)`` tuple, or ``(None, None)`` on read failure.
    :rtype: tuple
    """
    # Size gate.  ``enumerate_source_files`` already filters these out for
    # the bulk scan, but ``update_file()`` calls straight in here when the
    # user saves, so the check has to live on this path too.
    try:
        if os.path.getsize(filepath) > _MAX_FILE_SIZE:
            return (None, None)
    except OSError:
        # Broken symlink, permission denied, or race with a delete —
        # treat like a read failure.
        return (None, None)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except (OSError, IOError, MemoryError):
        return (None, None)

    intern = sys.intern

    # One C-level pass for the whole file's identifier set.
    words = frozenset(intern(tok) for tok in _IDENT_REGEX.findall(text))

    # Definitions.  Most files contain none, and the combined regex is
    # anchored at line start, so this pass is cheap.
    entries = []
    for match in _INDEX_REGEX.finditer(text):
        # Determine which group matched to get name and kind.
        for group_idx, kind in _GROUP_TO_KIND.items():
            name = match.group(group_idx)
            if not name:
                continue

            # Recover the raw line and its 1-based number.  ``rfind`` /
            # ``find`` bound the line; ``count`` gives the line number.
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.start())
            if line_end == -1:
                line_end = len(text)
            raw_line = text[line_start:line_end].rstrip("\r")

            # Measure leading whitespace for indent level.
            indent = len(raw_line) - len(raw_line.lstrip())

            entries.append(SymbolEntry(
                name=intern(name),
                kind=kind,
                filepath=filepath,
                line=text.count("\n", 0, match.start()) + 1,
                line_text=raw_line,
                indent=indent,
            ))
            break

    return (entries, words)


# --- IndexWorker -------------------------------------------------------

class IndexWorker(threading.Thread):
    """
    Background daemon thread that brings a ``SymbolIndex`` in line with
    what is on disk.

    The worker owns the entire index lifecycle -- loading the on-disk
    cache, deciding what has actually changed, parsing only that, and
    writing the cache back out.  None of it runs on the Qt main thread,
    so opening the editor never waits on a directory walk, a multi-
    megabyte unpickle, or a rescan.

    Supports cooperative cancellation via ``cancel()``.

    :param SymbolIndex index: The index to populate.
    :param list folders: Workspace folder paths to walk.
    :param set excluded_folders: Folder names to skip (from project config).
    :param str cache_path: Optional path to the per-project pickle cache.
        When given, the worker loads it, refreshes it incrementally, and
        writes it back if anything changed.
    """

    def __init__(self, index, folders, excluded_folders=None, cache_path=None):
        super().__init__(daemon=True, name="MCA-SymbolIndexer")
        self._index = index
        self._folders = [os.path.normpath(f) for f in folders]
        self._excluded_folders = excluded_folders or set()
        self._cache_path = cache_path
        self._cancelled = False

    def cancel(self):
        """
        Request cooperative cancellation.  The worker checks this flag
        between files and will stop promptly.
        """
        self._cancelled = True

    def _is_cancelled(self):
        """
        Callback form of the cancel flag, handed to the folder walk so a
        project close doesn't have to wait for a full enumeration.

        :rtype: bool
        """
        return self._cancelled

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

        Phase 0: Wait a short startup grace period so the DCC's own init
                 disk I/O doesn't collide with ours.
        Phase 1: Load the on-disk cache, if there is one.
        Phase 2: Enumerate what is actually on disk right now.
        Phase 3: Adopt the cache, then parse only the files that are new
                 or whose mtime moved, and drop the ones that are gone.
        Phase 4: Persist the refreshed cache -- but only if it changed.
        """
        # Phase 0 -- startup delay.  When the DCC auto-opens the editor
        # with a large project, this thread starts while the host is
        # still finishing its own load.  Wait briefly before hitting the
        # disk so those startup reads have room to finish.
        self._interruptible_sleep(_STARTUP_DELAY_SECS)
        if self._cancelled:
            return

        self._index._set_state("indexing")
        logger.info("Symbol indexing started for %d folder(s)", len(self._folders))

        # Phase 1 -- reload the previous run's work.  This is a multi-
        # megabyte unpickle on a big workspace, which is exactly why it
        # happens here and not in the panel's __init__.
        base = None
        if self._cache_path:
            _purge_stale_temp_files(self._cache_path)
            try:
                base = SymbolIndex.load_from_disk(self._cache_path)
            except Exception as exc:
                logger.warning("Symbol index cache load failed: %s", exc)
                base = None
        if self._cancelled:
            return

        # Phase 2 -- what is on disk right now.
        disk_files = enumerate_source_files(
            self._folders, self._excluded_folders, self._is_cancelled,
        )
        if self._cancelled:
            return

        total_files = len(disk_files)

        # Phase 3 -- work out the delta.
        deleted = []
        if base is not None:
            # Take the cached data over wholesale first, so goto-def and
            # completion work immediately instead of only after the
            # refresh finishes.
            self._index.adopt(base)
            todo, deleted = self._index.plan_refresh(disk_files)
            for filepath in deleted:
                self._index._remove_file(filepath)
            logger.info(
                "Symbol index refresh: %d cached, %d changed, %d removed",
                total_files - len(todo), len(todo), len(deleted),
            )
        else:
            todo = list(disk_files)
            logger.info("Symbol indexer found %d files to scan", total_files)

        # Progress is reported against the whole workspace, not just the
        # delta, so an incremental refresh reads as "98%" rather than
        # restarting the bar from zero.
        reused = total_files - len(todo)
        self._index._set_progress(reused, total_files)

        # Phase 3b -- parse the files that actually need it.
        # ``yield_counter`` tracks files processed since the last GIL
        # yield so we sleep briefly every _YIELD_EVERY_N_FILES files.
        yield_counter = 0
        for i, filepath in enumerate(todo):
            if self._cancelled:
                logger.info(
                    "Symbol indexing cancelled at file %d/%d", i, len(todo),
                )
                return

            entries, word_set = _parse_file(filepath)
            if entries is not None:
                self._index._bulk_insert(
                    filepath, entries, disk_files.get(filepath, 0.0), word_set,
                )

            # Update progress after each file.
            self._index._set_progress(reused + i + 1, total_files)

            # GIL-yield throttle -- every N files, briefly sleep so the
            # host's main-thread Python callbacks can actually run.
            # Without this, the indexer holds the GIL across tight
            # regex loops and Maya's scriptJobs / idle callbacks get
            # starved until the whole index is done.
            yield_counter += 1
            if yield_counter >= _YIELD_EVERY_N_FILES:
                yield_counter = 0
                time.sleep(_YIELD_SLEEP_SECS)

        # Phase 4 -- publish and persist.
        self._index._set_state("ready")
        sym_count = self._index.get_symbol_count()
        logger.info(
            "Symbol indexing complete: %d files, %d symbols (%d reparsed)",
            total_files, sym_count, len(todo),
        )

        # Only rewrite the cache when something moved.  On a normal reopen
        # with an unchanged workspace this is a no-op, which keeps a large
        # pickle off the disk entirely.
        if self._cache_path and self._index.is_dirty():
            try:
                self._index.save_to_disk(self._cache_path)
            except Exception as exc:
                logger.warning("Failed to persist symbol index: %s", exc)


# --- Cache housekeeping ------------------------------------------------

def _purge_stale_temp_files(cache_path):
    """
    Delete abandoned ``<cache>.tmp.*`` files left behind by a crashed or
    killed write.

    These are full-size copies of the index -- one orphan on a large
    workspace was sitting at ~100 MB in the prefs folder -- and nothing
    else ever cleaned them up.

    The prefix deliberately stops at ``.tmp`` rather than ``.tmp.``, so
    this also sweeps up leftovers from the older naming scheme that had
    no pid/thread suffix.  A temp file another process is still writing
    is held open by Windows and simply fails to delete, which is fine.

    :param str cache_path: Path to the real cache file.
    """
    directory = os.path.dirname(cache_path)
    prefix = os.path.basename(cache_path) + ".tmp"
    try:
        names = os.listdir(directory)
    except OSError:
        return

    for name in names:
        if not name.startswith(prefix):
            continue
        try:
            os.remove(os.path.join(directory, name))
            logger.info("Removed stale symbol-index temp file: %s", name)
        except OSError:
            pass
