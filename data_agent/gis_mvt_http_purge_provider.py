"""HTTP adapter for provider-neutral GIS MVT cache generation purge."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .gis_mvt_cache_purge import GISMVTCachePurgeProvider
from .gis_mvt_response_cache import MVTCachePurgeError, MVTCachePurgeResult
from .provider_credentials import validate_bearer_token_file

HTTP_MVT_CACHE_PURGE_SCHEMA = "gda.gis_mvt_cache_purge.v1"
_MAX_RESPONSE_BYTES = 64 * 1024


class HTTPGISMVTCachePurgeProviderConfigurationError(ValueError):
    """The HTTP purge provider configuration is unsafe or incomplete."""


class HTTPGISMVTCachePurgeProviderError(MVTCachePurgeError):
    """The HTTP purge provider failed or returned an invalid receipt."""


def _safe_endpoint(endpoint_url: str) -> str:
    value = endpoint_url.strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise HTTPGISMVTCachePurgeProviderConfigurationError(
            "HTTP purge endpoint must use http or https"
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPGISMVTCachePurgeProviderConfigurationError(
            "HTTP purge endpoint must not contain credentials, query, or fragment"
        )
    if not parts.hostname:
        raise HTTPGISMVTCachePurgeProviderConfigurationError(
            "HTTP purge endpoint must contain a host"
        )
    try:
        _port = parts.port
    except ValueError as exc:
        raise HTTPGISMVTCachePurgeProviderConfigurationError(
            "HTTP purge endpoint contains an invalid port"
        ) from exc
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def _read_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HTTPGISMVTCachePurgeProviderConfigurationError(
            "HTTP purge bearer token file could not be read"
        ) from exc
    if not token or any(character.isspace() for character in token):
        raise HTTPGISMVTCachePurgeProviderConfigurationError(
            "HTTP purge bearer token file must contain one non-empty token"
        )
    return token


@dataclass(frozen=True)
class HTTPGISMVTCachePurgeRequest:
    generation_token: str
    max_keys: int
    scan_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "generation_token": self.generation_token,
            "max_keys": self.max_keys,
            "scan_count": self.scan_count,
            "schema": HTTP_MVT_CACHE_PURGE_SCHEMA,
        }


class HTTPGISMVTCachePurgeProvider(GISMVTCachePurgeProvider):
    """Call a bounded external cache purge endpoint and validate its receipt."""

    provider_kind = "http_cache_purge"
    enabled = True

    def __init__(
        self,
        endpoint_url: str,
        *,
        bearer_token_file: Path | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint_url = _safe_endpoint(endpoint_url)
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise HTTPGISMVTCachePurgeProviderConfigurationError(
                "HTTP purge timeout must be between 0 and 60 seconds"
            )
        self.timeout_seconds = timeout_seconds
        self.bearer_token_file = (
            validate_bearer_token_file(
                bearer_token_file,
                error_factory=HTTPGISMVTCachePurgeProviderConfigurationError,
                label="HTTP purge bearer token file",
            )
            if bearer_token_file is not None
            else None
        )
        if client is not None and transport is not None:
            raise HTTPGISMVTCachePurgeProviderConfigurationError(
                "provide client or transport, not both"
            )
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "gis-data-agent-mvt-cache-purge/1",
            },
        )
        self._owns_client = client is None

    async def purge_generation(
        self,
        generation_token: str,
        *,
        max_keys: int,
        scan_count: int,
    ) -> MVTCachePurgeResult:
        request = HTTPGISMVTCachePurgeRequest(
            generation_token=generation_token,
            max_keys=max_keys,
            scan_count=scan_count,
        )
        headers = {}
        if self.bearer_token_file is not None:
            headers["Authorization"] = f"Bearer {_read_token(self.bearer_token_file)}"
        try:
            response = await self._client.post(
                self.endpoint_url,
                content=json.dumps(
                    request.as_dict(), ensure_ascii=True, separators=(",", ":")
                ),
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge request failed"
            ) from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge response exceeds the bounded contract"
            )
        if response.status_code >= 500:
            raise HTTPGISMVTCachePurgeProviderError(
                f"HTTP cache purge provider returned HTTP {response.status_code}"
            )
        if response.status_code in {401, 403}:
            raise HTTPGISMVTCachePurgeProviderError(
                f"HTTP cache purge provider authorization failed with HTTP {response.status_code}"
            )
        if not 200 <= response.status_code < 300:
            raise HTTPGISMVTCachePurgeProviderError(
                f"HTTP cache purge provider returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge provider returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge provider returned an invalid document"
            )
        if payload.get("schema") != HTTP_MVT_CACHE_PURGE_SCHEMA:
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge provider returned an unsupported schema"
            )
        if payload.get("status") != "succeeded":
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge provider did not return succeeded status"
            )
        if payload.get("generation_token") != generation_token:
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge receipt generation does not match the task"
            )
        try:
            matched_keys = int(payload["matched_keys"])
            deleted_keys = int(payload["deleted_keys"])
            remaining_keys = int(payload["remaining_keys"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge receipt counts are invalid"
            ) from exc
        if (
            matched_keys < 0
            or deleted_keys < 0
            or remaining_keys < 0
            or deleted_keys > matched_keys
            or remaining_keys != 0
        ):
            raise HTTPGISMVTCachePurgeProviderError(
                "HTTP cache purge receipt is not zero-residue"
            )
        return MVTCachePurgeResult(
            True, generation_token, matched_keys, deleted_keys, remaining_keys
        )

    async def aclose(self) -> None:
        if not self._owns_client:
            return
        close = self._client.aclose()
        if inspect.isawaitable(close):
            await close


__all__ = [
    "HTTPGISMVTCachePurgeProvider",
    "HTTPGISMVTCachePurgeProviderConfigurationError",
    "HTTPGISMVTCachePurgeProviderError",
    "HTTP_MVT_CACHE_PURGE_SCHEMA",
]
