# Installation

Download the latest version from the [Downloads page](../download.md), then follow the instructions for your DCC application.

---

## Maya

MCA Editor for Maya is distributed as a single Python file that you drop into Maya's plug-ins folder. No installer, no dependencies to manage — Maya handles everything.

!!! warning "Use the correct version"
    Each Maya version requires its own build. The files are **not interchangeable** — Maya 2024 uses Python 3.10 while Maya 2025/2026 use Python 3.11. Windows and macOS builds are also not interchangeable.

### Step 1: Copy the file

Extract the zip and place `mcaEditor.py` in your Maya plug-ins folder:

=== "Windows"

    ```
    C:\Users\<you>\Documents\maya\<version>\plug-ins\mcaEditor.py
    ```

=== "macOS"

    ```
    ~/Library/Preferences/Autodesk/maya/<version>/plug-ins/mcaEditor.py
    ```

=== "Linux"

    ```
    ~/maya/<version>/plug-ins/mcaEditor.py
    ```

If the `plug-ins` folder doesn't exist, create it.

### Step 2: Load the plugin

1. Open Maya
2. Go to **Windows > Settings/Preferences > Plug-in Manager**
3. Find `mcaEditor.py` in the list
4. Check **Loaded**
5. Check **Auto load** to have it load every session

### Step 3: Open MCA Editor

Click the **Script Editor** button in Maya's toolbar. MCA Editor opens instead of Maya's built-in editor.

---

## Unreal Engine

MCA Editor for Unreal Engine is distributed as a standard UE plugin with pre-compiled binaries. Extract it into your project's `Plugins/` folder and enable it in the Plugins menu.

!!! warning "Use the correct version"
    Each UE version requires its own build. Download the zip that matches your Unreal Engine version (5.5, 5.6, 5.7, etc.).

### Step 1: Extract the plugin

Download and extract the zip for your UE version. Place the `MCAEditor/` folder into your project's `Plugins/` directory:

```
YourProject/
  Plugins/
    MCAEditor/            <-- extract here
      MCAEditor.uplugin
      Binaries/
      Content/
      Resources/
```

If the `Plugins/` folder doesn't exist, create it.

### Step 2: Enable the plugin

1. Open your project in Unreal Engine
2. Go to **Edit > Plugins**
3. Search for **MCA Editor**
4. Check the **Enabled** checkbox
5. Restart UE when prompted

### Step 3: Open MCA Editor

Click the **MCA Editor** button in the toolbar, or go to **Window > MCA Editor**.

---

## First Run

On first load, MCA Editor will:

1. **Create a managed virtual environment** for third-party dependencies (PySide6, AI chat SDK)
2. **Install required packages** automatically

This happens once and takes about 30 seconds. Subsequent launches are instant.

!!! info "Where files go"

    === "Maya"

        - **Package cache:** `%LOCALAPPDATA%\MCAEditor-Maya<version>-py3.XX\` (Windows)
        - **Virtual environment:** `~/Documents/mca_preferences/.venv-3.XX/`
        - **Settings:** Stored in your OS settings (QSettings / Windows Registry)

    === "Unreal Engine"

        - **Plugin location:** `<YourProject>/Plugins/MCAEditor/`
        - **Virtual environment:** `~/Documents/mca_preferences/.venv-3.XX/`
        - **Settings:** Stored in your OS settings (QSettings / Windows Registry)

---

## Update

=== "Maya"

    Replace the `mcaEditor.py` file with the new version and restart Maya. The plugin detects version changes and re-extracts automatically.

=== "Unreal Engine"

    Delete the existing `MCAEditor/` folder from your project's `Plugins/` directory and extract the new version in its place. Restart UE.

---

## Uninstall

=== "Maya"

    1. Uncheck **Loaded** and **Auto load** in Maya's Plug-in Manager
    2. Delete `mcaEditor.py` from your plug-ins folder
    3. Optionally, delete the cache folder at `%LOCALAPPDATA%\MCAEditor-Maya*\`

=== "Unreal Engine"

    1. Go to **Edit > Plugins**, uncheck **MCA Editor**, and restart UE
    2. Delete the `MCAEditor/` folder from your project's `Plugins/` directory
