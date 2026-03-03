"""
Lightweight i18n module for GIS Data Agent (v4.1.4).

Uses YAML dictionaries + a ``t()`` translation function with ContextVar
for per-request language selection.

Usage::

    from data_agent.i18n import t, set_language

    set_language("en")
    t("preview.file_format", fmt="CSV")  # → "File format: CSV"
"""

import os
import yaml
from contextvars import ContextVar

_current_lang: ContextVar[str] = ContextVar("i18n_lang", default="zh")
_translations: dict[str, dict[str, str]] = {}


def _load_translations():
    """Load all YAML locale files from the ``locales/`` directory."""
    locales_dir = os.path.join(os.path.dirname(__file__), "locales")
    if not os.path.isdir(locales_dir):
        return
    for fname in os.listdir(locales_dir):
        if fname.endswith(".yaml"):
            lang = fname[:-5]
            with open(os.path.join(locales_dir, fname), "r", encoding="utf-8") as f:
                _translations[lang] = yaml.safe_load(f) or {}


def set_language(lang: str):
    """Set the current language for the calling async context."""
    _current_lang.set(lang)


def get_language() -> str:
    """Return the current language code."""
    return _current_lang.get()


def t(key: str, **kwargs) -> str:
    """Look up a translation key and optionally interpolate ``{kwargs}``.

    Fallback chain: current language → zh → key itself.
    """
    lang = _current_lang.get()
    strings = _translations.get(lang) or _translations.get("zh", {})
    val = strings.get(key, _translations.get("zh", {}).get(key, key))
    return val.format(**kwargs) if kwargs else val


# Auto-load on import
_load_translations()
