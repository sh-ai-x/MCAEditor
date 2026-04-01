"""
MCA Editor — Blender Addon.

Registers MCA Editor as a Blender addon, providing a professional
PySide6-based code editor for Blender Python scripting. The editor
runs as a floating Qt window above Blender using Win32 owner-window
z-ordering (same approach as the Unreal Engine integration).

The Qt event loop is pumped via ``bpy.app.timers.register()`` at ~120Hz,
which runs on Blender's main thread without blocking input processing.

Blender Addon Structure:
    - bl_info dict provides addon metadata for Blender's preferences
    - register() installs operators and menu items
    - unregister() cleans up everything on addon disable

Dependencies:
    - bpy (Blender Python API)
    - PySide6 (installed via managed venv on first launch)
"""

# --- Blender addon metadata (read by Blender at scan time) -------------------

bl_info = {
    "name": "MCA Editor",
    "author": "MCA Tools",
    "version": (1, 0, 7),
    "blender": (4, 0, 0),
    "location": "Window > MCA Editor",
    "description": "Professional code editor for Blender Python scripting",
    "category": "Development",
    "support": "COMMUNITY",
}


import bpy
import logging

# Module-level logger for addon lifecycle.
logger = logging.getLogger("mca_editor.blender")


# --- Operator: Launch MCA Editor --------------------------------------------

class MCA_OT_launch_editor(bpy.types.Operator):
    """
    Launch the MCA Editor window.

    Creates a new Qt window (or raises an existing one) containing the
    full MCA Editor panel with code editing, output, terminal, and
    Blender code execution support.
    """
    bl_idname = "mca.launch_editor"
    bl_label = "MCA Editor"
    bl_description = "Open the MCA Editor code editor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """
        Launch or raise the editor window.

        :param bpy.types.Context context: Blender context.
        :return: {'FINISHED'} on success, {'CANCELLED'} on failure.
        :rtype: set
        """
        try:
            from . import blender_window
            success = blender_window.launch_editor()
            if success:
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "Failed to launch MCA Editor")
                return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, "MCA Editor launch error: {}".format(exc))
            logger.error("Launch error: %s", exc, exc_info=True)
            return {'CANCELLED'}


# --- Operator: Close MCA Editor ---------------------------------------------

class MCA_OT_close_editor(bpy.types.Operator):
    """
    Close the MCA Editor window.

    Saves editor state and cleanly shuts down the Qt window.
    """
    bl_idname = "mca.close_editor"
    bl_label = "Close MCA Editor"
    bl_description = "Close the MCA Editor window"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """
        Close the editor window.

        :param bpy.types.Context context: Blender context.
        :return: {'FINISHED'}.
        :rtype: set
        """
        try:
            from . import blender_window
            blender_window.close_editor()
        except Exception as exc:
            logger.warning("Close error: %s", exc)
        return {'FINISHED'}


# --- Menu Integration -------------------------------------------------------

def _draw_menu_item(self, context):
    """
    Draw the MCA Editor item in the Window menu.

    :param bpy.types.Menu self: The menu being drawn.
    :param bpy.types.Context context: Blender context.
    """
    self.layout.separator()
    self.layout.operator(MCA_OT_launch_editor.bl_idname, icon='TEXT')


# --- Auto-Launch on Startup -------------------------------------------------

def _auto_launch_timer():
    """
    Timer callback for auto-launching the editor on Blender startup.

    Checks if the editor was open in the previous session (via QSettings)
    and relaunches it automatically. Runs once and does not repeat.

    :return: None (do not repeat).
    :rtype: None
    """
    try:
        from . import blender_window
        blender_window.auto_launch()
    except Exception as exc:
        logger.warning("Auto-launch failed: %s", exc)
    # Return None to unregister this timer (run only once).
    return None


# --- Registration -----------------------------------------------------------

# Classes to register with Blender's class system.
_CLASSES = (
    MCA_OT_launch_editor,
    MCA_OT_close_editor,
)


def register():
    """
    Register the MCA Editor addon with Blender.

    Called when the user enables the addon in Preferences. Registers
    operators, adds the Window menu item, and schedules auto-launch.
    """
    # Register operator classes.
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    logger.info("MCA Editor operators registered")

    # Add menu item to Window menu.
    bpy.types.TOPBAR_MT_window.append(_draw_menu_item)
    logger.info("MCA Editor menu item added to Window menu")

    # Schedule auto-launch after a short delay to let Blender finish
    # its own startup. 1.0 second gives enough time for the UI to
    # stabilize and workspace to restore.
    bpy.app.timers.register(_auto_launch_timer, first_interval=1.0)
    logger.info("MCA Editor addon registered (v{})".format(
        ".".join(str(v) for v in bl_info["version"])
    ))


def unregister():
    """
    Unregister the MCA Editor addon from Blender.

    Called when the user disables the addon in Preferences or when
    Blender shuts down. Closes the editor window and removes all
    registered operators and menu items.
    """
    # Close the editor window if it's open.
    try:
        from . import blender_window
        blender_window.close_editor(shutting_down=True)
    except Exception as exc:
        logger.warning("Error closing editor during unregister: %s", exc)

    # Remove menu item from Window menu.
    bpy.types.TOPBAR_MT_window.remove(_draw_menu_item)

    # Unregister operator classes (reverse order).
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

    logger.info("MCA Editor addon unregistered")
