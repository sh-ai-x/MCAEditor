# Claude Code Task: Cross-Platform Path Audit & Fixes

## Context
MCA Editor currently targets Windows but is being expanded to macOS and Linux.
Before platform testing begins, audit the entire codebase for hardcoded
Windows-specific paths and platform assumptions, then fix them using a new
central platform utility module.

---

## Step 1: Read These Files First (Do Not Skip)

Before making any changes, read the following files in full:
- `mca_core/config/settings.py`
- `mca_core/session_manager.py`
- `mca_core/venv_manager.py`
- `mca_maya/plugin_main.py`
- `mca_maya/maya_window.py`
- `mca_core/mcp_setup.py`
- `build_maya.py`

---

## Step 2: Create `mca_core/platform_utils.py`

Create this file exactly as specified. All path logic in the codebase should
route through these helpers going forward.

```python
"""
mca_core/platform_utils.py

Cross-platform path and environment utilities for MCA Editor.
All platform-specific path logic should live here.
"""
import os
import platform
import sys
from pathlib import Path


def get_platform() -> str:
    """Returns 'windows', 'macos', or 'linux'."""
    system = platform.system()
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        system, system.lower()
    )


def get_config_dir() -> Path:
    """
    Root directory for MCA Editor user config and preferences.
    Windows:  %APPDATA%\\MCAEditor\\
    macOS:    ~/Library/Application Support/MCAEditor/
    Linux:    ~/.config/MCAEditor/   (respects XDG_CONFIG_HOME)
    """
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "MCAEditor"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir(maya_version: str = "", python_version: str = "") -> Path:
    """
    Directory for extracted plugin packages (the single-file cache).
    Windows:  %LOCALAPPDATA%\\MCAEditor\\
    macOS:    ~/Library/Caches/MCAEditor/
    Linux:    ~/.cache/MCAEditor/   (respects XDG_CACHE_HOME)

    If maya_version and python_version are provided, appends a versioned
    subdirectory e.g. MCAEditor-Maya2025-py3.11/
    """
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

    if maya_version and python_version:
        subdir = f"MCAEditor-Maya{maya_version}-py{python_version}"
        path = base / subdir
    else:
        path = base / "MCAEditor"

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_preferences_dir() -> Path:
    """
    Directory for user scripts, projects, and session data.
    Windows:  ~/Documents/mca_preferences/
    macOS:    ~/Documents/mca_preferences/
    Linux:    ~/mca_preferences/

    Note: ~/Documents may not exist on all Linux installs, so Linux
    falls back to home directory.
    """
    system = platform.system()
    if system == "Linux":
        base = Path.home()
    else:
        # Windows and macOS both have ~/Documents
        docs = Path.home() / "Documents"
        base = docs if docs.exists() else Path.home()
    path = base / "mca_preferences"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_maya_scripts_dir(maya_version: str) -> Path:
    """
    Maya's user scripts directory for the given version.
    Windows:  ~/Documents/maya/<version>/scripts/
    macOS:    ~/Library/Preferences/Autodesk/maya/<version>/scripts/
    Linux:    ~/maya/<version>/scripts/
    """
    system = platform.system()
    if system == "Windows":
        base = Path.home() / "Documents" / "maya" / maya_version
    elif system == "Darwin":
        base = (Path.home() / "Library" / "Preferences" /
                "Autodesk" / "maya" / maya_version)
    else:
        base = Path.home() / "maya" / maya_version
    return base / "scripts"


def get_maya_plugins_dir(maya_version: str) -> Path:
    """
    Maya's user plug-ins directory for the given version.
    Windows:  ~/Documents/maya/<version>/plug-ins/
    macOS:    ~/Library/Preferences/Autodesk/maya/<version>/plug-ins/
    Linux:    ~/maya/<version>/plug-ins/
    """
    return get_maya_scripts_dir(maya_version).parent / "plug-ins"


def get_maya_modules_dir() -> Path:
    """
    Maya's user modules directory (version-independent).
    Windows:  ~/Documents/maya/modules/
    macOS:    ~/Library/Preferences/Autodesk/maya/modules/
    Linux:    ~/maya/modules/
    """
    return get_maya_scripts_dir("").parent.parent / "modules"


def get_venv_dir(python_version: str) -> Path:
    """
    MCA Editor's managed virtual environment directory.
    e.g. get_venv_dir("3.11") -> <preferences_dir>/.venv-3.11/
    """
    return get_preferences_dir() / f".venv-{python_version}"


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


def is_batch_mode() -> bool:
    """
    Returns True if running in Maya batch/headless mode.
    Used to skip license checks on render farms.
    """
    try:
        import maya.cmds as cmds
        return cmds.about(batch=True)
    except Exception:
        return False
```

---

## Step 3: Audit and Fix — Specific Patterns to Find and Replace

Search the entire codebase for each of these patterns. For each one found,
replace with the appropriate `platform_utils` call.

### Pattern A: Hardcoded Windows %LOCALAPPDATA% or %APPDATA%
```python
# BEFORE (any variation of this):
os.environ.get("LOCALAPPDATA", ...)
os.path.expandvars("%LOCALAPPDATA%")
Path(os.environ["LOCALAPPDATA"])

# AFTER:
from mca_core.platform_utils import get_cache_dir
get_cache_dir(maya_version, python_version)
```

### Pattern B: Hardcoded ~/Documents/mca_preferences
```python
# BEFORE:
Path.home() / "Documents" / "mca_preferences"
os.path.expanduser("~/Documents/mca_preferences")

# AFTER:
from mca_core.platform_utils import get_preferences_dir
get_preferences_dir()
```

### Pattern C: Hardcoded Maya documents path
```python
# BEFORE:
Path.home() / "Documents" / "maya" / version / "plug-ins"
Path.home() / "Documents" / "maya" / version / "scripts"

# AFTER:
from mca_core.platform_utils import get_maya_plugins_dir, get_maya_scripts_dir
get_maya_plugins_dir(version)
get_maya_scripts_dir(version)
```

### Pattern D: Hardcoded .venv path
```python
# BEFORE:
Path.home() / "Documents" / "mca_preferences" / f".venv-{version}"

# AFTER:
from mca_core.platform_utils import get_venv_dir
get_venv_dir(python_version)
```

### Pattern E: Windows-only path separators or drive letters
```python
# BEFORE:
"C:\\Users\\" + username
path.replace("\\", "/")   # unnecessary if using pathlib

# AFTER: use pathlib Path objects throughout, never string concatenation for paths
```

---

## Step 4: Add Batch Mode Check to `plugin_main.py`

In `initializePlugin()`, add this guard before any UI or license logic:

```python
from mca_core.platform_utils import is_batch_mode

def initializePlugin(obj):
    if is_batch_mode():
        # Headless/render farm — load minimal plugin, skip UI and license checks
        _register_commands(obj)
        return
    
    # ... rest of existing init code ...
```

Also add to `uninitializePlugin()`:
```python
def uninitializePlugin(obj):
    if is_batch_mode():
        _deregister_commands(obj)
        return
    
    # ... rest of existing cleanup code ...
```

---

## Step 5: Add Trial Start Date Tracking

In `mca_core/config/settings.py` (or wherever QSettings is managed), add
a function to initialize and read the trial start date. This is purely local —
no server required.

```python
def get_or_init_trial_start() -> str:
    """
    Returns the trial start date as an ISO string.
    Sets it to today if this is the first launch.
    """
    from datetime import datetime
    existing = get_setting("license/trial_start", default=None)
    if existing is None:
        now = datetime.utcnow().isoformat()
        set_setting("license/trial_start", now)
        return now
    return existing


def get_trial_days_remaining() -> int:
    """Returns how many trial days are left (0 if expired)."""
    from datetime import datetime
    trial_start_str = get_or_init_trial_start()
    try:
        trial_start = datetime.fromisoformat(trial_start_str)
    except Exception:
        trial_start = datetime.utcnow()
    days_used = (datetime.utcnow() - trial_start).days
    return max(0, 14 - days_used)
```

---

## Step 6: Update `build_maya.py`

Add `mca_core/platform_utils.py` to the **pure Python** distribution list
(do NOT Cython-compile it — it needs to be readable for path debugging on
new platforms):

```python
# In DIST_PURE_PYTHON list:
"mca_core/platform_utils.py",
```

---

## Step 7: Verify — Show a Diff Summary

After making all changes, show a summary of every file modified with a brief
description of what changed. Do not make any changes beyond what is listed
in this spec. If you find other platform issues not covered here, list them
as a separate "Found but not fixed" section for review.

---

## What NOT to Change

- Do not modify any UI layout or widget code
- Do not add any network calls
- Do not change the license key format or HMAC logic
- Do not modify the Cython build configuration beyond adding platform_utils
  to the pure Python list
- Do not refactor anything unrelated to path handling
