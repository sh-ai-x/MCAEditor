# MCP Extraction — Migration Plan

**Date:** 2026-07-01
**Goal:** Move the DCC MCP servers (Maya, Unreal, Blender) out of the MCA Editor
repo into a standalone, shareable package (`mca-mcp`) that any project can install,
while the editor keeps consuming them through a thin shim.

---

## 1. Decision Summary

- **One monorepo** (`mca-mcp`) for the three DCC servers + shared `common/` code.
  Not separate repos — you share code between them, you're a solo maintainer, and
  install targets (not repo boundaries) solve "Maya user shouldn't pull Unreal."
- **Per-DCC install targets** so a user only pulls what they need
  (`mca-mcp install maya` / `pip install mca-mcp[unreal]`).
- **Unreal C++ bridge** (`mca_unreal/` → `MCAEditorScripting`) distributed via
  **GitHub Releases** (prebuilt `.uplugin` per UE version), NOT bundled in the clone.
- **Editor MCP stays in this repo** — `mcp_editor_server.py` is coupled to the
  editor's JSON-RPC API (ports 7003-7013) and is not shareable.

---

## 2. Current State (verified)

### Servers (all dependency-free from `mca_core`)
Import only stdlib + `mcp` + `pydantic_core`. Designed to be copied to a deploy dir
and run in a separate venv.

| Server | Lines | Tool source | Discovery |
|---|---|---|---|
| `mcp_maya_server.py` | 1298 | cloned MayaMCP `mayatools/` (+ our patches) | `OperationManager` walk |
| `mcp_unreal_server.py` | 1141 | in-repo `unreal_tools/` (89 files) | `OperationManager` walk (dup of Maya) |
| `mcp_blender_server.py` | 765 | inline in file | inline `@server.list_tools` |
| `mcp_editor_server.py` | 744 | inline `_TOOLS` in file | inline — **STAYS** |

### Orchestration
- `mcp_setup.py` (1217 lines) — clone MayaMCP, build venv, copy servers +
  `unreal_tools/`, register in `~/.claude.json`. **Editor-coupled** (deploy paths
  under `mca_preferences/`, `get_prefs_dir()` import).
- Deploy dir: `~/Documents/mca_preferences/mcp_servers/`
- Registration: `~/.claude.json`, names `MCAMayaMCP` / `MCAUnrealMCP` / `MCAEditorMCP`.

### Coupling / trigger points (call sites to update)
- `mca_qt/editor_panel.py:4020` → `mcp_setup.ensure_maya_mcp(...)`
- `mca_core/adapters/maya_adapter.py:690` → `get_mcp_server_status()`
- `mca_core/adapters/internal_maya_adapter.py:605` → `get_mcp_server_status()`
- `mca_core/adapters/blender_adapter.py:552` → `get_mcp_server_status()`
- `mca_core/adapters/internal_blender_adapter.py:471` → `get_mcp_server_status()`
- (Unreal `ensure_unreal_mcp` trigger — confirm call site during Phase 4.)

### Unreal C++ bridge
- `mca_unreal/MCAEditor.uplugin`
- `mca_unreal/Source/MCAEditorScripting/` (Public + Private) — the `PyUnreal*Library` classes
- `mca_unreal/Content/Python/ue_editor_host.py`

---

## 3. Target Repo Layout (`mca-mcp`)

```
mca-mcp/
  pyproject.toml            # pip-installable; extras: [maya] [unreal] [blender] [all]
  README.md
  CHANGELOG.md
  LICENSE
  mca_mcp/
    __init__.py             # __version__
    common/
      __init__.py
      discovery.py          # OperationManager (de-duped from Maya+Unreal)
      transport.py          # socket send/recv, arg serialization/quoting fixes
      schema.py             # docstring -> JSON schema helpers
      registration.py       # ~/.claude.json read/write, `claude` CLI fallback
      venv.py               # create venv + install `mcp`
    maya/
      server.py             # from mca_core/mcp_maya_server.py
      mayatools/            # vendored from MayaMCP (see 4.2) OR fetched at install
    unreal/
      server.py             # from mca_core/mcp_unreal_server.py
      unreal_tools/         # the 89 in-repo tool files
    blender/
      server.py             # from mca_core/mcp_blender_server.py (inline tools)
  install/
    cli.py                  # `mca-mcp install maya|unreal|blender|all`, `status`, `uninstall`
  tests/
    test_discovery.py
    test_schema.py
    test_registration.py    # against a temp fake ~/.claude.json
```

Separate release channel (own repo OR Releases tab on `mca-mcp`):
```
mca-unreal-bridge (Releases)
  MCAEditorScripting-UE5.3.zip
  MCAEditorScripting-UE5.4.zip
  ...
```

---

## 4. Migration Phases

### Phase 0 — Scaffold (0.5 day)
- Create `mca-mcp` repo, `pyproject.toml` with optional-dependency extras.
- CI: lint + `pytest` on push (GitHub Actions, Windows + macOS matrix).
- Empty `mca_mcp/common/` with placeholder modules.

### Phase 1 — Extract shared `common/` (1 day)
- Pull the duplicated `OperationManager` from `mcp_maya_server.py` /
  `mcp_unreal_server.py` into `common/discovery.py`. Reconcile the two copies
  (they're described as "identical" — verify diff, keep the superset).
- Pull arg serialization + quoting fixes (the `f"{k}='{v}'"` bug fix noted in
  the Maya server) into `common/transport.py`.
- Move `~/.claude.json` registration logic out of `mcp_setup.py` into
  `common/registration.py`. Parameterize deploy dir + config path (no
  `get_prefs_dir()` dependency).
- Move venv creation into `common/venv.py`.
- **Unit tests** for discovery + schema + registration (registration against a
  temp config file). This is the safety net for the whole migration.

### Phase 2 — Move Maya + Unreal servers (1 day)
- Copy `mcp_maya_server.py` → `mca_mcp/maya/server.py`; refactor its inlined
  discovery to import from `common/`.
- Copy `mcp_unreal_server.py` → `mca_mcp/unreal/server.py`; same refactor.
- Move `mca_core/unreal_tools/` → `mca_mcp/unreal/unreal_tools/` (git history via
  `git mv` in a branch, or `git filter-repo` if you want history in the new repo).
- **Maya tools decision (4.2 below).**
- Smoke test: run each server standalone, confirm `list_tools` returns the
  expected count (Unreal ~89-tool categories; Maya matches MayaMCP + patches).

### Phase 3 — Move Blender server (0.5 day)
- Copy `mcp_blender_server.py` → `mca_mcp/blender/server.py`. Tools are inline,
  so minimal refactor — just point any shared transport/registration at `common/`.

### Phase 4 — Standalone installer CLI (1 day) ← bulk of the work
- Rewrite `mcp_setup.py`'s orchestration as `install/cli.py`:
  - `mca-mcp install maya|unreal|blender|all [--deploy-dir DIR] [--scope project|user]`
  - `mca-mcp status`   → the shape currently returned by `get_mcp_server_status()`
  - `mca-mcp uninstall <dcc>`
- Key change: **deploy dir + config path are arguments**, defaulting to the old
  `mca_preferences/mcp_servers/` only when invoked by the editor shim. Standalone
  users get a sane default (`~/.mca-mcp/`).
- Idempotent, background-thread-friendly (editor calls it off the UI thread).
- Preserve the Maya 2024 quirks knowledge if the installer touches command ports
  (it doesn't today — registration only — but note it).

### Phase 5 — Point MCA Editor back at the package (0.5 day)
- Add `mca-mcp` to the managed venv (`venv_manager.py` `REQUIRED_PACKAGES`), pinned
  version. (Or git submodule if you prefer lockstep dev.)
- Shrink `mca_core/mcp_setup.py` to a shim that:
  - imports the package installer,
  - calls it with the editor's deploy dir (`get_prefs_dir()/mcp_servers`) + scope,
  - re-exports `ensure_maya_mcp` / `ensure_unreal_mcp` / `get_mcp_server_status`
    so the 5 existing call sites (§2) keep working unchanged.
- Keep `mcp_editor_server.py` + its deploy path here — it does NOT move.
- Rebuild all three Maya versions (2024/2025/2026), clear extraction cache, test
  MCP registration end-to-end in a real Maya session.

### Phase 6 — Unreal C++ bridge release channel (1-2 days, parallelizable)
- Decide repo home (own repo vs Releases on `mca-mcp`).
- Add a build script that packages `MCAEditorScripting` per UE version into a
  zip with the `.uplugin`.
- `mca-mcp install unreal` gains a step: download the matching bridge release and
  drop it into the target UE project's `Plugins/` (or print instructions if it
  can't locate the project). Python `unreal_tools/` ship with the package; only
  the compiled bridge comes from Releases.
- Document the UE-version → bridge-version compatibility matrix.

### Phase 7 — Docs + publish (0.5 day)
- README: install, per-DCC quickstart, Claude Code registration, bridge matrix.
- Tag `v0.1.0`, publish (PyPI if public, or private index / git tag if not).
- Update this repo's memory + session notes to point at the new package.

**Rough total: 5-7 focused days** (Phase 6 is the swing factor).

---

## 4.2 Open Question — Maya `mayatools/` source

Today the Maya server relies on **cloning PatrickPalmer/MayaMCP** for `mayatools/`
+ patches (delete `generate_scene.py`, etc.). For a shareable package, pick one:

- **(A) Vendor** the patched `mayatools/` into `mca_mcp/maya/mayatools/`.
  - Pro: no git clone at install, offline-friendly, patches already applied.
  - Con: lose upstream `git pull`; must manually re-sync from MayaMCP.
  - Respect MayaMCP's MIT license (keep LICENSE + attribution). ✅ recommended.
- **(B) Keep cloning** at install time (installer runs `git clone` + applies patches).
  - Pro: easy upstream sync.
  - Con: needs git on the user's machine, network at install, patch step can break
    on upstream changes.

**Recommendation: (A) vendor**, with a `tools/sync_mayamcp.py` helper to pull
upstream and re-apply patches when you choose to.

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Registration logic regresses `~/.claude.json` | Unit tests in Phase 1 against temp config; test before touching editor |
| Editor call sites break | Shim re-exports same 3 functions; 5 sites unchanged (§2) |
| Maya 2024 command-port quirks | Installer only touches registration, not ports — no change to that path |
| Cython build coupling | Servers already ship as pure `.py` (DIST_PURE_PYTHON) — no compile impact |
| Bridge/UE version drift | Compatibility matrix + per-UE release zips |
| License compliance (MayaMCP MIT) | Keep LICENSE + attribution when vendoring |

---

## 6. First Concrete Step

Phase 1, PoC scope: extract `common/discovery.py` + `common/registration.py` with
unit tests, and stand up `mca_mcp/unreal/server.py` importing from `common/` so it
runs standalone. That proves the pattern on the server with the most tools before
touching Maya's clone story or the editor shim.
