"""Bounded health probes for configured Metadata Fabric providers.

The probe is deliberately separate from provider read/search: it validates
connectivity and the provider endpoint contract without reading catalog
objects, namespaces, URLs with credentials, or response documents.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Literal

import httpx

from .metadata_fabric import MetadataFabricSystem
from .metadata_provider_read import _read_token, _safe_url, _token_path
from .openmetadata_lineage_worker import (
    OpenMetadataLineageConfigurationError,
    normalize_openmetadata_api_url,
)
from .provider_credentials import resolve_bearer_token_file

PROVIDER_HEALTH_SCHEMA = "gda.metadata_provider_health.v1"
_MAX_RESPONSE_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_SECONDS = 2.5

ProviderHealthStatus = Literal[
    "ok",
    "unconfigured",
    "configuration_error",
    "unauthorized",
    "unavailable",
    "protocol_error",
]


def _result(
    provider: MetadataFabricSystem,
    status: ProviderHealthStatus,
    *,
    endpoint: str | None = None,
    status_code: int | None = None,
    latency_ms: float = 0.0,
    retryable: bool = False,
    code: str | None = None,
) -> dict[str, Any]:
    """Return only bounded, non-sensitive probe facts."""
    return {
        "schema_version": PROVIDER_HEALTH_SCHEMA,
        "provider": provider.value,
        "status": status,
        "endpoint": endpoint,
        "status_code": status_code,
        "latency_ms": round(max(latency_ms, 0.0), 1),
        "retryable": retryable,
        "code": code,
    }


def _timeout_seconds() -> float:
    raw = os.environ.get("GDA_METADATA_PROVIDER_HEALTH_TIMEOUT_SECONDS", "")
    if not raw.strip():
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return 0.0
    return value if 0 < value <= 30 else 0.0


def _probe(
    provider: MetadataFabricSystem,
    *,
    base_url: str,
    endpoint: str,
    token_file: Path | None,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return _result(
            provider,
            "configuration_error",
            endpoint=endpoint,
            code="invalid_timeout",
        )
    headers: dict[str, str] = {}
    try:
        if token_file is not None:
            headers["Authorization"] = f"Bearer {_read_token(token_file, provider=provider)}"
    except Exception:
        return _result(
            provider,
            "configuration_error",
            endpoint=endpoint,
            code="invalid_bearer_token_file",
        )

    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "*/*"
                if provider is MetadataFabricSystem.GRAVITINO
                else "application/json",
                "User-Agent": "gis-data-agent-metadata-provider-health/1",
            },
        ) as client:
            response = client.get(f"{base_url}{endpoint}", headers=headers or None)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return _result(
            provider,
            "unavailable",
            endpoint=endpoint,
            latency_ms=(time.monotonic() - started) * 1000,
            retryable=True,
            code=type(exc).__name__.lower(),
        )
    latency_ms = (time.monotonic() - started) * 1000
    if len(response.content) > _MAX_RESPONSE_BYTES:
        return _result(
            provider,
            "protocol_error",
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            code="response_too_large",
        )
    if response.status_code in {401, 403}:
        return _result(
            provider,
            "unauthorized",
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            code="provider_unauthorized",
        )
    if response.status_code >= 500:
        return _result(
            provider,
            "unavailable",
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            retryable=True,
            code="provider_http_5xx",
        )
    if not 200 <= response.status_code < 300:
        return _result(
            provider,
            "protocol_error",
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            code="provider_http_error",
        )
    if provider is MetadataFabricSystem.GRAVITINO:
        try:
            payload = response.json()
        except ValueError:
            return _result(
                provider,
                "protocol_error",
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
                code="invalid_health_document",
            )
        if not isinstance(payload, dict) or str(payload.get("status", "")).lower() not in {
            "up",
            "ok",
            "healthy",
        }:
            return _result(
                provider,
                "protocol_error",
                endpoint=endpoint,
                status_code=response.status_code,
                latency_ms=latency_ms,
                code="health_status_not_up",
            )
    return _result(
        provider,
        "ok",
        endpoint=endpoint,
        status_code=response.status_code,
        latency_ms=latency_ms,
        code="probe_succeeded",
    )


def check_metadata_provider(
    provider: MetadataFabricSystem,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Probe one configured provider, returning a stable failure class."""
    provider = MetadataFabricSystem(provider)
    timeout_seconds = _timeout_seconds()
    if provider is MetadataFabricSystem.GRAVITINO:
        raw_url = os.environ.get("GDA_GRAVITINO_URL", "").strip()
        token_raw = os.environ.get("GDA_GRAVITINO_BEARER_TOKEN_FILE", "").strip()
        if not raw_url:
            return _result(provider, "unconfigured", endpoint="/health", code="url_not_configured")
        try:
            base_url = _safe_url(raw_url, provider=provider)
            token_file = _token_path(Path(token_raw), provider=provider) if token_raw else None
        except Exception:
            return _result(
                provider,
                "configuration_error",
                endpoint="/health",
                code="invalid_configuration",
            )
        return _probe(
            provider,
            base_url=base_url,
            endpoint="/health",
            token_file=token_file,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    raw_url = os.environ.get("GDA_OPENMETADATA_URL", "").strip()
    try:
        token_file = resolve_bearer_token_file(
            file_env_name="GDA_OPENMETADATA_BEARER_TOKEN_FILE",
            source_env_name="GDA_OPENMETADATA_BEARER_TOKEN_SOURCE",
            error_factory=lambda _message: ValueError("invalid credential source"),
        )
        if not raw_url and token_file is None:
            return _result(
                provider,
                "unconfigured",
                endpoint="/system/version",
                code="not_configured",
            )
        if not raw_url or token_file is None:
            return _result(
                provider,
                "configuration_error",
                endpoint="/system/version",
                code="url_and_token_required",
            )
        base_url = normalize_openmetadata_api_url(raw_url)
        _token_path(token_file, provider=provider)
    except (OpenMetadataLineageConfigurationError, ValueError, OSError):
        return _result(
            provider,
            "configuration_error",
            endpoint="/system/version",
            code="invalid_configuration",
        )
    return _probe(
        provider,
        base_url=base_url,
        endpoint="/system/version",
        token_file=token_file,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


def check_configured_metadata_providers(
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, dict[str, Any]]:
    """Probe providers that are configured; absent providers remain explicit."""
    return {
        provider.value: check_metadata_provider(provider, transport=transport)
        for provider in (MetadataFabricSystem.OPENMETADATA, MetadataFabricSystem.GRAVITINO)
    }
