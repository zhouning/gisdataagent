"""Read-only provider bridge for Metadata Fabric crosswalks.

GDA owns the crosswalk and the evidence contract. OpenMetadata and Gravitino
remain authoritative for provider state; this module deliberately returns a
bounded projection instead of copying provider catalog documents into GDA.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .metadata_fabric import MetadataFabricBinding, MetadataFabricSystem
from .metadata_provider_metrics import record_metadata_provider_operation
from .openmetadata_lineage_worker import (
    OpenMetadataLineageConfigurationError,
    normalize_openmetadata_api_url,
)
from .platform_contracts import (
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)
from .provider_credentials import (
    resolve_bearer_token_file,
    validate_bearer_token_file,
)

PROVIDER_READ_SCHEMA = "gda.metadata_provider_read.v1"
_MAX_EVIDENCE_BYTES = 16 * 1024


class ProviderReadStatus(StrEnum):
    PRESENT = "present"
    NOT_FOUND = "not_found"


class MetadataProviderReadError(RuntimeError):
    """A provider read failed without changing provider state."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        provider: MetadataFabricSystem,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class MetadataProviderReadConfigurationError(MetadataProviderReadError):
    """Provider read configuration is absent or unsafe."""

    def __init__(self, message: str, *, provider: MetadataFabricSystem) -> None:
        super().__init__(
            message,
            code="provider_read_configuration_error",
            provider=provider,
            retryable=False,
        )


class ProviderReadResult(BaseModel):
    """Small, auditable provider observation returned by a read adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[PROVIDER_READ_SCHEMA] = PROVIDER_READ_SCHEMA
    tenant_id: TenantId
    resource_urn: ResourceURNText
    binding_id: UUID
    system: MetadataFabricSystem
    external_namespace: str = Field(min_length=1, max_length=512)
    external_object_id: str = Field(min_length=1, max_length=512)
    external_object_type: str = Field(min_length=1, max_length=128)
    status: ProviderReadStatus
    provider_revision: str | None = Field(default=None, max_length=512)
    provider_fingerprint: Sha256 | None = None
    observed_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in {ProviderReadStatus.PRESENT, ProviderReadStatus.NOT_FOUND}:
            raise ValueError("provider read status is invalid")
        return value

    @field_validator("evidence")
    @classmethod
    def _bounded_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("provider read evidence must be JSON serializable") from exc
        if len(encoded.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
            raise ValueError("provider read evidence exceeds the bounded contract")
        return value


class MetadataProviderReadClient(Protocol):
    system: MetadataFabricSystem

    def read(self, binding: MetadataFabricBinding) -> ProviderReadResult:
        ...

    def close(self) -> None:
        ...


def _safe_url(value: str, *, provider: MetadataFabricSystem) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise MetadataProviderReadConfigurationError(
            "provider URL must be an absolute http(s) endpoint", provider=provider
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise MetadataProviderReadConfigurationError(
            "provider URL must not contain credentials, query, or fragment",
            provider=provider,
        )
    try:
        hostname = parts.hostname
        _port = parts.port
    except ValueError as exc:
        raise MetadataProviderReadConfigurationError(
            "provider URL contains an invalid host or port", provider=provider
        ) from exc
    if not hostname:
        raise MetadataProviderReadConfigurationError(
            "provider URL must contain a host", provider=provider
        )
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _token_path(value: Path, *, provider: MetadataFabricSystem) -> Path:
    return validate_bearer_token_file(
        value,
        error_factory=lambda message: MetadataProviderReadConfigurationError(
            message, provider=provider
        ),
        label="provider bearer token file",
    )


def _read_token(path: Path, *, provider: MetadataFabricSystem) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MetadataProviderReadConfigurationError(
            "provider bearer token file could not be read", provider=provider
        ) from exc
    if not token or any(character.isspace() for character in token):
        raise MetadataProviderReadConfigurationError(
            "provider bearer token file must contain one non-empty token",
            provider=provider,
        )
    return token


def _selected_evidence(obj: dict[str, Any], *, system: MetadataFabricSystem) -> dict[str, Any]:
    """Keep only stable, useful fields; never return the provider document."""
    keys = (
        "name",
        "fullyQualifiedName",
        "displayName",
        "version",
        "updatedAt",
        "deleted",
        "comment",
        "description",
        "columns",
        "schema",
        "location",
        "properties",
    )
    evidence: dict[str, Any] = {key: obj[key] for key in keys if key in obj}
    if system is MetadataFabricSystem.GRAVITINO:
        properties = evidence.get("properties")
        if isinstance(properties, dict):
            evidence["properties"] = {
                key: properties[key]
                for key in (
                    "provider",
                    "format",
                    "format-version",
                    "location",
                    "current-snapshot-id",
                )
                if key in properties
            }
    encoded = json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
        raise MetadataProviderReadError(
            "provider selected evidence exceeds the bounded contract",
            code="provider_evidence_too_large",
            provider=system,
            retryable=False,
        )
    return evidence


def _provider_fingerprint_payload(
    obj: dict[str, Any], *, system: MetadataFabricSystem
) -> dict[str, Any]:
    """Drop provider-managed volatile fields before binding a revision."""
    if system is not MetadataFabricSystem.GRAVITINO:
        return obj
    stable = dict(obj)
    # Gravitino reconstructs audit metadata after restart; it is not a
    # technical object version and must not invalidate a stable crosswalk.
    stable.pop("audit", None)
    return stable


def _response_document(
    response: httpx.Response,
    *,
    provider: MetadataFabricSystem,
    path: str,
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise MetadataProviderReadError(
            f"{provider.value} read returned invalid JSON",
            code="provider_invalid_json",
            provider=provider,
            status_code=response.status_code,
            retryable=False,
        ) from exc
    if not isinstance(payload, dict):
        raise MetadataProviderReadError(
            f"{provider.value} read returned an invalid document",
            code="provider_invalid_document",
            provider=provider,
            status_code=response.status_code,
            retryable=False,
        )
    if not 200 <= response.status_code < 300:
        retryable = response.status_code == 429 or response.status_code >= 500
        code = (
            "provider_unauthorized"
            if response.status_code in {401, 403}
            else "provider_http_error"
        )
        raise MetadataProviderReadError(
            f"{provider.value} read returned HTTP {response.status_code} for {path}",
            code=code,
            provider=provider,
            status_code=response.status_code,
            retryable=retryable,
        )
    return payload


class _HttpProviderReadClient:
    system: MetadataFabricSystem

    def __init__(
        self,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None,
        user_agent: str,
        accept: str = "application/json",
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise MetadataProviderReadConfigurationError(
                "provider timeout must be between 0 and 120 seconds",
                provider=self.system,
            )
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={"Accept": accept, "User-Agent": user_agent},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> _HttpProviderReadClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request(
        self,
        binding: MetadataFabricBinding,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        payload_key: str | None,
    ) -> ProviderReadResult:
        try:
            response = self._client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MetadataProviderReadError(
                f"{self.system.value} read request failed: {type(exc).__name__}",
                code="provider_transport_error",
                provider=self.system,
                retryable=True,
            ) from exc
        observed_at = datetime.now(UTC)
        if response.status_code == 404:
            return ProviderReadResult(
                tenant_id=binding.tenant_id,
                resource_urn=binding.resource_urn,
                binding_id=binding.binding_id,
                system=binding.system,
                external_namespace=binding.external_namespace,
                external_object_id=binding.external_object_id,
                external_object_type=binding.external_object_type,
                status=ProviderReadStatus.NOT_FOUND,
                observed_at=observed_at,
            )
        payload = _response_document(response, provider=self.system, path=url)
        obj = payload if payload_key is None else payload.get(payload_key)
        if not isinstance(obj, dict):
            raise MetadataProviderReadError(
                f"{self.system.value} read document is missing {payload_key or 'the entity'}",
                code="provider_invalid_document",
                provider=self.system,
                status_code=response.status_code,
                retryable=False,
            )
        if str(obj.get("id") or obj.get("name") or "") not in {
            binding.external_object_id,
            binding.external_object_id.rsplit("/", 1)[-1],
        }:
            raise MetadataProviderReadError(
                f"{self.system.value} read returned the wrong object",
                code="provider_identity_mismatch",
                provider=self.system,
                status_code=response.status_code,
                retryable=False,
            )
        evidence = _selected_evidence(obj, system=self.system)
        fingerprint = canonical_json_fingerprint(
            _provider_fingerprint_payload(obj, system=self.system)
        )
        return ProviderReadResult(
            tenant_id=binding.tenant_id,
            resource_urn=binding.resource_urn,
            binding_id=binding.binding_id,
            system=binding.system,
            external_namespace=binding.external_namespace,
            external_object_id=binding.external_object_id,
            external_object_type=binding.external_object_type,
            status=ProviderReadStatus.PRESENT,
            provider_revision=(
                str(obj.get("version") or obj.get("updatedAt") or binding.external_version_ref)
                if (obj.get("version") or obj.get("updatedAt") or binding.external_version_ref)
                else None
            ),
            provider_fingerprint=fingerprint,
            observed_at=observed_at,
            evidence=evidence,
        )


class GravitinoMetadataProviderReadClient(_HttpProviderReadClient):
    """Read one object through Gravitino's technical metadata API."""

    system = MetadataFabricSystem.GRAVITINO
    _PATH_SEGMENTS = {"table": "tables", "view": "views", "fileset": "filesets", "topic": "topics"}
    _PAYLOAD_KEYS = {"table": "table", "view": "view", "fileset": "fileset", "topic": "topic"}

    def __init__(
        self,
        api_url: str,
        *,
        timeout_seconds: float = 10.0,
        bearer_token_file: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_url = _safe_url(api_url, provider=self.system)
        self._bearer_token_file = (
            _token_path(bearer_token_file, provider=self.system)
            if bearer_token_file is not None
            else None
        )
        super().__init__(
            timeout_seconds=timeout_seconds,
            transport=transport,
            user_agent="gis-data-agent-metadata-provider-read/1",
            accept="*/*",
        )

    def read(self, binding: MetadataFabricBinding) -> ProviderReadResult:
        if binding.system is not self.system:
            raise MetadataProviderReadError(
                "Gravitino adapter received a non-Gravitino binding",
                code="provider_binding_system_mismatch",
                provider=self.system,
            )
        parts = binding.external_namespace.split("/")
        if len(parts) != 3 or any(not part for part in parts):
            raise MetadataProviderReadError(
                "Gravitino binding namespace must be metalake/catalog/namespace",
                code="provider_binding_invalid",
                provider=self.system,
            )
        segment = self._PATH_SEGMENTS.get(binding.external_object_type)
        payload_key = self._PAYLOAD_KEYS.get(binding.external_object_type)
        if segment is None or payload_key is None:
            raise MetadataProviderReadError(
                "Gravitino binding object type is unsupported by the read adapter",
                code="provider_binding_unsupported_type",
                provider=self.system,
            )
        metalake, catalog, namespace = (quote(part, safe="") for part in parts)
        object_name = quote(binding.external_object_id, safe="")
        url = (
            f"{self.api_url}/api/metalakes/{metalake}/catalogs/{catalog}"
            f"/schemas/{namespace}/{segment}/{object_name}"
        )
        headers = {}
        if self._bearer_token_file is not None:
            token = _read_token(self._bearer_token_file, provider=self.system)
            headers["Authorization"] = f"Bearer {token}"
        result = self._request(
            binding, url=url, headers=headers or None, payload_key=payload_key
        )
        expected_ref = binding.external_version_ref or ""
        if (
            result.status is ProviderReadStatus.PRESENT
            and expected_ref.startswith("metadata-sha256:")
            and result.provider_fingerprint != expected_ref.removeprefix("metadata-sha256:")
        ):
            raise MetadataProviderReadError(
                "Gravitino provider fingerprint differs from the bound version",
                code="provider_version_mismatch",
                provider=self.system,
                retryable=False,
            )
        return result


class OpenMetadataProviderReadClient(_HttpProviderReadClient):
    """Read one bound OpenMetadata entity without copying its catalog record."""

    system = MetadataFabricSystem.OPENMETADATA
    _PATH_SEGMENTS = {
        "table": "tables",
        "glossaryTerm": "glossaryTerms",
        "database": "databases",
        "databaseSchema": "databaseSchemas",
        "dashboard": "dashboards",
        "pipeline": "pipelines",
        "topic": "topics",
        "apiEndpoint": "apiEndpoints",
        "searchIndex": "searchIndexes",
        "mlmodel": "mlmodels",
        "container": "containers",
        "dataProduct": "dataProducts",
        "metric": "metrics",
        "storedProcedure": "storedProcedures",
    }

    def __init__(
        self,
        api_url: str,
        *,
        bearer_token_file: Path,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            normalized = normalize_openmetadata_api_url(api_url)
        except OpenMetadataLineageConfigurationError as exc:
            raise MetadataProviderReadConfigurationError(
                str(exc), provider=self.system
            ) from exc
        self.api_url = normalized
        self._bearer_token_file = _token_path(bearer_token_file, provider=self.system)
        super().__init__(
            timeout_seconds=timeout_seconds,
            transport=transport,
            user_agent="gis-data-agent-metadata-provider-read/1",
        )

    def read(self, binding: MetadataFabricBinding) -> ProviderReadResult:
        if binding.system is not self.system:
            raise MetadataProviderReadError(
                "OpenMetadata adapter received a non-OpenMetadata binding",
                code="provider_binding_system_mismatch",
                provider=self.system,
            )
        segment = self._PATH_SEGMENTS.get(binding.external_object_type)
        if segment is None:
            raise MetadataProviderReadError(
                "OpenMetadata binding object type is unsupported by the read adapter",
                code="provider_binding_unsupported_type",
                provider=self.system,
            )
        object_id = quote(binding.external_object_id, safe="")
        token = _read_token(self._bearer_token_file, provider=self.system)
        headers = {"Authorization": f"Bearer {token}"}
        return self._request(
            binding,
            url=f"{self.api_url}/{segment}/{object_id}",
            headers=headers,
            payload_key=None,
        )


class MetadataProviderReadService:
    """Dispatch provider reads while preserving the GDA crosswalk boundary."""

    def __init__(self, clients: dict[MetadataFabricSystem, MetadataProviderReadClient]) -> None:
        self._clients = dict(clients)

    @classmethod
    def from_env(
        cls,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> MetadataProviderReadService:
        clients: dict[MetadataFabricSystem, MetadataProviderReadClient] = {}
        gravitino_url = os.environ.get("GDA_GRAVITINO_URL", "").strip()
        openmetadata_url = os.environ.get("GDA_OPENMETADATA_URL", "").strip()
        timeout_raw = os.environ.get("GDA_METADATA_PROVIDER_READ_TIMEOUT_SECONDS", "10")
        if gravitino_url or openmetadata_url:
            provider = (
                MetadataFabricSystem.GRAVITINO
                if gravitino_url
                else MetadataFabricSystem.OPENMETADATA
            )
            try:
                timeout = float(timeout_raw)
            except ValueError as exc:
                raise MetadataProviderReadConfigurationError(
                    "provider read timeout must be numeric", provider=provider
                ) from exc
        else:
            timeout = 10.0
        if gravitino_url:
            token = os.environ.get("GDA_GRAVITINO_BEARER_TOKEN_FILE", "").strip()
            clients[MetadataFabricSystem.GRAVITINO] = GravitinoMetadataProviderReadClient(
                gravitino_url,
                timeout_seconds=timeout,
                bearer_token_file=Path(token) if token else None,
                transport=transport,
            )
        openmetadata_token = resolve_bearer_token_file(
            file_env_name="GDA_OPENMETADATA_BEARER_TOKEN_FILE",
            source_env_name="GDA_OPENMETADATA_BEARER_TOKEN_SOURCE",
            error_factory=lambda message: MetadataProviderReadConfigurationError(
                message, provider=MetadataFabricSystem.OPENMETADATA
            ),
        )
        if openmetadata_url or openmetadata_token is not None:
            if not openmetadata_url or openmetadata_token is None:
                raise MetadataProviderReadConfigurationError(
                    "OpenMetadata URL and bearer token file must be configured together",
                    provider=MetadataFabricSystem.OPENMETADATA,
                )
            clients[MetadataFabricSystem.OPENMETADATA] = OpenMetadataProviderReadClient(
                openmetadata_url,
                bearer_token_file=openmetadata_token,
                timeout_seconds=timeout,
                transport=transport,
            )
        return cls(clients)

    def read(self, binding: MetadataFabricBinding) -> ProviderReadResult:
        started = time.monotonic()
        outcome = "error"
        try:
            client = self._clients.get(binding.system)
            if client is None:
                raise MetadataProviderReadConfigurationError(
                    f"no {binding.system.value} provider-read adapter is configured",
                    provider=binding.system,
                )
            result = client.read(binding)
            outcome = result.status.value
            return result
        finally:
            record_metadata_provider_operation(
                binding.system.value,
                "read",
                outcome,
                time.monotonic() - started,
            )

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

    def __enter__(self) -> MetadataProviderReadService:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
