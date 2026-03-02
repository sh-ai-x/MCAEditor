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

# --- Maya Python Include Path ------------------------------------------------
# Maya 2025 puts Python.h in a non-standard location:
#   <MAYA>/include/Python311/Python/Python.h
# The default sysconfig include path points to <MAYA>/Python/include/ which
# doesn't exist, so the C compiler can't find Python.h.  We detect this and
# inject the correct include directory.

def _find_maya_paths():
    """
    Locate Maya's non-standard Python include and library directories.

    Maya 2025 stores these in unusual places:
        Headers:  <MAYA_ROOT>/include/Python311/Python/Python.h
        Library:  <MAYA_ROOT>/lib/python311.lib

    The default sysconfig paths point to <MAYA_ROOT>/Python/include/ and
    <MAYA_ROOT>/Python/libs/ which don't exist, so both the compiler and
    linker fail.

    :rtype: tuple(str or None, str or None)
    :return: (include_dir, library_dir) — either may be None if not
        running under Maya or the directories don't exist.
    """
    exe = sys.executable
    # Check if we're running under Maya's Python interpreter.
    if "Maya" not in exe and "maya" not in exe:
        return None, None

    # Walk up from the interpreter to the Maya root.
    # e.g. C:/Program Files/Autodesk/Maya2025/bin/mayapy.exe → Maya2025/
    maya_root = os.path.dirname(os.path.dirname(os.path.abspath(exe)))

    # --- Include directory ---
    # Maya 2025 uses Python 3.11 → include/Python311/Python/
    ver = "Python{}{}".format(sys.version_info.major, sys.version_info.minor)
    inc_dir = os.path.join(maya_root, "include", ver, "Python")
    if not os.path.isdir(inc_dir):
        inc_dir = None

    # --- Library directory ---
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

    # All packages are compiled to .pyd — no source code ships in the build.
    packages = ["mca_core", "mca_qt", "mca_standalone", "mca_maya"]

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

    from Cython.Build import cythonize
    return cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",      # Python 3 semantics.
            "binding": True,            # Required for PySide6/Shiboken — preserves
                                        # Python method signatures so Qt's metaclass
                                        # can introspect virtual overrides and slots.
            "boundscheck": False,       # Disable bounds checking for speed.
            "wraparound": True,         # Keep Python negative-indexing semantics —
                                        # the codebase uses [-1] extensively and the
                                        # performance cost is negligible for a UI app.
        },
        # Don't fail if a single file has issues.
        nthreads=os.cpu_count() or 1,
    )


# --- Setup ------------------------------------------------------------------

if __name__ == "__main__":
    extensions = collect_extensions()

    setup(
        name="mcaeditor",
        version="0.1.0",
        packages=find_packages(include=[
            "mca_core*", "mca_qt*", "mca_standalone*", "mca_maya*", "mca_editor*",
        ]),
        ext_modules=extensions,
        python_requires=">=3.9",
        install_requires=["PySide6>=6.5.0"],
    )
