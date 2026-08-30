"""Typed bridge from a JQDLTB DataProductVersion to GIS serving authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .gis_service_control_plane import (
    GISServiceDefinitionVersion,
    GISServiceSLOBinding,
    LayerDefinitionVersion,
    MVTServingProjectionVersion,
    ServiceReleaseBinding,
)
from .platform_contracts import TenantId, canonical_json_fingerprint

JQDLTB_SERVING_RELEASE_SCHEMA = "gda.jqdltb_serving_release_binding.v1"
_JSON_VALUE_ADAPTER = TypeAdapter(Any)


class JqdltbServingReleaseBinding(BaseModel):
    """Immutable identity of one product version and one serving release.

    The nested control-plane contracts are retained in the plan only so the
    caller can validate the complete chain before persisting this compact
    binding.  The registry stores their IDs and fingerprints in JSONB.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_name: str = Field(default=JQDLTB_SERVING_RELEASE_SCHEMA, alias="schema")
    tenant_id: TenantId
    product_urn: str
    data_product_version_id: UUID
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_resource_version_id: UUID
    service: GISServiceDefinitionVersion
    layer: LayerDefinitionVersion
    projection: MVTServingProjectionVersion
    release: ServiceReleaseBinding
    slo: GISServiceSLOBinding
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bound_by: str = Field(min_length=1, max_length=512)
    bound_at: datetime

    @model_validator(mode="after")
    def _consistent_binding(self) -> JqdltbServingReleaseBinding:
        if self.schema_name != JQDLTB_SERVING_RELEASE_SCHEMA:
            raise ValueError("unsupported JQDLTB serving release schema")
        if self.service.tenant_id != self.tenant_id:
            raise ValueError("serving service tenant differs from product tenant")
        if self.product_urn != self.service.source_product_urn:
            raise ValueError("serving service product differs from JQDLTB product")
        if self.service.source_data_product_version_id != self.data_product_version_id:
            raise ValueError("GIS service must bind the exact DataProductVersion")
        if self.service.source_manifest_sha256 != self.manifest_sha256:
            raise ValueError("GIS service manifest hash differs from DataProductVersion")
        if self.layer.tenant_id != self.tenant_id:
            raise ValueError("serving layer tenant differs from product tenant")
        if self.layer.service_definition_version_id != self.service.service_definition_version_id:
            raise ValueError("serving layer belongs to another service definition")
        if self.layer.source_output_resource_version_id != self.output_resource_version_id:
            raise ValueError("serving layer must bind the JQDLTB ADS output")
        if self.projection.tenant_id != self.tenant_id:
            raise ValueError("MVT projection tenant differs from product tenant")
        if (
            self.projection.service_definition_version_id
            != self.service.service_definition_version_id
            or self.projection.layer_definition_version_id
            != self.layer.layer_definition_version_id
            or self.projection.source_output_resource_version_id
            != self.output_resource_version_id
        ):
            raise ValueError("MVT projection does not bind the exact service layer/output")
        if self.release.tenant_id != self.tenant_id:
            raise ValueError("service release tenant differs from product tenant")
        if (
            self.release.service_definition_version_id
            != self.service.service_definition_version_id
            or self.release.layer_definition_version_id
            != self.layer.layer_definition_version_id
            or self.release.mvt_serving_projection_version_id
            != self.projection.mvt_serving_projection_version_id
        ):
            raise ValueError("service release does not bind the exact MVT projection")
        if self.slo.tenant_id != self.tenant_id or self.slo.service_urn != self.service.service_urn:
            raise ValueError("ServiceSLO binding does not belong to the serving service")
        if self.binding_sha256 != jqdltb_serving_release_fingerprint(self):
            raise ValueError("binding_sha256 does not match serving release evidence")
        if self.bound_at.tzinfo is None or self.bound_at.utcoffset() is None:
            raise ValueError("bound_at must include a timezone")
        return self


def jqdltb_serving_release_fingerprint(
    value: JqdltbServingReleaseBinding | dict[str, Any],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(
            mode="json", by_alias=True, exclude={"binding_sha256"}
        )
    else:
        payload = {key: item for key, item in value.items() if key != "binding_sha256"}
        payload = _JSON_VALUE_ADAPTER.dump_python(payload, mode="json")
    # The product manifest carries this binding fingerprint, while the GIS
    # definition carries the resulting manifest fingerprint.  Keep those
    # two immutable identities acyclic by fingerprinting the serving IDs and
    # contracts, not the repeated manifest/definition content hashes.
    service = payload.get("service")
    if isinstance(service, dict):
        service = dict(service)
        service.pop("source_manifest_sha256", None)
        service.pop("definition_sha256", None)
        payload["service"] = service
    return canonical_json_fingerprint(payload)


def build_jqdltb_serving_release_binding(
    *,
    tenant_id: TenantId,
    product_urn: str,
    data_product_version_id: UUID,
    manifest_sha256: str,
    output_resource_version_id: UUID,
    service: GISServiceDefinitionVersion,
    layer: LayerDefinitionVersion,
    projection: MVTServingProjectionVersion,
    release: ServiceReleaseBinding,
    slo: GISServiceSLOBinding,
    bound_by: str,
    bound_at: datetime,
) -> JqdltbServingReleaseBinding:
    values: dict[str, Any] = {
        "schema": JQDLTB_SERVING_RELEASE_SCHEMA,
        "tenant_id": tenant_id,
        "product_urn": product_urn,
        "data_product_version_id": data_product_version_id,
        "manifest_sha256": manifest_sha256,
        "output_resource_version_id": output_resource_version_id,
        "service": service,
        "layer": layer,
        "projection": projection,
        "release": release,
        "slo": slo,
        "bound_by": bound_by,
        "bound_at": bound_at.astimezone(UTC),
    }
    return JqdltbServingReleaseBinding.model_validate(
        values | {"binding_sha256": jqdltb_serving_release_fingerprint(values)}
    )


__all__ = [
    "JQDLTB_SERVING_RELEASE_SCHEMA",
    "JqdltbServingReleaseBinding",
    "build_jqdltb_serving_release_binding",
    "jqdltb_serving_release_fingerprint",
]
