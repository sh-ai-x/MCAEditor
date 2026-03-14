# Session Notes — 2026-03-13: First-Launch Splash Screen

## Summary
Replaced the plain `QProgressDialog` shown during first-launch plugin
initialization with a branded Orange Slice splash screen featuring the
animated mascot GIF, status updates, and rotating orange puns.

## Changes

### New File: `mca_maya/splash_progress.py`
- Frameless dark card with orange border, centered on Maya's main window
- "MCA Editor Setup" title in orange branding
- Status label showing current setup step (white text)
- `Logo_InAndOut.gif` mascot animating at 180px
- Orange separator line between mascot and joke area
- 35 shuffled orange-themed puns rotating every 3.5 seconds
- Functional API (no Qt virtual overrides) — compiles to `.pyd` cleanly
- Uses `mca_core._package_root` for GIF path resolution (same as chat_widget)
- Tries shiboken6 first, falls back to shiboken2 (fixes Maya 2025+ compat)

### Threaded Setup (`run_with_splash`)
- All blocking work (venv creation, pip install, git clone, MCP registration)
  runs on a `threading.Thread` background thread
- Main thread stays in a ~60fps polling loop: drains status messages from a
  `queue.Queue`, rotates jokes on a timer, calls `processEvents()` for smooth
  GIF animation
- Previous approach called `processEvents()` only between subprocess calls,
  causing the GIF to freeze for seconds at a time

### Modified: `mca_maya/plugin_main.py`
- `_first_launch_setup()` now imports and calls `run_with_splash()` with a
  `_do_setup()` worker function instead of manually creating a `QProgressDialog`
- Removed inline PySide6/PySide2 imports and shiboken2-only code (moved to
  splash_progress.py with proper shiboken6/2 fallback)

## Testing
- Built and deployed all three Maya versions (2024, 2025, 2026)
- Reset Maya 2024 and 2025 (removed .venv, extraction cache, MCP servers)
- Tested first-launch flow — splash animates smoothly throughout setup
- Previewed standalone via PySide6 `QApplication` outside Maya

## Mac Build Discussion
- Cython produces platform-native binaries (.pyd on Windows, .so on Mac)
- Cannot cross-compile from Windows to Mac
- Nathan has a Mac Mini — setting up Claude Code there for macOS builds
- Mac needs: Maya 2026, Xcode CLI tools, repo clone, Claude Code
