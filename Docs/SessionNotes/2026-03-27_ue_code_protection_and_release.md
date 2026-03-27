# Session Notes — 2026-03-27: UE Code Protection & Public Release

## Summary

Audited and fixed code protection for the Unreal Engine plugin build,
built all three UE versions (5.5, 5.6, 5.7) with full C++ compilation
via RunUAT, tested in UE 5.6 and 5.7, updated the website with UE
installation docs, and deployed everything live.

## Code Protection Fixes

### 1. Duplicate .py/.pyd Files Eliminated

**Problem**: MCP server files (`mcp_maya_server.py`, `mcp_editor_server.py`,
`mcp_unreal_server.py`) and `venv_manager.py` shipped as BOTH `.py` source
AND `.pyd` compiled extensions. The `.py` copies leaked source code.

**Root cause**: `setup.py` compiled ALL `.py` files to `.pyd`, then
`bundle_python_packages()` copied both the `.pyd` and the `.py` (from
`DIST_PURE_PYTHON`). No dedup logic existed.

**Fix**: In `bundle_python_packages()` (both `build_unreal.py` and
`build_maya.py`), skip `.pyd` files whose module name matches a
`DIST_PURE_PYTHON` entry. The `.py` copies are required because
`mcp_setup.py` physically copies them to a deploy directory as scripts.

### 2. ue_editor_host.py Compiled to .pyc

**Problem**: `ue_editor_host.py` (450+ lines) shipped as raw source in
the UE plugin distribution.

**Fix**: Added a compilation step in `build_unreal.py` that compiles
`ue_editor_host.py` to `.pyc` using UE's Python (for magic number match),
then removes the `.py` source. Python's sourceless import finds the `.pyc`
directly in the directory.

**Verified**: UE 5.6 and 5.7 both import the `.pyc` correctly — the
auto-launch check, venv setup, and QSettings all work.

### Final Distribution Breakdown

| Type | Count | Protection Level |
|---|---|---|
| `.pyd` (Cython native) | 81 | Strong — binary, not reversible |
| `.pyc` (bytecode) | 29 | Moderate — requires decompiler |
| `.py` (source) | 4 | Required (MCP deploy + venv bootstrap) |

## .uplugin Changes for Public Release

### EnabledByDefault: false

Changed from `true` to `false`. With `true`, a fresh project with
`--skip-cpp` builds showed a scary "Missing Modules" dialog asking to
rebuild. Setting to `false` means users enable in Edit > Plugins
(standard UE workflow, no confusing dialogs).

### PythonScriptPlugin: Optional false

Changed from `"Optional": true` to `"Optional": false`. With it optional,
UE didn't auto-enable PythonScriptPlugin, so our C++ module couldn't
call `IPythonScriptPlugin::Get()` — the toolbar button did nothing.
Making it required means UE automatically enables Python when MCA Editor
is enabled.

## Full RunUAT Builds

All three UE versions built with `RunUAT BuildPlugin` (no `--skip-cpp`):
- Pre-compiled `Binaries/Win64/` with DLLs included
- `Installed: true` in `.uplugin` (UE treats as pre-built, no recompile)
- `EngineVersion` set by RunUAT (e.g. `5.7.0`)
- ~31 MB per zip (vs 5 MB with --skip-cpp)

Customers extract to Plugins/, enable in Edit > Plugins, restart — done.

## Testing

### UE 5.6 (Wayward project)
- Deployed compiled Python to existing plugin at
  `E:\Rascal\depot\Wayward\Plugins\MCAEditor-UE5.6-v1.0.5\`
- C++ module loaded: `StartupModule()` done, toolbar button registered
- `.pyc` sourceless import of `ue_editor_host` worked
- PySide6 venv bootstrapped correctly
- QSettings loaded (`was_open=False`)
- Editor opened and working via toolbar button

### UE 5.7 (clean project test)
- Fresh project at `D:\Unreal-Projects\UE57Test\`
- Extracted zip to Plugins/MCAEditor/
- First attempt failed: PythonScriptPlugin not enabled (fixed by
  making it a required dependency in .uplugin)
- Second attempt with `--skip-cpp` showed "Missing Modules" dialog
  (fixed by doing full RunUAT build with pre-compiled binaries)
- Final test: extracted full RunUAT build, opened project, enabled
  in Edit > Plugins, restarted — worked perfectly

## Website Updates

### Content Changes
- **Homepage**: "A better Maya script editor" → "A professional code
  editor for Maya and Unreal Engine". Added tabbed Quick Start and
  Supported Versions for Maya/UE.
- **Installation page**: Split into Maya and UE sections. UE instructions:
  extract to Plugins/, enable in Edit > Plugins, restart.
- **mkdocs.yml**: Updated site_description to include Unreal Engine.
- **Download page**: Already had UE section in HTML/JS — just needed
  `releases.json` to have UE entries.

### Deploy Script Updates
- Added `_UE_ZIP_RE` regex to match UE zip filenames
- Added `UE_VERSIONS` list (`["5.5", "5.6", "5.7"]`)
- `_build_downloads_dict()` now generates UE download entries
- `upload_download_zips()` handles both Maya and UE zip uploads

### Deployment
- Site deployed to VPS at `mcaeditor.com`
- 3 UE zips uploaded to `/downloads/unreal/` (~31 MB each)
- `releases.json` updated with UE download entries for v1.0.5

## Files Changed

- `build_unreal.py` — duplicate .py/.pyd fix, ue_editor_host .pyc compilation
- `build_maya.py` — duplicate .py/.pyd fix (same pattern)
- `mca_unreal/MCAEditor.uplugin` — EnabledByDefault false, PythonScriptPlugin required
- `mkdocs.yml` — site_description updated
- `website/docs/index.md` — homepage updated for Maya + UE
- `website/docs/getting-started/installation.md` — UE installation instructions
- `tools/deploy_website.py` — UE zip upload support

## Builds Produced

- `dist/MCAEditor-UE5.5-v1.0.5.zip` (30.4 MB, full RunUAT)
- `dist/MCAEditor-UE5.6-v1.0.5.zip` (30.6 MB, full RunUAT)
- `dist/MCAEditor-UE5.7-v1.0.5.zip` (30.7 MB, full RunUAT)

## Python Version Note

UE 5.5, 5.6, and 5.7 all use Python 3.11.8 — same ABI, so all `.pyd`
files are binary-compatible across versions. Only the C++ binaries
differ per UE version.
