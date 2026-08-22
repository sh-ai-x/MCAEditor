"""
Standalone correctness suite for the reworked symbol index.

Exercises the incremental-refresh path end to end against a throwaway
workspace so it never touches the developer's real prefs or projects.

Usage:
    python tests/test_symbol_index.py
"""

import os
import pickle
import shutil
import sys
import tempfile
import time

# Run from anywhere -- resolve the project root relative to this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mca_core.symbol_index as si

# The startup grace period exists to stay out of the DCC's way; it only
# slows the test down.
si._STARTUP_DELAY_SECS = 0.0


def run():
    """
    Build a scratch workspace and assert the index behaves correctly
    across cold build, warm reopen, incremental delta, and failure modes.

    :return: None.  Raises AssertionError on the first failure.
    """
    root = tempfile.mkdtemp(prefix="mca_idx_ws_")
    cache_dir = tempfile.mkdtemp(prefix="mca_idx_cache_")
    cache = os.path.join(cache_dir, "idx.pkl")

    def write(rel, text):
        """Write *text* to *rel* under the scratch root and return its path."""
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
        return os.path.normpath(path)

    def index_once():
        """Run a worker to completion against the scratch workspace."""
        index = si.SymbolIndex()
        worker = si.IndexWorker(index, [root], set(), cache_path=cache)
        worker.start()
        worker.join()
        return index

    a = write("pkg/a.py", "class Alpha:\n    def hello(self):\n        return beta_thing\n")
    b = write("pkg/b.py", "def beta_thing():\n    return Alpha\n")
    c = write("pkg/sub/c.mel", "global proc doThing()\n{\n}\n")
    # MEL source embedded in a .py file.  An invalidation rule keyed off
    # the file extension silently leaves stale symbols here.
    embedded = write("pkg/gen.py",
                     'MEL = """\nglobal proc embeddedProc()\n"""\n')
    write("pkg/huge.py", "x = 1\n" + ("# pad\n" * 200000))       # over the size gate
    write("pkg/img.png", "binary-ish")                            # skipped extension
    write("pkg/native.pyd", "binary-ish")                         # skipped extension
    write("pkg/__pycache__/junk.py", "def hidden(): pass\n")      # skipped directory

    # --- 1. one filter set, shared by the walk and the freshness check --
    files = si.enumerate_source_files([root])
    assert set(files) == {a, b, c, embedded}, sorted(files)
    print("PASS enumerate: oversized, binary and skip-dir files all excluded")

    # --- 1b. editor metadata must never be indexed ----------------------
    # The session manifests are rewritten on a debounce while the user
    # works.  Indexing them made every launch see "changed files" and
    # rewrite the whole multi-megabyte cache for nothing.
    write(".mca-project", "{}")
    write(".mca-session-Maya2025.json", "{}")
    write(".mca-session.json.bak", "{}")
    assert set(si.enumerate_source_files([root])) == {a, b, c, embedded}, \
        "editor metadata leaked into the index"
    print("PASS enumerate: editor metadata excluded")

    # --- 2. cold build ---------------------------------------------------
    index = index_once()
    assert index.get_state() == "ready"
    assert index.get_file_count() == 4, index.get_file_count()
    assert index.find_definitions("Alpha")
    assert index.find_definitions("beta_thing")
    assert index.find_definitions("doThing"), "MEL proc with no return type"
    assert not index.is_dirty(), "index should be clean immediately after save"
    assert os.path.isfile(cache)
    print("PASS cold build wrote a cache (%d bytes)" % os.path.getsize(cache))

    # --- 3. reopen with nothing changed ---------------------------------
    mtime_before = os.path.getmtime(cache)
    started = time.time()
    index = index_once()
    elapsed = time.time() - started
    assert index.get_file_count() == 4
    assert index.find_definitions("Alpha")
    assert not index.is_dirty(), "an unchanged workspace must not dirty the index"
    assert os.path.getmtime(cache) == mtime_before, "cache must not be rewritten"
    print("PASS warm reopen: nothing reparsed, nothing rewritten (%.3fs)" % elapsed)

    # --- 4. edit + add + delete -----------------------------------------
    # Sleep past the mtime tolerance so the change is detectable.
    time.sleep(1.1)
    write("pkg/b.py", "def beta_thing():\n    return Alpha\n\nclass Gamma:\n    pass\n")
    d = write("pkg/d.py", "def delta():\n    pass\n")
    os.remove(a)

    index = index_once()
    assert index.get_file_count() == 4, index.get_file_count()
    assert index.find_definitions("Gamma"), "edited file was not reparsed"
    assert index.find_definitions("delta"), "new file was not indexed"
    assert not index.find_definitions("Alpha"), "deleted file is still indexed"
    assert index.find_definitions("doThing"), "untouched file was lost"
    print("PASS incremental refresh: edit, add and delete all handled")

    # --- 4b. reparsing must replace, not duplicate ----------------------
    # A file that gets reparsed is already present in the index adopted
    # from the cache.  Appending its symbols a second time would make Go
    # To Declaration list the same line twice.
    for name in ("Gamma", "beta_thing", "delta", "doThing"):
        hits = index.find_definitions(name)
        assert len(hits) == len(set(hits)), "%s duplicated: %r" % (name, hits)
    total_by_name = sum(len(v) for v in index._symbols_by_name.values())
    total_by_file = sum(len(v) for v in index._symbols_by_file.values())
    assert total_by_name == total_by_file, (total_by_name, total_by_file)
    print("PASS reparse replaces entries instead of duplicating them")

    # --- 5. the delta survives a round trip through the cache -----------
    index = index_once()
    assert index.get_file_count() == 4
    assert index.find_definitions("Gamma") and index.find_definitions("delta")
    assert not index.find_definitions("Alpha")
    print("PASS refreshed delta persisted to the cache")

    # --- 6. query surfaces that used to read _all_files -----------------
    b_path = os.path.normpath(os.path.join(root, "pkg", "b.py"))
    hits = index.find_usages("Alpha")
    assert any(hit[0] == b_path for hit in hits), hits
    assert index.get_files_with_word("Gamma") == [b_path]
    assert index.get_files_containing_substring("amm") == [b_path]
    assert len(index.get_all_files()) == 4
    print("PASS find_usages / word filters / get_all_files")

    # --- 7. dirty tracking ----------------------------------------------
    assert not index.is_dirty()
    index.update_file(d)
    assert index.is_dirty(), "update_file must mark the index dirty"
    print("PASS dirty flag drives the save decision")

    # --- 8. abandoned temp files get cleaned up -------------------------
    orphan = cache + ".tmp.999.888"
    with open(orphan, "w") as handle:
        handle.write("x" * 100)
    index_once()
    assert not os.path.exists(orphan), "stale temp file was not purged"
    print("PASS stale .tmp purge")

    # --- 9. a corrupt cache degrades to a clean full scan ---------------
    with open(cache, "wb") as handle:
        handle.write(b"garbage, definitely not a pickle")
    index = index_once()
    assert index.get_state() == "ready" and index.get_file_count() == 4
    print("PASS corrupt cache falls back to a full rebuild")

    # --- 10. freshness agrees with the indexer --------------------------
    assert index.is_fresh_for([root]), "freshness must hold right after a scan"
    print("PASS is_fresh_for is True on an untouched workspace")

    # --- 10b. a pure mtime touch reparses without changing the totals ---
    before_files = index.get_file_count()
    before_symbols = index.get_symbol_count()
    time.sleep(1.1)
    os.utime(c, None)
    index = index_once()
    assert index.get_file_count() == before_files
    assert index.get_symbol_count() == before_symbols, (
        before_symbols, index.get_symbol_count())
    print("PASS touch-only reparse leaves symbol totals unchanged")

    # --- 10c. an older cache schema is upgraded, not thrown away --------
    # Discarding it would mean re-reading every file in the workspace off
    # disk, which on a large project is minutes of the DCC feeling hung.
    old_mel_symbol = "g"          # what the pre-fix MEL regex produced
    entry_tuples = {
        fp: [tuple(e) for e in entries]
        for fp, entries in index._symbols_by_file.items()
    }
    # Rewrite the .mel file's entry the way the old, buggy parser would have.
    for fp in list(entry_tuples):
        if fp.lower().endswith(".mel"):
            entry_tuples[fp] = [(old_mel_symbol, "global_proc", fp, 1,
                                 "global proc doThing()", 0)]
        elif os.path.basename(fp) == "gen.py":
            # Embedded MEL in a .py file, mis-parsed the old way.  An
            # extension-based invalidation rule misses this entirely.
            entry_tuples[fp] = [(old_mel_symbol, "global_proc", fp, 2,
                                 "global proc embeddedProc()", 0)]
    legacy = {
        "magic": si._CACHE_MAGIC,
        "version": 2,
        "symbols_by_name": {},          # v2 wrote it; the upgrade rebuilds it
        "symbols_by_file": entry_tuples,
        "file_mtimes": dict(index._file_mtimes),
        "file_words": dict(index._file_words),
        "all_files": list(entry_tuples),
    }
    with open(cache, "wb") as handle:
        pickle.dump(legacy, handle, protocol=4)

    upgraded = si.SymbolIndex.load_from_disk(cache)
    assert upgraded is not None, "legacy cache was discarded instead of upgraded"
    assert upgraded.is_dirty(), "upgraded index must be flagged for rewrite"
    assert upgraded.find_definitions("delta"), "python entries lost on upgrade"

    index = index_once()
    assert index.get_file_count() == 4, index.get_file_count()
    assert index.find_definitions("delta"), "reused entry lost after upgrade"
    assert index.find_definitions("doThing"), "MEL was not reparsed on upgrade"
    assert index.find_definitions("embeddedProc"),         "MEL embedded in a .py file was not reparsed on upgrade"
    assert not index.find_definitions(old_mel_symbol),         "stale mis-parsed MEL symbol survived the upgrade"
    with open(cache, "rb") as handle:
        assert pickle.Unpickler(handle).load()["version"] == si._CACHE_SCHEMA_VERSION
    print("PASS legacy cache schema upgraded in place, MEL entries corrected")

    # --- 11. a cancelled worker never publishes a partial index ---------
    partial = si.SymbolIndex()
    worker = si.IndexWorker(partial, [root], set(), cache_path=cache)
    worker.cancel()
    worker.start()
    worker.join()
    assert partial.get_state() != "ready", partial.get_state()
    print("PASS cancelled worker never reports 'ready'")

    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(cache_dir, ignore_errors=True)
    print("\nALL SYMBOL INDEX TESTS PASSED")


if __name__ == "__main__":
    run()
