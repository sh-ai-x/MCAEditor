"""
MCA Editor — Virtual Environment Manager
=========================================

Creates and manages a dedicated Python venv inside the MCA preferences
directory. All third-party dependencies (pywinpty, pyflakes, future AI
packages) are installed here — Maya's Python and the system Python are
never modified.

The venv is created lazily on first use (plugin load or app startup) and
persists across sessions. Subsequent startups only do a sys.path insert,
which is fast.

Dependencies:
    - Python 3.8+ (stdlib only — this module must import before the venv exists)

Side Effects:
    - Creates ``mca_preferences/.venv/`` on first call to ``ensure_venv()``
    - Modifies ``sys.path`` when ``inject_venv_path()`` is called
    - May run ``pip install`` via subprocess during ``ensure_packages()``
"""

import logging
import os
import platform
import subprocess
import sys

logger = logging.getLogger(__name__)

# --- Constants ---

# Packages required for MCA Editor features. Each entry is a pip requirement
# specifier. The dict maps pip package names to the actual importable module
# name (they don't always match).
REQUIRED_PACKAGES = {
    "pywinpty": "winpty",       # Terminal backend (Windows only)
    "pyflakes": "pyflakes",     # Tier 2 code analysis
}

# How long to wait for pip operations before giving up (seconds).
PIP_TIMEOUT_SECS = 120

# Base name of the venv directory inside mca_preferences. The actual
# directory is versioned by Python major.minor to avoid ABI conflicts
# when multiple Maya versions are installed (e.g. Maya 2024 = Python 3.10,
# Maya 2025 = Python 3.11). Each gets its own venv:
#   .venv-3.10/
#   .venv-3.11/
VENV_DIR_BASE = ".venv"


# --- Venv Location ---

def _get_preferences_dir():
    """
    Return the mca_preferences directory path.

    Uses the same logic as session_manager.py — ~/mca_preferences on all
    platforms. Does NOT create the directory; that's the caller's job.

    :rtype: str
    """
    return os.path.join(os.path.expanduser("~"), "mca_preferences")


def get_venv_dir():
    """
    Return the full path to the managed venv directory for the current
    Python version.

    The directory is versioned by Python major.minor (e.g. ``.venv-3.11``)
    so that Maya 2024 (Python 3.10) and Maya 2025 (Python 3.11) each get
    their own venv with compatible compiled extensions.

    :rtype: str
    """
    version_tag = "{}.{}".format(sys.version_info.major, sys.version_info.minor)
    venv_name = "{}-{}".format(VENV_DIR_BASE, version_tag)
    return os.path.join(_get_preferences_dir(), venv_name)


def get_venv_python():
    """
    Return the path to the venv's Python executable.

    On Windows this is ``.venv/Scripts/python.exe``, on Unix it's
    ``.venv/bin/python``.

    :rtype: str
    """
    venv_dir = get_venv_dir()
    if platform.system() == "Windows":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def get_venv_site_packages():
    """
    Return the path to the venv's site-packages directory.

    Handles the Windows vs Unix directory structure difference.
    Returns None if the venv doesn't exist yet.

    :rtype: str or None
    """
    venv_dir = get_venv_dir()
    if not os.path.isdir(venv_dir):
        return None

    if platform.system() == "Windows":
        # Windows: .venv/Lib/site-packages
        sp = os.path.join(venv_dir, "Lib", "site-packages")
    else:
        # Unix: .venv/lib/pythonX.Y/site-packages
        # Need to find the pythonX.Y directory dynamically
        lib_dir = os.path.join(venv_dir, "lib")
        if os.path.isdir(lib_dir):
            for entry in os.listdir(lib_dir):
                if entry.startswith("python"):
                    sp = os.path.join(lib_dir, entry, "site-packages")
                    if os.path.isdir(sp):
                        return sp
        return None

    return sp if os.path.isdir(sp) else None


# --- Venv Creation ---

def ensure_venv():
    """
    Create the managed venv if it doesn't already exist.

    Uses the currently running Python interpreter (``sys.executable``) to
    create the venv. Inside Maya this is mayapy.exe, in standalone it's
    the system or project Python. The venv inherits the host's Python
    version and ABI, so compiled extensions (like pywinpty) are compatible.

    Does nothing if the venv already exists and has a valid Python
    executable.

    :return: True if the venv is ready to use, False if creation failed.
    :rtype: bool
    """
    venv_dir = get_venv_dir()
    venv_python = get_venv_python()

    # --- Already exists and looks valid ---
    if os.path.isfile(venv_python):
        logger.debug("Venv already exists at %s", venv_dir)
        return True

    # --- Create the preferences directory if needed ---
    prefs_dir = _get_preferences_dir()
    os.makedirs(prefs_dir, exist_ok=True)

    # --- Create the venv ---
    logger.info("Creating MCA Editor venv at %s", venv_dir)
    try:
        # Use the venv module via subprocess so it works even if the
        # current process has a non-standard sys.prefix (like Maya).
        # --without-pip is faster; we bootstrap pip separately if needed.
        result = subprocess.run(
            [sys.executable, "-m", "venv", venv_dir],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error(
                "Venv creation failed (exit %d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error("Venv creation timed out after 60 seconds")
        return False
    except Exception as exc:
        logger.error("Venv creation failed: %s", exc)
        return False

    # --- Verify the venv Python exists ---
    if not os.path.isfile(venv_python):
        logger.error("Venv created but Python not found at %s", venv_python)
        return False

    logger.info("Venv created successfully")
    return True


# --- Package Management ---

def _pip_install(packages):
    """
    Run pip install for the given package specifiers using the venv Python.

    :param list packages: List of pip requirement strings (e.g. ["pywinpty>=2.0.0"]).
    :return: True if all packages installed successfully.
    :rtype: bool
    """
    venv_python = get_venv_python()
    if not os.path.isfile(venv_python):
        logger.error("Cannot install packages — venv Python not found at %s", venv_python)
        return False

    cmd = [venv_python, "-m", "pip", "install", "--quiet"] + packages
    logger.info("Installing packages: %s", ", ".join(packages))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PIP_TIMEOUT_SECS,
        )
        if result.returncode != 0:
            logger.error(
                "pip install failed (exit %d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error("pip install timed out after %d seconds", PIP_TIMEOUT_SECS)
        return False
    except Exception as exc:
        logger.error("pip install failed: %s", exc)
        return False

    logger.info("Packages installed successfully")
    return True


def is_package_available(import_name):
    """
    Check if a package can be imported from the venv's site-packages.

    This does NOT actually import the package into the current process.
    It checks if the package directory or module file exists in the venv's
    site-packages. This is safer than trying to import, which could have
    side effects.

    :param str import_name: The importable module name (e.g. "winpty", "pyflakes").
    :return: True if the package appears to be installed.
    :rtype: bool
    """
    sp = get_venv_site_packages()
    if sp is None:
        return False

    # Check for package directory (most packages)
    if os.path.isdir(os.path.join(sp, import_name)):
        return True

    # Check for single-file module
    if os.path.isfile(os.path.join(sp, import_name + ".py")):
        return True

    # Check for compiled extension (.pyd on Windows, .so on Unix)
    for ext in (".pyd", ".so"):
        # Extension modules can have ABI tags in the filename
        for entry in os.listdir(sp):
            if entry.startswith(import_name) and entry.endswith(ext):
                return True

    return False


def ensure_packages(package_map=None):
    """
    Install any missing required packages into the venv.

    Checks each package against the venv's site-packages. Only runs pip
    for packages that aren't already present. Does nothing if everything
    is installed — no network call, no subprocess.

    :param dict package_map: Mapping of pip package names to import names.
        Defaults to REQUIRED_PACKAGES if not provided.
    :return: True if all packages are available (were already installed or
        installed successfully). False if any install failed.
    :rtype: bool
    """
    if package_map is None:
        package_map = REQUIRED_PACKAGES

    # --- Filter to platform-relevant packages ---
    filtered = {}
    for pip_name, import_name in package_map.items():
        # pywinpty is Windows-only
        if pip_name == "pywinpty" and platform.system() != "Windows":
            continue
        filtered[pip_name] = import_name

    # --- Find what's missing ---
    missing = []
    for pip_name, import_name in filtered.items():
        if not is_package_available(import_name):
            missing.append(pip_name)

    if not missing:
        logger.debug("All required packages already installed")
        return True

    logger.info("Missing packages: %s", ", ".join(missing))

    # --- Install missing packages ---
    success = _pip_install(missing)

    # --- Verify installation ---
    if success:
        still_missing = []
        for pip_name, import_name in filtered.items():
            if not is_package_available(import_name):
                still_missing.append(pip_name)
        if still_missing:
            logger.warning(
                "Packages installed but still not found: %s",
                ", ".join(still_missing),
            )
            return False

    return success


# --- sys.path Injection ---

def inject_venv_path():
    """
    Add the venv's site-packages to sys.path if not already present.

    This is the main entry point for runtime integration. Call this early
    in plugin/app startup — after ``ensure_venv()`` and ``ensure_packages()``
    have run at least once.

    Inserts at position 1 (after '' or the script directory) so venv
    packages take priority over any system-level installs but don't
    override the current working directory.

    :return: True if the path was injected (or was already present).
    :rtype: bool
    """
    sp = get_venv_site_packages()
    if sp is None:
        logger.warning("Cannot inject venv path — site-packages not found")
        return False

    # Normalize for reliable comparison
    sp_normalized = os.path.normcase(os.path.normpath(sp))
    for existing in sys.path:
        if os.path.normcase(os.path.normpath(existing)) == sp_normalized:
            logger.debug("Venv site-packages already on sys.path")
            return True

    sys.path.insert(1, sp)
    logger.info("Added venv site-packages to sys.path: %s", sp)
    return True


# --- Repair / Recreation ---

def recreate_venv():
    """
    Delete and rebuild the venv from scratch.

    Useful if the venv becomes corrupted (e.g. Python version upgrade
    broke compiled extensions). Removes the entire .venv directory, then
    calls ensure_venv() and ensure_packages() to rebuild.

    :return: True if recreation succeeded.
    :rtype: bool
    """
    import shutil

    venv_dir = get_venv_dir()
    if os.path.isdir(venv_dir):
        logger.info("Removing existing venv at %s", venv_dir)
        try:
            shutil.rmtree(venv_dir)
        except Exception as exc:
            logger.error("Failed to remove venv: %s", exc)
            return False

    # Rebuild
    if not ensure_venv():
        return False
    if not ensure_packages():
        return False
    if not inject_venv_path():
        return False

    return True


# --- Convenience: Full Setup ---

def setup(quiet=False):
    """
    Run the complete venv setup sequence.

    This is the single call that plugin_main.py and standalone main.py
    should make at startup:

    1. Create venv if it doesn't exist
    2. Install any missing packages
    3. Add venv site-packages to sys.path

    If any step fails, subsequent steps are still attempted where possible
    (e.g. if pip fails, the path is still injected so previously-installed
    packages remain available).

    :param bool quiet: If True, suppress info-level log messages.
        Useful after first-run to keep Maya's output clean.
    :return: True if all steps succeeded.
    :rtype: bool
    """
    all_ok = True

    # Step 1: Ensure venv exists
    if not ensure_venv():
        logger.warning("Venv creation failed — some features may be unavailable")
        all_ok = False

    # Step 2: Install missing packages (only if venv exists)
    if os.path.isfile(get_venv_python()):
        if not ensure_packages():
            logger.warning("Package installation failed — some features may be unavailable")
            all_ok = False
    else:
        all_ok = False

    # Step 3: Inject path (even if package install failed — previously
    # installed packages should still be usable)
    if not inject_venv_path():
        logger.warning("Path injection failed — venv packages will not be importable")
        all_ok = False

    return all_ok
