"""
MCA Maya - Plugin Entry Point.

Maya plugin that replaces Maya's built-in Script Editor with MCA Editor.
When loaded, the Script Editor button and menu item open MCA Editor instead.

This file follows Maya's plugin API conventions:
    - ``initializePlugin(plugin)`` — called when plugin is loaded
    - ``uninitializePlugin(plugin)`` — called when plugin is unloaded

Deploy this file (or a symlink/copy) to:
    Documents/maya/<version>/plug-ins/mca_editor_plugin.py

Then enable it in Maya's Plug-in Manager (Windows > Settings/Preferences >
Plug-in Manager). Check "Loaded" and "Auto load" to have it start with Maya.

Dependencies:
    - maya.api.OpenMaya (plugin registration)
    - maya.cmds (command creation)
    - maya.mel (ScriptEditor override)
    - mca_maya.maya_window (show_mca_editor)
"""

import sys
import logging

import maya.api.OpenMaya as om2
import maya.cmds as cmds
import maya.mel as mel
import maya.utils

from mca_core.venv_manager import setup_venv, get_venv_python

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Silence MCA INFO/DEBUG Logging in the UI --------------------------------
# Every mca_* module uses logging.getLogger(__name__), which means their
# loggers are children of "mca_core", "mca_qt", and "mca_maya".  By
# setting these parent loggers to WARNING, all routine INFO/DEBUG messages
# (window opened, terminal started, panel expanded, etc.) are suppressed.
# Warnings and errors still come through.  To re-enable verbose output for
# debugging, run in Maya's script editor:
#     import logging; logging.getLogger("mca_core").setLevel(logging.DEBUG)
#     import logging; logging.getLogger("mca_qt").setLevel(logging.DEBUG)
#     import logging; logging.getLogger("mca_maya").setLevel(logging.DEBUG)
for _pkg in ("mca_core", "mca_qt", "mca_maya"):
    logging.getLogger(_pkg).setLevel(logging.WARNING)

# Tell Maya this plugin uses Maya Python API 2.0.
maya_useNewAPI = True

# Tracks whether Maya is shutting down (vs. user manually unloading the
# plugin).  Set to True by the kMayaExiting callback, checked in
# uninitializePlugin to decide whether editor_was_open should be cleared.
_maya_is_exiting = False

# Callback ID for the kMayaExiting scene message.  Stored here so we
# can remove it in uninitializePlugin if the plugin is unloaded before
# Maya exits.
_exit_callback_id = None

# Plugin metadata.
PLUGIN_NAME = "MCA Editor"
PLUGIN_VENDOR = "MCA Tools"
from mca_core import __version__ as PLUGIN_VERSION

# Maya version string (e.g. "2024", "2025").  Set once in initializePlugin()
# and used by maya_window.py to create version-specific settings and sessions.
_maya_version = None


# --- MCA Editor Command (for mel: mcaEditor) --------------------------------

class MCAEditorCommand(om2.MPxCommand):
    """
    Maya command that opens the MCA Editor dockable window.

    Usage from Maya's script editor or MEL::

        mcaEditor;

    Or from Python::

        import maya.cmds as cmds
        cmds.mcaEditor()
    """

    COMMAND_NAME = "mcaEditor"

    def __init__(self):
        """Initialize the command."""
        super().__init__()

    def doIt(self, arg_list):
        """
        Execute the command — opens the MCA Editor window.

        :param MArgList arg_list: Maya command arguments (unused).
        """
        from mca_maya.maya_window import show_mca_editor
        show_mca_editor()

    @staticmethod
    def creator():
        """
        Create a new instance of this command.

        :return: New command instance.
        :rtype: MCAEditorCommand
        """
        return MCAEditorCommand()


# --- Auto-Open Helper -------------------------------------------------------
# Module-level function so cmds.evalDeferred can import and call it by name.
# Defined here (not nested inside initializePlugin) because evalDeferred
# runs a string like "from mca_maya.plugin_main import _do_auto_open_editor".

def _do_auto_open_editor():
    """
    Re-open the editor if it was open when Maya last shut down.

    Called via evalDeferred(lowestPriority) from initializePlugin.
    Checks the ``editor_was_open`` setting and opens the editor if True.

    Always creates a fresh window via ``show_mca_editor()`` rather than
    reusing a window from the uiScript restoration path.  The uiScript
    path (``_restore_mca_editor``) can produce blank windows where the
    widget is parented correctly but nothing renders — so we discard
    whatever it created and start clean.
    """
    try:
        # Check setting — bail early if the editor wasn't open last session.
        # Use version-specific settings so Maya 2024/2025 have independent state.
        from mca_core.config.settings import MCASettings
        _app = "MCAEditor-Maya{}".format(_maya_version) if _maya_version else "MCAEditor"
        if not MCASettings(app_name=_app).get("editor_was_open", False):
            return

        from mca_maya import maya_window as _mw
        import maya.api.OpenMaya as _om2

        # Discard any window created by uiScript — the _restore_mca_editor
        # path can produce blank windows where the widget is parented but
        # nothing renders.  Always create fresh via show_mca_editor().
        _mw._mca_editor_window = None
        _mw._output_target = None

        _ctrl = "MCAEditorWorkspaceControl"
        if cmds.workspaceControl(_ctrl, exists=True):
            cmds.deleteUI(_ctrl)

        # --- Clean up stale state from ALL module copies -----------------
        # The dual module import problem can create separate globals in
        # different copies of maya_window.  Scan sys.modules for every copy
        # and remove their callbacks, tees, and window references so
        # show_mca_editor() starts from a clean slate.
        _tee_names = ("_StdoutTee", "_StderrTee")
        for _mod_name, _mod_obj in list(sys.modules.items()):
            if _mod_obj is None:
                continue
            if not hasattr(_mod_obj, "WORKSPACE_CONTROL_NAME"):
                continue
            if not hasattr(_mod_obj, "_output_callback_id"):
                continue
            # Remove orphaned Maya output callback.
            _cb_id = getattr(_mod_obj, "_output_callback_id", None)
            if _cb_id is not None:
                try:
                    _om2.MMessage.removeCallback(_cb_id)
                except Exception:
                    pass
                _mod_obj._output_callback_id = None
            # Clear tee and window references on every copy.
            _mod_obj._stdout_tee = None
            _mod_obj._stderr_tee = None
            _mod_obj._mca_editor_window = None

        # Unwrap ALL tee layers from sys.stdout / sys.stderr so
        # show_mca_editor() wraps Maya's raw Output — not a stale tee.
        # Use class name check (not isinstance) to handle cross-module tees.
        for _attr in ("stdout", "stderr"):
            _stream = getattr(sys, _attr)
            _depth = 0
            while type(_stream).__name__ in _tee_names and _depth < 20:
                _orig = getattr(_stream, "_original", None)
                if _orig is None:
                    break
                _stream = _orig
                _depth += 1
            setattr(sys, _attr, _stream)

        from mca_maya.maya_window import show_mca_editor
        show_mca_editor()

    except Exception as exc:
        logger.warning("Auto-open editor failed: %s", exc)


# --- First-Launch Progress Dialog -------------------------------------------

def _first_launch_setup():
    """
    Run full first-launch setup with a progress dialog.

    On the very first launch the venv doesn't exist yet, so venv creation,
    pip installs, git clone, and MCP registration all run synchronously.
    Each step takes several seconds and spawns subprocesses.  Without a
    progress dialog the user sees Maya freeze for 30-60 seconds and thinks
    it stalled.

    This function shows an indeterminate (pulsing) QProgressDialog that
    updates its label text as each step completes.  ``processEvents()``
    is called after every status update so the bar keeps animating even
    though the blocking subprocess calls are on the main thread.

    MCP setup is run synchronously here (``background=False``) so the
    user sees all setup steps in the same dialog.  On subsequent launches
    the venv already exists, so this function is never called and MCP
    runs in its normal background thread.

    :return: *True* if venv setup succeeded.
    :rtype: bool
    """
    # Maya 2025+ ships PySide6; older versions use PySide2.
    try:
        from PySide6 import QtWidgets, QtCore
    except ImportError:
        from PySide2 import QtWidgets, QtCore

    # Get Maya's main window as the parent so the dialog stays on top.
    maya_main = None
    try:
        from maya.OpenMayaUI import MQtUtil
        import shiboken2
        ptr = MQtUtil.mainWindow()
        if ptr:
            maya_main = shiboken2.wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        pass

    # Build the progress dialog — indeterminate (range 0,0 = pulsing bar),
    # no cancel button, fixed width so the label text doesn't resize it.
    # Parented to Maya's main window so it stays on top.
    dlg = QtWidgets.QProgressDialog(
        "Preparing MCA Editor for first use...",
        "",       # Empty cancel button text — hides the button.
        0, 0,     # min=max=0 → indeterminate / pulsing bar.
        maya_main,
    )
    dlg.setWindowTitle("MCA Editor Setup")
    dlg.setWindowModality(QtCore.Qt.WindowModal)
    dlg.setMinimumWidth(400)
    dlg.setCancelButton(None)  # Remove cancel button entirely.
    dlg.show()
    QtWidgets.QApplication.processEvents()

    def _on_status(msg):
        """Update the dialog label and pump the event loop."""
        dlg.setLabelText(msg)
        QtWidgets.QApplication.processEvents()

    # Run venv setup with progress callbacks.
    venv_ok = setup_venv(status_callback=_on_status)

    # Run MCP setup synchronously so all steps appear in the same dialog.
    try:
        from mca_core import mcp_setup
        mcp_setup.ensure_maya_mcp(background=False, status_callback=_on_status)
    except Exception as exc:
        logger.warning("MCP setup during first launch failed: %s", exc)

    dlg.close()
    return venv_ok


# --- Plugin Registration ----------------------------------------------------

def initializePlugin(plugin):
    """
    Initialize the MCA Editor plugin.

    Registers the ``mcaEditor`` command and overrides Maya's built-in
    ``ScriptEditor`` MEL procedure so that the Script Editor button
    (bottom-right of Maya) and Window > General Editors > Script Editor
    both open MCA Editor instead.

    :param MObject plugin: Maya's plugin MObject.
    """
    # Capture the Maya version early — used by maya_window.py to create
    # version-specific settings and session directories.
    global _maya_version
    _maya_version = cmds.about(version=True)  # e.g. "2024", "2025"
    logger.info("Maya version: %s", _maya_version)

    # --- Batch mode early exit ------------------------------------------------
    # In batch mode (maya -batch) there is no UI, so skip venv setup, MCP,
    # command ports, ScriptEditor override, and auto-open.  Only register
    # the mcaEditor command so scripts can query plugin info.
    from mca_core.platform_utils import is_batch_mode
    if is_batch_mode():
        fn_plugin = om2.MFnPlugin(plugin, PLUGIN_VENDOR, PLUGIN_VERSION)
        try:
            fn_plugin.registerCommand(
                MCAEditorCommand.COMMAND_NAME,
                MCAEditorCommand.creator,
            )
        except Exception as exc:
            logger.error("Failed to register command %s: %s",
                         MCAEditorCommand.COMMAND_NAME, exc)
            raise
        logger.info("%s v%s loaded (batch mode — UI skipped)", PLUGIN_NAME, PLUGIN_VERSION)
        return

    # Detect first launch — if the venv doesn't exist yet, we need to run
    # the full setup with a progress dialog so the user sees what's happening
    # instead of staring at a frozen Maya for 30-60 seconds.
    is_first_launch = get_venv_python() is None

    if is_first_launch:
        # First launch: show progress dialog, run venv + MCP setup
        # synchronously so the user sees all steps in one place.
        venv_ok = _first_launch_setup()
        if not venv_ok:
            logger.warning("First-launch setup had issues — some features "
                            "(terminal, code analysis) may be unavailable.")
        else:
            logger.info("First-launch setup OK")
    else:
        # Subsequent launches: fast path — just inject sys.path, no dialog.
        venv_ok = setup_venv()
        if not venv_ok:
            logger.warning("Venv setup had issues — some features (terminal, "
                            "code analysis) may be unavailable. Check Script Editor.")
        else:
            logger.info("Venv setup OK")

        # MCP setup runs in a background thread on subsequent launches
        # since everything is likely already in place (just file checks).
        try:
            from mca_core import mcp_setup
            mcp_setup.ensure_maya_mcp(background=True)
        except Exception as exc:
            logger.warning("MCP setup trigger failed: %s", exc)

    # Open Maya's command ports so external processes (like the MCP server)
    # can communicate with Maya over TCP.  The MCP server runs as a separate
    # process and sends Python commands to port 7002.  Port 7001 is the MEL
    # port, opened for completeness.
    # Use maya.utils.executeDeferred because command ports cannot be opened
    # reliably during initializePlugin — Maya's networking isn't ready yet.
    def _open_command_ports():
        """Open MEL (7001) and Python (7002) command ports for MCP access."""
        import maya.cmds as _cmds
        for port, src_type in [("7001", "mel"), ("7002", "python")]:
            port_name = ":{}".format(port)
            try:
                _cmds.commandPort(name=port_name, sourceType=src_type, echoOutput=True)
                logger.info("Opened %s command port %s", src_type, port_name)
            except RuntimeError:
                # RuntimeError is raised if the port is already open — that's fine.
                logger.debug("Command port %s already open", port_name)

    maya.utils.executeDeferred(_open_command_ports)

    fn_plugin = om2.MFnPlugin(plugin, PLUGIN_VENDOR, PLUGIN_VERSION)

    # Register the mcaEditor command.
    try:
        fn_plugin.registerCommand(
            MCAEditorCommand.COMMAND_NAME,
            MCAEditorCommand.creator,
        )
        logger.info("Registered command: %s", MCAEditorCommand.COMMAND_NAME)
    except Exception as exc:
        logger.error("Failed to register command %s: %s", MCAEditorCommand.COMMAND_NAME, exc)
        raise

    # Override Maya's ScriptEditor to open MCA Editor instead.
    # This replaces the global MEL procedure that Maya calls when the user
    # clicks the Script Editor button or uses Window > General Editors > Script Editor.
    try:
        mel.eval('''
            global proc ScriptEditor() {
                python("from mca_maya.maya_window import show_mca_editor; show_mca_editor()");
            }
        ''')
        logger.info("Overrode ScriptEditor MEL procedure -> MCA Editor")
    except Exception as exc:
        # Non-fatal: the plugin still works, just won't override the button.
        logger.warning("Could not override ScriptEditor MEL procedure: %s", exc)

    # --- Track Maya shutdown vs. user-initiated plugin unload ----------
    # Register a kMayaExiting callback so uninitializePlugin() can tell
    # whether it was called because Maya is shutting down (keep
    # editor_was_open = True for auto-reopen) or because the user
    # unchecked "Loaded" in the Plug-in Manager (clear it so the editor
    # doesn't force itself back open).
    global _exit_callback_id
    def _on_maya_exiting(*args):
        """Flag that Maya is shutting down, not a user-initiated unload."""
        global _maya_is_exiting
        _maya_is_exiting = True

    try:
        _exit_callback_id = om2.MSceneMessage.addCallback(
            om2.MSceneMessage.kMayaExiting, _on_maya_exiting
        )
    except Exception as exc:
        logger.warning("Could not register kMayaExiting callback: %s", exc)

    # --- Ensure auto-load on next Maya launch --------------------------
    # The plugin must load BEFORE Maya's workspace layout restore so the
    # uiScript can import our code.  pluginPrefs.mel auto-load is unreliable
    # for Python plugins, so we install a userSetup.py that explicitly loads
    # us.  The userSetup.py respects the pluginInfo autoload flag.
    def _ensure_auto_load():
        """Install userSetup.py (first time only) and enable auto-load flag."""
        # Install a userSetup.py that loads the plugin on Maya startup.
        # This is the most reliable auto-load mechanism for Python plugins.
        # The block respects the pluginInfo autoload flag — if the user
        # unchecks "Auto load" in the Plug-in Manager, our userSetup.py
        # will NOT reload the plugin on next launch.
        import os
        # Derive the Maya version dynamically so this works across
        # Maya 2024, 2025, 2026, etc. without hardcoding.
        from mca_core.platform_utils import get_maya_scripts_dir
        maya_version = cmds.about(version=True)
        scripts_dir = get_maya_scripts_dir(maya_version)
        setup_path = os.path.join(scripts_dir, "userSetup.py")

        # Marker lines to identify our auto-load block.
        _MARKER = "# MCA_EDITOR_AUTO_LOAD"
        _END_MARKER = "# END_MCA_EDITOR_AUTO_LOAD"

        # Detect the plugin name Maya knows us by.  The module-based
        # install uses "mca_editor_plugin" (stub file), while the
        # single-file build uses "mcaEditor".  Maya uses the filename
        # (sans .py) as the plugin name for pluginInfo queries.
        _plugin_name = "mca_editor_plugin"
        try:
            if cmds.pluginInfo("mcaEditor", q=True, loaded=True):
                _plugin_name = "mcaEditor"
        except Exception:
            pass

        # The auto-load block does four things:
        # 1. Checks the pluginInfo autoload flag — respects the user's
        #    choice in the Plug-in Manager.  If they unchecked "Auto load",
        #    we do NOT force the plugin back on.
        # 2. If the plugin is ALREADY loaded (Plug-in Manager auto-load
        #    beat us to it), skip workspace control deletion — uiScript
        #    restoration already created a working editor window.
        # 3. Deletes any stale workspace control left over from a previous
        #    session.  Maya saves workspace controls in its layout prefs,
        #    and the cached uiScript fires before the plugin is loaded,
        #    causing "No module named 'mca_maya'" errors.
        # 4. Loads the plugin if it isn't loaded yet.
        _BLOCK = (
            "{marker}\n"
            "import maya.cmds as _mca_cmds\n"
            "import maya.utils as _mca_utils\n"
            "def _mca_auto_load():\n"
            "    _pn = '{plugin_name}'\n"
            "    try:\n"
            "        if not _mca_cmds.pluginInfo(_pn, q=True, autoload=True):\n"
            "            return\n"
            "    except Exception:\n"
            "        return\n"
            "    # If plugin is already loaded (Plug-in Manager auto-load),\n"
            "    # uiScript restoration already created the editor. Skip\n"
            "    # workspace deletion so we don't destroy a working window.\n"
            "    try:\n"
            "        if _mca_cmds.pluginInfo(_pn, q=True, loaded=True):\n"
            "            return\n"
            "    except Exception:\n"
            "        pass\n"
            "    try:\n"
            "        _ctrl = 'MCAEditorWorkspaceControl'\n"
            "        if _mca_cmds.workspaceControl(_ctrl, exists=True):\n"
            "            _mca_cmds.deleteUI(_ctrl)\n"
            "    except Exception:\n"
            "        pass\n"
            "    try:\n"
            "        if not _mca_cmds.pluginInfo(_pn, q=True, loaded=True):\n"
            "            _mca_cmds.loadPlugin(_pn)\n"
            "    except Exception:\n"
            "        pass\n"
            "_mca_utils.executeDeferred(_mca_auto_load)\n"
            "{end_marker}\n"
        ).format(marker=_MARKER, end_marker=_END_MARKER,
                 plugin_name=_plugin_name)

        try:
            os.makedirs(scripts_dir, exist_ok=True)
            existing = ""
            if os.path.isfile(setup_path):
                with open(setup_path, "r") as f:
                    existing = f.read()

            if _MARKER in existing and _END_MARKER in existing:
                # Replace the existing block between markers with the
                # updated version.  This ensures any changes to the block
                # (like adding the autoload check) take effect.
                start = existing.index(_MARKER)
                end = existing.index(_END_MARKER) + len(_END_MARKER)
                # Include trailing newline if present.
                if end < len(existing) and existing[end] == "\n":
                    end += 1
                updated = existing[:start] + _BLOCK + existing[end:]
                if updated != existing:
                    with open(setup_path, "w") as f:
                        f.write(updated)
                    logger.info("Updated MCA Editor auto-load block in userSetup.py")
            elif _MARKER not in existing:
                # First install — append the block and enable auto-load.
                # Only force autoload=True on the FIRST install so that
                # subsequent user changes in the Plug-in Manager stick.
                try:
                    cmds.pluginInfo(_plugin_name, edit=True, autoload=True)
                except Exception:
                    pass
                with open(setup_path, "a") as f:
                    if existing and not existing.endswith("\n"):
                        f.write("\n")
                    f.write(_BLOCK)
                logger.info("Installed MCA Editor auto-load in userSetup.py")
        except Exception as exc:
            logger.debug("Could not install userSetup.py auto-load: %s", exc)

    maya.utils.executeDeferred(_ensure_auto_load)

    # --- Auto-open editor if it was open when Maya last closed --------
    # Two-stage deferred so the editor opens AFTER Maya's main window:
    #   1. executeDeferred (callable) — checks setting after plugin init
    #   2. evalDeferred (string, lowestPriority) — opens editor after ALL
    #      other startup tasks including workspace restore and UI layout
    #
    # cleanup_editor() deliberately does NOT clear editor_was_open, so
    # if the editor is still open at Maya shutdown, it will reopen.
    def _queue_auto_open():
        """Check setting, then queue the actual open at lowest priority."""
        from mca_core.config.settings import MCASettings
        _app = "MCAEditor-Maya{}".format(_maya_version) if _maya_version else "MCAEditor"
        if MCASettings(app_name=_app).get("editor_was_open", False):
            cmds.evalDeferred(
                "from mca_maya.plugin_main import _do_auto_open_editor; "
                "_do_auto_open_editor()",
                lowestPriority=True,
            )

    maya.utils.executeDeferred(_queue_auto_open)

    logger.info("%s v%s loaded", PLUGIN_NAME, PLUGIN_VERSION)
    om2.MGlobal.displayInfo("{} v{} loaded".format(PLUGIN_NAME, PLUGIN_VERSION))


def uninitializePlugin(plugin):
    """
    Uninitialize the MCA Editor plugin.

    Deregisters the ``mcaEditor`` command and restores Maya's default
    ``ScriptEditor`` MEL procedure.

    :param MObject plugin: Maya's plugin MObject.
    """
    global _exit_callback_id

    fn_plugin = om2.MFnPlugin(plugin)

    # NOTE: editor_was_open is NOT cleared here.  It is only set to False
    # when the user explicitly closes the editor (dockCloseEventTriggered).
    # Clearing it on plugin unload/reload would permanently break auto-open
    # because the flag persists in QSettings across Maya restarts.

    # Remove the kMayaExiting callback.
    if _exit_callback_id is not None:
        try:
            om2.MMessage.removeCallback(_exit_callback_id)
        except Exception:
            pass
        _exit_callback_id = None

    # Clean up the editor window first — terminates terminal processes,
    # adapters, and callbacks.  This must happen before the command ports
    # are closed so any in-flight communication can finish.
    # Pass _maya_is_exiting so cleanup_editor can skip Qt widget
    # operations during shutdown — Shiboken crashes if we delete UI
    # elements while Maya is tearing down its own Qt hierarchy.
    try:
        from mca_maya.maya_window import cleanup_editor
        cleanup_editor(maya_is_exiting=_maya_is_exiting)
    except Exception as exc:
        logger.warning("Editor cleanup failed: %s", exc)

    # Deregister the mcaEditor command.
    try:
        fn_plugin.deregisterCommand(MCAEditorCommand.COMMAND_NAME)
        logger.info("Deregistered command: %s", MCAEditorCommand.COMMAND_NAME)
    except Exception as exc:
        logger.error("Failed to deregister command %s: %s", MCAEditorCommand.COMMAND_NAME, exc)

    # Close the command ports we opened during init.
    try:
        if cmds.commandPort(":7001", query=True):
            cmds.commandPort(name=":7001", close=True)
            logger.info("Closed MEL command port :7001")
        if cmds.commandPort(":7002", query=True):
            cmds.commandPort(name=":7002", close=True)
            logger.info("Closed Python command port :7002")
    except Exception as exc:
        logger.warning("Could not close command ports: %s", exc)

    # Restore Maya's default ScriptEditor procedure.
    # The original proc is defined in Maya's startup MEL scripts.
    # tearOffPanel recreates the standard floating Script Editor panel.
    try:
        mel.eval('''
            global proc ScriptEditor() {
                tearOffPanel "Script Editor" "scriptEditor" true;
            }
        ''')
        logger.info("Restored default ScriptEditor MEL procedure")
    except Exception as exc:
        logger.warning("Could not restore ScriptEditor MEL procedure: %s", exc)

    logger.info("%s unloaded", PLUGIN_NAME)
    om2.MGlobal.displayInfo("{} unloaded".format(PLUGIN_NAME))
