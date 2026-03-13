# Plugin System Overview

MCA Editor has a plugin architecture that lets you extend the editor with custom functionality. Plugins can add panels, menu items, and interact with the editor and Maya through a clean Python API.

---

## How Plugins Work

A plugin is a Python package (folder) containing:

- `plugin.json` — Metadata and configuration
- `__init__.py` — Entry point with your plugin class

Your plugin class subclasses `MCAPlugin` and implements two methods: `activate()` and `deactivate()`. When activated, you receive an API object that gives you access to the editor's functionality.

---

## What Plugins Can Do

Through the `MCAPluginAPI`, plugins can:

- **Add UI panels** to the editor's right sidebar
- **Add menu items** under the Plugins menu
- **Read and write files** on disk and in the editor
- **Execute code** in Maya or locally
- **Access editor state** — cursor position, open files, project info
- **Show notifications** in the status bar
- **Store settings** that persist across sessions

---

## Plugin Locations

| Location | Purpose |
|---|---|
| `mca_core/plugins/` | Bundled plugins (ship with MCA Editor) |
| `~/Documents/mca_preferences/plugins/` | User plugins (your custom plugins) |

Bundled plugins load first, then user plugins. Both follow the same structure.

---

## Plugin Lifecycle

```
Discovery → Load Manifest → Import Module → activate(api) → ... → deactivate()
```

1. **Discovery** — Plugin Manager scans plugin directories for `plugin.json` files
2. **Manifest** — Reads metadata (ID, name, version, etc.)
3. **Import** — Dynamically imports the entry point module
4. **Activate** — Calls `plugin.activate(api)` with the API wrapper
5. **Deactivate** — Calls `plugin.deactivate()` on shutdown or when disabled

Plugins can be enabled/disabled from the **Plugins** menu without restarting.

---

## Next Steps

- [Getting Started](getting-started.md) — Build your first plugin
- [Plugin Manifest](plugin-json.md) — `plugin.json` reference
- [API Reference](api-reference.md) — Complete method listing
- [Examples](examples.md) — Patterns and recipes
