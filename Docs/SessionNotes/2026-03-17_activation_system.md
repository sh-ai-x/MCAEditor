# 2026-03-17 — Online Activation System & Gumroad Integration

## Summary
Built and deployed the complete online activation system for MCA Editor,
connecting Gumroad purchases to license key generation and machine-limited
activation.

## Version
- Bumped to **v1.0.1** — online activation system
- All three Maya versions built and deployed (2024, 2025, 2026)

## Gumroad Integration
- **Perpetual product**: https://ncomes.gumroad.com/l/ndsupov ($99)
- **Annual product**: https://ncomes.gumroad.com/l/qkscq ($35/yr)
- **Webhook**: Ping endpoint set to `https://api.mcaeditor.com/gumroad/webhook`
- Gumroad does NOT use webhook secrets — server skips verification (dev mode)
- Test purchases (creator self-buy) are processed normally (was previously skipping them)
- Product type detection uses `permalink` field fallback since Gumroad's internal
  `product_id` differs from the URL slug configured in `.env`
- VPS `.env` updated: `GUMROAD_PRODUCT_ANNUAL=qkscq`, `GUMROAD_PRODUCT_PERPETUAL=ndsupov`

## Online Activation System (NEW)

### Server Endpoints (api.mcaeditor.com)
- `POST /activate` — registers a machine, enforces 3-machine limit, returns activation token
- `POST /validate` — confirms activation is still valid, updates last_seen timestamp
- `POST /deactivate` — removes a machine activation (by token or key+machine_id)
- `POST /activations` — lists active machines for a key (JSON API for the editor)
- `GET /manage` — web page: enter email → see all keys + machines, deactivate with confirmation

### Database
- New `activations` table: key_hash, machine_id, machine_name, activation_token, timestamps
- `UNIQUE(key_hash, machine_id)` prevents duplicate slots
- Foreign key to `license_keys` table

### Client (mca_core/activation.py)
- **Machine fingerprint**: SHA-256 of hostname + MAC address (32 hex chars)
- **activate()**: offline HMAC check → POST to server → cache token locally
  - Falls back to offline-only if server unreachable
- **validate_on_launch()**: checks cached token, 7-day offline grace period
  - Auto-activates legacy keys (pre-online-activation) silently
  - Never blocks a user with valid HMAC key — online is belt-and-suspenders
- **deactivate()**: notifies server, clears local token + key
- **deactivate_machine()**: remotely removes another machine's activation
- **get_activations()**: fetches machine list for Manage tab in the dialog
- Uses `urllib.request` (stdlib only) — no third-party HTTP dependency in mca_core

### UI (licensing_dialog.py)
- `limit_reached` status switches to Manage tab with message
- Remote deactivation wired up via Remove buttons
- Web management link (api.mcaeditor.com/manage) shown as fallback

### Offline Behavior
- First activation without internet: offline HMAC validation passes, key stored,
  server activation fails silently, auto-activates next time internet is available
- Daily launch with cached token: no server call if within 7-day grace period
- Beyond grace period: tries server, if unreachable still allows use
- **Never blocks a user who has a valid HMAC key**

## Website Updates
- Pricing page: annual link updated to correct Gumroad URL
- Pricing page: added "Manage your activations" link
- License retrieval page: "Manage activations →" link with email passthrough
- Manage page: "View license keys →" link with email passthrough
- Contact email fixed to info@mechart.org on all server pages
- Footer navigation on both pages: cross-links between /license and /manage

## Issues Fixed
- Test purchases were being skipped (Gumroad flags creator self-purchases as test=true)
- Product type detection: Gumroad's webhook product_id is NOT the URL permalink slug,
  added fallback to check `permalink` and `product_permalink` fields
- `.env` sed doubling: `GUMROAD_PRODUCT_ANNUAL` got doubled to `qkscqqkscq` due to
  non-anchored sed pattern — fixed with `^` anchor

## Testing
- Test purchase flow verified end-to-end: Gumroad → webhook → key generated → retrieved
- Activation tested: UltraByte (Windows) registered as 1/3 machines
- Expired key tested: MCA-AG4A-BD7W-ZFAC-OF5O correctly rejected ("expired on 2026-03-16")
- Valid perpetual key tested: MCA-AMTA-CWLU-X23D-VKRY accepted and activated

## macOS SSL Fix (Later Session)
- Maya's embedded Python on macOS ships with **zero CA certificates** in its SSL
  trust store — `ssl.create_default_context().cert_store_stats()` returns all zeros
- Every HTTPS request from Maya Python failed with `CERTIFICATE_VERIFY_FAILED`
- This caused `activate()` to always fall back to offline-only mode on Mac
- **Fix**: Added `_get_ssl_context()` in `mca_core/activation.py` that detects the
  empty cert store and loads the macOS system bundle from `/etc/ssl/cert.pem`
- SSL context is built once and cached for the session (`_SSL_CONTEXT` module global)
- Windows is unaffected — Python uses the Windows certificate store automatically
- Falls back to `certifi` if `/etc/ssl/cert.pem` is missing
- All three Mac Maya builds (2024, 2025, 2026) rebuilt and deployed with the fix

## Website Downloads
- Added download zips to installation page for both Windows and macOS
- Download tables split by platform with `.md-button` styled links
- Zips contain only `mcaEditor.py` + `README.md` (no compiled internals exposed)
- All 6 zips uploaded to VPS at `/var/www/mcaeditor.com/downloads/`

## Build Pipeline Changes
- `build_maya.py`: `create_zip()` now produces slim download zips (single-file plugin + README only)
  instead of zipping the full dist folder with all compiled files
- Zip creation moved after `pack_and_deploy()` in the pipeline (needs the single-file .py first)
- `README.md` sourced from `G:\My Drive\Projects\MCAEditor\README.md`
- `dist/latest/` folder created to hold all current zips for Gumroad upload

## Mac Mini Remote Access
- SSH access established: `ncomes@192.168.68.72` (Nathans-Mac-mini.local)
- Can now download Mac builds remotely instead of building on the Mac manually
- macOS builds still must be compiled on Mac (Cython produces .so, not .pyd)

## Remaining
- Annual Gumroad product Content tab needs post-purchase instructions (retrieve key URL)
- Perpetual Gumroad product Content tab also needs the same instructions
- Upload the 6 zips from `dist/latest/` to both Gumroad products
