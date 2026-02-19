"""
MCA Core - Session Manager.

Handles buffer persistence and session manifest I/O for the MCA Editor.
Temp/new tabs are saved as files in a local buffers directory so content
survives across application restarts.

Storage layout::

    ~/Documents/mca_preferences/
        session.json          # Tab manifest (order, languages, active tab)
        buffers/
            buffer_1.py
            buffer_2.mel
            buffer_3.txt

Dependencies:
    - None (pure Python stdlib)

Side effects:
    - Creates directories under ~/Documents/mca_preferences/ on first write
    - Reads/writes session.json and buffer files in that directory
"""

import json
import os
import logging

# Module-level logger.
logger = logging.getLogger(__name__)

# Extension map: language identifier -> file extension for buffer files.
LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "mel": ".mel",
    "text": ".txt",
}


# =============================================================================
# Session Manager
# =============================================================================

class SessionManager:
    """
    Manages buffer persistence and session state on disk.

    Buffer files are stored in ``~/Documents/mca_preferences/buffers/``
    and a manifest (``session.json``) tracks which tabs are open, their
    order, languages, and which tab was active.

    All file I/O is guarded with try/except so a corrupt or missing
    manifest never crashes the editor.
    """

    # Current manifest schema version — bump if the schema changes.
    MANIFEST_VERSION = 1

    def __init__(self):
        """
        Initialize the session manager and compute directory paths.

        Directories are NOT created until the first write operation
        (lazy creation via ``_ensure_dirs``).
        """
        # Base preferences directory under the user's Documents folder.
        documents = os.path.expanduser("~/Documents")
        self._prefs_dir = os.path.join(documents, "mca_preferences")
        self._buffers_dir = os.path.join(self._prefs_dir, "buffers")

        # Default workspace directories inside mca_preferences.
        # "scripts" is for user scripts, "site-packages" is added to
        # sys.path so third-party packages can be imported from there.
        self._scripts_dir = os.path.join(self._prefs_dir, "scripts")
        self._site_packages_dir = os.path.join(self._scripts_dir, "site-packages")

        # In-memory counter for allocating unique buffer IDs.
        # Loaded from the manifest on first read, starts at 1 otherwise.
        self._next_buffer_id = 1
        self._dirs_created = False

    # --- Directory Management ------------------------------------------------

    def _ensure_dirs(self):
        """
        Create the preferences and buffers directories if they don't exist.

        Called lazily on first write to avoid creating empty directories
        if the user never creates a temp buffer.
        """
        if self._dirs_created:
            return
        os.makedirs(self._buffers_dir, exist_ok=True)
        self._dirs_created = True
        logger.debug("Ensured session directories: %s", self._buffers_dir)

    # --- Buffer File I/O -----------------------------------------------------

    def save_buffer(self, buffer_id, content, language):
        """
        Write buffer content to a file in the buffers directory.

        The filename is ``buffer_{id}.{ext}`` where ext is determined
        by the language (e.g. .py, .mel, .txt).

        :param int buffer_id: Unique buffer identifier.
        :param str content: The text content to save.
        :param str language: Language identifier (python, mel, text).
        :return: The buffer filename (relative, e.g. "buffer_1.py").
        :rtype: str
        """
        self._ensure_dirs()
        ext = LANGUAGE_EXTENSIONS.get(language, ".txt")
        filename = "buffer_{}{}".format(buffer_id, ext)
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
        import sys

        os.makedirs(self._scripts_dir, exist_ok=True)
        os.makedirs(self._site_packages_dir, exist_ok=True)

        # Add site-packages to sys.path so imports work from there.
        if self._site_packages_dir not in sys.path:
            sys.path.insert(0, self._site_packages_dir)
            logger.info("Added to sys.path: %s", self._site_packages_dir)

        logger.debug("Default workspace ensured: %s", self._scripts_dir)
        return self._scripts_dir

    # --- Session Manifest I/O ------------------------------------------------

    def save_manifest(self, tabs, active_tab_index):
        """
        Write the session manifest to disk.

        The manifest records the complete tab state so the editor can
        restore the exact layout on next launch.

        :param list tabs: List of tab dicts. Each dict has:
            - ``type`` (str): "buffer" or "file"
            - ``language`` (str): Language identifier
            - ``title`` (str): Tab display name
            - ``buffer_file`` (str, optional): Buffer filename for temp tabs
            - ``file_path`` (str, optional): Absolute path for file-backed tabs
        :param int active_tab_index: Index of the currently active tab.
        """
        self._ensure_dirs()
        manifest_path = os.path.join(self._prefs_dir, "session.json")

        manifest = {
            "version": self.MANIFEST_VERSION,
            "next_buffer_id": self._next_buffer_id,
            "tabs": tabs,
            "active_tab": active_tab_index,
        }

        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)
            logger.debug("Saved session manifest: %d tabs", len(tabs))
        except Exception as exc:
            logger.error("Failed to save session manifest: %s", exc)

    def load_manifest(self):
        """
        Read and parse the session manifest from disk.

        Restores the ``_next_buffer_id`` counter from the manifest so
        new buffers don't collide with existing buffer files.

        :return: Parsed manifest dict, or None if missing/corrupt.
        :rtype: dict or None
        """
        manifest_path = os.path.join(self._prefs_dir, "session.json")

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
