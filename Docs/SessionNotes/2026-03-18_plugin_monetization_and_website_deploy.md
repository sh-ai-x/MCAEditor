# 2026-03-18 — Plugin Monetization Phase 1 & Website Deploy Pipeline

## Summary
Implemented plugin monetization infrastructure (manifest verification + license stub),
created website documentation for plugins, deployed everything to the Hostinger VPS,
disabled the broken GitHub Actions workflow, and set up a proper deploy script.

## Plugin Monetization (Phase 1)

### New Files
- **`mca_core/plugin_manifest.py`** — Loads `plugin_manifest.json`, verifies HMAC-SHA256
  signatures (base64-encoded), checks semver compatibility. `PluginManifest` class holds
  nested `pricing` dict (`model`, `gumroad_permalink`, `purchase_url`).
- **`mca_core/plugin_license.py`** — Stub that always returns `(False, "coming soon")`
  for paid plugins. Will be replaced when marketplace launches.
- **`tools/test_plugin_manifest.py`** — 19 tests covering all manifest/license gate paths.
  All pass.

### Modified Files
- **`mca_core/plugins/__init__.py`** — Added manifest gate at top of `_load_plugin()`:
  load manifest → verify signature → check compatibility → check pricing model →
  license stub for paid/subscription. Plugins without `plugin_manifest.json` load freely.
- **`mca_core/config/settings.py`** — Added `plugin_license_server_url` default
  (`https://activate.mcaeditor.com`).

### Key Design Decisions
- `plugin_manifest.json` is separate from `plugin.json` (plugin metadata)
- Nested `pricing` dict in manifest (not flat attributes) per the monetization spec
- Base64-encoded HMAC signatures (not hex)
- `manifest_version` is integer (default 0), not string
- 10% Gumroad affiliate rate (changed from initial 5%)
- `"subscription"` pricing model treated as `"paid"` until subscription support ships

## Website Updates

### New Pages
- **`website/docs/plugins.md`** — Plugin Directory with Orange Slice listing
- **`website/docs/editor-guide/plugins.md`** — User guide for installing/managing plugins
- **`website/docs/plugin-development/publishing.md`** — Developer guide for publishing plugins

### Changes
- **`mkdocs.yml`** — Copyright fixed to "Mechanical Art Studios", added nav entries
- **`website/docs/plugin-development/distribution.md`** — Added "Selling Your Plugin" section

## Deploy Infrastructure

### GitHub Actions — DISABLED
- `.github/workflows/deploy-docs.yml` changed from `push` trigger to `workflow_dispatch`
- GitHub Pages doesn't work for private repos (needs Enterprise plan)
- This stops the failure notification emails Nathan was receiving

### VPS Deploy Script — NEW
- **`tools/deploy_website.py`** — Builds MkDocs locally, uploads via SFTP to
  `/var/www/mcaeditor.com/` on the Hostinger VPS (187.124.230.93)
- Uses SSH key auth (no password needed)
- Usage: `python tools/deploy_website.py`

### SSH Access Simplified
- Added `Host vps` entry to `~/.ssh/config` — `ssh vps` connects as root with key auth
- Added ed25519 public key to VPS `~/.ssh/authorized_keys`

## Version
- Bumped to **1.0.3** in `mca_core/__init__.py`
- All 6 builds (Win + macOS, Maya 2024/2025/2026) rebuilt and deployed at 1.0.3

## Version Check Feature
- **`mca_core/version_check.py`** — Background thread checks `website/docs/version.json`
  for newer versions. Non-blocking, shows yellow warning in output panel if update available.
- Wired into both `mca_maya/maya_window.py` and `mca_standalone/main.py`

## Files Not Committed (gitignored or untracked)
- `tools/deploy_website.py` — gitignored (tools/ dir)
- `tools/test_plugin_manifest.py` — gitignored
- `site/` — build output
- `website/site/` — build output
- `resources/images/Banners/`, `resources/images/mca_600x600.png` — untracked assets
