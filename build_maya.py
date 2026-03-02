"""
MCA Editor - Maya 2025 Build & Distribution Script.

Automates the full pipeline for creating a distributable Maya 2025 plugin:
    1. Locate Maya 2025's ``mayapy.exe`` interpreter
    2. Ensure Cython is available in Maya's Python
    3. Compile all source via ``setup.py build_ext --inplace``
    4. Collect compiled ``.pyd`` files + ``__init__.py`` stubs into a clean dist folder
    5. Bundle resources (icons, images)
    6. Generate standalone install/uninstall scripts
    7. Clean in-place build artifacts from the source tree
    8. Zip the final distribution

Usage:
    python build_maya.py
    python build_maya.py --mayapy "C:/custom/path/mayapy.exe"

Dependencies:
    - Cython >= 3.0 (auto-installed into Maya's Python if missing)
    - Maya 2025 installed (provides mayapy.exe with Python 3.11)
"""

import os
import sys
import shutil
import argparse
import subprocess
import zipfile

# --- Constants ---------------------------------------------------------------

# Version must match mca_core/__init__.py.
VERSION = "0.1.0"

# Default location of Maya 2025's Python interpreter on Windows.
DEFAULT_MAYAPY = "C:/Program Files/Autodesk/Maya2025/bin/mayapy.exe"

# Packages to include in the Maya distribution (no standalone or legacy compat).
DIST_PACKAGES = ["mca_core", "mca_qt", "mca_maya"]

# Resource directories to bundle alongside the compiled packages.
RESOURCE_DIRS = ["resources/images"]

# Pure-Python files that must ship uncompiled in the Maya distribution.
# venv_manager.py runs at plugin init before the venv exists, so it
# cannot be a compiled .pyd — it needs to work with just stdlib.
# mcp_maya_server.py runs as a separate process outside Maya.
DIST_PURE_PYTHON = [
    os.path.join("mca_core", "venv_manager.py"),
    os.path.join("mca_core", "mcp_maya_server.py"),
]

# Project root (directory containing this script).
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Name of the output distribution folder and zip.
DIST_NAME = "MCAEditor-Maya2025"
DIST_DIR = os.path.join(PROJECT_ROOT, "dist", DIST_NAME)
ZIP_PATH = os.path.join(PROJECT_ROOT, "dist", "{}-v{}.zip".format(DIST_NAME, VERSION))


# --- Install / Uninstall Script Templates ------------------------------------

# Standalone install script placed in the distribution root.
# Users run this with any Python to register MCA Editor with Maya.
INSTALL_SCRIPT = r'''"""
MCA Editor - Maya Install Script.

Registers MCA Editor with Maya by creating a ``.mod`` file and
a plugin stub so the editor appears in Maya's Plug-in Manager.

Usage:
    python install_maya.py
    python install_maya.py --setup-venv   # Pre-create venv and install deps
"""

import argparse
import os
import subprocess
import sys

def install(setup_venv=False):
    """
    Install MCA Editor into Maya's user directories.

    Creates a ``.mod`` module file and a plugin stub for each
    detected Maya version (2024+).

    :param bool setup_venv: If True, also create the managed venv and
        install required packages now rather than on first launch.
    """
    # The package root is wherever this script lives.
    package_root = os.path.dirname(os.path.abspath(__file__))

    # Locate Maya's application directory.
    if sys.platform == "win32":
        maya_dir = os.path.join(os.path.expanduser("~"), "Documents", "maya")
    elif sys.platform == "darwin":
        maya_dir = os.path.join(
            os.path.expanduser("~"), "Library", "Preferences", "Autodesk", "maya"
        )
    else:
        maya_dir = os.path.join(os.path.expanduser("~"), "maya")

    if not os.path.isdir(maya_dir):
        print("ERROR: Maya application directory not found: {}".format(maya_dir))
        print("Is Maya installed?")
        sys.exit(1)

    print("MCA Editor Installer")
    print("=" * 50)
    print("Maya app dir : {}".format(maya_dir))
    print("Package root : {}".format(package_root))
    print()

    # --- Create .mod file so Maya can find our packages ---
    modules_dir = os.path.join(maya_dir, "modules")
    os.makedirs(modules_dir, exist_ok=True)

    mod_path = os.path.join(modules_dir, "mcaeditor.mod")
    mod_content = "+ MCAEditor {version} {root}\nPYTHONPATH += {root}\n".format(
        version="__VERSION__", root=package_root
    )
    with open(mod_path, "w", encoding="utf-8") as f:
        f.write(mod_content)
    print("Created module file: {}".format(mod_path))

    # --- Create plugin stub for each Maya version directory ---
    plugin_stub = (
        '"""\nMCA Editor - Maya Plugin Stub (auto-generated).\n"""\n'
        "import sys\nimport os\n\n"
        "_PACKAGE_ROOT = r\"{root}\"\n"
        "if _PACKAGE_ROOT not in sys.path:\n"
        "    sys.path.insert(0, _PACKAGE_ROOT)\n\n"
        "maya_useNewAPI = True\n\n"
        "from mca_maya.plugin_main import initializePlugin, uninitializePlugin\n"
    ).format(root=package_root)

    found_versions = False
    for entry in sorted(os.listdir(maya_dir)):
        if entry.isdigit() and int(entry) >= 2020 and os.path.isdir(os.path.join(maya_dir, entry)):
            plugins_dir = os.path.join(maya_dir, entry, "plug-ins")
            os.makedirs(plugins_dir, exist_ok=True)
            stub_path = os.path.join(plugins_dir, "mca_editor_plugin.py")
            with open(stub_path, "w", encoding="utf-8") as f:
                f.write(plugin_stub)
            print("Created plugin stub: {}".format(stub_path))
            found_versions = True

    if not found_versions:
        print("\nWARNING: No Maya version directories found in {}".format(maya_dir))

    # --- Optional: pre-create venv and install dependencies ---
    if setup_venv:
        print()
        print("--- Setting up managed venv ---")
        # Add the package root to sys.path so we can import the venv manager.
        if package_root not in sys.path:
            sys.path.insert(0, package_root)
        try:
            from mca_core.venv_manager import setup_venv as do_setup
            ok = do_setup()
            if ok:
                print("Venv created and packages installed successfully.")
            else:
                print("WARNING: Venv setup had issues. Dependencies will be")
                print("         installed automatically on first launch.")
        except Exception as exc:
            print("WARNING: Could not set up venv: {}".format(exc))
            print("         Dependencies will be installed on first launch.")

    print()
    print("Installation complete!")
    print()
    print("Next steps:")
    print("  1. Open Maya")
    print("  2. Go to Windows > Settings/Preferences > Plug-in Manager")
    print("  3. Find 'mca_editor_plugin.py' and check 'Loaded'")
    print("  4. Check 'Auto load' to load automatically on startup")
    print("  5. Click the Script Editor button - MCA Editor should open!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install MCA Editor for Maya.")
    parser.add_argument(
        "--setup-venv", action="store_true",
        help="Pre-create the managed venv and install dependencies now "
             "instead of on first launch. Useful for studios where artist "
             "machines may not have internet access later.",
    )
    args = parser.parse_args()
    install(setup_venv=args.setup_venv)
'''.replace("__VERSION__", VERSION)

# Standalone uninstall script placed in the distribution root.
UNINSTALL_SCRIPT = r'''"""
MCA Editor - Maya Uninstall Script.

Removes MCA Editor's ``.mod`` file and plugin stubs from Maya's directories.

Usage:
    python uninstall_maya.py
"""

import os
import sys

def uninstall():
    """
    Remove MCA Editor from Maya's user directories.

    Deletes the ``.mod`` file and plugin stubs for all detected Maya versions.
    """
    # Locate Maya's application directory.
    if sys.platform == "win32":
        maya_dir = os.path.join(os.path.expanduser("~"), "Documents", "maya")
    elif sys.platform == "darwin":
        maya_dir = os.path.join(
            os.path.expanduser("~"), "Library", "Preferences", "Autodesk", "maya"
        )
    else:
        maya_dir = os.path.join(os.path.expanduser("~"), "maya")

    if not os.path.isdir(maya_dir):
        print("ERROR: Maya application directory not found: {}".format(maya_dir))
        sys.exit(1)

    print("MCA Editor Uninstaller")
    print("=" * 50)

    # Remove .mod file.
    mod_path = os.path.join(maya_dir, "modules", "mcaeditor.mod")
    if os.path.isfile(mod_path):
        os.remove(mod_path)
        print("Removed: {}".format(mod_path))
    else:
        print("Not found (skip): {}".format(mod_path))

    # Remove plugin stubs from each Maya version.
    for entry in sorted(os.listdir(maya_dir)):
        if entry.isdigit() and int(entry) >= 2020 and os.path.isdir(os.path.join(maya_dir, entry)):
            stub_path = os.path.join(maya_dir, entry, "plug-ins", "mca_editor_plugin.py")
            if os.path.isfile(stub_path):
                os.remove(stub_path)
                print("Removed: {}".format(stub_path))

    print()
    print("Uninstall complete.")


if __name__ == "__main__":
    uninstall()
'''


# --- Helper Functions --------------------------------------------------------

def run_command(cmd, description):
    """
    Execute a subprocess command with logging.

    :param list cmd: Command and arguments to execute.
    :param str description: Human-readable description for log output.
    :raises SystemExit: If the command fails (non-zero return code).
    """
    print("\n--- {} ---".format(description))
    print("  > {}".format(" ".join(cmd)))

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print("ERROR: {} failed with return code {}".format(description, result.returncode))
        sys.exit(1)


def locate_mayapy(override_path):
    """
    Find the mayapy.exe interpreter for Maya 2025.

    :param str override_path: User-supplied path, or None to use default.
    :return: Verified path to mayapy.exe.
    :rtype: str
    :raises SystemExit: If mayapy.exe is not found.
    """
    path = override_path or DEFAULT_MAYAPY

    if not os.path.isfile(path):
        print("ERROR: mayapy.exe not found at: {}".format(path))
        print("Use --mayapy to specify the correct path.")
        sys.exit(1)

    print("Using mayapy: {}".format(path))
    return path


def ensure_cython(mayapy):
    """
    Ensure Cython is available in Maya's Python environment.

    Runs ``pip install --user cython`` through mayapy so we don't need
    admin rights on the Program Files directory.

    :param str mayapy: Path to Maya's Python interpreter.
    """
    print("\n--- Ensuring Cython is available ---")

    # Check if Cython is already importable.
    check = subprocess.run(
        [mayapy, "-c", "import Cython; print(Cython.__version__)"],
        capture_output=True, text=True
    )
    if check.returncode == 0:
        print("  Cython {} already installed.".format(check.stdout.strip()))
        return

    # Install Cython into user site-packages.
    print("  Cython not found, installing...")
    run_command(
        [mayapy, "-m", "pip", "install", "--user", "cython"],
        "Installing Cython"
    )


def clean_build_dirs():
    """
    Remove previous build and dist directories for a clean start.
    """
    print("\n--- Cleaning previous build artifacts ---")

    for dirname in ["build", "dist"]:
        path = os.path.join(PROJECT_ROOT, dirname)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print("  Removed: {}".format(path))


def compile_extensions(mayapy):
    """
    Run Cython compilation via setup.py using Maya's Python interpreter.

    Produces ``.pyd`` files in-place next to the original ``.py`` files.

    :param str mayapy: Path to Maya's Python interpreter.
    """
    setup_py = os.path.join(PROJECT_ROOT, "setup.py")
    run_command(
        [mayapy, setup_py, "build_ext", "--inplace"],
        "Compiling extensions with Cython"
    )


def create_dist_structure():
    """
    Create the distribution directory and populate it with compiled files.

    For each package in DIST_PACKAGES:
        - Copies ``.pyd`` compiled extensions (preserving directory structure)
        - Copies ``__init__.py`` files (required for Python package discovery)
        - Copies explicit DIST_PURE_PYTHON files
        - Skips all other ``.py`` source files (code protection)
    """
    print("\n--- Creating distribution structure ---")

    # Start fresh.
    if os.path.isdir(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR)

    for package in DIST_PACKAGES:
        package_path = os.path.join(PROJECT_ROOT, package)

        for root, dirs, files in os.walk(package_path):
            # Skip __pycache__ and .venv directories.
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]

            # Compute the relative path from project root.
            rel_root = os.path.relpath(root, PROJECT_ROOT)
            dest_root = os.path.join(DIST_DIR, rel_root)

            # Collect files to copy: .pyd (compiled) and __init__.py (package marker).
            pyd_files = [f for f in files if f.endswith(".pyd")]
            init_files = [f for f in files if f == "__init__.py"]

            # Include any pure-Python files that must ship uncompiled.
            pure_files = [
                f for f in files
                if os.path.join(rel_root, f) in DIST_PURE_PYTHON
            ]

            files_to_copy = pyd_files + init_files + pure_files

            # Only create the directory if there are files to put in it.
            if files_to_copy:
                os.makedirs(dest_root, exist_ok=True)
                for filename in files_to_copy:
                    src = os.path.join(root, filename)
                    dst = os.path.join(dest_root, filename)
                    shutil.copy2(src, dst)
                    print("  Copied: {}".format(os.path.relpath(dst, DIST_DIR)))


def copy_resources():
    """
    Copy resource files (icons, images) into the distribution directory.
    """
    print("\n--- Copying resources ---")

    for res_dir in RESOURCE_DIRS:
        src_dir = os.path.join(PROJECT_ROOT, res_dir)
        if not os.path.isdir(src_dir):
            print("  WARNING: Resource directory not found: {}".format(src_dir))
            continue

        dst_dir = os.path.join(DIST_DIR, res_dir)
        os.makedirs(dst_dir, exist_ok=True)

        for filename in os.listdir(src_dir):
            src = os.path.join(src_dir, filename)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dst_dir, filename))
                print("  Copied: {}/{}".format(res_dir, filename))


def create_install_scripts():
    """
    Write the standalone install and uninstall scripts into the dist folder.

    These are plain Python scripts with no proprietary code — just filesystem
    operations to register/unregister MCA Editor with Maya.
    """
    print("\n--- Creating install/uninstall scripts ---")

    install_path = os.path.join(DIST_DIR, "install_maya.py")
    with open(install_path, "w", encoding="utf-8") as f:
        f.write(INSTALL_SCRIPT)
    print("  Created: install_maya.py")

    uninstall_path = os.path.join(DIST_DIR, "uninstall_maya.py")
    with open(uninstall_path, "w", encoding="utf-8") as f:
        f.write(UNINSTALL_SCRIPT)
    print("  Created: uninstall_maya.py")


def clean_source_tree():
    """
    Remove in-place build artifacts from the source tree.

    Cleans up ``.pyd``, ``.c`` (Cython intermediate), and ``build/``
    directories that were created during the compilation step.
    """
    print("\n--- Cleaning source tree ---")

    # Remove .pyd and .c files from each package.
    for package in DIST_PACKAGES + ["mca_standalone", "mca_editor"]:
        package_path = os.path.join(PROJECT_ROOT, package)
        if not os.path.isdir(package_path):
            continue

        for root, dirs, files in os.walk(package_path):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for filename in files:
                if filename.endswith((".pyd", ".c")):
                    filepath = os.path.join(root, filename)
                    os.remove(filepath)
                    print("  Removed: {}".format(os.path.relpath(filepath, PROJECT_ROOT)))

    # Remove the build directory created by setuptools.
    build_dir = os.path.join(PROJECT_ROOT, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
        print("  Removed: build/")


def create_zip():
    """
    Create a zip archive of the distribution folder.

    The zip includes the distribution directory name as the top-level folder,
    so unzipping produces ``MCAEditor-Maya2025/`` with all contents inside.

    :return: Path to the created zip file.
    :rtype: str
    """
    print("\n--- Creating zip archive ---")

    # Ensure the parent directory exists.
    os.makedirs(os.path.dirname(ZIP_PATH), exist_ok=True)

    dist_parent = os.path.join(PROJECT_ROOT, "dist")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            for filename in files:
                filepath = os.path.join(root, filename)
                # Archive name preserves the top-level dist folder name.
                arcname = os.path.relpath(filepath, dist_parent)
                zf.write(filepath, arcname)
                print("  Added: {}".format(arcname))

    print("\nZip created: {}".format(ZIP_PATH))
    return ZIP_PATH


# --- Main Build Pipeline ----------------------------------------------------

def main():
    """
    Main entry point for the Maya 2025 build pipeline.

    Parses command-line arguments, then runs each build step in order:
    locate mayapy -> ensure cython -> clean -> compile -> package -> zip.
    """
    parser = argparse.ArgumentParser(
        description="Build MCA Editor for Maya 2025 distribution."
    )
    parser.add_argument(
        "--mayapy",
        default=None,
        help="Path to mayapy.exe (default: {})".format(DEFAULT_MAYAPY),
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  MCA Editor - Maya 2025 Build Script")
    print("  Version: {}".format(VERSION))
    print("=" * 60)

    # Step 1: Locate Maya's Python interpreter.
    mayapy = locate_mayapy(args.mayapy)

    # Step 2: Ensure Cython is available in Maya's Python.
    ensure_cython(mayapy)

    # Step 3: Clean previous build artifacts.
    clean_build_dirs()

    # Step 4: Compile extensions in-place using Maya's Python.
    compile_extensions(mayapy)

    # Step 5: Create distribution directory with compiled files.
    create_dist_structure()

    # Step 6: Copy resource files (icons, images).
    copy_resources()

    # Step 7: Write install/uninstall scripts into dist.
    create_install_scripts()

    # Step 8: Create the zip archive.
    zip_path = create_zip()

    # Step 9: Clean in-place build artifacts from the source tree.
    clean_source_tree()

    # Done!
    print()
    print("=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    print()
    print("Distribution folder: {}".format(DIST_DIR))
    print("Zip archive:         {}".format(zip_path))
    print()
    print("To install into Maya:")
    print("  1. Unzip {} to a permanent location".format(os.path.basename(zip_path)))
    print("  2. Run: python install_maya.py")
    print("  3. Open Maya 2025 and load the plugin from Plug-in Manager")


# Script guard for direct execution.
if __name__ == "__main__":
    main()
