# Publishing a Plugin

MCA Editor has a public plugin API that lets you build and distribute tools that run natively inside the editor. Plugins can add sidebar panels, menu items, toolbar actions, and more — all using the same `EditorAPI` that MCA itself uses internally.

This page covers how to build a plugin, list it in the MCA plugin directory, and optionally sell it.

---

## Building a Plugin

A plugin is a folder containing a Python entry point that subclasses `MCAPlugin`.

### Minimal structure

```
my-tool/
    plugin.py
```

### Minimal plugin.py

```python
from mca_editor.plugins import MCAPlugin


class MyTool(MCAPlugin):

    name = "My Tool"
    version = "1.0.0"
    author = "Your Name"

    def activate(self, api):
        # api is an MCAPluginAPI instance — use it to extend the editor
        api.add_menu_action("Plugins", "Run My Tool", self._run)

    def deactivate(self):
        # Clean up anything your plugin registered
        pass

    def _run(self):
        print("My Tool is running.")
```

Drop this folder into `~/Documents/mca_preferences/plugins/` and MCA will load it automatically.

### Available API methods

| Method | Description |
|--------|-------------|
| `api.add_sidebar_panel(title, widget)` | Add a Qt widget as a sidebar panel |
| `api.add_menu_action(menu, label, callback)` | Add an item to a menu |
| `api.add_toolbar_action(label, callback, tooltip)` | Add a toolbar button |
| `api.execute_in_dcc(code)` | Run Python in the connected DCC (e.g. Maya) |
| `api.get_editor_text()` | Read the active editor's content |
| `api.set_editor_text(text)` | Replace the active editor's content |
| `api.open_file(filepath)` | Open a file in the editor |
| `api.show_notification(message, level)` | Show a status bar message |

Full API reference: [mcaeditor.com/docs/api](https://mcaeditor.com/docs/api)

---

## Distributing a Plugin

### Free plugins

Free plugins need no registration. Package your plugin folder as a zip and distribute it however you like — your own site, GitHub, itch.io, anywhere. Users install it by unzipping into their plugins directory.

If you'd like your plugin listed on the MCA plugin directory, [submit it for review](#getting-listed).

### Paid plugins

Paid plugins use MCA's built-in license system. When a user installs a paid plugin, MCA handles the license prompt, key validation, and offline caching automatically. You don't write any license code — MCA does it for you, including for all future versions of your plugin.

To sell a plugin:

1. **Create a Gumroad product** for your plugin. Gumroad will generate and email a license key to every buyer automatically.
2. **Register your plugin with MCA** (see below). You'll receive a signed `plugin_manifest.json` to include in your plugin folder.
3. **Set MCA as a Gumroad affiliate** at a minimum of 10%. This is required to be listed in the MCA plugin directory.
4. **Ship your plugin** as a zip containing your code and the `plugin_manifest.json`.

Users buy on Gumroad, receive a key by email, enter it when MCA prompts them, and the plugin loads. No further action needed from you.

---

## Registering Your Plugin

To get a signed manifest (required for paid plugins, optional for free plugins you want listed):

Email [info@mechart.org](mailto:info@mechart.org) with the following:

- Your name or studio name
- Plugin name and a short description
- Gumroad product permalink (paid plugins only)
- Confirmation that MCA has been added as an affiliate at 5% or more (paid plugins only)

You'll receive a `plugin_manifest.json` within a few business days. Include this file in the root of your plugin folder when you distribute it.

---

## Getting Listed

The MCA plugin directory at [mcaeditor.com/plugins](https://mcaeditor.com/plugins) is the main way users discover plugins. Listings are manually reviewed to ensure a baseline of quality.

To submit your plugin for listing, email [info@mechart.org](mailto:info@mechart.org) with:

- Plugin name, description (2–3 sentences), and what it does
- A screenshot or two showing it in use
- Download or purchase link
- Your name or studio name

Listings are free for both free and paid plugins.

---

## Frequently Asked Questions

**Do I need to update my plugin when MCA releases a new version?**

Not for licensing. MCA's license system is entirely managed by the editor — your plugin ships with a static manifest file and never needs to change for license reasons. You only need to update your plugin if MCA's API changes in a way that affects your code, which will be documented in the release notes with a migration path.

**Can I set my own price?**

Yes. You create and control your own Gumroad product and set whatever price you like. MCA takes a 10% affiliate cut automatically through Gumroad's affiliate system — you never deal with splitting payments manually.

**Can I offer my plugin for free and add paid features later?**

Yes. Contact [info@mechart.org](mailto:info@mechart.org) and we'll issue a new manifest reflecting the updated pricing model. Your plugin code does not need to change.

**Can I distribute my plugin outside of the MCA directory?**

Yes. The manifest and license system work regardless of where users download your plugin from. The directory listing is optional — it's just for visibility.

**What happens if a user requests a refund?**

Gumroad handles refunds. Once a refund is processed, the license key is invalidated on Gumroad's end. The next time MCA attempts to validate it, the key will be rejected and the plugin will not load.
