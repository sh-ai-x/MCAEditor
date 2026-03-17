# Claude Code Task: Pricing Page + License Server (Full Spec)

## Overview

Three deliverables:
1. **Pricing page** added to mcaeditor.com (MkDocs site)
2. **License server** — Flask app that receives Gumroad webhooks, stores
   license keys, and tracks per-product machine activations
3. **License client** — `mca_core/activation.py` that the editor uses to
   activate, validate, and deactivate on each machine

This replaces the earlier partial spec. Use this document only — ignore any
previous activation_system_spec.md or claude_code_pricing_gumroad_prompt.md.

---

## Read These Files First (Do Not Skip)

Before writing any code:
- `mkdocs.yml`
- `docs/index.md`
- `docs/getting-started/installation.md`
- `mca_core/config/settings.py`
- `mca_maya/plugin_main.py`
- `build_maya.py`

---

## Key Design Decisions

- **3 seats per product per license** — not shared across products
- **Each DCC is independent** — Maya and Unreal each get their own 3-seat
  pool. A Maya + Unreal bundle gives 3 Maya seats AND 3 Unreal seats.
- **Entitlements-based** — a license key carries a list of products it
  unlocks. Each DCC plugin checks if its product is in the entitlement list.
- **Upgrade path** — buying an upgrade adds a new product entitlement to an
  existing key. Same key, new DCC unlocked.
- **Launch products** — Maya only (perpetual $99, annual $49/yr). Unreal,
  Blender etc. are future — schema must support them from day one.

---

## Part 1: Pricing Page

### Create `docs/pricing.md`

```markdown
---
title: Pricing
---

# Pricing

MCA Editor is available as a **perpetual license** or an **annual
subscription**. Try it free for 14 days — no credit card required.

---

## MCA Editor for Maya

Supports **Windows, macOS, and Linux**. Maya 2024, 2025, and 2026.

| | Perpetual | Annual |
|---|---|---|
| **Price** | $99 USD | $49 USD/year |
| Maya 2024, 2025, 2026 | ✓ | ✓ |
| Windows, macOS, Linux | ✓ | ✓ |
| All editor features | ✓ | ✓ |
| Orange Slice AI Chat | ✓ | ✓ |
| Plugin architecture | ✓ | ✓ |
| Free updates (MCA Editor 1.x) | ✓ | ✓ |
| Machine activations | 3 seats | 3 seats |

[Buy Perpetual — $99](GUMROAD_PERPETUAL_URL){ .md-button .md-button--primary }
[Buy Annual — $49/yr](GUMROAD_ANNUAL_URL){ .md-button }

---

## Free Trial

MCA Editor includes a **14-day free trial** with full access to all features.
No account or credit card needed.

[Download & Try Free](getting-started/installation.md){ .md-button }

---

## What's Included

**Editor**
- Script Mode and Project Mode
- Syntax highlighting for Python and MEL
- Code completion, Find & Replace, Find in Files
- Integrated terminal
- Output panel with full stack traces
- Drag-and-drop tab management

**Orange Slice AI Chat**
- Built-in AI assistant that understands your Maya scene
- Reads your code, executes scripts, navigates your project
- Bring your own API key (Anthropic, OpenAI, or Google)

**Plugin Architecture**
- Extend MCA Editor with Python plugins
- 28-method documented API
- Panel, menu, and execution hooks

---

## Coming Soon

Unreal Engine, Blender, and MotionBuilder versions are in development.
Existing customers will receive a discounted upgrade path when they launch.

---

## License Terms

- One license covers **3 machine activations per DCC**
- Perpetual license includes all MCA Editor 1.x updates
- Annual license stays active as long as the subscription is current
- Need more seats? Email [info@mechart.org](mailto:info@mechart.org)

---

## FAQ

**Can I use MCA Editor on Windows, Mac, and Linux?**
Yes. A single license covers all three platforms.

**What happens after the 14-day trial?**
MCA Editor will prompt you to enter a license key. Your scripts and
settings are preserved.

**Can I upgrade from Annual to Perpetual?**
Yes — email [info@mechart.org](mailto:info@mechart.org) and we'll work
it out.

**Do you offer studio or site licenses?**
Not yet through the store. Email [info@mechart.org](mailto:info@mechart.org)
for volume pricing.

**What Maya versions are supported?**
Maya 2024, 2025, and 2026 on Windows, macOS, and Linux.

**Will there be an Unreal Engine version?**
Yes — planned for a future release. Existing customers will receive a
discounted upgrade.

**I got a new computer. Can I transfer my license?**
Yes. Open **Help > Licensing > Manage Activations** to deactivate your
old machine and free up a slot.
```

---

### Update `mkdocs.yml` nav

Add Pricing between Home and Getting Started:

```yaml
nav:
  - Home: index.md
  - Pricing: pricing.md
  - Getting Started:
      - Installation: getting-started/installation.md
      - First Launch: getting-started/first-launch.md
  - Editor Guide:
      ...rest unchanged...
```

---

### Update `docs/index.md`

After the opening paragraph ("MCA Editor replaces Maya's built-in Script
Editor..."), add these two buttons:

```markdown
[Buy Now — $99](pricing.md){ .md-button .md-button--primary }
[Try Free for 14 Days](getting-started/installation.md){ .md-button }
```

At the bottom of the Features section, add:

```markdown
[See pricing and try free →](pricing.md)
```

---

## Part 2: License Server

### Directory structure (project root — standalone, not inside mca_core)

```
mca_license_server/
    app.py
    database.py
    crypto.py
    gumroad.py
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
    raw_key TEXT NOT NULL UNIQUE,
    gumroad_sale_id TEXT UNIQUE,
    gumroad_email TEXT,
    license_type TEXT NOT NULL DEFAULT 'perpetual',  -- 'perpetual' or 'annual'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoke_reason TEXT
);

-- Products a license key is entitled to use
-- One row per product per key
CREATE TABLE IF NOT EXISTS license_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL,
    product TEXT NOT NULL,           -- 'maya', 'unreal', 'blender', etc.
    machine_limit INTEGER NOT NULL DEFAULT 3,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    added_via_sale_id TEXT,          -- Gumroad sale that added this entitlement
    UNIQUE(key_hash, product),
    FOREIGN KEY(key_hash) REFERENCES license_keys(key_hash)
);

-- One row per activated machine per key per product
-- Maya and Unreal activations are tracked independently
CREATE TABLE IF NOT EXISTS activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL,
    product TEXT NOT NULL,           -- 'maya', 'unreal', 'blender', etc.
    machine_fingerprint TEXT NOT NULL,
    platform TEXT,                   -- 'windows', 'macos', 'linux'
    hostname TEXT,                   -- for support reference only
    mca_version TEXT,
    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deactivated INTEGER NOT NULL DEFAULT 0,
    deactivated_at TIMESTAMP,
    UNIQUE(key_hash, product, machine_fingerprint),
    FOREIGN KEY(key_hash) REFERENCES license_keys(key_hash)
);

-- Upgrade history (adding a new DCC to an existing key)
CREATE TABLE IF NOT EXISTS license_upgrades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL,
    product_added TEXT NOT NULL,
    gumroad_sale_id TEXT,
    upgraded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(key_hash) REFERENCES license_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_keys_hash ON license_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_keys_raw ON license_keys(raw_key);
CREATE INDEX IF NOT EXISTS idx_entitlements_key ON license_entitlements(key_hash);
CREATE INDEX IF NOT EXISTS idx_activations_key_product ON activations(key_hash, product);
```

---

### `mca_license_server/config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

SERVER_SECRET = os.environ.get("SERVER_SECRET", "")
GUMROAD_WEBHOOK_SECRET = os.environ.get("GUMROAD_WEBHOOK_SECRET", "")

# Gumroad product IDs — fill in after creating Gumroad products
# Leave blank for now; webhook logic uses these to route product types
GUMROAD_PRODUCTS = {
    os.environ.get("GUMROAD_PRODUCT_MAYA_PERPETUAL", ""): {
        "products": ["maya"],
        "license_type": "perpetual",
        "machine_limit": 3,
    },
    os.environ.get("GUMROAD_PRODUCT_MAYA_ANNUAL", ""): {
        "products": ["maya"],
        "license_type": "annual",
        "machine_limit": 3,
    },
    # Future products — add when ready:
    # os.environ.get("GUMROAD_PRODUCT_UNREAL_PERPETUAL", ""): {
    #     "products": ["unreal"],
    #     "license_type": "perpetual",
    #     "machine_limit": 3,
    # },
    # os.environ.get("GUMROAD_PRODUCT_BUNDLE_MAYA_UNREAL_PERPETUAL", ""): {
    #     "products": ["maya", "unreal"],
    #     "license_type": "perpetual",
    #     "machine_limit": 3,
    # },
    # os.environ.get("GUMROAD_PRODUCT_UPGRADE_ADD_UNREAL", ""): {
    #     "products": ["unreal"],
    #     "license_type": "upgrade",   # upgrade = add entitlement to existing key
    #     "machine_limit": 3,
    # },
}

DB_PATH = os.environ.get("DB_PATH", "mca_licenses.db")
TOKEN_EXPIRY_DAYS = 30
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
    conn.execute("PRAGMA foreign_keys = ON")
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
    email: str,
    license_type: str,
    products: list[str],
    machine_limit: int,
) -> bool:
    """
    Register a new license key from a Gumroad sale.
    Creates the key record and one entitlement row per product.
    Returns True if inserted, False if duplicate (Gumroad double-fires sometimes).
    """
    key_hash = hash_key(raw_key)
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO license_keys
                    (key_hash, raw_key, gumroad_sale_id, gumroad_email, license_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key_hash, raw_key.strip().upper(), sale_id, email, license_type),
            )
            for product in products:
                conn.execute(
                    """
                    INSERT INTO license_entitlements
                        (key_hash, product, machine_limit, added_via_sale_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key_hash, product, machine_limit, sale_id),
                )
        return True
    except sqlite3.IntegrityError:
        return False  # Duplicate


def add_entitlement(
    raw_key: str,
    product: str,
    machine_limit: int,
    sale_id: str,
) -> bool:
    """
    Add a new product entitlement to an existing key (upgrade purchase).
    Returns True if added, False if already exists.
    """
    key_hash = hash_key(raw_key)
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO license_entitlements
                    (key_hash, product, machine_limit, added_via_sale_id)
                VALUES (?, ?, ?, ?)
                """,
                (key_hash, product, machine_limit, sale_id),
            )
            conn.execute(
                """
                INSERT INTO license_upgrades
                    (key_hash, product_added, gumroad_sale_id)
                VALUES (?, ?, ?)
                """,
                (key_hash, product, sale_id),
            )
        return True
    except sqlite3.IntegrityError:
        return False  # Already has this entitlement


def get_key_info(raw_key: str) -> dict | None:
    """Returns key info + entitlements, or None if not found."""
    key_hash = hash_key(raw_key)
    with get_db() as conn:
        key_row = conn.execute(
            "SELECT * FROM license_keys WHERE key_hash = ?",
            (key_hash,)
        ).fetchone()
        if not key_row:
            return None

        entitlements = conn.execute(
            "SELECT product, machine_limit FROM license_entitlements WHERE key_hash = ?",
            (key_hash,)
        ).fetchall()

    return {
        "key_hash": key_hash,
        "license_type": key_row["license_type"],
        "revoked": bool(key_row["revoked"]),
        "entitlements": {
            row["product"]: row["machine_limit"]
            for row in entitlements
        },
    }


def count_active_machines(key_hash: str, product: str) -> int:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as count FROM activations
            WHERE key_hash = ? AND product = ? AND deactivated = 0
            """,
            (key_hash, product)
        ).fetchone()
    return row["count"]


def get_activation(
    key_hash: str, product: str, fingerprint: str
) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM activations
            WHERE key_hash = ? AND product = ? AND machine_fingerprint = ?
            """,
            (key_hash, product, fingerprint)
        ).fetchone()
    return dict(row) if row else None


def create_activation(
    key_hash: str,
    product: str,
    fingerprint: str,
    platform: str,
    hostname: str,
    mca_version: str,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO activations
                (key_hash, product, machine_fingerprint, platform,
                 hostname, mca_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key_hash, product, fingerprint, platform, hostname, mca_version),
        )


def update_last_seen(key_hash: str, product: str, fingerprint: str):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE activations SET last_seen = CURRENT_TIMESTAMP
            WHERE key_hash = ? AND product = ? AND machine_fingerprint = ?
            """,
            (key_hash, product, fingerprint),
        )


def deactivate_machine(
    key_hash: str, product: str, fingerprint: str
) -> bool:
    with get_db() as conn:
        result = conn.execute(
            """
            UPDATE activations
            SET deactivated = 1, deactivated_at = CURRENT_TIMESTAMP
            WHERE key_hash = ? AND product = ? AND machine_fingerprint = ?
              AND deactivated = 0
            """,
            (key_hash, product, fingerprint),
        )
    return result.rowcount > 0


def get_active_machines(key_hash: str, product: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT platform, hostname, activated_at, last_seen,
                   machine_fingerprint
            FROM activations
            WHERE key_hash = ? AND product = ? AND deactivated = 0
            ORDER BY activated_at ASC
            """,
            (key_hash, product)
        ).fetchall()
    return [dict(row) for row in rows]
```

---

### `mca_license_server/crypto.py`

```python
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from config import SERVER_SECRET, TOKEN_EXPIRY_DAYS


def sign_token(
    key_hash: str,
    machine_fingerprint: str,
    product: str,
    entitlements: list[str],
) -> tuple[str, datetime]:
    """
    Sign a JWT activation token. The editor verifies this locally
    without a network call on every launch.
    """
    expiry = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS)
    payload = {
        "kh": key_hash[:16],
        "mf": machine_fingerprint[:16],
        "pr": product,
        "en": entitlements,          # Full entitlement list for this key
        "exp": expiry,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, SERVER_SECRET, algorithm="HS256")
    return token, expiry


def verify_token(token: str) -> dict | None:
    """
    Verify and decode a token. Returns payload or None if invalid/expired.
    """
    try:
        return jwt.decode(token, SERVER_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def verify_gumroad_signature(secret: str, payload: bytes, signature: str) -> bool:
    if not secret:
        return True  # Dev mode — no secret configured yet
    expected = hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

### `mca_license_server/gumroad.py`

```python
"""
Gumroad webhook handler.
Determines what was purchased and routes to database appropriately.
"""
import logging
from database import register_key, add_entitlement, get_key_info, hash_key
from config import GUMROAD_PRODUCTS

logger = logging.getLogger(__name__)


def handle_sale(form_data: dict) -> tuple[bool, str]:
    """
    Process a Gumroad sale webhook.
    Returns (success, message).
    """
    sale_id = form_data.get("sale_id", "")
    product_id = form_data.get("product_id", "")
    license_key = form_data.get("license_key", "")
    email = form_data.get("email", "")
    # For upgrades: customer provides their existing key in custom field
    existing_key = form_data.get("existing_license_key", "").strip()

    if not license_key:
        return False, f"No license key in webhook for sale {sale_id}"

    product_config = GUMROAD_PRODUCTS.get(product_id)
    if not product_config:
        # Unknown product — store key anyway with maya default
        logger.warning(f"Unknown product_id {product_id} for sale {sale_id}")
        product_config = {
            "products": ["maya"],
            "license_type": "perpetual",
            "machine_limit": 3,
        }

    license_type = product_config["license_type"]
    products = product_config["products"]
    machine_limit = product_config["machine_limit"]

    # Upgrade purchase — add entitlement to existing key
    if license_type == "upgrade":
        if not existing_key:
            return False, f"Upgrade purchase {sale_id} missing existing_license_key"

        key_info = get_key_info(existing_key)
        if not key_info:
            return False, f"Upgrade purchase {sale_id}: existing key not found"

        existing_hash = hash_key(existing_key)
        for product in products:
            add_entitlement(existing_hash, product, machine_limit, sale_id)

        logger.info(
            f"Added {products} to existing key for sale {sale_id}"
        )
        return True, "upgrade_processed"

    # New purchase — register fresh key with entitlements
    inserted = register_key(
        raw_key=license_key,
        sale_id=sale_id,
        email=email,
        license_type=license_type,
        products=products,
        machine_limit=machine_limit,
    )

    if inserted:
        logger.info(
            f"Registered {products} {license_type} key for sale {sale_id}"
        )
    else:
        logger.info(f"Duplicate webhook for sale {sale_id} — ignored")

    return True, "ok"
```

---

### `mca_license_server/app.py`

```python
"""
MCA Editor License Server
Handles Gumroad webhooks and machine activation.
"""
import logging
from datetime import datetime, timezone

from flask import Flask, request, jsonify

from config import GUMROAD_WEBHOOK_SECRET
from crypto import sign_token, verify_gumroad_signature
from database import (
    init_db, get_key_info, hash_key,
    count_active_machines, get_activation,
    create_activation, update_last_seen,
    deactivate_machine, get_active_machines,
)
from gumroad import handle_sale

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
init_db()


def _error(message: str, status: str, code: int = 400):
    return jsonify({"status": status, "error": message}), code


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Gumroad webhook
# ---------------------------------------------------------------------------

@app.route("/gumroad/webhook", methods=["POST"])
def gumroad_webhook():
    signature = request.headers.get("X-Gumroad-Signature", "")
    if not verify_gumroad_signature(
        GUMROAD_WEBHOOK_SECRET, request.get_data(), signature
    ):
        logger.warning("Webhook signature verification failed")
        return _error("Invalid signature", "unauthorized", 401)

    data = request.form
    if data.get("test") == "true":
        return jsonify({"status": "test_skipped"}), 200

    success, message = handle_sale(dict(data))
    if not success:
        logger.error(message)
        return _error(message, "error", 400)

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

@app.route("/activate", methods=["POST"])
def activate():
    """
    Register a new machine against a license key for a specific product.
    """
    body = request.get_json(silent=True) or {}
    license_key = body.get("license_key", "").strip()
    fingerprint = body.get("machine_fingerprint", "").strip()
    product = body.get("product", "maya").strip()
    platform = body.get("platform", "")
    hostname = body.get("hostname", "")
    mca_version = body.get("mca_version", "")

    if not license_key or not fingerprint:
        return _error("Missing license_key or machine_fingerprint", "bad_request")

    key_info = get_key_info(license_key)
    if not key_info or key_info["revoked"]:
        return _error(
            "License key not found or has been revoked.",
            "invalid_key", 403
        )

    entitlements = key_info["entitlements"]
    if product not in entitlements:
        return _error(
            f"This license does not include {product}.",
            "not_entitled", 403
        )

    machine_limit = entitlements[product]
    key_hash = hash_key(license_key)

    # Already activated on this machine?
    existing = get_activation(key_hash, product, fingerprint)
    if existing and not existing["deactivated"]:
        update_last_seen(key_hash, product, fingerprint)
        token, expiry = sign_token(
            key_hash, fingerprint, product, list(entitlements.keys())
        )
        return jsonify({
            "status": "already_activated",
            "token": token,
            "token_expires": expiry.isoformat(),
            "machine_limit": machine_limit,
            "active_machines": count_active_machines(key_hash, product),
            "entitlements": list(entitlements.keys()),
        })

    # Check machine limit for this product
    active_count = count_active_machines(key_hash, product)
    if active_count >= machine_limit:
        return jsonify({
            "status": "limit_reached",
            "error": (
                f"This license has reached its activation limit "
                f"({machine_limit} machines for {product}). "
                f"Deactivate a machine first via Help > Licensing."
            ),
            "machine_limit": machine_limit,
            "active_machines": active_count,
        }), 403

    create_activation(key_hash, product, fingerprint, platform, hostname, mca_version)

    token, expiry = sign_token(
        key_hash, fingerprint, product, list(entitlements.keys())
    )
    return jsonify({
        "status": "activated",
        "token": token,
        "token_expires": expiry.isoformat(),
        "machine_limit": machine_limit,
        "active_machines": active_count + 1,
        "entitlements": list(entitlements.keys()),
    })


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

@app.route("/validate", methods=["POST"])
def validate():
    """
    Refresh an existing activation token. Called when token nears expiry.
    """
    body = request.get_json(silent=True) or {}
    license_key = body.get("license_key", "").strip()
    fingerprint = body.get("machine_fingerprint", "").strip()
    product = body.get("product", "maya").strip()
    mca_version = body.get("mca_version", "")

    if not license_key or not fingerprint:
        return _error("Missing required fields", "bad_request")

    key_info = get_key_info(license_key)
    if not key_info or key_info["revoked"]:
        return _error("License key not found or revoked.", "invalid_key", 403)

    key_hash = hash_key(license_key)
    existing = get_activation(key_hash, product, fingerprint)

    if not existing or existing["deactivated"]:
        return _error(
            "This machine is not activated for this product.",
            "not_activated", 403
        )

    update_last_seen(key_hash, product, fingerprint)

    entitlements = key_info["entitlements"]
    token, expiry = sign_token(
        key_hash, fingerprint, product, list(entitlements.keys())
    )
    return jsonify({
        "status": "valid",
        "token": token,
        "token_expires": expiry.isoformat(),
        "entitlements": list(entitlements.keys()),
    })


# ---------------------------------------------------------------------------
# Deactivate
# ---------------------------------------------------------------------------

@app.route("/deactivate", methods=["POST"])
def deactivate():
    """
    Free up a machine slot for a specific product.
    """
    body = request.get_json(silent=True) or {}
    license_key = body.get("license_key", "").strip()
    fingerprint = body.get("machine_fingerprint", "").strip()
    product = body.get("product", "maya").strip()

    if not license_key or not fingerprint:
        return _error("Missing required fields", "bad_request")

    key_hash = hash_key(license_key)
    success = deactivate_machine(key_hash, product, fingerprint)

    if not success:
        return _error("No active activation found for this machine.", "not_found", 404)

    return jsonify({
        "status": "deactivated",
        "active_machines": count_active_machines(key_hash, product),
    })


# ---------------------------------------------------------------------------
# List activations
# ---------------------------------------------------------------------------

@app.route("/activations", methods=["GET"])
def activations():
    """
    List active machines for a key + product.
    Used to populate Help > Licensing > Manage Activations.
    """
    license_key = request.args.get("license_key", "").strip()
    product = request.args.get("product", "maya").strip()
    fingerprint = request.args.get("fingerprint", "").strip()

    if not license_key:
        return _error("Missing license_key", "bad_request")

    key_info = get_key_info(license_key)
    if not key_info:
        return _error("License key not found.", "invalid_key", 403)

    key_hash = hash_key(license_key)
    entitlements = key_info["entitlements"]
    machine_limit = entitlements.get(product, 3)
    machines = get_active_machines(key_hash, product)

    return jsonify({
        "product": product,
        "machine_limit": machine_limit,
        "active_machines": len(machines),
        "entitlements": list(entitlements.keys()),
        "activations": [
            {
                "platform": m["platform"],
                "hostname": m["hostname"],
                "activated_at": m["activated_at"],
                "last_seen": m["last_seen"],
                "is_current": m["machine_fingerprint"] == fingerprint,
            }
            for m in machines
        ],
    })


# ---------------------------------------------------------------------------
# Support: manual key lookup
# ---------------------------------------------------------------------------

@app.route("/check", methods=["GET"])
def check_key():
    raw_key = request.args.get("key", "").strip()
    if not raw_key:
        return _error("No key provided", "bad_request")
    key_info = get_key_info(raw_key)
    if not key_info:
        return jsonify({"valid": False})
    return jsonify({
        "valid": not key_info["revoked"],
        "license_type": key_info["license_type"],
        "entitlements": list(key_info["entitlements"].keys()),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

---

### `mca_license_server/requirements.txt`

```
flask>=3.0.0
PyJWT>=2.8.0
python-dotenv>=1.0.0
gunicorn>=21.0.0
```

---

### `mca_license_server/.env.example`

```
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SERVER_SECRET=

# From Gumroad Settings > Advanced > Webhook secret
GUMROAD_WEBHOOK_SECRET=

# From Gumroad after creating products — fill in after setup
GUMROAD_PRODUCT_MAYA_PERPETUAL=
GUMROAD_PRODUCT_MAYA_ANNUAL=

# Database file path
DB_PATH=mca_licenses.db
```

---

### `mca_license_server/README.md`

```markdown
# MCA Editor License Server

Flask server handling Gumroad webhooks and machine activation.

## Setup

    pip install -r requirements.txt
    cp .env.example .env
    # Fill in .env values
    python app.py

## Production

    gunicorn -w 2 -b 127.0.0.1:5000 app:app

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Health check |
| POST | /gumroad/webhook | Gumroad purchase events |
| POST | /activate | Activate a machine |
| POST | /validate | Refresh activation token |
| POST | /deactivate | Free a machine slot |
| GET | /activations | List active machines |
| GET | /check?key= | Support key lookup |

## Seat Logic

Each product gets its own independent 3-seat pool.
A Maya + Unreal bundle gives 3 Maya seats AND 3 Unreal seats.
Seats are never shared across products.

## Adding Future Products

In config.py, uncomment the relevant GUMROAD_PRODUCTS entries
and set the corresponding env vars after creating Gumroad products.

## Upgrade Purchases

When a customer buys an upgrade (add Unreal to existing Maya key),
Gumroad's custom field must contain their existing license key.
The webhook reads this and adds the new entitlement to the existing key.
```

---

## Part 3: License Client (`mca_core/activation.py`)

This file is Cython-compiled (add to build pipeline). It handles all
licensing logic on the editor side.

```python
"""
mca_core/activation.py — License activation client.
Cython-compiled. Do not import at module level outside activate().
"""
import hashlib
import json
import os
import platform
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACTIVATION_SERVER = "https://api.mcaeditor.com"
TOKEN_REFRESH_THRESHOLD_DAYS = 5   # Refresh when this many days until expiry
OFFLINE_GRACE_DAYS = 14
TRIAL_DAYS = 14


# ---------------------------------------------------------------------------
# Platform utilities
# ---------------------------------------------------------------------------

def get_platform() -> str:
    return {
        "Windows": "windows",
        "Darwin": "macos",
        "Linux": "linux",
    }.get(platform.system(), "unknown")


def get_hardware_fingerprint() -> str:
    """
    Stable hardware fingerprint. Cross-platform.
    Hashed — raw hardware data never stored or transmitted.
    """
    components = [str(uuid.getnode()), socket.gethostname()]

    system = platform.system()
    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            components.append(guid)
        except Exception:
            pass
    elif system == "Darwin":
        try:
            import subprocess
            out = subprocess.run(
                ["system_profiler", "SPHardwareDataType"],
                capture_output=True, text=True, timeout=5
            ).stdout
            for line in out.splitlines():
                if "Hardware UUID" in line:
                    components.append(line.split(":")[-1].strip())
                    break
        except Exception:
            pass
    elif system == "Linux":
        for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            try:
                components.append(Path(path).read_text().strip())
                break
            except Exception:
                pass

    raw = "|".join(c for c in components if c)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_cache_path() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "MCAEditor"
    d.mkdir(parents=True, exist_ok=True)
    return d / "activation.json"


def _load_cache() -> dict:
    try:
        return json.loads(get_cache_path().read_text())
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        get_cache_path().write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _clear_cache():
    try:
        get_cache_path().unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Trial
# ---------------------------------------------------------------------------

def get_trial_status() -> dict:
    from mca_core.config.settings import get_setting, set_setting
    trial_start_str = get_setting("license/trial_start", default=None)
    if trial_start_str is None:
        trial_start = datetime.now(timezone.utc)
        set_setting("license/trial_start", trial_start.isoformat())
    else:
        try:
            trial_start = datetime.fromisoformat(trial_start_str)
            if trial_start.tzinfo is None:
                trial_start = trial_start.replace(tzinfo=timezone.utc)
        except Exception:
            trial_start = datetime.now(timezone.utc)

    days_used = (datetime.now(timezone.utc) - trial_start).days
    days_remaining = max(0, TRIAL_DAYS - days_used)
    return {
        "active": days_remaining > 0,
        "days_remaining": days_remaining,
        "expired": days_remaining == 0,
    }


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class ActivationResult:
    def __init__(self, success: bool, status: str, message: str = "",
                 entitlements: list = None):
        self.success = success
        self.status = status
        self.message = message
        self.entitlements = entitlements or []


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------

def activate(license_key: str, mca_version: str,
             product: str = "maya") -> ActivationResult:
    """
    Activate this machine. Called when the user enters their license key.
    """
    import requests as _requests

    fingerprint = get_hardware_fingerprint()
    try:
        resp = _requests.post(
            f"{ACTIVATION_SERVER}/activate",
            json={
                "license_key": license_key,
                "machine_fingerprint": fingerprint,
                "product": product,
                "platform": get_platform(),
                "hostname": socket.gethostname(),
                "mca_version": mca_version,
            },
            timeout=10,
        )
        data = resp.json()
        status = data.get("status")

        if status in ("activated", "already_activated"):
            _save_cache({
                "license_key": license_key,
                "token": data["token"],
                "token_expires": data["token_expires"],
                "last_validated": datetime.now(timezone.utc).isoformat(),
                "entitlements": data.get("entitlements", [product]),
            })
            return ActivationResult(
                True, status,
                entitlements=data.get("entitlements", [product])
            )

        return ActivationResult(
            False, status, data.get("error", "Unknown error")
        )

    except Exception as e:
        offline = "ConnectionError" in type(e).__name__
        return ActivationResult(
            False,
            "offline" if offline else "error",
            str(e),
        )


# ---------------------------------------------------------------------------
# Validate on launch
# ---------------------------------------------------------------------------

def validate_on_launch(mca_version: str,
                       product: str = "maya") -> ActivationResult:
    """
    Called every time the editor launches.
    Uses cached token when fresh. Phones home when near expiry.
    Allows offline use within grace period.
    """
    import requests as _requests

    cache = _load_cache()
    if not cache:
        return ActivationResult(False, "not_activated",
            "No license found. Enter your key in Help > Licensing.")

    license_key = cache.get("license_key", "")
    entitlements = cache.get("entitlements", [])
    token_expires_str = cache.get("token_expires", "")
    last_validated_str = cache.get("last_validated", "")

    # Check this machine is entitled to run this product
    if entitlements and product not in entitlements:
        return ActivationResult(False, "not_entitled",
            f"Your license does not include {product}. "
            f"Visit mcaeditor.com/pricing to add it.")

    try:
        token_expires = datetime.fromisoformat(
            token_expires_str.replace("Z", "+00:00")
        )
    except Exception:
        token_expires = datetime.now(timezone.utc) - timedelta(days=1)

    try:
        last_validated = datetime.fromisoformat(last_validated_str)
        if last_validated.tzinfo is None:
            last_validated = last_validated.replace(tzinfo=timezone.utc)
    except Exception:
        last_validated = datetime.now(timezone.utc) - timedelta(days=999)

    now = datetime.now(timezone.utc)
    days_until_expiry = (token_expires - now).days
    days_since_validated = (now - last_validated).days

    # Token still fresh — no network needed
    if days_until_expiry > TOKEN_REFRESH_THRESHOLD_DAYS:
        return ActivationResult(True, "valid", entitlements=entitlements)

    # Try to refresh
    fingerprint = get_hardware_fingerprint()
    try:
        resp = _requests.post(
            f"{ACTIVATION_SERVER}/validate",
            json={
                "license_key": license_key,
                "machine_fingerprint": fingerprint,
                "product": product,
                "mca_version": mca_version,
            },
            timeout=8,
        )
        data = resp.json()
        if data.get("status") == "valid":
            updated_entitlements = data.get("entitlements", entitlements)
            _save_cache({
                **cache,
                "token": data["token"],
                "token_expires": data["token_expires"],
                "last_validated": now.isoformat(),
                "entitlements": updated_entitlements,
            })
            return ActivationResult(
                True, "valid", entitlements=updated_entitlements
            )
        elif data.get("status") == "not_activated":
            _clear_cache()
            return ActivationResult(False, "not_activated",
                "This machine is no longer activated. "
                "Re-enter your key in Help > Licensing.")
    except Exception:
        pass  # Fall through to offline logic

    # Offline fallback
    if days_since_validated <= OFFLINE_GRACE_DAYS:
        remaining = OFFLINE_GRACE_DAYS - days_since_validated
        return ActivationResult(
            True, "offline",
            f"Could not reach activation server. "
            f"Offline grace period: {remaining} days remaining.",
            entitlements=entitlements,
        )

    return ActivationResult(False, "expired",
        f"License validation has been offline for over {OFFLINE_GRACE_DAYS} days. "
        f"Connect to the internet to revalidate.")


# ---------------------------------------------------------------------------
# Deactivate
# ---------------------------------------------------------------------------

def deactivate(product: str = "maya") -> ActivationResult:
    """
    Deactivate this machine, freeing a seat slot.
    Called from Help > Licensing > Deactivate this machine.
    """
    import requests as _requests

    cache = _load_cache()
    if not cache:
        return ActivationResult(False, "not_activated", "No license found.")

    license_key = cache.get("license_key", "")
    fingerprint = get_hardware_fingerprint()

    try:
        resp = _requests.post(
            f"{ACTIVATION_SERVER}/deactivate",
            json={
                "license_key": license_key,
                "machine_fingerprint": fingerprint,
                "product": product,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "deactivated":
            _clear_cache()
            return ActivationResult(True, "deactivated")
        return ActivationResult(
            False, "error", data.get("error", "Unknown error")
        )
    except Exception as e:
        return ActivationResult(False, "offline", str(e))


# ---------------------------------------------------------------------------
# Get activations (for Manage Activations dialog)
# ---------------------------------------------------------------------------

def get_activations(product: str = "maya") -> dict | None:
    import requests as _requests

    cache = _load_cache()
    if not cache:
        return None

    license_key = cache.get("license_key", "")
    fingerprint = get_hardware_fingerprint()

    try:
        resp = _requests.get(
            f"{ACTIVATION_SERVER}/activations",
            params={
                "license_key": license_key,
                "product": product,
                "fingerprint": fingerprint,
            },
            timeout=10,
        )
        return resp.json()
    except Exception:
        return None
```

---

## Part 4: Wire Into `plugin_main.py`

Add to `initializePlugin()` after existing init code:

```python
from mca_core.platform_utils import is_batch_mode
from mca_core.activation import validate_on_launch, get_trial_status
from mca_core import VERSION

def initializePlugin(obj):
    # Skip all UI and licensing in headless/render farm mode
    if is_batch_mode():
        _register_commands(obj)
        return

    # ... existing plugin init code ...

    # License check — runs after UI is ready
    import maya.utils
    maya.utils.executeDeferred(_check_license)


def _check_license():
    from mca_core.activation import validate_on_launch, get_trial_status
    from mca_core import VERSION

    result = validate_on_launch(VERSION, product="maya")

    if result.success:
        return  # Licensed or within offline grace period — nothing to show

    if result.status in ("not_activated", "not_entitled"):
        trial = get_trial_status()
        if trial["active"]:
            # In trial — show non-blocking reminder after N days
            if trial["days_remaining"] <= 3:
                _show_trial_expiry_warning(trial["days_remaining"])
            return
        # Trial expired and no license
        _show_licensing_dialog()

    elif result.status == "expired":
        _show_revalidation_required_dialog(result.message)
```

---

## Part 5: Build Pipeline Updates

In `build_maya.py`:

```python
# Add to CYTHON_MODULES (compiled for protection):
"mca_core/activation.py",

# Add to DIST_PURE_PYTHON (NOT compiled — needed for path debugging):
"mca_core/platform_utils.py",
```

---

## Important Notes

1. **GUMROAD_PERPETUAL_URL and GUMROAD_ANNUAL_URL** in `pricing.md` are
   placeholders. Leave them exactly as written — Nathan fills these in
   after creating Gumroad products.

2. `mca_license_server/` lives at the **project root** — it is a standalone
   server, not part of the Maya plugin packages.

3. After generating the docs site, run `mkdocs build` and upload the
   updated `site/` folder to Hostinger.

4. Show a complete diff summary of every file created or modified
   before finishing. Do not touch anything not listed in this spec.
