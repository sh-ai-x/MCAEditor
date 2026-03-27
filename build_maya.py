"""
MCA Editor - Maya Build & Distribution Script.

Automates the full pipeline for creating a distributable Maya plugin:
    1. Locate the target Maya version's ``mayapy.exe`` interpreter
    2. Ensure Cython is available in Maya's Python
    3. Compile all source via ``setup.py build_ext --inplace``
    4. Collect compiled ``.pyd`` files + ``__init__.py`` stubs into a clean dist folder
    5. Bundle resources (icons, images)
    6. Generate standalone install/uninstall scripts
    7. Clean in-place build artifacts from the source tree
    8. Zip the final distribution

Usage:
    python build_maya.py                          # Build for Maya 2025 (default)
    python build_maya.py --maya-version 2024      # Build for Maya 2024
    python build_maya.py --mayapy "C:/custom/path/mayapy.exe"

Dependencies:
    - Cython >= 3.0 (auto-installed into Maya's Python if missing)
    - Maya 2024+ installed (provides mayapy.exe)
"""

import os
import sys
import shutil
import argparse
import subprocess
import zipfile

# --- Constants ---------------------------------------------------------------

# Pull the canonical version from mca_core so there is one source of truth.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mca_core import __version__ as VERSION

# Default Maya version to build for (can be overridden with --maya-version).
DEFAULT_MAYA_VERSION = "2025"

# Platform-specific template for the default mayapy path.
if sys.platform == "darwin":
    MAYAPY_TEMPLATE = "/Applications/Autodesk/maya{version}/Maya.app/Contents/bin/mayapy"
elif sys.platform == "win32":
    MAYAPY_TEMPLATE = "C:/Program Files/Autodesk/Maya{version}/bin/mayapy.exe"
else:
    # Linux — common install location.
    MAYAPY_TEMPLATE = "/usr/autodesk/maya{version}/bin/mayapy"

# Compiled extension suffix: .pyd on Windows, .so on macOS/Linux.
COMPILED_EXT = ".pyd" if sys.platform == "win32" else ".so"

# Packages to include in the Maya distribution (no standalone or legacy compat).
DIST_PACKAGES = ["mca_core", "mca_qt", "mca_maya"]

# Resource directories to bundle alongside the compiled packages.
RESOURCE_DIRS = ["resources/images", "resources/gifs"]

# Pure-Python files that must ship uncompiled in the Maya distribution.
# venv_manager.py runs at plugin init before the venv exists, so it
# cannot be a compiled .pyd — it needs to work with just stdlib.
# mcp_maya_server.py and mcp_editor_server.py run as separate processes
# outside Maya, launched by Claude Code via MCP stdio.
DIST_PURE_PYTHON = [
    os.path.join("mca_core", "venv_manager.py"),
    os.path.join("mca_core", "mcp_maya_server.py"),
    os.path.join("mca_core", "mcp_editor_server.py"),
]

# Files that ship as .pyc (bytecode) instead of .pyd (compiled C extension).
# ANY file with a Qt virtual method override crashes when compiled because
# Shiboken's C++ virtual dispatch fails on enum-typed arguments in
# Cython-compiled code (ACCESS_VIOLATION in Shiboken::Enum::unpickleEnum).
# Files without Qt virtual overrides compile fine.
DIST_PYC_FILES = [
    # --- mca_maya ---
    os.path.join("mca_maya", "maya_window.py"),
    # --- mca_qt ---
    os.path.join("mca_qt", "editor_panel.py"),
    # --- mca_qt/widgets ---
    os.path.join("mca_qt", "widgets", "code_editor.py"),
    os.path.join("mca_qt", "widgets", "completer.py"),
    os.path.join("mca_qt", "widgets", "drag_tab_manager.py"),
    os.path.join("mca_qt", "widgets", "drop_zone_overlay.py"),
    os.path.join("mca_qt", "widgets", "editor_group.py"),
    os.path.join("mca_qt", "widgets", "find_in_files.py"),
    os.path.join("mca_qt", "widgets", "find_replace_bar.py"),
    os.path.join("mca_qt", "widgets", "output_window.py"),
    os.path.join("mca_qt", "widgets", "quick_open.py"),
    os.path.join("mca_qt", "widgets", "settings_dialog.py"),
    os.path.join("mca_qt", "widgets", "sidebar.py"),
    os.path.join("mca_qt", "widgets", "terminal_native.py"),
    os.path.join("mca_qt", "widgets", "terminal_xterm.py"),
    os.path.join("mca_qt", "widgets", "tool_stripe.py"),
    # Plugin settings dialog has keyPressEvent override -> .pyc
    os.path.join("mca_qt", "widgets", "plugin_settings_dialog.py"),
    # --- PySide2/Shiboken2 + Cython incompatibility -----------------------
    # ANY file that defines a class inheriting from a Qt class must ship
    # as .pyc when targeting Maya 2024 (PySide2).  Shiboken2's metaclass
    # cannot properly handle Cython-compiled Qt subclasses — causes
    # TypeError, RecursionError, or ACCESS_VIOLATION crashes even without
    # virtual method overrides.
    os.path.join("mca_qt", "widgets", "editor_group_container.py"),
    os.path.join("mca_qt", "widgets", "terminal_tab_panel.py"),
    os.path.join("mca_qt", "widgets", "terminal_backend.py"),
    os.path.join("mca_qt", "widgets", "ai_panel.py"),
    os.path.join("mca_qt", "widgets", "connection_dialog.py"),
    os.path.join("mca_qt", "widgets", "create_project_dialog.py"),
    os.path.join("mca_qt", "widgets", "license_dialog.py"),
    os.path.join("mca_qt", "widgets", "licensing_dialog.py"),
    os.path.join("mca_qt", "widgets", "new_tab_dialog.py"),
    os.path.join("mca_qt", "widgets", "project_settings_dialog.py"),
    # --- AI Chat plugin ---
    # chat_widget.py has keyPressEvent override -> .pyc
    os.path.join("mca_core", "plugins", "ai_chat", "chat_widget.py"),
    # chat_worker.py subclasses QThread with run() override -> .pyc
    os.path.join("mca_core", "plugins", "ai_chat", "chat_worker.py"),
]

# Project root (directory containing this script).
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# These are set by _set_maya_version() based on the target Maya version.
DIST_NAME = None
DIST_DIR = None
ZIP_PATH = None


def _set_maya_version(maya_version):
    """
    Configure module-level dist paths for the target Maya version.

    Called once from main() after parsing command-line arguments.

    :param str maya_version: Maya version year (e.g. "2024", "2025").
    """
    global DIST_NAME, DIST_DIR, ZIP_PATH
    DIST_NAME = "MCAEditor-Maya{}".format(maya_version)
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


def locate_mayapy(override_path, maya_version):
    """
    Find the mayapy.exe interpreter for the target Maya version.

    :param str override_path: User-supplied path, or None to use default.
    :param str maya_version: Maya version year (e.g. "2024", "2025").
    :return: Verified path to mayapy.exe.
    :rtype: str
    :raises SystemExit: If mayapy.exe is not found.
    """
    path = override_path or MAYAPY_TEMPLATE.format(version=maya_version)

    if not os.path.isfile(path):
        print("ERROR: mayapy not found at: {}".format(path))
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
    Remove the build directory and this version's dist folder for a clean start.

    Only removes the version-specific dist subfolder (e.g. dist/MCAEditor-Maya2024),
    NOT the entire dist/ directory — so builds for other Maya versions are preserved.
    """
    print("\n--- Cleaning previous build artifacts ---")

    # Always clean the build directory (Cython intermediates).
    build_path = os.path.join(PROJECT_ROOT, "build")
    if os.path.isdir(build_path):
        shutil.rmtree(build_path)
        print("  Removed: {}".format(build_path))

    # Only remove THIS version's dist subfolder, not the whole dist/.
    if os.path.isdir(DIST_DIR):
        shutil.rmtree(DIST_DIR)
        print("  Removed: {}".format(DIST_DIR))

    # Remove the zip for this version if it exists.
    if os.path.isfile(ZIP_PATH):
        os.remove(ZIP_PATH)
        print("  Removed: {}".format(ZIP_PATH))


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


def compile_pyc_files(mayapy):
    """
    Compile .pyc fallback files and place them directly in package dirs.

    Files listed in ``DIST_PYC_FILES`` are compiled to bytecode using
    Maya's ``mayapy`` interpreter so the magic number matches Maya's
    Python version.  The ``.pyc`` files are placed directly in the
    package directory as ``module.pyc`` (NOT in ``__pycache__/``).

    Python's ``SourcelessFileLoader`` looks for ``.pyc`` files in the
    package directory itself.  The ``__pycache__/`` mechanism is only
    used by ``SourceFileLoader`` when a ``.py`` source file exists.
    For sourceless distribution (no .py present), the ``.pyc`` must
    live next to the ``__init__.py`` so ``FileFinder`` can discover it.

    Using ``mayapy`` is critical: if the build host runs a different
    Python version than Maya, ``py_compile`` would produce ``.pyc``
    files with a mismatched magic number, causing "bad magic number"
    errors when Maya tries to load the modules.

    :param str mayapy: Path to Maya's Python interpreter.
    :return: Set of relative paths that were compiled (for logging).
    :rtype: set
    """
    print("\n--- Compiling .pyc fallback files (using mayapy) ---")

    compiled = set()
    for rel_path in DIST_PYC_FILES:
        src_path = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.isfile(src_path):
            print("  WARNING: Source not found, skipping: {}".format(rel_path))
            continue

        # Place the .pyc directly in the package directory (sourceless import).
        # e.g. mca_maya/maya_window.py -> dist/mca_maya/maya_window.pyc
        rel_dir = os.path.dirname(rel_path)
        basename = os.path.splitext(os.path.basename(rel_path))[0]
        pyc_name = "{}.pyc".format(basename)

        dest_dir = os.path.join(DIST_DIR, rel_dir)
        os.makedirs(dest_dir, exist_ok=True)

        dest_pyc = os.path.join(dest_dir, pyc_name)

        # Use mayapy to compile so the .pyc magic number matches Maya's
        # Python version, not the build host's Python version.
        result = subprocess.run(
            [mayapy, "-c",
             "import py_compile; py_compile.compile(r'{}', cfile=r'{}', doraise=True)".format(
                 src_path, dest_pyc)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("  ERROR compiling {}: {}".format(rel_path, result.stderr.strip()))
            continue

        compiled.add(rel_path)
        print("  Compiled: {} -> {}".format(
            rel_path, os.path.relpath(dest_pyc, DIST_DIR)
        ))

    return compiled


def create_dist_structure():
    """
    Create the distribution directory and populate it with compiled files.

    For each package in DIST_PACKAGES:
        - Copies ``.pyd`` compiled extensions (preserving directory structure)
        - Copies ``__init__.py`` files (required for Python package discovery)
        - Copies explicit DIST_PURE_PYTHON files as ``.py``
        - Skips DIST_PYC_FILES (handled separately by ``compile_pyc_files()``)
        - Skips all other ``.py`` source files (code protection)
    """
    print("\n--- Creating distribution structure ---")

    # Start fresh.
    if os.path.isdir(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR)

    # Build a set of pure-python source paths for fast lookup.
    # Used to skip .pyd duplicates — files in DIST_PURE_PYTHON must ship
    # as .py only (MCP servers are copied to deploy dirs as scripts,
    # venv_manager bootstraps before the environment is ready).
    pure_python_set = set(DIST_PURE_PYTHON)

    for package in DIST_PACKAGES:
        package_path = os.path.join(PROJECT_ROOT, package)

        for root, dirs, files in os.walk(package_path):
            # Skip __pycache__ and .venv directories.
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]

            # Compute the relative path from project root.
            rel_root = os.path.relpath(root, PROJECT_ROOT)
            dest_root = os.path.join(DIST_DIR, rel_root)

            # Compiled extensions (.pyd / .so).
            # Skip .pyd files whose module ships as pure Python — prevents
            # shipping both .py source AND .pyd for the same module.
            pyd_files = []
            for f in files:
                if not f.endswith(COMPILED_EXT):
                    continue
                mod_name = f.split(".")[0]
                source_rel = os.path.join(rel_root, mod_name + ".py")
                if source_rel in pure_python_set:
                    continue
                pyd_files.append(f)

            init_files = [f for f in files if f == "__init__.py"]

            # Include any pure-Python files that must ship uncompiled.
            pure_files = [
                f for f in files
                if os.path.join(rel_root, f) in pure_python_set
            ]

            # CRITICAL: Copy plugin.json manifests for bundled plugins.
            # These are not .py files so they would be silently dropped
            # without this explicit inclusion.
            json_manifests = [
                f for f in files
                if f == "plugin.json"
            ]

            files_to_copy = pyd_files + init_files + pure_files + json_manifests

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

    # Remove compiled extensions and .c intermediates from each package.
    for package in DIST_PACKAGES + ["mca_standalone", "mca_editor"]:
        package_path = os.path.join(PROJECT_ROOT, package)
        if not os.path.isdir(package_path):
            continue

        for root, dirs, files in os.walk(package_path):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for filename in files:
                if filename.endswith((".pyd", ".so", ".c")):
                    filepath = os.path.join(root, filename)
                    os.remove(filepath)
                    print("  Removed: {}".format(os.path.relpath(filepath, PROJECT_ROOT)))

    # Remove the build directory created by setuptools.
    build_dir = os.path.join(PROJECT_ROOT, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)
        print("  Removed: build/")


def create_zip(maya_version):
    """
    Create a website-distribution zip containing only the single-file plugin
    and README.

    The zip contains ``mcaEditor.py`` (renamed from the version-specific file)
    and ``README.md`` at the top level — no nested folder.  This is the file
    users download from mcaeditor.com.

    :param str maya_version: Maya version year (e.g. "2024", "2025").
    :return: Path to the created zip file.
    :rtype: str
    """
    print("\n--- Creating download zip ---")

    # Ensure the parent directory exists.
    os.makedirs(os.path.dirname(ZIP_PATH), exist_ok=True)

    # Path to the single-file plugin produced by pack_and_deploy().
    single_file = os.path.join(PROJECT_ROOT, "dist", "mcaEditor-Maya{}.py".format(maya_version))
    if not os.path.isfile(single_file):
        print("  ERROR: Single-file plugin not found: {}".format(single_file))
        return ZIP_PATH

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add the plugin as "mcaEditor.py" (users drop this into plug-ins/).
        zf.write(single_file, "mcaEditor.py")
        print("  Added: mcaEditor.py")

        # Include README.md from Google Drive if available.
        readme_path = os.path.join("G:\\My Drive\\Projects\\MCAEditor", "README.md")
        if os.path.isfile(readme_path):
            zf.write(readme_path, "README.md")
            print("  Added: README.md")
        else:
            print("  WARNING: README.md not found at {}".format(readme_path))

    print("\nZip created: {}".format(ZIP_PATH))
    return ZIP_PATH


# --- Pack & Deploy ----------------------------------------------------------

def pack_and_deploy(maya_version):
    """
    Pack the distribution into a single-file plugin and deploy it.

    Runs ``pack_single_file.py`` to create the single-file Maya plugin,
    then copies it into the user's Maya plug-ins directory, replacing
    any existing ``mcaEditor.py``.

    :param str maya_version: Maya version year (e.g. "2024", "2025").
    """
    import pack_single_file

    # --- Pack into single .py file ---
    single_file = os.path.join(PROJECT_ROOT, "dist", "mcaEditor-Maya{}.py".format(maya_version))
    print("\n--- Packing single-file plugin ---")
    pack_single_file.pack(DIST_DIR, single_file, maya_version=maya_version)

    # --- Deploy to Maya's plug-ins folder ---
    if sys.platform == "win32":
        maya_dir = os.path.join(os.path.expanduser("~"), "Documents", "maya")
    elif sys.platform == "darwin":
        maya_dir = os.path.join(
            os.path.expanduser("~"), "Library", "Preferences", "Autodesk", "maya"
        )
    else:
        maya_dir = os.path.join(os.path.expanduser("~"), "maya")

    plugins_dir = os.path.join(maya_dir, maya_version, "plug-ins")

    if not os.path.isdir(plugins_dir):
        os.makedirs(plugins_dir, exist_ok=True)
        print("  Created: {}".format(plugins_dir))

    deploy_path = os.path.join(plugins_dir, "mcaEditor.py")
    shutil.copy2(single_file, deploy_path)
    print("\n--- Deployed to Maya {} ---".format(maya_version))
    print("  {}".format(deploy_path))


# --- Main Build Pipeline ----------------------------------------------------

def main():
    """
    Main entry point for the Maya build pipeline.

    Parses command-line arguments, then runs each build step in order:
    locate mayapy -> ensure cython -> clean -> compile -> package -> zip.
    """
    parser = argparse.ArgumentParser(
        description="Build MCA Editor for Maya distribution."
    )
    parser.add_argument(
        "--maya-version",
        default=DEFAULT_MAYA_VERSION,
        help="Maya version year to build for (default: {})".format(DEFAULT_MAYA_VERSION),
    )
    parser.add_argument(
        "--mayapy",
        default=None,
        help="Path to mayapy.exe (overrides --maya-version auto-detection)",
    )
    args = parser.parse_args()

    # Configure module-level paths for the target Maya version.
    _set_maya_version(args.maya_version)

    print("=" * 60)
    print("  MCA Editor - Maya {} Build Script".format(args.maya_version))
    print("  Version: {}".format(VERSION))
    print("=" * 60)

    # Step 1: Locate Maya's Python interpreter.
    mayapy = locate_mayapy(args.mayapy, args.maya_version)

    # Step 2: Ensure Cython is available in Maya's Python.
    ensure_cython(mayapy)

    # Step 3: Clean previous build artifacts.
    clean_build_dirs()

    # Step 4: Compile extensions in-place using Maya's Python.
    compile_extensions(mayapy)

    # Step 5: Create distribution directory with compiled .pyd files.
    create_dist_structure()

    # Step 6: Compile .pyc fallback files for Qt widget subclasses.
    # Must use mayapy so the .pyc magic number matches Maya's Python.
    compile_pyc_files(mayapy)

    # Step 7: Copy resource files (icons, images).
    copy_resources()

    # Step 8: Write install/uninstall scripts into dist.
    create_install_scripts()

    # Step 9: Clean in-place build artifacts from the source tree.
    clean_source_tree()

    # Step 10: Pack single-file plugin and deploy to Maya's plug-ins folder.
    pack_and_deploy(args.maya_version)

    # Step 11: Create the download zip (single-file plugin + README only).
    zip_path = create_zip(args.maya_version)

    # Done!
    print()
    print("=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    print()
    print("Distribution folder: {}".format(DIST_DIR))
    print("Zip archive:         {}".format(zip_path))


# Script guard for direct execution.
if __name__ == "__main__":
    main()
