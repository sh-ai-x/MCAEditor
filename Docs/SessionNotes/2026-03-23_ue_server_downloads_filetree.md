# 2026-03-23 — UE Server Support, Downloads Page, File Tree Fix

## Summary

Three areas of work this session:

1. **License Server: Unreal Engine support** — Extended `api.mcaeditor.com` to handle UE and bundle products
2. **Downloads page & versioned distribution** — Built dynamic download page with JS, `releases.json` manifest, and deploy pipeline
3. **File tree refresh & state persistence** — Fixed sidebar not detecting external file changes and losing expanded state

---

## 1. License Server — Unreal Engine Support

### Database
- Added `dcc TEXT NOT NULL DEFAULT 'maya'` column to `license_keys` in `schema.sql`
- Idempotent `ALTER TABLE` migration in `database.py:init_db()` (try/except OperationalError)
- Added `dcc` parameter to `register_key()` and `dcc` to SELECT lists in all query functions

### Config
- Added 3 new env vars in `config.py`: `PRODUCT_ID_UE_PERPETUAL`, `PRODUCT_ID_UE_ANNUAL`, `PRODUCT_ID_BUNDLE`
- Added `"bundle": 3` to `MACHINE_LIMITS`

### Webhook & API
- Refactored `_get_product_type()` in `app.py` to return `(product_type, dcc)` tuple
- Updated `_handle_sale()` to pass `dcc` to `register_key()`
- Added `"dcc"` field to `/activate` and `/validate` JSON responses
- Added `DCC_LABELS` dict for human-readable labels on `/manage` and `/license` pages
- Updated `_KEY_CARD` template to show DCC label

### Deployed to VPS
- All server changes deployed and tested via SFTP + SSH

---

## 2. Downloads Page & Versioned Distribution

### New Files
- **`CHANGELOG.md`** — Backfilled v1.0.0 through v1.0.3 entries
- **`website/docs/download.md`** — Dynamic download page with HTML tabs for Windows/macOS, UE section (hidden when empty), "What's New" changelog, previous versions
- **`website/docs/assets/javascripts/downloads.js`** — Vanilla JS IIFE fetching `/releases.json`, renders tables, tabs, changelog

### Deploy Pipeline (`tools/deploy_website.py`)
- Added `parse_changelog()` — regex parses CHANGELOG.md version headers and bullet items
- Added `read_remote_json()` — reads existing releases.json from VPS via SFTP
- Added `_build_downloads_dict()` — generates download URL paths for all Maya versions
- Added `upload_releases()` — idempotent merge of new changelog entries into releases.json
- Added `upload_download_zips()` — uploads from `dist/latest/`, renames `Windows`→`win`, `macOS`→`mac`
- Restructured `deploy_site()` to keep SFTP open through step 3

### Nav & Link Updates
- Added `Download` to `mkdocs.yml` nav between Home and Pricing
- Added `navigation.tabs.sticky` feature
- Removed `Changelog` from nav (covered by download page's "Show older releases")
- Updated CTAs in `pricing.md`, `installation.md`, and `index.md` to link to download page

### CSS
- Added download page styles in `custom.css`: `.dl-tabs`, `.dl-tab`, `.dl-tab-content`, `.dl-table`

### Bug Fix
- Download page was stuck on "Loading latest release..." — `downloads.js` script tag used relative path, changed to absolute `/assets/javascripts/downloads.js`

---

## 3. File Tree Refresh & State Persistence

### Root Cause: External files not detected
- `QFileSystemWatcher` only watched top-level workspace folders, not subdirectories
- Files added in nested folders never triggered `directoryChanged`

### Fix: Watch all subdirectories
- Modified `_populate_folder()` to collect all discovered directory paths into a `discovered_dirs` set
- Added `_sync_watcher()` method — diffs discovered dirs against currently watched dirs, adds/removes as needed
- Called at end of every `_refresh_tree()` to keep watcher in sync

### Fix: Expanded state lost during rebuild
- `QTreeWidget.clear()` in PySide6 can fire `itemCollapsed` signals, which drained `_expanded_paths` through `_on_item_collapsed` before the re-expansion loop ran
- Fix: snapshot `_expanded_paths` into `restore_paths` before `clear()`, use snapshot for re-expansion

### Fix: Rapid rebuilds from batch file additions
- Added 200ms debounce timer (`QTimer`, singleShot) on `_on_directory_changed`
- Multiple rapid `directoryChanged` signals coalesce into one rebuild via `_debounced_refresh()`

### UI Polish
- Changed refresh button label from `"R"` to `"\u21BB"` (↻) for better discoverability

---

## Builds & Deployment

- Built all 6 variants: Maya 2024/2025/2026 x Windows/macOS
- macOS builds done on Mac Mini via SSH
- All zips uploaded to VPS `/downloads/maya/` via `deploy_website.py`
- Website rebuilt and deployed

---

## Files Changed

| File | Change |
|------|--------|
| `CHANGELOG.md` | New — backfilled v1.0.0–v1.0.3 |
| `mca_license_server/schema.sql` | Added `dcc` column |
| `mca_license_server/database.py` | Migration + `dcc` in queries |
| `mca_license_server/config.py` | 3 UE/bundle env vars |
| `mca_license_server/.env.example` | 3 new vars |
| `mca_license_server/app.py` | UE product detection, DCC labels, API responses |
| `tools/deploy_website.py` | Changelog parsing, zip upload, releases.json |
| `website/docs/download.md` | New dynamic download page |
| `website/docs/assets/javascripts/downloads.js` | New JS for download rendering |
| `website/docs/assets/stylesheets/custom.css` | Download page styles |
| `mkdocs.yml` | Nav update, sticky tabs |
| `website/docs/pricing.md` | CTA link update |
| `website/docs/getting-started/installation.md` | Link to download page |
| `website/docs/index.md` | CTA link update |
| `mca_qt/widgets/sidebar.py` | Subdirectory watching, debounce, state snapshot |
