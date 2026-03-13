# API Reference

Complete reference for the `MCAPluginAPI` — the object your plugin receives in `activate()`.

All methods are available on the `api` object passed to your plugin's `activate(api)` method.

---

## Plugin-Specific Methods

These methods are unique to the plugin API and are not available elsewhere.

### add_panel

```python
api.add_panel(panel_id, title, widget, icon=None, location="right")
```

Register a QWidget as a panel in the editor.

| Parameter | Type | Description |
|---|---|---|
| `panel_id` | str | Unique identifier for this panel |
| `title` | str | Display title for the panel tab |
| `widget` | QWidget | The widget to display |
| `icon` | QIcon | Optional icon for the panel button (default: puzzle piece). See [Custom Panel Icons](qt-guide.md#custom-panel-icons) |
| `location` | str | Panel location: `"right"` (default) |

---

### remove_panel

```python
api.remove_panel(panel_id)
```

Remove a previously registered panel.

| Parameter | Type | Description |
|---|---|---|
| `panel_id` | str | The panel ID used in `add_panel()` |

---

### add_menu_action

```python
api.add_menu_action(menu_path, label, callback, shortcut=None)
```

Add an item to the Plugins menu.

| Parameter | Type | Description |
|---|---|---|
| `menu_path` | str | Menu path — use `"PluginName"` for a top-level item, or `"PluginName/Submenu"` for nested |
| `label` | str | Text displayed in the menu |
| `callback` | callable | Function to call when the item is clicked |
| `shortcut` | str | Optional keyboard shortcut (e.g., `"Ctrl+Shift+P"`) |

---

### show_notification

```python
api.show_notification(message, level="info", duration=5000)
```

Show a notification in the status bar and write to the output panel.

| Parameter | Type | Description |
|---|---|---|
| `message` | str | Notification text |
| `level` | str | `"info"`, `"success"`, `"warning"`, or `"error"` |
| `duration` | int | Display duration in milliseconds |

---

## File Operations

### open_file

```python
result = api.open_file(filepath)
```

Open a file in the editor.

| Parameter | Type | Description |
|---|---|---|
| `filepath` | str | Absolute path to the file |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### save_file

```python
result = api.save_file()
```

Save the currently active file.

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### save_all

```python
results = api.save_all()
```

Save all open files.

**Returns:** List of result dicts, one per file.

---

### close_tab

```python
result = api.close_tab()
```

Close the currently active tab.

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### list_open_files

```python
files = api.list_open_files()
```

Get a list of all open files.

**Returns:** List of dicts:

```python
[
    {
        "name": "script.py",
        "path": "/path/to/script.py",
        "language": "python",
        "modified": False
    },
    ...
]
```

---

### get_active_file_path

```python
path = api.get_active_file_path()
```

Get the file path of the currently active tab.

**Returns:** `str` or `None` if the tab has no associated file.

---

### read_disk_file

```python
result = api.read_disk_file(filepath)
```

Read a file from disk (does not open it in the editor).

| Parameter | Type | Description |
|---|---|---|
| `filepath` | str | Absolute path to read |

**Returns:** `{"success": bool, "result": str, "error": str}` where `result` is the file content.

---

### write_disk_file

```python
result = api.write_disk_file(filepath, content)
```

Write content to a file on disk.

| Parameter | Type | Description |
|---|---|---|
| `filepath` | str | Absolute path to write |
| `content` | str | File content |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

## Editor Content

### get_text

```python
text = api.get_text()
```

Get the full text content of the active editor.

**Returns:** `str` or `None` if no editor is active.

---

### set_text

```python
result = api.set_text(text)
```

Replace the entire content of the active editor.

| Parameter | Type | Description |
|---|---|---|
| `text` | str | New content |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### get_selected_text

```python
text = api.get_selected_text()
```

Get the currently selected text in the active editor.

**Returns:** `str` or `None` if nothing is selected.

---

### insert_text

```python
result = api.insert_text(text, line=None, col=None)
```

Insert text at the cursor position, or at a specific location.

| Parameter | Type | Description |
|---|---|---|
| `text` | str | Text to insert |
| `line` | int | Optional line number (1-based) |
| `col` | int | Optional column number (1-based) |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### replace_range

```python
result = api.replace_range(start_line, start_col, end_line, end_col, text)
```

Replace a range of text in the active editor.

| Parameter | Type | Description |
|---|---|---|
| `start_line` | int | Start line (1-based) |
| `start_col` | int | Start column (1-based) |
| `end_line` | int | End line (1-based) |
| `end_col` | int | End column (1-based) |
| `text` | str | Replacement text |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### get_cursor_position

```python
pos = api.get_cursor_position()
```

Get the current cursor position.

**Returns:** `{"line": int, "col": int}` (1-based) or `None`.

---

### get_language

```python
lang = api.get_language()
```

Get the language of the active editor tab.

**Returns:** `str` (`"python"`, `"mel"`, `"text"`, etc.) or `None`.

---

## Navigation

### navigate_to

```python
result = api.navigate_to(filepath, line=1)
```

Open a file and jump to a specific line.

| Parameter | Type | Description |
|---|---|---|
| `filepath` | str | Absolute file path |
| `line` | int | Line number (1-based, default 1) |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### go_to_line

```python
result = api.go_to_line(line)
```

Jump to a line in the active editor.

| Parameter | Type | Description |
|---|---|---|
| `line` | int | Line number (1-based) |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

## Output Panel

### write_output

```python
result = api.write_output(text, level="info")
```

Write a message to the output panel.

| Parameter | Type | Description |
|---|---|---|
| `text` | str | Message text |
| `level` | str | `"info"`, `"success"`, `"warning"`, or `"error"` |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### get_output_text

```python
text = api.get_output_text(max_lines=100)
```

Get recent text from the output panel.

| Parameter | Type | Description |
|---|---|---|
| `max_lines` | int | Maximum number of lines to return (default 100) |

**Returns:** `str`

---

### clear_output

```python
result = api.clear_output()
```

Clear the output panel.

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

## Project

### open_project

```python
result = api.open_project(path)
```

Open a project folder.

| Parameter | Type | Description |
|---|---|---|
| `path` | str | Absolute path to the project folder |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### close_project

```python
result = api.close_project()
```

Close the current project.

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

### get_project

```python
project = api.get_project()
```

Get information about the current project.

**Returns:** Dict or `None`:

```python
{
    "name": "my-project",
    "root": "/path/to/project",
    "python_paths": ["/path/to/project/lib"],
    "excluded_folders": [".git", "__pycache__"]
}
```

---

## Code Execution

### execute_in_dcc

```python
result = api.execute_in_dcc(code, language="python")
```

Execute code in the connected DCC (Maya).

| Parameter | Type | Description |
|---|---|---|
| `code` | str | Code to execute |
| `language` | str | `"python"` or `"mel"` (default `"python"`) |

**Returns:** `{"success": bool, "output": str, "error": str}`

---

### execute_locally

```python
result = api.execute_locally(code)
```

Execute Python code in the editor's own Python interpreter.

| Parameter | Type | Description |
|---|---|---|
| `code` | str | Python code to execute |

**Returns:** `{"success": bool, "output": str, "error": str}`

---

## Settings

### get_setting

```python
value = api.get_setting(key, default=None)
```

Read a setting from persistent storage.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Setting key |
| `default` | any | Value to return if the key doesn't exist |

**Returns:** The stored value, or `default`.

!!! tip "Namespace your keys"
    Use your plugin ID as a prefix to avoid collisions: `"com.yourname.plugin/setting_name"`

---

### set_setting

```python
result = api.set_setting(key, value)
```

Store a setting persistently.

| Parameter | Type | Description |
|---|---|---|
| `key` | str | Setting key |
| `value` | any | Value to store (must be QSettings-serializable) |

**Returns:** `{"success": bool, "result": ..., "error": str}`

---

## State

### get_state

```python
state = api.get_state()
```

Get a comprehensive snapshot of the editor's current state.

**Returns:**

```python
{
    "editor": {
        "file_path": "/path/to/file.py",
        "file_name": "file.py",
        "language": "python",
        "modified": False,
        "cursor": {"line": 10, "col": 4},
        "selection": "selected text"
    },
    "open_files": [
        {"name": "file.py", "path": "/path/to/file.py",
         "language": "python", "modified": False}
    ],
    "project": {
        "name": "my-project",
        "root": "/path/to/project",
        "python_paths": [],
        "excluded_folders": [".git"]
    },
    "dcc": {
        "connected": True,
        "name": "Maya 2025",
        "type": "maya"
    },
    "server": {
        "api_port": 9100,
        "version": "0.3.9"
    }
}
```
