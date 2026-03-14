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


def _fix_maya_venv(venv_dir):
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

    Does nothing on non-Windows platforms or for non-Maya venvs.

    :param str venv_dir: Path to the venv root directory.
    """
    # Only needed on Windows — macOS/Linux venvs use symlinks properly.
    if platform.system() != "Windows":
        return

    # Check if this venv was created from Maya's Python.
    maya_bin = _get_pyvenv_home(venv_dir)
    if maya_bin is None:
        return
    if not os.path.isfile(os.path.join(maya_bin, "mayapy.exe")):
        # Not a Maya venv — standard Python venvs work fine.
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

    # Step 3: Inject path (even if package install failed — previously
    # installed packages should still be usable).
    _status("Configuring environment...")
    if not inject_venv_path():
        logger.warning("Path injection failed — venv packages will not "
                        "be importable.")
        all_ok = False

    return all_ok
