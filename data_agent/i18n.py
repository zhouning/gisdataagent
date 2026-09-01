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
    return _current_lang.set(lang)


def reset_language(token) -> None:
    """Restore the language context returned by :func:`set_language`."""
    _current_lang.reset(token)


def get_language() -> str:
    """Return the current language code."""
    return _current_lang.get()


def _language_from_headers(headers) -> str | None:
    """Resolve the UI language from browser request headers."""
    raw = headers.get(b'x-locale') or headers.get(b'accept-language')
    if not raw:
        return None
    value = raw.decode('latin-1').split(',', 1)[0].strip().lower().replace('_', '-')
    if value.startswith('en'):
        return 'en'
    if value.startswith('ar'):
        return 'ar'
    if value.startswith('zh'):
        return 'zh'
    return None


class LocaleMiddleware:
    """Bind the browser locale to every HTTP/WebSocket request.

    Frontend controls send ``X-Locale`` and ``Accept-Language``.  Binding the
    context at the ASGI boundary keeps API error messages and generated
    navigation labels in sync even when a route does not explicitly parse the
    headers itself.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') not in {'http', 'websocket'}:
            return await self.app(scope, receive, send)
        locale = _language_from_headers(dict(scope.get('headers') or []))
        if locale is None:
            return await self.app(scope, receive, send)
        token = set_language(locale)
        try:
            return await self.app(scope, receive, send)
        finally:
            reset_language(token)


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
