# Session Notes — 2026-03-31

## EventGraph C++ Bridge (PyUnreal Milestone 1.5)

### Summary
Compiled and tested the EventGraph C++ library (`MCAEventGraphLibrary`) that was
written in a previous session. Built the UE 5.6 plugin via `build_unreal.py`,
deployed to the Wayward project, and ran the integration test suite in UE.

### Key Details
- **Build**: `build_unreal.py --ue-version 5.6` — full RunUAT + Cython pipeline
- **Deploy**: Replaced `MCAEditor-UE5.6-v1.0.5` with `MCAEditor-UE5.6-v1.0.7`
  in `E:\Rascal\depot\Wayward\Plugins\`
- **Test**: `tools/test_event_graph.py` — **14/14 passed**
  - AddEventNode (BlueprintInitializeAnimation, BlueprintUpdateAnimation)
  - AddFunctionCallNode (TryGetPawnOwner pure, PrintString non-pure)
  - GetNodePins — returns pin name, direction, type
  - ConnectPins — exec pin wiring between event and function nodes
  - SetNodePosition — graph layout
  - ListEventGraphNodes — introspection
  - AnimBP compiles cleanly after all edits

### Test Script Fixes
- `isinstance(nodes, list)` failed because UE Python returns `Array` — changed to `len(nodes) >= 0`
- `TryGetPawnOwner` is a pure function with no exec pins — switched ConnectPins
  test to use `PrintString` (non-pure, has exec input/output)

### Skeleton Path
- Default mannequin paths don't exist in Wayward project
- Used `/Game/ThirdParty/GBWContent/Character/AAToolsCharacter/UE5Mannequins/Meshes/SKM_Manny`

---

## PyUnreal Documentation Site (Milestone 5)

### Summary
Built and deployed a MkDocs Material documentation site for PyUnreal at
https://mcaeditor.com/docs/pyunreal/. Matches the main MCA Editor site styling.

### What Was Done
- Created `mkdocs.yml` in PyUnreal repo with Material theme (dark slate, blue header)
- Added `overrides/main.html` with Umami analytics tracking
- Added `docs/assets/stylesheets/custom.css` matching MCA Editor's color scheme
- Built with `mkdocs build`, deployed via SCP to VPS
- Cleaned stale files from previous manual deployment

### Site Structure
- **Home**: Overview, installation, two-tier architecture explanation
- **Guides** (4): Getting Started, AnimBP Cookbook, Blueprint Cookbook, Control Rig Cookbook
- **API Reference** (18 pages): AnimBlueprint, StateMachine, State, Transition,
  EventGraph, Blueprint, Component, Variable, ControlRig, Control, Bone, Null,
  Material, Actor, scene, viewport, load, errors

---

## SEO & Discoverability

### robots.txt
- Added to both sites (main + PyUnreal)
- Points to both sitemaps
- Deployed and verified accessible

### Open Graph & Twitter Card Meta Tags
- Added `overrides/main.html` templates with OG tags on both sites
- Per-page `description` frontmatter on 12 key pages:
  - PyUnreal: index, getting-started, AnimBlueprint, EventGraph, Blueprint,
    ControlRig, Material, Actor, scene, animbp-cookbook, blueprint-cookbook,
    control-rig-cookbook
  - MCA Editor: index, download, installation
- Tags: `og:type`, `og:site_name`, `og:description`, `og:url`, `og:title`,
  `twitter:card`, `twitter:title`, `twitter:description`

### Google Search Console
- Domain property verified via DNS TXT record
- Record: `google-site-verification=vQLYxYq8fOgilp65v5lRn_BkCKtO76Jvr6M4Vfu`
- Main sitemap submitted — 24 pages discovered (Success)
- PyUnreal sitemap submitted — pages discovered (Success)

### Social Plugin
- Tried `mkdocs-material[imaging]` social plugin for auto-generated OG images
- Requires `cairosvg` native dependency — removed in favor of template-based OG tags
- Simpler, no native deps, works fine for text-only social previews

---

## Files Changed

### MCA Editor Repo
- `Docs/PYUNREAL_PLAN.md` — Milestone 1.5 and 5 marked COMPLETE
- `tools/test_event_graph.py` — Fixed isinstance check and ConnectPins test
- `website/docs/robots.txt` — New, allows all bots + sitemap pointers
- `website/docs/index.md` — Added OG meta description frontmatter
- `website/docs/download.md` — Added OG meta description frontmatter
- `website/docs/getting-started/installation.md` — Added OG meta description
- `website/overrides/main.html` — Added OG + Twitter Card meta tags
- `mkdocs.yml` — Added search plugin

### PyUnreal Repo
- `mkdocs.yml` — New, full MkDocs Material config
- `overrides/main.html` — New, analytics + OG + Twitter Card tags
- `docs/assets/stylesheets/custom.css` — New, matches MCA Editor blue theme
- `docs/assets/images/pyunreal-logo.png` — Copied from MCA logo
- `docs/robots.txt` — New
- `docs/index.md` — Added meta description frontmatter
- `docs/guides/*.md` — Added meta descriptions (4 files)
- `docs/api/*.md` — Added meta descriptions (6 key files)

---

## Custom Analytics Dashboard

### Problem
Umami 3.0.3 Events detail page (Chart, Activity, Properties tabs) all show
"Something went wrong". The event data is correctly stored in PostgreSQL —
verified via direct DB queries — but the Umami UI fails to render it.

### Solution
Built a custom analytics dashboard that queries the Umami PostgreSQL database
directly, bypassing the broken Umami UI entirely.

### Implementation
- **Script**: `tools/analytics_dashboard.py` — Python HTTP server using psycopg2
- **Deployed**: `/home/mca/analytics-dashboard/app.py` on VPS
- **Service**: `mca-analytics.service` (systemd, auto-restart, port 3001)
- **URL**: https://analytics.mcaeditor.com/downloads
- **Nginx**: Added `location /downloads` proxy block to umami site config

### Dashboard Shows
- Summary cards: Total Downloads, Downloads Today, Page Views, Unique Visitors
- Download log table: date, product, platform, filename (every download click)
- Top Pages (by view count)
- Top Referrers (by visit count)
- Dark theme matching MCA Editor branding (#1a1a2e background, #E8922A highlights)
- `noindex, nofollow` meta tag — private, not indexed by search engines
- Live data on every page load (no caching)

### VPS Infrastructure
- `python3-psycopg2` installed via apt on VPS (Ubuntu 24.04)
- DB connection to Umami PostgreSQL container at `172.18.0.2:5432`
- Note: DB IP may change if Docker containers are recreated — would need to
  update `DB_HOST` in app.py if that happens
