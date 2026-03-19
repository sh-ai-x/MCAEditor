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

## Selling a Plugin

Paid plugins use MCA's built-in license system. You don't write any license code — MCA handles the license prompt, key validation, and offline caching for you. This includes all future versions of your plugin.

### How it works

1. Users buy your plugin on Gumroad and receive a license key by email
2. They drop your plugin folder into their plugins directory
3. MCA detects the paid plugin and prompts for the key
4. MCA validates the key, caches the result locally, and loads the plugin
5. That's it — no further action from you or the user

### Revenue split

```
User pays $20 on Gumroad
    |
    +-- Gumroad fee (~10%)       --> $2.00 to Gumroad
    +-- MCA affiliate (10%)      --> $2.00 to MCA (automatic via Gumroad)
    +-- Developer keeps          --> $16.00
```

You set your own price. MCA's 10% is handled automatically through Gumroad's affiliate system — no invoices, no manual payouts.

### Steps to sell a plugin

**1. Create a Gumroad product**

Set up a product on [Gumroad](https://gumroad.com) for your plugin. Enable **license keys** so Gumroad generates and emails a key to every buyer automatically.

**2. Add MCA as an affiliate**

In your Gumroad product settings, add MCA as an affiliate at a minimum of **10%**. This is required to be listed in the MCA plugin directory.

!!! info "Why 10%?"
    MCA provides the plugin infrastructure, license enforcement, and user discovery at no upfront cost to you. The 10% affiliate cut is handled entirely by Gumroad — you never send a payment manually. For comparison, Unity takes 30% and Unreal takes 12%.

**3. Register your plugin**

Email [info@mechart.org](mailto:info@mechart.org) with:

- Your name or studio name
- Plugin ID (reverse domain, e.g. `com.yourstudio.my-tool`)
- Plugin display name
- Gumroad product permalink
- Confirmation that MCA has been added as an affiliate at 10% or more

You'll receive a signed `plugin_manifest.json` within a few business days.

**4. Ship your plugin**

Include the `plugin_manifest.json` in the root of your plugin folder alongside `plugin.json`:

```
my-tool/
    plugin.json
    plugin_manifest.json
    __init__.py
    ...
```

Distribute the folder as a zip. Users unzip, MCA handles the rest.

---

## Getting Listed

The MCA plugin directory at [mcaeditor.com/plugins](https://mcaeditor.com/plugins) is the primary way users discover plugins. Listings are reviewed to ensure quality.

To submit your plugin for listing, email [info@mechart.org](mailto:info@mechart.org) with:

- Plugin name and a short description (2-3 sentences)
- What it does and who it's for
- A screenshot or two showing it in use
- Download or purchase link
- Your name or studio name

Listings are free for both free and paid plugins.

---

## Updating Your Plugin

When you release a new version of your plugin:

1. Update the `version` field in `plugin.json`
2. Ship the updated folder with the **same** `plugin_manifest.json`
3. Users replace the old folder with the new one

You do **not** need a new manifest for code updates. The manifest only changes if your pricing model or Gumroad product changes — contact [info@mechart.org](mailto:info@mechart.org) to request a new one.

---

## Frequently Asked Questions

??? question "Do I need to update my plugin when MCA releases a new version?"
    Not for licensing. MCA's license system is entirely managed by the editor — your plugin ships with a static manifest file and never needs to change for license reasons. You only need to update if MCA's plugin API changes in a way that affects your code, which is documented in the [changelog](https://mcaeditor.com/changelog/) with a migration path.

??? question "Can I set my own price?"
    Yes. You create and control your own Gumroad product and set whatever price you like. MCA's 10% affiliate cut is automatic through Gumroad — you never deal with splitting payments manually.

??? question "Can I offer my plugin for free and charge later?"
    Yes. Contact [info@mechart.org](mailto:info@mechart.org) and we'll issue a new manifest reflecting the updated pricing model. Your plugin code does not need to change.

??? question "Can I distribute outside the MCA directory?"
    Yes. The manifest and license system work regardless of where users download your plugin. The directory listing is optional — it's just for visibility.

??? question "What happens if a user requests a refund?"
    Gumroad handles refunds. Once processed, the license key is invalidated on Gumroad's end. The next time MCA verifies it, the key is rejected and the plugin will not load.

??? question "What if I want to stop selling my plugin?"
    Remove it from Gumroad. Existing license keys continue to work — MCA caches validations locally so your users aren't left stranded. You can also contact us to remove the directory listing.

??? question "Do I need to know Qt to build a plugin?"
    No. Plugins that only add menu actions and interact with the editor via `MCAPluginAPI` don't need Qt at all. Qt is only needed if you want to build custom UI panels. See the [Qt Guide](https://mcaeditor.com/plugin-development/qt-guide/) for details.
