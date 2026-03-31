# Session Notes — 2026-03-30: Website Updates, File Tree Fix, Full Rebuild

## Summary

Added Vimeo install video to website, expanded Project Mode documentation, fixed
duplicate project roots in sidebar file tree, and rebuilt all platforms.

---

## Website Changes

### Vimeo Video Embed (Installation Page)
- Added responsive Vimeo embed under the Maya header on the Getting Started > Installation page
- Video ID: `1178681539` (Maya intro/install walkthrough)
- Known issue: thin white vertical line on left edge of video — comes from inside the Vimeo player iframe (cross-origin, can't fix with CSS). May switch to YouTube embed later.
- Removed `<script>` tag (Python-Markdown strips it); iframe works without it
- Added `.video-embed` CSS class in `custom.css` with `border:none !important` etc.

### Project Mode Documentation
- Added screenshots: StartProjectClose.png, SideBar.png, QuickFind.png, FindInFiles.png
- Expanded Project Settings section with tables for General settings and Profile settings
- Added **Project Lifecycle** section documenting Open/Close/Refresh behavior:
  - Open: path injection → env vars → terminal cwd → startup script → startup code
  - Close: shutdown script → shutdown code → env var restore → path removal → UI reset
  - Refresh: mini close/open cycle, re-reads `.mca-project` from disk
- Added **Startup and Shutdown Scripts** section with:
  - Common use cases for each
  - Maya shelf creation/removal examples
  - Tips on execution order and what's available during script execution

### Other Website Changes
- Removed Linux references from pricing, terminal docs, and installation page
  (MCA Editor supports Windows and macOS only)

---

## File Tree Fix — Duplicate Project Roots

### Problem
When opening a project, the sidebar file tree showed files from two different
projects (e.g., both "Wayward" and "MCA" packages). Only one project was open.

### Root Cause
`sidebar.py:restore_tree_state_from_settings()` merged saved workspace folders
from QSettings into the current workspace without checking whether they belonged
to the active project. Stale folder entries from previously opened projects were
added alongside the current project root.

### Fix
Added a guard in `restore_tree_state_from_settings()` (line ~1098): when a
`project_root` is provided, skip any saved folder whose normalized path doesn't
start with the project root. This ensures only folders inside the active project
are restored.

**File changed:** `mca_qt/widgets/sidebar.py`

---

## Builds

### Windows (built locally)
- Maya 2024, 2025, 2026 — v1.0.6
- UE 5.5, 5.6, 5.7 — v1.0.6 (sidebar fix is in shared `mca_qt` layer)

### macOS (built on Mac Mini via SSH)
- Maya 2024, 2025, 2026 — v1.0.6
- Mac Mini repo was missing `.git` — cloned fresh using `id_ed25519_github` key
- README warning in Mac builds is cosmetic (hardcoded Google Drive path doesn't exist on Mac)

### Deployment
- All Windows and macOS zips uploaded to VPS via `deploy_website.py`
- Website rebuilt and deployed to mcaeditor.com

---

## Mac Mini Notes
- IP: 192.168.68.72 (must be on same WiFi network)
- SSH key for GitHub: `~/.ssh/id_ed25519_github` (not the default `id_ed25519`)
- Repo freshly cloned to `~/Projects/MCAEditor` (old non-git copy moved to `MCAEditor_old`)
