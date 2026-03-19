# MCA Editor — Plugin Monetization System Spec

**Date:** 2026-03-18  
**Status:** Design finalized — implementation spec separate  
**Depends on:** Activation server (specced, not yet built), Plugin system wiring (2026-03-03_api_plugin_plan.md)

---

## Core Principle

> **Plugins ship zero license code. MCA's PluginManager owns all license logic, forever.**

Plugin authors never update their plugin for licensing reasons. The plugin declares what it is via a signed manifest. MCA decides whether to load it. This holds true even if the developer goes dormant.

---

## Decisions Made

| Topic | Decision |
|-------|----------|
| Free plugins | No manifest required — load unconditionally |
| Paid plugins | Require signed `plugin_manifest.json` from MCA |
| Developer fee | None — replaced by affiliate revenue share |
| MCA revenue | 10% Gumroad affiliate cut (minimum, mandated at registration) |
| Payment platform | Gumroad (developer's own product) |
| License keys | Gumroad-generated keys — MCA validates via Gumroad's `/api/licenses/verify` |
| Discovery (launch) | Website directory at `mcaeditor.com/plugins` |
| Discovery (future) | In-editor browser panel (V2, deferred) |
| Developer portal | Manual email flow at launch, self-serve portal later |

---

## How It Works — End to End

### For Plugin Authors

1. Build their plugin using MCA's public `EditorAPI`
2. Register at `developers.mcaeditor.com` (or email `info@mechart.org` at launch)
3. Create a Gumroad product for their plugin
4. Add MCA as a Gumroad affiliate at minimum 10% — required to be listed
5. Submit plugin details (plugin ID, display name, Gumroad permalink, affiliate confirmation)
6. Receive a signed `plugin_manifest.json` from MCA
7. Ship plugin folder containing their code + that manifest
8. MCA handles all license enforcement — author never touches it again

### For Users

1. Browse `mcaeditor.com/plugins` — click "Buy on Gumroad" (affiliate link)
2. Purchase on Gumroad, receive a Gumroad license key by email
3. Drop plugin folder into `~/Documents/mca_preferences/plugins/`
4. If plugin is paid — MCA's license dialog prompts for their Gumroad key
5. MCA validates the key against Gumroad's API, caches the result locally (14-day offline grace)
6. Plugin loads — no further action needed from user or developer

---

## Plugin Manifest Schema

Every paid plugin ships a `plugin_manifest.json` in its root directory. Free plugins do not need one. This schema is **versioned and must remain backward-compatible forever**.

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
    "purchase_url": "https://mechart.gumroad.com/l/my-tool?affiliate=mca"
  },
  "entry_point": "my_tool/plugin.py",
  "min_mca_version": "1.0.0",
  "mca_signature": "<base64-encoded HMAC from MCA server>"
}
```

**`pricing.model` values:**
- `"free"` — manifest optional; if present, loads unconditionally (signature still verified if manifest exists)
- `"paid"` — requires a Gumroad license key
- `"subscription"` — future use; treated as `"paid"` for now

**`mca_signature`** is computed by MCA's server over a canonical JSON of all other fields using a private key that lives server-side only. PluginManager verifies with the corresponding public key, compiled into `mca_core`.

---

## PluginManager Load Flow

```
load_plugin(plugin_dir)
    │
    ├── Does plugin_manifest.json exist?
    │       └── NO → load freely, no questions asked (free/local/open-source)
    │
    ├── Parse manifest, validate mca_signature (offline, public key check)
    │       └── Invalid signature → reject ("Plugin manifest is not valid")
    │
    ├── Check min_mca_version compatibility
    │       └── Incompatible → reject with user-facing message
    │
    ├── pricing.model == "free" (or no model field)?
    │       └── YES → instantiate plugin, done
    │
    └── pricing.model == "paid"
            │
            ├── Check local plugin license cache
            │       (plugin_id + machine_id, stored in plugin_licenses.db)
            │
            ├── Cache hit + not expired (14 days)?
            │       └── YES → instantiate plugin, done
            │
            ├── Do we have a stored license key for this plugin?
            │       └── NO → show PluginLicenseDialog, prompt user to enter Gumroad key
            │
            ├── Call activation server: POST /validate_plugin
            │       {plugin_id, gumroad_permalink, license_key, machine_id, mca_version}
            │
            │       Activation server calls Gumroad /api/licenses/verify
            │       + tracks machine activations
            │
            ├── Server returns valid?
            │       ├── YES → store key, cache result (14-day TTL), instantiate plugin
            │       └── NO  → show error with reason, offer to re-enter key or buy
            │
            └── Server unreachable?
                    ├── Prior valid cache within grace period → load (offline grace)
                    └── No grace period → "License check failed — check your connection"
```

This entire flow lives in `mca_core/plugin_license.py`, called by `PluginManager`. Plugin code is **never imported** before the flow completes successfully.

---

## Activation Server Additions

Two new endpoints added to the existing activation server:

### `POST /validate_plugin`

MCA Editor calls this. Server proxies to Gumroad and tracks machine activations.

```
Request:
{
  "plugin_id": "com.example.my-tool",
  "gumroad_permalink": "my-tool",
  "license_key": "<gumroad license key>",
  "machine_id": "<fingerprint>",
  "mca_version": "1.2.0"
}

Response (valid):
{
  "valid": true,
  "plugin_id": "com.example.my-tool",
  "machines_used": 1,
  "machine_limit": 2
}

Response (invalid):
{
  "valid": false,
  "reason": "invalid_key" | "wrong_plugin" | "machine_limit_exceeded" | "refunded"
}
```

### `POST /register_plugin` (developer-facing, authenticated)

Called manually (or eventually by the developer portal) when a dev registers a plugin. Returns the signed `plugin_manifest.json`. Requires a developer API key.

---

## Revenue Flow

```
User pays $20 on Gumroad
    │
    ├── Gumroad fee (~10%)       → $2.00 to Gumroad
    ├── MCA affiliate (10%)      → $2.00 to MCA's Gumroad account (automatic)
    └── Developer keeps          → $16.00
```

MCA earns passively with zero payment routing. All handled by Gumroad's affiliate system. No invoices, no manual payouts.

---

## New Files

| File | Purpose | Ship when |
|------|---------|-----------|
| `mca_core/plugin_manifest.py` | Manifest parsing + signature verification | Now |
| `mca_core/plugin_license.py` | License check flow, cache read/write, server call | Now (stub ok at launch) |
| `mca_qt/widgets/plugin_license_dialog.py` | Gumroad key entry UI | Before first paid plugin |
| `mca_preferences/plugin_licenses.db` | SQLite cache of validated licenses | Before first paid plugin |
| `tools/sign_manifest.py` | Server-side manifest signer (gitignored) | Before first paid plugin |

---

## Files to Modify

| File | Change |
|------|--------|
| `mca_editor/plugins/__init__.py` | Add manifest check + `plugin_license.check()` call before instantiation |
| `mca_core/config/settings.py` | Add `plugin_license_server_url` setting |
| `build_maya.py` | Add `plugin_manifest.py`, `plugin_license.py` to Cython build list |
| Activation server | Add `/validate_plugin`, `/register_plugin` endpoints |

---

## What Plugin Authors Never Have to Do

- Write license checks
- Call any API
- Handle offline grace periods
- Deal with machine limits
- Update their plugin when MCA's backend changes
- Update their plugin when MCA adds an in-editor marketplace

Their only obligation: ship a valid signed `plugin_manifest.json`. If they change their pricing or Gumroad product, they request a new manifest. Their plugin code is never touched.

---

## What Ships Now vs Later

### Now (before launch — one session)
- `plugin_manifest.py` — manifest parsing and signature verification
- `plugin_license.py` — stub that checks for manifest, verifies signature, returns "coming soon" for paid plugins
- `PluginManager` wired to call both before loading any plugin

### Before first paid plugin ships
- Full `plugin_license.py` implementation (Gumroad key flow, cache, server call)
- `plugin_license_dialog.py` UI
- `plugin_licenses.db` SQLite cache
- Activation server `/validate_plugin` endpoint
- `tools/sign_manifest.py` manifest signer

### V2 / Future
- In-editor plugin browser panel
- Self-serve developer portal at `developers.mcaeditor.com`
- Subscription pricing model support
