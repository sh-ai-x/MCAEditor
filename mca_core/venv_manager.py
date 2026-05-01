"""
MCA Core - Virtual Environment Manager.

Creates and manages a Python venv inside ``mca_preferences/`` to hold
all MCA Editor dependencies (pywinpty, pyflakes, future AI packages).
This keeps Maya's Python and the system Python completely clean.

The venv directory is versioned by Python major.minor (e.g.
``.venv-3.10``, ``.venv-3.11``) so that Maya 2024 (Python 3.10) and
Maya 2025 (Python 3.11) each get their own venv with compatible
compiled extensions.  The standalone editor gets its own too.

Both standalone and Maya modes call into this module at startup.  Normal
startup is just a ``sys.path.insert()`` — fast.  The venv is only created
(and packages installed) on first launch or when new requirements appear.

Storage layout::

    ~/Documents/mca_preferences/
        .venv-3.11/               # Managed venv (versioned by Python)
            pyvenv.cfg
            Scripts/              # Windows (or bin/ on Linux/Mac)
                python.exe        # Venv Python — used for subprocess terminal
            Lib/
                site-packages/    # pywinpty, pyflakes, etc.

Dependencies:
    - None (pure Python stdlib).  Subprocess calls to pip happen only when
      packages are missing.

Side effects:
    - Creates ``.venv-X.Y/`` under ``mca_preferences/`` on first call
    - Runs ``pip install`` for missing packages (network access required)
    - Modifies ``sys.path`` when ``inject_venv_path()`` is called
"""

import logging
import os
import platform
import shutil
import subprocess
import sys

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Constants ----------------------------------------------------------------

# Base preferences directory under the user's Documents folder.
# Centralized in mca_core.__init__.get_prefs_dir().
from mca_core import get_prefs_dir
_PREFS_DIR = get_prefs_dir()

# Base name of the venv directory. The actual directory is versioned by
# Python major.minor to avoid ABI conflicts when multiple Maya versions
# are installed (e.g. Maya 2024 = Python 3.10, Maya 2025 = Python 3.11).
# Each gets its own venv:  .venv-3.10/  .venv-3.11/  etc.
_VENV_DIR_BASE = ".venv"

# Version marker file placed inside the venv.  When the MCA Editor
# version changes (user installs a new plugin build), the venv is
# wiped and rebuilt so no stale packages linger.
_VENV_VERSION_FILE = ".mca_venv_version"

# Packages required for v1 of MCA Editor.
# Maps pip package name (for install) → importable module name (for checking).
# These don't always match (e.g. pywinpty installs as "winpty").
REQUIRED_PACKAGES = {
    "pywinpty>=2.0.0": "winpty",     # Terminal backend (Windows only)
    "pyflakes": "pyflakes",          # Tier 2 code analysis
    "openai>=1.30.0": "openai",     # AI chat (Anthropic/OpenAI/Gemini via OAI compat)
}

# Timeout (seconds) for subprocess calls to pip / venv creation.
_SUBPROCESS_TIMEOUT = 120

# Suppress CMD window popups on Windows.  Every subprocess.run() call
# flashes a visible console window unless CREATE_NO_WINDOW is set.
# On non-Windows platforms this flag is zero (no-op).
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

# Template for sitecustomize.py placed in the venv's site-packages.
# Maya's compiled extensions (e.g. _ssl.pyd) depend on runtime DLLs
# (libssl, libcrypto) that live in Maya's bin directory.  Python 3.8+
# on Windows no longer searches PATH for DLLs — os.add_dll_directory()
# is required.  This sitecustomize runs at interpreter startup and
# registers Maya's bin so all compiled extensions can load.
_SITECUSTOMIZE_SRC = '''\
"""
MCA Editor venv sitecustomize.

Adds Maya's bin directory to the DLL search path so compiled extensions
like _ssl.pyd can find their runtime dependencies (libssl, libcrypto).
Python 3.8+ on Windows requires os.add_dll_directory() for this.
"""
import os


def _add_maya_dll_dir():
    """Read pyvenv.cfg and add Maya bin dir to DLL search path."""
    # Navigate from site-packages up to the venv root:
    # site-packages/ -> Lib/ -> .venv-X.Y/
    _venv_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    _cfg = os.path.join(_venv_root, "pyvenv.cfg")
    if not os.path.isfile(_cfg):
        return
    with open(_cfg) as _f:
        for _line in _f:
            if _line.startswith("home"):
                _maya_bin = _line.split("=", 1)[1].strip()
                if os.path.isdir(_maya_bin) and hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(_maya_bin)
                return


_add_maya_dll_dir()
'''


# --- Venv Location ------------------------------------------------------------

def get_venv_dir():
    """
    Return the full path to the managed venv directory for the current
    Python version.

    Versioned by Python major.minor so Maya 2024 (3.10) and Maya 2025
    (3.11) each get their own venv with compatible compiled extensions.

    :return: Absolute path to the venv directory.
    :rtype: str
    """
    version_tag = "{}.{}".format(sys.version_info.major, sys.version_info.minor)
    venv_name = "{}-{}".format(_VENV_DIR_BASE, version_tag)
    return os.path.join(_PREFS_DIR, venv_name)


def get_venv_python():
    """
    Return the absolute path to the venv's Python executable.

    On Windows this is ``.venv-X.Y/Scripts/python.exe``; on POSIX it is
    ``.venv-X.Y/bin/python``.

    :return: Path to the venv Python, or *None* if the venv doesn't exist.
    :rtype: str or None
    """
    venv_dir = get_venv_dir()

    if platform.system() == "Windows":
        # Check for python.exe first, then mayapy.exe — Maya's venv module
        # names the venv executable after the source interpreter (mayapy.exe)
        # instead of the standard python.exe.
        for exe_name in ("python.exe", "mayapy.exe"):
            candidate = os.path.join(venv_dir, "Scripts", exe_name)
            if os.path.isfile(candidate):
                return candidate
        return None
    else:
        # POSIX: check python first, then mayapy — Maya's venv module may
        # name the executable after the source interpreter (mayapy).
        for exe_name in ("python", "mayapy", "python3"):
            candidate = os.path.join(venv_dir, "bin", exe_name)
            if os.path.isfile(candidate):
                return candidate
        return None


def get_venv_site_packages():
    """
    Return the path to the venv's ``site-packages`` directory.

    Works by inspecting the venv layout directly rather than running
    Python inside it (faster).  Returns *None* if the venv doesn't
    exist yet.

    :return: Absolute path, or *None* if the venv doesn't exist yet.
    :rtype: str or None
    """
    venv_dir = get_venv_dir()

    if not os.path.isdir(venv_dir):
        return None

    if platform.system() == "Windows":
        # Windows: .venv-X.Y/Lib/site-packages
        site_pkg = os.path.join(venv_dir, "Lib", "site-packages")
    else:
        # POSIX: .venv-X.Y/lib/pythonX.Y/site-packages
        # Need to find the pythonX.Y directory dynamically.
        lib_dir = os.path.join(venv_dir, "lib")
        if not os.path.isdir(lib_dir):
            return None
        for name in os.listdir(lib_dir):
            if name.startswith("python"):
                site_pkg = os.path.join(lib_dir, name, "site-packages")
                if os.path.isdir(site_pkg):
                    return site_pkg
        return None

    if os.path.isdir(site_pkg):
        return site_pkg
    return None


# --- Venv Creation ------------------------------------------------------------

def ensure_venv():
    """
    Create the managed venv if it doesn't already exist.

    Uses ``sys.executable`` (which may be mayapy or system python) to run
    ``python -m venv``.  The venv inherits the host's Python version and
    ABI, so compiled extensions (like pywinpty) are compatible.

    Does nothing if the venv already exists and has a valid Python
    executable.

    :return: *True* if the venv is ready (created or already existed),
             *False* if creation failed.
    :rtype: bool
    """
    venv_dir = get_venv_dir()

    # If the venv Python already exists, nothing to do.
    if get_venv_python() is not None:
        logger.debug("Venv already exists at %s", venv_dir)
        return True

    logger.info("Creating managed venv at %s ...", venv_dir)

    # Make sure the parent directory exists.
    os.makedirs(_PREFS_DIR, exist_ok=True)

    # Determine the best Python executable for venv creation.
    # Inside Maya, sys.executable is the Maya app binary which doesn't
    # support "-m venv".  We need "mayapy" which is the real Python
    # interpreter in Maya's bin dir.
    # Inside UE, sys.executable is UnrealEditor.exe or UnrealEditor-Cmd.exe
    # which also can't run "-m venv" and may flash a console window.
    python_exe = sys.executable
    exe_name = os.path.basename(python_exe).lower()
    if exe_name.startswith("maya") and not exe_name.startswith("mayapy"):
        # Running inside Maya — find mayapy in the same directory.
        exe_dir = os.path.dirname(python_exe)
        if platform.system() == "Windows":
            mayapy = os.path.join(exe_dir, "mayapy.exe")
        else:
            # macOS: mayapy lives alongside Maya in Contents/MacOS/.
            mayapy = os.path.join(exe_dir, "mayapy")
        if os.path.isfile(mayapy):
            python_exe = mayapy
            logger.debug("Using mayapy for venv creation: %s", mayapy)
    elif exe_name.startswith("unreal"):
        # Running inside UE — sys.executable is the UE editor binary.
        # Find a system Python 3 interpreter to create the venv instead.
        python_exe = _find_system_python()
        if python_exe is None:
            logger.warning("No system Python found for venv creation in UE.")
            return False
        logger.debug("Using system Python for venv creation in UE: %s", python_exe)

    # Create the venv without pip first — ensurepip often fails when the
    # venv executable is named mayapy.exe (Maya's Python interpreter).
    # We'll bootstrap pip separately after fixing the executable name.
    try:
        subprocess.run(
            [python_exe, "-m", "venv", "--without-pip", venv_dir],
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "Failed to create venv (exit %d): %s",
            exc.returncode,
            exc.stderr.decode(errors="replace").strip() if exc.stderr else "",
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Venv creation timed out after %ds.", _SUBPROCESS_TIMEOUT)
        return False
    except OSError as exc:
        logger.warning("Venv creation OS error: %s", exc)
        return False

    # Maya's venv module names the venv executable after the source
    # interpreter (mayapy/mayapy.exe) instead of python/python.exe.
    # Copy it so pip, ensurepip, and standard tooling work correctly.
    if platform.system() == "Windows":
        scripts_dir = os.path.join(venv_dir, "Scripts")
        mayapy_in_venv = os.path.join(scripts_dir, "mayapy.exe")
        python_in_venv = os.path.join(scripts_dir, "python.exe")
        if os.path.isfile(mayapy_in_venv) and not os.path.isfile(python_in_venv):
            shutil.copy2(mayapy_in_venv, python_in_venv)
            logger.debug("Copied mayapy.exe -> python.exe in venv Scripts/")
    else:
        # macOS/Linux: venv bin/ may have mayapy instead of python.
        bin_dir = os.path.join(venv_dir, "bin")
        mayapy_in_venv = os.path.join(bin_dir, "mayapy")
        python_in_venv = os.path.join(bin_dir, "python")
        if os.path.isfile(mayapy_in_venv) and not os.path.isfile(python_in_venv):
            shutil.copy2(mayapy_in_venv, python_in_venv)
            logger.debug("Copied mayapy -> python in venv bin/")

    # Apply Maya-specific fixes (stdlib junction, DLL copy, sitecustomize).
    # Must happen before ensurepip since the venv Python needs these
    # to locate the standard library and runtime DLLs.
    _fix_maya_venv(venv_dir)

    # Verify the venv Python exists after creation.
    venv_python = get_venv_python()
    if venv_python is None or not os.path.isfile(venv_python):
        logger.warning("Venv created but Python not found at expected path")
        return False

    # Bootstrap pip into the venv.
    try:
        subprocess.run(
            [venv_python, "-m", "ensurepip", "--upgrade", "--default-pip"],
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        logger.debug("Pip bootstrapped successfully.")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("ensurepip failed — pip install will be unavailable: %s", exc)
        # Continue anyway — the venv itself is valid, just pip-less.

    logger.info("Venv created successfully.")
    return True


# --- Package Management ------------------------------------------------------

def ensure_packages(package_map=None):
    """
    Install any missing packages into the managed venv.

    Checks each package against the venv's site-packages directory and
    only installs what's missing.  No network call if everything is
    present.  Platform-inappropriate packages (e.g. pywinpty on Linux)
    are silently skipped.

    :param dict package_map: Mapping of pip requirement specifiers to
        importable module names.  Defaults to ``REQUIRED_PACKAGES``.
    :return: *True* if all packages are now available, *False* if any
             install failed.
    :rtype: bool
    """
    if package_map is None:
        package_map = REQUIRED_PACKAGES

    venv_python = get_venv_python()
    if venv_python is None:
        logger.warning("Cannot install packages — venv does not exist.")
        return False

    # Filter to platform-relevant packages and find what's missing.
    missing = []
    for pip_spec, import_name in package_map.items():
        # pywinpty is Windows-only — skip on other platforms.
        pip_name = _pip_name(pip_spec)
        if pip_name == "pywinpty" and platform.system() != "Windows":
            continue

        if not _is_installed_locally(import_name):
            missing.append(pip_spec)

    if not missing:
        logger.debug("All required packages already installed.")
        return True

    logger.info("Installing missing packages: %s", ", ".join(missing))

    # Try installing with the venv's own Python + pip.
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install", "--quiet"] + missing,
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        logger.info("Package installation completed.")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("pip install via venv failed: %s — trying host interpreter.", exc)

    # Fallback: use the original host interpreter (e.g. mayapy from Maya's
    # bin directory) with --target pointing to the venv's site-packages.
    return _pip_install_via_host(missing)


# --- sys.path Injection ------------------------------------------------------

def inject_venv_path():
    """
    Add the venv's ``site-packages`` to ``sys.path`` if not already present.

    This is called early at startup so that ``import winpty`` (etc.) works
    in the host process.  The venv site-packages is inserted at position 0
    so managed deps take priority over the legacy ``scripts/site-packages/``
    directory.

    Uses normalized path comparison so different separators or cases
    (Windows) don't cause duplicate entries.

    :return: The site-packages path that was added, or *None* if the venv
             isn't available.
    :rtype: str or None
    """
    site_pkg = get_venv_site_packages()
    if site_pkg is None:
        logger.debug("Venv site-packages not found — skipping injection.")
        return None

    # Normalize for reliable comparison on Windows (case-insensitive paths).
    sp_normalized = os.path.normcase(os.path.normpath(site_pkg))
    for existing in sys.path:
        if os.path.normcase(os.path.normpath(existing)) == sp_normalized:
            logger.debug("Venv site-packages already on sys.path.")
            return site_pkg

    sys.path.insert(0, site_pkg)
    logger.info("Injected venv site-packages into sys.path: %s", site_pkg)

    return site_pkg


# --- Internal Helpers ---------------------------------------------------------

def _find_unreal_bundled_python():
    """
    Locate Unreal Engine's bundled Python interpreter.

    Unreal Engine 5.x ships a Python interpreter at
    ``Engine/Binaries/ThirdParty/Python3/Win64/python.exe`` (Win) or
    ``.../Mac/bin/python3`` (macOS).  When the editor's Python plugin
    initializes, ``sys.prefix`` points at this directory, so we can derive
    the executable path from ``sys.prefix`` directly.

    Using UE's bundled Python for venv creation guarantees the resulting
    venv has the exact same ABI as the running interpreter — critical for
    pywinpty's compiled extension to load.

    :return: Path to UE's bundled Python, or *None* if not detected.
    :rtype: str or None
    """
    # When running inside UE, sys.executable is the editor binary, but
    # sys.prefix still points at UE's bundled Python install dir.
    prefix = getattr(sys, "prefix", None)
    if not prefix:
        return None

    # Look for python.exe / python3 within sys.prefix.  We require that the
    # path contains "ThirdParty" or "UE_" segments so we don't accidentally
    # match a non-UE Python that happens to set sys.prefix.
    norm = os.path.normcase(prefix)
    if "thirdparty" not in norm and "ue_" not in norm and "epic games" not in norm:
        return None

    if platform.system() == "Windows":
        candidate = os.path.join(prefix, "python.exe")
    else:
        # macOS UE layout: <prefix>/bin/python3
        candidate = os.path.join(prefix, "bin", "python3")
        if not os.path.isfile(candidate):
            candidate = os.path.join(prefix, "bin", "python")

    if os.path.isfile(candidate):
        return candidate
    return None


def _find_system_python():
    """
    Find a Python 3.10+ interpreter suitable for creating the managed venv.

    Used when running inside a host application (UE, Maya) where
    ``sys.executable`` is the host binary rather than a Python interpreter.
    We need a real Python to run ``-m venv``, ``-m ensurepip``, etc.

    **Selection priority** (most → least preferred):

    1. **UE's bundled Python** — when running inside Unreal, prefer the
       bundled interpreter because it guarantees ABI match with the running
       process (compiled extensions like pywinpty must match).
    2. **Exact major.minor match** — any system Python whose version equals
       ``sys.version_info[:2]`` of the running interpreter.
    3. **Any 3.10+** — last-resort fallback so the venv builds even if the
       host doesn't have a perfectly matched Python on PATH.  This is
       imperfect but better than failing outright; ``_check_venv_python_match``
       will detect the resulting ABI drift and trigger a rebuild on next
       launch.

    :return: Path to a suitable Python executable, or *None* if not found.
    :rtype: str or None
    """
    # Priority 1: UE's bundled Python — only when inside UE.  This avoids
    # building the venv with a system Python whose minor version differs
    # from the bundled one (e.g. Python 3.10 system vs UE-bundled 3.11).
    bundled = _find_unreal_bundled_python()
    if bundled is not None:
        logger.debug("Found UE bundled Python: %s", bundled)
        return bundled

    # Build candidate command list.  On Windows we try the py launcher first
    # because it can target a specific minor version (``py -3.11``) — that
    # lets us match the running ABI exactly when multiple Pythons exist.
    target_major = sys.version_info.major
    target_minor = sys.version_info.minor

    candidates = []
    if platform.system() == "Windows":
        # Try py launcher with exact running minor version first.
        candidates.append(["py", "-{}.{}".format(target_major, target_minor)])
        candidates.append(["py", "-{}".format(target_major)])
        candidates.append(["python"])
        candidates.append(["python3"])
    else:
        # POSIX: try the version-tagged interpreter first.
        candidates.append(["python{}.{}".format(target_major, target_minor)])
        candidates.append(["python3"])
        candidates.append(["python"])

    # First pass: prefer an exact (major, minor) match against the running
    # interpreter.  Second pass: accept any 3.10+ as a fallback.
    fallback = None

    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd + ["--version"],
                check=True,
                timeout=10,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATION_FLAGS,
            )
            version_str = result.stdout.decode(errors="replace").strip()

            # Parse version. Output format: "Python 3.X.Y".
            parts = version_str.split()
            if len(parts) < 2:
                continue
            version_parts = parts[1].split(".")
            major = int(version_parts[0])
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0

            if major < 3 or minor < 10:
                continue

            # Resolve the actual executable path for subprocess use.
            if len(cmd) == 1:
                exe = shutil.which(cmd[0]) or cmd[0]
            else:
                py_result = subprocess.run(
                    cmd + ["-c", "import sys; print(sys.executable)"],
                    check=True,
                    timeout=10,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=_CREATION_FLAGS,
                )
                exe = py_result.stdout.decode(errors="replace").strip()
                if not os.path.isfile(exe):
                    continue

            # Exact ABI match — return immediately.
            if major == target_major and minor == target_minor:
                logger.debug("Found matching Python %d.%d: %s", major, minor, exe)
                return exe

            # Otherwise remember the first compatible fallback we see.
            if fallback is None:
                fallback = exe

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                OSError, FileNotFoundError, ValueError):
            continue

    if fallback is not None:
        logger.warning(
            "No Python %d.%d found for venv creation — falling back to %s. "
            "ABI mismatch may force a rebuild on next launch.",
            target_major, target_minor, fallback,
        )
    return fallback


def _pip_name(requirement):
    """
    Extract the bare pip package name from a requirement specifier.

    ``"pywinpty>=2.0.0"`` → ``"pywinpty"``

    :param str requirement: Pip requirement string.
    :return: Package name only.
    :rtype: str
    """
    for char in (">=", "<=", "==", "!=", "~=", ">", "<", "["):
        if char in requirement:
            return requirement.split(char, 1)[0].strip()
    return requirement.strip()


def _is_installed_locally(import_name):
    """
    Check whether a package is installed by looking in the venv's
    site-packages directory.

    Checks for a package directory, single-file module, or compiled
    extension (.pyd/.so).  This is much faster than spawning a
    subprocess for ``pip show``.

    :param str import_name: The importable module name.
    :return: *True* if found.
    :rtype: bool
    """
    site_pkg = get_venv_site_packages()
    if site_pkg is None:
        return False

    # Check for package directory (most packages).
    if os.path.isdir(os.path.join(site_pkg, import_name)):
        return True

    # Check for single-file module.
    if os.path.isfile(os.path.join(site_pkg, import_name + ".py")):
        return True

    # Check for compiled extension (.pyd on Windows, .so on Unix).
    # Extension modules can have ABI tags in the filename
    # (e.g. "winpty.cp311-win_amd64.pyd").
    try:
        for entry in os.listdir(site_pkg):
            if entry.startswith(import_name) and (
                entry.endswith(".pyd") or entry.endswith(".so")
            ):
                return True
    except OSError:
        pass

    return False


def _get_pyvenv_home(venv_dir):
    """
    Parse the ``home`` directory from a venv's ``pyvenv.cfg``.

    The ``home`` key points to the directory containing the Python
    interpreter that was used to create the venv (e.g. Maya's bin dir).

    :param str venv_dir: Path to the venv root.
    :return: The ``home`` directory, or *None* if not found.
    :rtype: str or None
    """
    cfg_path = os.path.join(venv_dir, "pyvenv.cfg")
    if not os.path.isfile(cfg_path):
        return None
    with open(cfg_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("home"):
                _, _, value = line.partition("=")
                return value.strip()
    return None


def _get_pyvenv_version(venv_dir):
    """
    Parse the Python ``version`` field from a venv's ``pyvenv.cfg``.

    The ``version`` key records the ``X.Y.Z`` version of the Python that
    actually created the venv — which is what determines the ABI of any
    compiled extensions (``.pyd`` / ``.so`` files) installed inside it.

    :param str venv_dir: Path to the venv root.
    :return: ``(major, minor)`` tuple of ints, or *None* if not parseable.
    :rtype: tuple or None
    """
    cfg_path = os.path.join(venv_dir, "pyvenv.cfg")
    if not os.path.isfile(cfg_path):
        return None
    # Parse "version = X.Y.Z" — only the first two components matter for
    # ABI compatibility (cp310 extensions load on any 3.10.x, etc.).
    try:
        with open(cfg_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("version"):
                    _, _, value = line.partition("=")
                    parts = value.strip().split(".")
                    if len(parts) >= 2:
                        return (int(parts[0]), int(parts[1]))
    except (OSError, ValueError):
        # Conservative: unparseable cfg is treated as "unknown", not "wrong".
        pass
    return None


def _fix_maya_venv(venv_dir):
    """
    Apply platform-specific fixes for venvs created from Maya's Python.

    Maya's ``mayapy`` resolves ``PYTHONHOME`` using hardcoded relative path
    logic.  When the executable is symlinked/copied into a venv directory,
    the resolved path doesn't exist and Python cannot find the standard
    library (``encodings``, ``os``, etc.).

    **Windows** — ``mayapy.exe`` resolves ``PYTHONHOME`` to
    ``<exe_dir>/../Python/``.  Fix: directory junction
    ``<venv>/Python`` → ``<maya>/Python``, DLL copy, sitecustomize.

    **macOS** — ``mayapy`` is a framework Python that resolves
    ``PYTHONHOME`` to ``<exe_dir>/../../Frameworks/Python.framework/
    Versions/Current/``.  Fix: symlink ``<venv>/Frameworks`` →
    ``<maya_contents>/Frameworks``.

    :param str venv_dir: Path to the venv root directory.
    """
    maya_bin = _get_pyvenv_home(venv_dir)
    if maya_bin is None:
        return

    if platform.system() == "Darwin":
        _fix_maya_venv_macos(venv_dir, maya_bin)
    elif platform.system() == "Windows":
        _fix_maya_venv_windows(venv_dir, maya_bin)


def _fix_maya_venv_macos(venv_dir, maya_bin):
    """
    Apply macOS-specific fixes for venvs created from Maya's Python.

    Maya's ``mayapy`` on macOS is a framework Python.  It resolves
    ``PYTHONHOME`` by walking up from the executable to find
    ``Frameworks/Python.framework/Versions/Current/``.  When symlinked
    into a venv's ``bin/`` directory, the walk resolves to
    ``<venv>/Frameworks/...`` which doesn't exist.

    Fix: create a symlink from ``<venv>/Frameworks`` to Maya's
    ``Contents/Frameworks`` so the framework path resolution succeeds.

    :param str venv_dir: Path to the venv root directory.
    :param str maya_bin: The ``home`` directory from ``pyvenv.cfg``
        (e.g. ``/Applications/Autodesk/maya2024/Maya.app/Contents/MacOS``).
    """
    # Verify this is a Maya venv — check for mayapy in the home dir.
    if not os.path.isfile(os.path.join(maya_bin, "mayapy")):
        return

    # Maya's Frameworks directory is a sibling of MacOS/:
    #   .../Maya.app/Contents/MacOS/mayapy
    #   .../Maya.app/Contents/Frameworks/Python.framework/...
    maya_contents = os.path.dirname(maya_bin)
    maya_frameworks = os.path.join(maya_contents, "Frameworks")
    if not os.path.isdir(maya_frameworks):
        logger.warning("Maya Frameworks dir not found: %s", maya_frameworks)
        return

    # Create symlink: <venv>/Frameworks -> <maya_contents>/Frameworks
    # The venv's bin/python symlinks to mayapy, which resolves
    # PYTHONHOME to <venv>/Frameworks/Python.framework/Versions/Current/.
    venv_frameworks = os.path.join(venv_dir, "Frameworks")
    if not os.path.exists(venv_frameworks):
        try:
            os.symlink(maya_frameworks, venv_frameworks)
            logger.debug("Created symlink: %s -> %s", venv_frameworks, maya_frameworks)
        except OSError as exc:
            logger.warning("Failed to create Frameworks symlink: %s", exc)


def _fix_maya_venv_windows(venv_dir, maya_bin):
    """
    Apply Windows-specific fixes for venvs created from Maya's Python.

    Maya's ``mayapy.exe`` resolves ``PYTHONHOME`` to ``<exe_dir>/../Python/``
    using hardcoded relative path logic.  When the executable is copied into
    a venv's ``Scripts/`` directory, this resolves to a nonexistent path and
    Python cannot find the standard library (``encodings``, ``os``, etc.).

    This function applies three fixes:

    1. **Directory junction** — Creates ``<venv>/Python`` → ``<maya>/Python``
       so the hardcoded relative path resolves to Maya's real stdlib.
    2. **DLL copy** — Copies ``pythonXY.dll`` into ``Scripts/`` so the
       copied executable can find the Python runtime DLL.
    3. **sitecustomize.py** — Adds ``os.add_dll_directory()`` for Maya's
       ``bin/`` so compiled extensions like ``_ssl.pyd`` can find their
       runtime dependencies (``libssl``, ``libcrypto``).

    :param str venv_dir: Path to the venv root directory.
    :param str maya_bin: The ``home`` directory from ``pyvenv.cfg``
        (e.g. ``C:/Program Files/Autodesk/Maya2025/bin``).
    """
    # Verify this is a Maya venv.
    if not os.path.isfile(os.path.join(maya_bin, "mayapy.exe")):
        return

    maya_root = os.path.dirname(maya_bin)
    maya_python_dir = os.path.join(maya_root, "Python")
    if not os.path.isdir(maya_python_dir):
        logger.warning("Maya Python directory not found: %s", maya_python_dir)
        return

    scripts_dir = os.path.join(venv_dir, "Scripts")

    # --- Fix 1: Create directory junction for stdlib ---
    # mayapy.exe resolves PYTHONHOME to <exe>/../Python/ — create a
    # junction so that path leads to Maya's actual Python directory.
    # Normalize paths to native backslashes — mklink fails with forward slashes.
    venv_python_dir = os.path.normpath(os.path.join(venv_dir, "Python"))
    maya_python_dir = os.path.normpath(maya_python_dir)
    if not os.path.exists(venv_python_dir):
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", venv_python_dir, maya_python_dir],
                check=True,
                capture_output=True,
                creationflags=_CREATION_FLAGS,
            )
            logger.debug("Created junction: %s -> %s", venv_python_dir, maya_python_dir)
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.warning("Failed to create stdlib junction: %s", exc)
            return

    # --- Fix 2: Copy the Python runtime DLL ---
    # The copied mayapy.exe dynamically links to pythonXY.dll which
    # lives in Maya's bin/ — it won't be found from the venv location.
    scripts_dir = os.path.normpath(scripts_dir)
    dll_name = "python{}{}.dll".format(sys.version_info.major, sys.version_info.minor)
    src_dll = os.path.normpath(os.path.join(maya_bin, dll_name))
    dst_dll = os.path.normpath(os.path.join(scripts_dir, dll_name))
    if os.path.isfile(src_dll) and not os.path.isfile(dst_dll):
        shutil.copy2(src_dll, dst_dll)
        logger.debug("Copied %s to venv Scripts/", dll_name)

    # --- Fix 3: Create sitecustomize.py for DLL loading ---
    # Compiled extensions like _ssl.pyd depend on DLLs (libssl, libcrypto)
    # in Maya's bin/.  sitecustomize.py runs at interpreter startup and
    # registers Maya's bin via os.add_dll_directory().
    site_pkg_dir = os.path.join(venv_dir, "Lib", "site-packages")
    os.makedirs(site_pkg_dir, exist_ok=True)
    sitecustomize_path = os.path.join(site_pkg_dir, "sitecustomize.py")
    if not os.path.isfile(sitecustomize_path):
        with open(sitecustomize_path, "w", encoding="utf-8") as f:
            f.write(_SITECUSTOMIZE_SRC)
        logger.debug("Created sitecustomize.py for Maya DLL loading.")


def _pip_install_via_host(missing):
    """
    Fall back to using the original host interpreter for pip install.

    When the venv's Python cannot run pip (e.g. missing DLLs or broken
    ensurepip), this uses the original interpreter from Maya's bin
    directory with ``--target`` pointing to the venv's site-packages.

    :param list missing: List of pip requirement specifiers to install.
    :return: *True* if installation succeeded, *False* otherwise.
    :rtype: bool
    """
    venv_dir = get_venv_dir()
    maya_bin = _get_pyvenv_home(venv_dir)
    if maya_bin is None:
        logger.warning("Cannot determine host interpreter for fallback pip install.")
        return False

    # Try mayapy first, then plain python — whichever exists in home.
    host_python = None
    if platform.system() == "Windows":
        search_names = ("mayapy.exe", "python.exe")
    else:
        search_names = ("mayapy", "python3", "python")
    for exe_name in search_names:
        candidate = os.path.join(maya_bin, exe_name)
        if os.path.isfile(candidate):
            host_python = candidate
            break

    if host_python is None:
        logger.warning("No host Python found in %s for fallback pip install.", maya_bin)
        return False

    site_pkg = get_venv_site_packages()
    if site_pkg is None:
        logger.warning("Venv site-packages not found for fallback pip install.")
        return False

    logger.info("Falling back to host interpreter for pip: %s", host_python)
    try:
        subprocess.run(
            [host_python, "-m", "pip", "install", "--target", site_pkg, "--quiet"] + missing,
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        logger.info("Package installation completed via host interpreter.")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Fallback pip install also failed: %s", exc)
        return False


# --- Convenience: Full Setup --------------------------------------------------

def _check_venv_python_match():
    """
    Wipe the managed venv if its embedded Python version doesn't match
    the running interpreter.

    The venv directory name is chosen by ``get_venv_dir()`` based on the
    running ``sys.version_info`` (e.g. ``.venv-3.11``).  Its *contents*,
    however, are whatever the Python that created the venv installed.
    These can diverge — for example:

      * A Windows Update replaces the host Python under us, so the next
        launch runs a different interpreter than the one that built the
        venv.
      * A third-party tool or IDE re-creates the venv using a different
        Python that happens to resolve to the same folder name.
      * The user installed a new Python version and the old venv's
        ``home`` became stale.

    When this happens, compiled extensions inside the venv (e.g.
    ``winpty.cp310-win_amd64.pyd``) silently fail to import under the
    running Python (``ModuleNotFoundError: No module named
    'winpty.winpty'``), which degrades the terminal to the subprocess
    fallback with no obvious root cause.

    This check reads ``pyvenv.cfg`` at startup and compares its
    ``version`` field against ``sys.version_info``.  On a confirmed
    ``(major, minor)`` mismatch the venv is wiped so ``ensure_venv()``
    rebuilds it from the current interpreter.  Ambiguous cases (missing
    or unreadable ``pyvenv.cfg``) are left alone — we only act on a
    definite mismatch.
    """
    venv_dir = get_venv_dir()
    if not os.path.isdir(venv_dir):
        # No venv yet — nothing to verify; ensure_venv() will create it.
        return

    venv_version = _get_pyvenv_version(venv_dir)
    if venv_version is None:
        # Couldn't parse pyvenv.cfg — be conservative, don't wipe.
        return

    # Running interpreter's major.minor — what the venv SHOULD match.
    running_version = (sys.version_info.major, sys.version_info.minor)

    if venv_version == running_version:
        # Match — venv is consistent with the running Python's ABI.
        return

    # Confirmed mismatch — wipe and let ensure_venv() rebuild from the
    # real interpreter.  Log loudly so it's obvious in session logs why
    # first-launch-after-update takes a bit longer than usual.
    logger.warning(
        "Managed venv at %s was created with Python %d.%d but the editor "
        "is running under Python %d.%d — wiping and rebuilding to restore "
        "compiled extension compatibility.",
        venv_dir,
        venv_version[0], venv_version[1],
        running_version[0], running_version[1],
    )
    try:
        shutil.rmtree(venv_dir)
        logger.info("Stale venv removed: %s", venv_dir)
    except (OSError, shutil.Error) as exc:
        # If the wipe fails (file lock, permission error), leave the
        # broken venv in place — ensure_venv() will see it as "exists"
        # and skip creation, so we'll degrade the same as before.  The
        # user can delete the folder manually if needed.
        logger.warning("Failed to remove stale venv: %s", exc)


def _check_venv_version():
    """
    Wipe the managed venv if it was built by a different MCA Editor version.

    Reads the ``.mca_venv_version`` marker file inside the venv directory
    and compares it to the current ``__version__``.  If they differ (or the
    marker is missing from an older install), the entire venv is deleted so
    that ``ensure_venv()`` + ``ensure_packages()`` rebuild it from scratch.

    This prevents stale or incompatible packages from lingering across
    plugin updates.
    """
    from mca_core import __version__

    venv_dir = get_venv_dir()
    if not os.path.isdir(venv_dir):
        # No venv yet — nothing to wipe.
        return

    version_file = os.path.join(venv_dir, _VENV_VERSION_FILE)

    # Read the stored version (if any).
    stored_version = ""
    if os.path.isfile(version_file):
        try:
            with open(version_file, "r") as f:
                stored_version = f.read().strip()
        except (IOError, OSError):
            pass

    if stored_version == __version__:
        # Same version — venv is current.
        return

    # Version mismatch — wipe the venv for a clean slate.
    logger.info(
        "MCA Editor version changed (%s -> %s) — rebuilding venv",
        stored_version or "unknown", __version__,
    )
    try:
        shutil.rmtree(venv_dir)
        logger.info("Old venv removed: %s", venv_dir)
    except (OSError, shutil.Error) as exc:
        logger.warning("Failed to remove old venv: %s", exc)


def _stamp_venv_version():
    """
    Write the current MCA Editor version into the venv's marker file.

    Called after ``ensure_packages()`` succeeds so that subsequent launches
    see the venv as current and skip the wipe.
    """
    from mca_core import __version__

    venv_dir = get_venv_dir()
    version_file = os.path.join(venv_dir, _VENV_VERSION_FILE)
    try:
        with open(version_file, "w") as f:
            f.write(__version__)
    except (IOError, OSError) as exc:
        logger.warning("Failed to write venv version marker: %s", exc)


def setup_venv(requirements=None, status_callback=None):
    """
    One-call convenience: ensure venv exists, install packages, inject path.

    This is the function most callers should use at startup.  If any step
    fails, subsequent steps are still attempted where possible (e.g. if
    pip fails, the path is still injected so previously-installed packages
    remain available).

    :param dict requirements: Package map (defaults to ``REQUIRED_PACKAGES``).
    :param callable status_callback: Optional ``fn(str)`` to report progress
        messages (e.g. for a progress dialog during first launch).
    :return: *True* if the venv is ready and injected, *False* if something
             failed (features should gracefully degrade).
    :rtype: bool
    """
    def _status(msg):
        """Log and forward progress messages to the callback."""
        logger.info(msg)
        if status_callback:
            try:
                status_callback(msg)
            except Exception:
                pass

    all_ok = True

    # Step 0a: Wipe the venv if its embedded Python ABI doesn't match the
    # running interpreter.  This catches cases like a Windows Update
    # swapping the host Python out from under us — the venv's cp310
    # extensions would then silently fail to import on cp311, degrading
    # the terminal to its subprocess fallback with no obvious root cause.
    _check_venv_python_match()

    # Step 0b: Wipe stale venv on version change.
    # When the user installs a new plugin build, nuke the old venv so
    # all packages are reinstalled fresh — prevents stale dependency bugs.
    _check_venv_version()

    # Step 1: Ensure venv exists.
    _status("Creating Python environment...")
    if not ensure_venv():
        logger.warning("Venv setup failed — features requiring managed "
                        "packages will be unavailable.")
        all_ok = False

    # Step 2: Install missing packages (only if venv exists).
    _status("Installing dependencies...")
    venv_python = get_venv_python()
    if venv_python is not None:
        if not ensure_packages(requirements):
            logger.warning("Package installation had issues — some features "
                            "may be unavailable.")
            all_ok = False
    else:
        all_ok = False

    # Stamp the venv with the current version so future launches know
    # this venv is up-to-date and skip the wipe.
    if all_ok:
        _stamp_venv_version()

    # Step 3: Inject path (even if package install failed — previously
    # installed packages should still be usable).
    _status("Configuring environment...")
    if not inject_venv_path():
        logger.warning("Path injection failed — venv packages will not "
                        "be importable.")
        all_ok = False

    return all_ok
