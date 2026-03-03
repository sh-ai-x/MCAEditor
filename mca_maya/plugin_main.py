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

from mca_core.venv_manager import setup_venv

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
PLUGIN_VERSION = "0.1.0"


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

    Called via executeDeferred from initializePlugin.  Checks the
    ``editor_was_open`` setting and opens the editor if True.

    If Maya's workspace restore created a stale empty workspace control
    (from the saved layout), we clean up the old window's resources and
    delete the control so show_mca_editor() creates a fresh one with
    the actual widget inside.
    """
    try:
        # Check setting — bail early if the editor wasn't open last session.
        from mca_core.config.settings import MCASettings
        if not MCASettings().get("editor_was_open", False):
            return

        _ctrl = "MCAEditorWorkspaceControl"
        if cmds.workspaceControl(_ctrl, exists=True):
            # Clean up any window created by the uiScript restoration
            # (may have failed or produced a blank window).
            from mca_maya import maya_window as _mw
            if _mw._mca_editor_window is not None:
                try:
                    _mw._mca_editor_window._panel.save_window_state(
                        _mw._mca_editor_window._settings
                    )
                    _mw._mca_editor_window._panel.cleanup()
                except Exception:
                    pass
                _mw._mca_editor_window = None

            # Remove stale output callback so the new window gets a clean one.
            if _mw._output_callback_id is not None:
                try:
                    import maya.api.OpenMaya as _om2
                    _om2.MMessage.removeCallback(_mw._output_callback_id)
                except Exception:
                    pass
                _mw._output_callback_id = None

            cmds.deleteUI(_ctrl)
            logger.info("Deleted stale workspace control before auto-open")

        from mca_maya.maya_window import show_mca_editor
        show_mca_editor()
    except Exception as exc:
        logger.warning("Auto-open editor failed: %s", exc)


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
    # Set up the managed venv and install/inject dependencies before any
    # imports that rely on venv packages (pywinpty, pyflakes, etc.).
    # This is fast on subsequent launches — just a sys.path.insert().
    venv_ok = setup_venv()
    if not venv_ok:
        logger.warning("Venv setup had issues — some features (terminal, "
                        "code analysis) may be unavailable. Check Script Editor.")
    else:
        logger.info("Venv setup OK")

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

    # Kick off MCP server deployment in the background.  This clones
    # MayaMCP (if needed), sets up its venv, and registers with Claude Code.
    # Runs in a daemon thread so it never blocks Maya startup.
    try:
        from mca_core import mcp_setup
        mcp_setup.ensure_maya_mcp(background=True)
    except Exception as exc:
        logger.warning("MCP setup trigger failed: %s", exc)

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
        scripts_dir = os.path.join(
            os.path.expanduser("~"), "Documents", "maya", "2025", "scripts"
        )
        setup_path = os.path.join(scripts_dir, "userSetup.py")

        # Marker lines to identify our auto-load block.
        _MARKER = "# MCA_EDITOR_AUTO_LOAD"
        _END_MARKER = "# END_MCA_EDITOR_AUTO_LOAD"

        # The auto-load block does three things:
        # 1. Checks the pluginInfo autoload flag — respects the user's
        #    choice in the Plug-in Manager.  If they unchecked "Auto load",
        #    we do NOT force the plugin back on.
        # 2. Deletes any stale workspace control left over from a previous
        #    session.  Maya saves workspace controls in its layout prefs,
        #    and the cached uiScript fires before the plugin is loaded,
        #    causing "No module named 'mca_maya'" errors.
        # 3. Loads the mcaEditor plugin if it isn't loaded yet.
        _BLOCK = (
            "{marker}\n"
            "import maya.cmds as _mca_cmds\n"
            "import maya.utils as _mca_utils\n"
            "def _mca_auto_load():\n"
            "    try:\n"
            "        if not _mca_cmds.pluginInfo('mcaEditor', q=True, autoload=True):\n"
            "            return\n"
            "    except Exception:\n"
            "        return\n"
            "    try:\n"
            "        _ctrl = 'MCAEditorWorkspaceControl'\n"
            "        if _mca_cmds.workspaceControl(_ctrl, exists=True):\n"
            "            _mca_cmds.deleteUI(_ctrl)\n"
            "    except Exception:\n"
            "        pass\n"
            "    try:\n"
            "        if not _mca_cmds.pluginInfo('mcaEditor', q=True, loaded=True):\n"
            "            _mca_cmds.loadPlugin('mcaEditor')\n"
            "    except Exception:\n"
            "        pass\n"
            "_mca_utils.executeDeferred(_mca_auto_load)\n"
            "{end_marker}\n"
        ).format(marker=_MARKER, end_marker=_END_MARKER)

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
                    cmds.pluginInfo("mcaEditor", edit=True, autoload=True)
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
        if MCASettings().get("editor_was_open", False):
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

    If the user is unloading the plugin (not a Maya shutdown), clears the
    ``editor_was_open`` setting so the editor doesn't force itself back
    open on next launch.

    :param MObject plugin: Maya's plugin MObject.
    """
    global _exit_callback_id

    fn_plugin = om2.MFnPlugin(plugin)

    # If this is a user-initiated unload (not Maya shutting down), clear
    # editor_was_open so the editor doesn't auto-open next launch.
    # During Maya shutdown, _maya_is_exiting is True, so we leave the
    # setting alone — the editor should reopen when Maya starts again.
    if not _maya_is_exiting:
        try:
            from mca_core.config.settings import MCASettings
            MCASettings().set("editor_was_open", False)
            logger.info("Cleared editor_was_open (user-initiated unload)")
        except Exception:
            pass

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
    try:
        from mca_maya.maya_window import cleanup_editor
        cleanup_editor()
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
