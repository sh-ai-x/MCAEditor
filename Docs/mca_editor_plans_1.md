# MCA Editor — Venv & Embedded Terminal Plans

Two interconnected updates: a venv-based dependency system that keeps Maya's
Python clean, and a dual-frontend terminal that works embedded in both
standalone and Maya environments.

The venv comes first because the terminal in Maya depends on it.

---

## Plan 1: Venv-Based Dependency Management

### Goal
All MCA Editor dependencies (pywinpty, pyflakes, future AI packages) live in
a managed venv inside `mca_preferences/`. Maya's Python and the system Python
are never modified. Both standalone and Maya modes use this venv.

### Directory Structure
```
mca_preferences/
├── scripts/              # (exists) User scripts, buffers
├── site-packages/        # (exists) Legacy — can phase out over time
├── .venv-3.11/           # NEW — managed venv (versioned by Python)
│   ├── pyvenv.cfg
│   ├── Scripts/          # (Windows) or bin/ (Linux/Mac)
│   │   └── python.exe    # Venv Python — used for subprocess terminal
│   └── Lib/
│       └── site-packages/
│           ├── pywinpty/
│           ├── pyflakes/
│           └── ...
└── session/              # (exists) Session state
```

The venv directory is versioned by Python major.minor (e.g. `.venv-3.10`,
`.venv-3.11`) so multiple Maya versions can coexist without ABI conflicts.
Maya 2024 (Python 3.10) and Maya 2025 (Python 3.11) each get their own venv.

### New File: `mca_core/venv_manager.py`

Responsibilities:
- **`ensure_venv()`** — Creates the venv if it doesn't exist. Uses
  `sys.executable` to find the host Python (mayapy or system python).
  Calls `python -m venv mca_preferences/.venv` via subprocess.
- **`ensure_packages(requirements)`** — Takes a list of package specs
  (e.g. `["pywinpty>=2.0.0", "pyflakes"]`). Checks what's installed via
  `importlib.metadata` on the venv's site-packages. Runs
  `venv_python -m pip install <missing>` only for what's actually missing.
  No network call if everything is present.
- **`get_venv_python()`** — Returns the path to the venv's Python
  executable. Used by the terminal subprocess and future AI tool launches.
- **`get_venv_site_packages()`** — Returns the path to the venv's
  site-packages directory. Used for `sys.path` injection.
- **`inject_venv_path()`** — Adds the venv's site-packages to `sys.path`
  if not already present. Called at plugin startup in Maya and at app
  startup in standalone.
- **`is_package_available(name)`** — Quick check if a specific package
  can be imported from the venv. Used for graceful feature gating
  (e.g. terminal disabled if pywinpty not available, diagnostics Tier 2
  disabled if pyflakes not available).

### Required Packages (v1)
```
pywinpty>=2.0.0     # Terminal backend (Windows only)
pyflakes            # Tier 2 code analysis
```

Future additions (not now):
```
anthropic           # Claude API client
mcp                 # MCP SDK
```

### Integration Points

**Maya plugin (`mca_maya/plugin_main.py` — `initializePlugin`)**:
1. Import `venv_manager` (pure Python, no dependencies needed)
2. Call `ensure_venv()` — creates venv on first load, no-op after
3. Call `ensure_packages(REQUIRED_PACKAGES)` — installs missing deps
4. Call `inject_venv_path()` — adds venv site-packages to `sys.path`
5. Proceed with existing plugin init (register command, etc.)

Step 2-3 only hit the network on first install or after an update adds
new requirements. Normal startup is just a `sys.path.insert()` — fast.

**Standalone (`mca_standalone/main.py`)**:
Same sequence before creating QApplication. The standalone app may already
have packages in its own environment, but the venv approach keeps it
consistent and portable.

**Build script (`build_maya.py`)**:
The venv is NOT included in the distribution zip. It's created at first
launch on the user's machine. This keeps the zip small and ensures
compiled extensions match the user's Python version exactly.

**Install script (`install_maya.py`)**:
Add an optional `--setup-venv` flag that pre-creates the venv and installs
packages during installation rather than on first launch. Useful for
studio deployments where machines may not have internet access later.

### Offline / Air-Gapped Environments
Some studios block internet on artist machines. Two options:
1. `--setup-venv` during install while on a machine with internet
2. A `vendor/` directory in the distribution containing pre-downloaded
   wheels that `pip install --no-index --find-links vendor/` can use

The vendor approach is a stretch goal — flag it in the install docs but
don't build it for v1.

### Migration from Legacy site-packages
The existing `mca_preferences/site-packages/` was set up in the workspace
unification session. The `_ensure_dirs()` call in `session_manager.py`
creates it. Once the venv is in place:
1. Keep creating `site-packages/` for backward compat (users may have
   manually installed packages there)
2. `sys.path` order: venv site-packages FIRST, then legacy site-packages
3. Don't auto-migrate — just let both coexist

### Error Handling
- Venv creation fails (permissions, disk space): Log warning, continue
  without venv. Features that need missing packages gracefully disable.
- Package install fails (no internet, pip error): Log the specific failure,
  continue. `is_package_available()` gates let the editor still work.
- Corrupted venv: Add a `recreate_venv(force=True)` option that deletes
  and rebuilds. Wire to a "Repair Installation" menu item.

---

## Plan 2: Dual-Frontend Embedded Terminal

### Goal
The terminal works embedded in both standalone and Maya. Standalone uses
the xterm.js/QWebEngineView version (already working). Maya uses the
original QPlainTextEdit/AnsiParser version (already written, still on disk).
Same backend, two frontends, runtime selection.

### Current State
```
mca_qt/widgets/
├── terminal_backend.py    # PTY manager via pywinpty — SHARED, unchanged
├── ansi_parser.py         # VT100 parser + 2D grid — exists, was "replaced"
├── terminal_widget.py     # QPlainTextEdit frontend — exists, was "replaced"
└── xterm_widget.py        # xterm.js/QWebEngineView — current default
```

The "old" files (`ansi_parser.py`, `terminal_widget.py`) were kept on disk
per the xterm migration notes. They become the Maya frontend.

### Rename for Clarity
```
terminal_widget.py    → terminal_native.py    # QPlainTextEdit version
xterm_widget.py       → terminal_xterm.py     # xterm.js version
```

Both expose a `TerminalWidget` class with the same public API:
- `start(shell, cwd, env, cols, rows)`
- `terminate()`
- `is_alive()`
- `set_font_size(size)`
- `clear()`
- Signals: `process_exited`, `font_size_changed`, `title_changed`

### Runtime Selection (`mca_qt/widgets/terminal_factory.py` — NEW)

Simple factory function:

```python
def create_terminal_widget(parent=None):
    """
    Returns the best available terminal widget for the current environment.

    Selection order:
    1. xterm.js (QWebEngineView) — if QtWebEngine is available
    2. Native (QPlainTextEdit + AnsiParser) — if pywinpty is available
    3. None — terminal feature disabled

    :param QWidget parent: Parent widget.
    :rtype: TerminalWidget or None
    """
    # Try xterm.js first (standalone with PySide6)
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from .terminal_xterm import TerminalWidget
        return TerminalWidget(parent)
    except ImportError:
        pass

    # Fall back to native (Maya or minimal environments)
    try:
        import winpty  # pywinpty
        from .terminal_native import TerminalWidget
        return TerminalWidget(parent)
    except ImportError:
        pass

    # No terminal available
    return None
```

### Modified: `mca_qt/editor_panel.py`

Replace the current direct import:
```python
# OLD
from .widgets.xterm_widget import TerminalWidget

# NEW
from .widgets.terminal_factory import create_terminal_widget
```

In `__init__`, where the terminal is created:
```python
self._terminal = create_terminal_widget(parent=self)
if self._terminal is not None:
    self._center_splitter.addWidget(self._terminal)
    self._terminal.hide()
else:
    # Terminal unavailable — hide menu entry, disable Ctrl+`
    logger.info("Terminal unavailable (missing pywinpty or QtWebEngine)")
```

The toggle, persistence, cleanup, and menu code just null-checks
`self._terminal` before acting.

### QPlainTextEdit Terminal Refresh

The native terminal widget was written and tested in the Feb 24 session.
A few things to verify/update before it's back in service:

1. **Import paths** — It was written when widgets lived in `mca_editor/ui/`.
   Update imports to use `mca_qt.qt_compat` and current package paths.

2. **API alignment** — Make sure the public API matches what `editor_panel.py`
   expects. The xterm version may have added methods during the migration
   (e.g. `title_changed` signal). Add stubs if needed.

3. **Settings integration** — Wire `terminal_font_family`, `terminal_font_size`,
   `terminal_scrollback_lines` from `mca_core/config/settings.py` (these
   settings already exist, just need to be read by the native widget).

4. **Ctrl+Scroll zoom** — Already implemented in the original. Verify it
   still works and emits `font_size_changed`.

5. **Context menu** — Copy/Paste/Clear/Select All. Already implemented
   in the original.

6. **cwd parameter** — The xterm version accepts `cwd` in `start()`.
   Make sure the native version passes it through to the backend.

### Known Tradeoffs: Native vs xterm.js

| Feature | xterm.js | Native (QPlainTextEdit) |
|---------|----------|------------------------|
| Rendering quality | Excellent (GPU-accelerated WebGL) | Good (Qt text rendering) |
| ANSI support | Complete (xterm.js handles it) | Custom parser — covers 95% |
| Performance | 60fps, handles heavy output | 60fps via QTimer, may lag on extreme output |
| Alternate screen (vim, htop) | Full support | Implemented but less battle-tested |
| Truecolor (24-bit) | Yes | Yes (parser supports it) |
| Selection / copy | Native browser selection | Custom QPlainTextEdit selection |
| Dependency | QtWebEngine (~100MB) | None beyond pywinpty |

The native version is "good enough" for running Claude Code, pip commands,
git, and shell work. Artists won't notice the difference for typical use.

### Terminal in the Build Script

`build_maya.py` needs to include `terminal_native.py`, `ansi_parser.py`,
and `terminal_backend.py` in the Maya distribution. `terminal_xterm.py`
and the `resources/terminal/` xterm.js assets can be excluded from the
Maya build since QtWebEngine isn't available there.

`terminal_factory.py` goes in both distributions — it handles the
selection at runtime.

---

## Implementation Order

### Phase 1: Venv Manager
1. Write `mca_core/venv_manager.py`
2. Integrate into `mca_maya/plugin_main.py` (initializePlugin)
3. Integrate into `mca_standalone/main.py`
4. Update `build_maya.py` to exclude venv from dist
5. Update `install_maya.py` template with `--setup-venv` flag
6. Test: Fresh Maya launch → venv created → pywinpty installed → imports work

### Phase 2: Terminal Dual Frontend
1. Rename `terminal_widget.py` → `terminal_native.py`
2. Rename `xterm_widget.py` → `terminal_xterm.py`
3. Update imports in both to use `mca_qt.qt_compat`
4. Align public APIs (add any missing signals/methods)
5. Write `terminal_factory.py`
6. Update `editor_panel.py` to use factory
7. Update `build_maya.py` to include native terminal, exclude xterm assets
8. Test standalone: Verify xterm.js still selected and works
9. Test Maya: Verify native terminal selected and works
10. Test missing deps: Verify graceful disable when pywinpty absent

### Phase 3: Verify End-to-End
1. Clean install: Run `install_maya.py`, open Maya, load plugin
2. First launch creates venv, installs pywinpty
3. Ctrl+` opens embedded native terminal in Maya
4. Type `claude` or `claude-code` — Claude Code launches in terminal
5. Close Maya, reopen — terminal state persists, no reinstall
6. Standalone editor still uses xterm.js version
