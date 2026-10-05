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

## Installing a Plugin

Plugins load automatically with no setup required. Drop the folder into your plugins directory and restart the editor.

A plugin may ship a `plugin_manifest.json` declaring its id, version and minimum MCA version. MCA checks that manifest for compatibility before loading. There is no licence check — every plugin loads if it is compatible.

---

## Offline Use

Once a paid plugin is activated, MCA caches the license locally for **14 days**. You can work offline without an internet connection during that period. After 14 days, MCA verifies the license once when you next go online.

If you're offline and the cache has expired, the plugin won't load until you reconnect. Your work and settings are not affected.

---

## Finding Plugins

Browse available plugins at [mcaeditor.com/plugins](https://mcaeditor.com/plugins). Each listing includes a description, screenshots, and a link to the plugin.

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

