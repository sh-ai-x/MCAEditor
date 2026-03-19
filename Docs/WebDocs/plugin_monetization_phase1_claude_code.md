# Claude Code Prompt — Plugin Manifest & License Hook (Phase 1)

**Session scope:** Add manifest awareness and a license stub to PluginManager.
No full license implementation — just the hook that makes future work non-breaking.

---

## Context

MCA Editor has a plugin system in `mca_editor/plugins/__init__.py` with
`MCAPlugin`, `MCAPluginAPI`, and `PluginManager`. The system discovers and
loads plugins from `~/Documents/mca_preferences/plugins/`. It is currently
wired but has no license enforcement.

The goal of this session is to add two new files and modify PluginManager so
that the load flow is:

1. No `plugin_manifest.json` → load freely (free/local/open-source plugins)
2. `plugin_manifest.json` present → verify MCA signature → check pricing model
3. `pricing.model == "free"` → load freely
4. `pricing.model == "paid"` → call `plugin_license.check()` → stub returns
   `(False, "Plugin marketplace coming soon")` for now → log and skip

This means no paid plugin can load yet, but the architecture is correct and
requires zero changes when the full license system is added later.

---

## Step 1 — Read these files verbatim before writing any code

- `mca_editor/plugins/__init__.py` — full file
- `mca_core/config/settings.py` — full file
- `build_maya.py` — full file

Do not proceed until you have read all three.

---

## Step 2 — Create `mca_core/plugin_manifest.py`

New file. No Qt imports. Safe to Cython-compile.

### Responsibilities
- Define `PluginManifest` dataclass holding all manifest fields
- `load(plugin_dir)` — reads `plugin_manifest.json` from `plugin_dir`, returns
  `PluginManifest` or `None` if file does not exist
- `verify_signature(manifest)` — verifies `mca_signature` using HMAC-SHA256
  with a hardcoded public key constant (`MCA_MANIFEST_PUBLIC_KEY`). Returns
  `(True, None)` or `(False, reason_string)`
- `is_compatible(manifest, current_mca_version)` — checks `min_mca_version`
  using simple semver comparison (split on `.`, compare as int tuples)

### Manifest schema (parse these fields)
```json
{
  "manifest_version": 1,
  "plugin_id": "com.example.my-tool",
  "display_name": "My Tool",
  "version": "1.0.0",
  "author": "Studio Name",
  "developer_id": "dev_abc123",
  "pricing": {
    "model": "paid",
    "gumroad_permalink": "my-tool",
    "purchase_url": "https://gumroad.com/l/my-tool"
  },
  "entry_point": "my_tool/plugin.py",
  "min_mca_version": "1.0.0",
  "mca_signature": "<base64-encoded HMAC>"
}
```

### Signature verification
The signature is HMAC-SHA256 over the canonical JSON of all fields **except**
`mca_signature` itself, using the key `MCA_MANIFEST_PUBLIC_KEY`. For now,
set `MCA_MANIFEST_PUBLIC_KEY = "MCA_MANIFEST_DEV_KEY_PLACEHOLDER"` — this
will be replaced with the real key when the signing server is built. The
`verify_signature` function must still run the full HMAC check even with the
placeholder key so the code path is exercised.

### Coding standards
- No type hints in function signatures (types in Sphinx docstrings only)
- Sphinx-style docstrings on every class and method
- Heavy comments explaining WHY
- `import logging` with module-level logger
- try/except with meaningful messages around JSON parsing and HMAC operations

---

## Step 3 — Create `mca_core/plugin_license.py`

New file. No Qt imports. Safe to Cython-compile.

### Responsibilities
- `check(manifest)` — single public function. Takes a `PluginManifest`.
  Returns `(allowed: bool, reason: str)`.

### Stub implementation for now
```python
def check(manifest):
    """
    Check whether a paid plugin is licensed for this machine.
    
    :param PluginManifest manifest: The plugin's parsed manifest.
    :return: Tuple of (allowed, reason). allowed is False until the full
             license system is implemented.
    :rtype: tuple
    """
    # --- Stub: full implementation added when activation server ships ---
    # When implemented, this will:
    # 1. Check plugin_licenses.db cache (14-day TTL)
    # 2. Prompt user for Gumroad license key via PluginLicenseDialog
    # 3. Call activation server POST /validate_plugin
    # 4. Cache valid result, return (True, "")
    _logger.info(
        "Plugin '%s' requires a license. Marketplace coming soon.",
        manifest.plugin_id
    )
    return False, "Plugin marketplace coming soon — paid plugins are not yet supported."
```

### Coding standards
Same as plugin_manifest.py above.

---

## Step 4 — Modify `mca_editor/plugins/__init__.py`

**Read the file verbatim first.** Then add the manifest check to
`PluginManager`'s load method.

### Load flow to implement

In whatever method loads a single plugin directory:

```python
# 1. Check for manifest
manifest = plugin_manifest.load(plugin_dir)

# 2. No manifest — free/local plugin, load unconditionally
if manifest is None:
    # instantiate and load plugin as before
    ...
    return

# 3. Manifest present — verify signature
ok, reason = plugin_manifest.verify_signature(manifest)
if not ok:
    _logger.warning(
        "Plugin at '%s' has an invalid MCA signature: %s. Skipping.",
        plugin_dir, reason
    )
    return

# 4. Check MCA version compatibility
from mca_editor import __version__
if not plugin_manifest.is_compatible(manifest, __version__):
    _logger.warning(
        "Plugin '%s' requires MCA >= %s (current: %s). Skipping.",
        manifest.display_name, manifest.min_mca_version, __version__
    )
    return

# 5. Check pricing
if manifest.pricing_model == "paid":
    allowed, reason = plugin_license.check(manifest)
    if not allowed:
        _logger.info(
            "Plugin '%s' not loaded: %s", manifest.display_name, reason
        )
        return

# 6. Instantiate and load plugin as before
...
```

Do not restructure the rest of `PluginManager`. Only add the manifest check
at the top of the load path. Preserve all existing behaviour for plugins
without a manifest.

---

## Step 5 — Modify `mca_core/config/settings.py`

Add one new setting to `_DEFAULTS`:

```python
"plugin_license_server_url": "https://activate.mcaeditor.com",
```

---

## Step 6 — Modify `build_maya.py`

Read the file verbatim. Add `plugin_manifest.py` and `plugin_license.py` to
whatever list controls which `mca_core` files get Cython-compiled. Follow
exactly the same pattern as other `mca_core` entries in that list.

---

## What NOT to do this session

- Do not implement the full license check (SQLite cache, server call, dialog)
- Do not create `plugin_license_dialog.py`
- Do not modify the activation server
- Do not create `tools/sign_manifest.py`
- Do not add any Qt imports to the new files
- Do not restructure `PluginManager` beyond the manifest check

---

## Verification

After implementation, Claude Code must verify:

1. `python -c "from mca_core.plugin_manifest import load, verify_signature; print('OK')"` — imports cleanly
2. `python -c "from mca_core.plugin_license import check; print('OK')"` — imports cleanly
3. Drop a plugin folder with NO manifest into the plugins directory — it loads as before
4. Drop a plugin folder with a manifest where `pricing.model = "paid"` — it skips with the "coming soon" log message
5. Drop a plugin folder with a manifest where `pricing.model = "free"` and a valid signature — it loads
6. `build_maya.py` runs without error and includes the two new files in the Cython build list
