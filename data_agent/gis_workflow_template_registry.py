"""Versioned production templates allowed in governed GIS workflow plans."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .platform_contracts import Sha256, canonical_json_fingerprint


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISWorkflowTemplateStepSpec(_FrozenContract):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    title: str = Field(min_length=1, max_length=128)
    operation: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    inputs: tuple[str, ...] = Field(min_length=1)
    output_semantic_type: str = Field(min_length=1, max_length=128)


class GISWorkflowTemplateSpec(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_template_spec.v1"] = (
        "gda.gis_workflow_template_spec.v1"
    )
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    engine: Literal["postgis"] = "postgis"
    read_only: Literal[True] = True
    source_roles: tuple[str, ...] = Field(min_length=1)
    required_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    clarification_ids: tuple[str, ...] = ()
    steps: tuple[GISWorkflowTemplateStepSpec, ...] = Field(min_length=1)
    spec_fingerprint: Sha256

    @model_validator(mode="after")
    def _exact_template(self) -> GISWorkflowTemplateSpec:
        if len(set(self.source_roles)) != len(self.source_roles):
            raise ValueError("workflow template source roles must be unique")
        if not set(self.required_fields).issubset(self.source_roles):
            raise ValueError("workflow template fields reference an unknown source role")
        node_ids: list[str] = []
        source_refs = {f"source:{role}" for role in self.source_roles}
        for step in self.steps:
            if step.node_id in node_ids:
                raise ValueError("workflow template node ids must be unique")
            allowed_refs = source_refs | {f"node:{node_id}" for node_id in node_ids}
            if any(reference not in allowed_refs for reference in step.inputs):
                raise ValueError("workflow template step references a missing input")
            node_ids.append(step.node_id)
        expected = canonical_json_fingerprint(
            self.model_dump(mode="json", exclude={"spec_fingerprint"})
        )
        if self.spec_fingerprint != expected:
            raise ValueError("GIS workflow template fingerprint is invalid")
        return self

    @classmethod
    def release(cls, **values: object) -> GISWorkflowTemplateSpec:
        provisional = cls.model_construct(**values, spec_fingerprint="0" * 64)
        fingerprint = canonical_json_fingerprint(
            provisional.model_dump(mode="json", exclude={"spec_fingerprint"})
        )
        return cls(**values, spec_fingerprint=fingerprint)


class GISWorkflowTemplateCatalog(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_template_catalog.v1"] = (
        "gda.gis_workflow_template_catalog.v1"
    )
    registry_fingerprint: Sha256
    templates: tuple[GISWorkflowTemplateSpec, ...]


class GISWorkflowTemplateRegistry:
    def __init__(self, specs: Iterable[GISWorkflowTemplateSpec]):
        releases = tuple(specs)
        by_id = {spec.template_id: spec for spec in releases}
        if len(by_id) != len(releases) or not releases:
            raise ValueError("GIS workflow template ids must be unique")
        self._releases = tuple(sorted(releases, key=lambda item: item.template_id))
        self._by_id = by_id
        self.fingerprint = canonical_json_fingerprint(
            [spec.model_dump(mode="json") for spec in self._releases]
        )

    def resolve(self, template_id: str) -> GISWorkflowTemplateSpec:
        try:
            return self._by_id[template_id]
        except KeyError as exc:
            raise ValueError("GIS workflow template is not registered") from exc

    def catalog(self) -> GISWorkflowTemplateCatalog:
        return GISWorkflowTemplateCatalog(
            registry_fingerprint=self.fingerprint,
            templates=self._releases,
        )

    @property
    def templates(self) -> tuple[GISWorkflowTemplateSpec, ...]:
        return self._releases


PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID = "parcel-redline-road-admin-summary.v1"
PLANNING_ZONE_LAND_USE_TEMPLATE_ID = "planning-zone-land-use-summary.v1"


DEFAULT_GIS_WORKFLOW_TEMPLATE_REGISTRY = GISWorkflowTemplateRegistry(
    (
        GISWorkflowTemplateSpec.release(
            template_id=PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID,
            title="生态红线道路邻近地块分析",
            description="按红线关系、道路距离和面积门槛筛选地块，并按行政区统计。",
            source_roles=("parcels", "eco_redline", "roads", "admin_units"),
            required_fields={
                "parcels": ("parcel_id",),
                "admin_units": ("admin_code", "admin_name"),
            },
            clarification_ids=(
                "redline_relation",
                "area_basis",
                "road_distance_basis",
            ),
            steps=(
                GISWorkflowTemplateStepSpec(
                    node_id="redline_intersection",
                    title="地块与生态红线空间匹配",
                    operation="intersection",
                    inputs=("source:parcels", "source:eco_redline"),
                    output_semantic_type="gda.gis.parcel_redline_match.v1",
                ),
                GISWorkflowTemplateStepSpec(
                    node_id="road_buffer",
                    title="道路缓冲区",
                    operation="buffer",
                    inputs=("source:roads",),
                    output_semantic_type="gda.gis.road_buffer.v1",
                ),
                GISWorkflowTemplateStepSpec(
                    node_id="road_proximity_intersection",
                    title="道路邻近空间筛选",
                    operation="spatial_filter",
                    inputs=("node:redline_intersection", "node:road_buffer"),
                    output_semantic_type="gda.gis.parcel_candidate.v1",
                ),
                GISWorkflowTemplateStepSpec(
                    node_id="area_filter",
                    title="地块面积门槛筛选",
                    operation="area_filter",
                    inputs=("node:road_proximity_intersection",),
                    output_semantic_type="gda.gis.eligible_parcel.v1",
                ),
                GISWorkflowTemplateStepSpec(
                    node_id="admin_area_summary",
                    title="按行政区分配并汇总面积",
                    operation="spatial_group_by",
                    inputs=("node:area_filter", "source:admin_units"),
                    output_semantic_type="gda.gis.admin_area_summary.v1",
                ),
            ),
        ),
        GISWorkflowTemplateSpec.release(
            template_id=PLANNING_ZONE_LAND_USE_TEMPLATE_ID,
            title="规划区现状用地叠加统计",
            description="叠加规划区与现状地块，按规划区和现状用地类型统计面积。",
            source_roles=("parcels", "planning_zones"),
            required_fields={
                "parcels": ("parcel_id", "land_use_code", "land_use_name"),
                "planning_zones": ("zone_code", "zone_name"),
            },
            steps=(
                GISWorkflowTemplateStepSpec(
                    node_id="planning_zone_land_use_intersection",
                    title="规划区与现状地块叠加",
                    operation="intersection",
                    inputs=("source:parcels", "source:planning_zones"),
                    output_semantic_type="gda.gis.planning_zone_land_use_fragment.v1",
                ),
                GISWorkflowTemplateStepSpec(
                    node_id="planning_zone_land_use_summary",
                    title="按规划区和用地类型汇总面积",
                    operation="land_use_spatial_group_by",
                    inputs=("node:planning_zone_land_use_intersection",),
                    output_semantic_type="gda.gis.planning_zone_land_use_summary.v1",
                ),
            ),
        ),
    )
)


__all__ = [
    "DEFAULT_GIS_WORKFLOW_TEMPLATE_REGISTRY",
    "GISWorkflowTemplateCatalog",
    "GISWorkflowTemplateRegistry",
    "GISWorkflowTemplateSpec",
    "GISWorkflowTemplateStepSpec",
    "PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID",
    "PLANNING_ZONE_LAND_USE_TEMPLATE_ID",
]
