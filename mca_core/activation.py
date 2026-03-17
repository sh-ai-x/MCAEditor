"""
MCA Editor -- License Activation Stub.

Provides the expected API surface for online license activation so the
full code path (license check on plugin load, licensing dialog, trial
banner) can exercise without a live server.  Every function falls back
to the existing offline system in ``mca_core.license``.

When the real activation server is wired up, this module will be replaced
with HTTP calls to the license server.  Until then the stubs return safe
defaults that let the editor run in offline/trial mode.

Dependencies:
    - mca_core.license (offline HMAC validation)
    - mca_core.config.settings (QSettings access)
"""

import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Result Object
# =============================================================================

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


# =============================================================================
# Public API — Stubs
# =============================================================================

def validate_on_launch(version, product="maya"):
    """
    Validate the license on startup.

    Checks the stored key via ``license.check_license()`` and wraps the
    result in an :class:`ActivationResult`.  When a live server is
    available this will also refresh cached tokens.

    Stub behaviour:
        - Licensed user  -> ``success=True, status="ok"``
        - Active trial   -> ``success=False, status="not_activated"``
        - Expired trial  -> ``success=False, status="not_activated"``
        - Invalid key    -> ``success=False, status="expired"``

    :param str version: Plugin version string (e.g. ``"0.4.0"``).
    :param str product: Product identifier (default ``"maya"``).
    :return: Activation result.
    :rtype: ActivationResult
    """
    from mca_core.config.settings import MCASettings

    # Use product-aware app name to match plugin_main.py settings scope.
    settings = _get_settings(product)
    from mca_core.license import check_license
    status = check_license(settings)

    if status["licensed"]:
        # Valid key on file — report success.
        logger.debug("validate_on_launch: licensed (%s)", status["message"])
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
    Activate a license key.

    Stub: falls back to offline validation via ``license.store_license_key()``.
    When the license server is connected, this will POST the key to the
    server and return entitlements.

    :param str key: The license key string (``MCA-XXXX-XXXX-XXXX-XXXX``).
    :param str version: Plugin version string.
    :param str product: Product identifier (default ``"maya"``).
    :return: Dict with ``"success"``, ``"status"``, ``"message"``,
        ``"entitlements"`` keys.
    :rtype: dict
    """
    settings = _get_settings(product)
    from mca_core.license import store_license_key

    # Use the offline validator to check and store the key.
    result = store_license_key(settings, key)

    if result["valid"]:
        logger.info("activate: key accepted (offline validation)")
        return {
            "success": True,
            "status": "ok",
            "message": "License activated successfully",
            "entitlements": {},
        }
    else:
        logger.warning("activate: key rejected — %s", result["error"])
        return {
            "success": False,
            "status": "invalid",
            "message": result["error"],
            "entitlements": {},
        }


def deactivate(product="maya"):
    """
    Deactivate this machine's license.

    Stub: clears the stored key from settings.  When the license server
    is connected, this will also notify the server to free the seat.

    :param str product: Product identifier (default ``"maya"``).
    :return: Dict with ``"success"`` and ``"message"`` keys.
    :rtype: dict
    """
    settings = _get_settings(product)

    # Clear the stored key.
    settings.set("license_key", "")
    logger.info("deactivate: license key cleared")

    return {
        "success": True,
        "message": "License deactivated on this machine",
    }


def get_activations(product="maya"):
    """
    Get list of activated machines for the current key.

    Stub: returns ``None`` to indicate online activation info is
    unavailable.  The licensing dialog shows a placeholder when this
    returns ``None``.

    When the license server is connected, this will return a list of
    dicts with ``"platform"``, ``"hostname"``, ``"activated_at"``,
    ``"is_current"`` keys.

    :param str product: Product identifier (default ``"maya"``).
    :return: List of activation dicts, or ``None`` if unavailable.
    :rtype: list or None
    """
    # Online activation list not available in stub mode.
    return None


# =============================================================================
# Internal Helpers
# =============================================================================

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
