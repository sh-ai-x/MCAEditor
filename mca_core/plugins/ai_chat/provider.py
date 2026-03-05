"""
MCA Core - AI Chat Provider Abstraction.

Factory for creating OpenAI-compatible clients that talk to Anthropic,
OpenAI, or Google Gemini through their OpenAI-compatible endpoints.
All three providers use the same ``openai`` SDK — just different
``base_url`` and header configurations.

Dependencies:
    - openai >= 1.30.0 (lazy-imported so the plugin can be discovered
      even if the managed venv isn't ready yet)
"""

import logging

# Module-level logger.
logger = logging.getLogger(__name__)


# --- Provider Configurations -------------------------------------------------

# Each provider maps to a base_url, default model, and any extra headers.
# The Anthropic endpoint requires an extra ``anthropic-version`` header.
PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1/",
        "default_model": "claude-sonnet-4-6",
        # No extra headers needed — the OAI-compat endpoint handles
        # auth via the standard Authorization header.  The anthropic-version
        # header is only for the native /v1/messages endpoint.
        "extra_headers": {},
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1/",
        "default_model": "gpt-4o",
        "extra_headers": {},
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "extra_headers": {},
    },
}

# Ordered list of provider IDs for UI dropdowns.
PROVIDER_IDS = ["anthropic", "openai", "gemini"]


# --- Client Factory ----------------------------------------------------------

def create_client(provider_id, api_key, model=None):
    """
    Create a configured OpenAI client for the specified provider.

    Lazy-imports the ``openai`` package so this module can be imported
    even when the managed venv hasn't been set up yet.

    :param str provider_id: One of ``"anthropic"``, ``"openai"``, ``"gemini"``.
    :param str api_key: The API key for authentication.
    :param str model: Override the default model. If *None*, uses the
        provider's default model from ``PROVIDERS``.
    :return: Tuple of (client, model_name).
    :rtype: tuple(openai.OpenAI, str)
    :raises ImportError: If the ``openai`` package is not installed.
    :raises ValueError: If the provider_id is unknown.
    """
    # Lazy import — openai lives in the managed venv.
    try:
        import openai
    except ImportError:
        raise ImportError(
            "The 'openai' package is not installed. "
            "It should be auto-installed in the managed venv on next launch."
        )

    # Look up provider config.
    config = PROVIDERS.get(provider_id)
    if config is None:
        raise ValueError(
            "Unknown provider: '{}'. Must be one of: {}".format(
                provider_id, ", ".join(PROVIDER_IDS)
            )
        )

    # Resolve model name — use override or provider default.
    resolved_model = model if model else config["default_model"]

    # Build the client with the provider's base_url and any extra headers.
    client = openai.OpenAI(
        api_key=api_key,
        base_url=config["base_url"],
        default_headers=config.get("extra_headers", {}),
    )

    logger.info("Created %s client (model=%s)", config["name"], resolved_model)
    return client, resolved_model


def get_provider_name(provider_id):
    """
    Get the human-readable name for a provider.

    :param str provider_id: The provider identifier.
    :return: Display name, or the raw ID if unknown.
    :rtype: str
    """
    config = PROVIDERS.get(provider_id)
    if config:
        return config["name"]
    return provider_id


def get_default_model(provider_id):
    """
    Get the default model for a provider.

    :param str provider_id: The provider identifier.
    :return: Default model name, or empty string if unknown.
    :rtype: str
    """
    config = PROVIDERS.get(provider_id)
    if config:
        return config["default_model"]
    return ""
