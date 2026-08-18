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
from collections.abc import Mapping
from contextvars import ContextVar
from http.cookies import CookieError, SimpleCookie
from typing import Any, ClassVar
from urllib.parse import parse_qs

import yaml

SUPPORTED_LANGUAGES = ("zh", "en", "ar")
DEFAULT_LANGUAGE = "zh"

_current_lang: ContextVar[str] = ContextVar("i18n_lang", default=DEFAULT_LANGUAGE)
_translations: dict[str, dict[str, str]] = {}


def normalize_language(lang: str | None, default: str = DEFAULT_LANGUAGE) -> str:
    """Return a supported base language for a BCP 47 locale or alias."""
    fallback = str(default or DEFAULT_LANGUAGE).strip().lower().replace("_", "-")
    fallback = fallback.split("-", 1)[0]
    if fallback not in SUPPORTED_LANGUAGES:
        fallback = DEFAULT_LANGUAGE
    if not lang:
        return fallback
    primary = str(lang).strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in SUPPORTED_LANGUAGES else fallback


def resolve_language(
    user_env: Mapping[str, Any] | None = None,
    message_metadata: Mapping[str, Any] | None = None,
    default: str | None = None,
) -> str:
    """Resolve locale by message override, connection environment, then default."""
    message_metadata = message_metadata or {}
    user_env = user_env or {}
    candidate = (
        message_metadata.get("locale")
        or message_metadata.get("language")
        or user_env.get("locale")
        or user_env.get("language")
        or default
        or DEFAULT_LANGUAGE
    )
    return normalize_language(str(candidate), DEFAULT_LANGUAGE)


def resolve_http_language(
    query_locale: str | None = None,
    x_locale: str | None = None,
    accept_language: str | None = None,
    default: str | None = None,
    cookie_locale: str | None = None,
) -> str:
    """Resolve query/header locale preferences, including Accept-Language weights."""

    def supported(value: str | None) -> str | None:
        if not value:
            return None
        primary = str(value).strip().lower().replace("_", "-").split("-", 1)[0]
        return primary if primary in SUPPORTED_LANGUAGES else None

    for explicit in (query_locale, x_locale, cookie_locale):
        resolved = supported(explicit)
        if resolved:
            return resolved

    accepted: list[tuple[float, int, str]] = []
    for index, item in enumerate(str(accept_language or "").split(",")):
        language_range, *parameters = item.strip().split(";")
        resolved = supported(language_range)
        if not resolved:
            continue
        quality = 1.0
        for parameter in parameters:
            name, separator, value = parameter.strip().partition("=")
            if separator and name.lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0:
            accepted.append((quality, -index, resolved))

    if accepted:
        return max(accepted)[2]
    return normalize_language(default, DEFAULT_LANGUAGE)


class HttpLocaleMiddleware:
    """Bind every HTTP request to its query, header, cookie, or browser locale."""

    _CONTENT_LANGUAGES: ClassVar[dict[str, str]] = {
        "zh": "zh-CN",
        "en": "en-US",
        "ar": "ar-AE",
    }

    def __init__(self, app: Any, default: str | None = None):
        self.app = app
        self.default = default

    async def __call__(self, scope: dict, receive: Any, send: Any):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        query = parse_qs(scope.get("query_string", b"").decode("utf-8", "replace"))
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("cookie", ""))
        except CookieError:
            cookies = SimpleCookie()
        language = resolve_http_language(
            query_locale=(query.get("locale") or [None])[0],
            x_locale=headers.get("x-locale"),
            accept_language=headers.get("accept-language"),
            default=self.default,
            cookie_locale=(cookies.get("gda.locale").value if cookies.get("gda.locale") else None),
        )
        token = _current_lang.set(language)

        async def send_localized(message: dict):
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                if not any(key.lower() == b"content-language" for key, _ in response_headers):
                    response_headers.append((
                        b"content-language",
                        self._CONTENT_LANGUAGES[language].encode("ascii"),
                    ))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_localized)
        finally:
            _current_lang.reset(token)


def _load_translations():
    """Load all YAML locale files from the ``locales/`` directory."""
    _translations.clear()
    locales_dir = os.path.join(os.path.dirname(__file__), "locales")
    if not os.path.isdir(locales_dir):
        return
    for fname in sorted(os.listdir(locales_dir)):
        if fname.endswith(".yaml"):
            lang = fname[:-5]
            with open(os.path.join(locales_dir, fname), "r", encoding="utf-8") as f:
                _translations[lang] = yaml.safe_load(f) or {}


def set_language(lang: str | None) -> str:
    """Set the current language for the calling async context."""
    normalized = normalize_language(lang)
    _current_lang.set(normalized)
    return normalized


def get_language() -> str:
    """Return the current language code."""
    return _current_lang.get()


def t(key: str, **kwargs) -> str:
    """Look up a translation key and optionally interpolate ``{kwargs}``.

    Fallback chain: current language → zh → key itself.
    """
    lang = normalize_language(_current_lang.get())
    strings = _translations.get(lang) or _translations.get("zh", {})
    val = strings.get(key, _translations.get("zh", {}).get(key, key))
    return val.format(**kwargs) if kwargs else val


# Auto-load on import
_load_translations()
