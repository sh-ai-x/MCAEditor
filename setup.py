"""
MCA Editor - Cython Build Script.

Compiles all Python source files in the MCA Editor packages into
Cython ``.pyd`` (Windows) / ``.so`` (Linux/macOS) extensions for
code protection and distribution.

Usage:
    # Build compiled extensions in-place (for testing):
    python setup.py build_ext --inplace

    # Build a wheel with compiled extensions:
    pip install cython build
    python -m build

Dependencies:
    - Cython >= 3.0
    - setuptools >= 68.0
"""

import os
import sys

from setuptools import setup, find_packages

# Pull the canonical version from the package so there is one source of truth.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mca_core import __version__ as VERSION

# --- Maya Python Include Path ------------------------------------------------
# Maya 2025 puts Python.h in a non-standard location:
#   <MAYA>/include/Python311/Python/Python.h
# The default sysconfig include path points to <MAYA>/Python/include/ which
# doesn't exist, so the C compiler can't find Python.h.  We detect this and
# inject the correct include directory.

def _find_maya_paths():
    """
    Locate Maya's non-standard Python include and library directories.

    On Windows, Maya 2025 stores headers and libraries in unusual places:
        Headers:  <MAYA_ROOT>/include/Python311/Python/Python.h
        Library:  <MAYA_ROOT>/lib/python311.lib
    The default sysconfig paths point to non-existent directories, so both
    the compiler and linker fail without this fix.

    On macOS, Maya embeds Python in a framework inside the .app bundle.
    ``sysconfig`` returns the correct paths, but ``distutils.sysconfig``
    (used by setuptools for compilation) returns the system Python framework
    path, causing "Python.h not found" errors.  We return the correct
    ``sysconfig`` include path so it can be injected as an extra include dir.

    :rtype: tuple(str or None, str or None)
    :return: (include_dir, library_dir) — either may be None if not
        running under Maya or the directories don't exist.
    """
    exe = sys.executable
    # Check if we're running under Maya's Python interpreter.
    if "Maya" not in exe and "maya" not in exe:
        return None, None

    # --- macOS: distutils picks up the system Python framework instead of
    #     Maya's embedded framework.  Use sysconfig (which is correct). ---
    if sys.platform == "darwin":
        import sysconfig as _sc
        inc_dir = _sc.get_path("include")
        if inc_dir and os.path.isdir(inc_dir):
            return inc_dir, None
        return None, None

    # --- Windows: Maya puts headers and libs in non-standard locations. ---
    # Walk up from the interpreter to the Maya root.
    # e.g. C:/Program Files/Autodesk/Maya2025/bin/mayapy.exe → Maya2025/
    maya_root = os.path.dirname(os.path.dirname(os.path.abspath(exe)))

    # Maya 2025 uses Python 3.11 → include/Python311/Python/
    ver = "Python{}{}".format(sys.version_info.major, sys.version_info.minor)
    inc_dir = os.path.join(maya_root, "include", ver, "Python")
    if not os.path.isdir(inc_dir):
        inc_dir = None

    # Maya 2025 puts python311.lib in <MAYA_ROOT>/lib/ instead of
    # <MAYA_ROOT>/Python/libs/ where sysconfig says to look.
    lib_dir = os.path.join(maya_root, "lib")
    if not os.path.isdir(lib_dir):
        lib_dir = None

    return inc_dir, lib_dir

# --- Cython Extension Collection -------------------------------------------

def collect_extensions():
    """
    Collect all .py files from MCA Editor packages for Cython compilation.

    Skips __init__.py files (must remain as Python for package discovery),
    __main__.py files, and any test files.

    :return: List of Cython Extension objects.
    :rtype: list
    """
    try:
        from Cython.Build import cythonize
    except ImportError:
        print("WARNING: Cython not installed. Skipping compilation.")
        print("Install with: pip install cython")
        return []

    # Compile all packages.  The binding=True directive preserves Python
    # method signatures so Shiboken can introspect Qt virtual overrides.
    packages = ["mca_core", "mca_qt", "mca_standalone", "mca_maya"]

    # Files to skip during compilation (shipped as .pyc instead).
    # ANY file with a Qt virtual method override (eventFilter, paintEvent,
    # keyPressEvent, sizeHint, etc.) crashes when compiled to .pyd because
    # Shiboken's C++ virtual dispatch fails on enum-typed arguments in
    # Cython-compiled code.  The crash is ACCESS_VIOLATION at 0x00000008
    # in Shiboken::Enum::unpickleEnum, triggered during Qt's paint/event
    # dispatch cycles.  Files without Qt virtual overrides compile fine.
    exclude_from_compilation = {
        # --- mca_maya ---
        os.path.join("mca_maya", "maya_window.py"),          # eventFilter, event
        # --- mca_qt ---
        os.path.join("mca_qt", "editor_panel.py"),           # showEvent
        # --- mca_qt/widgets ---
        os.path.join("mca_qt", "widgets", "code_editor.py"),       # paintEvent, keyPressEvent, sizeHint, event, etc.
        os.path.join("mca_qt", "widgets", "completer.py"),         # eventFilter
        os.path.join("mca_qt", "widgets", "drag_tab_manager.py"), # eventFilter
        os.path.join("mca_qt", "widgets", "drop_zone_overlay.py"), # paintEvent
        os.path.join("mca_qt", "widgets", "editor_group.py"),     # mousePressEvent, paintEvent, eventFilter, etc.
        os.path.join("mca_qt", "widgets", "find_in_files.py"),    # closeEvent
        os.path.join("mca_qt", "widgets", "find_replace_bar.py"), # eventFilter, keyPressEvent
        os.path.join("mca_qt", "widgets", "output_window.py"),    # eventFilter, keyPressEvent, event
        os.path.join("mca_qt", "widgets", "quick_open.py"),       # eventFilter
        os.path.join("mca_qt", "widgets", "settings_dialog.py"),  # keyPressEvent
        os.path.join("mca_qt", "widgets", "sidebar.py"),          # dragEnterEvent, dragMoveEvent, dropEvent
        os.path.join("mca_qt", "widgets", "terminal_native.py"),  # eventFilter, resizeEvent
        os.path.join("mca_qt", "widgets", "terminal_xterm.py"),   # eventFilter
        os.path.join("mca_qt", "widgets", "tool_stripe.py"),      # sizeHint
        os.path.join("mca_qt", "widgets", "plugin_settings_dialog.py"),  # keyPressEvent
        os.path.join("mca_qt", "widgets", "editor_group_container.py"),   # QWidget + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "terminal_tab_panel.py"),       # QWidget + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "terminal_backend.py"),         # QThread + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "ai_panel.py"),                 # QFrame/QWidget + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "connection_dialog.py"),        # QDialog + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "create_project_dialog.py"),    # QDialog + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "license_dialog.py"),           # QDialog + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "licensing_dialog.py"),        # QDialog + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "new_tab_dialog.py"),           # QDialog + PySide2 Shiboken2
        os.path.join("mca_qt", "widgets", "project_settings_dialog.py"),  # QDialog + PySide2 Shiboken2
        # --- AI Chat plugin ---
        os.path.join("mca_core", "plugins", "ai_chat", "chat_widget.py"),   # keyPressEvent
        os.path.join("mca_core", "plugins", "ai_chat", "chat_worker.py"),   # QThread.run()
    }

    py_files = []
    for package in packages:
        for root, dirs, files in os.walk(package):
            # Skip __pycache__ and test directories.
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]

            for filename in files:
                if not filename.endswith(".py"):
                    continue
                # Keep __init__.py as pure Python (needed for package discovery).
                if filename == "__init__.py":
                    continue
                # Keep __main__.py as pure Python (needed for -m invocation).
                if filename == "__main__.py":
                    continue

                filepath = os.path.join(root, filename)
                # Skip files excluded from compilation (shipped as .pyc).
                if filepath in exclude_from_compilation:
                    continue
                py_files.append(filepath)

    if not py_files:
        return []

    print("Cythonizing {} files:".format(len(py_files)))
    for f in py_files:
        print("  {}".format(f))

    # Check if Maya's Python headers and libraries are in non-standard
    # locations and inject the correct paths for the compiler and linker.
    maya_inc, maya_lib = _find_maya_paths()
    extra_include = []
    extra_lib_dirs = []
    if maya_inc:
        print("Maya Python include: {}".format(maya_inc))
        extra_include.append(maya_inc)
    if maya_lib:
        print("Maya Python libdir:  {}".format(maya_lib))
        extra_lib_dirs.append(maya_lib)

    # Environment variable overrides for non-standard Python installations.
    # build_unreal.py sets these because UE's bundled Python has headers at
    # Engine/Source/ThirdParty/Python3/Win64/include/ instead of the usual
    # sysconfig location, so the C compiler can't find Python.h without help.
    env_inc = os.environ.get("MCA_PYTHON_INCLUDE")
    env_lib = os.environ.get("MCA_PYTHON_LIBDIR")
    if env_inc and os.path.isdir(env_inc):
        print("Custom Python include: {}".format(env_inc))
        extra_include.append(env_inc)
    if env_lib and os.path.isdir(env_lib):
        print("Custom Python libdir:  {}".format(env_lib))
        extra_lib_dirs.append(env_lib)

    # Build Extension objects from the .py file list so we can attach
    # the extra include/library directories that Maya needs.
    from setuptools import Extension

    extensions = []
    for filepath in py_files:
        # Convert file path to dotted module name.
        # e.g. "mca_core/license.py" → "mca_core.license"
        mod_name = filepath.replace(os.sep, ".").replace("/", ".")[:-3]
        ext = Extension(
            mod_name,
            sources=[filepath],
            include_dirs=extra_include,
            library_dirs=extra_lib_dirs,
        )
        extensions.append(ext)

    return cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",      # Python 3 semantics.
            "binding": True,            # Required for PySide6/Shiboken — preserves
                                        # Python method signatures so Qt's metaclass
                                        # can introspect virtual overrides and slots.
            "boundscheck": False,       # Disable for performance (all indexing is safe).
            "wraparound": True,         # Keep Python negative-indexing semantics —
                                        # the codebase uses [-1] extensively.
        },
        # Force regeneration of .c intermediates even if timestamps look fresh.
        # Without this, Cython may skip recompilation after edits, causing the
        # compiled .pyd to silently contain stale code.
        force=True,
        # Don't fail if a single file has issues.
        nthreads=os.cpu_count() or 1,
    )


# --- Setup ------------------------------------------------------------------

if __name__ == "__main__":
    extensions = collect_extensions()

    setup(
        name="mcaeditor",
        version=VERSION,
        packages=find_packages(include=[
            "mca_core*", "mca_qt*", "mca_standalone*", "mca_maya*", "mca_editor*",
        ]),
        ext_modules=extensions,
        python_requires=">=3.9",
        install_requires=["PySide6>=6.5.0"],
    )
