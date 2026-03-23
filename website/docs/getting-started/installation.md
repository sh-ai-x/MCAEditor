# Installation

MCA Editor is distributed as a single Python file that you drop into Maya's plug-ins folder. No installer, no dependencies to manage — Maya handles everything.

---

## Download

Download the latest version from the [Downloads page](../download.md).

!!! warning "Use the correct version"
    Each Maya version requires its own build. The files are **not interchangeable** — Maya 2024 uses Python 3.10 while Maya 2025/2026 use Python 3.11. Windows and macOS builds are also not interchangeable.

---

## Install

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

## First Run

On first load, MCA Editor will:

1. **Extract** its packages to a local cache directory
2. **Create a managed virtual environment** for third-party dependencies (like the AI chat SDK)
3. **Install required packages** automatically

This happens once and takes about 30 seconds. Subsequent launches are instant.

!!! info "Where files go"
    - **Package cache:** `%LOCALAPPDATA%\MCAEditor-Maya<version>-py3.XX\` (Windows)
    - **Virtual environment:** `~/Documents/mca_preferences/.venv-3.XX/`
    - **Settings:** Stored in your OS settings (QSettings / Windows Registry)

---

## Update

To update MCA Editor, simply replace the `mcaEditor.py` file with the new version and restart Maya. The plugin detects version changes and re-extracts automatically.

---

## Uninstall

1. Uncheck **Loaded** and **Auto load** in Maya's Plug-in Manager
2. Delete `mcaEditor.py` from your plug-ins folder
3. Optionally, delete the cache folder at `%LOCALAPPDATA%\MCAEditor-Maya*\`
