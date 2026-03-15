# Session Notes — 2026-03-14: macOS Builds for All Maya Versions

## Summary
Pulled latest changes from GitHub and built + deployed MCA Editor v0.3.9
for all three Maya versions on the Mac Mini.

## Changes Pulled
- `Docs/SessionNotes/2026-03-13_first_launch_splash_screen.md` (new)
- `mca_qt/editor_panel.py` — verbosity fix for blue code echo
- `mca_qt/widgets/completer.py` — fix for wrong completion being inserted

## Builds Completed
All three Maya versions built and deployed successfully (77 files each):

| Maya Version | Python | Deploy Path |
|---|---|---|
| 2024 | cpython-310 | `~/Library/Preferences/Autodesk/maya/2024/plug-ins/mcaEditor.py` |
| 2025 | cpython-311 | `~/Library/Preferences/Autodesk/maya/2025/plug-ins/mcaEditor.py` |
| 2026 | cpython-311 | `~/Library/Preferences/Autodesk/maya/2026/plug-ins/mcaEditor.py` |

## Build Notes
- Cannot run Maya 2024 and 2026 builds in parallel — they share the source
  tree for Cython `.c` intermediates, and `clean_source_tree()` in one build
  can delete files the other is still compiling. Must build sequentially.
- Maya 2025 and 2026 both use Python 3.11; Maya 2024 uses Python 3.10.
