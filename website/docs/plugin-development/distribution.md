# Sharing & Distribution

## Packaging Your Plugin

A plugin is just a folder. To share it, zip the folder:

```
my_plugin/
    plugin.json
    __init__.py
    (any additional .py files)
```

Zip it as `my_plugin.zip`. The recipient unzips it into their user plugins directory:

```
~/Documents/mca_preferences/plugins/my_plugin/
```

Then opens MCA Editor — the plugin appears automatically in the Plugins menu.

---

## What to Include

| Include | Exclude |
|---|---|
| `plugin.json` | `__pycache__/` |
| All `.py` files | `.pyc` files |
| Any assets (icons, data files) | `.git/` |
| A `README.md` (recommended) | User-specific settings |

---

## Versioning

Use semantic versioning in your `plugin.json`:

```json
{
    "version": "1.2.0"
}
```

- **Patch** (`1.0.1`) — Bug fixes, no API changes
- **Minor** (`1.1.0`) — New features, backwards compatible
- **Major** (`2.0.0`) — Breaking changes

Set `min_editor_version` to the oldest MCA Editor version your plugin supports:

```json
{
    "min_editor_version": "0.3.0"
}
```

---

## Selling Your Plugin

If you want to sell your plugin, MCA handles all licensing automatically — you don't write any license code. Set up a Gumroad product, register with MCA, and ship a signed manifest alongside your code.

See [Publishing a Plugin](publishing.md) for the full walkthrough, including revenue split, registration, and getting listed in the plugin directory.
