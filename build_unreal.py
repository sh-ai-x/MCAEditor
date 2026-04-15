"""
MCA Editor - Unreal Engine Build & Distribution Script.

Automates the full pipeline for creating a distributable UE plugin:
    1. Locate the target UE version's RunUAT.bat and Python interpreter
    2. Compile the C++ plugin via RunUAT BuildPlugin
    3. Compile Python to .pyd via Cython (using UE's Python for ABI match)
    4. Collect compiled .pyd + .pyc fallbacks into Content/Python/
    5. Bundle resources (icons, images)
    6. Zip the final distribution

Usage:
    python build_unreal.py                          # Build for UE 5.5 (default)
    python build_unreal.py --ue-version 5.4         # Build for UE 5.4
    python build_unreal.py --ue-version 5.5 --ue-root "D:/Epic/UE_5.5"
    python build_unreal.py --skip-cpp               # Skip C++ (Python only)

The output is a zip that can be extracted directly into any UE project's
Plugins/ folder.  All Python code is compiled to .pyd (Cython) for code
protection — same level of protection as the Maya distribution.

Dependencies:
    - Unreal Engine 5.4+ installed (provides Python 3.11)
    - Cython >= 3.0 (auto-installed into UE's Python if missing)
    - Visual Studio 2022 (for both C++ and Cython compilation)
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

# Project root (where this script lives).
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Default UE version to build for.
DEFAULT_UE_VERSION = "5.5"

# Platform-specific template for the default UE installation path.
if sys.platform == "win32":
    UE_ROOT_TEMPLATE = "C:/Program Files/Epic Games/UE_{version}"
else:
    UE_ROOT_TEMPLATE = "/Users/Shared/Epic Games/UE_{version}"

# UE plugin source directory in our repo.
PLUGIN_SOURCE_DIR = os.path.join(PROJECT_ROOT, "mca_unreal")

# Compiled extension suffix: .pyd on Windows, .so on macOS/Linux.
COMPILED_EXT = ".pyd" if sys.platform == "win32" else ".so"

# Python packages to compile and bundle into Content/Python/.
# Same packages as Maya — the editor codebase is cross-DCC.
DIST_PACKAGES = ["mca_core", "mca_qt"]

# Resource directories to bundle alongside the Python packages.
RESOURCE_DIRS = ["resources/images", "resources/gifs"]

# Output base directory for all UE builds.
DIST_BASE = os.path.join(PROJECT_ROOT, "dist")

# Pure-Python files that must ship uncompiled (.py).
# venv_manager.py runs before the venv exists.
# MCP server scripts run as separate processes outside UE.
DIST_PURE_PYTHON = [
    os.path.join("mca_core", "venv_manager.py"),
    os.path.join("mca_core", "mcp_maya_server.py"),
    os.path.join("mca_core", "mcp_editor_server.py"),
    os.path.join("mca_core", "mcp_unreal_server.py"),
]

# Files that ship as .pyc instead of .pyd.
# ANY file with a Qt virtual method override crashes when compiled to .pyd
# because Shiboken's C++ virtual dispatch fails on enum-typed arguments in
# Cython-compiled code (ACCESS_VIOLATION in Shiboken::Enum::unpickleEnum).
# This is the same list as build_maya.py minus mca_maya-specific files.
DIST_PYC_FILES = [
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
    os.path.join("mca_qt", "widgets", "plugin_settings_dialog.py"),
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
    os.path.join("mca_core", "plugins", "ai_chat", "chat_widget.py"),
    os.path.join("mca_core", "plugins", "ai_chat", "chat_worker.py"),
]


# --- Utility Functions -------------------------------------------------------

def log(msg):
    """Print a log message with consistent formatting."""
    print("  {}".format(msg))


def run_command(cmd, description):
    """
    Run a subprocess command, raising on failure.

    :param list cmd: Command and arguments.
    :param str description: Human-readable description for error messages.
    """
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        raise RuntimeError("{} failed (exit code {})".format(description, result.returncode))


def find_ue_root(version):
    """
    Locate the UE installation directory for the given version.

    :param str version: UE version string (e.g. "5.5").
    :return: Absolute path to the UE root directory, or None.
    :rtype: str or None
    """
    path = UE_ROOT_TEMPLATE.format(version=version)
    if os.path.isdir(path):
        return path

    # Try common alternative locations on Windows.
    if sys.platform == "win32":
        for drive in ["C:", "D:", "E:"]:
            alt = "{}/Program Files/Epic Games/UE_{}".format(drive, version)
            if os.path.isdir(alt):
                return alt

    return None


def find_ue_python(ue_root):
    """
    Locate UE's bundled Python interpreter.

    :param str ue_root: Path to the UE root directory.
    :return: Absolute path to python.exe.
    :rtype: str
    """
    if sys.platform == "win32":
        return os.path.join(ue_root, "Engine", "Binaries", "ThirdParty",
                            "Python3", "Win64", "python.exe")
    else:
        return os.path.join(ue_root, "Engine", "Binaries", "ThirdParty",
                            "Python3", "Mac", "bin", "python3")


def find_runuat(ue_root):
    """
    Locate RunUAT within the UE installation.

    :param str ue_root: Path to the UE root directory.
    :return: Absolute path to RunUAT.bat (or .sh on macOS/Linux).
    :rtype: str
    """
    if sys.platform == "win32":
        return os.path.join(ue_root, "Engine", "Build", "BatchFiles", "RunUAT.bat")
    else:
        return os.path.join(ue_root, "Engine", "Build", "BatchFiles", "RunUAT.sh")


# --- Build Steps -------------------------------------------------------------

def ensure_cython(python_exe):
    """
    Ensure Cython is available in UE's Python environment.

    :param str python_exe: Path to UE's Python interpreter.
    """
    log("Checking for Cython in UE Python...")
    result = subprocess.run(
        [python_exe, "-c", "import Cython; print(Cython.__version__)"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        log("Cython {} found.".format(result.stdout.strip()))
        return

    # Install Cython into user site-packages.
    log("Cython not found, installing...")
    run_command(
        [python_exe, "-m", "pip", "install", "--user", "cython"],
        "Installing Cython"
    )


def compile_cpp_plugin(ue_root, output_dir):
    """
    Compile the C++ plugin using RunUAT BuildPlugin.

    Produces a ready-to-use plugin with Binaries/ containing the
    compiled DLLs.  No C++ source is included in the output.

    :param str ue_root: Path to UE installation root.
    :param str output_dir: Directory to write the packaged plugin to.
    :return: True if compilation succeeded.
    :rtype: bool
    """
    runuat = find_runuat(ue_root)
    plugin_file = os.path.join(PLUGIN_SOURCE_DIR, "MCAEditor.uplugin")

    cmd = [
        runuat,
        "BuildPlugin",
        "-Plugin={}".format(plugin_file),
        "-Package={}".format(output_dir),
        "-TargetPlatforms=Win64",
        "-Rocket",
    ]

    log("Running RunUAT BuildPlugin...")
    log("This may take a few minutes...")
    print()

    result = subprocess.run(cmd, cwd=ue_root, timeout=600)
    if result.returncode != 0:
        log("ERROR: RunUAT BuildPlugin failed (exit code {})".format(result.returncode))
        return False

    log("C++ plugin compiled successfully.")
    return True


def find_ue_python_dev_paths(ue_root):
    """
    Locate UE's Python development headers and library directories.

    UE's bundled Python reports sysconfig include paths that don't exist.
    The actual headers live at Engine/Source/ThirdParty/Python3/<platform>/include/
    and the .lib at Engine/Source/ThirdParty/Python3/<platform>/libs/.

    :param str ue_root: Path to UE installation root.
    :return: (include_dir, library_dir) — either may be None if not found.
    :rtype: tuple
    """
    if sys.platform == "win32":
        platform_dir = "Win64"
    else:
        platform_dir = "Mac"

    base = os.path.join(ue_root, "Engine", "Source", "ThirdParty", "Python3", platform_dir)
    inc_dir = os.path.join(base, "include")
    lib_dir = os.path.join(base, "libs")

    # Verify Python.h exists in the include directory.
    if not os.path.isfile(os.path.join(inc_dir, "Python.h")):
        inc_dir = None
    if not os.path.isdir(lib_dir):
        lib_dir = None

    return inc_dir, lib_dir


def compile_python_extensions(python_exe, ue_root):
    """
    Compile Python to .pyd via Cython using UE's Python interpreter.

    Uses setup.py build_ext --inplace, same as the Maya build.
    The .pyd files are produced in-place next to the .py source files,
    then collected by ``bundle_python_packages()``.

    Sets MCA_PYTHON_INCLUDE and MCA_PYTHON_LIBDIR environment variables
    so setup.py can find UE's non-standard header/library locations.

    :param str python_exe: Path to UE's Python interpreter.
    :param str ue_root: Path to UE installation root.
    """
    # UE's Python sysconfig points to a non-existent Include/ directory.
    # The real headers are at Engine/Source/ThirdParty/Python3/Win64/include/.
    inc_dir, lib_dir = find_ue_python_dev_paths(ue_root)

    env = os.environ.copy()
    if inc_dir:
        log("UE Python include: {}".format(inc_dir))
        env["MCA_PYTHON_INCLUDE"] = inc_dir
    else:
        log("WARNING: Could not find UE Python headers (Python.h).")
    if lib_dir:
        log("UE Python libdir:  {}".format(lib_dir))
        env["MCA_PYTHON_LIBDIR"] = lib_dir

    setup_py = os.path.join(PROJECT_ROOT, "setup.py")
    result = subprocess.run(
        [python_exe, setup_py, "build_ext", "--inplace"],
        cwd=PROJECT_ROOT, env=env
    )
    if result.returncode != 0:
        raise RuntimeError("Cython compilation failed (exit code {})".format(result.returncode))


def compile_pyc_files(python_exe, output_python_dir):
    """
    Compile .pyc fallback files using UE's Python interpreter.

    Files in DIST_PYC_FILES crash when compiled to .pyd (Shiboken
    enum dispatch issue), so they ship as .pyc instead.  Using UE's
    Python ensures the .pyc magic number matches.

    :param str python_exe: Path to UE's Python interpreter.
    :param str output_python_dir: Path to Content/Python/ in the output.
    :return: Set of relative paths that were compiled.
    :rtype: set
    """
    log("Compiling .pyc fallback files...")
    compiled = set()

    for rel_path in DIST_PYC_FILES:
        src_path = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.isfile(src_path):
            continue

        # Place .pyc directly in the package directory (sourceless import).
        rel_dir = os.path.dirname(rel_path)
        basename = os.path.splitext(os.path.basename(rel_path))[0]
        pyc_name = "{}.pyc".format(basename)

        dest_dir = os.path.join(output_python_dir, rel_dir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_pyc = os.path.join(dest_dir, pyc_name)

        # Use UE's Python so the .pyc magic number matches UE's runtime.
        result = subprocess.run(
            [python_exe, "-c",
             "import py_compile; py_compile.compile(r'{}', cfile=r'{}', doraise=True)".format(
                 src_path, dest_pyc)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log("WARNING: Failed to compile {}: {}".format(rel_path, result.stderr.strip()))
            continue

        compiled.add(rel_path)

    log("Compiled {} .pyc fallback files.".format(len(compiled)))
    return compiled


def bundle_python_packages(output_python_dir):
    """
    Collect compiled .pyd + __init__.py + pure-python files into the output.

    Mirrors build_maya.py's ``create_dist_structure()`` — copies .pyd
    compiled extensions, __init__.py stubs, explicit pure-python files,
    and plugin.json manifests.  Skips all other .py source files.

    :param str output_python_dir: Path to Content/Python/ in the output.
    """
    os.makedirs(output_python_dir, exist_ok=True)

    # Build a set of pure-python source paths for fast lookup.
    # Used to skip .pyd duplicates — files in DIST_PURE_PYTHON must ship
    # as .py only (MCP servers are copied to deploy dirs as scripts,
    # venv_manager bootstraps before the environment is ready).
    pure_python_set = set(DIST_PURE_PYTHON)

    for package in DIST_PACKAGES:
        package_path = os.path.join(PROJECT_ROOT, package)
        if not os.path.isdir(package_path):
            log("WARNING: Package not found: {}".format(package))
            continue

        log("Collecting {} ...".format(package))

        for root, dirs, files in os.walk(package_path):
            # Skip __pycache__ and .venv directories.
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]

            # Compute relative path from project root.
            rel_root = os.path.relpath(root, PROJECT_ROOT)
            dest_root = os.path.join(output_python_dir, rel_root)

            # Compiled extensions (.pyd / .so).
            # Skip .pyd files whose module ships as pure Python — prevents
            # shipping both .py source AND .pyd for the same module.
            pyd_files = []
            for f in files:
                if not f.endswith(COMPILED_EXT):
                    continue
                # Extract module name (e.g. "venv_manager" from
                # "venv_manager.cp311-win_amd64.pyd").
                mod_name = f.split(".")[0]
                source_rel = os.path.join(rel_root, mod_name + ".py")
                if source_rel in pure_python_set:
                    continue
                pyd_files.append(f)

            # __init__.py must remain as .py for package discovery.
            init_files = [f for f in files if f == "__init__.py"]

            # Explicit pure-python files that must ship uncompiled.
            pure_files = [
                f for f in files
                if os.path.join(rel_root, f) in pure_python_set
            ]

            # plugin.json manifests for the plugin system.
            json_manifests = [f for f in files if f == "plugin.json"]

            # unreal_tools/ source files — UE's MCP server reads these as
            # source text at runtime to discover tool definitions, so they
            # must ship as .py and cannot be compiled to .pyd or .pyc.
            # Detect by path component so every nested subdir is included.
            path_parts = rel_root.replace("\\", "/").split("/")
            in_unreal_tools = "unreal_tools" in path_parts
            unreal_tools_files = (
                [f for f in files if f.endswith(".py")]
                if in_unreal_tools else []
            )

            files_to_copy = (
                pyd_files + init_files + pure_files
                + json_manifests + unreal_tools_files
            )

            if files_to_copy:
                os.makedirs(dest_root, exist_ok=True)
                for filename in files_to_copy:
                    src = os.path.join(root, filename)
                    dst = os.path.join(dest_root, filename)
                    shutil.copy2(src, dst)

    # Count what we collected.
    pyd_count = 0
    py_count = 0
    pyc_count = 0
    for root, dirs, files in os.walk(output_python_dir):
        for f in files:
            if f.endswith(COMPILED_EXT):
                pyd_count += 1
            elif f.endswith(".pyc"):
                pyc_count += 1
            elif f.endswith(".py"):
                py_count += 1
    log("Collected: {} .pyd, {} .pyc, {} .py files".format(pyd_count, pyc_count, py_count))


def bundle_resources(output_python_dir):
    """
    Copy resource directories (images, gifs) into Content/Python/resources/.

    :param str output_python_dir: Path to Content/Python/ in the output.
    """
    for res_dir in RESOURCE_DIRS:
        src = os.path.join(PROJECT_ROOT, res_dir)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(output_python_dir, res_dir)
        log("Copying resources: {} ...".format(res_dir))
        shutil.copytree(src, dst, dirs_exist_ok=True)


def clean_source_tree():
    """
    Remove in-place build artifacts (.pyd, .c, build/) from the source tree.

    Cleans ALL packages that setup.py compiles — not just DIST_PACKAGES —
    to avoid leaving stale .pyd/.c files from mca_maya, mca_standalone, etc.
    """
    log("Cleaning source tree...")
    removed = 0

    # setup.py compiles these four packages; clean all of them.
    all_packages = ["mca_core", "mca_qt", "mca_standalone", "mca_maya"]
    for package in all_packages:
        package_path = os.path.join(PROJECT_ROOT, package)
        if not os.path.isdir(package_path):
            continue
        for root, dirs, files in os.walk(package_path):
            for filename in files:
                if filename.endswith((".pyd", ".so", ".c")):
                    os.remove(os.path.join(root, filename))
                    removed += 1

    # Remove the build/ directory (Cython intermediates).
    build_dir = os.path.join(PROJECT_ROOT, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)

    log("Cleaned {} build artifacts.".format(removed))


def create_zip(output_dir, zip_path):
    """
    Create a distributable zip from the packaged plugin directory.

    Structured so extracting into Plugins/ creates Plugins/MCAEditor/.

    :param str output_dir: Path to the packaged plugin directory.
    :param str zip_path: Path for the output zip file.
    """
    log("Creating zip: {} ...".format(os.path.basename(zip_path)))

    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(output_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                arcname = os.path.join("MCAEditor", os.path.relpath(filepath, output_dir))
                zf.write(filepath, arcname)
                file_count += 1

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    log("Zip created: {} files, {:.1f} MB".format(file_count, size_mb))


# --- Main --------------------------------------------------------------------

def main():
    """
    Parse arguments and run the full build pipeline.
    """
    parser = argparse.ArgumentParser(
        description="Build MCA Editor plugin for Unreal Engine."
    )
    parser.add_argument(
        "--ue-version",
        default=DEFAULT_UE_VERSION,
        help="UE version to build for (default: {})".format(DEFAULT_UE_VERSION),
    )
    parser.add_argument(
        "--ue-root",
        default=None,
        help="Path to UE installation root (auto-detected if omitted).",
    )
    parser.add_argument(
        "--skip-cpp",
        action="store_true",
        help="Skip C++ compilation (only rebuild Python packages).",
    )
    args = parser.parse_args()

    ue_version = args.ue_version

    print()
    print("=" * 60)
    print("  MCA Editor - Unreal Engine Build")
    print("  Version: {}  |  UE {}  |  {}".format(VERSION, ue_version, sys.platform))
    print("=" * 60)
    print()

    # --- Locate UE installation ---
    if args.ue_root:
        ue_root = args.ue_root
    else:
        ue_root = find_ue_root(ue_version)

    if not ue_root or not os.path.isdir(ue_root):
        print("ERROR: Cannot find UE {} installation.".format(ue_version))
        print("  Searched: {}".format(UE_ROOT_TEMPLATE.format(version=ue_version)))
        print("  Use --ue-root to specify the path manually.")
        sys.exit(1)

    ue_python = find_ue_python(ue_root)
    if not os.path.isfile(ue_python):
        print("ERROR: UE Python not found at: {}".format(ue_python))
        sys.exit(1)

    log("UE root:   {}".format(ue_root))
    log("UE Python: {}".format(ue_python))

    # --- Set up output paths ---
    dist_name = "MCAEditor-UE{}-v{}".format(ue_version, VERSION)
    output_dir = os.path.join(DIST_BASE, dist_name)
    zip_path = os.path.join(DIST_BASE, "{}.zip".format(dist_name))
    output_python_dir = os.path.join(output_dir, "Content", "Python")

    # Clean previous build for this version.
    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    if os.path.isfile(zip_path):
        os.remove(zip_path)

    # ================================================================
    # Step 1: Compile C++ Plugin
    # ================================================================
    print()
    print("-" * 60)
    print("  Step 1: Compile C++ Plugin")
    print("-" * 60)
    print()

    if args.skip_cpp:
        log("Skipping C++ compilation (--skip-cpp).")
        # Copy raw plugin structure — UE will compile on first load.
        os.makedirs(output_dir, exist_ok=True)
        shutil.copy2(
            os.path.join(PLUGIN_SOURCE_DIR, "MCAEditor.uplugin"),
            os.path.join(output_dir, "MCAEditor.uplugin"),
        )
        shutil.copytree(
            os.path.join(PLUGIN_SOURCE_DIR, "Source"),
            os.path.join(output_dir, "Source"),
        )
        shutil.copytree(
            os.path.join(PLUGIN_SOURCE_DIR, "Resources"),
            os.path.join(output_dir, "Resources"),
        )
        log("Copied raw plugin (source-only, no pre-compiled binaries).")
    else:
        if not compile_cpp_plugin(ue_root, output_dir):
            sys.exit(1)

    # ================================================================
    # Step 2: Compile Python with Cython
    # ================================================================
    print()
    print("-" * 60)
    print("  Step 2: Compile Python (.pyd via Cython)")
    print("-" * 60)
    print()

    ensure_cython(ue_python)
    compile_python_extensions(ue_python, ue_root)

    # ================================================================
    # Step 3: Bundle Python into Content/Python/
    # ================================================================
    print()
    print("-" * 60)
    print("  Step 3: Bundle Python Packages")
    print("-" * 60)
    print()

    # Ensure Content/Python/ exists and copy the host script.
    os.makedirs(output_python_dir, exist_ok=True)
    host_script = os.path.join(PLUGIN_SOURCE_DIR, "Content", "Python", "ue_editor_host.py")
    if os.path.isfile(host_script):
        shutil.copy2(host_script, os.path.join(output_python_dir, "ue_editor_host.py"))
        log("Copied ue_editor_host.py")

    # Collect compiled .pyd + __init__.py + pure-python files.
    bundle_python_packages(output_python_dir)

    # Compile .pyc fallbacks for files that crash as .pyd.
    compile_pyc_files(ue_python, output_python_dir)

    # Compile ue_editor_host.py to .pyc for code protection.
    # This file has no Qt virtual overrides so .pyd would work too, but
    # .pyc is simpler and sufficient (it's glue code, not core IP).
    # Python's sourceless import finds .pyc directly in the package dir.
    host_py = os.path.join(output_python_dir, "ue_editor_host.py")
    if os.path.isfile(host_py):
        host_pyc = os.path.join(output_python_dir, "ue_editor_host.pyc")
        result = subprocess.run(
            [ue_python, "-c",
             "import py_compile; py_compile.compile(r'{}', cfile=r'{}', doraise=True)".format(
                 host_py, host_pyc)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            os.remove(host_py)
            log("Compiled ue_editor_host.py -> .pyc (source removed)")
        else:
            log("WARNING: Failed to compile ue_editor_host.py: {}".format(
                result.stderr.strip()))

    # ================================================================
    # Step 4: Bundle Resources
    # ================================================================
    print()
    print("-" * 60)
    print("  Step 4: Bundle Resources")
    print("-" * 60)
    print()

    bundle_resources(output_python_dir)

    # ================================================================
    # Step 5: Clean Source Tree
    # ================================================================
    print()
    print("-" * 60)
    print("  Step 5: Clean Source Tree")
    print("-" * 60)
    print()

    clean_source_tree()

    # ================================================================
    # Step 6: Create Distribution Zip
    # ================================================================
    print()
    print("-" * 60)
    print("  Step 6: Create Distribution Zip")
    print("-" * 60)
    print()

    create_zip(output_dir, zip_path)

    print()
    print("=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    print()
    print("  Plugin folder: {}".format(output_dir))
    print("  Zip archive:   {}".format(zip_path))
    print()
    print("  To install:")
    print("    1. Extract the zip into <YourProject>/Plugins/")
    print("    2. Open the UE project")
    print("    3. Click Window > MCA Editor")
    print()


if __name__ == "__main__":
    main()
