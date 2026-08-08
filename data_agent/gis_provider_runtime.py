"""Provider runtime contracts for governed GIS service releases.

This module is deliberately data-plane-only. It discovers and reads a real
Martin MVT endpoint, but it does not own a service definition, active pointer,
or asynchronous run state. Callers record the returned observation through the
existing PlatformGateway authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .gis_service_control_plane import (
    EndpointProtocol,
    GISServiceType,
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
)
from .platform_contracts import (
    FrameworkAttemptObservation,
    FrameworkKind,
    TenantId,
    canonical_json_fingerprint,
)


class GISProviderRuntimeError(RuntimeError):
    """Base error for provider contract or transport failures."""


class GISProviderContractError(GISProviderRuntimeError):
    """The provider response or release contract is not admissible."""


class GISProviderUnavailable(GISProviderRuntimeError):
    """The provider could not serve a request or returned a server error."""


class GISProviderCapability(StrEnum):
    CATALOG = "catalog"
    HEALTH = "health"
    MVT_READ = "mvt_read"


class ProviderHealthState(StrEnum):
    READY = "ready"
    FAILED = "failed"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def provider_manifest_fingerprint(value: GISProviderManifest | dict[str, Any]) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={"manifest_sha256"})
    else:
        payload = {
            key: item for key, item in value.items() if key != "manifest_sha256"
        }
    return canonical_json_fingerprint(payload)


class GISProviderManifest(_FrozenContract):
    provider_system: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
    provider_version: str = Field(min_length=1, max_length=128)
    protocols: tuple[EndpointProtocol, ...] = Field(min_length=1)
    capabilities: tuple[GISProviderCapability, ...] = Field(min_length=1)
    read_only: bool = True
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _consistent_manifest(self) -> GISProviderManifest:
        if self.manifest_sha256 != provider_manifest_fingerprint(self):
            raise ValueError("manifest_sha256 does not match the provider manifest")
        if EndpointProtocol.MVT in self.protocols and not self.read_only:
            raise ValueError("the initial MVT provider profile is read-only")
        return self


def martin_provider_manifest(version: str = "0.18.0") -> GISProviderManifest:
    values = {
        "provider_system": "martin",
        "provider_version": version,
        "protocols": (EndpointProtocol.MVT,),
        "capabilities": (
            GISProviderCapability.CATALOG,
            GISProviderCapability.HEALTH,
            GISProviderCapability.MVT_READ,
        ),
        "read_only": True,
    }
    return GISProviderManifest(
        **values,
        manifest_sha256=provider_manifest_fingerprint(values),
    )


class MVTProviderReleaseContext(_FrozenContract):
    """The immutable control-plane IDs needed by a provider tile request."""

    tenant_id: TenantId
    service_type: GISServiceType
    service_release_binding_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    style_definition_version_id: UUID
    tile_matrix_set_definition_version_id: UUID
    tile_matrix_set_crs_uri: str = Field(min_length=1, max_length=512)
    min_zoom: int = Field(ge=0, le=30)
    max_zoom: int = Field(ge=0, le=30)
    provider_layer_ref: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")
    provider_query: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent_context(self) -> MVTProviderReleaseContext:
        if self.service_type != GISServiceType.VECTOR_TILE:
            raise GISProviderContractError(
                "Martin MVT adapter requires a vector_tile service definition"
            )
        if self.max_zoom < self.min_zoom:
            raise ValueError("max_zoom cannot precede min_zoom")
        return self

    @classmethod
    def from_release(
        cls,
        release: ServiceReleaseBinding,
        tile_matrix_set: TileMatrixSetDefinitionVersion,
        *,
        service_type: GISServiceType | str,
        provider_layer_ref: str,
        provider_query: Mapping[str, str] | None = None,
    ) -> MVTProviderReleaseContext:
        if release.tile_matrix_set_definition_version_id is None:
            raise GISProviderContractError("MVT release must bind a tile matrix set")
        if (
            release.tile_matrix_set_definition_version_id
            != tile_matrix_set.tile_matrix_set_definition_version_id
        ):
            raise GISProviderContractError(
                "provider TMS does not match the release binding"
            )
        if (
            release.service_definition_version_id
            != tile_matrix_set.service_definition_version_id
        ):
            raise GISProviderContractError(
                "provider TMS belongs to another service definition"
            )
        if tile_matrix_set.layer_definition_version_id != release.layer_definition_version_id:
            raise GISProviderContractError(
                "provider TMS belongs to another layer definition"
            )
        return cls(
            tenant_id=release.tenant_id,
            service_type=service_type,
            service_release_binding_id=release.service_release_binding_id,
            service_definition_version_id=release.service_definition_version_id,
            layer_definition_version_id=release.layer_definition_version_id,
            style_definition_version_id=release.style_definition_version_id,
            tile_matrix_set_definition_version_id=(
                tile_matrix_set.tile_matrix_set_definition_version_id
            ),
            tile_matrix_set_crs_uri=tile_matrix_set.crs_uri,
            min_zoom=tile_matrix_set.min_zoom,
            max_zoom=tile_matrix_set.max_zoom,
            provider_layer_ref=provider_layer_ref,
            provider_query=dict(provider_query or {}),
        )


class ProviderHealthObservation(_FrozenContract):
    provider_system: str
    provider_version: str
    endpoint_uri: str
    state: ProviderHealthState
    status_code: int = Field(ge=100, le=599)
    observed_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def _observed_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_observation(self) -> ProviderHealthObservation:
        payload = self.model_dump(mode="json", exclude={"evidence_sha256"})
        if self.evidence_sha256 != canonical_json_fingerprint(payload):
            raise ValueError("evidence_sha256 does not match provider observation")
        return self


@dataclass(frozen=True)
class ProviderTileResponse:
    content: bytes
    status_code: int
    media_type: str
    etag: str | None


class MartinVectorTileProvider:
    """Small read-only adapter for a governed Martin MVT endpoint."""

    ACCEPTED_MEDIA_TYPES = frozenset(
        {
            "application/vnd.mapbox-vector-tile",
            "application/x-protobuf",
            "application/octet-stream",
        }
    )

    def __init__(
        self,
        endpoint_uri: str,
        *,
        manifest: GISProviderManifest | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint_uri)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise GISProviderContractError(
                "Martin endpoint must be a credential-free HTTP(S) URI"
            )
        if timeout <= 0:
            raise ValueError("provider timeout must be positive")
        self.endpoint_uri = endpoint_uri.rstrip("/")
        self.manifest = manifest or martin_provider_manifest()
        if EndpointProtocol.MVT not in self.manifest.protocols:
            raise GISProviderContractError("Martin adapter requires an MVT manifest")
        self.timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        options: dict[str, Any] = {
            "timeout": self.timeout,
            "trust_env": False,
        }
        if self._transport is not None:
            options["transport"] = self._transport
        return httpx.AsyncClient(**options)

    async def discover_capabilities(self) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.endpoint_uri}/catalog")
        except httpx.HTTPError as exc:
            raise GISProviderUnavailable("Martin catalog request failed") from exc
        if response.status_code >= 500:
            raise GISProviderUnavailable(
                f"Martin catalog returned HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise GISProviderContractError(
                f"Martin catalog returned HTTP {response.status_code}"
            )
        try:
            catalog = response.json()
        except ValueError as exc:
            raise GISProviderContractError("Martin catalog was not JSON") from exc
        if not isinstance(catalog, dict):
            raise GISProviderContractError("Martin catalog must be a JSON object")
        return catalog

    async def health(self) -> ProviderHealthObservation:
        observed_at = datetime.now(UTC)
        try:
            async with self._client() as client:
                response = await client.get(f"{self.endpoint_uri}/health")
        except httpx.HTTPError as exc:
            raise GISProviderUnavailable("Martin health request failed") from exc
        state = (
            ProviderHealthState.READY
            if response.status_code == 200
            else ProviderHealthState.FAILED
        )
        values = {
            "provider_system": self.manifest.provider_system,
            "provider_version": self.manifest.provider_version,
            "endpoint_uri": self.endpoint_uri,
            "state": state,
            "status_code": response.status_code,
            "observed_at": observed_at,
        }
        observation = ProviderHealthObservation(
            **values,
            evidence_sha256=canonical_json_fingerprint(
                ProviderHealthObservation.model_construct(**values).model_dump(
                    mode="json"
                )
            ),
        )
        if state is ProviderHealthState.FAILED:
            raise GISProviderUnavailable(
                f"Martin health returned HTTP {response.status_code}"
            )
        return observation

    async def build_ready_observation(
        self,
        context: MVTProviderReleaseContext,
        *,
        run_id: UUID,
        observation_id: UUID,
        attempt_no: int,
        external_run_id: str,
        external_attempt_id: str,
        observed_at: datetime | None = None,
    ) -> FrameworkAttemptObservation:
        health = await self.health()
        evidence = {
            "schema": "gda.gis_mvt_provider_observation.v1",
            "provider_system": self.manifest.provider_system,
            "provider_version": self.manifest.provider_version,
            "endpoint_uri": self.endpoint_uri,
            "service_release_binding_id": str(context.service_release_binding_id),
            "service_definition_version_id": str(
                context.service_definition_version_id
            ),
            "layer_definition_version_id": str(context.layer_definition_version_id),
            "style_definition_version_id": str(context.style_definition_version_id),
            "tile_matrix_set_definition_version_id": str(
                context.tile_matrix_set_definition_version_id
            ),
            "provider_layer_ref": context.provider_layer_ref,
            "health_evidence_sha256": health.evidence_sha256,
        }
        return FrameworkAttemptObservation(
            tenant_id=context.tenant_id,
            observation_id=observation_id,
            run_id=run_id,
            attempt_no=attempt_no,
            framework_kind=FrameworkKind.CLOUD,
            external_namespace=self.manifest.provider_system,
            external_run_id=external_run_id,
            external_attempt_id=external_attempt_id,
            observed_state="ready",
            observation_sha256=canonical_json_fingerprint(evidence),
            evidence=evidence,
            observed_at=observed_at or datetime.now(UTC),
        )

    async def fetch_tile(
        self,
        context: MVTProviderReleaseContext,
        z: int,
        x: int,
        y: int,
    ) -> ProviderTileResponse:
        if z < context.min_zoom or z > context.max_zoom:
            raise GISProviderContractError("tile zoom is outside the release TMS")
        if z < 0 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
            raise GISProviderContractError("tile coordinate is outside the TMS")
        path = f"/{context.provider_layer_ref}/{z}/{x}/{y}"
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self.endpoint_uri}{path}",
                    params=context.provider_query,
                    headers={
                        "Accept": "application/vnd.mapbox-vector-tile",
                        "Accept-Encoding": "identity",
                    },
                )
        except httpx.HTTPError as exc:
            raise GISProviderUnavailable("Martin tile request failed") from exc
        if response.status_code >= 500:
            raise GISProviderUnavailable(
                f"Martin tile returned HTTP {response.status_code}"
            )
        if response.status_code == 204:
            return ProviderTileResponse(b"", 204, "application/vnd.mapbox-vector-tile", None)
        if response.status_code != 200:
            raise GISProviderContractError(
                f"Martin tile returned HTTP {response.status_code}"
            )
        media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type not in self.ACCEPTED_MEDIA_TYPES:
            raise GISProviderContractError(
                f"Martin tile returned unsupported media type {media_type or '<empty>'}"
            )
        return ProviderTileResponse(
            response.content,
            200,
            media_type,
            response.headers.get("etag"),
        )
