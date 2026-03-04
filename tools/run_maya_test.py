"""
MCA Editor — Automated Maya Test Runner.

Launches Maya with the plugin smoke test, waits for results, and
reports pass/fail.  Optionally builds and deploys the plugin first.

Usage:
    # Test current deployed plugin (no build):
    python tools/run_maya_test.py

    # Build, deploy, then test:
    python tools/run_maya_test.py --build

    # Custom timeout (default 120s):
    python tools/run_maya_test.py --build --timeout 180

    # Run comprehensive editor test suite (~80 tests):
    python tools/run_maya_test.py --full --timeout 300

Exit codes:
    0 = PASS (plugin loaded, window opened, event loop survived)
    1 = FAIL (crash, exception, or timeout)

Dependencies: None (stdlib only)
Side effects: Launches Maya, writes to %TEMP%/mca_test_result.log
"""

import os
import sys
import time
import shutil
import subprocess

# --- Constants ---------------------------------------------------------------

# Maya 2025 executable.
MAYA_EXE = "C:/Program Files/Autodesk/Maya2025/bin/maya.exe"
MAYAPY_EXE = "C:/Program Files/Autodesk/Maya2025/bin/mayapy.exe"

# Project root (one level up from tools/).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Test script that runs inside Maya (smoke test).
TEST_SCRIPT = os.path.join(PROJECT_ROOT, "tools", "maya_plugin_test.py")

# Comprehensive editor test script (used with --full).
FULL_TEST_SCRIPT = os.path.join(PROJECT_ROOT, "tools", "maya_editor_test.py")

# Log file written by the test script.
LOG_PATH = os.path.join(os.environ.get("TEMP", "C:/Temp"), "mca_test_result.log")

# Extraction cache directory.
EXTRACT_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "MCAEditor"
)

# Maya plug-ins directory.
MAYA_PLUGINS_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "maya", "2025", "plug-ins"
)

# Default timeout in seconds.
DEFAULT_TIMEOUT = 120

# Default timeout for comprehensive tests (longer due to ~80 tests).
FULL_TEST_TIMEOUT = 300


# --- Build & Deploy ---------------------------------------------------------

def build_and_deploy():
    """
    Run the full build pipeline and deploy to Maya's plug-ins folder.

    Calls build_maya.py then pack_single_file.py using mayapy for
    compilation, then copies the packed plugin to Maya's plug-ins dir.

    :raises SystemExit: If any build step fails.
    """
    print("\n=== Building ===")

    # Step 1: Build compiled distribution.
    build_script = os.path.join(PROJECT_ROOT, "build_maya.py")
    result = subprocess.run(
        [sys.executable, build_script],
        cwd=PROJECT_ROOT
    )
    if result.returncode != 0:
        print("ERROR: build_maya.py failed")
        sys.exit(1)

    # Step 2: Pack into single file.
    pack_script = os.path.join(PROJECT_ROOT, "pack_single_file.py")
    result = subprocess.run(
        [sys.executable, pack_script],
        cwd=PROJECT_ROOT
    )
    if result.returncode != 0:
        print("ERROR: pack_single_file.py failed")
        sys.exit(1)

    # Step 3: Clear extraction cache so Maya re-extracts fresh.
    if os.path.isdir(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)
        print("Cleared extraction cache: {}".format(EXTRACT_DIR))

    # Step 4: Copy packed plugin to Maya's plug-ins folder.
    src = os.path.join(PROJECT_ROOT, "dist", "mcaEditor.py")
    dst = os.path.join(MAYA_PLUGINS_DIR, "mcaEditor.py")
    os.makedirs(MAYA_PLUGINS_DIR, exist_ok=True)
    shutil.copy2(src, dst)
    print("Deployed: {}".format(dst))


# --- Test Runner ------------------------------------------------------------

def run_maya_test(timeout, test_script=None):
    """
    Launch Maya with a test script and wait for results.

    :param int timeout: Maximum seconds to wait for Maya.
    :param str test_script: Path to the test script. Defaults to TEST_SCRIPT.
    :return: Tuple of (passed, last_step, full_log).
    :rtype: tuple(bool, str, str)
    """
    # Use the default smoke test if no script specified.
    if test_script is None:
        test_script = TEST_SCRIPT

    # Clear old log.
    if os.path.isfile(LOG_PATH):
        os.remove(LOG_PATH)

    # Clear extraction cache to force fresh extraction.
    if os.path.isdir(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)
        print("Cleared extraction cache")

    # Build the MEL command that sources our Python test script.
    # The test script uses executeDeferred to run after Maya startup.
    test_path = test_script.replace("\\", "/")
    mel_cmd = "python(\"exec(open(r'{}').read())\")".format(test_path)

    print("\n=== Launching Maya ===")
    print("  Command: maya.exe -command \"{}\"".format(mel_cmd))
    print("  Timeout: {}s".format(timeout))
    print("  Log: {}".format(LOG_PATH))

    # Launch Maya with the test command.
    proc = subprocess.Popen(
        [MAYA_EXE, "-command", mel_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll for results.
    start = time.time()
    passed = False
    while time.time() - start < timeout:
        # Check if Maya exited (crash or normal quit).
        if proc.poll() is not None:
            break

        # Check log for final PASS/FAIL verdict.
        # The comprehensive test writes "[PASS] test_name" per test, so we
        # look for a standalone "PASS" or "FAIL" line (no brackets) that
        # signals the suite is done.
        if os.path.isfile(LOG_PATH):
            with open(LOG_PATH, "r") as f:
                content = f.read()
            # Scan from end for the final verdict line.
            done = False
            for log_line in reversed(content.split("\n")):
                verdict = log_line.strip()
                if verdict == "PASS":
                    passed = True
                    done = True
                    break
                elif verdict == "FAIL":
                    passed = False
                    done = True
                    break
            if done:
                break

        time.sleep(2)

    # Give Maya a moment to fully exit after PASS.
    if passed and proc.poll() is None:
        # Maya should be quitting — wait a few more seconds.
        for _ in range(10):
            if proc.poll() is not None:
                break
            time.sleep(1)

    # Kill Maya if still running (timeout or hung).
    if proc.poll() is None:
        print("  Killing Maya (timeout or hung)...")
        proc.kill()
        proc.wait()

    # Read final log.
    full_log = ""
    last_step = "NO_LOG"
    if os.path.isfile(LOG_PATH):
        with open(LOG_PATH, "r") as f:
            full_log = f.read().strip()
        # Last non-empty line is the final step/verdict.
        lines = [l for l in full_log.split("\n") if l.strip()]
        if lines:
            last_step = lines[-1]
        # Check for standalone PASS verdict (not "[PASS] test_name").
        passed = any(l.strip() == "PASS" for l in full_log.split("\n"))

    return passed, last_step, full_log


# --- Main -------------------------------------------------------------------

def _print_full_summary(full_log):
    """
    Parse [PASS] and [FAIL] lines from the full test log and print a
    summary table.  Used with --full mode.

    :param str full_log: Complete log file contents.
    :return: Tuple of (pass_count, fail_count).
    :rtype: tuple(int, int)
    """
    pass_lines = []
    fail_lines = []

    for line in full_log.split("\n"):
        stripped = line.strip()
        if stripped.startswith("[PASS]"):
            pass_lines.append(stripped)
        elif stripped.startswith("[FAIL]"):
            fail_lines.append(stripped)

    # Print all results grouped by status.
    print("\n=== Test Results ===")

    if fail_lines:
        print("\n  FAILURES:")
        for line in fail_lines:
            print("    {}".format(line))

    print("\n  PASSED: {}".format(len(pass_lines)))
    print("  FAILED: {}".format(len(fail_lines)))
    print("  TOTAL:  {}".format(len(pass_lines) + len(fail_lines)))

    return len(pass_lines), len(fail_lines)


def main():
    """
    Parse arguments and run Maya plugin tests.

    Supports two modes:
    - Default (smoke test): load plugin, open window, survive 5s.
    - --full: Comprehensive editor test suite (~80 tests via EditorAPI).
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Run MCA Editor Maya plugin tests."
    )
    parser.add_argument(
        "--build", action="store_true",
        help="Build and deploy the plugin before testing.",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Run comprehensive editor test suite (~80 tests).",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Maximum seconds to wait for Maya (default: {} smoke, {} full).".format(
            DEFAULT_TIMEOUT, FULL_TEST_TIMEOUT
        ),
    )
    args = parser.parse_args()

    # Pick the right test script and timeout based on mode.
    if args.full:
        test_script = FULL_TEST_SCRIPT
        timeout = args.timeout or FULL_TEST_TIMEOUT
        mode_label = "comprehensive"
    else:
        test_script = TEST_SCRIPT
        timeout = args.timeout or DEFAULT_TIMEOUT
        mode_label = "smoke"

    # Verify Maya exists.
    if not os.path.isfile(MAYA_EXE):
        print("ERROR: Maya not found at: {}".format(MAYA_EXE))
        sys.exit(1)

    # Verify test script exists.
    if not os.path.isfile(test_script):
        print("ERROR: Test script not found: {}".format(test_script))
        sys.exit(1)

    print("Mode: {} test".format(mode_label))

    # Optionally build first.
    if args.build:
        build_and_deploy()

    # Run the test.
    passed, last_step, full_log = run_maya_test(timeout, test_script)

    # Report results.
    if args.full and full_log:
        # Parse structured [PASS]/[FAIL] lines for the summary table.
        pass_count, fail_count = _print_full_summary(full_log)
        print()
        if fail_count == 0 and pass_count > 0:
            print("RESULT: PASS ({} tests)".format(pass_count))
            sys.exit(0)
        else:
            print("RESULT: FAIL ({} passed, {} failed)".format(
                pass_count, fail_count))
            sys.exit(1)
    else:
        # Smoke test — simple output.
        print("\n=== Test Results ===")
        if full_log:
            for line in full_log.split("\n"):
                print("  {}".format(line))
        else:
            print("  (no log output)")

        print()
        if passed:
            print("RESULT: PASS")
            sys.exit(0)
        else:
            print("RESULT: FAIL (last step: {})".format(last_step))
            sys.exit(1)


# Script guard.
if __name__ == "__main__":
    main()
