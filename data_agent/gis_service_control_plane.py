"""Typed contracts for the minimal GIS service control-plane authority."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from .platform_contracts import TenantId, canonical_json_fingerprint, parse_resource_urn


class GISServiceType(StrEnum):
    FEATURE = "feature"
    MAP = "map"
    VECTOR_TILE = "vector_tile"
    COVERAGE = "coverage"


class ServiceDeploymentState(StrEnum):
    PLANNED = "planned"
    DEPLOYING = "deploying"
    READY = "ready"
    FAILED = "failed"


class EndpointProtocol(StrEnum):
    ARCGIS_REST = "arcgis_rest"
    OGC_API_FEATURES = "ogc_api_features"
    WMS = "wms"
    WMTS = "wmts"
    MVT = "mvt"


class LayerGeometryType(StrEnum):
    GEOMETRY = "geometry"
    POINT = "point"
    MULTIPOINT = "multipoint"
    LINESTRING = "linestring"
    MULTILINESTRING = "multilinestring"
    POLYGON = "polygon"
    MULTIPOLYGON = "multipolygon"
    GEOMETRYCOLLECTION = "geometrycollection"


class StyleFormat(StrEnum):
    MAPBOX_STYLE = "mapbox_style"
    SLD = "sld"
    QML = "qml"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


_JSON_VALUE_ADAPTER = TypeAdapter(Any)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _fingerprint(value: BaseModel | dict[str, Any], field_name: str) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={field_name})
    else:
        payload = {key: item for key, item in value.items() if key != field_name}
    return canonical_json_fingerprint(
        _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    )


class GISServiceDefinitionVersion(_FrozenContract):
    tenant_id: TenantId
    service_definition_version_id: UUID
    service_urn: str
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    platform_definition_version_id: UUID
    source_product_urn: str
    source_data_product_version_id: UUID
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_type: GISServiceType
    service_contract: dict[str, Any]
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_definition(self) -> GISServiceDefinitionVersion:
        service = parse_resource_urn(self.service_urn)
        product = parse_resource_urn(self.source_product_urn)
        if service["tenant_id"] != self.tenant_id or service["resource_kind"] != "gis_service":
            raise ValueError("service_urn must identify a tenant GIS service Resource")
        if product["tenant_id"] != self.tenant_id or product["resource_kind"] != "data_product":
            raise ValueError("source_product_urn must identify a tenant DataProduct")
        if self.predecessor_version_id == self.service_definition_version_id:
            raise ValueError("a service definition cannot be its own predecessor")
        if not self.service_contract:
            raise ValueError("service_contract must not be empty")
        if self.definition_sha256 != gis_service_definition_fingerprint(self):
            raise ValueError("definition_sha256 does not match the service definition")
        return self


def gis_service_definition_fingerprint(
    value: GISServiceDefinitionVersion | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {"predecessor_version_id": None, **value}
    return _fingerprint(value, "definition_sha256")


def _validate_extent(
    value: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if not all(isfinite(coordinate) for coordinate in value):
        raise ValueError("spatial extent coordinates must be finite")
    if value[0] > value[2] or value[1] > value[3]:
        raise ValueError("spatial extent minimums cannot exceed maximums")
    return value


class LayerDefinitionVersion(_FrozenContract):
    tenant_id: TenantId
    layer_definition_version_id: UUID
    service_definition_version_id: UUID
    layer_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    source_output_resource_version_id: UUID
    geometry_type: LayerGeometryType
    geometry_column: str = Field(min_length=1, max_length=128)
    schema_contract: dict[str, Any]
    crs_uri: str = Field(min_length=1, max_length=512)
    spatial_extent: tuple[float, float, float, float]
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _layer_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("spatial_extent")
    @classmethod
    def _layer_extent(cls, value: tuple[float, float, float, float]):
        return _validate_extent(value)

    @model_validator(mode="after")
    def _consistent_layer(self) -> LayerDefinitionVersion:
        if self.predecessor_version_id == self.layer_definition_version_id:
            raise ValueError("a layer definition cannot be its own predecessor")
        if not self.schema_contract:
            raise ValueError("schema_contract must not be empty")
        if self.definition_sha256 != layer_definition_fingerprint(self):
            raise ValueError("definition_sha256 does not match the layer definition")
        return self


def layer_definition_fingerprint(
    value: LayerDefinitionVersion | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {"predecessor_version_id": None, **value}
    return _fingerprint(value, "definition_sha256")


class StyleDefinitionVersion(_FrozenContract):
    tenant_id: TenantId
    style_definition_version_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    style_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    style_format: StyleFormat
    style_document: dict[str, Any]
    style_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _style_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_style(self) -> StyleDefinitionVersion:
        if self.predecessor_version_id == self.style_definition_version_id:
            raise ValueError("a style definition cannot be its own predecessor")
        if not self.style_document:
            raise ValueError("style_document must not be empty")
        if self.style_sha256 != style_definition_fingerprint(self):
            raise ValueError("style_sha256 does not match the style definition")
        return self


def style_definition_fingerprint(
    value: StyleDefinitionVersion | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {"predecessor_version_id": None, **value}
    return _fingerprint(value, "style_sha256")


class TileMatrixSetDefinitionVersion(_FrozenContract):
    tenant_id: TenantId
    tile_matrix_set_definition_version_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID | None = None
    tile_matrix_set_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    crs_uri: str = Field(min_length=1, max_length=512)
    tile_width: int = Field(gt=0, le=8192)
    tile_height: int = Field(gt=0, le=8192)
    min_zoom: int = Field(ge=0, le=30)
    max_zoom: int = Field(ge=0, le=30)
    scale_denominators: tuple[float, ...]
    spatial_extent: tuple[float, float, float, float]
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tile_matrix_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("spatial_extent")
    @classmethod
    def _tile_matrix_extent(cls, value: tuple[float, float, float, float]):
        return _validate_extent(value)

    @model_validator(mode="after")
    def _consistent_tile_matrix_set(self) -> TileMatrixSetDefinitionVersion:
        if self.predecessor_version_id == self.tile_matrix_set_definition_version_id:
            raise ValueError("a tile matrix set cannot be its own predecessor")
        if self.max_zoom < self.min_zoom:
            raise ValueError("max_zoom cannot precede min_zoom")
        if len(self.scale_denominators) != self.max_zoom - self.min_zoom + 1:
            raise ValueError("scale_denominators must cover every admitted zoom")
        if any(not isfinite(scale) or scale <= 0 for scale in self.scale_denominators):
            raise ValueError("scale denominators must be finite and positive")
        if any(
            current <= following
            for current, following in zip(
                self.scale_denominators, self.scale_denominators[1:], strict=False
            )
        ):
            raise ValueError("scale denominators must strictly decrease with zoom")
        if self.definition_sha256 != tile_matrix_set_definition_fingerprint(self):
            raise ValueError(
                "definition_sha256 does not match the tile matrix set definition"
            )
        return self


def tile_matrix_set_definition_fingerprint(
    value: TileMatrixSetDefinitionVersion | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {
            "layer_definition_version_id": None,
            "predecessor_version_id": None,
            **value,
        }
    return _fingerprint(value, "definition_sha256")


class ServiceReleaseBinding(_FrozenContract):
    tenant_id: TenantId
    service_release_binding_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    style_definition_version_id: UUID
    tile_matrix_set_definition_version_id: UUID | None = None
    release_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _release_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_release(self) -> ServiceReleaseBinding:
        if self.binding_sha256 != service_release_binding_fingerprint(self):
            raise ValueError("binding_sha256 does not match the service release binding")
        return self


def service_release_binding_fingerprint(
    value: ServiceReleaseBinding | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {"tile_matrix_set_definition_version_id": None, **value}
    return _fingerprint(value, "binding_sha256")


class ServiceDeploymentRevision(_FrozenContract):
    tenant_id: TenantId
    deployment_revision_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID | None = None
    run_id: UUID
    revision_key: str = Field(pattern=r"^r[0-9]+$")
    provider_system: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
    provider_namespace: str = Field(min_length=1, max_length=512)
    provider_deployment_id: str = Field(min_length=1, max_length=512)
    provider_revision_ref: str = Field(min_length=1, max_length=512)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: ServiceDeploymentState = ServiceDeploymentState.PLANNED
    state_version: int = Field(default=0, ge=0)
    terminal_observation_id: UUID | None = None
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None = None

    @field_validator("created_at", "updated_at", "terminal_at")
    @classmethod
    def _timestamps_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def _consistent_deployment(self) -> ServiceDeploymentRevision:
        terminal = self.state in {
            ServiceDeploymentState.READY,
            ServiceDeploymentState.FAILED,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("terminal deployment state must bind terminal_at")
        if terminal != (self.terminal_observation_id is not None):
            raise ValueError("terminal deployment state must bind provider observation")
        if self.state == ServiceDeploymentState.PLANNED and self.state_version != 0:
            raise ValueError("planned deployment must use state version zero")
        if self.updated_at < self.created_at:
            raise ValueError("deployment updated_at cannot precede created_at")
        if self.deployment_sha256 != service_deployment_fingerprint(self):
            raise ValueError("deployment_sha256 does not match the immutable revision")
        return self


def service_deployment_fingerprint(
    value: ServiceDeploymentRevision | dict[str, Any],
) -> str:
    excluded = {
        "deployment_sha256",
        "state",
        "state_version",
        "terminal_observation_id",
        "updated_at",
        "terminal_at",
    }
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude=excluded)
    else:
        payload = {key: item for key, item in value.items() if key not in excluded}
    if payload.get("service_release_binding_id") is None:
        payload.pop("service_release_binding_id", None)
    return canonical_json_fingerprint(
        _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    )


class EndpointRevision(_FrozenContract):
    tenant_id: TenantId
    endpoint_revision_id: UUID
    service_urn: str
    deployment_revision_id: UUID
    endpoint_protocol: EndpointProtocol
    endpoint_uri: str = Field(min_length=1, max_length=2048)
    endpoint_contract: dict[str, Any]
    endpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _endpoint_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("endpoint_uri")
    @classmethod
    def _stable_endpoint_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint_uri must be a stable credential-free HTTPS URI")
        return value

    @model_validator(mode="after")
    def _consistent_endpoint(self) -> EndpointRevision:
        service = parse_resource_urn(self.service_urn)
        if service["tenant_id"] != self.tenant_id or service["resource_kind"] != "gis_service":
            raise ValueError("service_urn must identify a tenant GIS service Resource")
        if not self.endpoint_contract:
            raise ValueError("endpoint_contract must not be empty")
        if self.endpoint_sha256 != endpoint_revision_fingerprint(self):
            raise ValueError("endpoint_sha256 does not match the endpoint revision")
        return self


def endpoint_revision_fingerprint(value: EndpointRevision | dict[str, Any]) -> str:
    return _fingerprint(value, "endpoint_sha256")


class GISServiceControlProjection(_FrozenContract):
    tenant_id: TenantId
    service_urn: str
    endpoint_state_version: int = Field(ge=0)
    active_endpoint_revision: EndpointRevision | None = None
    active_deployment_revision: ServiceDeploymentRevision | None = None
    active_service_definition_version: GISServiceDefinitionVersion | None = None
    active_release_binding: ServiceReleaseBinding | None = None
    active_layer_definition_version: LayerDefinitionVersion | None = None
    active_style_definition_version: StyleDefinitionVersion | None = None
    active_tile_matrix_set_definition_version: (
        TileMatrixSetDefinitionVersion | None
    ) = None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _projection_timestamps_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_projection(self) -> GISServiceControlProjection:
        present = (
            self.active_endpoint_revision is not None,
            self.active_deployment_revision is not None,
            self.active_service_definition_version is not None,
        )
        if len(set(present)) != 1:
            raise ValueError("active service projection must be complete or empty")
        if self.active_endpoint_revision is not None:
            if self.active_endpoint_revision.service_urn != self.service_urn:
                raise ValueError("active endpoint belongs to a different service")
            if (
                self.active_endpoint_revision.deployment_revision_id
                != self.active_deployment_revision.deployment_revision_id
            ):
                raise ValueError("active endpoint and deployment revisions do not match")
            if (
                self.active_deployment_revision.service_definition_version_id
                != self.active_service_definition_version.service_definition_version_id
            ):
                raise ValueError("active deployment and definition versions do not match")
            release_id = self.active_deployment_revision.service_release_binding_id
            release_components = (
                self.active_release_binding,
                self.active_layer_definition_version,
                self.active_style_definition_version,
            )
            if release_id is None:
                if any(component is not None for component in release_components) or (
                    self.active_tile_matrix_set_definition_version is not None
                ):
                    raise ValueError("legacy deployment cannot expose release components")
            elif any(component is None for component in release_components):
                raise ValueError("active release projection must be complete")
            else:
                release = self.active_release_binding
                if release.service_release_binding_id != release_id:
                    raise ValueError("active deployment and release binding do not match")
                if (
                    release.service_definition_version_id
                    != self.active_service_definition_version.service_definition_version_id
                    or release.layer_definition_version_id
                    != self.active_layer_definition_version.layer_definition_version_id
                    or release.style_definition_version_id
                    != self.active_style_definition_version.style_definition_version_id
                ):
                    raise ValueError("active release components do not match")
                tile_matrix = self.active_tile_matrix_set_definition_version
                if (tile_matrix is None) != (
                    release.tile_matrix_set_definition_version_id is None
                ):
                    raise ValueError("active tile matrix set projection does not match")
                if tile_matrix is not None and (
                    tile_matrix.tile_matrix_set_definition_version_id
                    != release.tile_matrix_set_definition_version_id
                ):
                    raise ValueError("active tile matrix set definition does not match")
        return self
