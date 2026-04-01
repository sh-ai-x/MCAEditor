# Session Notes — 2026-03-31

## Blender Integration (Phase 1: Foundation)

### Summary
Built the complete foundation for MCA Editor's Blender integration. Created all
adapter classes, the Blender addon entry point, the Qt window host, and the MCP
server. Follows the proven UE integration pattern (floating Qt window with
`bpy.app.timers` pumping `processEvents()` at ~120Hz).

### Architecture Decision
Blender does NOT use Qt — it has its own custom UI toolkit. The Qt window cannot
be docked into Blender's panels. Instead, the editor runs as a floating Qt
window above Blender using Win32 owner-window z-ordering, identical to the UE
integration approach. Chose `bpy.app.timers.register()` over BQT/modal operators
for simplicity.

### New Files Created

**Blender Addon Package (`mca_blender/`):**
- `__init__.py` — `bl_info` metadata, `register()`/`unregister()`, operators
  (`MCA_OT_launch_editor`, `MCA_OT_close_editor`), Window menu integration,
  auto-launch timer for session restore
- `blender_window.py` — Qt event loop host: `bpy.app.timers` pump at ~120Hz,
  QApplication creation, MCAEditorPanel wrapper, stdout/stderr tee writers for
  output capture, Win32 owner-window z-ordering via `SetWindowLongPtrW`, status
  bar, MEL stripping, Blender doc links in Help menu, license gate, venv setup

**Adapters (`mca_core/adapters/`):**
- `internal_blender_adapter.py` — In-process adapter for when MCA Editor runs
  as a Blender addon. Direct `exec()`/`eval()` in `__main__` with full `bpy`
  access. Scene info via `bpy.data`, completions via `dir()`. Always connected.
- `blender_adapter.py` — TCP socket adapter for standalone editor connecting to
  a running Blender instance. JSON protocol over TCP (port 8400). Base64-wrapped
  execution wrapper with eval-first-then-exec pattern.

**MCP Server:**
- `mca_core/mcp_blender_server.py` — Standalone MCP server with 13 tools:
  `execute_python`, `get_scene_info`, `scene_new/open/save`, `create_object`,
  `select_objects`, `get_selected`, `set_transform`, `get_object_properties`,
  `create_material`, `assign_material`, `delete_objects`, `viewport_focus`

### Modified Files
- `mca_core/adapters/__init__.py` — Added `BlenderAdapter` export
- `mca_core/adapters/adapter_manager.py` — Added `BlenderAdapter` import and
  registration in `_register_builtin_adapters()`
- `mca_core/config/settings.py` — Changed `dcc_blender_port` from 7002 to 8400
  (7002 conflicts with Maya Python port)

### Key Design Decisions
- **No BQT dependency** — Custom Qt event pump implementation, same as UE
- **Port 8400** for Blender — Avoids conflicts with Maya (7001/7002) and Editor
  API (7003-7013)
- **Minimum Blender 4.0** — Requires Python 3.11+ for PySide6 compatibility
- **JSON protocol** over TCP for socket adapter (not raw commandPort like Maya)
- **Stdout/stderr tees** for output capture (Blender has no MCommandMessage)

### Bug Fixes During Testing (Blender 4.5)

**HWND Discovery matched own window:**
`_find_blender_hwnd()` found the Qt window (title "MCA Editor — Blender" contains
"Blender") instead of the real Blender window. Both HWNDs were the same, causing
`SetWindowLongPtrW` to fail (can't set window as its own owner).
- Fix: Added check to skip windows where `hwnd == _last_qt_hwnd` and exclude
  titles containing "MCA Editor"

**Help menu not found:**
`panel.layout().menuBar()` returned None because the menubar was on the outer
QWidget, not the panel's own layout.
- Fix: Pass `_menubar` reference directly to `_strip_mel_from_ui(panel, _menubar)`

**Output not appearing in MCA Editor panel:**
Original implementation relied on stdout tees for output capture, but
`editor_panel.py` wires output through adapter's `_on_output`/`_on_error`
callbacks (lines 664-665), not stdout.
- Fix: Changed `_execute_python()` to capture stdout via StringIO buffers and
  route through `_on_output`/`_on_error` callbacks

**Output not echoing to Blender console:**
After switching to StringIO capture, `print()` output went to the buffer but was
never written back to Blender's original stdout.
- Fix: After restoring sys.stdout, echo captured output to the underlying stream
  (bypassing the tee via `_original` attribute to avoid double output in the panel)
- Status: Still not fully working — needs further investigation next session

### Addon Installation Notes
- Blender 4.5 uses the new extensions system (since 4.2+); legacy `bl_info`
  addons may not show in the default addon preferences view
- Workaround: launch directly from Blender's Python console:
  ```python
  import mca_blender.blender_window as bw; bw.launch_editor()
  ```
- Addon deployed to: `%APPDATA%/Blender Foundation/Blender/4.5/scripts/addons/mca_blender/`
- `mca_core` and `mca_qt` loaded from source dir via `sys.path` (dev mode)
- Blender 4.5 uses Python 3.11 (PySide6 compatible); Blender 5.1 uses Python 3.13 (NOT compatible)

### Still Needed (Future Sessions)
- **Fix Blender console output routing** — `print()` from MCA Editor execution
  not appearing in Blender's system console despite echo fix; needs debugging
  with actual Blender process to inspect stdout state
- **Blender Python console → MCA Editor** — Blender's `code.InteractiveConsole`
  may save its own stdout reference before tees are installed; may need
  `bpy.app.handlers` or a different interception strategy
- `blender_manifest.toml` for Blender 4.2+ extensions system (proper addon listing)
- `build_blender.py` — Cython compilation + addon zip packaging
- Blender socket server addon (for TCP adapter to connect to)
- `mcp_setup.py` update for `ensure_blender_mcp()`
- `mca_blender/install.py` — Addon installation helper

### Verified
- All Python imports work: `BlenderAdapter`, `InternalBlenderAdapter`,
  `AdapterManager` with Blender adapter registered
- No breakage to existing Maya/UE functionality
- MCA Editor window launches from Blender 4.5 via Python console
- Qt window renders correctly as floating window above Blender
- Code execution from MCA Editor works (output appears in MCA Editor panel)
- Win32 owner-window z-ordering works after HWND fix
- Menu bar, status bar, and MEL stripping all functional
