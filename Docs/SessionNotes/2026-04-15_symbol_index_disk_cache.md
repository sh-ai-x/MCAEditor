# 2026-04-15 — Symbol index survives Maya restart via on-disk cache

## Symptom

Every time the editor panel was closed and reopened in Maya, the symbol
index would kick off a full re-scan.  On large projects this froze Maya
for minutes each time, even when nothing had changed on disk.  Nathan
flagged this as the **6th time** this class of regression had come back.

The in-session ``_cached_symbol_index`` module-level cache was supposed
to prevent this, but it vanishes whenever:

- Maya is restarted.
- The plugin is unloaded / reloaded.
- A new build overwrites the extracted package (``mca_qt.editor_panel``
  gets re-imported under a fresh module object, wiping its globals).
- The first-ever indexing run didn't reach ``ready`` before the user
  closed the panel, so the eager module stash in ``_poll_index_progress``
  never fired.

## Fix

Added an on-disk pickle cache on top of the existing in-memory cache.
The in-session module cache is still the first line of defence — the
on-disk layer only kicks in when the module cache is empty, which is
exactly the "fresh Maya process / fresh plugin load" case the user kept
hitting.

### New in ``mca_core/symbol_index.py``

- ``SymbolIndex.save_to_disk(path)`` — pickles ``_symbols_by_name``,
  ``_symbols_by_file``, ``_file_mtimes``, ``_file_words``, and
  ``_all_files`` with a magic header (``MCAIDX\x00``) and schema
  version.  Writes via temp file + ``os.replace`` so a crash mid-save
  can't corrupt an existing cache.
- ``SymbolIndex.load_from_disk(path)`` (classmethod) — validates magic
  and schema version, reconstructs a ``SymbolIndex`` already in the
  ``ready`` state, or returns ``None`` cleanly on any failure (missing
  file, truncated pickle, schema mismatch, missing keys).
- ``SymbolIndex.is_fresh_for(folders, excluded)`` — stat-only walk of
  the workspace that compares the disk's file set + mtimes to what the
  cache claims.  Uses a 1.0s mtime tolerance for FAT32 / network shares.
  Cheap enough to run on every open before trusting the cache.
- ``_walk_folder_for_freshness`` — module-level helper that mirrors
  ``IndexWorker._walk_folder`` without cancellation / parsing, shared
  by ``is_fresh_for``.

### New in ``mca_qt/editor_panel.py``

- ``_get_index_cache_path(normalized_folders)`` — returns
  ``~/Documents/mca_preferences/MCAEditor/index_cache/idx_<sha1>.pkl``
  where ``<sha1>`` is 16 hex chars derived from the sorted, normalized,
  (Windows-lowercased) workspace folder list.  Different projects map
  to different cache files with no risk of collision.
- ``_disk_cache_still_valid(disk_index, folders, excluded)`` — thin
  try/except wrapper around ``is_fresh_for``; any exception during
  validation falls through to reindex instead of raising out of init.
- ``_save_index_to_disk_if_ready()`` — guarded saver used from both the
  completion-path (``_poll_index_progress``) and the cleanup-path
  (``_stop_symbol_indexing``).

### Cache lookup order in ``_start_symbol_indexing``

1. **Instance cache** — panel still has a ready index with matching
   folders.  Rare in practice but cheapest.
2. **Module cache** — ``_cached_symbol_index`` survives panel
   destruction within the same Maya session.
3. **Disk cache** — pickle file from a previous Maya session.  Must
   pass ``is_fresh_for`` validation before reuse; stale caches fall
   through to a fresh reindex rather than serve wrong data.  On a hit,
   the disk result is also seeded into the module cache so subsequent
   close/reopen in this session hits branch (2).

Only if all three miss (or the disk cache is stale) does the expensive
``IndexWorker`` path actually run.

## Persistence points

The index is saved to disk in two places:

- ``_poll_index_progress`` when state transitions to ``ready`` —
  normal completion path, covers the common case.
- ``_stop_symbol_indexing(clear_index=True)`` when the detach-time
  stash finds a ready index — belt-and-braces for the rare case where
  the progress timer was killed before it saw ``ready`` (e.g. the run
  finished between two 500 ms ticks).

## Smoke tests (all passing)

| Scenario                                      | Expected | Result |
|-----------------------------------------------|----------|--------|
| Fresh index → save → load → ``ready``         | OK       | ✓      |
| Load → ``is_fresh_for`` unchanged workspace   | True     | ✓      |
| Load → ``is_fresh_for`` after file edit       | False    | ✓      |
| Load → ``is_fresh_for`` after file add        | False    | ✓      |
| Load → ``is_fresh_for`` after file delete     | False    | ✓      |
| ``load_from_disk`` on corrupted pickle        | None     | ✓      |
| ``load_from_disk`` on missing file            | None     | ✓      |

## Gotchas

- The cache file must live **outside** the indexed workspace — it
  would otherwise appear in the freshness walk and the set-equality
  check would reject it every time.  We store it under the prefs
  dir, so this isn't an issue in real use.
- Schema version is bumped to ``2`` the moment any of the five
  pickled structures changes shape (new field on ``SymbolEntry``,
  different keys in ``_file_words``, etc.).  Old caches are silently
  discarded on version mismatch — no migration code needed.
- The on-disk cache is keyed by the **folder list**, not the project
  config.  Toggling ``excluded_folders`` on the same set of workspace
  folders won't invalidate the cache — the stat-only walk will still
  see the excluded files on disk and ``is_fresh_for`` will (correctly)
  return False, triggering a reindex.
