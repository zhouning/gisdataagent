"""Provider runtime contracts for governed GIS service releases.

This module is deliberately data-plane-only. It discovers and reads a real
Martin MVT endpoint, but it does not own a service definition, active pointer,
or asynchronous run state. Callers record the returned observation through the
existing PlatformGateway authority.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Literal
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .gis_service_control_plane import (
    CachePolicyVersion,
    EndpointProtocol,
    EndpointRevision,
    GISServiceDefinitionVersion,
    GISServiceType,
    LayerDefinitionVersion,
    MVTServingProjectionVersion,
    ServiceDeploymentRevision,
    ServiceDeploymentState,
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
)
from .platform_contracts import (
    FrameworkAttemptObservation,
    FrameworkKind,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
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
    OGC_FEATURES_READ = "ogc_features_read"


class ProviderHealthState(StrEnum):
    READY = "ready"
    FAILED = "failed"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


_JSON_VALUE_ADAPTER = TypeAdapter(Any)
_MVT_MEDIA_TYPES = frozenset(
    {
        "application/vnd.mapbox-vector-tile",
        "application/x-protobuf",
        "application/octet-stream",
    }
)


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


def pygeoapi_provider_manifest(version: str = "0.21.0") -> GISProviderManifest:
    """Return the read-only provider profile used for OGC API Features."""
    values = {
        "provider_system": "pygeoapi",
        "provider_version": version,
        "protocols": (EndpointProtocol.OGC_API_FEATURES,),
        "capabilities": (
            GISProviderCapability.CATALOG,
            GISProviderCapability.HEALTH,
            GISProviderCapability.OGC_FEATURES_READ,
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
    mvt_serving_projection_version_id: UUID
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
        serving_projection: MVTServingProjectionVersion,
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
        if (
            release.mvt_serving_projection_version_id
            != serving_projection.mvt_serving_projection_version_id
        ):
            raise GISProviderContractError(
                "provider serving projection does not match the release binding"
            )
        if (
            serving_projection.service_definition_version_id
            != release.service_definition_version_id
            or serving_projection.layer_definition_version_id
            != release.layer_definition_version_id
        ):
            raise GISProviderContractError(
                "provider serving projection belongs to another release component"
            )
        return cls(
            tenant_id=release.tenant_id,
            service_type=service_type,
            service_release_binding_id=release.service_release_binding_id,
            service_definition_version_id=release.service_definition_version_id,
            layer_definition_version_id=release.layer_definition_version_id,
            style_definition_version_id=release.style_definition_version_id,
            mvt_serving_projection_version_id=(
                serving_projection.mvt_serving_projection_version_id
            ),
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


class MartinMVTConformanceReceipt(_FrozenContract):
    """One successful, release-bound Martin MVT data-plane probe.

    This is provider-produced evidence for the existing GIS deployment terminal
    settlement.  It records an actual catalog and tile read rather than treating
    a standalone health response as sufficient serving readiness.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, use_enum_values=False, populate_by_name=True
    )
    receipt_schema: Literal["gda.gis_martin_mvt_conformance.v1"] = Field(
        default="gda.gis_martin_mvt_conformance.v1", alias="schema"
    )
    provider_system: Literal["martin"] = "martin"
    provider_version: str
    provider_endpoint_uri: str
    service_release_binding_id: UUID
    mvt_serving_projection_version_id: UUID
    provider_layer_ref: Literal["gda_mvt_serving_projection"]
    provider_query: dict[str, str]
    provider_query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    health: ProviderHealthObservation
    z: int = Field(ge=0, le=30)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    tile_status_code: Literal[200]
    tile_media_type: str = Field(min_length=1, max_length=256)
    tile_content_bytes: int = Field(gt=0)
    tile_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tile_etag: str | None = Field(default=None, max_length=4096)
    observed_at: datetime
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def _conformance_observed_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_receipt(self) -> MartinMVTConformanceReceipt:
        if self.health.state is not ProviderHealthState.READY:
            raise ValueError("Martin conformance requires a ready health observation")
        if (
            self.health.provider_system != self.provider_system
            or self.health.provider_version != self.provider_version
            or self.health.endpoint_uri != self.provider_endpoint_uri
        ):
            raise ValueError("Martin conformance health does not match the provider")
        if self.observed_at < self.health.observed_at:
            raise ValueError("Martin conformance cannot precede its health observation")
        if self.x >= 2**self.z or self.y >= 2**self.z:
            raise ValueError("Martin conformance tile coordinate is outside the TMS")
        expected_query = {
            "serving_projection_version_id": str(
                self.mvt_serving_projection_version_id
            )
        }
        if self.provider_query != expected_query:
            raise ValueError(
                "Martin conformance must query exactly one serving projection"
            )
        if self.provider_query_sha256 != canonical_json_fingerprint(
            self.provider_query
        ):
            raise ValueError("provider_query_sha256 does not match the provider query")
        if self.receipt_sha256 != martin_mvt_conformance_fingerprint(self):
            raise ValueError("receipt_sha256 does not match Martin conformance")
        return self


def martin_mvt_conformance_fingerprint(
    value: MartinMVTConformanceReceipt | dict[str, Any],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json", by_alias=True, exclude={"receipt_sha256"}
        )
    else:
        payload = {key: item for key, item in value.items() if key != "receipt_sha256"}
        health = payload.get("health")
        if isinstance(health, BaseModel):
            payload["health"] = health.model_dump(mode="json")
        payload = _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    return canonical_json_fingerprint(payload)


class MartinMVTWarmupSample(_FrozenContract):
    """One immutable tile coordinate in a provider-origin warmup set."""

    z: int = Field(ge=0, le=30)
    x: int = Field(ge=0)
    y: int = Field(ge=0)

    @model_validator(mode="after")
    def _inside_tile_matrix(self) -> MartinMVTWarmupSample:
        if self.x >= 2**self.z or self.y >= 2**self.z:
            raise ValueError("warmup sample coordinate is outside the tile matrix")
        return self


def martin_mvt_warmup_sample_set_fingerprint(
    samples: tuple[MartinMVTWarmupSample, ...],
) -> str:
    """Fingerprint the ordered, requested coordinate set before provider I/O."""
    return canonical_json_fingerprint(
        {
            "schema": "gda.gis_service_martin_warmup_samples.v1",
            "samples": [sample.model_dump(mode="json") for sample in samples],
        }
    )


def martin_mvt_warmup_sample_receipt_fingerprint(
    value: MartinMVTWarmupSampleReceipt | dict[str, Any],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={"sample_sha256"})
    else:
        payload = {
            key: item for key, item in value.items() if key != "sample_sha256"
        }
        payload = _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    return canonical_json_fingerprint(payload)


class MartinMVTWarmupSampleReceipt(_FrozenContract):
    """Observed response for one non-empty Martin MVT warmup request."""

    sample_no: int = Field(ge=1, le=100)
    z: int = Field(ge=0, le=30)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    status_code: Literal[200]
    media_type: str = Field(min_length=1, max_length=256)
    content_bytes: int = Field(gt=0)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    etag: str | None = Field(default=None, max_length=4096)
    observed_at: datetime
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def _sample_observed_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_sample(self) -> MartinMVTWarmupSampleReceipt:
        if self.x >= 2**self.z or self.y >= 2**self.z:
            raise ValueError("warmup sample coordinate is outside the tile matrix")
        if self.media_type not in _MVT_MEDIA_TYPES:
            raise ValueError("warmup sample media type is not MVT")
        if self.sample_sha256 != martin_mvt_warmup_sample_receipt_fingerprint(
            self
        ):
            raise ValueError("sample_sha256 does not match the warmup sample")
        return self


def martin_mvt_endpoint_warmup_fingerprint(
    value: MartinMVTEndpointWarmupReceipt | dict[str, Any],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json", by_alias=True, exclude={"receipt_sha256"}
        )
    else:
        payload = {
            key: item for key, item in value.items() if key != "receipt_sha256"
        }
        payload = _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    return canonical_json_fingerprint(payload)


class MartinMVTEndpointWarmupReceipt(_FrozenContract):
    """Exact-release receipt for real Martin health, catalog and MVT reads."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, use_enum_values=False, populate_by_name=True
    )
    receipt_schema: Literal["gda.gis_service_martin_endpoint_warmup.v1"] = Field(
        default="gda.gis_service_martin_endpoint_warmup.v1", alias="schema"
    )
    provider_system: Literal["martin"] = "martin"
    provider_version: str = Field(min_length=1, max_length=128)
    provider_origin_uri: str
    consumer_endpoint_uri: str
    tenant_id: TenantId
    service_urn: str
    endpoint_revision_id: UUID
    deployment_revision_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    cache_policy_version_id: UUID
    cache_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    mvt_serving_projection_version_id: UUID
    provider_layer_ref: Literal["gda_mvt_serving_projection"]
    provider_query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    health: ProviderHealthObservation
    requested_sample_count: int = Field(ge=1, le=100)
    successful_sample_count: int = Field(ge=1, le=100)
    sample_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    samples: tuple[MartinMVTWarmupSampleReceipt, ...] = Field(
        min_length=1, max_length=100
    )
    started_at: datetime
    completed_at: datetime
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("started_at", "completed_at")
    @classmethod
    def _warmup_time_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("provider_origin_uri")
    @classmethod
    def _credential_free_provider_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Martin warmup provider origin must be credential-free HTTP(S)"
            )
        return value

    @field_validator("consumer_endpoint_uri")
    @classmethod
    def _stable_consumer_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Martin warmup consumer endpoint must be credential-free HTTPS"
            )
        return value

    @model_validator(mode="after")
    def _consistent_receipt(self) -> MartinMVTEndpointWarmupReceipt:
        service = parse_resource_urn(self.service_urn)
        if (
            service["tenant_id"] != self.tenant_id
            or service["resource_kind"] != "gis_service"
        ):
            raise ValueError("Martin warmup service_urn does not match its tenant")
        if self.health.state is not ProviderHealthState.READY:
            raise ValueError("Martin warmup requires a ready health observation")
        if (
            self.health.provider_system != self.provider_system
            or self.health.provider_version != self.provider_version
            or self.health.endpoint_uri != self.provider_origin_uri
        ):
            raise ValueError("Martin warmup health does not match its provider origin")
        if self.completed_at < self.started_at:
            raise ValueError("Martin warmup cannot complete before it starts")
        if self.health.observed_at < self.started_at:
            raise ValueError("Martin warmup health cannot precede the warmup")
        if any(
            sample.observed_at < self.started_at
            or sample.observed_at > self.completed_at
            for sample in self.samples
        ):
            raise ValueError("Martin warmup samples must occur inside its time window")
        if (
            self.requested_sample_count != len(self.samples)
            or self.successful_sample_count != self.requested_sample_count
        ):
            raise ValueError("every requested Martin warmup sample must succeed")
        if [sample.sample_no for sample in self.samples] != list(
            range(1, len(self.samples) + 1)
        ):
            raise ValueError("Martin warmup sample sequence must be contiguous")
        requested = tuple(
            MartinMVTWarmupSample(z=sample.z, x=sample.x, y=sample.y)
            for sample in self.samples
        )
        if len(set(requested)) != len(requested):
            raise ValueError("Martin warmup samples must be unique")
        if self.sample_set_sha256 != martin_mvt_warmup_sample_set_fingerprint(
            requested
        ):
            raise ValueError("sample_set_sha256 does not match Martin samples")
        expected_query = {
            "serving_projection_version_id": str(
                self.mvt_serving_projection_version_id
            )
        }
        if self.provider_query_sha256 != canonical_json_fingerprint(expected_query):
            raise ValueError(
                "provider_query_sha256 does not match the serving projection"
            )
        if self.receipt_sha256 != martin_mvt_endpoint_warmup_fingerprint(self):
            raise ValueError("receipt_sha256 does not match Martin warmup")
        return self


@dataclass(frozen=True)
class ProviderTileResponse:
    content: bytes
    status_code: int
    media_type: str
    etag: str | None


class MartinVectorTileProvider:
    """Small read-only adapter for a governed Martin MVT endpoint."""

    ACCEPTED_MEDIA_TYPES = _MVT_MEDIA_TYPES

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

    async def probe_health(self) -> ProviderHealthObservation:
        """Capture the provider health response, including a failed terminal result."""
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
        return observation

    async def health(self) -> ProviderHealthObservation:
        """Return healthy evidence or retain the existing unavailable-provider signal."""
        observation = await self.probe_health()
        if observation.state is ProviderHealthState.FAILED:
            raise GISProviderUnavailable(
                f"Martin health returned HTTP {observation.status_code}"
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

    def _build_deployment_terminal_observation(
        self,
        context: MVTProviderReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        health: ProviderHealthObservation,
        terminal_state: ProviderHealthState,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        provider_receipt: dict[str, Any],
        observed_at: datetime | None,
    ) -> FrameworkAttemptObservation:
        if health.state is not terminal_state:
            raise GISProviderContractError(
                "provider health does not match the deployment terminal state"
            )
        if (
            health.provider_system != self.manifest.provider_system
            or health.provider_version != self.manifest.provider_version
            or health.endpoint_uri != self.endpoint_uri
        ):
            raise GISProviderContractError(
                "provider health does not belong to this Martin adapter"
            )
        if (
            deployment.tenant_id != context.tenant_id
            or deployment.service_definition_version_id
            != context.service_definition_version_id
            or deployment.service_release_binding_id
            != context.service_release_binding_id
            or deployment.provider_system != self.manifest.provider_system
        ):
            raise GISProviderContractError(
                "deployment does not match the Martin release context"
            )
        parsed_endpoint = urlsplit(endpoint_uri)
        if (
            parsed_endpoint.scheme != "https"
            or not parsed_endpoint.hostname
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise GISProviderContractError(
                "deployment endpoint must be a credential-free HTTPS URI"
            )
        if not provider_receipt:
            raise GISProviderContractError(
                "deployment terminal evidence requires provider receipt"
            )
        evidence = {
            "schema": "gda.gis_service_deployment_observation.v2",
            "deployment_revision_id": str(deployment.deployment_revision_id),
            "service_definition_version_id": str(
                deployment.service_definition_version_id
            ),
            "service_release_binding_id": str(
                deployment.service_release_binding_id
            ),
            "provider_system": deployment.provider_system,
            "provider_version": self.manifest.provider_version,
            "provider_namespace": deployment.provider_namespace,
            "provider_deployment_id": deployment.provider_deployment_id,
            "provider_revision_ref": deployment.provider_revision_ref,
            "config_sha256": deployment.config_sha256,
            "endpoint_uri": endpoint_uri,
            "health_evidence_sha256": health.evidence_sha256,
            "provider_receipt": provider_receipt,
            "release_context": {
                "layer_definition_version_id": str(
                    context.layer_definition_version_id
                ),
                "style_definition_version_id": str(
                    context.style_definition_version_id
                ),
                "tile_matrix_set_definition_version_id": str(
                    context.tile_matrix_set_definition_version_id
                ),
                "mvt_serving_projection_version_id": str(
                    context.mvt_serving_projection_version_id
                ),
            },
        }
        return FrameworkAttemptObservation(
            tenant_id=deployment.tenant_id,
            observation_id=observation_id,
            run_id=deployment.run_id,
            attempt_no=attempt_no,
            framework_kind=FrameworkKind.CLOUD,
            external_namespace=deployment.provider_namespace,
            external_run_id=deployment.provider_deployment_id,
            external_attempt_id=deployment.provider_revision_ref,
            observed_state=terminal_state.value,
            observation_sha256=canonical_json_fingerprint(evidence),
            evidence=evidence,
            observed_at=observed_at or datetime.now(UTC),
        )

    async def build_deployment_ready_observation(
        self,
        context: MVTProviderReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        provider_receipt: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> FrameworkAttemptObservation:
        """Build release-bound readiness evidence for one Martin deployment."""
        health = await self.health()
        return self._build_deployment_terminal_observation(
            context,
            deployment,
            health=health,
            terminal_state=ProviderHealthState.READY,
            observation_id=observation_id,
            attempt_no=attempt_no,
            endpoint_uri=endpoint_uri,
            provider_receipt=provider_receipt,
            observed_at=observed_at,
        )

    async def conform_mvt_read(
        self,
        context: MVTProviderReleaseContext,
        z: int,
        x: int,
        y: int,
    ) -> MartinMVTConformanceReceipt:
        """Verify the governed Martin function can serve one release-bound tile.

        A successful receipt proves one complete data-plane path: Martin health,
        catalog advertisement, the fixed serving-projection function, and a
        non-empty MVT response for the supplied known-data coordinate.
        """
        if context.provider_layer_ref != "gda_mvt_serving_projection":
            raise GISProviderContractError(
                "Martin conformance requires the governed serving projection function"
            )
        expected_query = {
            "serving_projection_version_id": str(
                context.mvt_serving_projection_version_id
            )
        }
        if context.provider_query != expected_query:
            raise GISProviderContractError(
                "Martin conformance requires exactly one serving projection query"
            )

        health = await self.health()
        catalog = await self.discover_capabilities()
        tiles = catalog.get("tiles")
        if not isinstance(tiles, Mapping) or context.provider_layer_ref not in tiles:
            raise GISProviderContractError(
                "Martin catalog does not advertise the governed serving projection"
            )
        tile = await self.fetch_tile(context, z, x, y)
        if tile.status_code != 200 or not tile.content:
            raise GISProviderContractError(
                "Martin conformance requires a non-empty HTTP 200 MVT tile"
            )

        observed_at = datetime.now(UTC)
        values = {
            "schema": "gda.gis_martin_mvt_conformance.v1",
            "provider_system": self.manifest.provider_system,
            "provider_version": self.manifest.provider_version,
            "provider_endpoint_uri": self.endpoint_uri,
            "service_release_binding_id": str(context.service_release_binding_id),
            "mvt_serving_projection_version_id": str(
                context.mvt_serving_projection_version_id
            ),
            "provider_layer_ref": context.provider_layer_ref,
            "provider_query": dict(context.provider_query),
            "provider_query_sha256": canonical_json_fingerprint(
                context.provider_query
            ),
            "catalog_sha256": canonical_json_fingerprint(catalog),
            "health": health.model_dump(mode="json"),
            "z": z,
            "x": x,
            "y": y,
            "tile_status_code": tile.status_code,
            "tile_media_type": tile.media_type,
            "tile_content_bytes": len(tile.content),
            "tile_content_sha256": hashlib.sha256(tile.content).hexdigest(),
            "tile_etag": tile.etag,
            "observed_at": observed_at,
        }
        return MartinMVTConformanceReceipt(
            **values,
            receipt_sha256=martin_mvt_conformance_fingerprint(values),
        )

    async def warmup_mvt_tiles(
        self,
        context: MVTProviderReleaseContext,
        release: ServiceReleaseBinding,
        deployment: ServiceDeploymentRevision,
        endpoint: EndpointRevision,
        cache_policy: CachePolicyVersion,
        samples: tuple[MartinMVTWarmupSample, ...],
    ) -> MartinMVTEndpointWarmupReceipt:
        """Read a bounded exact-release sample set from the Martin origin.

        The consumer endpoint is recorded as control-plane identity, while I/O
        uses this adapter's private provider origin. This proves provider
        readiness and tile materialization; it does not claim that a shared
        Gateway, CDN, Redis, or GeoWebCache layer was populated.
        """
        if not samples or len(samples) > 100:
            raise GISProviderContractError(
                "Martin warmup requires between 1 and 100 samples"
            )
        coordinates = tuple((sample.z, sample.x, sample.y) for sample in samples)
        if len(set(coordinates)) != len(coordinates):
            raise GISProviderContractError("Martin warmup samples must be unique")
        if context.provider_layer_ref != "gda_mvt_serving_projection":
            raise GISProviderContractError(
                "Martin warmup requires the governed serving projection function"
            )
        expected_query = {
            "serving_projection_version_id": str(
                context.mvt_serving_projection_version_id
            )
        }
        if context.provider_query != expected_query:
            raise GISProviderContractError(
                "Martin warmup requires exactly one serving projection query"
            )
        if (
            release.tenant_id != context.tenant_id
            or release.service_release_binding_id
            != context.service_release_binding_id
            or release.service_definition_version_id
            != context.service_definition_version_id
            or release.mvt_serving_projection_version_id
            != context.mvt_serving_projection_version_id
            or release.cache_policy_version_id
            != cache_policy.cache_policy_version_id
        ):
            raise GISProviderContractError(
                "Martin warmup release does not match its provider context"
            )
        if (
            cache_policy.tenant_id != context.tenant_id
            or cache_policy.service_definition_version_id
            != context.service_definition_version_id
        ):
            raise GISProviderContractError(
                "Martin warmup cache policy does not match the release"
            )
        if (
            deployment.tenant_id != context.tenant_id
            or deployment.service_definition_version_id
            != context.service_definition_version_id
            or deployment.service_release_binding_id
            != context.service_release_binding_id
            or deployment.provider_system != self.manifest.provider_system
            or deployment.state is not ServiceDeploymentState.READY
        ):
            raise GISProviderContractError(
                "Martin warmup requires its exact ready deployment"
            )
        if (
            endpoint.tenant_id != context.tenant_id
            or endpoint.deployment_revision_id != deployment.deployment_revision_id
            or endpoint.endpoint_protocol is not EndpointProtocol.MVT
        ):
            raise GISProviderContractError(
                "Martin warmup endpoint does not match the deployment"
            )
        if endpoint.endpoint_contract != {
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": context.provider_layer_ref,
            "provider_query": expected_query,
        }:
            raise GISProviderContractError(
                "Martin warmup endpoint contract does not bind the release"
            )

        started_at = datetime.now(UTC)
        health = await self.health()
        catalog = await self.discover_capabilities()
        tiles = catalog.get("tiles")
        if not isinstance(tiles, Mapping) or context.provider_layer_ref not in tiles:
            raise GISProviderContractError(
                "Martin catalog does not advertise the governed serving projection"
            )

        sample_receipts: list[MartinMVTWarmupSampleReceipt] = []
        for sample_no, sample in enumerate(samples, start=1):
            tile = await self.fetch_tile(context, sample.z, sample.x, sample.y)
            if tile.status_code != 200 or not tile.content:
                raise GISProviderContractError(
                    "Martin warmup requires a non-empty HTTP 200 MVT for every sample"
                )
            observed_at = datetime.now(UTC)
            sample_values = {
                "sample_no": sample_no,
                "z": sample.z,
                "x": sample.x,
                "y": sample.y,
                "status_code": tile.status_code,
                "media_type": tile.media_type,
                "content_bytes": len(tile.content),
                "content_sha256": hashlib.sha256(tile.content).hexdigest(),
                "etag": tile.etag,
                "observed_at": observed_at,
            }
            sample_receipts.append(
                MartinMVTWarmupSampleReceipt(
                    **sample_values,
                    sample_sha256=(
                        martin_mvt_warmup_sample_receipt_fingerprint(sample_values)
                    ),
                )
            )

        completed_at = datetime.now(UTC)
        values = {
            "schema": "gda.gis_service_martin_endpoint_warmup.v1",
            "provider_system": self.manifest.provider_system,
            "provider_version": self.manifest.provider_version,
            "provider_origin_uri": self.endpoint_uri,
            "consumer_endpoint_uri": endpoint.endpoint_uri,
            "tenant_id": context.tenant_id,
            "service_urn": endpoint.service_urn,
            "endpoint_revision_id": endpoint.endpoint_revision_id,
            "deployment_revision_id": deployment.deployment_revision_id,
            "service_definition_version_id": context.service_definition_version_id,
            "service_release_binding_id": context.service_release_binding_id,
            "cache_policy_version_id": cache_policy.cache_policy_version_id,
            "cache_namespace": cache_policy.cache_namespace,
            "mvt_serving_projection_version_id": (
                context.mvt_serving_projection_version_id
            ),
            "provider_layer_ref": context.provider_layer_ref,
            "provider_query_sha256": canonical_json_fingerprint(expected_query),
            "catalog_sha256": canonical_json_fingerprint(catalog),
            "health": health.model_dump(mode="json"),
            "requested_sample_count": len(samples),
            "successful_sample_count": len(sample_receipts),
            "sample_set_sha256": martin_mvt_warmup_sample_set_fingerprint(samples),
            "samples": [
                receipt.model_dump(mode="json") for receipt in sample_receipts
            ],
            "started_at": started_at,
            "completed_at": completed_at,
        }
        return MartinMVTEndpointWarmupReceipt(
            **values,
            receipt_sha256=martin_mvt_endpoint_warmup_fingerprint(values),
        )

    async def build_deployment_ready_conformance_observation(
        self,
        context: MVTProviderReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        z: int,
        x: int,
        y: int,
        observed_at: datetime | None = None,
    ) -> FrameworkAttemptObservation:
        """Build v2 readiness evidence from one actual Martin catalog/tile probe."""
        conformance = await self.conform_mvt_read(context, z, x, y)
        occurrence = observed_at or datetime.now(UTC)
        if occurrence < conformance.observed_at:
            raise GISProviderContractError(
                "deployment readiness cannot precede Martin conformance"
            )
        return self._build_deployment_terminal_observation(
            context,
            deployment,
            health=conformance.health,
            terminal_state=ProviderHealthState.READY,
            observation_id=observation_id,
            attempt_no=attempt_no,
            endpoint_uri=endpoint_uri,
            provider_receipt=conformance.model_dump(mode="json", by_alias=True),
            observed_at=occurrence,
        )

    async def build_deployment_failed_observation(
        self,
        context: MVTProviderReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        provider_receipt: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> FrameworkAttemptObservation:
        """Build release-bound failed evidence after a concrete Martin health failure."""
        health = await self.probe_health()
        return self._build_deployment_terminal_observation(
            context,
            deployment,
            health=health,
            terminal_state=ProviderHealthState.FAILED,
            observation_id=observation_id,
            attempt_no=attempt_no,
            endpoint_uri=endpoint_uri,
            provider_receipt=provider_receipt,
            observed_at=observed_at,
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


_OGC_FEATURES_MEDIA_TYPES = frozenset({"application/geo+json", "application/json"})
_OGC_FEATURES_CONFORMANCE_URI_FRAGMENT = "ogcapi-features"
_OGC_COLLECTION_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class OGCAPIFeaturesReleaseContext(_FrozenContract):
    """Immutable control-plane identity for one OGC API Features collection."""

    tenant_id: TenantId
    service_type: GISServiceType
    service_release_binding_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    source_product_urn: str
    source_data_product_version_id: UUID
    collection_id: str = Field(pattern=_OGC_COLLECTION_ID)

    @model_validator(mode="after")
    def _consistent_context(self) -> OGCAPIFeaturesReleaseContext:
        if self.service_type is not GISServiceType.FEATURE:
            raise GISProviderContractError(
                "OGC API Features adapter requires a feature service definition"
            )
        product = parse_resource_urn(self.source_product_urn)
        if product["tenant_id"] != self.tenant_id or product["resource_kind"] != "data_product":
            raise GISProviderContractError(
                "OGC API Features context source_product_urn does not match its tenant"
            )
        return self

    @classmethod
    def from_release(
        cls,
        release: ServiceReleaseBinding,
        definition: GISServiceDefinitionVersion,
        layer: LayerDefinitionVersion,
        *,
        collection_id: str,
    ) -> OGCAPIFeaturesReleaseContext:
        if definition.service_type is not GISServiceType.FEATURE:
            raise GISProviderContractError(
                "OGC API Features release must bind a feature service"
            )
        if (
            release.tenant_id != definition.tenant_id
            or layer.tenant_id != definition.tenant_id
            or release.service_definition_version_id
            != definition.service_definition_version_id
            or release.layer_definition_version_id
            != layer.layer_definition_version_id
            or layer.service_definition_version_id
            != definition.service_definition_version_id
        ):
            raise GISProviderContractError(
                "OGC API Features release components do not share one service lineage"
            )
        if collection_id != layer.layer_key:
            raise GISProviderContractError(
                "OGC API Features collection_id must match the release layer key"
            )
        return cls(
            tenant_id=release.tenant_id,
            service_type=definition.service_type,
            service_release_binding_id=release.service_release_binding_id,
            service_definition_version_id=definition.service_definition_version_id,
            layer_definition_version_id=layer.layer_definition_version_id,
            source_product_urn=definition.source_product_urn,
            source_data_product_version_id=definition.source_data_product_version_id,
            collection_id=collection_id,
        )


class ProviderFeatureResponse:
    """Validated GeoJSON response returned by an OGC API Features provider."""

    def __init__(
        self,
        *,
        content: bytes,
        status_code: int,
        media_type: str,
        feature_count: int,
        payload: dict[str, Any],
        etag: str | None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.media_type = media_type
        self.feature_count = feature_count
        self.payload = payload
        self.etag = etag


def ogc_api_features_conformance_fingerprint(
    value: OGCAPIFeaturesConformanceReceipt | dict[str, Any],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json", by_alias=True, exclude={"receipt_sha256"}
        )
    else:
        payload = {
            key: item for key, item in value.items() if key != "receipt_sha256"
        }
        payload = _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    return canonical_json_fingerprint(payload)


class OGCAPIFeaturesConformanceReceipt(_FrozenContract):
    """One successful exact-release OGC API Features data-plane probe."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, use_enum_values=False, populate_by_name=True
    )
    receipt_schema: Literal["gda.gis_ogc_api_features_conformance.v1"] = Field(
        default="gda.gis_ogc_api_features_conformance.v1", alias="schema"
    )
    provider_system: Literal["pygeoapi"] = "pygeoapi"
    provider_version: str = Field(min_length=1, max_length=128)
    provider_origin_uri: str
    tenant_id: TenantId
    source_product_urn: str
    source_data_product_version_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    service_release_binding_id: UUID
    collection_id: str = Field(pattern=_OGC_COLLECTION_ID)
    health: ProviderHealthObservation
    conformance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_limit: int = Field(ge=1, le=1000)
    requested_bbox: tuple[float, float, float, float] | None = None
    items_status_code: Literal[200]
    items_media_type: str = Field(min_length=1, max_length=256)
    feature_count: int = Field(gt=0, le=1000)
    items_content_bytes: int = Field(gt=0)
    items_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    items_etag: str | None = Field(default=None, max_length=4096)
    observed_at: datetime
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("provider_origin_uri")
    @classmethod
    def _credential_free_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OGC API Features provider origin must be credential-free HTTP(S)")
        return value

    @field_validator("observed_at")
    @classmethod
    def _observed_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("requested_bbox")
    @classmethod
    def _valid_bbox(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        if value is not None and (
            not all(isfinite(item) for item in value)
            or value[0] > value[2]
            or value[1] > value[3]
        ):
            raise ValueError("requested_bbox must be a finite ordered extent")
        return value

    @model_validator(mode="after")
    def _consistent_receipt(self) -> OGCAPIFeaturesConformanceReceipt:
        service = parse_resource_urn(self.source_product_urn)
        if service["tenant_id"] != self.tenant_id or service["resource_kind"] != "data_product":
            raise ValueError("source_product_urn does not match the receipt tenant")
        if self.health.state is not ProviderHealthState.READY:
            raise ValueError("OGC API Features conformance requires ready health")
        if (
            self.health.provider_system != self.provider_system
            or self.health.provider_version != self.provider_version
            or self.health.endpoint_uri != self.provider_origin_uri
        ):
            raise ValueError("OGC API Features health does not match the provider")
        if self.items_media_type not in _OGC_FEATURES_MEDIA_TYPES:
            raise ValueError("OGC API Features receipt media type is not GeoJSON")
        if self.observed_at < self.health.observed_at:
            raise ValueError("OGC API Features conformance cannot precede provider health")
        if self.receipt_sha256 != ogc_api_features_conformance_fingerprint(self):
            raise ValueError("receipt_sha256 does not match OGC API Features conformance")
        return self


class OGCAPIFeaturesProvider:
    """Read-only adapter for a governed OGC API Features provider origin."""

    ACCEPTED_MEDIA_TYPES = _OGC_FEATURES_MEDIA_TYPES

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
                "OGC API Features endpoint must be a credential-free HTTP(S) URI"
            )
        if timeout <= 0:
            raise ValueError("provider timeout must be positive")
        self.endpoint_uri = endpoint_uri.rstrip("/")
        self.manifest = manifest or pygeoapi_provider_manifest()
        if EndpointProtocol.OGC_API_FEATURES not in self.manifest.protocols:
            raise GISProviderContractError(
                "OGC API Features adapter requires an OGC API Features manifest"
            )
        self.timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        options: dict[str, Any] = {"timeout": self.timeout, "trust_env": False}
        if self._transport is not None:
            options["transport"] = self._transport
        return httpx.AsyncClient(**options)

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> tuple[httpx.Response, Any]:
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self.endpoint_uri}{path}",
                    params=params,
                    headers={"Accept": "application/json, application/geo+json"},
                )
        except httpx.HTTPError as exc:
            raise GISProviderUnavailable("OGC API Features request failed") from exc
        if response.status_code >= 500:
            raise GISProviderUnavailable(
                f"OGC API Features request returned HTTP {response.status_code}"
            )
        if response.status_code != 200:
            raise GISProviderContractError(
                f"OGC API Features request returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GISProviderContractError("OGC API Features response was not JSON") from exc
        return response, payload

    async def probe_health(self) -> ProviderHealthObservation:
        observed_at = datetime.now(UTC)
        try:
            async with self._client() as client:
                response = await client.get(self.endpoint_uri)
        except httpx.HTTPError as exc:
            raise GISProviderUnavailable("OGC API Features health request failed") from exc
        powered_by = response.headers.get("x-powered-by", "")
        version_match = re.search(r"\bpygeoapi\s+([^\s;]+)", powered_by, re.IGNORECASE)
        if version_match and version_match.group(1) != self.manifest.provider_version:
            raise GISProviderContractError(
                "OGC API Features provider version header does not match its manifest"
            )
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
        return ProviderHealthObservation(
            **values,
            evidence_sha256=canonical_json_fingerprint(
                ProviderHealthObservation.model_construct(**values).model_dump(mode="json")
            ),
        )

    async def health(self) -> ProviderHealthObservation:
        observation = await self.probe_health()
        if observation.state is ProviderHealthState.FAILED:
            raise GISProviderUnavailable(
                f"OGC API Features health returned HTTP {observation.status_code}"
            )
        return observation

    async def discover_conformance(self) -> dict[str, Any]:
        _, payload = await self._get_json("/conformance")
        if not isinstance(payload, dict) or not isinstance(payload.get("conformsTo"), list):
            raise GISProviderContractError(
                "OGC API Features conformance response must contain conformsTo"
            )
        conforms_to = payload["conformsTo"]
        if not any(
            isinstance(item, str)
            and _OGC_FEATURES_CONFORMANCE_URI_FRAGMENT in item.lower()
            for item in conforms_to
        ):
            raise GISProviderContractError(
                "provider does not advertise OGC API Features conformance"
            )
        return payload

    async def discover_capabilities(self) -> dict[str, Any]:
        _, payload = await self._get_json("/collections")
        if not isinstance(payload, dict) or not isinstance(payload.get("collections"), list):
            raise GISProviderContractError(
                "OGC API Features collections response must contain collections"
            )
        for collection in payload["collections"]:
            if not isinstance(collection, dict) or not isinstance(collection.get("id"), str):
                raise GISProviderContractError(
                    "OGC API Features catalog contains an invalid collection"
                )
        return payload

    @staticmethod
    def _validate_request(
        context: OGCAPIFeaturesReleaseContext,
        *,
        limit: int,
        bbox: tuple[float, float, float, float] | None,
    ) -> None:
        if context.service_type is not GISServiceType.FEATURE:
            raise GISProviderContractError("OGC API Features read requires a feature release")
        if limit < 1 or limit > 1000:
            raise GISProviderContractError("OGC API Features limit must be between 1 and 1000")
        if bbox is not None and (
            len(bbox) != 4
            or not all(isfinite(item) for item in bbox)
            or bbox[0] > bbox[2]
            or bbox[1] > bbox[3]
        ):
            raise GISProviderContractError("OGC API Features bbox must be a finite ordered extent")

    async def fetch_items(
        self,
        context: OGCAPIFeaturesReleaseContext,
        *,
        limit: int = 100,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> ProviderFeatureResponse:
        self._validate_request(context, limit=limit, bbox=bbox)
        # OGC API Features advertises GeoJSON items through ``f=json``; the
        # representation is identified by the response media type.
        params: dict[str, str] = {"f": "json", "limit": str(limit)}
        if bbox is not None:
            params["bbox"] = ",".join(str(item) for item in bbox)
        path = f"/collections/{quote(context.collection_id, safe='')}/items"
        response, payload = await self._get_json(path, params=params)
        media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type not in self.ACCEPTED_MEDIA_TYPES:
            raise GISProviderContractError(
                f"OGC API Features items returned unsupported media type {media_type or '<empty>'}"
            )
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise GISProviderContractError(
                "OGC API Features items must be a GeoJSON FeatureCollection"
            )
        features = payload.get("features")
        if not isinstance(features, list) or len(features) > limit:
            raise GISProviderContractError(
                "OGC API Features response features must be a list within the requested limit"
            )
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise GISProviderContractError("OGC API Features response contains invalid GeoJSON")
            if "geometry" not in feature or (
                feature["geometry"] is not None
                and not isinstance(feature["geometry"], dict)
            ):
                raise GISProviderContractError(
                    "OGC API Features response contains invalid geometry"
                )
            geometry = feature["geometry"]
            if geometry is not None and (
                geometry.get("type") not in {
                    "Point",
                    "MultiPoint",
                    "LineString",
                    "MultiLineString",
                    "Polygon",
                    "MultiPolygon",
                    "GeometryCollection",
                }
                or (
                    geometry.get("type") != "GeometryCollection"
                    and "coordinates" not in geometry
                )
            ):
                raise GISProviderContractError(
                    "OGC API Features response contains invalid geometry type"
                )
            if "properties" in feature and feature["properties"] is not None and not isinstance(
                feature["properties"], dict
            ):
                raise GISProviderContractError(
                    "OGC API Features response contains invalid properties"
                )
        return ProviderFeatureResponse(
            content=response.content,
            status_code=response.status_code,
            media_type=media_type,
            feature_count=len(features),
            payload=payload,
            etag=response.headers.get("etag"),
        )

    async def conform_features_read(
        self,
        context: OGCAPIFeaturesReleaseContext,
        *,
        limit: int = 100,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> OGCAPIFeaturesConformanceReceipt:
        self._validate_request(context, limit=limit, bbox=bbox)
        health = await self.health()
        conformance = await self.discover_conformance()
        catalog = await self.discover_capabilities()
        advertised = {
            item.get("id")
            for item in catalog["collections"]
            if isinstance(item, dict)
        }
        if context.collection_id not in advertised:
            raise GISProviderContractError(
                "OGC API Features catalog does not advertise the governed collection"
            )
        items = await self.fetch_items(context, limit=limit, bbox=bbox)
        if items.status_code != 200 or items.feature_count == 0:
            raise GISProviderContractError(
                "OGC API Features conformance requires a non-empty HTTP 200 FeatureCollection"
            )
        values = {
            "schema": "gda.gis_ogc_api_features_conformance.v1",
            "provider_system": self.manifest.provider_system,
            "provider_version": self.manifest.provider_version,
            "provider_origin_uri": self.endpoint_uri,
            "tenant_id": context.tenant_id,
            "source_product_urn": context.source_product_urn,
            "source_data_product_version_id": context.source_data_product_version_id,
            "service_definition_version_id": context.service_definition_version_id,
            "layer_definition_version_id": context.layer_definition_version_id,
            "service_release_binding_id": context.service_release_binding_id,
            "collection_id": context.collection_id,
            "health": health,
            "conformance_sha256": canonical_json_fingerprint(conformance),
            "catalog_sha256": canonical_json_fingerprint(catalog),
            "requested_limit": limit,
            "requested_bbox": bbox,
            "items_status_code": items.status_code,
            "items_media_type": items.media_type,
            "feature_count": items.feature_count,
            "items_content_bytes": len(items.content),
            "items_content_sha256": hashlib.sha256(items.content).hexdigest(),
            "items_etag": items.etag,
            "observed_at": datetime.now(UTC),
        }
        return OGCAPIFeaturesConformanceReceipt(
            **values,
            receipt_sha256=ogc_api_features_conformance_fingerprint(values),
        )

    def _build_deployment_terminal_observation(
        self,
        context: OGCAPIFeaturesReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        health: ProviderHealthObservation,
        terminal_state: ProviderHealthState,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        provider_receipt: dict[str, Any],
        observed_at: datetime | None,
    ) -> FrameworkAttemptObservation:
        if health.state is not terminal_state:
            raise GISProviderContractError(
                "provider health does not match the deployment terminal state"
            )
        if (
            health.provider_system != self.manifest.provider_system
            or health.provider_version != self.manifest.provider_version
            or health.endpoint_uri != self.endpoint_uri
        ):
            raise GISProviderContractError(
                "provider health does not belong to this OGC API Features adapter"
            )
        if (
            deployment.tenant_id != context.tenant_id
            or deployment.service_definition_version_id != context.service_definition_version_id
            or deployment.service_release_binding_id != context.service_release_binding_id
            or deployment.provider_system != self.manifest.provider_system
        ):
            raise GISProviderContractError(
                "deployment does not match the OGC API Features release context"
            )
        parsed_endpoint = urlsplit(endpoint_uri)
        if (
            parsed_endpoint.scheme != "https"
            or not parsed_endpoint.hostname
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise GISProviderContractError(
                "deployment endpoint must be a credential-free HTTPS URI"
            )
        if not provider_receipt:
            raise GISProviderContractError(
                "deployment terminal evidence requires provider receipt"
            )
        evidence = {
            "schema": "gda.gis_service_deployment_observation.v2",
            "deployment_revision_id": str(deployment.deployment_revision_id),
            "service_definition_version_id": str(deployment.service_definition_version_id),
            "service_release_binding_id": str(deployment.service_release_binding_id),
            "provider_system": deployment.provider_system,
            "provider_version": self.manifest.provider_version,
            "provider_namespace": deployment.provider_namespace,
            "provider_deployment_id": deployment.provider_deployment_id,
            "provider_revision_ref": deployment.provider_revision_ref,
            "config_sha256": deployment.config_sha256,
            "endpoint_uri": endpoint_uri,
            "health_evidence_sha256": health.evidence_sha256,
            "provider_receipt": provider_receipt,
            "release_context": {
                "source_product_urn": context.source_product_urn,
                "source_data_product_version_id": str(context.source_data_product_version_id),
                "layer_definition_version_id": str(context.layer_definition_version_id),
                "collection_id": context.collection_id,
            },
        }
        return FrameworkAttemptObservation(
            tenant_id=deployment.tenant_id,
            observation_id=observation_id,
            run_id=deployment.run_id,
            attempt_no=attempt_no,
            framework_kind=FrameworkKind.CLOUD,
            external_namespace=deployment.provider_namespace,
            external_run_id=deployment.provider_deployment_id,
            external_attempt_id=deployment.provider_revision_ref,
            observed_state=terminal_state.value,
            observation_sha256=canonical_json_fingerprint(evidence),
            evidence=evidence,
            observed_at=observed_at or datetime.now(UTC),
        )

    async def build_deployment_ready_conformance_observation(
        self,
        context: OGCAPIFeaturesReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        limit: int = 100,
        bbox: tuple[float, float, float, float] | None = None,
        observed_at: datetime | None = None,
    ) -> FrameworkAttemptObservation:
        receipt = await self.conform_features_read(context, limit=limit, bbox=bbox)
        occurrence = observed_at or datetime.now(UTC)
        if occurrence < receipt.observed_at:
            raise GISProviderContractError(
                "deployment readiness cannot precede OGC API Features conformance"
            )
        return self._build_deployment_terminal_observation(
            context,
            deployment,
            health=receipt.health,
            terminal_state=ProviderHealthState.READY,
            observation_id=observation_id,
            attempt_no=attempt_no,
            endpoint_uri=endpoint_uri,
            provider_receipt=receipt.model_dump(mode="json", by_alias=True),
            observed_at=occurrence,
        )

    async def build_deployment_failed_observation(
        self,
        context: OGCAPIFeaturesReleaseContext,
        deployment: ServiceDeploymentRevision,
        *,
        observation_id: UUID,
        attempt_no: int,
        endpoint_uri: str,
        provider_receipt: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> FrameworkAttemptObservation:
        health = await self.probe_health()
        return self._build_deployment_terminal_observation(
            context,
            deployment,
            health=health,
            terminal_state=ProviderHealthState.FAILED,
            observation_id=observation_id,
            attempt_no=attempt_no,
            endpoint_uri=endpoint_uri,
            provider_receipt=provider_receipt,
            observed_at=observed_at,
        )
