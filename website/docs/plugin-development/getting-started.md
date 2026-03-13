# Getting Started with Plugins

This guide walks you through creating your first MCA Editor plugin — a simple panel that displays a greeting and adds a menu action.

---

## Step 1: Create the Plugin Folder

Create a new folder in your user plugins directory:

```
~/Documents/mca_preferences/plugins/my_first_plugin/
```

---

## Step 2: Write the Manifest

Create `plugin.json` in your plugin folder:

```json
{
    "id": "com.yourname.my-first-plugin",
    "name": "My First Plugin",
    "version": "1.0.0",
    "author": "Your Name",
    "description": "A simple example plugin",
    "entry_point": "__init__.py"
}
```

The `id` should be unique — reverse domain notation is recommended.

---

## Step 3: Write the Plugin

Create `__init__.py`:

```python
"""
My First Plugin — a simple example MCA Editor plugin.
"""

from mca_core.plugins import MCAPlugin


class MyFirstPlugin(MCAPlugin):
    """A simple plugin that adds a panel and a menu action."""

    PLUGIN_ID = "com.yourname.my-first-plugin"
    PLUGIN_NAME = "My First Plugin"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_AUTHOR = "Your Name"
    PLUGIN_DESCRIPTION = "A simple example plugin"

    def activate(self, api):
        """
        Called when the plugin is loaded.

        :param MCAPluginAPI api: The plugin API instance.
        """
        self._api = api

        # Lazy import Qt so the module can be discovered without Qt.
        from mca_qt.qt_compat import QWidget, QLabel, QVBoxLayout

        # Build the panel widget.
        self._panel = QWidget()
        layout = QVBoxLayout(self._panel)
        layout.addWidget(QLabel("Hello from My First Plugin!"))

        # Register the panel in the right sidebar.
        self._api.add_panel(
            "my-first-panel",
            "My Plugin",
            self._panel
        )

        # Add a menu action under Plugins > My First Plugin > Greet.
        self._api.add_menu_action(
            "My First Plugin",
            "Greet",
            self._greet
        )

    def deactivate(self):
        """Called when the plugin is unloaded. Clean up resources."""
        self._api.remove_panel("my-first-panel")
        self._panel = None
        self._api = None

    def _greet(self):
        """Menu action callback — writes a greeting to the output panel."""
        self._api.write_output("Hello from My First Plugin!", level="info")
```

---

## Step 4: Load It

1. Open MCA Editor in Maya
2. Go to **Plugins** menu — your plugin should appear
3. The panel is available in the right sidebar

If you don't see it, check that the folder structure is correct:

```
~/Documents/mca_preferences/plugins/
    my_first_plugin/
        plugin.json
        __init__.py
```

---

## Step 5: Iterate

To reload your plugin after making changes:

1. Disable the plugin from the Plugins menu
2. Re-enable it

!!! tip "Development workflow"
    Keep your plugin folder open in Project Mode alongside Maya. Edit, disable/enable, and test — all within MCA Editor.

### Debugging Tips

- **Output panel is your friend** — Use `api.write_output(str(value), level="info")`
  anywhere in your plugin to inspect values without leaving MCA Editor.
- **Check the manifest first** — Most load failures are caused by malformed
  `plugin.json`. Validate it at [jsonlint.com](https://jsonlint.com) if your plugin
  doesn't appear.
- **Module-level imports fail silently** — If your plugin doesn't appear at all
  (not just fails to activate), a module-level import is likely crashing. Move all
  imports inside `activate()`.

---

## What's Next

- [Plugin Manifest](plugin-json.md) — All `plugin.json` fields
- [API Reference](api-reference.md) — Every method available to your plugin
- [Examples](examples.md) — Common patterns for panels, menus, and Maya interaction
