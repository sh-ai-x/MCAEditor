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

    # Packages to compile.
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

    return cythonize(
        py_files,
        compiler_directives={
            "language_level": "3",      # Python 3 semantics.
            "boundscheck": False,       # Disable bounds checking for speed.
            "wraparound": False,        # Disable negative indexing for speed.
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
