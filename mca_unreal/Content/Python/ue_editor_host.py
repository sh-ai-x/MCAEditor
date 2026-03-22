"""
MCA Editor — Unreal Engine Host Script.

Launches the PySide6 MCA Editor as a free-floating Qt window that stays
on top of UE's main window. Same editor as Maya — same codebase, same
features, same theme — but configured for UE:

  - No MEL language option (Python + Text only)
  - UE Output Log tailed into the MCA Editor output panel
  - Separate session workspace (ue_scripts/)
  - dcc_version="UE5" for session isolation

The window uses Qt.WindowStaysOnTopHint to float above UE at all times.
It is NOT docked — it's a free-floating popup that can't fall behind.

Called by the C++ MCAEditorModule when the user clicks the toolbar button.

Dependencies:
    - PySide6 (installed via managed venv)
    - mca_core, mca_qt packages (from MCA Editor source)
"""

import sys
import os
import re
import logging

# --- UE logging helper -----------------------------------------------------
# Python's logging module does NOT route to UE's Output Log.
# Use unreal.log() for messages that must appear in the UE log.
try:
    import unreal as _unreal
    def _ue_log(msg):
        _unreal.log(f"[MCAEditor] {msg}")
    def _ue_log_warning(msg):
        _unreal.log_warning(f"[MCAEditor] {msg}")
    def _ue_log_error(msg):
        _unreal.log_error(f"[MCAEditor] {msg}")
except ImportError:
    # Running outside UE — fall back to print.
    _unreal = None
    def _ue_log(msg):
        print(f"[MCAEditor] {msg}")
    def _ue_log_warning(msg):
        print(f"[MCAEditor] WARNING: {msg}")
    def _ue_log_error(msg):
        print(f"[MCAEditor] ERROR: {msg}")

# --- Module-level logger ---------------------------------------------------
logger = logging.getLogger("mca_editor.ue_host")

# --- Module-level state (survives across Python calls in UE) ---------------
_mca_editor_window = None
_mca_app = None
_log_tailer = None  # UELogTailer instance for piping UE logs to the output panel.


# ============================================================================
# Step 1: Locate MCA Editor source packages
# ============================================================================

# In dev, use the source directory.  In prod, packages are bundled.
_MCA_SOURCE_DIR = os.environ.get("MCA_EDITOR_SOURCE", r"E:\Projects\MCAEditor")
if os.path.isdir(_MCA_SOURCE_DIR) and _MCA_SOURCE_DIR not in sys.path:
    sys.path.insert(0, _MCA_SOURCE_DIR)
    logger.info("Added MCA source to path: %s", _MCA_SOURCE_DIR)


# ============================================================================
# Step 2: Set up managed venv for PySide6
# ============================================================================

def _setup_venv():
    """
    Ensure PySide6 and other deps are available via the managed venv.

    UE's Python doesn't include PySide6 — we install it into a versioned
    venv at ~/Documents/mca_preferences/.venv-X.Y/.
    """
    try:
        from mca_core.venv_manager import setup_venv, REQUIRED_PACKAGES

        # Add PySide6 to the requirements since UE doesn't ship it.
        ue_requirements = dict(REQUIRED_PACKAGES)
        ue_requirements["PySide6>=6.5.0"] = "PySide6"

        setup_venv(requirements=ue_requirements)
        _ue_log("Venv setup complete — PySide6 available")
    except Exception as exc:
        _ue_log_warning(f"Venv setup failed: {exc} — checking if PySide6 is importable")
        try:
            import PySide6
            _ue_log(f"PySide6 already importable: {PySide6.__file__}")
        except ImportError:
            _ue_log_error("PySide6 not available and venv setup failed — cannot launch editor")
            raise


# ============================================================================
# Step 3: UE Output Log Tailer
# ============================================================================

# Regex to parse UE log lines.  Example:
#   [2026.03.22-04.24.14:497][  0]LogPython: [MCAEditor] Something
# Groups: timestamp, frame, category, verbosity (optional), message
_UE_LOG_RE = re.compile(
    r'^\[[\d.\-:]+\]\[\s*\d+\]'       # [timestamp][frame]
    r'(\w+):\s*'                        # LogCategory:
    r'(?:(Display|Warning|Error):\s*)?'  # Optional verbosity prefix
    r'(.*)$'                            # Message
)

# Categories to skip — too noisy or internal.
_SKIP_CATEGORIES = frozenset({
    'LogSlate', 'LogStreaming', 'LogPakFile', 'LogShaderCompilers',
    'LogRHI', 'LogD3D12RHI', 'LogHAL', 'LogConfig', 'LogInit',
    'LogLoad', 'LogUObjectBase', 'LogLinker', 'LogPackageName',
    'LogAssetRegistry', 'LogContentStreaming', 'LogDerivedDataCache',
    'LogEOSSDK', 'LogEOSAnalytics', 'LogCsvProfiler', 'LogStall',
    'LogSourceControl', 'LogPluginManager', 'LogCollectionManager',
    'LogPlacementMode', 'LogZenServiceInstance', 'LogFabLauncher',
    'LogFileCache', 'LogAudio', 'LogCook', 'LogSerialization',
    'LogNetVersion', 'LogSavePackage',
})


class UELogTailer:
    """
    Tails UE's log file and pipes new lines to the MCA Editor output panel.

    Reads from the current session's log file (Saved/Logs/<Project>.log),
    skipping internal/noisy categories. Parses log severity and routes
    to the appropriate output panel method (info, warning, error).

    :param OutputWindow output: The MCA Editor output panel.
    :param str log_path: Path to UE's log file.
    """

    def __init__(self, output, log_path):
        self._output = output
        self._log_path = log_path
        self._file = None
        self._position = 0  # Byte offset — start from current end.

        # Open the log file and seek to the end so we only show NEW lines.
        try:
            self._file = open(log_path, 'r', encoding='utf-8', errors='replace')
            self._file.seek(0, 2)  # Seek to end.
            self._position = self._file.tell()
            _ue_log(f"Log tailer started: {log_path}")
        except (OSError, IOError) as exc:
            _ue_log_warning(f"Could not open log file: {exc}")

    def poll(self):
        """
        Read new lines from the log file and write them to the output panel.

        Called periodically from the Qt tick. Reads all new content since
        the last poll and routes each line based on its severity.
        """
        if self._file is None:
            return

        try:
            # On Windows, a file handle that has reached EOF won't see new
            # data appended by another process (UE) unless we re-check the
            # file size. Seek to our last known position to reset the EOF
            # flag, then read whatever UE has appended since.
            self._file.seek(self._position)
            new_data = self._file.read()
            if not new_data:
                return
            # Update our position to the new end.
            self._position = self._file.tell()

            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Skip our own log messages to avoid feedback loops.
                if '[MCAEditor]' in line:
                    continue

                # Try to parse as a structured UE log line.
                match = _UE_LOG_RE.match(line)
                if match:
                    category = match.group(1)
                    verbosity = match.group(2)  # Display, Warning, Error, or None.
                    message = match.group(3)

                    # Skip noisy internal categories.
                    if category in _SKIP_CATEGORIES:
                        continue

                    # Route to the appropriate output method.
                    label = f"[{category}] {message}"
                    if verbosity == 'Error':
                        self._output.write_error(label)
                    elif verbosity == 'Warning':
                        self._output.write_warning(label)
                    else:
                        self._output.write_output(label)
                else:
                    # Unstructured line (continuation, stack trace, etc.)
                    # — show as-is.
                    self._output.write_output(line)
        except (OSError, IOError):
            # Log file may have been rotated or deleted.
            pass

    def close(self):
        """Close the log file handle."""
        if self._file is not None:
            try:
                self._file.close()
            except (OSError, IOError):
                pass
            self._file = None


def _find_ue_log_path():
    """
    Find the current UE session's log file path.

    UE writes its log to Saved/Logs/<ProjectName>.log in the project
    directory. We find it via sys.argv or the known project path.

    :return: Path to the UE log file, or None if not found.
    :rtype: str or None
    """
    # Try to find the project directory from the UE log system.
    if _unreal is not None:
        try:
            # unreal.Paths.project_log_dir() returns the Saved/Logs/ directory.
            log_dir = _unreal.Paths.project_log_dir()
            # The main log file is named after the project target.
            # Find the most recent .log file in the directory.
            if os.path.isdir(log_dir):
                log_files = [
                    os.path.join(log_dir, f) for f in os.listdir(log_dir)
                    if f.endswith('.log') and not f.startswith('.')
                ]
                if log_files:
                    # Return the most recently modified log file.
                    log_files.sort(key=os.path.getmtime, reverse=True)
                    return log_files[0]
        except Exception as exc:
            _ue_log_warning(f"Could not find log via unreal.Paths: {exc}")

    return None


# ============================================================================
# Step 4: Create the MCA Editor as a stay-on-top window
# ============================================================================

def _launch_editor():
    """
    Create the MCA Editor panel as a free-floating Qt window above UE.

    The window uses Qt.WindowStaysOnTopHint so it always floats above
    all other windows including UE. This is simpler and more reliable
    than Win32 HWND ownership tricks.

    :return: True if the editor was created successfully.
    :rtype: bool
    """
    global _mca_editor_window, _mca_app, _log_tailer

    # If already open, just raise it.
    if _mca_editor_window is not None:
        try:
            _mca_editor_window.raise_()
            _mca_editor_window.activateWindow()
            _ue_log("Editor already open — raised to front")
            return True
        except RuntimeError:
            # C++ object deleted — recreate.
            _mca_editor_window = None

    _ue_log("=== Launching MCA Editor for UE ===")

    # --- Venv setup ---------------------------------------------------------
    _setup_venv()

    # --- QApplication -------------------------------------------------------
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    _mca_app = QApplication.instance()
    if _mca_app is None:
        _mca_app = QApplication(sys.argv)
        _ue_log("Created new QApplication")
    else:
        _ue_log("Reusing existing QApplication")

    # --- Create the editor panel --------------------------------------------
    _ue_log("Creating MCAEditorPanel...")
    from mca_core.config.settings import MCASettings
    from mca_qt.editor_panel import MCAEditorPanel

    settings = MCASettings()

    # Create with dcc_version="UE5" for session isolation, no adapter
    # manager (execution goes through _execute_locally which uses exec()).
    _mca_editor_window = MCAEditorPanel(
        settings=settings,
        adapter_manager=None,
        dcc_version="UE5",
    )
    _ue_log("MCAEditorPanel created successfully")

    # --- Configure for UE (no MEL, UE title) --------------------------------
    _mca_editor_window.setWindowTitle("MCA Editor — Unreal Engine")
    _mca_editor_window.resize(1200, 800)

    # Mark as embedded so the "No DCC" indicator and DCC menu are hidden.
    # In UE, execution goes through _execute_locally() — no adapter needed.
    _mca_editor_window._embedded_in_dcc = True
    _mca_editor_window._dcc_indicator.setVisible(False)

    # Remove all MEL-related UI elements and close MEL tabs.
    _strip_mel_from_ui(_mca_editor_window)

    # --- Start UE log tailer ------------------------------------------------
    # Pipe UE's Output Log into the MCA Editor output panel.
    log_path = _find_ue_log_path()
    if log_path:
        _log_tailer = UELogTailer(_mca_editor_window._output, log_path)
    else:
        _ue_log_warning("Could not find UE log file — log tailing disabled")

    # --- Set window to stay on top of UE ------------------------------------
    # WindowStaysOnTopHint keeps the editor above UE at all times.
    # Must be set before show() for reliable behavior.
    _mca_editor_window.setWindowFlags(
        _mca_editor_window.windowFlags() | Qt.WindowStaysOnTopHint
    )

    # Show the editor.
    _mca_editor_window.show()
    _ue_log("=== MCA Editor launched ===")
    return True


def _strip_mel_from_ui(panel):
    """
    Remove all MEL-related items from the editor panel UI.

    Removes MEL from the language combo, hides MEL menu actions,
    and closes any open MEL tabs. UE only supports Python — no MEL.

    :param MCAEditorPanel panel: The editor panel instance.
    """
    # --- Remove MEL from the language combo ---------------------------------
    try:
        combo = panel._lang_combo
        for i in range(combo.count() - 1, -1, -1):
            if combo.itemText(i) == "MEL":
                combo.removeItem(i)
                _ue_log("Removed 'MEL' from language combo")
    except AttributeError:
        pass

    # --- Hide MEL-related menu actions --------------------------------------
    try:
        for name in ("New MEL Buffer", "MEL Command Reference"):
            if name in panel._action_registry:
                action = panel._action_registry[name]
                action.setVisible(False)
                _ue_log(f"Hidden menu action: '{name}'")
    except AttributeError:
        pass

    # --- Close any open MEL tabs --------------------------------------------
    # Walk all editor groups and remove tabs whose editor language is "mel".
    # _editors is a list of (editor, tab_name, file_path) tuples.
    try:
        container = panel._group_container
        for group in container.groups():
            mel_indices = []
            for i, (editor, tab_name, file_path) in enumerate(group.editors()):
                if getattr(editor, 'language', '') == 'mel':
                    mel_indices.append(i)
            # Remove from end to start to avoid index shifting.
            for i in reversed(mel_indices):
                group.remove_editor(i)
                _ue_log(f"Closed MEL tab at index {i}")
    except (AttributeError, Exception) as exc:
        _ue_log_warning(f"Could not close MEL tabs: {exc}")


def _close_editor():
    """
    Close the MCA Editor window cleanly.

    Called by the C++ plugin when the user closes the UE tab or shuts down.
    """
    global _mca_editor_window, _log_tailer

    # Stop the log tailer.
    if _log_tailer is not None:
        _log_tailer.close()
        _log_tailer = None

    if _mca_editor_window is not None:
        try:
            _mca_editor_window.close()
            _ue_log("MCA Editor closed")
        except RuntimeError:
            pass
        _mca_editor_window = None


def _pump_qt():
    """
    Process pending Qt events and poll the UE log tailer.

    Called periodically by the C++ tick function to keep the Qt event loop
    alive while UE owns the main loop. Also reads new UE log lines and
    pipes them to the MCA Editor output panel.
    """
    # Poll the UE log tailer for new log lines.
    if _log_tailer is not None:
        _log_tailer.poll()

    # Process Qt events so the editor stays responsive.
    if _mca_app is not None:
        _mca_app.processEvents()


# ============================================================================
# Entry point — called by C++ via "py ue_editor_host.launch()"
# ============================================================================

def launch():
    """
    Public entry point for the C++ plugin.

    Creates the editor if it doesn't exist, or raises it if already open.
    """
    try:
        return _launch_editor()
    except Exception as exc:
        import traceback
        _ue_log_error(f"launch() failed: {exc}")
        _ue_log_error(traceback.format_exc())
        return False


def close():
    """Public entry point to close the editor."""
    _close_editor()


def tick():
    """Public entry point for the C++ tick — pumps Qt events."""
    _pump_qt()


# If this script is executed directly (e.g. via "py ue_editor_host"),
# launch the editor immediately.
if __name__ == "__main__":
    launch()
