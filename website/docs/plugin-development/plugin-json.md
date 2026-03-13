# Plugin Manifest (plugin.json)

Every plugin requires a `plugin.json` file in its root directory. This file tells MCA Editor about your plugin before any code is loaded.

---

## Full Example

```json
{
    "id": "com.example.my-plugin",
    "name": "My Plugin",
    "version": "1.0.0",
    "author": "Developer Name",
    "description": "What this plugin does",
    "url": "https://example.com",
    "entry_point": "__init__.py",
    "min_editor_version": "0.3.0",
    "permissions": ["execute_in_dcc", "write_disk_file"],
    "dcc": ["maya", "all"]
}
```

---

## Fields

### Required

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique plugin identifier. Use reverse domain notation (e.g., `com.yourname.plugin-name`). This is how the editor tracks enabled/disabled state. |
| `name` | string | Human-readable name displayed in menus and the plugin manager. |
| `version` | string | Semantic version string (e.g., `"1.0.0"`). |

### Optional

| Field | Type | Default | Description |
|---|---|---|---|
| `author` | string | `""` | Plugin author name. |
| `description` | string | `""` | Short description of what the plugin does. |
| `url` | string | `""` | Project URL, support page, or documentation link. |
| `entry_point` | string | `"__init__.py"` | Python file to import when loading the plugin. |
| `min_editor_version` | string | `""` | Minimum MCA Editor version required (e.g., `"0.3.0"`). |
| `permissions` | array | `[]` | List of API capabilities the plugin uses. Informational — not currently enforced. |
| `dcc` | array | `["all"]` | Which DCCs this plugin supports: `"maya"`, `"all"`. |

---

## ID Conventions

The plugin `id` must be unique across all installed plugins. Recommended format:

```
com.<author>.<plugin-name>
```

Examples:

- `com.mechart.ai-chat`
- `com.studio.rigging-tools`

!!! warning
    Changing a plugin's `id` after release will cause users to lose their enabled/disabled state and any settings tied to the old ID.

---

## Permissions

The `permissions` field is informational — it documents which API capabilities your plugin uses. Current permission names:

| Permission | Description |
|---|---|
| `execute_in_dcc` | Runs code in Maya |
| `execute_locally` | Runs code in the editor's Python |
| `write_disk_file` | Writes files to disk |
| `read_disk_file` | Reads files from disk |
| `open_file` | Opens files in the editor |
| `set_text` | Modifies editor content |

---

## DCC Field

The `dcc` field declares which host applications your plugin supports:

- `["all"]` — Works everywhere (default)
- `["maya"]` — Only loads when running inside Maya
