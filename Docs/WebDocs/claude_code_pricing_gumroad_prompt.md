# Claude Code Task: Pricing Page + Gumroad Webhook Server

## Overview

Two deliverables:
1. A **pricing page** added to mcaeditor.com (MkDocs site)
2. A **lightweight Gumroad webhook server** that receives purchase events
   and registers license keys in a database — ready to plug into the full
   activation system later

This is intentionally scoped. Do NOT build the full activation/machine-limit
system yet. Just the key registration side — capturing purchases into a DB.

---

## Read These Files First

Before touching anything:
- `mkdocs.yml` — to understand nav structure
- `docs/index.md` — homepage, needs a pricing button added
- `docs/getting-started/installation.md` — download table to reference

---

## Deliverable 1: Pricing Page

### File to create: `docs/pricing.md`

```markdown
---
title: Pricing
---

# Pricing

MCA Editor is available as a **perpetual license** or an **annual subscription**.
Try it free for 14 days — no credit card required.

---

## MCA Editor for Maya

Supports **Windows, macOS, and Linux**. Maya 2024, 2025, and 2026.

<div class="pricing-table" markdown>

| | Perpetual | Annual |
|---|---|---|
| **Price** | $99 USD | $35 USD/year |
| Maya 2024, 2025, 2026 | ✓ | ✓ |
| Windows, macOS, Linux | ✓ | ✓ |
| All Editor Features | ✓ | ✓ |
| Orange Slice AI Chat | ✓ | ✓ |
| Plugin Architecture | ✓ | ✓ |
| Free Updates (current major version) | ✓ | ✓ |
| Activations | 2 machines | 2 machines |

</div>

[Buy Perpetual — $99](GUMROAD_PERPETUAL_URL){ .md-button .md-button--primary }
[Buy Annual — $35/yr](GUMROAD_ANNUAL_URL){ .md-button }

---

## Free Trial

MCA Editor includes a **14-day free trial** with full access to all features.
No account or credit card needed — just install and run.

[Download & Try Free](getting-started/installation.md){ .md-button }

---

## What's Included

### Editor Features
- Script Mode and Project Mode
- Syntax highlighting for Python and MEL
- Code completion, Find & Replace, Find in Files
- Integrated terminal
- Drag-and-drop tab management
- Output panel with full stack traces

### Orange Slice AI Chat
- Built-in AI assistant that understands your Maya scene
- Reads your code, executes scripts, navigates your project
- Bring your own API key (Anthropic, OpenAI, or Google)

### Plugin Architecture
- Extend MCA Editor with Python plugins
- Clean documented API with 28 methods
- Panel, menu, and execution hooks

---

## License Terms

- One license covers **2 machine activations**
- Perpetual license covers the **current major version** (MCA Editor 1.x)
- Annual license stays active as long as subscription is current
- Need more seats? Email [info@mechart.org](mailto:info@mechart.org)

---

## FAQ

**Can I use MCA Editor on Windows, Mac, and Linux?**
Yes. A single license covers all platforms.

**What happens after the 14-day trial?**
MCA Editor will prompt you to enter a license key. Your scripts and settings
are preserved — nothing is lost.

**Can I upgrade from Annual to Perpetual?**
Yes. Email [info@mechart.org](mailto:info@mechart.org) and we'll sort it out.

**Do you offer studio or site licenses?**
Not yet through the store, but email [info@mechart.org](mailto:info@mechart.org)
and we can work something out.

**What versions of Maya are supported?**
Maya 2024, 2025, and 2026 on Windows, macOS, and Linux.

**Will there be an Unreal Engine version?**
Yes — planned for a future release. Existing customers will receive a
discounted upgrade path.
```

---

### Update `mkdocs.yml` nav

Add Pricing to the top-level nav, between Home and Getting Started:

```yaml
nav:
  - Home: index.md
  - Pricing: pricing.md          # ADD THIS LINE
  - Getting Started:
      - Installation: getting-started/installation.md
      - First Launch: getting-started/first-launch.md
  - Editor Guide:
      ...
```

---

### Update `docs/index.md` homepage

Find the Quick Start section and add two buttons directly above the numbered
steps, after the introductory paragraph:

```markdown
[Buy Now — $99](pricing.md){ .md-button .md-button--primary }
[Try Free for 14 Days](getting-started/installation.md){ .md-button }
```

Also add a "More Features" or "See Pricing" link at the bottom of the
Features section:

```markdown
[See pricing and try free →](pricing.md)
```

---

## Deliverable 2: Gumroad Webhook Server

A minimal Flask app that:
- Receives Gumroad sale webhooks
- Validates the webhook is genuinely from Gumroad
- Stores the license key and sale info in SQLite
- Returns 200 OK so Gumroad doesn't retry

This is intentionally minimal. No machine activation yet. Just key capture.

### Directory structure to create:
```
mca_license_server/
    app.py
    database.py
    config.py
    schema.sql
    requirements.txt
    .env.example
    README.md
```

---

### `mca_license_server/schema.sql`

```sql
-- License keys registered via Gumroad webhook
CREATE TABLE IF NOT EXISTS license_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL UNIQUE,
    raw_key TEXT NOT NULL UNIQUE,          -- Store raw key for support lookups
    gumroad_sale_id TEXT UNIQUE,
    gumroad_product_id TEXT,
    gumroad_email TEXT,                    -- Buyer email for support
    product_type TEXT NOT NULL DEFAULT 'perpetual',  -- 'perpetual' or 'annual'
    machine_limit INTEGER NOT NULL DEFAULT 2,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoke_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_keys_hash ON license_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_keys_raw ON license_keys(raw_key);
CREATE INDEX IF NOT EXISTS idx_keys_sale ON license_keys(gumroad_sale_id);
```

---

### `mca_license_server/config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Required — set in .env
GUMROAD_WEBHOOK_SECRET = os.environ.get("GUMROAD_WEBHOOK_SECRET", "")
SERVER_SECRET = os.environ.get("SERVER_SECRET", "")

# Gumroad product IDs — fill in after creating Gumroad products
# Leave as empty strings for now; webhook will still store keys
PRODUCT_ID_PERPETUAL = os.environ.get("GUMROAD_PRODUCT_PERPETUAL", "")
PRODUCT_ID_ANNUAL = os.environ.get("GUMROAD_PRODUCT_ANNUAL", "")

# Machine limits per product type
MACHINE_LIMITS = {
    "perpetual": 2,
    "annual": 2,
}

DB_PATH = os.environ.get("DB_PATH", "mca_licenses.db")
```

---

### `mca_license_server/database.py`

```python
import hashlib
import sqlite3
from pathlib import Path
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    schema = (Path(__file__).parent / "schema.sql").read_text()
    with get_db() as conn:
        conn.executescript(schema)


def hash_key(license_key: str) -> str:
    return hashlib.sha256(
        license_key.strip().upper().encode()
    ).hexdigest()


def register_key(
    raw_key: str,
    sale_id: str,
    product_id: str,
    email: str,
    product_type: str,
    machine_limit: int,
) -> bool:
    """
    Register a new license key from a Gumroad sale.
    Returns True if inserted, False if already exists (duplicate webhook).
    """
    key_hash = hash_key(raw_key)
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO license_keys
                    (key_hash, raw_key, gumroad_sale_id, gumroad_product_id,
                     gumroad_email, product_type, machine_limit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (key_hash, raw_key.strip().upper(), sale_id,
                 product_id, email, product_type, machine_limit),
            )
        return True
    except sqlite3.IntegrityError:
        # Duplicate sale_id or key — Gumroad sometimes sends webhooks twice
        return False


def key_exists(raw_key: str) -> bool:
    key_hash = hash_key(raw_key)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM license_keys WHERE key_hash = ? AND revoked = 0",
            (key_hash,)
        ).fetchone()
    return row is not None


def get_key_info(raw_key: str) -> dict | None:
    key_hash = hash_key(raw_key)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT raw_key, product_type, machine_limit, created_at,
                   revoked, gumroad_email
            FROM license_keys WHERE key_hash = ?
            """,
            (key_hash,)
        ).fetchone()
    return dict(row) if row else None
```

---

### `mca_license_server/app.py`

```python
"""
MCA Editor License Server — Gumroad webhook receiver.
Minimal scope: capture purchases into SQLite.
Machine activation endpoints to be added in a future session.
"""
import hashlib
import hmac
import logging
from flask import Flask, request, jsonify
from database import init_db, register_key, key_exists
from config import (
    GUMROAD_WEBHOOK_SECRET,
    PRODUCT_ID_PERPETUAL,
    PRODUCT_ID_ANNUAL,
    MACHINE_LIMITS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
init_db()


def _get_product_type(product_id: str) -> str:
    """Map Gumroad product ID to internal product type string."""
    if product_id == PRODUCT_ID_ANNUAL:
        return "annual"
    return "perpetual"  # Default for perpetual and unknown products


def _verify_gumroad_webhook(request) -> bool:
    """
    Verify the webhook came from Gumroad.
    Gumroad signs webhooks with HMAC-SHA256 if a secret is configured.
    If no secret is set yet, skip verification (development mode).
    """
    if not GUMROAD_WEBHOOK_SECRET:
        logger.warning("No webhook secret set — skipping verification (dev mode)")
        return True

    signature = request.headers.get("X-Gumroad-Signature", "")
    if not signature:
        return False

    expected = hmac.new(
        GUMROAD_WEBHOOK_SECRET.encode(),
        request.get_data(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


@app.route("/health", methods=["GET"])
def health():
    """Simple health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/gumroad/webhook", methods=["POST"])
def gumroad_webhook():
    """
    Receives Gumroad sale events.
    Gumroad sends form-encoded POST data.
    """
    if not _verify_gumroad_webhook(request):
        logger.warning("Webhook verification failed")
        return jsonify({"error": "Invalid signature"}), 401

    data = request.form

    # Skip test purchases
    if data.get("test") == "true":
        logger.info("Test webhook received — skipping")
        return jsonify({"status": "test_skipped"}), 200

    sale_id = data.get("sale_id", "")
    product_id = data.get("product_id", "")
    license_key = data.get("license_key", "")
    email = data.get("email", "")

    if not license_key:
        logger.error(f"Webhook received with no license key. Sale: {sale_id}")
        return jsonify({"error": "No license key in webhook"}), 400

    product_type = _get_product_type(product_id)
    machine_limit = MACHINE_LIMITS.get(product_type, 2)

    inserted = register_key(
        raw_key=license_key,
        sale_id=sale_id,
        product_id=product_id,
        email=email,
        product_type=product_type,
        machine_limit=machine_limit,
    )

    if inserted:
        logger.info(f"Registered key for sale {sale_id} ({product_type})")
    else:
        logger.info(f"Duplicate webhook for sale {sale_id} — ignored")

    # Always return 200 so Gumroad doesn't retry
    return jsonify({"status": "ok"}), 200


@app.route("/check", methods=["GET"])
def check_key():
    """
    Basic key existence check.
    Query param: ?key=MCA-XXXX-XXXX-XXXX-XXXX
    Used for manual support lookups. Not called by the editor yet.
    """
    raw_key = request.args.get("key", "").strip()
    if not raw_key:
        return jsonify({"error": "No key provided"}), 400

    exists = key_exists(raw_key)
    return jsonify({"valid": exists})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

---

### `mca_license_server/requirements.txt`

```
flask>=3.0.0
python-dotenv>=1.0.0
gunicorn>=21.0.0
```

---

### `mca_license_server/.env.example`

```
# Copy this to .env and fill in values

# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SERVER_SECRET=

# Copy from Gumroad Settings > Advanced > Webhook secret
GUMROAD_WEBHOOK_SECRET=

# Copy from Gumroad product URLs after creating products
GUMROAD_PRODUCT_PERPETUAL=
GUMROAD_PRODUCT_ANNUAL=

# Path to SQLite database file
DB_PATH=mca_licenses.db
```

---

### `mca_license_server/README.md`

```markdown
# MCA License Server

Lightweight Flask server that receives Gumroad purchase webhooks and
registers license keys in a local SQLite database.

## Setup

1. Install dependencies:
   pip install -r requirements.txt

2. Copy .env.example to .env and fill in values:
   cp .env.example .env

3. Run locally:
   python app.py

4. Run in production (behind nginx):
   gunicorn -w 2 -b 127.0.0.1:5000 app:app

## Gumroad Setup (manual steps)

After deploying to a server at api.mcaeditor.com:

1. Go to Gumroad > Settings > Advanced
2. Set webhook URL to: https://api.mcaeditor.com/gumroad/webhook
3. Copy the webhook secret into .env as GUMROAD_WEBHOOK_SECRET
4. Create your products and copy their IDs into .env

## Endpoints

- GET  /health              — Health check
- POST /gumroad/webhook     — Gumroad purchase events
- GET  /check?key=MCA-...   — Manual key lookup (support use)

## What's Not Here Yet

Machine activation endpoints (activate, validate, deactivate, list)
will be added in a future session once testing is complete.
See: activation_system_spec.md for the full planned spec.
```

---

## Important Notes for Claude Code

1. **GUMROAD_PERPETUAL_URL and GUMROAD_ANNUAL_URL** in `pricing.md` are
   placeholders. Leave them exactly as `GUMROAD_PERPETUAL_URL` and
   `GUMROAD_ANNUAL_URL` — do not invent fake URLs. Nathan will replace
   these with real Gumroad links after creating the products.

2. **Do not build** the machine activation endpoints yet. The README
   explicitly scopes what's included.

3. The `mca_license_server/` directory lives at the **project root**,
   not inside `mca_core` or any existing package. It's a standalone
   server deployed separately.

4. The pricing page uses MkDocs Material theme button syntax
   (`{ .md-button .md-button--primary }`). Verify this matches the
   theme already in use before publishing.

5. After all changes, run `mkdocs build` to regenerate the site, then
   upload the updated `site/` folder to Hostinger as usual.

6. Show a diff summary of every file created or modified before finishing.
```
