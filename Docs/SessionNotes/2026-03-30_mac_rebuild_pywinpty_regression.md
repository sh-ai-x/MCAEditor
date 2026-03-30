# 2026-03-30 — Mac Rebuild & Windows pywinpty Regression

## Summary
Rebuilt and deployed MCA Editor v1.0.5 for all three Mac Maya versions (2024/2025/2026) after the Windows Claude's rebuild regressed the pywinpty terminal fix.

---

## Problem
The Windows Claude rebuilt the Maya plugins and reintroduced the pywinpty warning:
```
mca_qt.widgets.terminal_native : Terminal start: pywinpty not available (subprocess fallback with local echo)
```

This error message **does not exist** in the current repo code. The current code says:
```
"Terminal start: no PTY available — using subprocess pipe with local echo"
```

This means the Windows Claude deployed from an older or modified version of the source that did not include the fixes from commits:
- `9fcfd8b` — Skip pywinpty import on non-Windows to suppress Mac warnings
- `56d5fe7` — Suppress pywinpty warning on macOS and update session notes
- `d18ca52` — Add Unix PTY backend for macOS terminal, fix SSL certs for Claude Code

## What Was Done
Rebuilt all three Maya versions from the current repo (which has all fixes):

| Maya Version | Status | Deploy Path |
|---|---|---|
| 2024 | Built + deployed (132 files, v1.0.5) | `~/Library/Preferences/Autodesk/maya/2024/plug-ins/mcaEditor.py` |
| 2025 | Built + deployed (132 files, v1.0.5) | `~/Library/Preferences/Autodesk/maya/2025/plug-ins/mcaEditor.py` |
| 2026 | Built + deployed (132 files, v1.0.5) | `~/Library/Preferences/Autodesk/maya/2026/plug-ins/mcaEditor.py` |

Build command used for each:
```bash
python3 build_maya.py --maya-version {2024,2025,2026}
```

## Root Cause — Windows Claude Instructions

**IMPORTANT FOR WINDOWS CLAUDE:**

When rebuilding Maya plugins on Windows, you MUST:

1. **Pull the latest code from GitHub first** (`git pull origin main`) before building. The repo contains critical cross-platform fixes that must not be skipped.

2. **Never modify `terminal_backend.py` or `terminal_native.py` without checking the Mac PTY logic.** These files have platform-specific code paths:
   - **Windows:** `pywinpty` ConPTY (via `_run_pty()`)
   - **macOS/Linux:** stdlib `pty` module (via `_run_unix_pty()`)
   - **Fallback:** subprocess pipe with local echo (last resort)

3. **The platform detection is in `terminal_backend.py` lines 59-83:**
   ```python
   if platform.system() == "Windows":
       # Only tries pywinpty on Windows
   else:
       # macOS/Linux uses stdlib pty module — no pywinpty needed
   ```

4. **Do not revert or overwrite the `check_unix_pty()` function** or the `HAS_UNIX_PTY` flag. These are essential for Mac terminal support.

5. **After building on Windows, push changes to GitHub** so the Mac builds stay in sync.

## Files That Must Stay Cross-Platform

| File | Critical Logic |
|------|---------------|
| `mca_qt/widgets/terminal_backend.py` | Platform-gated PTY imports (line 59-83), `_run_unix_pty()` method, `check_unix_pty()` helper |
| `mca_qt/widgets/terminal_native.py` | `start()` checks both `check_conpty()` and `check_unix_pty()` (line 202) |
| `mca_qt/widgets/terminal_factory.py` | Cross-platform terminal selection |
| `build_maya.py` | Cross-platform build support (`.so` on Mac, `.pyd` on Windows) |
