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
import subprocess
import sys

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Constants ----------------------------------------------------------------

# Base preferences directory under the user's Documents folder.
# Matches the path used by session_manager.py.
_PREFS_DIR = os.path.join(os.path.expanduser("~/Documents"), "mca_preferences")

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
}

# Timeout (seconds) for subprocess calls to pip / venv creation.
_SUBPROCESS_TIMEOUT = 120


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
        python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        python = os.path.join(venv_dir, "bin", "python")

    if os.path.isfile(python):
        return python
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

    try:
        subprocess.run(
            [sys.executable, "-m", "venv", venv_dir],
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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

    # Verify the venv Python exists after creation.
    if not os.path.isfile(get_venv_python()):
        logger.warning("Venv created but Python not found at expected path")
        return False

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

    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install", "--quiet"] + missing,
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Package installation completed.")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "pip install failed (exit %d): %s",
            exc.returncode,
            exc.stderr.decode(errors="replace").strip() if exc.stderr else "",
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("pip install timed out after %ds.", _SUBPROCESS_TIMEOUT)
        return False
    except OSError as exc:
        logger.warning("pip install OS error: %s", exc)
        return False


def is_package_available(import_name):
    """
    Quick check whether a package is installed in the venv.

    Checks for the package directory, single-file module, or compiled
    extension in the venv's site-packages.  Does NOT actually import
    the package (avoids side effects).

    :param str import_name: The importable module name (e.g. ``"winpty"``,
        ``"pyflakes"``).
    :return: *True* if the package appears to be installed.
    :rtype: bool
    """
    return _is_installed_locally(import_name)


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


# --- Repair / Recreation -----------------------------------------------------

def recreate_venv():
    """
    Delete and recreate the managed venv from scratch.

    Use this to repair a corrupted environment (e.g. Python version
    upgrade broke compiled extensions).  After recreation the packages
    are reinstalled and the path is re-injected.

    :return: *True* if the fresh venv is ready, *False* on failure.
    :rtype: bool
    """
    import shutil

    venv_dir = get_venv_dir()

    # Remove existing venv directory.
    if os.path.isdir(venv_dir):
        logger.info("Removing existing venv at %s ...", venv_dir)
        try:
            shutil.rmtree(venv_dir)
        except OSError as exc:
            logger.warning("Failed to remove venv: %s", exc)
            return False

    # Rebuild: create venv, install packages, re-inject path.
    if not ensure_venv():
        return False
    if not ensure_packages():
        return False
    if not inject_venv_path():
        return False

    return True


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


# --- Convenience: Full Setup --------------------------------------------------

def setup_venv(requirements=None):
    """
    One-call convenience: ensure venv exists, install packages, inject path.

    This is the function most callers should use at startup.  If any step
    fails, subsequent steps are still attempted where possible (e.g. if
    pip fails, the path is still injected so previously-installed packages
    remain available).

    :param dict requirements: Package map (defaults to ``REQUIRED_PACKAGES``).
    :return: *True* if the venv is ready and injected, *False* if something
             failed (features should gracefully degrade).
    :rtype: bool
    """
    all_ok = True

    # Step 1: Ensure venv exists.
    if not ensure_venv():
        logger.warning("Venv setup failed — features requiring managed "
                        "packages will be unavailable.")
        all_ok = False

    # Step 2: Install missing packages (only if venv exists).
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
    if not inject_venv_path():
        logger.warning("Path injection failed — venv packages will not "
                        "be importable.")
        all_ok = False

    return all_ok
