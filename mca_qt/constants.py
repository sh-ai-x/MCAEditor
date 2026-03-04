"""
MCA Qt - Shared Constants.

Centralises directory-skip rules and depth limits used across multiple
modules (find_in_files, quick_open, editor_panel, sidebar) so they stay
in sync without duplication.

Dependencies: None
"""

# --- Filesystem Walk Constants -----------------------------------------------

# Directories to skip during recursive workspace scanning.
# These are standard non-source directories that should never appear
# in search results, file pickers, or the workspace tree.
SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".tox", ".eggs", "dist",
    "build", ".idea", ".vs", ".vscode",
}

# Maximum directory depth for recursive scanning.  Prevents runaway
# traversal into deeply nested dependency trees.
MAX_WALK_DEPTH = 5
