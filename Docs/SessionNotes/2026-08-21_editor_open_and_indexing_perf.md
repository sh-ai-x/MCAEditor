# 2026-08-21 — Editor Open & Indexing Performance

## Summary

The editor took ~7.6s to show a window and then re-indexed the entire
26k-file workspace on **every single open**. Root cause was a cache
comparison that could never succeed, compounded by doing all the index
work on the Qt main thread.

Measured on `E:\Rascal\depot\Wayward_RAW\Tools\Python\framework\packages`
(25,725 eligible files, 232,725 symbols):

| | Before | After |
| --- | --- | --- |
| Window visible | 7.57s | **0.24s** |
| `_start_symbol_indexing()` (main thread) | 5.52s | **0.001s** |
| Index ready | 34–214s | **1.96s** |
| Cache file | 102 MB | **51 MB** |
| Cache unpickle | 3.47s | 1.1s (and off the main thread) |
| Worst main-thread stall during startup | 1.6s+ | **221ms, once** |
| Full rebuild (when genuinely needed) | 42.1s | 29.3s |

Version bumped `1.0.33` → `1.0.34`.

---

## Root cause #1 — the disk cache was *always* rejected (THE bug)

`SymbolIndex.is_fresh_for()` compared the set of files on disk against
the set of files in the index and bailed on any difference.

The two sets used **different filters**:

- `IndexWorker._walk_folder` collected a path, then `_parse_file`
  rejected it if it was larger than `_MAX_FILE_SIZE` (512 KB) — so it
  never landed in `_file_mtimes`.
- `_walk_folder_for_freshness` had no size gate, so it counted that same
  file on the disk side.

Every oversized file was therefore a permanent, unfixable mismatch. On
the reference project there were **343** of them (PySide `.pyd` binaries,
`.pak` bundles, `.tga` textures, generated `unreal.py` autocomplete
stubs), so the verdict was "stale" on every open, forever, and the whole
26k-file index was rebuilt from scratch each time.

This is the "never reindex on every open" rule regressing for the
seventh time. It kept coming back because the invariant lived in two
functions that had to be kept in agreement by hand.

**Fix:** one enumerator, `enumerate_source_files()`, is now the single
source of truth for "which files belong in the index". Both the scan and
the freshness comparison call it. The size gate lives *in the walker*, so
a file that can't make it into the index can't appear on the disk side of
the comparison either. `_parse_file` keeps its own size check because
`update_file()` calls straight into it on save.

## Root cause #2 — the whole index lifecycle ran on the Qt main thread

`_start_symbol_indexing()` was called synchronously from
`MCAEditorPanel.__init__` (via `_auto_open_last_project` →
`_open_project`) and did, before returning:

1. `SymbolIndex.load_from_disk()` — unpickle 102 MB → **3.47s**
2. `is_fresh_for()` — walk the workspace, `getmtime` every file → **1.67s**

…and then, because of #1, threw the result away. Five and a half seconds
of dead air before the window appeared, paid on every open, to accomplish
nothing.

Two more main-thread writes existed on the other end: `_poll_index_progress`
called `save_to_disk()` when indexing finished (serializing 102 MB on the
UI thread), and `_stop_symbol_indexing` did it again on close.

**Fix:** `IndexWorker` now owns the entire lifecycle — load, validate,
refresh, persist — on its own daemon thread. `_start_symbol_indexing()`
hands it the cache path and returns immediately. The panel-side
`_disk_cache_still_valid()` wrapper was deleted (nothing called it any
more).

## Root cause #3 — index refresh was all-or-nothing

Even with #1 fixed, a single edited file discarded 26,249 perfectly good
entries and forced a full rescan. Full scans are dominated by disk I/O
(~1.3ms/file — the parse itself is only ~10% of that), so there is no
way to make the rescan fast enough; it has to not happen.

**Fix:** `SymbolIndex.plan_refresh()` diffs the cached mtimes against the
enumerated disk mtimes and returns `(stale, deleted)`. The worker adopts
the cached index wholesale first — so Go To Declaration and completion
work within milliseconds instead of after the scan — then reparses only
what moved and drops what's gone. Touching one file in the reference
project: `25,724 cached, 1 changed, 0 removed`, done in 2.68s.

## Root cause #4 — one giant `pickle.load` froze the UI even from a thread

Moving the cache read to a background thread was not enough.
`pickle.load` is a single C call that holds the GIL for its entire
duration, so a 50 MB read stalled the main thread for ~1.6s regardless of
which thread it ran on. This showed up in the profile as `_init_plugins`
inexplicably taking 1.7s.

**Fix (cache schema v4):** the payload is a header plus bounded chunks
(`_CACHE_CHUNK_FILES = 1000`) written through **one shared `Pickler`**, so
the memo table still collapses duplicate strings across chunks and the
file doesn't grow. Reads go through one `Unpickler` with a 1ms sleep
between chunks. Worst uninterruptible read drops from 1.6s to ~80ms.

Sharing the memo matters: sharding into independent pickles would have
duplicated every repeated identifier and undone the size win.

## Cache size — 102 MB → 51 MB

- `symbols_by_name` and `all_files` are pure derivations of
  `symbols_by_file`. They were being written anyway, roughly doubling the
  file. Both are now rebuilt at load (a fast in-memory loop).
- Identifiers and symbol names are `sys.intern`-ed at parse time, so
  pickle's memo collapses the ~6.3M identifier occurrences down to the
  ~835k distinct strings. Costs ~0.13ms/file at parse time; measured at
  1.3× parse overhead, invisible next to the file read.

## Other fixes rolled in

- **`_all_files` removed.** `_bulk_insert` did
  `if filepath not in self._all_files` against a growing list — ~1.6s of
  pure list scanning across a 26k-file index. The list was redundant with
  `_symbols_by_file`; `get_all_files()` now returns its keys.
- **`os.scandir`** replaces `listdir` + `isdir` + `isfile` + `getmtime`.
  Windows returns the attributes as part of the enumeration, so size and
  mtime are free. Walk time 1.37s → 0.18s. Recursion replaced with an
  explicit stack (deep asset trees can blow the recursion limit before
  they hit `_MAX_DEPTH`).
- **`_SKIP_EXTS` widened** to cover binaries that were previously walked
  and only rejected later by the size gate — `.pyd`, `.mll`, `.pak`,
  `.tga`, `.whl`, `.uasset`, etc.
- **Dirty flag.** `SymbolIndex.is_dirty()` gates every write. An unchanged
  workspace never rewrites the cache, on completion or on close.
- **Stale `.tmp` purge.** A killed write left a full-size copy behind and
  nothing removed it — this machine had a **99 MB orphan from May 8**
  sitting in the prefs folder. The prefix match stops at `.tmp` (not
  `.tmp.`) so it also catches leftovers from the pre-unique-suffix naming.

## Bugs found while rewriting

**MEL procs with no return type were indexed under the wrong name.**
`_INDEX_REGEX` used `proc\s+\w*\s*(name)`. On `global proc doThing()` the
greedy `\w*` swallowed `doThing`, backtracked one character, and indexed
the symbol as **`g`**. `proc helper()` was indexed as `r`. Go To
Declaration could never find those procs. Pre-existing (confirmed against
`HEAD`), fixed by matching an optional return type followed by the
required open paren: `proc\s+(?:\w+(?:\s*\[\s*\])?\s+)?(name)\s*\(`.
Handles `string[]` return types too.

**`_bulk_insert` duplicated symbols on reparse.** Introduced by this
work: reusing `_bulk_insert` for the refresh path appended to
`_symbols_by_name` without removing the file's previous entries, so every
reparsed symbol was listed twice. Caught by a symbol count going
`232725 → 232726` after touching one file. `_bulk_insert` now has replace
semantics (costs one dict lookup on a cold index). Never reached disk —
only `symbols_by_file` is persisted, and that dict was always replaced
correctly. Two regression checks added.

**License validation could stall the launch.** `_try_auto_activate()` is
documented "fire-and-forget" and nothing reads its result, but it ran
inline on Maya's main thread with a 10s HTTP timeout — so a slow license
server delayed the editor opening for no benefit. Now on a daemon thread.
The grace-period revalidation still runs inline (revocation is still
enforced at launch) but with a new `_LAUNCH_HTTP_TIMEOUT = 3` instead of
10s. This machine's token was last validated 2026-08-18 and the grace
period is 7 days, so it would have started firing on 2026-08-25.

---

## Cache schema

`_CACHE_SCHEMA_VERSION` is now **4**.

**Old caches are upgraded, not discarded.** This was not the original
plan and it cost a round trip: the first build shipped with "schema
mismatch -> rebuild", and the very next Maya 2025 launch hung on
`mcaEditor` during startup and then sat indexing for minutes. The
extraction step was ruled out by measurement (0.09s for the 5.3 MB
payload, 78 files) - the cost was entirely the full reparse.

Schemas 2 and 3 hold the same symbol data in a different container, so
`_from_legacy_payload()` converts them. Two details matter:

- **Re-intern on the way in.** Legacy caches predate the
  intern-at-parse-time change, so their strings are millions of distinct
  objects. Carrying them straight over gave pickle's memo nothing to
  collapse and produced an **85 MB** cache that would have stayed that
  size forever. Interning during conversion brings it to 57 MB.
- **`adopt()` inherits the source's dirty flag** rather than forcing it
  clean, so an upgraded index actually gets rewritten in the new format.
  Without that it would be re-converted on every launch.
- Entries the parser change affects are dropped so they reparse. **The
  first attempt keyed this off the `.mel` extension and was wrong** -
  verification found 8 files still carrying stale symbols (`g`, `_`,
  `s`), all of them `.py` files with MEL embedded in strings:
  `dynamicChain.py`, `melparse.py`, `splash_templates.py`. The rule is
  now keyed off the *entry kind* the old parser produced
  (`proc` / `global_proc`), which catches embedded MEL regardless of
  extension, and a `parser_version` field in the cache header drives it
  so the same mechanism works for any future parser change - including
  on caches already written in the current schema.

Measured on the real 102 MB v2 cache: **5.8s**, keeping 25,705 of 25,725
files (20 reparsed, 526 removed by the widened skip-extension list).
Was 200s+ as a full rebuild.

---

## Tests

New suite `tests/test_symbol_index.py` (13 checks) covering the new behaviour — cold build,
warm reopen (asserts nothing reparses *and* the cache is not rewritten),
edit/add/delete delta, duplicate detection, touch-only reparse,
`find_usages`/word filters, dirty flag, `.tmp` purge, corrupt-cache
fallback, and cancellation. All pass, plus the two existing suites:

```
python tests/test_symbol_index.py            # ALL SYMBOL INDEX TESTS PASSED
python tests/test_session_persistence.py     # ALL CHECKS PASSED
python tests/test_panel_persistence.py       # ALL CHECKS PASSED
```

Responsiveness was measured with a 10ms heartbeat timer running against
the real standalone window while the index loads: window shown at 0.24s,
index ready at 1.96s, exactly one stall over 100ms (221ms).

**The compiled `.pyd` was verified functionally**, not by string search
(Cython 3.x compresses string literals — grepping the binary proves
nothing). Imported
`dist/MCAEditor-Maya2024/mca_core/symbol_index.cp310-win_amd64.pyd` with
the source tree off `sys.path` and confirmed cold index, cache write,
warm reopen without rewrite, and incremental refresh without duplicates.
This matters because the namedtuple/pickle path has broken under Cython
before (see the `SymbolEntry.__module__` note in the module header).

---

## Files touched

- `mca_core/symbol_index.py` — `enumerate_source_files()`, `plan_refresh()`,
  `adopt()`, `is_dirty()`, chunked v4 persistence, `_chunk_dict()`,
  `_purge_stale_temp_files()`, rewritten `IndexWorker` and `_parse_file`,
  `_all_files` removed, `_bulk_insert` replace semantics, MEL regex fix,
  widened `_SKIP_EXTS`.
- `mca_qt/editor_panel.py` — `_start_symbol_indexing()` no longer touches
  the disk; `_disk_cache_still_valid()` deleted; disk writes gated on
  `is_dirty()`; "Indexing…" status while the worker has nothing to count.
- `mca_core/activation.py` — `_LAUNCH_HTTP_TIMEOUT`, `_post_json(timeout=)`,
  auto-activation moved to a daemon thread.
- `tests/test_symbol_index.py` (new).
- `CHANGELOG.md`, `mca_core/__init__.py` (version).

No build-list changes needed. `symbol_index.py` and `activation.py` have
no Qt virtual overrides so they still compile to `.pyd`; `editor_panel.py`
was already on the `.pyc` list.

## Builds (done, v1.0.34)

Built with `C:/Python310/python.exe`, run sequentially (parallel builds
collide on shared Cython `.c` intermediates).

| Target | Build hash |
| --- | --- |
| Maya 2024 | `69cc06ed4f8b` |
| Maya 2025 | `58a96cf96469` |
| Maya 2026 | `d175cbc7e033` |

All three deployed to `~/Documents/maya/<version>/plug-ins/mcaEditor.py`.
Hashes differ, so Maya re-extracts the cache on next load — no manual
cache clear needed.

### Editor metadata was being indexed

`.mca-project` and the `.mca-session-*.json` manifests sit in the
workspace root and are rewritten on the panel's 400ms debounce. They were
being indexed, so `is_fresh_for()` reported **False** on an otherwise
untouched workspace and every launch rewrote the 57 MB cache. Now skipped
via `_SKIP_FILE_PREFIXES`. After the fix the verdict is True and the
cache is left alone.

The live caches on this machine were repaired ahead of the next launch,
so there is nothing to migrate or correct on first run:

```
Loaded symbol index from disk: 25703 files, 22 queued for reparse
Symbol index refresh: 25694 cached, 23 changed, 8 removed
repair run: 2.2s
mis-parsed 1-char proc symbols remaining: 0
editor metadata still indexed: 0
freshness verdict: True
```

**Not committed/pushed. UE builds not rebuilt. Website not redeployed.**

## Follow-ups worth considering

- The `_file_words` map is 74% of the cache and exists only to pre-filter
  Find-in-Files / Find Usages. Persisting it *inverted* (`word → file ids`
  as packed bytes) measured at 41.7 MB and **0.29s** to unpickle, and
  would turn `find_usages`'s 26k-iteration pre-filter into a single dict
  lookup. Not done here — it needs an overlay for files edited during the
  session so `update_file()` stays cheap.
- First-ever index on a cold filesystem cache took 214s on the reference
  project (29s warm). It's background work and now happens once per
  workspace rather than once per open, but a progress affordance beyond
  the status-bar percentage might be worth it.

---

# Addendum — Enter auto-indent bug (v1.0.35)

Reported after the perf work: pressing Enter while on a `class` or `def`
line indented that line.

**Cause.** `_handle_newline()` in `mca_qt/widgets/code_editor.py` derived
both the indentation and the block-opener check from `cursor.block().text()`
— the *whole* line — with no reference to the cursor's column. With the
caret at column 0 of `def foo():` it still saw the trailing colon, added
an indent level, and inserted `"\n" + indent` at column 0. The newline
landed above the definition and the indent landed in front of it, so the
`def` moved one level right.

Same shape for MEL lines ending in `{`, and for splitting mid-line:
`def foo(` + Enter picked up an indent from a colon further to the right.

**Fix.** Only the text left of the cursor is considered. When there is a
selection the probe uses `selectionStart()` — on a forward selection the
cursor position sits at the far end and can be on an entirely different
line, so reading the block under the cursor looked at the wrong text.

Auto-indent after a colon or brace at the end of a line is unchanged.

**Tests.** `tests/test_editor_indent.py` — 16 checks, headless Qt, drives
a real `MCACodeEditor`. Covers the reported cases, the behaviour that must
not regress, tab-indent mode, MEL braces, and both selection paths. Two of
my initial expectations were wrong (mid-body split, and the two selection
cases) — the code was right and the test was corrected, not the code.

Verified in the shipped artifacts: `code_editor.pyc` imported from each
`dist/MCAEditor-Maya*` with the source tree off `sys.path`, under mayapy
for the cp311 builds.

### Builds (done, v1.0.35)

| Target | Build hash |
| --- | --- |
| Maya 2024 | `007ac02f3741` |
| Maya 2025 | `d7b9aee35b45` |
| Maya 2026 | `83f6527bfdfe` |

All deployed. Still not committed/pushed; UE builds not rebuilt.

### Known limitation, not changed

`def foo():  # comment` + Enter does not indent — the colon is no longer
the last character. Pre-existing, unrelated to this fix, and correcting it
properly means not tripping over colons inside strings and comments.

---

# Addendum — Website deploy (v1.0.35)

Site went **1.0.32 → 1.0.35**. https://mcaeditor.com

v1.0.33 and v1.0.34 were never published, so this is the first public
release since 1.0.32.

## Two bugs in the deploy pipeline, found before publishing

**1. New zips would have been silently skipped.** `build_maya.py` writes
`MCAEditor-Maya2024-v1.0.35.zip`, but `_MAYA_ZIP_RE` in
`tools/deploy_website.py` matches `MCAEditor-Maya2024-Windows-v1.0.35.zip`.
Copying fresh builds into `dist/latest/` as-built matches nothing — the
upload loop just skips them and the deploy reports success having uploaded
no new Maya build at all. Staged under the expected `-Windows-` names.

**2. The site advertised downloads that did not exist.**
`_build_downloads_dict()` emitted an entry for every Maya year on *both*
platforms plus all three UE versions, unconditionally, regardless of what
had been built. With no macOS build since 1.0.32 that meant publishing
macOS buttons that 404. It now only lists a download when the matching zip
is actually staged, and `upload_releases()` skips a release with nothing
staged rather than publishing a version with no way to get it.

Verified before deploying:

```
v1.0.35  downloads=YES   (Maya 2024/25/26 win + UE 5.5/5.6/5.7)
v1.0.34  none (skipped)
v1.0.33  none (skipped)
```

## UE builds were stale

UE was still at 1.0.33. Built 5.5, 5.6 and 5.7 at 1.0.35 so the release is
complete for Windows.

## Public release notes rewritten

1.0.33/1.0.34 aren't offered as downloads (never published, and 1.0.34
shipped the two bugs found later that day). That would have buried the
entire performance story, which lived under the 1.0.34 heading — so the
1.0.35 entry was rewritten as the complete "since 1.0.32" list, in user
terms (open 7.6s → 0.3s, reopen 34–200s → under 2s) rather than the
internal debugging narrative.

## Verification

`curl` from this machine returns HTTP 000 — the sandbox blocks outbound
HTTPS, and the VPS cannot hairpin to its own public IP either. Neither is
a site fault. Verified from the VPS against localhost with a `Host` header:

```
served version.json  -> 1.0.35
served releases.json -> latest 1.0.35
Maya 2024/2025/2026 win zips -> HTTP 200
UE 5.5/5.6/5.7 zips          -> HTTP 200
macOS 1.0.35 zip             -> HTTP 404 (and nothing links to it)
```

nginx active, config valid, certs good to 2026-10-14.

## Still open

- **macOS.** `Nathans-Mac-mini.local` still does not resolve, so 1.0.35 is
  Windows-only. macOS users get the update notice but 1.0.32 remains the
  newest build for their platform. When the Mac is back: build the three
  Maya zips, stage them in `dist/latest/` as
  `MCAEditor-Maya<year>-macOS-v<ver>.zip`, re-run `deploy_website.py` —
  the new existence check picks them up with no further changes.
