# First Launch

After loading the plugin, MCA Editor replaces Maya's Script Editor button. Here's what to expect on your first session.

---

## Opening the Editor

Click the **Script Editor** button in Maya's status bar. MCA Editor opens as a docked panel inside Maya — you can resize, float, or tab it like any Maya panel.

MCA Editor remembers its state between sessions. If you close it, click the Script Editor button again to reopen. If you had it open when Maya last closed, it will reopen automatically.

---

## The Interface

MCA Editor opens in **Script Mode** by default — a clean, single-tab editor focused on quick script execution. The main areas are:

- **Editor Area** — The main code editing area with syntax highlighting
- **Output Panel** — Below the editor, shows execution results and logs
- **Tool Stripe** — Right edge, quick access to terminal and plugins
- **Status Bar** — Bottom, shows cursor position, language, and connection status

---

## Running Your First Script

1. Type some Python code in the editor:

    ```python
    import maya.cmds as cmds
    print(cmds.ls(selection=True))
    ```

2. Press ++ctrl+enter++ to execute the code
3. The result appears in the Output Panel below

!!! tip "Execution shortcuts"
    - ++ctrl+enter++ — Execute all code in the current tab
    - ++ctrl+shift+enter++ — Execute only the selected text

---

## Connecting to Maya

MCA Editor communicates with Maya through command ports. The connection is established automatically when the plugin loads. You can see the connection status in the bottom-right of the status bar.

If the connection drops, go to **File > Connect to Maya** to reconnect.

---

## Trial Period

MCA Editor includes a **14-day free trial**. After the trial, you'll need a license key to continue using the editor. You can enter your key in **Help > Licensing**.

---

## Next Steps

- Learn about [Script Mode](../editor-guide/script-mode.md) for quick scripting
- Set up [Project Mode](../editor-guide/project-mode.md) for larger projects
- Explore [Keyboard Shortcuts](../editor-guide/keyboard-shortcuts.md) to speed up your workflow
