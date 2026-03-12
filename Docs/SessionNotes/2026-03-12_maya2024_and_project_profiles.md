# Session Notes: Maya 2024 Support & Project Profiles

**Date:** 2026-03-12

## Maya 2024 (PySide2) Compatibility

### Problem
Plugin froze/crashed in Maya 2024 (Python 3.10, PySide2). Root cause:
**Shiboken2's metaclass cannot handle Cython-compiled `.pyd` files that
define classes inheriting from Qt classes.** Even without virtual method
overrides or Signals, the metaclass introspection fails with TypeError,
RecursionError, or ACCESS_VIOLATION.

### Fix
- **9 additional files** moved from `.pyd` to `.pyc` in `setup.py` and
  `build_maya.py` (3 Signal-bearing + 6 Qt-subclass):
  `editor_group_container.py`, `terminal_tab_panel.py`, `terminal_backend.py`,
  `ai_panel.py`, `connection_dialog.py`, `create_project_dialog.py`,
  `license_dialog.py`, `new_tab_dialog.py`, `project_settings_dialog.py`

- **PySide2 `exec()` patches** added to `qt_compat.py`:
  QApplication, QDialog, QMenu, QDrag all get `exec()` wrappers calling `exec_()`.
  Must use `lambda self: self.exec_()` (bound method), NOT direct alias
  `cls.exec = cls.exec_` (crashes Shiboken2).

- **Progress dialog parenting**: Maya 2024 uses `shiboken2.wrapInstance()`
  to get the main window for parenting the first-launch progress dialog.

- **Multi-version builds**: `build_maya.py --maya-version 2024` builds to
  `dist/MCAEditor-Maya2024/`, `--maya-version 2025` to `dist/MCAEditor-Maya2025/`.

## Per-Version Preference Isolation

### Problem
Maya 2024 and 2025 were sharing QSettings, session.json, and output.log.
Different Python/PySide versions could cause conflicts.

### Fix
- **QSettings**: Namespaced by Maya version (`MCAEditor-Maya2024`, `MCAEditor-Maya2025`).
  Set via `MCASettings(app_name=...)` in `plugin_main.py` and `maya_window.py`.

- **Session files**: `session.json` and `output.log` stored in version-specific
  subdirs (e.g. `~/Documents/mca_preferences/Maya2025/`). `scripts/` workspace
  stays shared at root level.

- **Existing preferences migrated**: Registry keys copied, session files copied
  to new version-specific locations.

## .mca-project Profile System (Schema v4)

### Problem
The `.mca-project` file stored DCC-specific settings (startup/shutdown code,
env vars) at the top level. This doesn't work when the same project is opened
from Maya 2024, Maya 2025, and eventually Unreal -- each needs different
dependency paths and startup code.

### Design
**Schema v4** splits the file into two layers:

**Shared settings (top-level):**
- name, python_paths, excluded_folders, open_on_editor_open, auto_reload_modules

**Profile-specific settings (under `"profiles"` key):**
- startup_script, startup_code, shutdown_script, shutdown_code, env_vars, load_immediately
- Keyed by DCC tag: `"Maya2025"`, `"Maya2024"`, `"Unreal"`, `"default"`, etc.

**Profile resolution order:**
1. Exact match on `dcc_tag` (e.g. `"Maya2025"`)
2. Fall back to `"default"` profile
3. Empty defaults if neither exists

**v3 auto-migration:** When loading a v3 file, the flat DCC-specific fields
are moved into a `"default"` profile. The user can then copy it to version-
specific profiles via the settings dialog.

### Files Changed
- `mca_core/project.py` -- MCAProject now accepts `dcc_tag`, stores `_profiles` dict,
  profile-specific properties delegate to active profile
- `mca_qt/editor_panel.py` -- Stores `_dcc_version`, passes `dcc_tag` to MCAProject
- `mca_qt/widgets/project_settings_dialog.py` -- Profile selector (QComboBox) with
  Add/Remove/Copy buttons, profile-specific widgets switch when profile changes

### Example v4 .mca-project
```json
{
    "schema_version": 4,
    "name": "Wayward",
    "python_paths": ["."],
    "excluded_folders": ["__pycache__", ".git", ...],
    "open_on_editor_open": true,
    "auto_reload_modules": true,
    "profiles": {
        "Maya2025": {
            "startup_script": "",
            "startup_code": "import os\n...\nstartup.startup_init(dcc='maya')",
            "shutdown_script": "",
            "shutdown_code": "startup.shutdown('maya')",
            "env_vars": {
                "MCA_MAYA_DEPEND": "...dependencies/2025",
                "MCA_COMMON_DEPEND": "...dependencies/python311"
            },
            "load_immediately": false
        },
        "Maya2024": {
            "startup_code": "...",
            "env_vars": {
                "MCA_MAYA_DEPEND": "...dependencies/2024",
                "MCA_COMMON_DEPEND": "...dependencies/python310"
            }
        }
    }
}
```

## Pending
- Build and test both Maya 2024 and 2025 with the profile changes
- Convert Wayward `.mca-project` to v4 with Maya2025 profile (auto-migrates on first open)
- Commit and push all changes to GitHub
