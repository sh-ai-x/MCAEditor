"""
MCA Core - Update Availability Checker.

Checks whether a newer version of MCA Editor is available by fetching
a small JSON file from the project website.  Runs in a background thread
so it never blocks the UI.  If the user is offline, the server is
unreachable, or the current version is up-to-date, nothing happens —
no output, no error, no warning.

The check runs at most once per Python session (module-level flag).

Dependencies:
    - None (pure Python stdlib — urllib, json, threading)

Side effects:
    - One HTTPS GET to mcaeditor.com/version.json (background thread)
"""

import json
import logging
import os
import platform
import threading

logger = logging.getLogger(__name__)

# --- Constants ----------------------------------------------------------------

# URL of the version metadata file hosted on the project website.
_VERSION_URL = "https://mcaeditor.com/version.json"

# HTTP timeout in seconds — keep short so offline users don't wait.
_HTTP_TIMEOUT = 5

# Module-level flag to ensure the check runs only once per session.
_checked = False


# --- Version Comparison -------------------------------------------------------

def _parse_version(version_str):
    """
    Parse a semantic version string into a comparable tuple of ints.

    Handles versions like ``"1.0.2"`` or ``"1.0.2.beta1"`` — only the
    numeric prefix is used for comparison.

    :param str version_str: Version string (e.g. ``"1.0.2"``).
    :return: Tuple of ints for comparison (e.g. ``(1, 0, 2)``).
    :rtype: tuple
    """
    parts = []
    for segment in version_str.strip().split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            # Stop at the first non-numeric segment (e.g. "beta1").
            break
    return tuple(parts)


# --- SSL Context (reuse from activation.py) -----------------------------------

def _get_ssl_context():
    """
    Build an SSL context that works in Maya's embedded Python.

    Maya's bundled Python on macOS ships with no CA certificates, so
    ``ssl.create_default_context()`` has an empty trust store and every
    HTTPS request fails.  This detects that and loads the macOS system
    certificate bundle from ``/etc/ssl/cert.pem``.

    :return: An SSL context with CA certificates, or None if the default
        context already works.
    :rtype: ssl.SSLContext or None
    """
    import ssl

    ctx = ssl.create_default_context()

    # Check if the default context already has CA certs loaded.
    stats = ctx.cert_store_stats()
    if stats.get("x509_ca", 0) > 0:
        return None

    # macOS Maya fix — load the system certificate bundle.
    if platform.system() == "Darwin":
        macos_cert_bundle = "/etc/ssl/cert.pem"
        if os.path.isfile(macos_cert_bundle):
            try:
                ctx.load_verify_locations(macos_cert_bundle)
                return ctx
            except Exception:
                pass

    # Try certifi as a fallback.
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
        return ctx
    except (ImportError, Exception):
        pass

    return None


# Cached SSL context — built once per session.
_ssl_context = None
_ssl_context_initialized = False


# --- HTTP Fetch ---------------------------------------------------------------

def _fetch_version_info():
    """
    Fetch the latest version info from the project website.

    Makes a single HTTPS GET request with a short timeout.  Returns
    the parsed JSON dict on success, or None on any failure.

    :return: Dict with ``latest_version`` and ``download_url`` keys,
        or None if the request failed.
    :rtype: dict or None
    """
    global _ssl_context, _ssl_context_initialized

    import urllib.request
    import urllib.error

    # Build SSL context once and cache.
    if not _ssl_context_initialized:
        _ssl_context = _get_ssl_context()
        _ssl_context_initialized = True

    req = urllib.request.Request(_VERSION_URL)

    try:
        if _ssl_context is not None:
            resp = urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=_ssl_context)
        else:
            resp = urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)

        data = json.loads(resp.read().decode("utf-8"))
        return data

    except Exception as exc:
        # Network error, timeout, DNS failure, malformed JSON, etc.
        # Fail completely silently — the user should never know this ran.
        logger.debug("Version check failed: %s", exc)
        return None


# --- Public API ---------------------------------------------------------------

def check_for_update(callback):
    """
    Check if a newer version of MCA Editor is available.

    Runs the check in a background thread so the UI is never blocked.
    If a newer version exists, *callback* is called with the new version
    string and download URL.  If the current version is up-to-date, the
    user is offline, or any error occurs, *callback* is never called.

    The check runs at most once per Python session — subsequent calls
    are no-ops.

    :param callable callback: Function to call when an update is available.
        Signature: ``callback(latest_version, download_url)``.
        Called from the background thread — callers must marshal to the
        main thread if updating UI.
    """
    global _checked

    # Only check once per session.
    if _checked:
        return
    _checked = True

    def _worker():
        """Background thread: fetch version info and compare."""
        from mca_core import __version__

        data = _fetch_version_info()
        if data is None:
            return

        latest = data.get("latest_version", "")
        download_url = data.get("download_url", "")

        if not latest:
            return

        # Compare as tuples so "1.0.10" > "1.0.9" works correctly.
        current_tuple = _parse_version(__version__)
        latest_tuple = _parse_version(latest)

        if latest_tuple > current_tuple:
            logger.info(
                "Update available: %s -> %s (download: %s)",
                __version__, latest, download_url,
            )
            try:
                callback(latest, download_url)
            except Exception as exc:
                logger.debug("Update callback failed: %s", exc)
        else:
            logger.debug("MCA Editor is up-to-date (%s)", __version__)

    # Fire and forget — daemon thread dies with the process.
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
