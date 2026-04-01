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

### Still Needed (Future Sessions)
- `build_blender.py` — Cython compilation + addon zip packaging
- Blender socket server addon (for TCP adapter to connect to)
- `mcp_setup.py` update for `ensure_blender_mcp()`
- Testing in actual Blender 4.x
- `mca_blender/install.py` — Addon installation helper

### Verified
- All Python imports work: `BlenderAdapter`, `InternalBlenderAdapter`,
  `AdapterManager` with Blender adapter registered
- No breakage to existing Maya/UE functionality
