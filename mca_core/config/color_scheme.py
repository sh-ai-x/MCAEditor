"""
MCA Core - Color Scheme Configuration.

Defines the canonical list of syntax tokens per language and provides
helpers for reading/writing token styles from MCASettings.  Each token
has a display name, default foreground color, and bold/italic flags.

Settings key format:
    color.<lang>.<token>.<prop>
    e.g. ``color.python.keyword.fg`` = ``"#569cd6"``

Dependencies:
    - mca_core.config.settings (MCASettings) for persistence

Side Effects:
    - Reads and writes ``color.*`` keys in the application settings store.
"""

import logging
from collections import OrderedDict

# Module-level logger.
logger = logging.getLogger(__name__)


# =============================================================================
# Token Default Definitions
# =============================================================================

# Canonical default styles for every syntax token, keyed by (language, token).
# Each value is a dict: display (human label), fg (hex color), bold, italic.
TOKEN_DEFAULTS = OrderedDict([
    # --- Python tokens (11) ---
    (("python", "keyword"),          {"display": "Keywords",          "fg": "#569cd6", "bold": True,  "italic": False}),
    (("python", "builtin"),          {"display": "Built-ins",         "fg": "#4ec9b0", "bold": False, "italic": False}),
    (("python", "decorator"),        {"display": "Decorators",        "fg": "#d7ba7d", "bold": False, "italic": False}),
    (("python", "number"),           {"display": "Numbers",           "fg": "#b5cea8", "bold": False, "italic": False}),
    (("python", "funcdef"),          {"display": "Function Defs",     "fg": "#dcdcaa", "bold": False, "italic": False}),
    (("python", "classdef"),         {"display": "Class Defs",        "fg": "#4ec9b0", "bold": True,  "italic": False}),
    (("python", "funccall"),         {"display": "Function Calls",    "fg": "#dcdcaa", "bold": False, "italic": False}),
    (("python", "operator"),         {"display": "Operators",         "fg": "#d4d4d4", "bold": False, "italic": False}),
    (("python", "string"),           {"display": "Strings",           "fg": "#ce9178", "bold": False, "italic": False}),
    (("python", "comment"),          {"display": "Comments",          "fg": "#6a9955", "bold": False, "italic": True}),
    (("python", "multiline_string"), {"display": "Multi-line Strings","fg": "#ce9178", "bold": False, "italic": False}),

    # --- MEL tokens (6) ---
    (("mel", "keyword"),  {"display": "Keywords",       "fg": "#569cd6", "bold": True,  "italic": False}),
    (("mel", "variable"), {"display": "Variables ($)",   "fg": "#9cdcfe", "bold": False, "italic": False}),
    (("mel", "number"),   {"display": "Numbers",        "fg": "#b5cea8", "bold": False, "italic": False}),
    (("mel", "string"),   {"display": "Strings",        "fg": "#ce9178", "bold": False, "italic": False}),
    (("mel", "procdef"),  {"display": "Proc Defs",      "fg": "#dcdcaa", "bold": False, "italic": False}),
    (("mel", "comment"),  {"display": "Comments",       "fg": "#6a9955", "bold": False, "italic": True}),
])


# =============================================================================
# Helper Functions
# =============================================================================

def get_token_style(settings, lang, token_key):
    """
    Retrieve the style for a single token, falling back to defaults.

    Reads ``color.<lang>.<token>.fg``, ``.bold``, and ``.italic``
    from the settings store.  Any missing key falls back to the
    value defined in ``TOKEN_DEFAULTS``.

    :param MCASettings settings: Application settings instance.
    :param str lang: Language identifier (e.g. ``"python"``, ``"mel"``).
    :param str token_key: Token identifier (e.g. ``"keyword"``).
    :return: Dict with keys ``fg`` (str), ``bold`` (bool), ``italic`` (bool).
    :rtype: dict
    """
    defaults = TOKEN_DEFAULTS.get((lang, token_key), {})
    prefix = "color.{}.{}.".format(lang, token_key)

    fg = settings.get(prefix + "fg")
    bold = settings.get(prefix + "bold")
    italic = settings.get(prefix + "italic")

    # QSettings may return "true"/"false" strings for booleans since these
    # keys aren't in _DEFAULTS and don't get automatic type coercion.
    def _to_bool(val, fallback):
        if val is None:
            return fallback
        if isinstance(val, str):
            return val.lower() == "true"
        return bool(val)

    return {
        "fg":     fg if fg is not None else defaults.get("fg", "#d4d4d4"),
        "bold":   _to_bool(bold, defaults.get("bold", False)),
        "italic": _to_bool(italic, defaults.get("italic", False)),
    }


def set_token_style(settings, lang, token_key, fg, bold, italic):
    """
    Write the style for a single token into settings.

    :param MCASettings settings: Application settings instance.
    :param str lang: Language identifier.
    :param str token_key: Token identifier.
    :param str fg: Foreground hex color string.
    :param bool bold: Whether the text should be bold.
    :param bool italic: Whether the text should be italic.
    """
    prefix = "color.{}.{}.".format(lang, token_key)
    settings.set(prefix + "fg", fg)
    settings.set(prefix + "bold", bold)
    settings.set(prefix + "italic", italic)


def build_scheme_dict(settings):
    """
    Build a full color scheme dictionary from current settings.

    Returns a dict keyed by ``(lang, token_key)`` with values
    ``{fg, bold, italic}`` — ready to pass to highlighter constructors.

    :param MCASettings settings: Application settings instance.
    :return: Complete scheme dictionary.
    :rtype: dict
    """
    scheme = {}
    for (lang, token_key) in TOKEN_DEFAULTS:
        scheme[(lang, token_key)] = get_token_style(settings, lang, token_key)
    return scheme


def restore_defaults(settings):
    """
    Reset all color scheme settings keys back to their defaults.

    Removes all ``color.*`` keys so the next read falls through to
    ``TOKEN_DEFAULTS``.

    :param MCASettings settings: Application settings instance.
    """
    for (lang, token_key), defaults in TOKEN_DEFAULTS.items():
        prefix = "color.{}.{}.".format(lang, token_key)
        # Write the default values explicitly so the settings reflect them.
        settings.set(prefix + "fg", defaults["fg"])
        settings.set(prefix + "bold", defaults["bold"])
        settings.set(prefix + "italic", defaults["italic"])

    settings.sync()
    logger.info("Color scheme restored to defaults")


def get_tokens_for_language(lang):
    """
    Return an ordered list of token entries for a given language.

    :param str lang: Language identifier (e.g. ``"python"``, ``"mel"``).
    :return: List of ``(token_key, display_name)`` tuples in definition order.
    :rtype: list
    """
    result = []
    for (token_lang, token_key), info in TOKEN_DEFAULTS.items():
        if token_lang == lang:
            result.append((token_key, info["display"]))
    return result
