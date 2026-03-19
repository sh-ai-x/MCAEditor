# Plugins

MCA Editor supports third-party plugins that extend the editor with new panels, tools, and workflows — all running natively inside Maya without leaving your DCC.

---

## Installing a Plugin

Plugins are installed by dropping a folder into your MCA plugins directory:

=== "Windows"

    ```
    C:\Users\<you>\Documents\mca_preferences\MCAEditor\plugins\
    ```

=== "macOS"

    ```
    ~/Documents/mca_preferences/MCAEditor/plugins/
    ```

Each plugin lives in its own subfolder:

```
plugins/
    my-tool/
        plugin.json
        __init__.py
        ...
    another-tool/
        plugin.json
        __init__.py
        ...
```

MCA scans this directory automatically every time the editor opens. The plugin appears in the **Plugins** menu with no extra setup.

---

## Free vs Paid Plugins

**Free plugins** load automatically with no setup required. Drop the folder in and you're done.

**Paid plugins** include a signed `plugin_manifest.json` in their folder. When MCA detects a paid plugin for the first time, it prompts you to enter a license key. You receive this key by email after purchasing the plugin on Gumroad.

!!! tip "Where to find your key"
    After purchasing a plugin on Gumroad, check your email for the receipt — it contains your license key. You can also find it in your [Gumroad Library](https://app.gumroad.com/library).

---

## Entering a License Key

1. Install the plugin by dropping its folder into your plugins directory
2. Open MCA Editor — the plugin license dialog appears automatically
3. Paste the license key from your Gumroad receipt
4. Click **Activate**

Once activated, the plugin loads immediately and is ready to use.

---

## Offline Use

Once a paid plugin is activated, MCA caches the license locally for **14 days**. You can work offline without an internet connection during that period. After 14 days, MCA verifies the license once when you next go online.

If you're offline and the cache has expired, the plugin won't load until you reconnect. Your work and settings are not affected.

---

## Finding Plugins

Browse available plugins at [mcaeditor.com/plugins](https://mcaeditor.com/plugins). Each listing includes a description, screenshots, and a link to purchase or download.

---

## Managing Plugins

### Enable / Disable

Toggle plugins on and off from the **Plugins** menu without restarting Maya. Disabled plugins remain installed but do not load.

### Remove

To remove a plugin, close MCA Editor and delete the plugin's folder from your plugins directory.

---

## Troubleshooting

??? question "Plugin does not appear after installation"
    Make sure the plugin folder is placed directly inside the `plugins/` directory, not nested inside another folder. The structure should be:

    ```
    plugins/my-tool/plugin.json
    ```

    Not:

    ```
    plugins/my-tool-v1.0/my-tool/plugin.json
    ```

    Also check that the folder contains a valid `plugin.json` file.

??? question "\"Plugin manifest is not valid\" error"
    The plugin's `plugin_manifest.json` may have been modified or corrupted. Re-download the plugin from the developer and replace the entire folder.

??? question "\"Plugin requires MCA Editor X.X.X\" error"
    Update MCA Editor to the version listed in the error message. Plugin developers set a minimum MCA version — older versions of the editor may not support newer plugins.

    Download the latest version from [mcaeditor.com](https://mcaeditor.com).

??? question "License key not accepted"
    - Make sure you are entering the key exactly as it appears in your Gumroad receipt email
    - Check that you purchased the correct product — each plugin has its own key
    - If the problem persists, contact the plugin developer to verify the key is still active

??? question "\"License check failed\" error"
    MCA needs to verify your license key online. Check your internet connection and try again. If you were previously working offline, the 14-day grace period may have expired.
