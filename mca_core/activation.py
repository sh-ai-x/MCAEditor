"""
MCA Editor -- Online License Activation.

Handles machine activation, validation, and deactivation against the
MCA Editor license server at api.mcaeditor.com.  The editor calls
``activate()`` when a user enters a key, ``validate_on_launch()`` on
each startup, and ``deactivate()`` when the user removes their license.

On first activation the server enforces a 3-machine limit and returns
an activation token.  The token is cached locally so subsequent launches
only need offline HMAC validation — no internet required unless the
cached token is missing or stale.

Machine fingerprinting uses hostname + MAC address hashed with SHA-256
to produce a stable, anonymous machine identifier.

Dependencies:
    - mca_core.license (offline HMAC validation)
    - mca_core.config.settings (QSettings access)
    - urllib.request (stdlib, for HTTP calls to the license server)
    - uuid, socket, platform, hashlib (stdlib, for machine fingerprint)
"""

import hashlib
import json
import logging
import os
import platform
import socket
import time
import uuid

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# License server base URL.
_API_BASE = "https://api.mcaeditor.com"

# Endpoint URLs.
_ACTIVATE_URL = _API_BASE + "/activate"
_VALIDATE_URL = _API_BASE + "/validate"
_DEACTIVATE_URL = _API_BASE + "/deactivate"
_ACTIVATIONS_URL = _API_BASE + "/activations"

# How many days the editor will run offline (without server validation)
# before requiring a network check.  After this period, the editor
# will still try to validate but won't block the user — it just logs.
_OFFLINE_GRACE_DAYS = 7

# Filename for the cached activation token in the preferences directory.
_TOKEN_FILENAME = "activation_token.json"

# HTTP request timeout in seconds.
_HTTP_TIMEOUT = 10


# ============================================================================
# Result Object
# ============================================================================

class ActivationResult:
    """
    Simple result object returned by ``validate_on_launch()``.

    :param bool success: Whether the license check passed.
    :param str status: One of ``"ok"``, ``"offline"``, ``"not_activated"``,
        ``"expired"``, ``"limit_reached"``.
    :param str message: Human-readable status message for UI display.
    """

    def __init__(self, success, status, message):
        """
        Initialise the result.

        :param bool success: Whether the license check passed.
        :param str status: Machine-readable status code.
        :param str message: Human-readable description.
        """
        self.success = success
        self.status = status
        self.message = message

    def __repr__(self):
        return "ActivationResult(success={}, status={!r})".format(
            self.success, self.status
        )


# ============================================================================
# Machine Fingerprinting
# ============================================================================

def _generate_machine_id():
    """
    Generate a stable machine fingerprint.

    Combines hostname and the first non-loopback MAC address, hashed
    with SHA-256.  The result is stable across reboots but changes
    if the NIC is replaced or the hostname is changed.

    :return: 32-character hex string identifying this machine
    :rtype: str
    """
    hostname = socket.gethostname()

    # uuid.getnode() returns the 48-bit MAC address as an integer.
    mac = uuid.getnode()
    mac_str = ":".join(("%012x" % mac)[i:i + 2] for i in range(0, 12, 2))

    raw = "{}:{}".format(hostname, mac_str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _get_machine_name():
    """
    Get a human-readable machine name for the management page.

    :return: String like "DESKTOP-ABC (Windows)" or "studio-mac (Darwin)"
    :rtype: str
    """
    return "{} ({})".format(socket.gethostname(), platform.system())


# ============================================================================
# Token Cache
# ============================================================================

def _get_token_path():
    """
    Get the full path to the cached activation token file.

    :return: Absolute path to activation_token.json
    :rtype: str
    """
    from mca_core import get_prefs_dir
    return os.path.join(get_prefs_dir(), _TOKEN_FILENAME)


def _load_cached_token():
    """
    Load the cached activation token from disk.

    :return: Dict with token data, or None if no cache exists
    :rtype: dict or None
    """
    path = _get_token_path()
    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError, OSError) as exc:
        logger.warning("Failed to read activation cache: %s", exc)
        return None


def _save_cached_token(token, machine_id, product_type="perpetual"):
    """
    Save an activation token to disk.

    :param str token: The activation token from the server
    :param str machine_id: This machine's fingerprint
    :param str product_type: 'perpetual' or 'annual'
    """
    path = _get_token_path()

    # Ensure the preferences directory exists.
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)

    data = {
        "activation_token": token,
        "machine_id": machine_id,
        "product_type": product_type,
        "last_validated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug("Activation token cached to %s", path)
    except (IOError, OSError) as exc:
        logger.warning("Failed to cache activation token: %s", exc)


def _delete_cached_token():
    """Remove the cached activation token from disk."""
    path = _get_token_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.debug("Activation cache deleted")
    except OSError as exc:
        logger.warning("Failed to delete activation cache: %s", exc)


# ============================================================================
# HTTP Helpers
# ============================================================================

def _post_json(url, payload):
    """
    Send a JSON POST request to the license server.

    Uses urllib.request (stdlib) to avoid adding any third-party
    dependency to mca_core.  Returns the parsed JSON response or
    None on network failure.

    :param str url: Full URL to POST to
    :param dict payload: JSON-serializable payload
    :return: Tuple of (status_code, response_dict) or (None, None) on failure
    :rtype: tuple
    """
    import urllib.request
    import urllib.error

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)
        status = resp.status
        resp_data = json.loads(resp.read().decode("utf-8"))
        return status, resp_data
    except urllib.error.HTTPError as exc:
        # Server returned an error status (403, 400, etc.) — still parse body.
        try:
            resp_data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            resp_data = {"error": str(exc)}
        return exc.code, resp_data
    except Exception as exc:
        # Network error, timeout, DNS failure, SSL error, etc.
        logger.debug("HTTP request to %s failed: %s", url, exc)
        return None, None


# ============================================================================
# Public API
# ============================================================================

def validate_on_launch(version, product="maya"):
    """
    Validate the license on startup.

    Checks for a stored key, validates it offline (HMAC), then checks
    the cached activation token.  If the token exists and is recent,
    no server call is made.  If the token is stale or missing, the
    editor still launches (offline grace period).

    :param str version: Plugin version string (e.g. ``"1.0.0"``).
    :param str product: Product identifier (default ``"maya"``).
    :return: Activation result.
    :rtype: ActivationResult
    """
    settings = _get_settings(product)
    from mca_core.license import check_license

    status = check_license(settings)

    if status["licensed"]:
        # Valid key on file — check activation state.
        cached = _load_cached_token()

        if cached and cached.get("activation_token"):
            # We have a cached token — try background validation.
            last_str = cached.get("last_validated", "")
            days_since = _days_since_validation(last_str)

            if days_since <= _OFFLINE_GRACE_DAYS:
                # Within grace period — no server call needed.
                logger.debug("validate_on_launch: licensed, cached token valid (%d days)", days_since)
                return ActivationResult(
                    success=True,
                    status="ok",
                    message=status["message"],
                )

            # Grace period exceeded — try to validate with server.
            stored_key = settings.get("license_key", "")
            srv_status, srv_data = _post_json(_VALIDATE_URL, {
                "key": stored_key,
                "activation_token": cached["activation_token"],
            })

            if srv_status == 200 and srv_data and srv_data.get("valid"):
                # Server confirmed — update last_validated.
                _save_cached_token(
                    cached["activation_token"],
                    cached.get("machine_id", _generate_machine_id()),
                    cached.get("product_type", "perpetual"),
                )
                logger.debug("validate_on_launch: server validated successfully")
                return ActivationResult(
                    success=True,
                    status="ok",
                    message=status["message"],
                )

            if srv_status == 403:
                # Server explicitly rejected — key revoked or activation removed.
                logger.warning("validate_on_launch: server rejected activation")
                _delete_cached_token()
                settings.set("license_key", "")
                return ActivationResult(
                    success=False,
                    status="expired",
                    message=srv_data.get("error", "Activation revoked"),
                )

            # Network error — be lenient, allow continued use.
            logger.debug("validate_on_launch: server unreachable, allowing offline use")
            return ActivationResult(
                success=True,
                status="offline",
                message=status["message"],
            )

        # No cached token — key was entered before online activation existed,
        # or token file was deleted.  Allow use but try to auto-activate
        # silently in the background.
        stored_key = settings.get("license_key", "")
        if stored_key:
            _try_auto_activate(stored_key)

        logger.debug("validate_on_launch: licensed, no cached token (legacy key)")
        return ActivationResult(
            success=True,
            status="ok",
            message=status["message"],
        )

    if status["needs_key"]:
        # Trial expired AND no valid key.
        logger.debug("validate_on_launch: needs key")
        return ActivationResult(
            success=False,
            status="not_activated",
            message=status["message"],
        )

    # Trial still active but no key — not activated yet.
    logger.debug("validate_on_launch: trial active, not activated")
    return ActivationResult(
        success=False,
        status="not_activated",
        message=status["message"],
    )


def get_trial_status(product="maya"):
    """
    Get trial status for this installation.

    Delegates to ``license.get_trial_status()`` using the product-specific
    settings instance.

    :param str product: Product identifier (default ``"maya"``).
    :return: Dict with ``"active"``, ``"days_remaining"``,
        ``"first_launch"``, ``"expired"`` keys.
    :rtype: dict
    """
    settings = _get_settings(product)
    from mca_core.license import get_trial_status as _get_trial
    return _get_trial(settings)


def activate(key, version, product="maya"):
    """
    Activate a license key on this machine.

    First validates the key offline (HMAC check).  If valid, POSTs to
    the license server to register this machine.  On success, stores the
    key in settings and caches the activation token locally.

    :param str key: The license key string (``MCA-XXXX-XXXX-XXXX-XXXX``).
    :param str version: Plugin version string.
    :param str product: Product identifier (default ``"maya"``).
    :return: Dict with ``"success"``, ``"status"``, ``"message"``,
        ``"entitlements"`` keys.
    :rtype: dict
    """
    settings = _get_settings(product)
    from mca_core.license import validate_key, store_license_key

    # Step 1: Offline HMAC validation — reject obviously bad keys fast.
    key_result = validate_key(key)
    if not key_result["valid"]:
        logger.warning("activate: key rejected offline — %s", key_result["error"])
        return {
            "success": False,
            "status": "invalid",
            "message": key_result["error"],
            "entitlements": {},
        }

    # Step 2: Online activation — register this machine with the server.
    machine_id = _generate_machine_id()
    machine_name = _get_machine_name()

    srv_status, srv_data = _post_json(_ACTIVATE_URL, {
        "key": key,
        "machine_id": machine_id,
        "machine_name": machine_name,
    })

    if srv_status == 200 and srv_data and srv_data.get("status") == "ok":
        # Server accepted — store key and cache token.
        store_license_key(settings, key)
        _save_cached_token(
            srv_data["activation_token"],
            machine_id,
            srv_data.get("product_type", "perpetual"),
        )

        logger.info("activate: key activated successfully (%d/%d machines)",
                     srv_data.get("active_count", 1),
                     srv_data.get("machine_limit", 3))
        return {
            "success": True,
            "status": "ok",
            "message": "License activated successfully",
            "entitlements": {
                "product_type": srv_data.get("product_type", "perpetual"),
                "machine_limit": srv_data.get("machine_limit", 3),
                "active_count": srv_data.get("active_count", 1),
            },
        }

    if srv_status == 403 and srv_data:
        # Server rejected — check reason.
        error_status = srv_data.get("status", "invalid")
        error_msg = srv_data.get("error", "Activation failed")

        if error_status == "limit_reached":
            logger.warning("activate: machine limit reached — %s", error_msg)
            return {
                "success": False,
                "status": "limit_reached",
                "message": error_msg,
                "entitlements": {
                    "machine_limit": srv_data.get("machine_limit", 3),
                    "active_count": srv_data.get("active_count", 0),
                },
            }

        logger.warning("activate: server rejected — %s", error_msg)
        return {
            "success": False,
            "status": error_status,
            "message": error_msg,
            "entitlements": {},
        }

    # Network failure — fall back to offline-only activation.
    # Store the key locally so the editor works, but warn that
    # online activation couldn't be completed.
    logger.warning("activate: server unreachable, activating offline only")
    store_license_key(settings, key)

    return {
        "success": True,
        "status": "ok",
        "message": "License activated (offline — server unreachable)",
        "entitlements": {},
    }


def deactivate(product="maya"):
    """
    Deactivate this machine's license.

    Notifies the server to free the activation slot, deletes the cached
    token, and clears the stored key from settings.  If the server is
    unreachable, local state is still cleared.

    :param str product: Product identifier (default ``"maya"``).
    :return: Dict with ``"success"`` and ``"message"`` keys.
    :rtype: dict
    """
    settings = _get_settings(product)
    cached = _load_cached_token()

    # Try to notify the server.
    if cached and cached.get("activation_token"):
        srv_status, srv_data = _post_json(_DEACTIVATE_URL, {
            "activation_token": cached["activation_token"],
        })

        if srv_status == 200:
            logger.info("deactivate: server confirmed deactivation")
        else:
            logger.warning("deactivate: server notification failed (status=%s)", srv_status)

    # Always clear local state regardless of server response.
    _delete_cached_token()
    settings.set("license_key", "")
    logger.info("deactivate: local license key and token cleared")

    return {
        "success": True,
        "message": "License deactivated on this machine",
    }


def deactivate_machine(key, machine_id, product="maya"):
    """
    Deactivate a specific machine remotely (from the Manage tab).

    Used when the user wants to free an activation slot on another
    machine without physical access to it.

    :param str key: The license key string.
    :param str machine_id: The machine_id to deactivate.
    :param str product: Product identifier (default ``"maya"``).
    :return: Dict with ``"success"`` and ``"message"`` keys.
    :rtype: dict
    """
    srv_status, srv_data = _post_json(_DEACTIVATE_URL, {
        "key": key,
        "machine_id": machine_id,
    })

    if srv_status == 200:
        logger.info("deactivate_machine: removed machine %s", machine_id[:12])
        return {"success": True, "message": "Machine deactivated"}

    error = srv_data.get("error", "Failed") if srv_data else "Server unreachable"
    logger.warning("deactivate_machine: failed — %s", error)
    return {"success": False, "message": error}


def get_activations(product="maya"):
    """
    Get list of activated machines for the current key.

    Calls the server's ``/activations`` endpoint and returns the list
    for display in the Manage Activations tab.

    :param str product: Product identifier (default ``"maya"``).
    :return: List of activation dicts, or None if unavailable.
    :rtype: list or None
    """
    settings = _get_settings(product)
    stored_key = settings.get("license_key", "")

    if not stored_key:
        return None

    srv_status, srv_data = _post_json(_ACTIVATIONS_URL, {
        "key": stored_key,
    })

    if srv_status != 200 or not srv_data:
        logger.debug("get_activations: server request failed (status=%s)", srv_status)
        return None

    # Format for the licensing dialog.
    machine_id = _generate_machine_id()
    activations = srv_data.get("activations", [])

    result = []
    for act in activations:
        # Parse machine_name into hostname and platform.
        name = act.get("machine_name", "Unknown")
        parts = name.rsplit(" (", 1)
        hostname = parts[0] if parts else name
        plat = parts[1].rstrip(")") if len(parts) > 1 else ""

        result.append({
            "platform": plat,
            "hostname": hostname,
            "machine_id": act.get("machine_id", ""),
            "activated_at": act.get("activated_at", ""),
            "is_current": act.get("machine_id", "") == machine_id,
        })

    return result


# ============================================================================
# Internal Helpers
# ============================================================================

def _get_settings(product):
    """
    Get the product-specific MCASettings instance.

    For Maya builds, the app name includes the Maya version so settings
    are isolated per-version (e.g. ``MCAEditor-Maya2025``).  Falls back
    to ``MCAEditor`` for standalone or unknown products.

    :param str product: Product identifier (``"maya"`` or ``"standalone"``).
    :return: Settings instance.
    :rtype: MCASettings
    """
    from mca_core.config.settings import MCASettings

    if product == "maya":
        # Try to get the Maya version from plugin_main's global.
        try:
            from mca_maya.plugin_main import _maya_version
            if _maya_version:
                return MCASettings(app_name="MCAEditor-Maya{}".format(_maya_version))
        except ImportError:
            pass

    return MCASettings()


def _days_since_validation(last_validated_str):
    """
    Calculate how many days have passed since the last server validation.

    :param str last_validated_str: ISO timestamp string (e.g. "2026-03-17T10:00:00")
    :return: Days since last validation, or a large number if parsing fails
    :rtype: int
    """
    if not last_validated_str:
        return 9999

    try:
        # Parse the ISO timestamp.
        import datetime
        last_dt = datetime.datetime.strptime(last_validated_str, "%Y-%m-%dT%H:%M:%S")
        now = datetime.datetime.now()
        delta = now - last_dt
        return max(0, delta.days)
    except (ValueError, TypeError):
        return 9999


def _try_auto_activate(key):
    """
    Attempt to silently activate a legacy key in the background.

    Called when a valid key exists in settings but has no cached
    activation token (pre-online-activation key).  Fire-and-forget —
    failures are logged but don't affect the user.

    :param str key: The stored license key
    """
    try:
        machine_id = _generate_machine_id()
        machine_name = _get_machine_name()

        srv_status, srv_data = _post_json(_ACTIVATE_URL, {
            "key": key,
            "machine_id": machine_id,
            "machine_name": machine_name,
        })

        if srv_status == 200 and srv_data and srv_data.get("activation_token"):
            _save_cached_token(
                srv_data["activation_token"],
                machine_id,
                srv_data.get("product_type", "perpetual"),
            )
            logger.info("Auto-activated legacy key successfully")
        else:
            logger.debug("Auto-activation skipped (status=%s)", srv_status)
    except Exception as exc:
        # Fire-and-forget — never crash.
        logger.debug("Auto-activation failed: %s", exc)
