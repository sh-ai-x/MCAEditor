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

from mca_core.venv_manager import setup_venv

# Module-level logger.
logger = logging.getLogger(__name__)

# Tell Maya this plugin uses Maya Python API 2.0.
maya_useNewAPI = True

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

    logger.info("%s v%s loaded", PLUGIN_NAME, PLUGIN_VERSION)
    om2.MGlobal.displayInfo("{} v{} loaded".format(PLUGIN_NAME, PLUGIN_VERSION))


def uninitializePlugin(plugin):
    """
    Uninitialize the MCA Editor plugin.

    Deregisters the ``mcaEditor`` command and restores Maya's default
    ``ScriptEditor`` MEL procedure.

    :param MObject plugin: Maya's plugin MObject.
    """
    fn_plugin = om2.MFnPlugin(plugin)

    # Deregister the mcaEditor command.
    try:
        fn_plugin.deregisterCommand(MCAEditorCommand.COMMAND_NAME)
        logger.info("Deregistered command: %s", MCAEditorCommand.COMMAND_NAME)
    except Exception as exc:
        logger.error("Failed to deregister command %s: %s", MCAEditorCommand.COMMAND_NAME, exc)

    # Restore Maya's default ScriptEditor procedure.
    # The default implementation lives in Maya's MEL scripts and gets
    # re-sourced on next startup, so we just need a safe fallback here.
    try:
        mel.eval('''
            global proc ScriptEditor() {
                CommandWindow;
            }
        ''')
        logger.info("Restored default ScriptEditor MEL procedure")
    except Exception as exc:
        logger.warning("Could not restore ScriptEditor MEL procedure: %s", exc)

    logger.info("%s unloaded", PLUGIN_NAME)
    om2.MGlobal.displayInfo("{} unloaded".format(PLUGIN_NAME))
