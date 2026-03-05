"""
MCA Core - MCP Server Setup Orchestrator.

Handles the full lifecycle of getting the MCA MCP servers deployed and
registered with Claude Code.  Two servers are managed:

    1. **MCAMayaMCP** — Maya scene tools (create_object, materials, etc.)
    2. **MCAEditorMCP** — Editor tools (open files, edit buffers, execute code)

The entire process is idempotent — safe to call on every launch.  Fast path
on subsequent runs (just file existence checks, no subprocesses).

Setup sequence:
    1. Clone MayaMCP repo (if not present)
    2. Apply patches (delete generate_scene.py, copy our servers)
    3. Create venv with ``mcp`` package (if not present)
    4. Register both servers with Claude Code (if not registered)

All failures are logged but **never** block the editor.  If ``git`` is not
installed, or there's no network, or Claude Code CLI is missing, the setup
silently degrades.  The next launch will pick up where it left off.

Storage layout::

    ~/Documents/mca_preferences/mcp_servers/
        MayaMCP/                    # Git clone (untouched, can git pull)
            src/mayatools/          # Tool .py files (used by Maya server)
            .venv/                  # Venv with mcp package (shared by both servers)
            requirements.txt        # Just "mcp"
        mca_maya_server.py          # Maya scene MCP server (copied from repo)
        mca_maya_server.log         # Maya server log output
        mca_editor_server.py        # Editor MCP server (copied from repo)
        mca_editor_server.log       # Editor server log output

Dependencies:
    - None (pure Python stdlib).  Subprocess calls only when setup is needed.

Side effects:
    - Clones a git repo into ``mca_preferences/mcp_servers/MayaMCP/``
    - Creates a venv at ``mca_preferences/mcp_servers/MayaMCP/.venv/``
    - Copies ``mcp_maya_server.py`` and ``mcp_editor_server.py`` to deploy dir
    - Modifies ``~/.claude.json`` (via ``claude`` CLI or direct JSON write)
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading

# Module-level logger.
logger = logging.getLogger(__name__)

# --- Constants ----------------------------------------------------------------

# Base preferences directory (matches venv_manager.py).
_PREFS_DIR = os.path.join(os.path.expanduser("~/Documents"), "mca_preferences")

# MCP server deployment directory.
_MCP_DIR = os.path.join(_PREFS_DIR, "mcp_servers")

# MayaMCP clone location.
_MAYAMCP_DIR = os.path.join(_MCP_DIR, "MayaMCP")

# Our custom Maya server's deployed location.
_SERVER_DEPLOY_PATH = os.path.join(_MCP_DIR, "mca_maya_server.py")

# The Maya server source file (lives in the repo alongside this file).
_SERVER_SOURCE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mcp_maya_server.py"
)

# Our custom Editor server's deployed location.
_EDITOR_SERVER_DEPLOY_PATH = os.path.join(_MCP_DIR, "mca_editor_server.py")

# The Editor server source file (lives in the repo alongside this file).
_EDITOR_SERVER_SOURCE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "mcp_editor_server.py"
)

# MayaMCP git repo URL.
_MAYAMCP_REPO_URL = "https://github.com/PatrickPalmer/MayaMCP.git"

# The broken tool file to delete after cloning.
_GENERATE_SCENE_PATH = os.path.join(
    _MAYAMCP_DIR, "src", "mayatools", "scene", "generate_scene.py"
)

# Venv location inside the MayaMCP clone.
_MAYAMCP_VENV_DIR = os.path.join(_MAYAMCP_DIR, ".venv")

# Claude Code registration names.
_MCP_SERVER_NAME = "MCAMayaMCP"
_EDITOR_MCP_SERVER_NAME = "MCAEditorMCP"

# Subprocess timeout for git/pip operations (seconds).
_SUBPROCESS_TIMEOUT = 120

# Suppress CMD window popups on Windows.  Every subprocess.run() call
# flashes a visible console window unless CREATE_NO_WINDOW is set.
# On non-Windows platforms this flag is zero (no-op).
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

# Claude config file location.
_CLAUDE_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude.json")


# =============================================================================
# Public API
# =============================================================================

def ensure_maya_mcp(background=True, status_callback=None):
    """
    Ensure the MCA Maya MCP server is deployed and registered.

    This is the main entry point.  Call it from ``initializePlugin()`` (Maya)
    or ``_show_connect_dialog()`` (standalone) after a successful connection.

    The entire setup is idempotent.  On subsequent launches where everything
    is already in place, this returns almost instantly (just file existence
    checks).

    :param bool background: If True, run setup in a background thread so the
        caller doesn't block.  If False, run synchronously.
    :param callable status_callback: Optional callback ``fn(str)`` to report
        progress messages (e.g. for UI status bar).  Called from the worker
        thread if background=True.
    """
    if background:
        thread = threading.Thread(
            target=_run_setup,
            args=(status_callback,),
            name="MCP-Setup",
            daemon=True,
        )
        thread.start()
        logger.info("MCP setup started in background thread.")
    else:
        _run_setup(status_callback)


def get_mcp_server_status():
    """
    Return the current status of both MCP server deployments.

    Used by ``get_mcp_server_info()`` in the adapter classes to report
    actual installation state instead of hardcoded ``installed: False``.

    :return: Status dictionary with ``maya`` and ``editor`` sub-dicts,
        each containing: name, description, installed, registered, server_path.
        Also includes shared keys: venv_path, clone_path.
    :rtype: dict
    """
    venv_ready = _is_venv_ready()

    # Maya MCP server status.
    maya_installed = (
        os.path.isfile(_SERVER_DEPLOY_PATH)
        and os.path.isdir(_MAYAMCP_DIR)
        and venv_ready
    )
    maya_registered = _is_registered(_MCP_SERVER_NAME)

    # Editor MCP server status.
    editor_installed = (
        os.path.isfile(_EDITOR_SERVER_DEPLOY_PATH)
        and venv_ready
    )
    editor_registered = _is_registered(_EDITOR_MCP_SERVER_NAME)

    return {
        "name": _MCP_SERVER_NAME,
        "description": "MCP server for Maya scene manipulation via MCA Editor",
        "installed": maya_installed,
        "registered": maya_registered,
        "server_path": _SERVER_DEPLOY_PATH if os.path.isfile(_SERVER_DEPLOY_PATH) else None,
        "venv_path": _MAYAMCP_VENV_DIR if os.path.isdir(_MAYAMCP_VENV_DIR) else None,
        "clone_path": _MAYAMCP_DIR if os.path.isdir(_MAYAMCP_DIR) else None,
        "editor": {
            "name": _EDITOR_MCP_SERVER_NAME,
            "description": "MCP server for editor control via Claude Code",
            "installed": editor_installed,
            "registered": editor_registered,
            "server_path": _EDITOR_SERVER_DEPLOY_PATH if os.path.isfile(_EDITOR_SERVER_DEPLOY_PATH) else None,
        },
    }


# =============================================================================
# Internal Setup Sequence
# =============================================================================

def _run_setup(status_callback=None):
    """
    Run the full setup sequence.  Idempotent — skips steps that are done.

    Each step checks if its work is already complete before doing anything.
    Failures are logged but don't stop subsequent steps.

    :param callable status_callback: Optional ``fn(str)`` for progress messages.
    """
    def _status(msg):
        logger.info(msg)
        if status_callback:
            try:
                status_callback(msg)
            except Exception:
                pass

    try:
        # Step 1: Clone MayaMCP if not present.
        if not _is_maya_mcp_present():
            _status("Cloning MayaMCP tools...")
            if not _clone_maya_mcp():
                _status("MCP setup: git clone failed (git may not be installed)")
                return

        # Step 2: Apply patches (delete bad tools, copy our server).
        _status("Configuring MCP tools...")
        _apply_patches()

        # Step 3: Create venv and install mcp package.
        if not _is_venv_ready():
            _status("Setting up MCP server venv...")
            if not _setup_venv():
                _status("MCP setup: venv creation failed")
                return

        # Step 4: Register Maya MCP server with Claude Code.
        if not _is_registered(_MCP_SERVER_NAME):
            _status("Registering Maya MCP server with Claude Code...")
            _register_server_with_claude_code(_MCP_SERVER_NAME, _SERVER_DEPLOY_PATH)

        # Step 5: Register Editor MCP server with Claude Code.
        if not _is_registered(_EDITOR_MCP_SERVER_NAME):
            _status("Registering Editor MCP server with Claude Code...")
            _register_server_with_claude_code(_EDITOR_MCP_SERVER_NAME, _EDITOR_SERVER_DEPLOY_PATH)

        _status("Setup complete!")
        logger.info("MCP setup complete. Maya: %s, Editor: %s",
                     _SERVER_DEPLOY_PATH, _EDITOR_SERVER_DEPLOY_PATH)

    except Exception as exc:
        logger.warning("MCP setup failed with unexpected error: %s", exc, exc_info=True)
        _status("MCP setup: unexpected error (check logs)")


# =============================================================================
# Step 1: Clone MayaMCP
# =============================================================================

def _is_maya_mcp_present():
    """
    Check if the MayaMCP clone exists and has the expected structure.

    :return: True if the clone looks valid.
    :rtype: bool
    """
    # Check for the mayatools directory — the thing we actually need.
    tools_dir = os.path.join(_MAYAMCP_DIR, "src", "mayatools")
    return os.path.isdir(tools_dir)


def _clone_maya_mcp():
    """
    Clone the MayaMCP repository into the deployment directory.

    :return: True if the clone succeeded.
    :rtype: bool
    """
    # Find git.
    git = _find_git()
    if not git:
        logger.warning("git not found — cannot clone MayaMCP")
        return False

    # Ensure the parent directory exists.
    os.makedirs(_MCP_DIR, exist_ok=True)

    # If the directory exists but is incomplete (e.g. leftover from a partial
    # wipe), remove it so the clone can proceed cleanly.
    if os.path.isdir(_MAYAMCP_DIR):
        logger.info("Removing incomplete MayaMCP directory before re-clone...")
        shutil.rmtree(_MAYAMCP_DIR, ignore_errors=True)

    logger.info("Cloning MayaMCP from %s to %s ...", _MAYAMCP_REPO_URL, _MAYAMCP_DIR)

    try:
        subprocess.run(
            [git, "clone", _MAYAMCP_REPO_URL, _MAYAMCP_DIR],
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        logger.info("MayaMCP clone complete.")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "git clone failed (exit %d): %s",
            exc.returncode,
            exc.stderr.decode(errors="replace").strip() if exc.stderr else "",
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("git clone timed out after %ds.", _SUBPROCESS_TIMEOUT)
        return False
    except OSError as exc:
        logger.warning("git clone OS error: %s", exc)
        return False


# =============================================================================
# Step 2: Apply Patches
# =============================================================================

def _apply_patches():
    """
    Apply post-clone patches.

    - Delete ``generate_scene.py`` (broken/dangerous tool)
    - Copy our custom Maya MCP server to the deployment directory
    - Copy our custom Editor MCP server to the deployment directory

    Safe to call multiple times.
    """
    # Delete the broken generate_scene.py if it exists.
    if os.path.isfile(_GENERATE_SCENE_PATH):
        try:
            os.remove(_GENERATE_SCENE_PATH)
            logger.info("Deleted broken tool: %s", _GENERATE_SCENE_PATH)
        except OSError as exc:
            logger.warning("Could not delete generate_scene.py: %s", exc)

    os.makedirs(_MCP_DIR, exist_ok=True)

    # Copy the Maya MCP server to the deployment directory.
    if os.path.isfile(_SERVER_SOURCE_PATH):
        try:
            shutil.copy2(_SERVER_SOURCE_PATH, _SERVER_DEPLOY_PATH)
            logger.info("Deployed Maya MCP server to %s", _SERVER_DEPLOY_PATH)
        except OSError as exc:
            logger.warning("Failed to copy Maya server: %s", exc)
    else:
        logger.warning("Maya server source not found at %s — cannot deploy", _SERVER_SOURCE_PATH)

    # Copy the Editor MCP server to the deployment directory.
    if os.path.isfile(_EDITOR_SERVER_SOURCE_PATH):
        try:
            shutil.copy2(_EDITOR_SERVER_SOURCE_PATH, _EDITOR_SERVER_DEPLOY_PATH)
            logger.info("Deployed Editor MCP server to %s", _EDITOR_SERVER_DEPLOY_PATH)
        except OSError as exc:
            logger.warning("Failed to copy Editor server: %s", exc)
    else:
        logger.warning("Editor server source not found at %s — cannot deploy", _EDITOR_SERVER_SOURCE_PATH)


# =============================================================================
# Step 3: Venv Setup
# =============================================================================

def _is_venv_ready():
    """
    Check if the MayaMCP venv exists and has the ``mcp`` package installed.

    Checks for the venv Python executable and the ``mcp`` package directory
    in site-packages.  No subprocess needed.

    :return: True if the venv is ready to run our server.
    :rtype: bool
    """
    venv_python = _get_venv_python()
    if not venv_python or not os.path.isfile(venv_python):
        return False

    # Check for the mcp package in site-packages.
    site_pkg = _get_venv_site_packages()
    if not site_pkg:
        return False

    return os.path.isdir(os.path.join(site_pkg, "mcp"))


def _setup_venv():
    """
    Create the MayaMCP venv and install requirements.

    Uses system Python (not Maya's Python) to create the venv, since this
    venv needs to run standalone as an MCP server process.

    :return: True if the venv is ready.
    :rtype: bool
    """
    system_python = _find_system_python()
    if not system_python:
        logger.warning("No system Python 3.10+ found — cannot create MCP venv")
        return False

    # Create venv if it doesn't exist.
    venv_python = _get_venv_python()
    if not venv_python or not os.path.isfile(venv_python):
        logger.info("Creating MCP venv at %s ...", _MAYAMCP_VENV_DIR)
        try:
            subprocess.run(
                [system_python, "-m", "venv", _MAYAMCP_VENV_DIR],
                check=True,
                timeout=_SUBPROCESS_TIMEOUT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATION_FLAGS,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Venv creation failed (exit %d): %s",
                exc.returncode,
                exc.stderr.decode(errors="replace").strip() if exc.stderr else "",
            )
            return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Venv creation error: %s", exc)
            return False

    # Install requirements from MayaMCP's requirements.txt.
    venv_python = _get_venv_python()
    if not venv_python:
        logger.warning("Venv created but Python not found at expected path")
        return False

    req_file = os.path.join(_MAYAMCP_DIR, "requirements.txt")
    if not os.path.isfile(req_file):
        # Fallback: install mcp directly if requirements.txt is missing.
        install_args = [venv_python, "-m", "pip", "install", "--quiet", "mcp"]
    else:
        install_args = [venv_python, "-m", "pip", "install", "--quiet", "-r", req_file]

    logger.info("Installing MCP requirements...")
    try:
        subprocess.run(
            install_args,
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        logger.info("MCP requirements installed successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "pip install failed (exit %d): %s",
            exc.returncode,
            exc.stderr.decode(errors="replace").strip() if exc.stderr else "",
        )
        return False
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("pip install error: %s", exc)
        return False


def _get_venv_python():
    """
    Get the path to the MayaMCP venv Python executable.

    :return: Path to python.exe (Windows) or python (POSIX), or None.
    :rtype: str or None
    """
    if platform.system() == "Windows":
        path = os.path.join(_MAYAMCP_VENV_DIR, "Scripts", "python.exe")
    else:
        path = os.path.join(_MAYAMCP_VENV_DIR, "bin", "python")

    if os.path.isfile(path):
        return path
    return None


def _get_venv_site_packages():
    """
    Get the site-packages directory of the MayaMCP venv.

    :return: Absolute path to site-packages, or None.
    :rtype: str or None
    """
    if not os.path.isdir(_MAYAMCP_VENV_DIR):
        return None

    if platform.system() == "Windows":
        site_pkg = os.path.join(_MAYAMCP_VENV_DIR, "Lib", "site-packages")
    else:
        lib_dir = os.path.join(_MAYAMCP_VENV_DIR, "lib")
        if not os.path.isdir(lib_dir):
            return None
        site_pkg = None
        for name in os.listdir(lib_dir):
            if name.startswith("python"):
                candidate = os.path.join(lib_dir, name, "site-packages")
                if os.path.isdir(candidate):
                    site_pkg = candidate
                    break
        if not site_pkg:
            return None

    if os.path.isdir(site_pkg):
        return site_pkg
    return None


# =============================================================================
# Step 4: Registration with Claude Code
# =============================================================================

def _is_registered(server_name):
    """
    Check if an MCP server is registered in Claude Code's config.

    Looks for the given server name entry in ``~/.claude.json``.

    :param str server_name: The MCP server registration name to check.
    :return: True if already registered.
    :rtype: bool
    """
    if not os.path.isfile(_CLAUDE_CONFIG_PATH):
        return False

    try:
        with open(_CLAUDE_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    # Check for the server in the mcpServers section.
    mcp_servers = config.get("mcpServers", {})
    return server_name in mcp_servers


def _register_server_with_claude_code(server_name, server_script_path):
    """
    Register an MCP server with Claude Code.

    Strategy:
        1. Try ``claude mcp add-json`` CLI command (preferred — handles all config)
        2. Fallback: write directly to ``~/.claude.json``

    The registration tells Claude Code how to start the MCP server:
    use MayaMCP's venv Python to run the server script.

    :param str server_name: The registration name (e.g. ``MCAMayaMCP``).
    :param str server_script_path: Absolute path to the server ``.py`` file.
    """
    venv_python = _get_venv_python()
    if not venv_python:
        logger.warning("Cannot register %s: MCP venv Python not found", server_name)
        return

    # Build the server configuration JSON.
    server_config = {
        "command": venv_python.replace("\\", "/"),
        "args": [server_script_path.replace("\\", "/")],
    }

    # Try the Claude CLI first.
    claude_cli = _find_claude_code()
    if claude_cli:
        config_json = json.dumps(server_config)
        try:
            subprocess.run(
                [claude_cli, "mcp", "add-json", server_name, config_json,
                 "--scope", "user"],
                check=True,
                timeout=30,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATION_FLAGS,
            )
            logger.info("Registered MCP server via Claude CLI: %s", server_name)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Claude CLI registration for %s failed, falling back to direct write: %s",
                           server_name, exc)

    # Fallback: write directly to ~/.claude.json.
    _register_direct(server_name, server_config)


def _register_direct(server_name, server_config):
    """
    Register by writing directly to ``~/.claude.json``.

    Creates the file if it doesn't exist, or merges into the existing config.

    :param str server_name: The registration name (e.g. ``MCAMayaMCP``).
    :param dict server_config: The MCP server configuration dict.
    """
    config = {}

    # Read existing config if present.
    if os.path.isfile(_CLAUDE_CONFIG_PATH):
        try:
            with open(_CLAUDE_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read existing claude.json: %s", exc)
            # Start fresh rather than corrupt existing config.
            config = {}

    # Ensure mcpServers section exists.
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # Add the server.
    config["mcpServers"][server_name] = server_config

    try:
        with open(_CLAUDE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        logger.info("Registered %s via direct write to %s", server_name, _CLAUDE_CONFIG_PATH)
    except OSError as exc:
        logger.warning("Failed to write claude.json: %s", exc)


# =============================================================================
# Tool Finders
# =============================================================================

def _find_git():
    """
    Locate the ``git`` executable.

    :return: Path to git, or None if not found.
    :rtype: str or None
    """
    try:
        result = subprocess.run(
            ["git", "--version"],
            check=True,
            timeout=10,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        logger.debug("Found git: %s", result.stdout.decode(errors="replace").strip())
        return "git"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError, FileNotFoundError):
        return None


def _find_system_python():
    """
    Find a system Python 3.10+ that is NOT Maya's bundled Python.

    The MCP server venv needs a standalone Python so it can run as its own
    process outside Maya.  Maya's ``mayapy`` would work but drags in Maya
    initialization overhead.

    Search order: ``python``, ``python3``, ``py -3`` (Windows launcher),
    then well-known install locations.

    :return: Path to a suitable Python executable, or None.
    :rtype: str or None
    """
    candidates = []

    if platform.system() == "Windows":
        # Try the Windows Python launcher first (most reliable).
        candidates.append(["py", "-3"])
        # Then try common names on PATH.
        candidates.append(["python"])
        candidates.append(["python3"])
    else:
        candidates.append(["python3"])
        candidates.append(["python"])

    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd + ["--version"],
                check=True,
                timeout=10,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATION_FLAGS,
            )
            version_str = result.stdout.decode(errors="replace").strip()

            # Parse version to ensure 3.10+.
            # Output format: "Python 3.X.Y"
            parts = version_str.split()
            if len(parts) >= 2:
                version_parts = parts[1].split(".")
                major = int(version_parts[0])
                minor = int(version_parts[1]) if len(version_parts) > 1 else 0

                if major >= 3 and minor >= 10:
                    # Make sure it's not mayapy (check for "maya" in path).
                    exe_path = shutil.which(cmd[0])
                    if exe_path and "maya" in exe_path.lower():
                        logger.debug("Skipping Maya Python: %s", exe_path)
                        continue

                    logger.debug("Found system Python %d.%d: %s", major, minor, cmd)
                    # Return the command as a single string or the first element.
                    if len(cmd) == 1:
                        return cmd[0]
                    else:
                        # For "py -3", we need to return both parts.
                        # Since subprocess.run accepts a list, return the first
                        # element and note that callers need to handle "py -3".
                        # Actually, for venv creation we need a single executable.
                        # Use "py" launcher to find the actual python path.
                        py_result = subprocess.run(
                            cmd + ["-c", "import sys; print(sys.executable)"],
                            check=True,
                            timeout=10,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=_CREATION_FLAGS,
                        )
                        exe = py_result.stdout.decode(errors="replace").strip()
                        if os.path.isfile(exe):
                            return exe

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                OSError, FileNotFoundError, ValueError):
            continue

    logger.warning("No system Python 3.10+ found")
    return None


def _find_claude_code():
    """
    Locate the ``claude`` CLI executable.

    :return: Path to claude, or None if not found.
    :rtype: str or None
    """
    # Check if claude is on PATH.
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    # Check common install locations on Windows.
    if platform.system() == "Windows":
        common_paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                         "claude-code", "claude.exe"),
            os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),
        ]
        for path in common_paths:
            if path and os.path.isfile(path):
                return path

    return None
