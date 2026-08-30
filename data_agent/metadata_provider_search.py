"""Bounded provider discovery for already-bound Metadata Fabric namespaces."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .metadata_fabric import MetadataFabricSystem
from .metadata_provider_metrics import record_metadata_provider_operation
from .metadata_provider_read import (
    MetadataProviderReadError,
    _read_token,
    _safe_url,
    _token_path,
)
from .openmetadata_lineage_worker import (
    OpenMetadataLineageConfigurationError,
    normalize_openmetadata_api_url,
)
from .platform_contracts import Sha256, TenantId, canonical_json_fingerprint
from .provider_credentials import resolve_bearer_token_file

PROVIDER_SEARCH_SCHEMA = "gda.metadata_provider_search.v1"
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_PROVIDER_IDENTIFIERS = 5_000
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def provider_search_candidate_fingerprint(
    *,
    tenant_id: str,
    provider_namespace: str,
    external_object_id: str,
    external_object_type: str,
    system: MetadataFabricSystem = MetadataFabricSystem.GRAVITINO,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": PROVIDER_SEARCH_SCHEMA,
            "tenant_id": tenant_id,
            "system": MetadataFabricSystem(system).value,
            "provider_namespace": provider_namespace,
            "external_object_id": external_object_id,
            "external_object_type": external_object_type,
        }
    )


class ProviderSearchItem(BaseModel):
    """A provider candidate, not a copied provider catalog object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[PROVIDER_SEARCH_SCHEMA] = PROVIDER_SEARCH_SCHEMA
    tenant_id: TenantId
    system: MetadataFabricSystem = MetadataFabricSystem.GRAVITINO
    provider_namespace: str = Field(min_length=1, max_length=512)
    external_object_id: str = Field(min_length=1, max_length=512)
    external_object_type: str = Field(min_length=1, max_length=128)
    candidate_sha256: Sha256
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence")
    @classmethod
    def _bounded_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 4096:
            raise ValueError("provider search evidence exceeds the bounded contract")
        return value

    @model_validator(mode="after")
    def _fingerprint_is_bound(self) -> ProviderSearchItem:
        expected = provider_search_candidate_fingerprint(
            tenant_id=self.tenant_id,
            provider_namespace=self.provider_namespace,
            external_object_id=self.external_object_id,
            external_object_type=self.external_object_type,
            system=self.system,
        )
        if self.candidate_sha256 != expected:
            raise ValueError("provider search candidate fingerprint is invalid")
        return self


class ProviderSearchPage(BaseModel):
    """Deterministic page of candidates discovered in one provider namespace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[PROVIDER_SEARCH_SCHEMA] = PROVIDER_SEARCH_SCHEMA
    tenant_id: TenantId
    system: MetadataFabricSystem = MetadataFabricSystem.GRAVITINO
    provider_namespace: str = Field(min_length=1, max_length=512)
    object_type: str = Field(min_length=1, max_length=128)
    query: str | None = Field(default=None, max_length=128)
    items: tuple[ProviderSearchItem, ...]
    count: int = Field(ge=0, le=100)
    offset: int = Field(ge=0, le=10_000)
    limit: int = Field(ge=1, le=100)
    has_more: bool
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _items_match_page(self) -> ProviderSearchPage:
        if self.count != len(self.items):
            raise ValueError("provider search count must match the page item count")
        for item in self.items:
            if (
                item.tenant_id != self.tenant_id
                or item.system is not self.system
                or item.provider_namespace != self.provider_namespace
                or item.external_object_type != self.object_type
            ):
                raise ValueError("provider search item does not match the page identity")
        return self


def _namespace_parts(namespace: str) -> tuple[str, str, str]:
    parts = namespace.strip().split("/")
    if len(parts) != 3 or any(not part or not _NAME_RE.fullmatch(part) for part in parts):
        raise ValueError("provider namespace must be metalake/catalog/namespace")
    return parts[0], parts[1], parts[2]


class GravitinoMetadataProviderSearchClient:
    """Search only one explicitly allowed Gravitino namespace."""

    system = MetadataFabricSystem.GRAVITINO
    _PATH_SEGMENTS = {
        "table": "tables",
        "view": "views",
        "fileset": "filesets",
        "topic": "topics",
    }

    def __init__(
        self,
        api_url: str,
        *,
        timeout_seconds: float = 10.0,
        bearer_token_file: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise MetadataProviderReadError(
                "provider search timeout must be between 0 and 120 seconds",
                code="provider_search_configuration_error",
                provider=self.system,
            )
        self.api_url = _safe_url(api_url, provider=self.system)
        self._bearer_token_file = (
            _token_path(bearer_token_file, provider=self.system)
            if bearer_token_file is not None
            else None
        )
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "*/*",
                "User-Agent": "gis-data-agent-metadata-provider-search/1",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GravitinoMetadataProviderSearchClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def search(
        self,
        tenant_id: str,
        *,
        provider_namespace: str,
        object_type: str = "table",
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProviderSearchPage:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
            raise MetadataProviderReadError(
                "provider search pagination is outside the supported range",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        normalized_query = query.strip() if query is not None else None
        if normalized_query == "":
            normalized_query = None
        if normalized_query is not None and len(normalized_query) > 128:
            raise MetadataProviderReadError(
                "provider search query must be at most 128 characters",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        try:
            metalake, catalog, namespace = _namespace_parts(provider_namespace)
        except ValueError as exc:
            raise MetadataProviderReadError(
                str(exc),
                code="provider_search_query_invalid",
                provider=self.system,
            ) from exc
        segment = self._PATH_SEGMENTS.get(object_type)
        if segment is None:
            raise MetadataProviderReadError(
                "provider search object type is unsupported",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        path = (
            f"{self.api_url}/api/metalakes/{quote(metalake, safe='')}"
            f"/catalogs/{quote(catalog, safe='')}/schemas/{quote(namespace, safe='')}/{segment}"
        )
        headers: dict[str, str] = {}
        if self._bearer_token_file is not None:
            token = _read_token(self._bearer_token_file, provider=self.system)
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._client.get(path, headers=headers or None)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MetadataProviderReadError(
                f"Gravitino provider search request failed: {type(exc).__name__}",
                code="provider_search_transport_error",
                provider=self.system,
                retryable=True,
            ) from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise MetadataProviderReadError(
                "Gravitino provider search response exceeds the bounded contract",
                code="provider_search_response_too_large",
                provider=self.system,
            )
        if response.status_code == 404:
            raise MetadataProviderReadError(
                "Gravitino provider namespace or collection was not found",
                code="provider_search_namespace_not_found",
                provider=self.system,
                status_code=404,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetadataProviderReadError(
                "Gravitino provider search returned invalid JSON",
                code="provider_invalid_json",
                provider=self.system,
                status_code=response.status_code,
            ) from exc
        if not 200 <= response.status_code < 300:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise MetadataProviderReadError(
                f"Gravitino provider search returned HTTP {response.status_code}",
                code="provider_http_error",
                provider=self.system,
                status_code=response.status_code,
                retryable=retryable,
            )
        if not isinstance(payload, dict) or payload.get("code") not in {None, 0}:
            raise MetadataProviderReadError(
                "Gravitino provider search returned an invalid document",
                code="provider_invalid_document",
                provider=self.system,
                status_code=response.status_code,
            )
        identifiers = payload.get("identifiers")
        if not isinstance(identifiers, list) or len(identifiers) > _MAX_PROVIDER_IDENTIFIERS:
            raise MetadataProviderReadError(
                "Gravitino provider search identifiers exceed the bounded contract",
                code="provider_search_response_invalid",
                provider=self.system,
            )
        query_folded = normalized_query.casefold() if normalized_query else None
        names: list[str] = []
        expected_namespace = [metalake, catalog, namespace]
        for identifier in identifiers:
            if not isinstance(identifier, dict):
                continue
            name = identifier.get("name")
            identifier_namespace = identifier.get("namespace")
            if (
                not isinstance(name, str)
                or not _NAME_RE.fullmatch(name)
                or identifier_namespace != expected_namespace
            ):
                continue
            if query_folded is not None and query_folded not in name.casefold():
                continue
            names.append(name)
        names = sorted(set(names), key=lambda value: (value.casefold(), value))
        page_names = names[offset : offset + limit]
        items = tuple(
            ProviderSearchItem(
                tenant_id=tenant_id,
                provider_namespace=provider_namespace,
                external_object_id=name,
                external_object_type=object_type,
                candidate_sha256=provider_search_candidate_fingerprint(
                    tenant_id=tenant_id,
                    provider_namespace=provider_namespace,
                    external_object_id=name,
                    external_object_type=object_type,
                    system=self.system,
                ),
                evidence={"name": name, "namespace": expected_namespace},
            )
            for name in page_names
        )
        return ProviderSearchPage(
            tenant_id=tenant_id,
            provider_namespace=provider_namespace,
            object_type=object_type,
            query=normalized_query,
            items=items,
            count=len(items),
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < len(names),
            observed_at=datetime.now(UTC),
        )


class OpenMetadataMetadataProviderSearchClient:
    """Search bound OpenMetadata services without copying governance entities."""

    system = MetadataFabricSystem.OPENMETADATA
    _INDEXES = {"table": "table_search_index"}

    def __init__(
        self,
        api_url: str,
        *,
        bearer_token_file: Path,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise MetadataProviderReadError(
                "provider search timeout must be between 0 and 120 seconds",
                code="provider_search_configuration_error",
                provider=self.system,
            )
        try:
            normalized = normalize_openmetadata_api_url(api_url)
        except OpenMetadataLineageConfigurationError as exc:
            raise MetadataProviderReadError(
                str(exc),
                code="provider_search_configuration_error",
                provider=self.system,
            ) from exc
        self.api_url = normalized
        self._bearer_token_file = _token_path(bearer_token_file, provider=self.system)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "gis-data-agent-metadata-provider-search/1",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenMetadataMetadataProviderSearchClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _service_matches(source: dict[str, Any], provider_namespace: str) -> bool:
        if not provider_namespace.startswith("service:"):
            return False
        expected = provider_namespace.removeprefix("service:")
        service = source.get("service")
        service_names: set[str] = set()
        if isinstance(service, str):
            service_names.add(service)
        elif isinstance(service, dict):
            for key in ("name", "fullyQualifiedName", "displayName"):
                value = service.get(key)
                if isinstance(value, str):
                    service_names.add(value)
        for key in ("serviceName", "serviceFQN"):
            value = source.get(key)
            if isinstance(value, str):
                service_names.add(value)
        fully_qualified_name = source.get("fullyQualifiedName")
        if isinstance(fully_qualified_name, str):
            if fully_qualified_name == expected or fully_qualified_name.startswith(
                f"{expected}."
            ):
                return True
            service_names.add(fully_qualified_name.split(".", 1)[0])
        return expected in service_names

    def search(
        self,
        tenant_id: str,
        *,
        provider_namespace: str,
        object_type: str = "table",
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProviderSearchPage:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10_000:
            raise MetadataProviderReadError(
                "provider search pagination is outside the supported range",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        normalized_query = query.strip() if query is not None else None
        if not normalized_query or len(normalized_query) > 128:
            raise MetadataProviderReadError(
                "OpenMetadata provider search requires a query of at most 128 characters",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        if (
            not provider_namespace.startswith("service:")
            or not _NAME_RE.fullmatch(provider_namespace.removeprefix("service:"))
        ):
            raise MetadataProviderReadError(
                "OpenMetadata provider namespace must be service:<name>",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        index = self._INDEXES.get(object_type)
        if index is None:
            raise MetadataProviderReadError(
                "OpenMetadata provider search object type is unsupported",
                code="provider_search_query_invalid",
                provider=self.system,
            )
        token = _read_token(self._bearer_token_file, provider=self.system)
        try:
            response = self._client.get(
                f"{self.api_url}/search/query",
                params={
                    "q": normalized_query,
                    "index": index,
                    "from": offset,
                    "size": limit,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MetadataProviderReadError(
                f"OpenMetadata provider search request failed: {type(exc).__name__}",
                code="provider_search_transport_error",
                provider=self.system,
                retryable=True,
            ) from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise MetadataProviderReadError(
                "OpenMetadata provider search response exceeds the bounded contract",
                code="provider_search_response_too_large",
                provider=self.system,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetadataProviderReadError(
                "OpenMetadata provider search returned invalid JSON",
                code="provider_invalid_json",
                provider=self.system,
                status_code=response.status_code,
            ) from exc
        if not 200 <= response.status_code < 300:
            retryable = response.status_code == 429 or response.status_code >= 500
            code = (
                "provider_unauthorized"
                if response.status_code in {401, 403}
                else "provider_http_error"
            )
            raise MetadataProviderReadError(
                f"OpenMetadata provider search returned HTTP {response.status_code}",
                code=code,
                provider=self.system,
                status_code=response.status_code,
                retryable=retryable,
            )
        if not isinstance(payload, dict):
            raise MetadataProviderReadError(
                "OpenMetadata provider search returned an invalid document",
                code="provider_invalid_document",
                provider=self.system,
                status_code=response.status_code,
            )
        hits = payload.get("hits")
        if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
            raise MetadataProviderReadError(
                "OpenMetadata provider search response is missing hits",
                code="provider_search_response_invalid",
                provider=self.system,
                status_code=response.status_code,
            )
        candidates: dict[str, tuple[str, str | None]] = {}
        query_folded = normalized_query.casefold()
        for hit in hits["hits"]:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source")
            if not isinstance(source, dict) or not self._service_matches(
                source, provider_namespace
            ):
                continue
            raw_id = source.get("id") or hit.get("_id")
            if not isinstance(raw_id, str):
                continue
            try:
                object_id = str(UUID(raw_id))
            except ValueError:
                continue
            name = source.get("name") or source.get("displayName")
            fqn = source.get("fullyQualifiedName")
            if not isinstance(name, str) or not name.strip():
                continue
            if not (
                query_folded in name.casefold()
                or (isinstance(fqn, str) and query_folded in fqn.casefold())
            ):
                continue
            candidates[object_id] = (name, fqn if isinstance(fqn, str) else None)
        ordered = sorted(
            candidates.items(),
            key=lambda item: (item[1][0].casefold(), item[1][0], item[0]),
        )
        items = tuple(
            ProviderSearchItem(
                tenant_id=tenant_id,
                system=self.system,
                provider_namespace=provider_namespace,
                external_object_id=object_id,
                external_object_type=object_type,
                candidate_sha256=provider_search_candidate_fingerprint(
                    tenant_id=tenant_id,
                    provider_namespace=provider_namespace,
                    external_object_id=object_id,
                    external_object_type=object_type,
                    system=self.system,
                ),
                evidence={
                    "name": name,
                    "fullyQualifiedName": fqn,
                    "namespace": provider_namespace,
                },
            )
            for object_id, (name, fqn) in ordered
        )
        total = hits.get("total")
        if isinstance(total, dict):
            total = total.get("value")
        has_more = isinstance(total, int) and total > offset + limit
        return ProviderSearchPage(
            tenant_id=tenant_id,
            system=self.system,
            provider_namespace=provider_namespace,
            object_type=object_type,
            query=normalized_query,
            items=items,
            count=len(items),
            offset=offset,
            limit=limit,
            has_more=has_more,
            observed_at=datetime.now(UTC),
        )


class MetadataProviderSearchService:
    """Environment-backed search dispatch for bounded provider adapters."""

    def __init__(
        self,
        gravitino: GravitinoMetadataProviderSearchClient | None,
        openmetadata: OpenMetadataMetadataProviderSearchClient | None = None,
    ) -> None:
        self._gravitino = gravitino
        self._openmetadata = openmetadata

    @classmethod
    def from_env(
        cls,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> MetadataProviderSearchService:
        url = os.environ.get("GDA_GRAVITINO_URL", "").strip()
        openmetadata_url = os.environ.get("GDA_OPENMETADATA_URL", "").strip()
        openmetadata_token = resolve_bearer_token_file(
            file_env_name="GDA_OPENMETADATA_BEARER_TOKEN_FILE",
            source_env_name="GDA_OPENMETADATA_BEARER_TOKEN_SOURCE",
            error_factory=lambda message: MetadataProviderReadError(
                message,
                code="provider_search_configuration_error",
                provider=MetadataFabricSystem.OPENMETADATA,
            ),
        )
        timeout_raw = os.environ.get("GDA_METADATA_PROVIDER_READ_TIMEOUT_SECONDS", "10")
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise MetadataProviderReadError(
                "provider search timeout must be numeric",
                code="provider_search_configuration_error",
                provider=(
                    MetadataFabricSystem.GRAVITINO
                    if url
                    else MetadataFabricSystem.OPENMETADATA
                ),
            ) from exc
        token = os.environ.get("GDA_GRAVITINO_BEARER_TOKEN_FILE", "").strip()
        gravitino = (
            GravitinoMetadataProviderSearchClient(
                url,
                timeout_seconds=timeout,
                bearer_token_file=Path(token) if token else None,
                transport=transport,
            )
            if url
            else None
        )
        if openmetadata_url or openmetadata_token is not None:
            if not openmetadata_url or openmetadata_token is None:
                raise MetadataProviderReadError(
                    "OpenMetadata URL and bearer token file must be configured together",
                    code="provider_search_configuration_error",
                    provider=MetadataFabricSystem.OPENMETADATA,
                )
            openmetadata = OpenMetadataMetadataProviderSearchClient(
                openmetadata_url,
                bearer_token_file=openmetadata_token,
                timeout_seconds=timeout,
                transport=transport,
            )
        else:
            openmetadata = None
        return cls(gravitino, openmetadata)

    def search(
        self,
        tenant_id: str,
        *,
        system: MetadataFabricSystem = MetadataFabricSystem.GRAVITINO,
        **kwargs: Any,
    ) -> ProviderSearchPage:
        system = MetadataFabricSystem(system)
        started = time.monotonic()
        outcome = "error"
        try:
            client = (
                self._gravitino
                if system is MetadataFabricSystem.GRAVITINO
                else self._openmetadata
            )
            if client is None:
                raise MetadataProviderReadError(
                    f"no {system.value} provider-search adapter is configured",
                    code="provider_search_configuration_error",
                    provider=system,
                )
            result = client.search(tenant_id, **kwargs)
            outcome = "success"
            return result
        finally:
            record_metadata_provider_operation(
                system.value,
                "search",
                outcome,
                time.monotonic() - started,
            )

    def close(self) -> None:
        if self._gravitino is not None:
            self._gravitino.close()
        if self._openmetadata is not None:
            self._openmetadata.close()

    def __enter__(self) -> MetadataProviderSearchService:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
