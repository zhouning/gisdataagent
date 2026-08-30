"""Typed contracts for the minimal GIS service control-plane authority."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Literal
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

from .platform_contracts import (
    FrameworkAttemptObservation,
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)


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


def service_deployment_terminal_state(
    observed_state: str,
) -> ServiceDeploymentState:
    """Map a provider terminal observation into the deployment state machine."""
    normalized = observed_state.strip().lower()
    if normalized in {"success", "succeeded", "ready", "completed"}:
        return ServiceDeploymentState.READY
    if normalized in {"failed", "error", "cancelled", "timed_out"}:
        return ServiceDeploymentState.FAILED
    raise ValueError("provider observation is not a GIS deployment terminal state")


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


class CacheKeyDimension(StrEnum):
    """Stable dimensions used to partition a private MVT response."""

    TENANT = "tenant"
    SERVICE_RELEASE = "service_release"
    PRINCIPAL = "principal"
    TILE = "tile"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class GISServiceSLOBinding(_FrozenContract):
    """Immutable projection binding one GIS service to an exact active SLO."""

    tenant_id: TenantId
    binding_id: UUID
    service_urn: ResourceURNText
    slo_definition_ref: ResourceURNText
    active_version_ref: ResourceURNText
    definition_fingerprint: Sha256
    approval_case_ref: ResourceURNText
    activation_version: int = Field(ge=1)
    bound_by: str = Field(min_length=1, max_length=512)
    binding_reason: str = Field(min_length=1, max_length=512)
    bound_at: datetime

    @field_validator("bound_at")
    @classmethod
    def _bound_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_slo_binding(self) -> GISServiceSLOBinding:
        service = parse_resource_urn(self.service_urn)
        definition = parse_resource_urn(self.slo_definition_ref)
        version = parse_resource_urn(self.active_version_ref)
        approval = parse_resource_urn(self.approval_case_ref)
        if (
            service["tenant_id"] != self.tenant_id
            or service["resource_kind"] != "gis_service"
        ):
            raise ValueError("service_urn must identify a tenant GIS service")
        if (
            definition["tenant_id"] != self.tenant_id
            or definition["resource_kind"] != "slo_definition"
        ):
            raise ValueError("slo_definition_ref must identify a tenant SLO definition")
        if (
            version["tenant_id"] != self.tenant_id
            or version["resource_kind"] != "slo_definition"
        ):
            raise ValueError("active_version_ref must identify a tenant SLO version")
        if not self.active_version_ref.startswith(f"{self.slo_definition_ref}.v"):
            raise ValueError("active_version_ref must bind the SLO definition")
        if (
            approval["tenant_id"] != self.tenant_id
            or approval["resource_kind"] != "approval_case"
        ):
            raise ValueError("approval_case_ref must identify a tenant ApprovalCase")
        if not re.fullmatch(r"^(human|workload|agent):[^\s]{1,128}$", self.bound_by):
            raise ValueError("bound_by must use a typed subject")
        return self


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


class CachePolicyVersion(_FrozenContract):
    """Immutable, service-bound policy for short-lived private tile caching."""

    tenant_id: TenantId
    cache_policy_version_id: UUID
    service_definition_version_id: UUID
    cache_policy_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    cache_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    cache_max_age_seconds: int = Field(ge=1, le=300)
    cache_key_dimensions: tuple[CacheKeyDimension, ...]
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _cache_policy_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_cache_policy(self) -> CachePolicyVersion:
        if self.predecessor_version_id == self.cache_policy_version_id:
            raise ValueError("a cache policy cannot be its own predecessor")
        required_dimensions = set(CacheKeyDimension)
        if (
            len(self.cache_key_dimensions) != len(required_dimensions)
            or set(self.cache_key_dimensions) != required_dimensions
        ):
            raise ValueError(
                "cache_key_dimensions must exactly partition tenant, service release, "
                "principal, and tile"
            )
        if self.policy_sha256 != cache_policy_version_fingerprint(self):
            raise ValueError("policy_sha256 does not match the cache policy")
        return self


def cache_policy_version_fingerprint(
    value: CachePolicyVersion | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {"predecessor_version_id": None, **value}
    return _fingerprint(value, "policy_sha256")


class ServicePolicyBinding(_FrozenContract):
    """Immutable, release-bound Gateway authorization rule for GIS reads.

    This is intentionally a narrow execution policy, not a generic ABAC
    language. It declares the complete decision that the governed GIS read
    routes can enforce today: protocol action, admitted roles and which of
    those roles need a version-compatible ConsumerBinding.
    """

    tenant_id: TenantId
    service_policy_binding_id: UUID
    service_definition_version_id: UUID
    service_release_binding_id: UUID
    policy_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    action: Literal["mvt.read", "ogc_features.read"] = "mvt.read"
    enforcement_point: Literal["gateway"] = "gateway"
    allowed_roles: tuple[str, ...] = Field(min_length=1, max_length=16)
    consumer_binding_required_roles: tuple[str, ...] = Field(
        default=(), max_length=16
    )
    required_consumer_operation: Literal["read"] = "read"
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _service_policy_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("allowed_roles", "consumer_binding_required_roles")
    @classmethod
    def _canonical_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("service policy roles must not repeat")
        for role in value:
            if not isinstance(role, str) or not role or not re.fullmatch(
                r"[a-z0-9][a-z0-9._-]{0,127}", role
            ):
                raise ValueError("service policy roles must be canonical identifiers")
        return value

    @model_validator(mode="after")
    def _consistent_service_policy(self) -> ServicePolicyBinding:
        if self.predecessor_version_id == self.service_policy_binding_id:
            raise ValueError("a service policy cannot be its own predecessor")
        if not set(self.consumer_binding_required_roles).issubset(self.allowed_roles):
            raise ValueError(
                "consumer_binding_required_roles must be included in allowed_roles"
            )
        if self.policy_sha256 != service_policy_binding_fingerprint(self):
            raise ValueError("policy_sha256 does not match the service policy binding")
        return self


def service_policy_binding_fingerprint(
    value: ServicePolicyBinding | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {
            "predecessor_version_id": None,
            "action": "mvt.read",
            "enforcement_point": "gateway",
            "consumer_binding_required_roles": (),
            "required_consumer_operation": "read",
            **value,
        }
    return _fingerprint(value, "policy_sha256")


class MVTServingProjectionVersion(_FrozenContract):
    """Immutable Martin/PostGIS source projection for one vector-tile layer.

    The projection is deliberately a concrete serving contract.  Martin gets
    only this identifier and resolves the source table, attribute allowlist,
    source-CRS clip, and tile feature limit inside PostGIS.
    """

    tenant_id: TenantId
    mvt_serving_projection_version_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    projection_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    version_key: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    predecessor_version_id: UUID | None = None
    source_output_resource_version_id: UUID
    source_schema: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    source_table: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    geometry_column: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    geometry_srid: int = Field(gt=0)
    feature_id_column: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    property_allowlist: tuple[str, ...] = Field(default=(), max_length=16)
    allowed_spatial_extent: tuple[float, float, float, float]
    max_features_per_tile: int = Field(ge=100, le=100_000)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _projection_created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("allowed_spatial_extent")
    @classmethod
    def _projection_extent(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return _validate_extent(value)

    @field_validator("property_allowlist")
    @classmethod
    def _projection_properties(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("MVT serving projection properties must not repeat")
        for property_name in value:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,62}", property_name):
                raise ValueError("MVT serving projection properties must be identifiers")
        return value

    @model_validator(mode="after")
    def _consistent_projection(self) -> MVTServingProjectionVersion:
        if self.predecessor_version_id == self.mvt_serving_projection_version_id:
            raise ValueError("an MVT serving projection cannot be its own predecessor")
        if self.feature_id_column in self.property_allowlist:
            raise ValueError("MVT serving properties cannot repeat the feature ID")
        if self.projection_sha256 != mvt_serving_projection_fingerprint(self):
            raise ValueError("projection_sha256 does not match the MVT serving projection")
        return self


def mvt_serving_projection_fingerprint(
    value: MVTServingProjectionVersion | dict[str, Any],
) -> str:
    if isinstance(value, dict):
        value = {"predecessor_version_id": None, "property_allowlist": (), **value}
    return _fingerprint(value, "projection_sha256")


class MVTServingRelationAttestation(_FrozenContract):
    """Immutable catalog observation for one physical MVT source relation."""

    tenant_id: TenantId
    mvt_serving_projection_version_id: UUID
    source_schema: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    source_table: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    relation_oid: int = Field(gt=0)
    relation_kind: str = Field(pattern=r"^[rvmfp]$")
    geometry_column: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    geometry_type: str = Field(min_length=1, max_length=64)
    geometry_srid: int = Field(gt=0)
    geometry_dimensions: int = Field(ge=2, le=4)
    feature_id_column: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")
    feature_id_data_type: str = Field(min_length=1, max_length=256)
    property_columns: tuple[str, ...] = Field(max_length=16)
    property_column_types: tuple[str, ...] = Field(max_length=16)
    relation_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attested_by: str = Field(min_length=1, max_length=512)
    attested_at: datetime

    @field_validator("attested_at")
    @classmethod
    def _attestation_time_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("property_columns")
    @classmethod
    def _property_columns_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("MVT relation property columns must not repeat")
        for column in value:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,62}", column):
                raise ValueError("MVT relation property columns must be identifiers")
        return value

    @model_validator(mode="after")
    def _property_column_types_match(self) -> MVTServingRelationAttestation:
        if len(self.property_columns) != len(self.property_column_types):
            raise ValueError("MVT relation property names and types must align")
        return self


class ServiceReleaseBinding(_FrozenContract):
    tenant_id: TenantId
    service_release_binding_id: UUID
    service_definition_version_id: UUID
    layer_definition_version_id: UUID
    style_definition_version_id: UUID
    tile_matrix_set_definition_version_id: UUID | None = None
    cache_policy_version_id: UUID | None = None
    mvt_serving_projection_version_id: UUID | None = None
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
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={"binding_sha256"})
    else:
        payload = {
            "tile_matrix_set_definition_version_id": None,
            "cache_policy_version_id": None,
            "mvt_serving_projection_version_id": None,
            **value,
        }
        payload.pop("binding_sha256", None)
    # Migration 203 adds this nullable column to immutable historical rows.
    # Omit it for NULL rows so their pre-migration release fingerprints remain
    # valid and only an actual policy binding changes release identity.
    if payload.get("cache_policy_version_id") is None:
        payload.pop("cache_policy_version_id", None)
    if payload.get("mvt_serving_projection_version_id") is None:
        payload.pop("mvt_serving_projection_version_id", None)
    return canonical_json_fingerprint(
        _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    )


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


class ServiceDeploymentEvent(_FrozenContract):
    """One immutable transition in a GIS deployment revision timeline."""

    tenant_id: TenantId
    event_id: UUID
    deployment_revision_id: UUID
    sequence_no: int = Field(ge=0)
    from_state: ServiceDeploymentState | None = None
    to_state: ServiceDeploymentState
    provider_observation_id: UUID | None = None
    actor_subject: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2048)
    idempotency_key: str = Field(min_length=1, max_length=512)
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def _event_occurred_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _consistent_transition(self) -> ServiceDeploymentEvent:
        if self.sequence_no == 0:
            if (
                self.from_state is not None
                or self.to_state is not ServiceDeploymentState.PLANNED
                or self.provider_observation_id is not None
            ):
                raise ValueError("initial deployment event must record planned state")
            return self
        if self.from_state is None:
            raise ValueError("deployment transition event requires from_state")
        if not (
            (
                self.from_state is ServiceDeploymentState.PLANNED
                and self.to_state is ServiceDeploymentState.DEPLOYING
            )
            or (
                self.from_state is ServiceDeploymentState.DEPLOYING
                and self.to_state
                in {ServiceDeploymentState.READY, ServiceDeploymentState.FAILED}
            )
        ):
            raise ValueError("deployment event has an invalid state transition")
        terminal = self.to_state in {
            ServiceDeploymentState.READY,
            ServiceDeploymentState.FAILED,
        }
        if terminal != (self.provider_observation_id is not None):
            raise ValueError("terminal deployment event must bind provider observation")
        return self


class GISServiceDeploymentTerminalSettlement(_FrozenContract):
    """One atomic terminal provider observation and deployment state settlement."""

    tenant_id: TenantId
    deployment: ServiceDeploymentRevision
    observation: FrameworkAttemptObservation
    observation_created: bool

    @model_validator(mode="after")
    def _consistent_settlement(self) -> GISServiceDeploymentTerminalSettlement:
        expected_state = service_deployment_terminal_state(self.observation.observed_state)
        if self.deployment.tenant_id != self.tenant_id:
            raise ValueError("settled deployment tenant must match")
        if self.observation.tenant_id != self.tenant_id:
            raise ValueError("settled observation tenant must match")
        if self.observation.run_id != self.deployment.run_id:
            raise ValueError("settled observation must bind the deployment Run")
        if self.deployment.state is not expected_state:
            raise ValueError("settled deployment state must match provider observation")
        if self.deployment.terminal_observation_id != self.observation.observation_id:
            raise ValueError("settled deployment must bind the terminal observation")
        return self


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
    active_cache_policy_version: CachePolicyVersion | None = None
    active_service_policy_binding: ServicePolicyBinding | None = None
    active_mvt_serving_projection_version: MVTServingProjectionVersion | None = None
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
                    or self.active_cache_policy_version is not None
                    or self.active_service_policy_binding is not None
                    or self.active_mvt_serving_projection_version is not None
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
                cache_policy = self.active_cache_policy_version
                if (cache_policy is None) != (release.cache_policy_version_id is None):
                    raise ValueError("active cache policy projection does not match")
                if cache_policy is not None and (
                    cache_policy.cache_policy_version_id
                    != release.cache_policy_version_id
                    or cache_policy.service_definition_version_id
                    != self.active_service_definition_version.service_definition_version_id
                ):
                    raise ValueError("active cache policy does not match the release")
                service_policy = self.active_service_policy_binding
                if service_policy is not None and (
                    service_policy.service_definition_version_id
                    != self.active_service_definition_version.service_definition_version_id
                    or service_policy.service_release_binding_id
                    != release.service_release_binding_id
                ):
                    raise ValueError("active service policy does not match the release")
                serving_projection = self.active_mvt_serving_projection_version
                if (serving_projection is None) != (
                    release.mvt_serving_projection_version_id is None
                ):
                    raise ValueError("active MVT serving projection does not match")
                if serving_projection is not None and (
                    serving_projection.mvt_serving_projection_version_id
                    != release.mvt_serving_projection_version_id
                    or serving_projection.service_definition_version_id
                    != self.active_service_definition_version.service_definition_version_id
                    or serving_projection.layer_definition_version_id
                    != self.active_layer_definition_version.layer_definition_version_id
                ):
                    raise ValueError("active MVT serving projection does not match release")
        return self
