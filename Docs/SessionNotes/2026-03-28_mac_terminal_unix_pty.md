# 2026-03-28 — Mac Terminal: Unix PTY, Login Shell, SSL Fix

## Summary
Fixed the integrated terminal on macOS Maya — terminal now opens with a real PTY, full PATH (Claude Code accessible), and working SSL certificates. Rebuilt and deployed all 3 Maya versions (2024/2025/2026).

---

## Problem
Three issues prevented the terminal from working properly in Maya on macOS:

1. **No real PTY** — The subprocess pipe fallback (`stdin=PIPE, stdout=PIPE`) caused the shell to run non-interactively (no prompt, no line editing). pywinpty is Windows-only and irrelevant on Mac.
2. **Missing PATH** — Maya launches with a minimal macOS PATH that doesn't include `/opt/homebrew/bin`, so `claude` command was not found.
3. **SSL failure** — Maya's environment lacks the system CA certificate bundle, causing Claude Code (Node.js) to fail with "SSL certificate verification failed" on all HTTPS requests.

## Solution

### 1. Unix PTY Backend (`terminal_backend.py`)
Added `_run_unix_pty()` method using Python's stdlib `pty.openpty()` + `os.fork()`:
- Creates a real pseudo-terminal (master/slave pair)
- Shell sees `isatty() == True` and runs interactively
- Full ANSI escape sequence support, colors, prompts
- Proper resize via `TIOCSWINSZ` ioctl + `SIGWINCH`
- No third-party packages required (stdlib `pty`, `fcntl`, `termios`, `select`)

Backend selection order in `run()`:
1. pywinpty ConPTY (Windows)
2. Unix PTY via stdlib `pty` (macOS/Linux) — **NEW**
3. Subprocess pipe fallback (last resort)

### 2. Login Shell
Shell spawned with `-l` flag (`zsh -l`) so it sources `.zprofile`/`.bash_profile` and gets the full user PATH including Homebrew, nvm, etc.

### 3. SSL Certificate Fix
Set environment variables in `_run_unix_pty()` for macOS:
- `NODE_EXTRA_CA_CERTS=/etc/ssl/cert.pem` — for Node.js (Claude Code)
- `SSL_CERT_FILE=/etc/ssl/cert.pem` — for Python SSL

## Files Changed

| File | Change |
|------|--------|
| `mca_qt/widgets/terminal_backend.py` | Added Unix PTY backend, `HAS_UNIX_PTY` flag, `check_unix_pty()`, login shell `-l`, SSL cert env vars |
| `mca_qt/widgets/terminal_native.py` | Updated PTY check to include Unix PTY (no local echo needed) |
| `mca_qt/widgets/terminal_factory.py` | Updated docstrings for cross-platform PTY support |

## SSH Key
Had to generate a new SSH key for GitHub on the Mac Mini:
- `~/.ssh/id_ed25519_github` — added to GitHub account

## Build & Deploy
All 3 Mac Maya versions rebuilt and deployed:
- Maya 2024 → `/Users/ncomes/Library/Preferences/Autodesk/maya/2024/plug-ins/mcaEditor.py`
- Maya 2025 → `/Users/ncomes/Library/Preferences/Autodesk/maya/2025/plug-ins/mcaEditor.py`
- Maya 2026 → `/Users/ncomes/Library/Preferences/Autodesk/maya/2026/plug-ins/mcaEditor.py`
