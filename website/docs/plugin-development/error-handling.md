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
    api.write_output("Save failed: {}".format(result["error"]), level="error")
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
            "Execution failed: {}".format(result["error"]), level="error"
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
        api.write_output("Plugin failed to load: {}".format(e), level="error")
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
