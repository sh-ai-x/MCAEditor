# Publishing a Plugin

MCA Editor has a public plugin API that lets you build and distribute tools that run natively inside the editor. Plugins can add sidebar panels, menu items, and interact with the editor and Maya through a clean Python API.

This page covers how to package a plugin, list it in the MCA plugin directory, and optionally sell it.

---

## Plugin Structure

A plugin is a folder containing a `plugin.json` manifest and a Python entry point:

```
my-tool/
    plugin.json
    __init__.py
```

The entry point subclasses `MCAPlugin` and implements `activate()` and `deactivate()`:

```python
"""
My Tool — an example MCA Editor plugin.
"""

from mca_core.plugins import MCAPlugin


class MyTool(MCAPlugin):
    """Example plugin that adds a menu action."""

    PLUGIN_ID = "com.yourname.my-tool"
    PLUGIN_NAME = "My Tool"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_AUTHOR = "Your Name"
    PLUGIN_DESCRIPTION = "Does something useful"

    def activate(self, api):
        """
        Called when the plugin is loaded.

        :param MCAPluginAPI api: The plugin API instance.
        """
        self._api = api
        api.add_menu_action("My Tool", "Run", self._run)

    def deactivate(self):
        """Called when the plugin is unloaded."""
        self._api = None

    def _run(self):
        """Menu action callback."""
        self._api.write_output("My Tool is running.", level="info")
```

For the complete API, see the [Plugin Development](https://mcaeditor.com/plugin-development/overview/) docs.

---

## Distributing for Free

Free plugins need no registration. Package your plugin folder as a zip and distribute it however you like — your own site, GitHub, forums, anywhere.

Users install it by unzipping into their plugins directory:

```
~/Documents/mca_preferences/MCAEditor/plugins/my-tool/
```

If you'd like your plugin listed on the MCA plugin directory for visibility, see [Getting Listed](#getting-listed) below.

---

## Sharing a Plugin

Plugins are free. There is no licence system, no key and no revenue split — MCA loads
any compatible plugin it finds.

Publish yours wherever you like. A public Git repository is the simplest option: users
clone or download the folder and drop it into their plugins directory. Include a README
saying what it does, which MCA version it needs, and how to install it.
MCA Editor itself is on [GitHub](https://github.com/ncomes/MCAEditor) under the MIT licence if you want a template to
follow.
## Getting Listed

The MCA plugin directory at [mcaeditor.com/plugins](https://mcaeditor.com/plugins) is the primary way users discover plugins. Listings are reviewed to ensure quality.

To submit your plugin for listing, email [info@mechart.org](mailto:info@mechart.org) with:

- Plugin name and a short description (2-3 sentences)
- What it does and who it's for
- A screenshot or two showing it in use
- A link to your plugin (a GitHub repository is ideal)
- Your name or studio name

Listings are free.

---

## Updating Your Plugin

When you release a new version of your plugin:

1. Update the `version` field in `plugin.json`
2. Ship the updated folder with the **same** `plugin_manifest.json`
3. Users replace the old folder with the new one

You do **not** need a new manifest for code updates. The manifest only carries your plugin's
identity, version and minimum MCA version.

---

## Frequently Asked Questions

??? question "Do I need to update my plugin when MCA releases a new version?"
    Only if MCA's plugin API changes in a way that affects your code, which is documented in the [changelog](https://mcaeditor.com/changelog/) with a migration path.

??? question "Can I distribute outside the MCA directory?"
    Yes. The directory listing is optional — it is just for visibility. Users can install your plugin from anywhere.

??? question "Do I need to know Qt to build a plugin?"
    No. Plugins that only add menu actions and interact with the editor via `MCAPluginAPI` don't need Qt at all. Qt is only needed if you want to build custom UI panels. See the [Qt Guide](https://mcaeditor.com/plugin-development/qt-guide/) for details.
