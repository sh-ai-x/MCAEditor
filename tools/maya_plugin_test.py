"""
MCA Editor — Maya Plugin Smoke Test.

Executed inside Maya via ``-command`` flag.  Tests that the plugin
loads, the editor window opens, and the Qt event loop survives
layout, paint, and geometry change cycles (where Shiboken segfaults
can occur in Cython-compiled code).

Writes progress to ``%TEMP%/mca_test_result.log``.  If Maya segfaults,
the log stops at whatever step it last reached — the LAST line in the
log tells you exactly where the crash happened.

Usage (called by ``run_maya_test.py``, not directly):
    maya.exe -command "python(\"exec(open(r'path/to/maya_plugin_test.py').read())\")"

Dependencies: None (runs inside Maya's Python)
Side effects: Writes log file, quits Maya on completion
"""

import os
import traceback

# --- Log file path ---
_LOG = os.path.join(os.environ.get("TEMP", "C:/Temp"), "mca_test_result.log")


def _log(msg):
    """
    Append a line to the test log with immediate flush.

    :param str msg: Message to write.
    """
    with open(_LOG, "a") as f:
        f.write(msg + "\n")
        f.flush()


def _run_test():
    """
    Main test sequence — runs after Maya's UI is fully initialized.

    Steps:
        1. Load the mcaEditor plugin
        2. Open the editor window via show_mca_editor()
        3. Resize the window to trigger geometry change events
           (catches Shiboken enum crashes in app-level event filters)
        4. Wait 5 seconds for Qt event loop to process all events
        5. If still alive, write PASS and quit
    """
    import maya.cmds as cmds

    try:
        # Step 1: Load the plugin.
        _log("PLUGIN_LOADING")
        if not cmds.pluginInfo("mca_editor_plugin", q=True, loaded=True):
            cmds.loadPlugin("mca_editor_plugin")
        _log("PLUGIN_LOADED")

        # Step 2: Open the editor window.
        _log("WINDOW_OPENING")
        from mca_maya.maya_window import show_mca_editor
        show_mca_editor()
        _log("WINDOW_OPENED")

        try:
            from PySide6.QtCore import QTimer, QCoreApplication
        except ImportError:
            from PySide2.QtCore import QTimer, QCoreApplication

        # Step 3: After a brief delay (let the window paint once), resize
        # the workspace control to trigger geometry change events.  This
        # exercises the application-level event filter path where Shiboken
        # enum dispatch can crash in Cython-compiled eventFilter methods.
        def _trigger_geometry_events():
            """Resize the workspace control to force geometry change events."""
            _log("GEOMETRY_TEST_START")
            try:
                ws_ctrl = "MCAEditorWorkspaceControl"
                if cmds.workspaceControl(ws_ctrl, exists=True):
                    # Resize to trigger processGeometryChangeEvent through
                    # the app-level event filter (MayaHotkeyFilter).
                    cmds.workspaceControl(ws_ctrl, edit=True, widthProperty="free")
                    cmds.workspaceControl(ws_ctrl, edit=True, resizeWidth=800)
                    cmds.workspaceControl(ws_ctrl, edit=True, resizeHeight=600)

                    # Process pending events so Qt dispatches the geometry
                    # changes through the event filter immediately.
                    QCoreApplication.processEvents()

                    cmds.workspaceControl(ws_ctrl, edit=True, resizeWidth=1000)
                    cmds.workspaceControl(ws_ctrl, edit=True, resizeHeight=700)
                    QCoreApplication.processEvents()

                _log("GEOMETRY_TEST_PASSED")
            except Exception:
                _log("GEOMETRY_TEST_EXCEPTION")
                _log(traceback.format_exc())

        # Fire geometry test 500ms after window open (let initial paint finish).
        QTimer.singleShot(500, _trigger_geometry_events)

        # Step 4: Wait 5 seconds total for the Qt event loop to process
        # all layout, paint, and geometry events.  If Maya survives, the
        # compiled code is stable.
        def _delayed_pass():
            """Called 5s after window open — event loop survived."""
            _log("EVENT_LOOP_SURVIVED")
            _log("PASS")
            cmds.quit(force=True)

        QTimer.singleShot(5000, _delayed_pass)

    except Exception:
        _log("EXCEPTION")
        _log(traceback.format_exc())
        try:
            cmds.quit(force=True)
        except Exception:
            pass


# --- Entry point (runs when Maya sources this file) ---

# Clear previous log so we start fresh.
with open(_LOG, "w") as _f:
    _f.write("")

_log("STARTED")

# Schedule the test AFTER Maya finishes startup.  Using
# maya.utils.executeDeferred ensures the UI is fully initialized
# before we try to load plugins and create windows.
import maya.utils
maya.utils.executeDeferred(_run_test)
