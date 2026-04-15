# 2026-04-15 — Managed venv auto-recovers from host Python swaps

## Symptom

After an overnight Windows update, the Maya 2025/2026 editor terminal
silently fell back to the subprocess pipe with local echo.  Session log
showed:

```
mca_qt.widgets.terminal_backend : pywinpty import failed:
  No module named 'winpty.winpty'
mca_qt.widgets.terminal_backend :   Venv site-packages on sys.path:
  C:\Users\ncomes\Documents\mca_preferences\MCAEditor\.venv-3.11\Lib\site-packages
mca_qt.widgets.terminal_backend :   winpty/ directory found:
  [... 'winpty.cp310-win_amd64.pyd' ...]
mca_qt.widgets.terminal_native : Terminal start: no PTY available —
  using subprocess pipe with local echo
```

This is the second time a Windows update has broken the terminal this
way.

## Root cause

The ``.venv-3.11`` folder on disk had become a **Python 3.10** venv:

- ``pyvenv.cfg`` → ``home = C:\Python310`` / ``version = 3.10.8``
- ``Scripts/`` contained ``pip3.10.exe``
- ``winpty/`` contained ``winpty.cp310-win_amd64.pyd`` (cp310 ABI)

``venv_manager.get_venv_dir()`` picks the venv folder based on the
running ``sys.version_info`` (e.g. ``.venv-3.11`` when Maya 2025/2026
starts the editor), but the **contents** of that folder come from
whichever Python actually created the venv.  These can diverge when the
host Python gets replaced out from under us — exactly what a Windows
Update can do.  The cp310 extension silently fails to load under cp311
(``ModuleNotFoundError``), and ``terminal_backend.py`` falls through to
``terminal_native.py``'s subprocess fallback with no obvious root cause.

## One-shot fix applied to the user's machine

1. Renamed the broken ``.venv-3.11`` to ``.venv-3.11.broken-py310``.
2. Recreated with ``Maya2026\bin\mayapy.exe -m venv --without-pip …``
   (``pyvenv.cfg`` now says ``version = 3.11.9``).
3. Ran ``venv_manager.setup_venv()`` via mayapy to copy
   ``mayapy.exe → python.exe``, bootstrap pip, install
   ``pywinpty / pyflakes / openai``, and lay down ``sitecustomize.py``.
4. Verified ``from winpty import PTY`` now resolves to
   ``winpty.cp311-win_amd64.pyd``.
5. Deleted the ``.broken-py310`` backup.

Maya 2024's ``.venv-3.10`` was untouched — its ``pyvenv.cfg`` correctly
points to ``Maya2024\bin\mayapy.exe``.

## Defensive change in ``mca_core/venv_manager.py``

Added two pieces so the editor self-heals the next time this happens:

- **``_get_pyvenv_version(venv_dir)``** — reads ``pyvenv.cfg``'s
  ``version`` field and returns the ``(major, minor)`` tuple of ints,
  or ``None`` if unparseable.
- **``_check_venv_python_match()``** — compares that tuple against
  ``sys.version_info``.  On a confirmed mismatch, ``shutil.rmtree``s
  the venv with a loud ``logger.warning``.  Missing / unreadable
  ``pyvenv.cfg`` is treated as ambiguous and left alone (we only act
  on definite mismatches).

Wired into ``setup_venv()`` as **Step 0a**, ahead of the existing
MCA-version check (Step 0b) and ``ensure_venv()`` (Step 1).  Order
matters — we wipe before anything tries to import from site-packages.

### Smoke tests (all passing)

| Scenario                               | Expected   | Result |
|----------------------------------------|------------|--------|
| Real venv, matching Python             | preserved  | ✓      |
| Fake venv tagged with wrong version    | wiped      | ✓      |
| Fake venv tagged with matching version | preserved  | ✓      |
| Fake venv with no ``pyvenv.cfg``       | preserved  | ✓      |

## Gotchas for next time

- The fallback to ``terminal_native`` + subprocess pipe is silent
  except for one INFO-level log line; keep an eye on startup logs
  after any Python-related Windows Update.
- Maya's ``mayapy`` names the venv executable after itself
  (``mayapy.exe``) rather than ``python.exe``.  ``ensure_venv()``
  already copies ``mayapy.exe → python.exe`` after creation, so the
  automated rebuild path works the same as the manual one I ran.
- ``_check_venv_python_match()`` uses ``pyvenv.cfg``'s ``version``
  field, not the ``home`` directory.  That's intentional — ``home``
  can be valid while ``version`` is stale if someone rebuilt the
  venv against a different Python in the same install dir.
