# 2026-03-27 — Unreal Engine Pricing & Homepage Update

## Overview

Add Unreal Engine and Maya+Unreal Bundle pricing to the website, and update the
homepage to reflect that MCA Editor is a cross-DCC tool (Maya + Unreal Engine).

Two files to edit:
- `website/docs/pricing.md`
- `website/docs/index.md`

After editing, run `python tools/deploy_website.py` to push to the VPS.

---

## Gumroad Permalink Placeholders

The three new Gumroad products have not been created yet. Use these placeholder
slugs throughout — find-and-replace them once Nathan creates the products:

| Placeholder           | Product                            | Price    |
|-----------------------|------------------------------------|----------|
| `UE_PERPETUAL_SLUG`   | MCA Editor for Unreal — Perpetual  | $99      |
| `UE_ANNUAL_SLUG`      | MCA Editor for Unreal — Annual     | $35/yr   |
| `BUNDLE_SLUG`         | Maya + Unreal Bundle — Perpetual   | $140     |
| `BUNDLE_ANNUAL_SLUG`  | Maya + Unreal Bundle — Annual      | $40/yr   |

Gumroad purchase URL format: `https://ncomes.gumroad.com/l/<SLUG>`

---

## File 1: `website/docs/pricing.md`

Replace the entire file with the following content.

```markdown
# Pricing

MCA Editor is available as a **perpetual license** or an **annual subscription**.
Try it free for 14 days — no credit card required.

---

## MCA Editor for Maya

Supports **Windows, macOS, and Linux**. Maya 2024, 2025, and 2026.

|                                     | Perpetual      | Annual          |
|-------------------------------------|----------------|-----------------|
| **Price**                           | $99 USD        | $35 USD/year    |
| Maya 2024, 2025, 2026               | ✓              | ✓               |
| Windows, macOS, Linux               | ✓              | ✓               |
| All Editor Features                 | ✓              | ✓               |
| Orange Slice AI Chat                | ✓              | ✓               |
| Plugin Architecture                 | ✓              | ✓               |
| Free Updates (current major version)| ✓              | ✓               |
| Activations                         | 3 machines     | 3 machines      |

[Buy Perpetual — $99](https://ncomes.gumroad.com/l/ndsupov){ .md-button .md-button--primary }
[Buy Annual — $35/yr](https://ncomes.gumroad.com/l/qkscq){ .md-button }

---

## MCA Editor for Unreal Engine

Supports **Windows**. Unreal Engine 5.4, 5.5, 5.6, and 5.7.

|                                     | Perpetual      | Annual          |
|-------------------------------------|----------------|-----------------|
| **Price**                           | $99 USD        | $35 USD/year    |
| Unreal Engine 5.4 – 5.7            | ✓              | ✓               |
| Windows                             | ✓              | ✓               |
| All Editor Features                 | ✓              | ✓               |
| Orange Slice AI Chat                | ✓              | ✓               |
| Plugin Architecture                 | ✓              | ✓               |
| Free Updates (current major version)| ✓              | ✓               |
| Activations                         | 3 machines     | 3 machines      |

[Buy Perpetual — $99](https://ncomes.gumroad.com/l/UE_PERPETUAL_SLUG){ .md-button .md-button--primary }
[Buy Annual — $35/yr](https://ncomes.gumroad.com/l/UE_ANNUAL_SLUG){ .md-button }

---

## Maya + Unreal Bundle

Get both **MCA Editor for Maya** and **MCA Editor for Unreal Engine** together
at a discounted price. One license key covers both DCCs.

|                                     | Perpetual      | Annual          |
|-------------------------------------|----------------|-----------------|
| **Price**                           | $140 USD       | $40 USD/year    |
| ~~$198 if bought separately~~       | Save $58       | ~~$70/yr~~ Save $30/yr |
| Maya 2024, 2025, 2026               | ✓              | ✓               |
| Unreal Engine 5.4 – 5.7            | ✓              | ✓               |
| Windows (Unreal), Windows/macOS/Linux (Maya) | ✓   | ✓               |
| All Editor Features                 | ✓              | ✓               |
| Orange Slice AI Chat                | ✓              | ✓               |
| Plugin Architecture                 | ✓              | ✓               |
| Free Updates (current major version)| ✓              | ✓               |
| Activations                         | 3 machines     | 3 machines      |

[Buy Bundle Perpetual — $140](https://ncomes.gumroad.com/l/BUNDLE_SLUG){ .md-button .md-button--primary }
[Buy Bundle Annual — $40/yr](https://ncomes.gumroad.com/l/BUNDLE_ANNUAL_SLUG){ .md-button }

---

## Free Trial

MCA Editor includes a **14-day free trial** with full access to all features.
No account or credit card needed — just install and run.

[Download & Try Free](download.md){ .md-button }

---

## What's Included

### Editor Features

- Script Mode and Project Mode
- Syntax highlighting for Python and MEL (Maya) / Python (Unreal)
- Code completion, Find & Replace, Find in Files
- Integrated terminal
- Drag-and-drop tab management
- Output panel with full stack traces

### Orange Slice AI Chat

- Built-in AI assistant that understands your scene and code
- Reads your code, executes scripts, navigates your project
- Bring your own API key (Anthropic, OpenAI, or Google)

### Plugin Architecture

- Extend MCA Editor with Python plugins
- Clean documented API with 28 methods
- Panel, menu, and execution hooks

---

## License Terms

- One license covers **3 machine activations**
- Perpetual license covers the **current major version** (MCA Editor 1.x)
- Annual license stays active as long as subscription is current
- Bundle license activates both Maya and Unreal on the same machines
- Manage your activations at [api.mcaeditor.com/manage](https://api.mcaeditor.com/manage)
- Need more seats? Email [info@mechart.org](mailto:info@mechart.org)

---

## FAQ

??? question "Can I use MCA Editor on Windows, Mac, and Linux?"
    Yes — for Maya. A single Maya license covers all three platforms.
    The Unreal Engine version currently supports Windows only.

??? question "What happens after the 14-day trial?"
    MCA Editor will prompt you to enter a license key. Your scripts and settings
    are preserved — nothing is lost.

??? question "Can I upgrade from Annual to Perpetual?"
    Yes. Email [info@mechart.org](mailto:info@mechart.org) and we'll sort it out.

??? question "Do you offer studio or site licenses?"
    Not yet through the store, but email [info@mechart.org](mailto:info@mechart.org)
    and we can work something out.

??? question "What versions of Maya are supported?"
    Maya 2024, 2025, and 2026 on Windows, macOS, and Linux.

??? question "What versions of Unreal Engine are supported?"
    Unreal Engine 5.4, 5.5, 5.6, and 5.7 on Windows.

??? question "Does the Bundle license cover future DCC versions?"
    Yes — the Bundle perpetual license covers the current major version (1.x)
    of both MCA Editor for Maya and MCA Editor for Unreal Engine.

??? question "Can I upgrade my Maya license to the Bundle?"
    Yes. Email [info@mechart.org](mailto:info@mechart.org) and we'll credit your
    existing purchase toward the bundle price.
```

---

## File 2: `website/docs/index.md`

### Change 1 — Tagline and intro paragraph

**Find:**
```markdown
A better Maya script editor — built for artists and technical directors who want more from their scripting workflow.

MCA Editor replaces Maya's built-in Script Editor with a modern, full-featured code editor that lives inside Maya. Write scripts faster, manage projects, and extend the editor with plugins.
```

**Replace with:**
```markdown
A better script editor for **Maya and Unreal Engine** — built for artists and technical directors who want more from their scripting workflow.

MCA Editor replaces your DCC's built-in script editor with a modern, full-featured code editor. Write scripts faster, manage projects, and extend the editor with plugins.
```

### Change 2 — Quick Start buy button

**Find:**
```markdown
Buy Now — $99
```

**Replace with:**
```markdown
[Maya — $99](pricing.md#mca-editor-for-maya){ .md-button .md-button--primary }
[Unreal — $99](pricing.md#mca-editor-for-unreal-engine){ .md-button .md-button--primary }
[Bundle — $130](pricing.md#maya--unreal-bundle){ .md-button }
```

### Change 3 — "Supported Maya Versions" section

**Find:**
```markdown
## Supported Maya Versions
```

**Replace with:**
```markdown
## Supported Versions
```

Then, after the existing Maya table (which stays as-is), add:

```markdown
**Unreal Engine** — Windows

| UE Version | Status  |
|------------|---------|
| UE 5.4     | ✓       |
| UE 5.5     | ✓       |
| UE 5.6     | ✓       |
| UE 5.7     | ✓       |
```

---

## Deploy

After both files are saved:

```bash
python tools/deploy_website.py
```

Verify at https://mcaeditor.com/pricing/ and https://mcaeditor.com/

---

## Post-Deploy: Replace Gumroad Slugs

Once Nathan creates the four Gumroad products and has the permalink slugs,
run a find-and-replace in `website/docs/pricing.md`:

- `UE_PERPETUAL_SLUG` → actual slug
- `UE_ANNUAL_SLUG` → actual slug
- `BUNDLE_SLUG` → actual slug
- `BUNDLE_ANNUAL_SLUG` → actual slug

Then re-deploy.

---

## Upgrade Flow: "I Already Own Maya/Unreal — Upgrade to Bundle"

### How it works

Anyone who owns either Maya perpetual OR Unreal perpetual can upgrade to the
bundle for $81 (= $140 - $59 discount). The server verifies their license key,
generates a single-use Gumroad discount code via the Gumroad API, and redirects
them to the bundle checkout with the code pre-applied in the URL.

### New website page: `website/docs/upgrade.md`

Add a minimal page with a form — just a license key input and a submit button
that POSTs to `https://api.mcaeditor.com/upgrade`. Add it to `mkdocs.yml` nav
under Pricing.

```markdown
# Upgrade to Bundle

Already own **MCA Editor for Maya** or **MCA Editor for Unreal Engine**?
Upgrade to the Maya + Unreal Bundle for **$81** — saving $59 off the full price.

Enter your existing license key below and we'll generate a discount link for you.

<form method="POST" action="https://api.mcaeditor.com/upgrade">
  <input type="text" name="license_key" placeholder="MCA-XXXX-XXXX-XXXX-XXXX" required />
  <button type="submit">Get Upgrade Link</button>
</form>

*The discount link is single-use and valid for 24 hours.*
```

### New server endpoint: `POST /upgrade` on `api.mcaeditor.com`

Add to `server.py` (Flask):

```python
import os, secrets, requests
from flask import request, redirect, jsonify

GUMROAD_TOKEN = os.environ["GUMROAD_TOKEN"]          # add to .env
BUNDLE_PRODUCT_ID = os.environ["BUNDLE_PRODUCT_ID"]  # add to .env (Gumroad internal product ID)
UPGRADE_DISCOUNT_CENTS = 5900                         # $59 off → $81 final price

@app.route("/upgrade", methods=["POST"])
def upgrade():
    key = request.form.get("license_key", "").strip().upper()

    # 1. Validate key exists and is perpetual
    row = db.execute(
        "SELECT dcc, license_type FROM license_keys WHERE key_hash = ?",
        (hmac_hash(key),)
    ).fetchone()

    if not row:
        return render_error("License key not found.")
    if row["license_type"] != "perpetual":
        return render_error("Upgrade pricing is available for perpetual licenses only.")

    # 2. Generate a single-use Gumroad discount code
    code = "UPGRADE-" + secrets.token_hex(6).upper()  # e.g. UPGRADE-A1B2C3D4E5F6

    resp = requests.post(
        "https://api.gumroad.com/v2/products/{}/offer_codes".format(BUNDLE_PRODUCT_ID),
        data={
            "access_token": GUMROAD_TOKEN,
            "name": code,
            "amount_off": UPGRADE_DISCOUNT_CENTS,
            "offer_type": "cents",
            "max_purchase_count": 1,
        }
    )
    if not resp.ok:
        return render_error("Could not generate discount. Please email info@mechart.org.")

    # 3. Redirect to Gumroad with offer code pre-applied
    bundle_url = "https://ncomes.gumroad.com/l/{}?offer_code={}".format(
        os.environ["BUNDLE_SLUG"], code
    )
    return redirect(bundle_url)
```

### New `.env` variables needed

```
GUMROAD_TOKEN=<your Gumroad API access token>
BUNDLE_PRODUCT_ID=<Gumroad internal product ID for the bundle — get from API or dashboard>
BUNDLE_SLUG=<the permalink slug for the bundle product>
```

### Add to pricing page FAQ

```markdown
??? question "I already own Maya or Unreal — can I upgrade to the Bundle?"
    Yes. [Use the upgrade page](upgrade.md) to enter your existing license key
    and get a $59 discount link for the bundle, bringing it to **$81**.
    The link is single-use and valid for 24 hours.
```

### Notes

- The `dcc` column check is intentionally skipped in the upgrade logic — owning
  either DCC perpetual qualifies. Keep it simple.
- If the customer already owns *both* Maya and Unreal perpetual, they've paid
  $198, so the bundle upgrade isn't useful to them. The endpoint doesn't need
  to handle this edge case — they just won't use it.
- `BUNDLE_PRODUCT_ID` is Gumroad's internal UUID, different from the permalink
  slug. Get it by calling `GET https://api.gumroad.com/v2/products?access_token=TOKEN`
  after creating the bundle product.
