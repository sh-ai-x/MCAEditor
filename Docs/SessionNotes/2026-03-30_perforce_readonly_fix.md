# 2026-03-30 — Perforce Read-Only Fix & Full Rebuild

## Summary
Fixed file save failures on Perforce-managed (read-only) files, version bumped to v1.0.6, rebuilt and deployed all editors across all platforms.

---

## Problem
When files are managed by Perforce, they are marked read-only on disk. The editor's `_write_file()` method called `open(filepath, "w")` directly, which throws `PermissionError` on read-only files. This blocked:
- Manual save (Ctrl+S)
- Auto-save on execute
- Save on close (cleanup)

Users had to manually unlock files before saving or executing.

## Fix
Added `os.chmod(filepath, stat.S_IWRITE | stat.S_IREAD)` before writing when `os.access(filepath, os.W_OK)` returns False. Applied to three save paths:

| File | Method | Save Path |
|------|--------|-----------|
| `mca_qt/editor_panel.py` | `_write_file()` | Explicit save + save-on-execute |
| `mca_qt/editor_panel.py` | `cleanup()` | Save-on-close |
| `mca_editor/ui/main_window.py` | `_write_file()` | Standalone editor save |

Added `import stat` to both files.

## Version Bump
`mca_core/__init__.py`: 1.0.5 -> 1.0.6

## Builds Completed

### Windows (built locally)
| Target | Files | Size | Status |
|--------|-------|------|--------|
| Maya 2024 | 132 | 4.7 MB | Deployed to `Documents/maya/2024/plug-ins/` |
| Maya 2025 | 132 | 4.9 MB | Deployed to `Documents/maya/2025/plug-ins/` |
| Maya 2026 | 132 | 4.9 MB | Deployed to `Documents/maya/2026/plug-ins/` |
| UE 5.5 | 146 | 5.1 MB | `--skip-cpp` (Python only) |
| UE 5.6 | 146 | 5.1 MB | `--skip-cpp` (Python only) |
| UE 5.7 | 146 | 5.1 MB | `--skip-cpp` (Python only) |

### macOS (built on Mac Mini, rebuilt by Mac Claude after regression fix)
| Target | Files | Size | Status |
|--------|-------|------|--------|
| Maya 2024 | 132 | 7.8 MB | Deployed to `~/Library/.../maya/2024/plug-ins/` |
| Maya 2025 | 132 | 7.9 MB | Deployed to `~/Library/.../maya/2025/plug-ins/` |
| Maya 2026 | 132 | 7.9 MB | Deployed to `~/Library/.../maya/2026/plug-ins/` |

## Mac SCP Regression
Initial Mac builds were done via SCP of source files, which created nested duplicate directories (`mca_maya/mca_maya/`, etc.) inflating Mac zips to 20MB. Cleaned up and rebuilt correctly. Additionally, Mac Claude identified that the SCP overwrote cross-platform terminal fixes — see `2026-03-30_mac_rebuild_pywinpty_regression.md` for details.

**Lesson learned:** Always `git pull` on the Mac instead of SCP to avoid overwriting platform-specific fixes and creating nested directories.

## Website Deployment
- All 9 download zips (6 Maya + 3 UE) uploaded to mcaeditor.com
- `releases.json` updated with v1.0.6 entry
- CHANGELOG.md updated with v1.0.6 entry
- Site rebuilt and deployed via `tools/deploy_website.py`
