"""
MCA Core - Plugin Manifest Verification.

Handles loading and verifying ``plugin_manifest.json`` files for the
plugin monetization system.  Each manifest contains metadata about the
plugin's pricing model and is signed with an HMAC-SHA256 signature so
the editor can reject tampered manifests.

A plugin WITHOUT a ``plugin_manifest.json`` is treated as a legacy
free plugin — no verification is required and it loads normally.

Dependencies: None (stdlib only)
Side effects: None
"""

import os
import json
import hmac
import hashlib
import base64
import logging

# Module-level logger for manifest operations.
logger = logging.getLogger(__name__)


# --- Constants ---------------------------------------------------------------

# Placeholder HMAC key for development.  Will be replaced with a real
# key before the first production release of the marketplace.
_MANIFEST_HMAC_KEY = b"MCA_MANIFEST_DEV_KEY_PLACEHOLDER"

# The manifest file name that triggers monetization checks.
MANIFEST_FILENAME = "plugin_manifest.json"


# =============================================================================
# Plugin Manifest Data Class
# =============================================================================

class PluginManifest:
    """
    Plain data object holding all fields from a ``plugin_manifest.json``.

    Fields map 1:1 to the JSON keys.  Missing keys default to empty
    strings so callers can safely read any attribute without guards.
    """

    def __init__(self):
        """Initialize all manifest fields to empty defaults."""
        self.manifest_version = 0       # Schema version of the manifest format (integer).
        self.plugin_id = ""             # Unique plugin identifier (reverse-domain).
        self.display_name = ""          # Human-readable name for UI display.
        self.version = ""               # Semantic version of the plugin.
        self.author = ""                # Author / publisher name.
        self.developer_id = ""          # Developer account ID in the marketplace.
        # Pricing is a nested dict matching the JSON schema:
        #   {"model": "free"|"paid"|"subscription",
        #    "gumroad_permalink": "...", "purchase_url": "..."}
        self.pricing = {}
        self.entry_point = ""           # Python entry point file (e.g. "__init__.py").
        self.min_mca_version = ""       # Minimum MCA Editor version required.
        self.mca_signature = ""         # Base64-encoded HMAC-SHA256 signature.

        # Internal: path to the plugin directory (not serialized).
        self._plugin_dir = ""


# =============================================================================
# Loading
# =============================================================================

def load(plugin_dir):
    """
    Load a ``plugin_manifest.json`` from a plugin directory.

    Returns ``None`` if the file does not exist — this means the plugin
    has no monetization manifest and should be treated as a free legacy
    plugin.  Returns a populated ``PluginManifest`` on success, or
    ``None`` on parse errors (with a warning logged).

    :param str plugin_dir: Absolute path to the plugin's root directory.
    :return: A populated PluginManifest, or None if no manifest exists.
    :rtype: PluginManifest or None
    """
    manifest_path = os.path.join(plugin_dir, MANIFEST_FILENAME)

    # No manifest file = legacy free plugin, nothing to check.
    if not os.path.exists(manifest_path):
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError, OSError) as exc:
        logger.warning("Failed to read plugin manifest: %s (%s)", manifest_path, exc)
        return None

    # Populate the manifest object from the JSON data.
    manifest = PluginManifest()
    manifest.manifest_version = data.get("manifest_version", 0)
    manifest.plugin_id = data.get("plugin_id", "")
    manifest.display_name = data.get("display_name", "")
    manifest.version = data.get("version", "")
    manifest.author = data.get("author", "")
    manifest.developer_id = data.get("developer_id", "")

    # Pricing lives in a nested object in the JSON schema.
    pricing_data = data.get("pricing", {})
    manifest.pricing = {
        "model": pricing_data.get("model", ""),
        "gumroad_permalink": pricing_data.get("gumroad_permalink", ""),
        "purchase_url": pricing_data.get("purchase_url", ""),
    }

    manifest.entry_point = data.get("entry_point", "")
    manifest.min_mca_version = data.get("min_mca_version", "")
    manifest.mca_signature = data.get("mca_signature", "")
    manifest._plugin_dir = plugin_dir

    logger.debug("Loaded plugin manifest: %s (%s)", manifest.plugin_id, manifest_path)
    return manifest


# =============================================================================
# Signature Verification
# =============================================================================

def _canonical_json(manifest):
    """
    Build the canonical JSON string for signature verification.

    Includes all manifest fields EXCEPT ``mca_signature``, serialized
    with sorted keys and no indentation.  This ensures the signature
    is deterministic regardless of field order in the JSON file.

    :param PluginManifest manifest: The manifest to canonicalize.
    :return: Canonical JSON string (UTF-8).
    :rtype: str
    """
    # Build a dict of all signable fields (everything except the signature).
    # The "pricing" key is a nested dict — json.dumps with sort_keys handles
    # nested dicts deterministically.
    fields = {
        "manifest_version": manifest.manifest_version,
        "plugin_id": manifest.plugin_id,
        "display_name": manifest.display_name,
        "version": manifest.version,
        "author": manifest.author,
        "developer_id": manifest.developer_id,
        "pricing": manifest.pricing,
        "entry_point": manifest.entry_point,
        "min_mca_version": manifest.min_mca_version,
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def verify_signature(manifest):
    """
    Verify the HMAC-SHA256 signature on a plugin manifest.

    Computes the expected signature over the canonical JSON representation
    of all fields (excluding ``mca_signature``) and compares it to the
    stored signature using constant-time comparison.

    :param PluginManifest manifest: The manifest to verify.
    :return: Tuple of (is_valid, reason).  ``reason`` is None on success,
        or a human-readable error string on failure.
    :rtype: tuple
    """
    if not manifest.mca_signature:
        return (False, "Manifest is missing the mca_signature field")

    # Build the canonical JSON and compute the expected HMAC (base64-encoded).
    canonical = _canonical_json(manifest)
    raw_digest = hmac.new(
        _MANIFEST_HMAC_KEY,
        canonical.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected = base64.b64encode(raw_digest).decode("ascii")

    # Constant-time comparison to prevent timing attacks.
    if hmac.compare_digest(expected, manifest.mca_signature):
        return (True, None)
    else:
        return (False, "Invalid manifest signature — the manifest may have been tampered with")


# =============================================================================
# Version Compatibility
# =============================================================================

def _parse_version(version_str):
    """
    Parse a semver string into a comparable tuple of integers.

    Handles 2-part (major.minor) and 3-part (major.minor.patch) strings.
    Returns ``(0, 0, 0)`` for empty or unparseable strings.

    :param str version_str: A version string like "1.0.2".
    :return: Tuple of (major, minor, patch).
    :rtype: tuple
    """
    if not version_str:
        return (0, 0, 0)
    try:
        parts = [int(p) for p in version_str.split(".")]
        # Pad to 3 elements if needed.
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_compatible(manifest, current_version):
    """
    Check whether the current MCA Editor version meets the plugin's
    minimum version requirement.

    :param PluginManifest manifest: The plugin manifest to check.
    :param str current_version: The current MCA Editor version string.
    :return: True if the editor version is >= the required minimum.
    :rtype: bool
    """
    # No minimum specified = compatible with everything.
    if not manifest.min_mca_version:
        return True

    required = _parse_version(manifest.min_mca_version)
    current = _parse_version(current_version)

    return current >= required
