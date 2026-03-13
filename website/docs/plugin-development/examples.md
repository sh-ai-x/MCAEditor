# Plugin Examples

Common patterns and recipes for MCA Editor plugins.

---

## Scene Info Panel

A plugin that shows information about the current Maya scene in a right-side panel.

```python
"""
Scene Info Plugin — displays live scene statistics.
"""

from mca_core.plugins import MCAPlugin


class SceneInfoPlugin(MCAPlugin):
    """Displays Maya scene statistics in a panel."""

    PLUGIN_ID = "com.example.scene-info"
    PLUGIN_NAME = "Scene Info"
    PLUGIN_VERSION = "1.0.0"

    def activate(self, api):
        """Set up the panel and refresh timer."""
        self._api = api

        from mca_qt.qt_compat import (
            QWidget, QLabel, QVBoxLayout, QPushButton, QTimer
        )

        # Build the panel UI.
        self._panel = QWidget()
        layout = QVBoxLayout(self._panel)

        self._info_label = QLabel("Click Refresh to load scene info.")
        layout.addWidget(self._info_label)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        layout.addWidget(refresh_btn)

        layout.addStretch()

        # Register in the sidebar.
        self._api.add_panel("scene-info", "Scene Info", self._panel)

    def deactivate(self):
        """Clean up."""
        self._api.remove_panel("scene-info")
        self._panel = None
        self._api = None

    def _refresh(self):
        """Query Maya for scene stats and update the label."""
        code = """
import maya.cmds as cmds
meshes = cmds.ls(type='mesh')
joints = cmds.ls(type='joint')
cameras = cmds.ls(type='camera')
print('Meshes: {}'.format(len(meshes)))
print('Joints: {}'.format(len(joints)))
print('Cameras: {}'.format(len(cameras)))
"""
        result = self._api.execute_in_dcc(code)
        if result["success"]:
            self._info_label.setText(result["output"])
        else:
            self._info_label.setText("Error: " + result.get("error", ""))
```

---

## Quick Action Menu Item

A plugin that adds a menu action to batch-rename selected objects.

```python
"""
Batch Rename Plugin — adds a menu action for renaming selected objects.
"""

from mca_core.plugins import MCAPlugin


class BatchRenamePlugin(MCAPlugin):
    """Adds a Plugins > Batch Rename menu action."""

    PLUGIN_ID = "com.example.batch-rename"
    PLUGIN_NAME = "Batch Rename"
    PLUGIN_VERSION = "1.0.0"

    def activate(self, api):
        """Register the menu action."""
        self._api = api
        self._api.add_menu_action(
            "Batch Rename",
            "Rename Selected...",
            self._rename_selected
        )

    def deactivate(self):
        """Clean up."""
        self._api = None

    def _rename_selected(self):
        """Rename all selected objects with a numbered prefix."""
        code = """
import maya.cmds as cmds
sel = cmds.ls(selection=True)
if not sel:
    print('Nothing selected.')
else:
    for i, obj in enumerate(sel):
        new_name = 'item_{:03d}'.format(i)
        cmds.rename(obj, new_name)
        print('Renamed {} -> {}'.format(obj, new_name))
"""
        result = self._api.execute_in_dcc(code)
        if result["success"]:
            self._api.write_output(result["output"], level="success")
        else:
            self._api.write_output(result.get("error", ""), level="error")
```

---

## Working with Editor Content

Read the user's code, transform it, and write it back.

```python
def _format_selection(self):
    """Example: wrap selected code in a try/except block."""
    selected = self._api.get_selected_text()
    if not selected:
        self._api.show_notification("No text selected.", level="warning")
        return

    # Indent the selection and wrap it.
    indented = "\n".join("    " + line for line in selected.splitlines())
    wrapped = "try:\n{}\nexcept Exception as e:\n    print(e)".format(indented)

    # Get cursor position to know where to replace.
    # For simplicity, replace the full editor content.
    full_text = self._api.get_text()
    new_text = full_text.replace(selected, wrapped, 1)
    self._api.set_text(new_text)
```

---

## Persisting Plugin Settings

Store and retrieve settings that survive between Maya sessions.

```python
def activate(self, api):
    """Load saved preferences on activation."""
    self._api = api

    # Read a setting with a default value.
    self._prefix = self._api.get_setting(
        "com.example.batch-rename/prefix",
        default="item"
    )

def _save_preferences(self):
    """Save the current prefix setting."""
    self._api.set_setting(
        "com.example.batch-rename/prefix",
        self._prefix
    )
```

---

## Executing Maya Code and Displaying Results

A complete pattern for running Maya commands and showing output in your panel:

```python
def _query_scene(self):
    """Run a Maya query and display the result in the panel label."""
    # Guard: check Maya is connected
    state = self._api.get_state()
    if not state["dcc"]["connected"]:
        self._result_label.setText("Maya not connected.")
        return

    result = self._api.execute_in_dcc("""
import maya.cmds as cmds
sel = cmds.ls(selection=True, long=True)
print("\\n".join(sel) if sel else "Nothing selected.")
""")
    if result["success"]:
        self._result_label.setText(result["output"].strip())
    else:
        self._result_label.setText("Error: {}".format(result["error"]))
```

---

## Loading Third-Party Packages

If your plugin needs a package not included with Maya, install it into the MCA
venv and import it in your plugin:

```python
def activate(self, api):
    self._api = api

    try:
        import requests  # Must be installed in MCA's venv
    except ImportError:
        api.write_output(
            "This plugin requires 'requests'. "
            "Install it via the MCA terminal: pip install requests",
            level="error"
        )
        return

    # Continue setup...
```

---

## Tips

- **Lazy-import Qt** — Import PySide inside `activate()`, not at module level. This lets the Plugin Manager discover your plugin without Qt being available.
- **Clean up in `deactivate()`** — Remove all panels, disconnect signals, stop timers. Anything you created, you should destroy.
- **Namespace your settings** — Use your plugin ID as a prefix for setting keys to avoid collisions.
- **Handle disconnection** — `execute_in_dcc()` can fail if Maya isn't connected. Always check the `success` field.
