"""
Standalone verification for MCA Editor session persistence hardening.

Exercises the SessionManager durability guarantees without needing Qt or a
running DCC:

    1. Atomic writes leave no truncated file and no stray .tmp
    2. session.json.bak rotation keeps the last non-empty manifest
    3. A corrupt session.json falls back to the backup
    4. A corrupt session.json with no backup sets last_load_was_corrupt
    5. An empty session never overwrites a good backup
    6. Recovery snapshot save / load / clear round-trips
    7. Stale recovery snapshots are purged by age

Run with:  python test_session_persistence.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

# Import the repo package before anything creates the real prefs dir.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import mca_core
from mca_core import session_manager as sm


# --- Test harness ------------------------------------------------------------

FAILURES = []


def check(label, condition, detail=""):
    """Record a pass/fail result and print it."""
    if condition:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}  {}".format(label, detail))
        FAILURES.append(label)


def make_layout(tab_paths):
    """Build a minimal v3 layout tree containing one group of file tabs."""
    return {
        "type": "splitter",
        "orientation": "horizontal",
        "sizes": [],
        "children": [
            {
                "type": "group",
                "tabs": [
                    {"type": "file", "file_path": p, "language": "python",
                     "title": os.path.basename(p)}
                    for p in tab_paths
                ],
                "active_tab": 0,
            }
        ],
    }


def new_manager(tmp_root):
    """Create a SessionManager rooted at a throwaway prefs directory."""
    # get_prefs_dir is read at SessionManager.__init__ time, so patch the
    # module attribute the function returns.
    mca_core._prefs_dir = tmp_root
    return sm.SessionManager(dcc_version="TestDCC")


# --- Tests -------------------------------------------------------------------

def test_atomic_write(tmp_root):
    print("\n[1] atomic_write")
    target = os.path.join(tmp_root, "sub", "dir", "file.txt")

    ok = sm.atomic_write(target, "hello world")
    check("creates missing parent dirs and writes", ok and os.path.isfile(target))
    check("content is exact",
          open(target, encoding="utf-8").read() == "hello world")
    check("no stray .tmp left behind", not os.path.exists(target + ".tmp"))

    # Overwrite an existing read-only file (the Perforce case).
    import stat as _stat
    os.chmod(target, _stat.S_IREAD)
    ok = sm.atomic_write(target, "second write")
    check("overwrites a read-only destination", ok,
          "(read-only overwrite failed)")
    check("read-only overwrite content correct",
          open(target, encoding="utf-8").read() == "second write")


def test_manifest_backup_rotation(tmp_root):
    print("\n[2] manifest backup rotation")
    mgr = new_manager(tmp_root)
    path = mgr.default_manifest_path

    mgr.save_manifest_v3(make_layout(["a.py", "b.py"]), 0)
    check("manifest written", os.path.isfile(path))
    check("no backup on first write", not os.path.isfile(path + ".bak"))

    mgr.save_manifest_v3(make_layout(["c.py"]), 0)
    check("backup created on second write", os.path.isfile(path + ".bak"))

    backup = json.load(open(path + ".bak", encoding="utf-8"))
    check("backup holds the PREVIOUS session (2 tabs)",
          mgr._count_tabs_in_tree(backup["layout"]) == 2,
          "got {}".format(mgr._count_tabs_in_tree(backup["layout"])))


def test_corrupt_falls_back_to_backup(tmp_root):
    print("\n[3] corrupt manifest falls back to backup")
    mgr = new_manager(tmp_root)
    path = mgr.default_manifest_path

    mgr.save_manifest_v3(make_layout(["one.py", "two.py", "three.py"]), 0)
    mgr.save_manifest_v3(make_layout(["one.py", "two.py", "three.py"]), 0)

    # Simulate the classic failure: truncated mid-write by a crash.
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"version": 3, "layo')

    loaded = mgr.load_manifest()
    check("recovered a manifest from backup", loaded is not None)
    check("recovered manifest has all 3 tabs",
          loaded is not None
          and mgr._count_tabs_in_tree(loaded.get("layout")) == 3,
          "got {}".format(loaded and mgr._count_tabs_in_tree(loaded.get("layout"))))
    check("not flagged corrupt (backup succeeded)",
          not mgr.last_load_was_corrupt)


def test_corrupt_no_backup_sets_flag(tmp_root):
    print("\n[4] corrupt manifest with no backup -> locked")
    mgr = new_manager(tmp_root)
    path = mgr.default_manifest_path

    mgr._ensure_dirs()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("}}} not json at all")

    loaded = mgr.load_manifest()
    check("returns None", loaded is None)
    check("last_load_was_corrupt is True", mgr.last_load_was_corrupt)

    # And a fresh manager on a directory with NO manifest must not be flagged.
    shutil.rmtree(os.path.join(tmp_root, "TestDCC"), ignore_errors=True)
    mgr2 = new_manager(tmp_root)
    check("missing manifest is NOT flagged corrupt",
          mgr2.load_manifest() is None and not mgr2.last_load_was_corrupt)


def test_empty_never_clobbers_backup(tmp_root):
    print("\n[5] empty session never overwrites a good backup")
    mgr = new_manager(tmp_root)
    path = mgr.default_manifest_path

    mgr.save_manifest_v3(make_layout(["keep1.py", "keep2.py"]), 0)
    mgr.save_manifest_v3(make_layout(["keep1.py", "keep2.py"]), 0)

    # User closes every tab, then the editor saves repeatedly.
    empty = {"type": "splitter", "orientation": "horizontal", "sizes": [],
             "children": [{"type": "group", "tabs": [], "active_tab": 0}]}
    for _ in range(3):
        mgr.save_manifest_v3(empty, 0)

    backup = json.load(open(path + ".bak", encoding="utf-8"))
    check("backup still holds the 2-tab session",
          mgr._count_tabs_in_tree(backup["layout"]) == 2,
          "got {}".format(mgr._count_tabs_in_tree(backup["layout"])))


def test_recovery_roundtrip(tmp_root):
    print("\n[6] recovery snapshot round-trip")
    mgr = new_manager(tmp_root)

    source = os.path.join(tmp_root, "script.py")
    with open(source, "w", encoding="utf-8") as handle:
        handle.write("print('on disk')\n")

    unsaved = "print('unsaved edits')\n# more work\n"
    check("snapshot written", mgr.save_recovery(source, unsaved))

    loaded = mgr.load_recovery(source)
    check("snapshot loads", loaded is not None)
    check("content round-trips exactly", loaded and loaded[0] == unsaved,
          repr(loaded and loaded[0]))
    check("metadata records the original path",
          loaded and loaded[1].get("file_path") == source)

    mgr.clear_recovery(source)
    check("clear_recovery removes it", mgr.load_recovery(source) is None)

    # Two different files must not collide.
    other = os.path.join(tmp_root, "other.py")
    mgr.save_recovery(source, "A")
    mgr.save_recovery(other, "B")
    check("distinct files get distinct snapshots",
          mgr.load_recovery(source)[0] == "A"
          and mgr.load_recovery(other)[0] == "B")

    # Path normalization: same file, differently spelled.
    weird = source.replace("\\", "/").replace(":/", ":\\") if os.sep == "\\" else source
    alt = os.path.join(os.path.dirname(source), ".", os.path.basename(source))
    check("normalized paths hit the same snapshot",
          mgr.load_recovery(alt) is not None
          and mgr.load_recovery(alt)[0] == "A")


def test_purge_stale(tmp_root):
    print("\n[7] stale recovery purge")
    mgr = new_manager(tmp_root)

    fresh = os.path.join(tmp_root, "fresh.py")
    old = os.path.join(tmp_root, "old.py")
    mgr.save_recovery(fresh, "fresh content")
    mgr.save_recovery(old, "old content")

    # Backdate the old snapshot past the threshold.
    key = mgr._recovery_key(old)
    snap = os.path.join(mgr._recovery_dir, key + ".snapshot")
    ancient = time.time() - (40 * 24 * 60 * 60)
    os.utime(snap, (ancient, ancient))

    removed = mgr.purge_stale_recoveries()
    check("one snapshot purged", removed == 1, "removed={}".format(removed))
    check("old snapshot gone", mgr.load_recovery(old) is None)
    check("fresh snapshot kept", mgr.load_recovery(fresh) is not None)


# --- Entry point -------------------------------------------------------------

def main():
    """Run every test in an isolated temp prefs directory."""
    tests = [
        test_atomic_write,
        test_manifest_backup_rotation,
        test_corrupt_falls_back_to_backup,
        test_corrupt_no_backup_sets_flag,
        test_empty_never_clobbers_backup,
        test_recovery_roundtrip,
        test_purge_stale,
    ]

    for test in tests:
        tmp_root = tempfile.mkdtemp(prefix="mca_session_test_")
        try:
            test(tmp_root)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n" + "=" * 60)
    if FAILURES:
        print("{} FAILURE(S): {}".format(len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
