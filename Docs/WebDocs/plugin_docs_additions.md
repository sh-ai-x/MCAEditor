# Plugin Docs — Missing Content Draft
# Hand this to Claude Code to add to the appropriate pages on mcaeditor.com

---

## 1. NEW PAGE: `plugin-development/qt-guide.md`
### Title: "Using Qt in Plugins"
### Add to sidebar under Plugin Development, between "Getting Started" and "Plugin Manifest"

```markdown
# Using Qt in Plugins

MCA Editor runs on PySide6 (Qt6) inside Maya 2025+. Plugins can build full Qt UIs
using the `mca_qt.qt_compat` compatibility layer, which abstracts away version
differences.

---

## Importing Qt

Always import Qt inside `activate()`, not at module level. The plugin discovery
system imports your module before Qt is guaranteed to be available.

```python
def activate(self, api):
    self._api = api

    # Safe — Qt is available by the time activate() is called.
    from mca_qt.qt_compat import (
        QWidget, QLabel, QVBoxLayout, QHBoxLayout,
        QPushButton, QLineEdit, QTextEdit, QCheckBox,
        QComboBox, QSpinBox, QTimer, QIcon
    )
```

---

## Available Classes

These classes are safe to import from `mca_qt.qt_compat`:

| Class | Notes |
|---|---|
| `QWidget` | Base class for all panels |
| `QLabel` | Static text |
| `QVBoxLayout`, `QHBoxLayout`, `QGridLayout` | Layout managers |
| `QPushButton` | Clickable button |
| `QLineEdit` | Single-line text input |
| `QTextEdit` | Multi-line text area |
| `QCheckBox` | Boolean toggle |
| `QComboBox` | Dropdown selector |
| `QSpinBox`, `QDoubleSpinBox` | Numeric inputs |
| `QTimer` | Periodic callbacks |
| `QIcon` | Icons for panels and actions |
| `QSizePolicy` | Widget sizing hints |
| `Qt` | Namespace for flags (e.g., `Qt.AlignTop`) |

For anything not in this list, import directly from `PySide6.QtWidgets` or
`PySide6.QtCore` — MCA Editor targets Maya 2025+ which ships PySide6.

---

## Building a Panel

Panels are registered with `api.add_panel()` and displayed in the right sidebar.
They must be `QWidget` instances.

```python
from mca_qt.qt_compat import QWidget, QVBoxLayout, QLabel, QPushButton

panel = QWidget()
layout = QVBoxLayout(panel)
layout.setContentsMargins(8, 8, 8, 8)
layout.setSpacing(6)

layout.addWidget(QLabel("My Plugin"))
layout.addWidget(QPushButton("Run"))
layout.addStretch()  # Push widgets to the top

api.add_panel("my-plugin", "My Plugin", panel)
```

---

## Timer-Based Updates

Use `QTimer` for periodic refreshes. Always stop timers in `deactivate()`.

```python
from mca_qt.qt_compat import QTimer

def activate(self, api):
    self._api = api
    # ... build UI ...

    self._timer = QTimer()
    self._timer.timeout.connect(self._refresh)
    self._timer.start(5000)  # Refresh every 5 seconds

def deactivate(self):
    self._timer.stop()
    self._timer = None
    self._api.remove_panel("my-plugin")
    self._api = None
```

---

## Maya Version Notes

| Maya Version | Qt Version | Import |
|---|---|---|
| Maya 2024 | Qt5 / PySide2 | Not supported by plugin API |
| Maya 2025 | Qt6 / PySide6 | ✓ Fully supported |
| Maya 2026 | Qt6 / PySide6 | ✓ Fully supported |

MCA Editor's plugin system requires **Maya 2025 or later**. PySide2 is not supported.
```

---

## 2. NEW PAGE: `plugin-development/error-handling.md`
### Title: "Error Handling"
### Add to sidebar under Plugin Development, after "Examples"

```markdown
# Error Handling

All API methods that interact with the editor or Maya return a result dict with a
`success` field. Always check it — Maya may not be connected, files may not exist,
and the editor state can change between calls.

---

## The Result Pattern

Most API methods return:

```python
{
    "success": bool,
    "result": ...,   # Return value on success, None on failure
    "error": str     # Error message on failure, "" on success
}
```

The safe pattern:

```python
result = api.save_file()
if result["success"]:
    api.write_output("Saved.", level="success")
else:
    api.write_output(f"Save failed: {result['error']}", level="error")
```

---

## Handling Maya Disconnection

`execute_in_dcc()` fails silently if Maya isn't connected. Always guard against it:

```python
def _run_in_maya(self, code):
    state = self._api.get_state()
    if not state["dcc"]["connected"]:
        self._api.show_notification(
            "Maya is not connected.", level="warning"
        )
        return None

    result = self._api.execute_in_dcc(code)
    if not result["success"]:
        self._api.write_output(
            f"Execution failed: {result['error']}", level="error"
        )
        return None

    return result["output"]
```

---

## Guarding Against Missing Editor State

`get_text()`, `get_active_file_path()`, and `get_cursor_position()` return `None`
when no editor tab is active. Always check:

```python
text = self._api.get_text()
if text is None:
    self._api.show_notification("No file open.", level="warning")
    return

# Safe to use text here
```

---

## Wrapping activate() Safely

If your `activate()` raises an exception, the plugin will fail to load. Wrap
anything that can fail:

```python
def activate(self, api):
    self._api = api
    try:
        self._setup_ui()
        self._load_settings()
    except Exception as e:
        api.write_output(f"Plugin failed to load: {e}", level="error")
        raise  # Re-raise so the Plugin Manager knows activation failed
```

---

## Common Pitfalls

| Problem | Cause | Fix |
|---|---|---|
| `execute_in_dcc()` always fails | Maya disconnected | Check `get_state()["dcc"]["connected"]` first |
| `get_text()` returns `None` | No active tab | Guard with `if text is None` |
| Panel appears empty | Qt imported at module level | Move imports inside `activate()` |
| Settings lost between sessions | Wrong key format | Namespace keys with your plugin ID |
| Plugin crashes on reload | Timer not stopped | Always stop timers in `deactivate()` |
```

---

## 3. NEW PAGE: `plugin-development/distribution.md`
### Title: "Sharing & Distribution"
### Add to sidebar under Plugin Development, after "Error Handling"

```markdown
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

## Plugin Marketplace

A plugin marketplace for MCA Editor is planned. When available, you'll be able to
submit plugins for discovery by other MCA Editor users. Details will be published
here when the marketplace launches.
```

---

## 4. ADDITIONS to existing `plugin-development/examples.md`

Add this section before the "Tips" section at the bottom:

```markdown
## Executing Maya Code and Displaying Results

A complete pattern for running Maya commands and showing output in your panel:

```python
def _query_scene(self):
    """Run a Maya query and display the result in the panel label."""
    # Guard: check Maya is connected
    state = self._api.get_state()
    if not state["dcc"]["connected"]:
        self._result_label.setText("Maya not connected.")
        return

    result = self._api.execute_in_dcc("""
import maya.cmds as cmds
sel = cmds.ls(selection=True, long=True)
print("\\n".join(sel) if sel else "Nothing selected.")
""")
    if result["success"]:
        self._result_label.setText(result["output"].strip())
    else:
        self._result_label.setText(f"Error: {result['error']}")
```

---

## Loading Third-Party Packages

If your plugin needs a package not included with Maya, install it into the MCA
venv and import it in your plugin:

```python
def activate(self, api):
    self._api = api

    try:
        import requests  # Must be installed in MCA's venv
    except ImportError:
        api.write_output(
            "This plugin requires 'requests'. "
            "Install it via the MCA terminal: pip install requests",
            level="error"
        )
        return

    # Continue setup...
```
```

---

## 5. ADDITION to existing "Getting Started" page

Add this note in Step 5 (Iterate), after the development workflow tip:

```markdown
### Debugging Tips

- **Output panel is your friend** — Use `api.write_output(str(value), level="info")`
  anywhere in your plugin to inspect values without leaving MCA Editor.
- **Check the manifest first** — Most load failures are caused by malformed
  `plugin.json`. Validate it at [jsonlint.com](https://jsonlint.com) if your plugin
  doesn't appear.
- **Module-level imports fail silently** — If your plugin doesn't appear at all
  (not just fails to activate), a module-level import is likely crashing. Move all
  imports inside `activate()`.
```

---

## Summary of Changes for Claude Code

| Action | File | What to Add |
|---|---|---|
| CREATE | `docs/plugin-development/qt-guide.md` | Full Qt usage guide |
| CREATE | `docs/plugin-development/error-handling.md` | Error handling patterns |
| CREATE | `docs/plugin-development/distribution.md` | Packaging & sharing guide |
| EDIT | `docs/plugin-development/examples.md` | Maya query pattern + third-party packages section |
| EDIT | `docs/plugin-development/getting-started.md` | Debugging tips in Step 5 |
| EDIT | `mkdocs.yml` | Add new pages to nav under Plugin Development |
