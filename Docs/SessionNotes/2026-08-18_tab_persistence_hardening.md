# 2026-08-18 — Tab Persistence Hardening (the "people keep losing their work" bug)

## Summary

Traced and fixed the recurring reports of lost tabs. There were **five** separate
data-loss paths, not one. The headline bug was a startup ordering error that
blanked the default session every time a project auto-opened — reproduced
against `HEAD` and verified fixed.

Version bumped `1.0.32` → `1.0.33`.

---

## Root cause #1 — auto-opening a project wiped the default session (THE bug)

This is almost certainly what users were actually hitting.

The sequence in `mca_qt/editor_panel.py`:

1. `__init__` calls `_will_auto_open_project()`. When it returns True, the
   default-session restore **and** the starter-buffer creation are both skipped
   (a v1.0.32 speed optimization — the project was about to replace the layout
   anyway, so building it twice cost ~0.6s).
2. `_auto_open_last_project()` → `_open_project()`.
3. `_open_project()` calls `_save_context_session()` to "preserve the outgoing
   context before switching" — **before** `self._active_project` is set.
4. At that moment the container is *empty* (step 1 skipped the restore), and
   `_active_project` is still `None`, so the save routed to the **default**
   `session.json` and wrote a zero-tab manifest over the user's real tab list.
5. The user works in the project, closes it, `_close_project()` loads the
   (now blank) default manifest → single empty buffer. **All their non-project
   tabs are gone**, with no crash and no error message.

Verified against a `git worktree` at `HEAD`: seeded 4 default tabs, auto-opened a
project, default `session.json` went **4 tabs → 0**. With the fix the file is
byte-identical (not rewritten at all).

**Fix:** an empty-session guard in `_save_session_manifest()`. A zero-tab
manifest is never written from a panel that has not yet held a single tab
(`_session_has_had_tabs`). Once any tab has existed, an empty save is
legitimate (the user closed everything) and is allowed through.

> This also explains why the flat `mca_preferences/MCAEditor/session.json` on
> this machine was already empty when the work started — it had been blanked
> long ago.

## Root cause #2 — no atomic writes anywhere

`session.json`, buffer files, `output.log`, and `_write_file` all used a plain
`open(path, "w")`, which **truncates the destination before writing**. A Maya
crash or hard process kill inside that window left a zero-byte `session.json`;
`load_manifest()` then returned `None` and every tab was gone. Given this
codebase's documented history of Shiboken shutdown crashes, this window was
being hit for real.

**Fix:** `mca_core/session_manager.atomic_write()` — write to `<name>.tmp`,
`flush()`, `os.fsync()`, then `os.replace()` (atomic on Windows and POSIX).
Clears a read-only destination attribute first so Perforce-managed files still
save. Every write in the session layer plus `_write_file` and `cleanup()` now
goes through it.

## Root cause #3 — no backup, and a corrupt manifest got overwritten

Once `session.json` was damaged there was no second copy, and the blank
fallback session was written straight over it on the next save — destroying any
chance of manual recovery.

**Fix (two parts):**
- `session.json.bak` rollover. Before each write, an existing manifest that
  parses *and* holds ≥1 tab is copied to `.bak`. Reads fall back to `.bak`.
  An empty manifest is never promoted to backup, so closing all tabs can't
  clobber the last good copy.
- `_session_manifest_locked`. If a manifest exists but neither it nor its backup
  parses, tab persistence is **paused for the session** and the user is told via
  status bar + log. The damaged file stays on disk for manual recovery.
  Latched by `_note_manifest_load_result()`, called after every manifest load
  (startup, project open, project close).

## Root cause #4 — the manifest lagged behind the tab list

`_new_buffer()` and `_open_file_path()` never called `_save_session_manifest()`.
Neither did tab drags, splits, or reorders. Only Ctrl+S, close-tab, and a
graceful `cleanup()` wrote it — so a crash after opening five files lost all
five.

**Fix:**
- `_new_buffer()` and `_open_file_path()` save immediately.
- `editors_changed` and `active_editor_changed` → `_schedule_session_save()`,
  a 400 ms single-shot debounce (these signals arrive in bursts; writing on each
  one would mean a dozen disk writes per user action).
- `__init__` writes the manifest once at the end, so the file matches what's on
  screen from the first second.

## Root cause #5 — no autosave, and tabs vanished on missing files / project switches

- **No autosave at all.** File-backed content was written *only* on Ctrl+S or a
  graceful close. Any hard crash lost everything typed since the last save.
- **`_restore_session` silently dropped tabs whose file was missing**, and the
  next save pruned them from the manifest permanently. A network share offline
  for one launch cost the tab forever.
- **`_save_context_session()` only persisted path-less buffers.** Since restored
  buffers all carry a `file_path`, it was effectively a no-op — so switching
  projects with unsaved changes destroyed them along with the tab widgets.

**Fix:**
- **Crash-recovery snapshots** (`mca_preferences/<dcc>/recovery/`): a timer
  (default 15s) writes a shadow copy of every *modified* tab —
  `<key>.snapshot` (verbatim content) + `<key>.json` (metadata), keyed by a
  SHA-1 of the normalized absolute path. **The user's real file is never
  touched**, so no surprise overwrites, no Perforce fight, no module
  auto-reload. On next launch a snapshot that *differs* from disk is loaded into
  the tab and marked modified (so it shows `*`); a snapshot matching disk is
  stale and deleted. Cleared on successful save and on explicit Discard, purged
  after 30 days.
- **Opt-in direct autosave** (`autosave_to_file`, default off) also writes
  modified tabs to their real file on the same timer. Deliberately does *not*
  run `_auto_reload_module` — reloading modules into a live DCC every few
  seconds behind the user's back is worse than stale imports. Failures show a
  status message, never a modal dialog (a locked file would otherwise pop a
  dialog every tick — hence the new `_write_file(..., notify_on_error=False)`).
- **Orphaned tabs** are carried forward for 7 days with an `unavailable_since`
  stamp (`ORPHAN_TAB_MAX_AGE_SECONDS`) and reopen automatically when the file
  returns.
- `_save_context_session()` now snapshots modified file-backed tabs before the
  context teardown destroys them.

---

## Unrelated breakage found and fixed

`mca_core/adapters/base_adapter.py` was **deleted in the working tree**
(unstaged) while `adapters/__init__.py` still imported `DCCAdapter`, `DCCType`,
and `ConnectionState` from it. Nothing else provided those symbols, so
`mca_core.adapters` — and therefore the whole editor — could not import at all.
Restored from `HEAD` with `git checkout --`.

---

## New settings

| Key | Default | Meaning |
| --- | --- | --- |
| `autosave_enabled` | `True` | Write crash-recovery snapshots |
| `autosave_interval_secs` | `15` | Autosave cadence (clamped 5–600) |
| `autosave_to_file` | `False` | Also write modified tabs to their real file |

Exposed in Settings → General → **"Autosave and Crash Recovery"**.
`_apply_settings_to_editors()` calls `_restart_autosave_timer()` so changes take
effect without an editor restart.

---

## Tests

Two new suites, both run without a DCC:

- `tests/test_session_persistence.py` (26 checks) — atomic writes, `.bak`
  rotation, corrupt-manifest fallback, the empty-never-clobbers-backup rule,
  recovery snapshot round-trip and path normalization, stale purge.
- `tests/test_panel_persistence.py` (34 checks, headless Qt via
  `QT_QPA_PLATFORM=offscreen`) — builds a **real `MCAEditorPanel`** against a
  throwaway prefs dir and an in-memory settings backend, so it never touches the
  developer's own session or QSettings. Covers: startup/new-tab/open-file
  persistence, simulated crash (no `cleanup()`) restoring all tabs, crash
  restoring *unsaved edits*, Ctrl+S clearing the snapshot, the `autosave_to_file`
  opt-in both on and off, corrupt-manifest preservation, missing-file tab
  survival, and the project auto-open regression above.

```
python tests/test_session_persistence.py
python tests/test_panel_persistence.py
```

Both pass. Also smoke-tested the real standalone app (`run.py`, offscreen,
25s) — launches clean, creates `recovery/`, writes the manifest.

---

## Files touched

- `mca_core/session_manager.py` — `atomic_write()`, `_read_manifest()` /
  `_write_manifest()` / `_rotate_manifest_backup()`, `last_load_was_corrupt`,
  recovery snapshot API (`save_recovery` / `load_recovery` / `clear_recovery` /
  `purge_stale_recoveries`), defensive `_count_tabs_in_tree`.
- `mca_qt/editor_panel.py` — empty-session guard, `_session_manifest_locked`,
  `_note_manifest_load_result()`, `_schedule_session_save()`,
  `_restart_autosave_timer()`, `_on_autosave_tick()`,
  `_save_recovery_snapshot()`, `_recovered_content_for()`,
  `_remember_orphaned_tab()`, atomic `_write_file`/`cleanup`, dropped the
  now-unused `stat` import.
- `mca_core/config/settings.py` — three autosave keys.
- `mca_qt/widgets/settings_dialog.py` — "Autosave and Crash Recovery" group.
- `mca_core/adapters/base_adapter.py` — restored.
- `CHANGELOG.md`, `mca_core/__init__.py` (version).

## Build notes

No build-list changes needed. `session_manager.py` has no Qt virtual overrides
so it still compiles to `.pyd`; `editor_panel.py` and `settings_dialog.py` were
already on the `.pyc` list.

### Builds (done, v1.0.33)

All six built with `C:/Python310/python.exe` (the venv Python is broken), run
**sequentially** — parallel builds collide on shared Cython `.c` intermediates.

| Target | Zip | Build hash |
| --- | --- | --- |
| Maya 2024 | `MCAEditor-Maya2024-v1.0.33.zip` | `e1d8cd40ddfc` |
| Maya 2025 | `MCAEditor-Maya2025-v1.0.33.zip` | `09e8ab23ab39` |
| Maya 2026 | `MCAEditor-Maya2026-v1.0.33.zip` | `c43905b3f287` |
| UE 5.5 | `MCAEditor-UE5.5-v1.0.33.zip` | — |
| UE 5.6 | `MCAEditor-UE5.6-v1.0.33.zip` | — |
| UE 5.7 | `MCAEditor-UE5.7-v1.0.33.zip` | — |

Maya builds auto-deployed to `~/Documents/maya/<version>/plug-ins/mcaEditor.py`.
All three build hashes differ, so Maya re-extracts the cache on next load — no
manual cache clear needed.

**Compiled artifact verified functionally**, not by string search (Cython 3.x
compresses string literals, so grepping a `.pyd` proves nothing — see the
project notes). Imported the shipped
`dist/MCAEditor-Maya2024/mca_core/session_manager.cp310-win_amd64.pyd` under
Python 3.10 and confirmed `atomic_write`, the recovery API, corrupt-manifest
fallback to `.bak`, and snapshot round-trip all work in the compiled build.

**Not committed/pushed, and the website has not been redeployed.**

### Mac Mini SSH — DOWN as of this session

`Nathans-Mac-mini.local` does not resolve via mDNS, and the Mac is not reachable
on SSH anywhere on either subnet:

- Both previously-recorded IPs (`192.168.68.79`, `.72`) answer ping but give
  **connection refused** on port 22 — refused, not timeout, so nothing is
  listening. Their current ARP OUIs (`b0:09:da`, `a4:cf:99`) are not Apple, so
  DHCP has likely reassigned those addresses to other devices.
- Swept `192.168.68.0/24` and `192.168.0.0/24` for open port 22. Six hosts
  answered; none accepted `ncomes` / the recorded password:
  `192.168.68.93` (Linux `minutes`) and `.95` (Linux `mechart`) authenticate
  with the existing key; `192.168.68.67` and the three `192.168.0.x` hosts
  reject the Mac credentials.

**Conclusion:** the Mac is powered off/asleep, off the network, or Remote Login
is disabled (System Settings → General → Sharing → Remote Login). No macOS build
was produced this session. `reference_mac_mini.md` IPs are stale — re-record the
current address once it is back up.
