"""
MCA Core - Session Manager.

Handles buffer persistence and session manifest I/O for the MCA Editor.
Temp/new tabs are saved as files in the ``scripts/`` directory so they
appear in the workspace tree and are accessible to terminal AI tools.

Storage layout::

    ~/Documents/mca_preferences/
        session.json              # Tab manifest (order, languages, active tab)
        scripts/                  # Default workspace (also holds buffer files)
            Python_1.py
            MEL_2.mel
            Text_3.txt
            site-packages/        # User-installed packages (added to sys.path)

Dependencies:
    - None (pure Python stdlib)

Side effects:
    - Creates directories under ~/Documents/mca_preferences/ on first write
    - Reads/writes session.json and buffer files in that directory
    - One-time migration moves buffers from old ``buffers/`` to ``scripts/``
"""

import glob
import json
import logging
import os
import shutil
import sys

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

        When *dcc_version* is provided (e.g. ``"Maya2024"``), session
        state (``session.json``, ``output.log``) is stored in a
        version-specific subdirectory so different Maya versions don't
        overwrite each other's sessions.  The ``scripts/`` workspace
        remains shared across all versions so users have one set of
        buffer files.

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
        # SHARED across all DCC versions — one set of buffer files.
        # "site-packages" is added to sys.path so third-party packages
        # can be imported from there.
        self._scripts_dir = os.path.join(self._prefs_dir, "scripts")
        self._site_packages_dir = os.path.join(self._scripts_dir, "site-packages")

        # Buffers now live in scripts/ so they're visible in the workspace tree
        # and accessible to terminal AI tools.
        self._buffers_dir = self._scripts_dir

        # Legacy buffers directory — used only during one-time migration.
        self._legacy_buffers_dir = os.path.join(self._prefs_dir, "buffers")

        # In-memory counter for allocating unique buffer IDs.
        # Loaded from the manifest on first read, starts at 1 otherwise.
        self._next_buffer_id = 1
        self._dirs_created = False

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

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.debug("Saved buffer: %s", filepath)
        except Exception as exc:
            logger.error("Failed to save buffer %s: %s", filepath, exc)

        return filename

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

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.debug("Saved output log (%d chars)", len(content))
        except Exception as exc:
            logger.error("Failed to save output log: %s", exc)

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

    def load_manifest(self):
        """
        Read and parse the session manifest from disk.

        Restores the ``_next_buffer_id`` counter from the manifest so
        new buffers don't collide with existing buffer files.

        :return: Parsed manifest dict, or None if missing/corrupt.
        :rtype: dict or None
        """
        manifest_path = os.path.join(self._session_dir, "session.json")

        if not os.path.isfile(manifest_path):
            logger.debug("No session manifest found at %s", manifest_path)
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Restore the buffer ID counter so we don't reuse IDs.
            if "next_buffer_id" in manifest:
                self._next_buffer_id = manifest["next_buffer_id"]

            logger.debug(
                "Loaded session manifest: %d tabs, next_buffer_id=%d",
                len(manifest.get("tabs", [])),
                self._next_buffer_id,
            )
            return manifest

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Corrupt session manifest, ignoring: %s", exc)
            return None
        except Exception as exc:
            logger.error("Failed to load session manifest: %s", exc)
            return None

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
        """
        self._ensure_dirs()
        manifest_path = os.path.join(self._session_dir, "session.json")

        manifest = {
            "version": self.MANIFEST_VERSION,
            "next_buffer_id": self._next_buffer_id,
            "layout": layout_tree,
            "active_group": active_group_index,
        }

        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)

            # Count total tabs for the debug log.
            total = self._count_tabs_in_tree(layout_tree)
            logger.debug("Saved v3 session manifest: %d tabs", total)
        except Exception as exc:
            logger.error("Failed to save session manifest: %s", exc)

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
        """
        manifest = {
            "version": self.MANIFEST_VERSION,
            "next_buffer_id": self._next_buffer_id,
            "layout": layout_tree,
            "active_group": active_group_index,
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)

            # Count total tabs for the debug log.
            total = self._count_tabs_in_tree(layout_tree)
            logger.debug("Saved session manifest to %s: %d tabs", filepath, total)
        except Exception as exc:
            logger.error("Failed to save session manifest to %s: %s", filepath, exc)

    def load_manifest_from(self, filepath):
        """
        Read and parse a session manifest from an arbitrary file path.

        Used for per-project session files (``.mca-session.json``).
        Updates ``_next_buffer_id`` using ``max(current, loaded)`` to
        prevent buffer ID collisions when switching between contexts.

        :param str filepath: Absolute path to the manifest file.
        :return: Parsed manifest dict, or None if missing/corrupt.
        :rtype: dict or None
        """
        if not os.path.isfile(filepath):
            logger.debug("No session manifest found at %s", filepath)
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Use max() so IDs never collide across contexts.
            if "next_buffer_id" in manifest:
                self._next_buffer_id = max(
                    self._next_buffer_id, manifest["next_buffer_id"]
                )

            logger.debug("Loaded session manifest from %s, next_buffer_id=%d",
                         filepath, self._next_buffer_id)
            return manifest

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Corrupt session manifest at %s, ignoring: %s",
                           filepath, exc)
            return None
        except Exception as exc:
            logger.error("Failed to load session manifest from %s: %s",
                         filepath, exc)
            return None

    def _count_tabs_in_tree(self, node):
        """
        Recursively count the total number of tabs in a layout tree.

        :param dict node: Layout tree node.
        :return: Total tab count.
        :rtype: int
        """
        if not node:
            return 0
        if node.get("type") == "group":
            return len(node.get("tabs", []))
        if node.get("type") == "splitter":
            return sum(
                self._count_tabs_in_tree(c)
                for c in node.get("children", [])
            )
        return 0

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
