"""
Headless integration test for MCA Editor tab persistence.

Builds a real MCAEditorPanel against a throwaway preferences directory and
an in-memory settings backend (so the user's own QSettings and session are
never touched), then verifies the behaviours that were losing people's work:

    1. Tabs are on disk immediately after the panel initializes
    2. Creating a new tab writes the manifest right away
    3. Opening a file writes the manifest right away
    4. Ctrl+S (_save_file) persists content and the manifest
    5. A simulated crash (no cleanup()) still restores every tab
    6. Autosave writes a recovery snapshot without touching the real file
    7. A crash with unsaved edits restores those edits on next launch
    8. A corrupt manifest is NOT overwritten by the fresh blank session
    9. A tab whose file went missing survives in the manifest

Run with:  python test_panel_persistence.py
"""

import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import mca_core
from mca_core.config.settings import MCASettings

from PySide6.QtWidgets import QApplication

FAILURES = []


def check(label, condition, detail=""):
    """Record a pass/fail result and print it."""
    if condition:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}  {}".format(label, detail))
        FAILURES.append(label)


def make_settings():
    """Build an MCASettings backed by a plain dict (no registry writes)."""
    return MCASettings(backend={})


def make_panel(tmp_root):
    """
    Construct a panel rooted at *tmp_root*.

    Patching ``mca_core._prefs_dir`` before construction points the
    SessionManager at the throwaway directory.
    """
    mca_core._prefs_dir = tmp_root
    from mca_qt.editor_panel import MCAEditorPanel
    return MCAEditorPanel(make_settings(), dcc_version="TestDCC")


def manifest_paths(tmp_root):
    """Return every file_path recorded in the session manifest on disk."""
    path = os.path.join(tmp_root, "TestDCC", "session.json")
    if not os.path.isfile(path):
        return None
    data = json.load(open(path, encoding="utf-8"))

    found = []

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "group":
            for tab in node.get("tabs", []):
                found.append(tab.get("file_path") or tab.get("buffer_file"))
        for child in node.get("children", []):
            walk(child)

    walk(data.get("layout"))
    return found


def tab_paths(panel):
    """Return the file paths of every tab currently open in *panel*."""
    return [p for _e, _n, p in panel._group_container.all_editors()]


# --- Tests -------------------------------------------------------------------

def test_startup_and_new_tab(tmp_root):
    print("\n[1] startup + new tab persistence")
    panel = make_panel(tmp_root)

    recorded = manifest_paths(tmp_root)
    check("manifest exists immediately after init", recorded is not None)
    check("starter tabs are recorded", recorded and len(recorded) >= 1,
          "got {}".format(recorded))

    before = len(recorded or [])
    panel._new_python_buffer()
    after = manifest_paths(tmp_root)
    check("new tab hits disk with no explicit save",
          after is not None and len(after) == before + 1,
          "before={} after={}".format(before, after and len(after)))

    panel.deleteLater()


def test_open_file_persisted(tmp_root):
    print("\n[2] opening a file is recorded immediately")
    target = os.path.join(tmp_root, "opened_script.py")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("# opened from disk\n")

    panel = make_panel(tmp_root)
    panel._open_file_path(target)

    recorded = manifest_paths(tmp_root)
    check("opened file present in manifest on disk",
          recorded is not None and target in recorded,
          "got {}".format(recorded))
    panel.deleteLater()


def test_crash_restores_tabs(tmp_root):
    print("\n[3] simulated crash restores every tab")
    files = []
    for name in ("alpha.py", "beta.py", "gamma.py"):
        path = os.path.join(tmp_root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# {}\n".format(name))
        files.append(path)

    panel = make_panel(tmp_root)
    for path in files:
        panel._open_file_path(path)
    opened = tab_paths(panel)

    # Simulate a hard crash: drop the panel WITHOUT calling cleanup().
    panel.deleteLater()
    del panel

    revived = make_panel(tmp_root)
    restored = tab_paths(revived)

    for path in files:
        check("restored after crash: {}".format(os.path.basename(path)),
              path in restored,
              "restored={}".format([os.path.basename(p or "") for p in restored]))
    check("no tabs lost overall", len(restored) >= len(opened),
          "opened={} restored={}".format(len(opened), len(restored)))
    revived.deleteLater()


def test_autosave_snapshot(tmp_root):
    print("\n[4] autosave snapshots without touching the real file")
    target = os.path.join(tmp_root, "work_in_progress.py")
    original = "# original content\n"
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(original)

    panel = make_panel(tmp_root)
    panel._open_file_path(target)

    editor = None
    for candidate, _n, path in panel._group_container.all_editors():
        if path == target:
            editor = candidate
    check("target tab is open", editor is not None)

    editor.setPlainText("# UNSAVED EDITS\nvalue = 42\n")
    editor.document().setModified(True)

    panel._on_autosave_tick()

    on_disk = open(target, encoding="utf-8").read()
    check("real file untouched by snapshot autosave", on_disk == original,
          repr(on_disk))

    snapshot = panel._session_manager.load_recovery(target)
    check("recovery snapshot written", snapshot is not None)
    check("snapshot holds the unsaved edits",
          snapshot and "UNSAVED EDITS" in snapshot[0])

    panel.deleteLater()


def test_crash_recovers_unsaved_edits(tmp_root):
    print("\n[5] crash with unsaved edits -> edits come back")
    target = os.path.join(tmp_root, "recover_me.py")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("# saved version\n")

    panel = make_panel(tmp_root)
    panel._open_file_path(target)
    for candidate, _n, path in panel._group_container.all_editors():
        if path == target:
            candidate.setPlainText("# saved version\nlost_work = True\n")
            candidate.document().setModified(True)
    panel._on_autosave_tick()

    # Hard crash -- no cleanup().
    panel.deleteLater()
    del panel

    revived = make_panel(tmp_root)
    recovered_text = None
    modified_flag = None
    for candidate, _n, path in revived._group_container.all_editors():
        if path == target:
            recovered_text = candidate.toPlainText()
            modified_flag = candidate.document().isModified()

    check("tab restored", recovered_text is not None)
    check("unsaved edits recovered",
          recovered_text and "lost_work = True" in recovered_text,
          repr(recovered_text))
    check("tab marked modified so user sees the '*'", modified_flag is True)
    revived.deleteLater()


def test_explicit_save_clears_snapshot(tmp_root):
    print("\n[6] Ctrl+S writes through and clears the snapshot")
    target = os.path.join(tmp_root, "save_me.py")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("# before\n")

    panel = make_panel(tmp_root)
    panel._open_file_path(target)

    group, idx, editor = panel._group_container.find_editor_by_path(target)
    group.set_current_index(idx)
    panel._group_container._on_group_activated(group)
    editor.setPlainText("# after ctrl+s\n")
    editor.document().setModified(True)
    panel._save_recovery_snapshot(editor)
    check("snapshot exists before save",
          panel._session_manager.load_recovery(target) is not None)

    panel._save_file()

    check("file content written",
          open(target, encoding="utf-8").read() == "# after ctrl+s\n",
          repr(open(target, encoding="utf-8").read()))
    check("modified flag cleared", not editor.document().isModified())
    check("stale snapshot cleared after save",
          panel._session_manager.load_recovery(target) is None)
    panel.deleteLater()


def test_autosave_to_file_optin(tmp_root):
    print("\n[6b] opt-in autosave writes straight to the file")
    target = os.path.join(tmp_root, "direct.py")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("# before\n")

    panel = make_panel(tmp_root)
    panel._settings.set("autosave_to_file", True)
    panel._open_file_path(target)

    _g, _i, editor = panel._group_container.find_editor_by_path(target)
    editor.setPlainText("# written by autosave\n")
    editor.document().setModified(True)

    panel._on_autosave_tick()

    check("real file updated by opt-in autosave",
          open(target, encoding="utf-8").read() == "# written by autosave\n",
          repr(open(target, encoding="utf-8").read()))
    check("no snapshot left after a successful direct write",
          panel._session_manager.load_recovery(target) is None)

    # And with the opt-in OFF the file must stay untouched.
    panel._settings.set("autosave_to_file", False)
    editor.setPlainText("# should NOT reach the file\n")
    editor.document().setModified(True)
    panel._on_autosave_tick()
    check("file untouched when opt-in is off",
          open(target, encoding="utf-8").read() == "# written by autosave\n",
          repr(open(target, encoding="utf-8").read()))
    check("snapshot taken instead",
          panel._session_manager.load_recovery(target) is not None)
    panel.deleteLater()


def test_corrupt_manifest_preserved(tmp_root):
    print("\n[7] corrupt manifest is preserved, not overwritten")
    panel = make_panel(tmp_root)
    panel._new_python_buffer()
    panel.deleteLater()
    del panel

    manifest = os.path.join(tmp_root, "TestDCC", "session.json")
    backup = manifest + ".bak"
    if os.path.exists(backup):
        os.remove(backup)
    corrupt = '{"version": 3, "layout": {"type": "spli'
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write(corrupt)

    revived = make_panel(tmp_root)
    check("panel started despite corrupt manifest", revived is not None)
    check("manifest write is locked", revived._session_manifest_locked is True)

    # Force saves -- none of them may touch the file.
    revived._new_python_buffer()
    revived._save_session_manifest()

    still = open(manifest, encoding="utf-8").read()
    check("corrupt manifest left intact for manual recovery", still == corrupt,
          repr(still[:60]))
    revived.deleteLater()


def test_auto_open_project_keeps_default_session(tmp_root):
    """
    The regression that was blanking people's default session.

    When a project auto-opens at startup, __init__ deliberately skips the
    default-session restore, then _open_project calls _save_context_session()
    on the still-empty container.  Without the empty-session guard that
    wrote a zero-tab session.json straight over the user's default tabs,
    which they then lost the moment they closed the project.
    """
    print("\n[9] auto-opening a project must not blank the default session")

    from mca_core.project import create_default_project

    # --- Build a default (non-project) session with real tabs ---
    default_files = []
    for name in ("default_one.py", "default_two.py"):
        path = os.path.join(tmp_root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# {}\n".format(name))
        default_files.append(path)

    panel = make_panel(tmp_root)
    for path in default_files:
        panel._open_file_path(path)
    settings_backend = panel._settings
    check("default session recorded 2 tabs",
          all(p in (manifest_paths(tmp_root) or []) for p in default_files),
          "got {}".format(manifest_paths(tmp_root)))
    panel.cleanup()
    panel.deleteLater()
    del panel

    before = manifest_paths(tmp_root)

    # --- Create a project and mark it as the last-opened one ---
    project_root = os.path.join(tmp_root, "SomeProject")
    os.makedirs(project_root, exist_ok=True)
    create_default_project(project_root, "SomeProject", [], dcc_tag="TestDCC")

    mca_core._prefs_dir = tmp_root
    from mca_qt.editor_panel import MCAEditorPanel
    settings = make_settings()
    settings.set("last_project_path", project_root)

    revived = MCAEditorPanel(settings, dcc_version="TestDCC")
    check("project auto-opened", revived._active_project is not None,
          "active_project={}".format(revived._active_project))

    after = manifest_paths(tmp_root)
    check("default session.json NOT blanked by the project auto-open",
          after == before,
          "before={} after={}".format(before, after))

    # --- Closing the project must bring the default tabs back ---
    revived._close_project()
    restored = tab_paths(revived)
    for path in default_files:
        check("default tab back after closing project: {}".format(
                  os.path.basename(path)),
              path in restored,
              "tabs={}".format([os.path.basename(p or "") for p in restored]))
    revived.deleteLater()


def test_missing_file_tab_survives(tmp_root):
    print("\n[8] tab for a temporarily missing file survives")
    target = os.path.join(tmp_root, "on_a_network_share.py")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("# remote file\n")

    panel = make_panel(tmp_root)
    panel._open_file_path(target)
    panel.deleteLater()
    del panel

    # The share goes offline.
    os.remove(target)

    revived = make_panel(tmp_root)
    recorded = manifest_paths(tmp_root)
    check("missing file still recorded in manifest",
          recorded is not None and target in recorded,
          "got {}".format(recorded))
    revived.deleteLater()
    del revived

    # The share comes back.
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("# remote file\n")

    final = make_panel(tmp_root)
    check("tab reopens once the file returns", target in tab_paths(final),
          "tabs={}".format(tab_paths(final)))
    final.deleteLater()


# --- Entry point -------------------------------------------------------------

def main():
    """Run every panel test in its own isolated preferences directory."""
    app = QApplication.instance() or QApplication(sys.argv)

    tests = [
        test_startup_and_new_tab,
        test_open_file_persisted,
        test_crash_restores_tabs,
        test_autosave_snapshot,
        test_crash_recovers_unsaved_edits,
        test_explicit_save_clears_snapshot,
        test_autosave_to_file_optin,
        test_corrupt_manifest_preserved,
        test_auto_open_project_keeps_default_session,
        test_missing_file_tab_survives,
    ]

    for test in tests:
        tmp_root = tempfile.mkdtemp(prefix="mca_panel_test_")
        try:
            test(tmp_root)
        except Exception:
            import traceback
            print("  ERROR in {}".format(test.__name__))
            traceback.print_exc()
            FAILURES.append(test.__name__ + " (exception)")
        finally:
            app.processEvents()
            shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n" + "=" * 60)
    if FAILURES:
        print("{} FAILURE(S):".format(len(FAILURES)))
        for item in FAILURES:
            print("  - {}".format(item))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
