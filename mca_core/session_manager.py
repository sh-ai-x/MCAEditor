"""
MCA Core - Session Manager.

Handles buffer persistence and session manifest I/O for the MCA Editor.
Temp/new tabs are saved as files in the ``scripts/`` directory so they
appear in the workspace tree and are accessible to terminal AI tools.

Storage layout::

    ~/Documents/mca_preferences/
        session.json              # Tab manifest (order, languages, active tab)
        session.json.bak          # Last known-good non-empty manifest
        recovery/                 # Crash-recovery snapshots of modified tabs
            <key>.snapshot        # Verbatim editor content
            <key>.json            # Metadata (original path, timestamps)
        scripts/                  # Default workspace (also holds buffer files)
            Python_1.py
            MEL_2.mel
            Text_3.txt
            site-packages/        # User-installed packages (added to sys.path)

Durability guarantees:
    Every write in this module goes through ``atomic_write`` -- content is
    written to a sibling ``.tmp`` file, flushed, ``fsync``ed, then moved into
    place with ``os.replace``.  A crash (or a Maya hard-exit) can therefore
    never leave a half-written, truncated session.json behind.  The previous
    behaviour -- a plain ``open(path, "w")`` -- truncated the real file first,
    so any interruption destroyed the entire tab list.

Dependencies:
    - None (pure Python stdlib)

Side effects:
    - Creates directories under ~/Documents/mca_preferences/ on first write
    - Reads/writes session.json and buffer files in that directory
    - One-time migration moves buffers from old ``buffers/`` to ``scripts/``
"""

import glob
import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import time

# Module-level logger.
logger = logging.getLogger(__name__)

# Extension map: language identifier -> file extension for buffer files.
LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "mel": ".mel",
    "text": ".txt",
}

# Prefix map: language identifier -> filename prefix for buffer files.
# E.g. a Python buffer becomes "Python_1.py", MEL becomes "MEL_2.mel".
LANGUAGE_PREFIXES = {
    "python": "Python",
    "mel": "MEL",
    "text": "Text",
}

# Name of the subdirectory (inside the per-DCC session dir) that holds
# crash-recovery snapshots of modified-but-unsaved editor tabs.
RECOVERY_DIR_NAME = "recovery"

# Recovery snapshots older than this are purged on startup so the folder
# doesn't grow without bound from files the user deleted long ago.
RECOVERY_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days.


# =============================================================================
# Durable File I/O
# =============================================================================

def atomic_write(filepath, content):
    """
    Write text to *filepath* so the file is never observed half-written.

    Content goes to a sibling ``<name>.tmp`` file which is flushed and
    ``fsync``ed, then moved onto the destination with ``os.replace`` --
    an atomic rename on both Windows (ReplaceFile semantics) and POSIX.
    Readers therefore see either the complete old file or the complete
    new one, never a truncated mixture.

    This matters because the previous implementation used a plain
    ``open(path, "w")``, which truncates the destination *before* writing.
    A DCC crash or a hard process kill in that window left a zero-byte
    session.json, and the editor came back with every tab gone.

    A read-only destination (common with Perforce) has its read-only
    attribute cleared first so the replace can succeed.

    :param str filepath: Absolute destination path.
    :param str content: Text to write (encoded UTF-8).
    :return: True if the file was durably written, False on any failure.
    :rtype: bool
    """
    tmp_path = filepath + ".tmp"

    try:
        # Make sure the destination directory exists -- a missing parent
        # is the most common cause of a silent persistence failure.
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # Write + flush + fsync so the bytes are on the platter before we
        # swap the file into place.  Without fsync a power loss can leave
        # the rename committed but the data still in the page cache.
        with open(tmp_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        # Clear a read-only flag on the destination, otherwise os.replace
        # raises PermissionError on Windows for VCS-managed files.
        if os.path.exists(filepath) and not os.access(filepath, os.W_OK):
            os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)

        os.replace(tmp_path, filepath)
        return True

    except Exception as exc:
        logger.error("Atomic write failed for %s: %s", filepath, exc)
        # Leave no stray temp file behind to confuse the workspace tree.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


# =============================================================================
# Session Manager
# =============================================================================

class SessionManager:
    """
    Manages buffer persistence and session state on disk.

    Buffer files are stored in ``~/Documents/mca_preferences/scripts/``
    (the same directory used as the workspace root) and a manifest
    (``session.json``) tracks which tabs are open, their order, languages,
    and which tab was active.

    On first launch after the migration, existing buffers are moved from
    the old ``buffers/`` directory into ``scripts/``.

    All file I/O is guarded with try/except so a corrupt or missing
    manifest never crashes the editor.
    """

    # Current manifest schema version — bump if the schema changes.
    # v1: flat "tabs" list, single active_tab
    # v2: "groups" array (each with "tabs" + "active_tab"),
    #     plus "active_group" and "group_splitter_sizes"
    # v3: recursive "layout" tree with nested splitters and groups,
    #     supports both horizontal and vertical splits
    MANIFEST_VERSION = 3

    def __init__(self, dcc_version=None):
        """
        Initialize the session manager and compute directory paths.

        When *dcc_version* is provided (e.g. ``"Maya2024"``, ``"UE5"``),
        session state (``session.json``, ``output.log``) is stored in a
        version-specific subdirectory so different DCC versions don't
        overwrite each other's sessions.  Maya versions share
        ``scripts/`` workspace; UE versions get a separate ``ue_scripts/``
        directory since Maya and UE work in different environments.

        Directories are NOT created until the first write operation
        (lazy creation via ``_ensure_dirs``).

        :param str dcc_version: Optional DCC version identifier for
            per-version session isolation (e.g. ``"Maya2024"``).
        """
        # Base preferences directory under the user's Documents folder.
        # Centralized in mca_core.__init__.get_prefs_dir().
        from mca_core import get_prefs_dir
        self._prefs_dir = get_prefs_dir()

        # When running inside a specific DCC version, session state goes
        # into a version-specific subdirectory.  This prevents Maya 2024
        # and 2025 from overwriting each other's tab layouts and output.
        self._dcc_version = dcc_version
        if dcc_version:
            self._session_dir = os.path.join(self._prefs_dir, dcc_version)
        else:
            self._session_dir = self._prefs_dir

        # Default workspace directories inside mca_preferences.
        # "scripts" is for user scripts AND buffer storage (unified).
        # UE gets its own "ue_scripts/" directory because Maya and UE work
        # in completely different environments — shared defaults make no sense.
        # Maya versions (2024, 2025, 2026) share "scripts/" since they all
        # target the same Maya Python environment.
        if dcc_version and dcc_version.startswith("UE"):
            scripts_name = "ue_scripts"
        else:
            scripts_name = "scripts"
        self._scripts_dir = os.path.join(self._prefs_dir, scripts_name)
        self._site_packages_dir = os.path.join(self._scripts_dir, "site-packages")

        # Buffers now live in scripts/ so they're visible in the workspace tree
        # and accessible to terminal AI tools.
        self._buffers_dir = self._scripts_dir

        # Legacy buffers directory — used only during one-time migration.
        self._legacy_buffers_dir = os.path.join(self._prefs_dir, "buffers")

        # Crash-recovery snapshots live beside the session manifest so each
        # DCC version recovers only its own tabs.
        self._recovery_dir = os.path.join(self._session_dir, RECOVERY_DIR_NAME)

        # In-memory counter for allocating unique buffer IDs.
        # Loaded from the manifest on first read, starts at 1 otherwise.
        self._next_buffer_id = 1
        self._dirs_created = False

        # Set by the manifest reader when a manifest file exists on disk
        # but could not be parsed.  Callers check this before writing a
        # fresh/blank session so an unreadable manifest is never replaced
        # by an empty one (which is how sessions used to vanish for good).
        self._last_load_corrupt = False

    # --- Directory Management ------------------------------------------------

    def _ensure_dirs(self):
        """
        Create the scripts and site-packages directories if they don't exist.

        Called lazily on first write to avoid creating empty directories
        if the user never creates a temp buffer.  Since buffers now live
        in ``scripts/``, this also creates ``site-packages/`` inside it.
        """
        if self._dirs_created:
            return
        os.makedirs(self._buffers_dir, exist_ok=True)
        os.makedirs(self._site_packages_dir, exist_ok=True)
        # Create the version-specific session directory if needed.
        if self._session_dir != self._prefs_dir:
            os.makedirs(self._session_dir, exist_ok=True)
        # Recovery snapshots need their directory up front -- autosave runs
        # on a timer and must never fail just because the folder is missing.
        os.makedirs(self._recovery_dir, exist_ok=True)
        self._dirs_created = True
        logger.debug("Ensured session directories: %s", self._buffers_dir)

    # --- Legacy Migration ----------------------------------------------------

    def migrate_buffers_to_scripts(self):
        """
        One-time migration: move buffer files from old ``buffers/`` to ``scripts/``.

        Scans ``mca_preferences/buffers/`` for buffer files (both legacy
        ``buffer_*`` and current ``Python_*``/``MEL_*``/``Text_*`` naming)
        and moves each one into ``scripts/`` (skipping if a same-named file
        already exists there).  After migration, removes the empty ``buffers/``
        directory if possible.

        Safe to call on every launch — does nothing if ``buffers/`` doesn't
        exist or is already empty.
        """
        legacy = self._legacy_buffers_dir

        # Nothing to migrate if the old directory doesn't exist.
        if not os.path.isdir(legacy):
            return

        # Ensure the target (scripts/) exists before moving anything.
        self._ensure_dirs()

        # Find all buffer files in the legacy directory.
        # Match both old naming (buffer_*) and new naming (Python_*, MEL_*, Text_*).
        patterns = [
            "buffer_*.py", "buffer_*.mel", "buffer_*.txt",
            "Python_*.py", "MEL_*.mel", "Text_*.txt",
        ]
        moved = 0
        for pattern in patterns:
            for src_path in glob.glob(os.path.join(legacy, pattern)):
                filename = os.path.basename(src_path)
                dst_path = os.path.join(self._scripts_dir, filename)

                # Skip if a file with the same name already exists in scripts/.
                if os.path.exists(dst_path):
                    logger.debug("Migration skip (already exists): %s", filename)
                    continue

                try:
                    shutil.move(src_path, dst_path)
                    moved += 1
                    logger.debug("Migrated buffer: %s -> %s", src_path, dst_path)
                except Exception as exc:
                    logger.warning("Failed to migrate buffer %s: %s", filename, exc)

        if moved:
            logger.info("Migrated %d buffer(s) from buffers/ to scripts/", moved)

        # Remove the old buffers/ directory if it's now empty.
        try:
            if os.path.isdir(legacy) and not os.listdir(legacy):
                os.rmdir(legacy)
                logger.info("Removed empty legacy buffers directory: %s", legacy)
        except Exception as exc:
            logger.debug("Could not remove legacy buffers dir: %s", exc)

    # --- Buffer File I/O -----------------------------------------------------

    def save_buffer(self, buffer_id, content, language):
        """
        Write buffer content to a file in the buffers directory.

        The filename is ``{Language}_{id}.{ext}`` where Language is the
        display name (Python, MEL, Text) and ext is the corresponding
        extension.  For example: ``Python_1.py``, ``MEL_2.mel``.

        :param int buffer_id: Unique buffer identifier.
        :param str content: The text content to save.
        :param str language: Language identifier (python, mel, text).
        :return: The buffer filename (relative, e.g. "Python_1.py").
        :rtype: str
        """
        self._ensure_dirs()
        ext = LANGUAGE_EXTENSIONS.get(language, ".txt")
        prefix = LANGUAGE_PREFIXES.get(language, "Text")
        filename = "{}_{}{}".format(prefix, buffer_id, ext)
        filepath = os.path.join(self._buffers_dir, filename)

        # Durable write: a truncated buffer file is silent data loss, since
        # the user has no other copy of a scratch tab's contents.
        if atomic_write(filepath, content):
            logger.debug("Saved buffer: %s", filepath)
            return filename

        # Return None so the caller can detect the failure and avoid
        # clearing the editor's modified flag on a stale on-disk buffer.
        # Previous behaviour returned the filename regardless of write
        # success, which made the editor think the save had worked.
        logger.error("Failed to save buffer %s", filepath)
        return None

    def load_buffer(self, buffer_filename):
        """
        Read buffer content from a file in the buffers directory.

        :param str buffer_filename: The buffer filename (e.g. "buffer_1.py").
        :return: The file content, or None if the file is missing or unreadable.
        :rtype: str or None
        """
        filepath = os.path.join(self._buffers_dir, buffer_filename)

        if not os.path.isfile(filepath):
            logger.warning("Buffer file not found: %s", filepath)
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            logger.error("Failed to load buffer %s: %s", filepath, exc)
            return None

    def remove_buffer(self, buffer_filename):
        """
        Delete a buffer file from disk. Silent if the file doesn't exist.

        :param str buffer_filename: The buffer filename (e.g. "buffer_1.py").
        """
        filepath = os.path.join(self._buffers_dir, buffer_filename)

        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
                logger.debug("Removed buffer: %s", filepath)
        except Exception as exc:
            logger.error("Failed to remove buffer %s: %s", filepath, exc)

    # --- Output Content Persistence ------------------------------------------

    def save_output(self, content):
        """
        Save the output panel text to a file alongside the session manifest.

        Stored as ``output.log`` in the preferences directory so the
        output window contents survive across restarts.

        :param str content: The plain text content of the output panel.
        """
        self._ensure_dirs()
        filepath = os.path.join(self._session_dir, "output.log")

        if atomic_write(filepath, content):
            logger.debug("Saved output log (%d chars)", len(content))
        else:
            logger.error("Failed to save output log: %s", filepath)

    def load_output(self):
        """
        Load the saved output panel text from disk.

        :return: The saved output text, or None if no file exists.
        :rtype: str or None
        """
        filepath = os.path.join(self._session_dir, "output.log")

        if not os.path.isfile(filepath):
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            logger.debug("Loaded output log (%d chars)", len(content))
            return content
        except Exception as exc:
            logger.error("Failed to load output log: %s", exc)
            return None

    # --- Buffer ID Allocation ------------------------------------------------

    def allocate_buffer_id(self):
        """
        Return the next available buffer ID and increment the counter.

        :return: A unique buffer ID.
        :rtype: int
        """
        buffer_id = self._next_buffer_id
        self._next_buffer_id += 1
        return buffer_id

    # --- Default Workspace ---------------------------------------------------

    @property
    def scripts_dir(self):
        """
        Path to the default user scripts workspace folder.

        :rtype: str
        """
        return self._scripts_dir

    @property
    def site_packages_dir(self):
        """
        Path to the user site-packages folder (inside scripts/).

        This directory is added to ``sys.path`` so third-party
        packages placed here can be imported in scripts.

        :rtype: str
        """
        return self._site_packages_dir

    def ensure_default_workspace(self):
        """
        Create the default workspace directories if they don't exist.

        Creates ``mca_preferences/scripts/`` and
        ``mca_preferences/scripts/site-packages/``, then adds the
        site-packages directory to ``sys.path`` if not already present.

        :return: The scripts directory path (for use as a workspace root).
        :rtype: str
        """
        os.makedirs(self._scripts_dir, exist_ok=True)
        os.makedirs(self._site_packages_dir, exist_ok=True)

        # Add site-packages to sys.path so imports work from there.
        if self._site_packages_dir not in sys.path:
            sys.path.insert(0, self._site_packages_dir)
            logger.info("Added to sys.path: %s", self._site_packages_dir)

        logger.debug("Default workspace ensured: %s", self._scripts_dir)
        return self._scripts_dir

    # --- Session Manifest I/O ------------------------------------------------

    @property
    def default_manifest_path(self):
        """
        Absolute path of the default (non-project) session manifest.

        :rtype: str
        """
        return os.path.join(self._session_dir, "session.json")

    @property
    def last_load_was_corrupt(self):
        """
        Whether the most recent manifest read hit an unreadable file.

        The editor uses this to distinguish "no session has ever been
        saved" (safe to start fresh and overwrite) from "a session
        exists but we could not read it" (must NOT be overwritten with
        a blank one, or the user's tab list is destroyed for good).

        :rtype: bool
        """
        return self._last_load_corrupt

    def _read_manifest(self, filepath, use_max_buffer_id):
        """
        Read a manifest, falling back to the ``.bak`` copy when needed.

        Recovery order:

        1. The manifest itself.
        2. ``<filepath>.bak`` -- the last manifest that was known to
           parse and contain at least one tab.

        A file that exists but is empty or unparseable counts as corrupt
        and sets ``last_load_was_corrupt``, which stops the editor from
        clobbering it with a blank session on the next save.

        :param str filepath: Absolute path to the manifest file.
        :param bool use_max_buffer_id: When True, merge the loaded
            ``next_buffer_id`` with the in-memory counter using ``max()``
            so IDs never collide across contexts (project switching).
            When False, adopt the loaded value directly.
        :return: Parsed manifest dict, or None if nothing was readable.
        :rtype: dict or None
        """
        self._last_load_corrupt = False

        backup_path = filepath + ".bak"
        primary_existed = os.path.isfile(filepath)

        # Try the live manifest first, then the backup.
        for candidate, is_backup in ((filepath, False), (backup_path, True)):
            if not os.path.isfile(candidate):
                continue

            try:
                with open(candidate, "r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                logger.warning("Corrupt session manifest at %s: %s", candidate, exc)
                continue
            except Exception as exc:
                logger.error("Failed to read session manifest %s: %s", candidate, exc)
                continue

            # A manifest that parses but isn't a dict is unusable.
            if not isinstance(manifest, dict):
                logger.warning("Session manifest at %s is not an object", candidate)
                continue

            # Restore the buffer ID counter so we don't reuse IDs and
            # overwrite an existing buffer file.
            loaded_id = manifest.get("next_buffer_id")
            if isinstance(loaded_id, int):
                if use_max_buffer_id:
                    self._next_buffer_id = max(self._next_buffer_id, loaded_id)
                else:
                    self._next_buffer_id = loaded_id

            if is_backup:
                # We only get here when the primary was missing or bad.
                logger.warning(
                    "Recovered session from backup manifest: %s", backup_path
                )

            logger.debug(
                "Loaded session manifest %s: %d tabs, next_buffer_id=%d",
                candidate,
                self._count_tabs_in_tree(manifest.get("layout")),
                self._next_buffer_id,
            )
            return manifest

        # Nothing loaded.  If a file was sitting there but wouldn't parse,
        # flag it so callers refuse to overwrite it.
        if primary_existed:
            self._last_load_corrupt = True
            logger.error(
                "Session manifest %s exists but could not be read; "
                "the current session will not overwrite it.", filepath
            )
        else:
            logger.debug("No session manifest found at %s", filepath)
        return None

    def _write_manifest(self, filepath, layout_tree, active_group_index):
        """
        Serialize and durably write a v3 manifest, rotating the backup.

        Sequence:

        1. Serialize to a string first -- a serialization error must not
           be allowed to damage the file already on disk.
        2. If the existing manifest parses *and* holds at least one tab,
           copy it to ``<filepath>.bak``.  The backup therefore always
           holds the most recent non-empty session, which is what makes
           it useful as a recovery source.
        3. Atomically replace the live manifest.

        :param str filepath: Absolute path to write the manifest file.
        :param dict layout_tree: Recursive layout dict.
        :param int active_group_index: Index of the active group (DFS order).
        :return: True if the manifest was written.
        :rtype: bool
        """
        manifest = {
            "version": self.MANIFEST_VERSION,
            "next_buffer_id": self._next_buffer_id,
            "layout": layout_tree,
            "active_group": active_group_index,
            # Wall-clock stamp purely for humans debugging a lost session.
            "saved_at": time.time(),
        }

        # Serialize before touching anything on disk.
        try:
            payload = json.dumps(manifest, indent=4)
        except (TypeError, ValueError) as exc:
            logger.error("Session manifest is not serializable: %s", exc)
            return False

        self._rotate_manifest_backup(filepath)

        if not atomic_write(filepath, payload):
            logger.error("Failed to save session manifest: %s", filepath)
            return False

        total = self._count_tabs_in_tree(layout_tree)
        logger.debug("Saved session manifest %s: %d tabs", filepath, total)
        return True

    def _rotate_manifest_backup(self, filepath):
        """
        Copy the current manifest to ``.bak`` when it is worth keeping.

        Only a manifest that parses *and* contains at least one tab is
        promoted to the backup slot.  Backing up an empty or corrupt
        manifest would destroy the one good copy we have -- exactly the
        failure this backup exists to protect against.

        :param str filepath: Absolute path of the live manifest file.
        """
        if not os.path.isfile(filepath):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
        except Exception:
            # Corrupt or unreadable -- leave the existing .bak alone,
            # it is almost certainly better than what's on disk now.
            return

        if not isinstance(existing, dict):
            return
        if self._count_tabs_in_tree(existing.get("layout")) < 1:
            # Empty session (user closed everything).  Keep the older,
            # non-empty backup rather than overwriting it with nothing.
            return

        try:
            shutil.copy2(filepath, filepath + ".bak")
        except Exception as exc:
            logger.debug("Could not rotate manifest backup for %s: %s", filepath, exc)

    def load_manifest(self):
        """
        Read and parse the default session manifest from disk.

        Restores the ``_next_buffer_id`` counter from the manifest so
        new buffers don't collide with existing buffer files.  Falls
        back to ``session.json.bak`` when the live manifest is missing
        or unreadable.

        :return: Parsed manifest dict, or None if missing/corrupt.
        :rtype: dict or None
        """
        return self._read_manifest(self.default_manifest_path,
                                   use_max_buffer_id=False)

    def save_manifest_v3(self, layout_tree, active_group_index):
        """
        Write a v3 session manifest with a recursive layout tree.

        The layout tree contains nested splitter and group nodes.
        Group nodes carry their tab data (type, language, title, etc.).

        :param dict layout_tree: Recursive layout dict with "type" nodes.
            Splitter nodes: {"type": "splitter", "orientation": "horizontal"/"vertical",
                             "sizes": [...], "children": [...]}
            Group nodes: {"type": "group", "tabs": [...], "active_tab": int}
        :param int active_group_index: Index of the active group (DFS order).
        :return: True if the manifest was written.
        :rtype: bool
        """
        self._ensure_dirs()
        return self._write_manifest(self.default_manifest_path,
                                    layout_tree, active_group_index)

    def save_manifest_to(self, filepath, layout_tree, active_group_index):
        """
        Write a v3 session manifest to an arbitrary file path.

        Used for per-project session files (``.mca-session.json``)
        stored in the project root. The format is identical to
        ``save_manifest_v3`` but writes to the caller-specified path
        instead of the default ``session.json``.

        :param str filepath: Absolute path to write the manifest file.
        :param dict layout_tree: Recursive layout dict (same as save_manifest_v3).
        :param int active_group_index: Index of the active group (DFS order).
        :return: True if the manifest was written.
        :rtype: bool
        """
        return self._write_manifest(filepath, layout_tree, active_group_index)

    def load_manifest_from(self, filepath):
        """
        Read and parse a session manifest from an arbitrary file path.

        Used for per-project session files (``.mca-session.json``).
        Updates ``_next_buffer_id`` using ``max(current, loaded)`` to
        prevent buffer ID collisions when switching between contexts.
        Falls back to ``<filepath>.bak`` when the live file is bad.

        :param str filepath: Absolute path to the manifest file.
        :return: Parsed manifest dict, or None if missing/corrupt.
        :rtype: dict or None
        """
        return self._read_manifest(filepath, use_max_buffer_id=True)

    def _count_tabs_in_tree(self, node):
        """
        Recursively count the total number of tabs in a layout tree.

        :param dict node: Layout tree node.
        :return: Total tab count.
        :rtype: int
        """
        # Defensive: this runs against manifests loaded from disk, which
        # may be hand-edited or partially corrupt, so never assume shape.
        if not node or not isinstance(node, dict):
            return 0
        if node.get("type") == "group":
            tabs = node.get("tabs", [])
            return len(tabs) if isinstance(tabs, list) else 0
        if node.get("type") == "splitter":
            children = node.get("children", [])
            if not isinstance(children, list):
                return 0
            return sum(self._count_tabs_in_tree(c) for c in children)
        return 0

    # --- Crash-Recovery Snapshots --------------------------------------------

    def _recovery_key(self, file_path):
        """
        Build a stable, filesystem-safe key for a tab's recovery snapshot.

        The key is a SHA-1 of the normalized absolute path, truncated to
        16 hex characters.  Hashing avoids every problem with turning a
        real path into a filename (length limits, drive letters, colons,
        separators) while still being deterministic across launches.

        :param str file_path: The tab's file path.
        :return: 16-character hex key.
        :rtype: str
        """
        # normcase folds Windows case/separator differences so the same
        # file never gets two snapshots.
        normalized = os.path.normcase(os.path.abspath(file_path))
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        return digest[:16]

    def save_recovery(self, file_path, content):
        """
        Write a crash-recovery snapshot for a modified tab.

        Two files are written into ``recovery/``: ``<key>.snapshot``
        holding the editor text verbatim, and ``<key>.json`` holding the
        metadata needed to decide, on the next launch, whether the
        snapshot is newer than the file on disk.

        This never touches the user's real file -- it is a shadow copy,
        so an autosave can't surprise-overwrite source they didn't mean
        to change or fight a Perforce read-only flag.

        :param str file_path: Absolute path of the tab's backing file.
        :param str content: Current editor text to snapshot.
        :return: True if the snapshot was written.
        :rtype: bool
        """
        if not file_path:
            return False

        self._ensure_dirs()
        key = self._recovery_key(file_path)
        snapshot_path = os.path.join(self._recovery_dir, key + ".snapshot")
        meta_path = os.path.join(self._recovery_dir, key + ".json")

        # Record the backing file's mtime/size so restore can tell whether
        # the file changed underneath us since the snapshot was taken.
        try:
            source_mtime = os.path.getmtime(file_path)
            source_size = os.path.getsize(file_path)
        except OSError:
            source_mtime = 0.0
            source_size = -1

        meta = {
            "file_path": file_path,
            "saved_at": time.time(),
            "source_mtime": source_mtime,
            "source_size": source_size,
        }

        # Content first: if the process dies between the two writes, a
        # snapshot with no metadata is recoverable, but metadata pointing
        # at a missing snapshot is not.
        if not atomic_write(snapshot_path, content):
            return False
        if not atomic_write(meta_path, json.dumps(meta, indent=4)):
            return False

        logger.debug("Recovery snapshot saved for %s (%d chars)",
                     file_path, len(content))
        return True

    def load_recovery(self, file_path):
        """
        Load a crash-recovery snapshot for *file_path*, if one exists.

        :param str file_path: Absolute path of the tab's backing file.
        :return: ``(content, metadata)`` tuple, or None when there is no
            usable snapshot.
        :rtype: tuple or None
        """
        if not file_path:
            return None

        key = self._recovery_key(file_path)
        snapshot_path = os.path.join(self._recovery_dir, key + ".snapshot")
        meta_path = os.path.join(self._recovery_dir, key + ".json")

        if not os.path.isfile(snapshot_path):
            return None

        try:
            with open(snapshot_path, "r", encoding="utf-8", newline="") as handle:
                content = handle.read()
        except Exception as exc:
            logger.warning("Could not read recovery snapshot %s: %s",
                           snapshot_path, exc)
            return None

        # Metadata is a nice-to-have: a snapshot without it is still
        # worth offering back to the user.
        meta = {}
        try:
            if os.path.isfile(meta_path):
                with open(meta_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    meta = loaded
        except Exception as exc:
            logger.debug("Could not read recovery metadata %s: %s", meta_path, exc)

        return content, meta

    def clear_recovery(self, file_path):
        """
        Delete the recovery snapshot for a file.

        Called once the tab's content is genuinely on disk, so a stale
        snapshot can't be offered back later as if it were unsaved work.

        :param str file_path: Absolute path of the tab's backing file.
        """
        if not file_path:
            return

        key = self._recovery_key(file_path)
        for suffix in (".snapshot", ".json"):
            target = os.path.join(self._recovery_dir, key + suffix)
            try:
                if os.path.isfile(target):
                    os.remove(target)
            except OSError as exc:
                logger.debug("Could not remove recovery file %s: %s", target, exc)

    def purge_stale_recoveries(self, max_age_seconds=RECOVERY_MAX_AGE_SECONDS):
        """
        Delete recovery snapshots older than *max_age_seconds*.

        Housekeeping so the recovery folder doesn't accumulate snapshots
        for files the user deleted or renamed months ago.  Safe to call
        on every launch.

        :param int max_age_seconds: Age threshold in seconds.
        :return: Number of snapshot pairs removed.
        :rtype: int
        """
        if not os.path.isdir(self._recovery_dir):
            return 0

        cutoff = time.time() - max_age_seconds
        removed = 0

        for name in os.listdir(self._recovery_dir):
            if not name.endswith(".snapshot"):
                continue
            snapshot_path = os.path.join(self._recovery_dir, name)
            try:
                if os.path.getmtime(snapshot_path) >= cutoff:
                    continue
                os.remove(snapshot_path)
                meta_path = snapshot_path[:-len(".snapshot")] + ".json"
                if os.path.isfile(meta_path):
                    os.remove(meta_path)
                removed += 1
            except OSError as exc:
                logger.debug("Could not purge recovery file %s: %s",
                             snapshot_path, exc)

        if removed:
            logger.info("Purged %d stale recovery snapshot(s)", removed)
        return removed

    def upgrade_manifest(self, manifest):
        """
        Upgrade a manifest to v3 format.

        Handles v1 -> v2 -> v3 upgrade chain:
        - V1: flat "tabs" list -> wrapped into v2 groups -> wrapped into v3 layout tree
        - V2: "groups" array -> wrapped into v3 layout tree
        - V3: already current, returned unchanged.

        :param dict manifest: The loaded manifest dict.
        :return: V3-formatted manifest.
        :rtype: dict
        """
        if not manifest:
            return manifest

        version = manifest.get("version", 1)

        # Already v3 with layout tree — nothing to do.
        if version >= 3 and "layout" in manifest:
            return manifest

        # --- V1 -> V2 upgrade ---
        if version < 2 or "groups" not in manifest:
            tabs = manifest.get("tabs", [])
            active_tab = manifest.get("active_tab", 0)

            manifest = {
                "version": 2,
                "next_buffer_id": manifest.get("next_buffer_id", 1),
                "groups": [
                    {
                        "tabs": tabs,
                        "active_tab": active_tab,
                    }
                ],
                "active_group": 0,
                "group_splitter_sizes": [],
            }
            logger.info("Upgraded session manifest from v%d to v2", version)
            version = 2

        # --- V2 -> V3 upgrade ---
        # Wrap the flat groups list into a single horizontal splitter node.
        groups_data = manifest.get("groups", [])
        splitter_sizes = manifest.get("group_splitter_sizes", [])

        # Build group nodes with their tab data.
        children = []
        for group_info in groups_data:
            children.append({
                "type": "group",
                "tabs": group_info.get("tabs", []),
                "active_tab": group_info.get("active_tab", 0),
            })

        # Wrap in a horizontal splitter.
        layout_tree = {
            "type": "splitter",
            "orientation": "horizontal",
            "sizes": splitter_sizes if len(splitter_sizes) == len(children) else [],
            "children": children,
        }

        upgraded = {
            "version": 3,
            "next_buffer_id": manifest.get("next_buffer_id", 1),
            "layout": layout_tree,
            "active_group": manifest.get("active_group", 0),
        }

        logger.info("Upgraded session manifest from v2 to v3")
        return upgraded
