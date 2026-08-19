"""Typed, preview-first multi-step GIS workflow for governed PostGIS sources."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .gis_analysis_execution import (
    GISAnalysisBudget,
    GISAnalysisExecutionValidationError,
    GISAnalysisPlanner,
    GISAnalysisSource,
)
from .gis_workflow_algorithm_registry import (
    DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY,
    GISWorkflowOperation,
)
from .gis_workflow_proposal import (
    GISWorkflowPlannerEvidence,
    GISWorkflowProposal,
    GISWorkflowProposalStatus,
    apply_gis_workflow_confirmations,
    verify_gis_workflow_proposal_attestation,
)
from .gis_workflow_template_registry import (
    DEFAULT_GIS_WORKFLOW_TEMPLATE_REGISTRY,
    PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID,
    PLANNING_ZONE_LAND_USE_TEMPLATE_ID,
)
from .nl2sql_source_authority import (
    NL2SQLSourceAuthority,
    NL2SQLSourceAuthorityError,
    NL2SQLSourceBinding,
)
from .platform_contracts import (
    ResourceVersion,
    Sha256,
    SubjectContext,
    TenantId,
    canonical_json_fingerprint,
)
from .platform_gateway import (
    PlatformGateway,
    PlatformGatewayError,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SOURCE_NAME = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$"
)


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISWorkflowSourceRole(StrEnum):
    PARCELS = "parcels"
    ECO_REDLINE = "eco_redline"
    ROADS = "roads"
    ADMIN_UNITS = "admin_units"
    PLANNING_ZONES = "planning_zones"


class GISWorkflowRedlineRelation(StrEnum):
    INTERSECTS = "intersects"
    COVERED_BY = "covered_by"


class GISWorkflowAreaBasis(StrEnum):
    CLIPPED_RESULT = "clipped_result"
    ORIGINAL_PARCEL = "original_parcel"


class GISWorkflowRoadDistanceBasis(StrEnum):
    GEOMETRY_BOUNDARY = "geometry_boundary"
    CENTROID = "centroid"


class GISWorkflowFieldOverrides(_FrozenContract):
    parcel_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )
    admin_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )
    admin_name: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )
    land_use_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )
    land_use_name: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )
    zone_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )
    zone_name: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
    )


class GISWorkflowPreviewRequest(_FrozenContract):
    question: str = Field(min_length=8, max_length=2_000)
    proposal: GISWorkflowProposal
    question_sha256: Sha256
    proposal_fingerprint: Sha256
    proposal_attestation: Sha256
    planner_evidence: GISWorkflowPlannerEvidence
    source_names: dict[GISWorkflowSourceRole, str] = Field(default_factory=dict)
    fields: GISWorkflowFieldOverrides = Field(default_factory=GISWorkflowFieldOverrides)
    redline_relation: GISWorkflowRedlineRelation | None = None
    area_basis: GISWorkflowAreaBasis | None = None
    road_distance_basis: GISWorkflowRoadDistanceBasis | None = None
    output_crs: Literal["EPSG:4326"] = "EPSG:4326"
    budget: GISAnalysisBudget = Field(
        default_factory=lambda: GISAnalysisBudget(
            max_features=5_000,
            max_output_bytes=25_000_000,
            max_duration_ms=120_000,
        )
    )

    @field_validator("source_names")
    @classmethod
    def _safe_source_names(
        cls, value: dict[GISWorkflowSourceRole, str]
    ) -> dict[GISWorkflowSourceRole, str]:
        for source_name in value.values():
            if _SOURCE_NAME.fullmatch(source_name) is None:
                raise ValueError("workflow source name is not a governed identifier")
        return value

    @model_validator(mode="after")
    def _exact_proposal(self) -> GISWorkflowPreviewRequest:
        expected = canonical_json_fingerprint(self.proposal.model_dump(mode="json"))
        if self.proposal_fingerprint != expected:
            raise ValueError("workflow proposal fingerprint does not match its contract")
        if self.question_sha256 != hashlib.sha256(
            self.question.encode("utf-8")
        ).hexdigest():
            raise ValueError("workflow proposal is bound to a different question")
        if not verify_gis_workflow_proposal_attestation(
            self.proposal_fingerprint,
            self.question_sha256,
            self.planner_evidence,
            self.proposal_attestation,
        ):
            raise ValueError("workflow proposal attestation is invalid")
        if self.proposal.template_id is not None:
            template = DEFAULT_GIS_WORKFLOW_TEMPLATE_REGISTRY.resolve(
                self.proposal.template_id
            )
            allowed_roles = {
                GISWorkflowSourceRole(role) for role in template.source_roles
            }
            if not set(self.source_names).issubset(allowed_roles):
                raise ValueError("workflow source override is unrelated to its template")
            allowed_fields = {
                field
                for fields in template.required_fields.values()
                for field in fields
            }
            provided_fields = set(self.fields.model_dump(exclude_none=True))
            if not provided_fields.issubset(allowed_fields):
                raise ValueError("workflow field override is unrelated to its template")
        if self.proposal.template_id == PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID:
            if (
                self.redline_relation is None
                or self.area_basis is None
                or self.road_distance_basis is None
            ):
                raise ValueError("parcel workflow requires all spatial confirmations")
        elif any(
            value is not None
            for value in (
                self.redline_relation,
                self.area_basis,
                self.road_distance_basis,
            )
        ):
            raise ValueError("planning-zone workflow does not accept parcel semantics")
        return self


class GISWorkflowExecuteRequest(GISWorkflowPreviewRequest):
    confirmed_plan_fingerprint: Sha256
    confirm_assumptions: Literal[True]


class GISWorkflowIntent(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_intent.v1"] = "gda.gis_workflow_intent.v1"
    template_id: Literal[
        "parcel-redline-road-admin-summary.v1",
        "planning-zone-land-use-summary.v1",
    ]
    distance_meters: float | None = Field(default=None, gt=0, le=1_000_000)
    minimum_area_m2: float | None = Field(default=None, gt=0, le=10**12)
    requested_area_value: float | None = Field(default=None, gt=0)
    requested_area_unit: Literal["mu", "square_meter", "hectare"] | None = None
    group_by: Literal["admin_unit", "planning_zone_land_use"]

    @model_validator(mode="after")
    def _template_parameters(self) -> GISWorkflowIntent:
        values = (
            self.distance_meters,
            self.minimum_area_m2,
            self.requested_area_value,
            self.requested_area_unit,
        )
        if self.template_id == PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID:
            if any(value is None for value in values) or self.group_by != "admin_unit":
                raise ValueError("parcel workflow intent is incomplete")
        elif any(value is not None for value in values) or self.group_by != (
            "planning_zone_land_use"
        ):
            raise ValueError("planning-zone workflow intent contains unrelated parameters")
        return self


class GISWorkflowAlgorithmBinding(_FrozenContract):
    algorithm_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    algorithm_version: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    spec_fingerprint: Sha256
    deterministic: Literal[True] = True
    engine: Literal["postgis"] = "postgis"


class GISWorkflowStep(_FrozenContract):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    title: str = Field(min_length=1, max_length=128)
    operation: Literal[
        "intersection",
        "buffer",
        "spatial_filter",
        "area_filter",
        "spatial_group_by",
        "land_use_spatial_group_by",
    ]
    inputs: tuple[str, ...] = Field(min_length=1)
    algorithm: GISWorkflowAlgorithmBinding
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_semantic_type: str = Field(min_length=1, max_length=128)


class GISWorkflowSourceBinding(_FrozenContract):
    role: GISWorkflowSourceRole
    source: GISAnalysisSource
    available_columns: tuple[str, ...]
    field_bindings: dict[str, str] = Field(default_factory=dict)

    @field_validator("available_columns")
    @classmethod
    def _canonical_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_IDENTIFIER.fullmatch(column) is None for column in value):
            raise ValueError("workflow source column is not a safe identifier")
        return tuple(sorted(set(value), key=str.casefold))


class GISWorkflowPlan(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_plan.v1"] = "gda.gis_workflow_plan.v1"
    tenant_id: TenantId
    question: str = Field(min_length=8, max_length=2_000)
    question_sha256: Sha256
    proposal_fingerprint: Sha256
    proposal_attestation: Sha256
    planner_evidence: GISWorkflowPlannerEvidence
    intent: GISWorkflowIntent
    redline_relation: GISWorkflowRedlineRelation | None = None
    area_basis: GISWorkflowAreaBasis | None = None
    road_distance_basis: GISWorkflowRoadDistanceBasis | None = None
    template_spec_fingerprint: Sha256
    algorithm_registry_fingerprint: Sha256
    output_srid: int = Field(ge=1, le=999_999)
    budget: GISAnalysisBudget
    sources: tuple[GISWorkflowSourceBinding, ...]
    steps: tuple[GISWorkflowStep, ...]
    security_context_fingerprint: Sha256
    planned_at: datetime
    plan_fingerprint: Sha256

    @field_validator("planned_at")
    @classmethod
    def _aware_planned_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("workflow planning time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _exact_plan(self) -> GISWorkflowPlan:
        if self.question_sha256 != hashlib.sha256(
            self.question.encode("utf-8")
        ).hexdigest():
            raise ValueError("workflow plan question fingerprint is invalid")
        if not verify_gis_workflow_proposal_attestation(
            self.proposal_fingerprint,
            self.question_sha256,
            self.planner_evidence,
            self.proposal_attestation,
        ):
            raise ValueError("workflow plan proposal attestation is invalid")
        template = DEFAULT_GIS_WORKFLOW_TEMPLATE_REGISTRY.resolve(
            self.intent.template_id
        )
        if self.template_spec_fingerprint != template.spec_fingerprint:
            raise ValueError("workflow plan template fingerprint is stale")
        confirmations = (
            self.redline_relation,
            self.area_basis,
            self.road_distance_basis,
        )
        if self.intent.template_id == PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID:
            if any(value is None for value in confirmations):
                raise ValueError("parcel workflow plan requires spatial confirmations")
        elif any(value is not None for value in confirmations):
            raise ValueError("planning-zone plan contains unrelated parcel semantics")
        expected_roles = tuple(
            GISWorkflowSourceRole(role) for role in template.source_roles
        )
        roles = tuple(source.role for source in self.sources)
        if roles != expected_roles:
            raise ValueError("workflow plan source roles do not match its template")
        node_ids: list[str] = []
        source_refs = {f"source:{role.value}" for role in expected_roles}
        for step in self.steps:
            if step.node_id in node_ids:
                raise ValueError("workflow node ids must be unique")
            allowed_refs = source_refs | {f"node:{node_id}" for node_id in node_ids}
            if any(reference not in allowed_refs for reference in step.inputs):
                raise ValueError("workflow node references a missing or future input")
            try:
                DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY.require_binding(
                    operation=step.operation,
                    algorithm_id=step.algorithm.algorithm_id,
                    algorithm_version=step.algorithm.algorithm_version,
                    spec_fingerprint=step.algorithm.spec_fingerprint,
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            node_ids.append(step.node_id)
        actual_steps = tuple(
            (
                step.node_id,
                step.operation,
                step.inputs,
                step.output_semantic_type,
            )
            for step in self.steps
        )
        expected_steps = tuple(
            (
                step.node_id,
                step.operation,
                step.inputs,
                step.output_semantic_type,
            )
            for step in template.steps
        )
        if actual_steps != expected_steps:
            raise ValueError("workflow plan steps do not match its registered template")
        if (
            self.algorithm_registry_fingerprint
            != DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY.fingerprint
        ):
            raise ValueError("workflow plan algorithm registry fingerprint is stale")
        expected = canonical_json_fingerprint(
            self.model_dump(
                mode="json", exclude={"plan_fingerprint", "planned_at"}
            )
        )
        if self.plan_fingerprint != expected:
            raise ValueError("workflow plan fingerprint does not match its contract")
        return self

    @classmethod
    def create(cls, **values: Any) -> GISWorkflowPlan:
        provisional = cls.model_construct(**values, plan_fingerprint="0" * 64)
        fingerprint = canonical_json_fingerprint(
            provisional.model_dump(
                mode="json", exclude={"plan_fingerprint", "planned_at"}
            )
        )
        return cls(**values, plan_fingerprint=fingerprint)


class GISWorkflowSourceCandidate(_FrozenContract):
    role: GISWorkflowSourceRole
    semantic_source_name: str
    selected: bool
    match_score: int = Field(ge=0, le=100)
    version_key: str
    resource_version_id: UUID
    geometry_column: str | None = None
    source_crs: str | None = None
    available_columns: tuple[str, ...] = ()


class GISWorkflowBlocker(_FrozenContract):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    message: str = Field(min_length=1, max_length=512)
    role: GISWorkflowSourceRole | None = None
    field: str | None = None


class GISWorkflowAssumption(_FrozenContract):
    assumption_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    label: str = Field(min_length=1, max_length=256)
    selected_value: str = Field(min_length=1, max_length=128)
    consequence: str = Field(min_length=1, max_length=512)


class GISWorkflowPreview(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_preview.v1"] = "gda.gis_workflow_preview.v1"
    status: Literal["ready", "blocked"]
    proposal: GISWorkflowProposal
    proposal_fingerprint: Sha256
    planner_evidence: GISWorkflowPlannerEvidence
    interpreted_intent: GISWorkflowIntent | None = None
    source_candidates: tuple[GISWorkflowSourceCandidate, ...] = ()
    steps: tuple[GISWorkflowStep, ...]
    assumptions: tuple[GISWorkflowAssumption, ...]
    blockers: tuple[GISWorkflowBlocker, ...] = ()
    plan: GISWorkflowPlan | None = None
    plan_fingerprint: Sha256 | None = None
    executable: bool

    @model_validator(mode="after")
    def _consistent_status(self) -> GISWorkflowPreview:
        ready = self.status == "ready"
        if ready != self.executable or ready != (self.plan is not None):
            raise ValueError("workflow preview readiness is inconsistent")
        if ready != (self.plan_fingerprint is not None):
            raise ValueError("ready workflow preview must expose its fingerprint")
        if ready == bool(self.blockers):
            raise ValueError("workflow blockers are inconsistent with readiness")
        return self


class GISWorkflowAdminStatistic(_FrozenContract):
    statistic_type: Literal["admin_unit"] = "admin_unit"
    admin_code: str
    admin_name: str
    parcel_count: int = Field(ge=0)
    area_m2: float = Field(ge=0)
    area_mu: float = Field(ge=0)


class GISWorkflowPlanningZoneLandUseStatistic(_FrozenContract):
    statistic_type: Literal["planning_zone_land_use"] = "planning_zone_land_use"
    zone_code: str
    zone_name: str
    land_use_code: str
    land_use_name: str
    parcel_count: int = Field(ge=0)
    area_m2: float = Field(ge=0)
    area_mu: float = Field(ge=0)


class GISWorkflowExecutionEvidence(_FrozenContract):
    transaction_read_only: Literal[True] = True
    transaction_isolation: Literal["repeatable read"] = "repeatable read"
    plan_fingerprint: Sha256
    source_resource_versions: tuple[UUID, ...]
    algorithm_spec_fingerprints: tuple[Sha256, ...]
    executed_at: datetime
    duration_ms: int = Field(ge=0)
    result_sha256: Sha256


class GISWorkflowExecutionResult(_FrozenContract):
    schema_id: Literal["gda.gis_workflow_result.v1"] = "gda.gis_workflow_result.v1"
    execution_id: UUID
    plan: GISWorkflowPlan
    geojson: dict[str, Any]
    statistics: tuple[
        GISWorkflowAdminStatistic | GISWorkflowPlanningZoneLandUseStatistic, ...
    ]
    summary: dict[str, Any]
    map_update: dict[str, Any]
    evidence: GISWorkflowExecutionEvidence


class GISWorkflowError(RuntimeError):
    code = "gis_workflow_error"


class GISWorkflowValidationError(GISWorkflowError):
    code = "gis_workflow_validation_error"


class GISWorkflowUnavailableError(GISWorkflowError):
    code = "gis_workflow_unavailable"


class GISWorkflowExecutionError(GISWorkflowError):
    code = "gis_workflow_execution_error"


_ROLE_ALIASES: dict[GISWorkflowSourceRole, tuple[str, ...]] = {
    GISWorkflowSourceRole.PARCELS: (
        "parcel", "parcels", "parcel_current", "dltb", "tuban", "地块", "图斑"
    ),
    GISWorkflowSourceRole.ECO_REDLINE: (
        "eco_redline", "redline", "ecological", "生态红线", "生态保护红线"
    ),
    GISWorkflowSourceRole.ROADS: (
        "road", "roads", "highway", "street", "道路", "路网"
    ),
    GISWorkflowSourceRole.ADMIN_UNITS: (
        "admin", "administrative", "district", "county", "xzq", "行政区", "区县"
    ),
    GISWorkflowSourceRole.PLANNING_ZONES: (
        "planning_zone", "planning_zones", "planning", "zone", "规划区", "规划分区"
    ),
}

_FIELD_ALIASES = {
    "parcel_id": ("parcel_id", "tbbh", "bsm", "id"),
    "admin_code": ("admin_code", "xzqdm", "xjxzqdm", "code", "id"),
    "admin_name": ("admin_name", "xzqmc", "xjxzqmc", "name"),
    "land_use_code": ("land_use_code", "dlbm", "landuse_code", "type_code"),
    "land_use_name": ("land_use_name", "dlmc", "landuse_name", "type_name"),
    "zone_code": ("zone_code", "ghfqdm", "planning_zone_code", "code", "id"),
    "zone_name": ("zone_name", "ghfqmc", "planning_zone_name", "name"),
}


def _registered_workflow_binding(
    operation: GISWorkflowOperation,
) -> GISWorkflowAlgorithmBinding:
    algorithm = DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY.resolve(operation)
    return GISWorkflowAlgorithmBinding(
        algorithm_id=algorithm.algorithm_id,
        algorithm_version=algorithm.algorithm_version,
        spec_fingerprint=algorithm.spec_fingerprint,
    )


def _steps(
    intent: GISWorkflowIntent,
    road_distance_basis: GISWorkflowRoadDistanceBasis | None,
) -> tuple[GISWorkflowStep, ...]:
    if intent.template_id == PLANNING_ZONE_LAND_USE_TEMPLATE_ID:
        return (
            GISWorkflowStep(
                node_id="planning_zone_land_use_intersection",
                title="规划区与现状地块叠加",
                operation="intersection",
                inputs=("source:parcels", "source:planning_zones"),
                algorithm=_registered_workflow_binding(
                    GISWorkflowOperation.INTERSECTION
                ),
                output_semantic_type=(
                    "gda.gis.planning_zone_land_use_fragment.v1"
                ),
            ),
            GISWorkflowStep(
                node_id="planning_zone_land_use_summary",
                title="按规划区和用地类型汇总面积",
                operation="land_use_spatial_group_by",
                inputs=("node:planning_zone_land_use_intersection",),
                algorithm=_registered_workflow_binding(
                    GISWorkflowOperation.LAND_USE_SPATIAL_GROUP_BY
                ),
                output_semantic_type=(
                    "gda.gis.planning_zone_land_use_summary.v1"
                ),
            ),
        )
    if road_distance_basis is None:
        raise GISWorkflowValidationError("parcel workflow is missing distance semantics")
    return (
        GISWorkflowStep(
            node_id="redline_intersection",
            title="地块与生态红线空间匹配",
            operation="intersection",
            inputs=("source:parcels", "source:eco_redline"),
            algorithm=_registered_workflow_binding(GISWorkflowOperation.INTERSECTION),
            output_semantic_type="gda.gis.parcel_redline_match.v1",
        ),
        GISWorkflowStep(
            node_id="road_buffer",
            title=f"道路 {intent.distance_meters:g} 米缓冲区",
            operation="buffer",
            inputs=("source:roads",),
            algorithm=_registered_workflow_binding(GISWorkflowOperation.BUFFER),
            parameters={"distance_meters": intent.distance_meters},
            output_semantic_type="gda.gis.road_buffer.v1",
        ),
        GISWorkflowStep(
            node_id="road_proximity_intersection",
            title=(
                "按地块中心点筛选道路邻近地块"
                if road_distance_basis is GISWorkflowRoadDistanceBasis.CENTROID
                else "按地块几何边界筛选道路邻近地块"
            ),
            operation="spatial_filter",
            inputs=("node:redline_intersection", "node:road_buffer"),
            algorithm=_registered_workflow_binding(GISWorkflowOperation.SPATIAL_FILTER),
            parameters={"distance_basis": road_distance_basis.value},
            output_semantic_type="gda.gis.parcel_candidate.v1",
        ),
        GISWorkflowStep(
            node_id="area_filter",
            title=f"面积大于 {intent.minimum_area_m2:g} 平方米",
            operation="area_filter",
            inputs=("node:road_proximity_intersection",),
            algorithm=_registered_workflow_binding(GISWorkflowOperation.AREA_FILTER),
            parameters={"minimum_area_m2": intent.minimum_area_m2},
            output_semantic_type="gda.gis.eligible_parcel.v1",
        ),
        GISWorkflowStep(
            node_id="admin_area_summary",
            title="按行政区分配并汇总面积",
            operation="spatial_group_by",
            inputs=("node:area_filter", "source:admin_units"),
            algorithm=_registered_workflow_binding(GISWorkflowOperation.SPATIAL_GROUP_BY),
            output_semantic_type="gda.gis.admin_area_summary.v1",
        ),
    )


def _assumptions(request: GISWorkflowPreviewRequest) -> tuple[GISWorkflowAssumption, ...]:
    if request.proposal.template_id != PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID:
        return ()
    if (
        request.redline_relation is None
        or request.area_basis is None
        or request.road_distance_basis is None
    ):
        raise GISWorkflowValidationError("parcel workflow confirmations are incomplete")
    relation = (
        ("相交即纳入", "地块与红线存在任何相交部分即进入候选，输出使用相交后的几何。")
        if request.redline_relation is GISWorkflowRedlineRelation.INTERSECTS
        else ("完全位于红线内", "仅纳入几何被红线完全覆盖的地块。")
    )
    area = (
        (
            "按裁剪结果面积",
            "面积门槛针对红线裁剪后的地块几何；道路缓冲区仅作空间筛选，不裁剪地块。",
        )
        if request.area_basis is GISWorkflowAreaBasis.CLIPPED_RESULT
        else ("按原地块面积", "面积门槛针对原始完整地块，地图仍展示条件相交后的部分。")
    )
    road = (
        (
            "按地块几何边界",
            "地块处理后几何的任一部分进入道路缓冲区即视为满足距离条件。",
        )
        if request.road_distance_basis is GISWorkflowRoadDistanceBasis.GEOMETRY_BOUNDARY
        else (
            "按地块中心点",
            "仅当地块处理后几何的中心点进入道路缓冲区时才满足距离条件。",
        )
    )
    return (
        GISWorkflowAssumption(
            assumption_id="redline_relation",
            label="“生态红线内”的空间语义",
            selected_value=request.redline_relation.value,
            consequence=relation[1],
        ),
        GISWorkflowAssumption(
            assumption_id="area_basis",
            label="面积阈值的计算对象",
            selected_value=request.area_basis.value,
            consequence=area[1],
        ),
        GISWorkflowAssumption(
            assumption_id="road_distance_basis",
            label="道路距离的判定对象",
            selected_value=request.road_distance_basis.value,
            consequence=road[1],
        ),
        GISWorkflowAssumption(
            assumption_id="admin_allocation",
            label="跨行政区结果的分配方法",
            selected_value="intersection_area",
            consequence="跨行政区几何按边界切分，各行政区仅统计其境内面积。",
        ),
    )


def _intent_from_proposal(proposal: GISWorkflowProposal) -> GISWorkflowIntent:
    if proposal.status is not GISWorkflowProposalStatus.SUPPORTED:
        raise GISWorkflowValidationError("GIS workflow proposal is not fully resolved")
    if proposal.template_id == PLANNING_ZONE_LAND_USE_TEMPLATE_ID:
        return GISWorkflowIntent(
            template_id=proposal.template_id,
            group_by="planning_zone_land_use",
        )
    if (
        proposal.template_id != PARCEL_REDLINE_ROAD_ADMIN_TEMPLATE_ID
        or proposal.distance is None
        or proposal.minimum_area is None
    ):
        raise GISWorkflowValidationError("GIS workflow proposal is not fully resolved")
    return GISWorkflowIntent(
        template_id=proposal.template_id,
        distance_meters=proposal.distance.meters,
        minimum_area_m2=proposal.minimum_area.square_meters,
        requested_area_value=proposal.minimum_area.value,
        requested_area_unit=proposal.minimum_area.unit,
        group_by="admin_unit",
    )


def _column_names(value: Any, *, parent: str = "") -> set[str]:
    descriptor_keys = {
        "name",
        "column_name",
        "field_name",
        "type",
        "data_type",
        "nullable",
        "description",
    }
    names: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"name", "column_name", "field_name"} and isinstance(item, str):
                if _IDENTIFIER.fullmatch(item):
                    names.add(item)
            if (
                parent in {"columns", "fields", "column_schema", "schema"}
                and key_text not in descriptor_keys
                and _IDENTIFIER.fullmatch(key_text)
            ):
                names.add(key_text)
            names.update(_column_names(item, parent=key_text))
    elif isinstance(value, (list, tuple)):
        for item in value:
            if (
                parent in {"columns", "fields"}
                and isinstance(item, str)
                and _IDENTIFIER.fullmatch(item)
            ):
                names.add(item)
            else:
                names.update(_column_names(item, parent=parent))
    return names


def _source_score(role: GISWorkflowSourceRole, name: str) -> int:
    normalized = name.casefold()
    scores = []
    for alias in _ROLE_ALIASES[role]:
        folded = alias.casefold()
        if normalized == folded:
            scores.append(100)
        elif folded in normalized:
            scores.append(min(95, 60 + len(folded) * 3))
    return max(scores, default=0)


def _field(
    logical_name: str,
    override: str | None,
    columns: tuple[str, ...],
) -> str | None:
    by_folded = {column.casefold(): column for column in columns}
    if override is not None:
        return by_folded.get(override.casefold())
    for alias in _FIELD_ALIASES[logical_name]:
        if alias.casefold() in by_folded:
            return by_folded[alias.casefold()]
    return None


class GISWorkflowPlanner:
    """Discover governed sources and build one confirmable deterministic plan."""

    def __init__(
        self,
        source_authority: NL2SQLSourceAuthority | None = None,
        gateway: PlatformGateway | None = None,
        gis_planner: GISAnalysisPlanner | None = None,
    ):
        self.source_authority = source_authority or NL2SQLSourceAuthority()
        self.gateway = gateway or PlatformGateway()
        self.gis_planner = gis_planner or GISAnalysisPlanner(
            self.source_authority, self.gateway
        )

    def _versions(
        self, subject: SubjectContext
    ) -> tuple[tuple[NL2SQLSourceBinding, ResourceVersion], ...]:
        try:
            bindings = self.source_authority.list_active(subject.tenant_id, "postgis")
            return tuple(
                (
                    binding,
                    self.gateway.get_resource_version(
                        subject.tenant_id, binding.resource_version_id
                    ),
                )
                for binding in bindings
            )
        except (NL2SQLSourceAuthorityError, PlatformGatewayError) as exc:
            raise GISWorkflowUnavailableError(str(exc)) from exc

    def preview(
        self,
        request: GISWorkflowPreviewRequest,
        subject: SubjectContext,
        *,
        planned_at: datetime | None = None,
    ) -> GISWorkflowPreview:
        assumptions = _assumptions(request)
        proposal = apply_gis_workflow_confirmations(
            request.proposal,
            redline_relation=(
                request.redline_relation.value
                if request.redline_relation is not None
                else None
            ),
            area_basis=(
                request.area_basis.value if request.area_basis is not None else None
            ),
            road_distance_basis=(
                request.road_distance_basis.value
                if request.road_distance_basis is not None
                else None
            ),
        )
        if proposal.status is GISWorkflowProposalStatus.UNSUPPORTED:
            return GISWorkflowPreview(
                status="blocked",
                proposal=request.proposal,
                proposal_fingerprint=request.proposal_fingerprint,
                planner_evidence=request.planner_evidence,
                steps=(),
                assumptions=assumptions,
                blockers=(
                    GISWorkflowBlocker(
                        code="gis_workflow_proposal_unsupported",
                        message=proposal.unsupported_reason or "当前需求不受支持",
                    ),
                ),
                executable=False,
            )
        if proposal.status is GISWorkflowProposalStatus.NEEDS_CLARIFICATION:
            return GISWorkflowPreview(
                status="blocked",
                proposal=request.proposal,
                proposal_fingerprint=request.proposal_fingerprint,
                planner_evidence=request.planner_evidence,
                steps=(),
                assumptions=assumptions,
                blockers=tuple(
                    GISWorkflowBlocker(
                        code="gis_workflow_clarification_required",
                        message=item.question,
                    )
                    for item in proposal.clarifications
                ),
                executable=False,
            )
        intent = _intent_from_proposal(proposal)
        workflow_steps = _steps(intent, request.road_distance_basis)
        template = DEFAULT_GIS_WORKFLOW_TEMPLATE_REGISTRY.resolve(intent.template_id)
        required_roles = tuple(
            GISWorkflowSourceRole(role) for role in template.source_roles
        )
        versions = self._versions(subject)
        selected: dict[GISWorkflowSourceRole, tuple[NL2SQLSourceBinding, ResourceVersion]] = {}
        candidates: list[GISWorkflowSourceCandidate] = []
        blockers: list[GISWorkflowBlocker] = []
        for role in required_roles:
            override = request.source_names.get(role)
            ranked = sorted(
                (
                    (
                        (
                        100
                        if binding.semantic_source_name == override
                        else _source_score(role, binding.semantic_source_name)
                        ),
                        binding,
                        version,
                    )
                    for binding, version in versions
                    if override is None or binding.semantic_source_name == override
                ),
                key=lambda item: (-item[0], item[1].semantic_source_name),
            )
            usable = [item for item in ranked if item[0] > 0]
            if not usable:
                blockers.append(
                    GISWorkflowBlocker(
                        code="workflow_source_missing",
                        role=role,
                        message=f"未找到 {role.value} 的活动不可变 PostGIS 数据源",
                    )
                )
                continue
            best_score = usable[0][0]
            best = [item for item in usable if item[0] == best_score]
            if override is None and len(best) > 1:
                blockers.append(
                    GISWorkflowBlocker(
                        code="workflow_source_ambiguous",
                        role=role,
                        message=f"{role.value} 存在多个同等匹配数据源，请明确选择",
                    )
                )
            else:
                selected[role] = (best[0][1], best[0][2])
            for score, binding, version in usable[:5]:
                columns = tuple(
                    sorted(
                        _column_names(version.authority_version_ref),
                        key=str.casefold,
                    )
                )
                geometry = next(
                    (
                        str(value)
                        for key, value in version.authority_version_ref.items()
                        if key in {"geometry_column", "postgis_geometry_column"}
                    ),
                    None,
                )
                candidates.append(
                    GISWorkflowSourceCandidate(
                        role=role,
                        semantic_source_name=binding.semantic_source_name,
                        selected=(
                            role in selected
                            and selected[role][0].binding_id == binding.binding_id
                        ),
                        match_score=score,
                        version_key=binding.version_key,
                        resource_version_id=binding.resource_version_id,
                        geometry_column=geometry,
                        source_crs=(
                            str(
                                version.authority_version_ref.get("crs")
                                or version.authority_version_ref.get("srid")
                                or ""
                            )
                            or None
                        ),
                        available_columns=columns,
                    )
                )
        source_bindings: list[GISWorkflowSourceBinding] = []
        if len(selected) == len(required_roles):
            for role in required_roles:
                binding, version = selected[role]
                try:
                    source = self.gis_planner.resolve_source(
                        binding.semantic_source_name, subject, role="input"
                    )
                except GISAnalysisExecutionValidationError as exc:
                    blockers.append(
                        GISWorkflowBlocker(
                            code="workflow_source_invalid",
                            role=role,
                            message=str(exc),
                        )
                    )
                    continue
                columns = tuple(
                    sorted(
                        _column_names(version.authority_version_ref),
                        key=str.casefold,
                    )
                )
                fields: dict[str, str] = {}
                required = tuple(
                    (logical_name, getattr(request.fields, logical_name))
                    for logical_name in template.required_fields.get(role.value, ())
                )
                for logical_name, override in required:
                    resolved = _field(logical_name, override, columns)
                    if resolved is None:
                        blockers.append(
                            GISWorkflowBlocker(
                                code="workflow_field_missing",
                                role=role,
                                field=logical_name,
                                message=f"{role.value} 缺少可验证的 {logical_name} 字段映射",
                            )
                        )
                    else:
                        fields[logical_name] = resolved
                source_bindings.append(
                    GISWorkflowSourceBinding(
                        role=role,
                        source=source,
                        available_columns=columns,
                        field_bindings=fields,
                    )
                )
        if blockers:
            return GISWorkflowPreview(
                status="blocked",
                proposal=request.proposal,
                proposal_fingerprint=request.proposal_fingerprint,
                planner_evidence=request.planner_evidence,
                interpreted_intent=intent,
                source_candidates=tuple(candidates),
                steps=workflow_steps,
                assumptions=assumptions,
                blockers=tuple(blockers),
                executable=False,
            )
        at = planned_at or datetime.now(UTC)
        plan = GISWorkflowPlan.create(
            tenant_id=subject.tenant_id,
            question=request.question,
            question_sha256=request.question_sha256,
            proposal_fingerprint=request.proposal_fingerprint,
            proposal_attestation=request.proposal_attestation,
            planner_evidence=request.planner_evidence,
            intent=intent,
            redline_relation=request.redline_relation,
            area_basis=request.area_basis,
            road_distance_basis=request.road_distance_basis,
            template_spec_fingerprint=template.spec_fingerprint,
            algorithm_registry_fingerprint=(
                DEFAULT_GIS_WORKFLOW_ALGORITHM_REGISTRY.fingerprint
            ),
            output_srid=int(request.output_crs.split(":", 1)[1]),
            budget=request.budget,
            sources=tuple(source_bindings),
            steps=workflow_steps,
            security_context_fingerprint=canonical_json_fingerprint(
                subject.model_dump(mode="json")
            ),
            planned_at=at,
        )
        return GISWorkflowPreview(
            status="ready",
            proposal=request.proposal,
            proposal_fingerprint=request.proposal_fingerprint,
            planner_evidence=request.planner_evidence,
            interpreted_intent=intent,
            source_candidates=tuple(candidates),
            steps=workflow_steps,
            assumptions=assumptions,
            plan=plan,
            plan_fingerprint=plan.plan_fingerprint,
            executable=True,
        )


class PostGISWorkflowProvider:
    """Compile the fixed workflow template into bounded read-only SQL."""

    def __init__(self, engine: Any, *, statement_timeout_ceiling_ms: int = 300_000):
        if engine is None or engine.dialect.name != "postgresql":
            raise GISWorkflowUnavailableError("GIS workflow execution requires PostgreSQL")
        if not 100 <= statement_timeout_ceiling_ms <= 1_795_000:
            raise GISWorkflowValidationError("workflow timeout ceiling is out of bounds")
        self.engine = engine
        self.statement_timeout_ceiling_ms = statement_timeout_ceiling_ms

    def _quote(self, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise GISWorkflowValidationError(f"unsafe workflow identifier {value!r}")
        return self.engine.dialect.identifier_preparer.quote_identifier(value)

    def _relation(self, value: str) -> str:
        parts = value.split(".")
        if not 1 <= len(parts) <= 2:
            raise GISWorkflowValidationError("workflow relation has too many qualifiers")
        return ".".join(self._quote(part) for part in parts)

    @staticmethod
    def _by_role(
        plan: GISWorkflowPlan,
    ) -> dict[GISWorkflowSourceRole, GISWorkflowSourceBinding]:
        return {binding.role: binding for binding in plan.sources}

    def _source_geometry(self, binding: GISWorkflowSourceBinding, alias: str) -> str:
        source = binding.source
        relation = self._relation(source.physical_relation)
        geometry = self._quote(source.geometry_column)
        return (
            f"SELECT ST_Transform({geometry}, {alias}.output_srid) AS geom "
            f"FROM {relation} AS t CROSS JOIN workflow_parameters AS {alias} "
            f"WHERE {geometry} IS NOT NULL AND NOT ST_IsEmpty({geometry}) "
            f"AND ST_SRID({geometry}) = {source.source_srid}"
        )

    def _parcel_ctes(self, plan: GISWorkflowPlan) -> str:
        bindings = self._by_role(plan)
        parcels = bindings[GISWorkflowSourceRole.PARCELS]
        redline = bindings[GISWorkflowSourceRole.ECO_REDLINE]
        roads = bindings[GISWorkflowSourceRole.ROADS]
        admins = bindings[GISWorkflowSourceRole.ADMIN_UNITS]
        parcel_relation = self._relation(parcels.source.physical_relation)
        parcel_geom = self._quote(parcels.source.geometry_column)
        parcel_id = self._quote(parcels.field_bindings["parcel_id"])
        admin_relation = self._relation(admins.source.physical_relation)
        admin_geom = self._quote(admins.source.geometry_column)
        admin_code = self._quote(admins.field_bindings["admin_code"])
        admin_name = self._quote(admins.field_bindings["admin_name"])
        redline_source = self._source_geometry(redline, "p")
        road_source = self._source_geometry(roads, "p")
        redline_match = (
            "SELECT parcel_id, parcel_geom AS original_geom, "
            "ST_Intersection(parcel_geom, redline_geom) AS geom "
            "FROM parcel_source CROSS JOIN redline_union "
            "WHERE redline_geom IS NOT NULL AND ST_Intersects(parcel_geom, redline_geom)"
            if plan.redline_relation is GISWorkflowRedlineRelation.INTERSECTS
            else
            "SELECT parcel_id, parcel_geom AS original_geom, parcel_geom AS geom "
            "FROM parcel_source CROSS JOIN redline_union "
            "WHERE redline_geom IS NOT NULL AND ST_CoveredBy(parcel_geom, redline_geom)"
        )
        area_geometry = (
            "geom"
            if plan.area_basis is GISWorkflowAreaBasis.CLIPPED_RESULT
            else "original_geom"
        )
        return ", ".join(
            (
                (
                    "workflow_parameters AS (SELECT "
                    "CAST(:output_srid AS integer) AS output_srid)"
                ),
                (
                    f"parcel_source AS (SELECT {parcel_id}::text AS parcel_id, "
                    f"ST_Transform({parcel_geom}, {plan.output_srid}) AS parcel_geom "
                    f"FROM {parcel_relation} WHERE {parcel_geom} IS NOT NULL "
                    f"AND NOT ST_IsEmpty({parcel_geom}) "
                    f"AND ST_SRID({parcel_geom}) = {parcels.source.source_srid})"
                ),
                f"redline_source AS ({redline_source})",
                (
                    "redline_union AS (SELECT ST_UnaryUnion(ST_Collect(geom)) "
                    "AS redline_geom FROM redline_source)"
                ),
                f"redline_match AS ({redline_match})",
                f"road_source AS ({road_source})",
                (
                    "road_buffer AS (SELECT ST_Transform(ST_UnaryUnion(ST_Collect("
                    "ST_Buffer(ST_Transform(geom, 4326)::geography, :distance_meters)::geometry"
                    f")), {plan.output_srid}) AS geom FROM road_source)"
                ),
                (
                    "road_candidates AS (SELECT parcel_id, original_geom, match.geom "
                    "FROM redline_match AS match CROSS JOIN road_buffer AS roads "
                    "WHERE roads.geom IS NOT NULL AND ST_Intersects("
                    + (
                        "ST_PointOnSurface(match.geom)"
                        if plan.road_distance_basis
                        is GISWorkflowRoadDistanceBasis.CENTROID
                        else "match.geom"
                    )
                    + ", roads.geom))"
                ),
                (
                    "eligible AS (SELECT parcel_id, original_geom, geom, "
                    f"ST_Area(ST_Transform({area_geometry}, 4326)::geography) AS measured_area_m2 "
                    "FROM road_candidates WHERE "
                    f"ST_Area(ST_Transform({area_geometry}, 4326)::geography) > :minimum_area_m2)"
                ),
                (
                    f"admin_source AS (SELECT {admin_code}::text AS admin_code, "
                    f"{admin_name}::text AS admin_name, "
                    f"ST_Transform({admin_geom}, {plan.output_srid}) AS geom "
                    f"FROM {admin_relation} WHERE {admin_geom} IS NOT NULL "
                    f"AND NOT ST_IsEmpty({admin_geom}) "
                    f"AND ST_SRID({admin_geom}) = {admins.source.source_srid})"
                ),
                (
                    "allocated AS (SELECT eligible.parcel_id, admin.admin_code, admin.admin_name, "
                    "eligible.measured_area_m2, ST_Intersection(eligible.geom, admin.geom) AS geom "
                    "FROM eligible JOIN admin_source AS admin ON "
                    "ST_Intersects(eligible.geom, admin.geom))"
                ),
                (
                    "non_empty AS (SELECT parcel_id, admin_code, admin_name, "
                    "measured_area_m2, geom, "
                    "ST_Area(ST_Transform(geom, 4326)::geography) AS allocated_area_m2 "
                    "FROM allocated WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom))"
                ),
            )
        )

    def _planning_zone_ctes(self, plan: GISWorkflowPlan) -> str:
        bindings = self._by_role(plan)
        parcels = bindings[GISWorkflowSourceRole.PARCELS]
        zones = bindings[GISWorkflowSourceRole.PLANNING_ZONES]
        parcel_relation = self._relation(parcels.source.physical_relation)
        parcel_geom = self._quote(parcels.source.geometry_column)
        parcel_id = self._quote(parcels.field_bindings["parcel_id"])
        land_use_code = self._quote(parcels.field_bindings["land_use_code"])
        land_use_name = self._quote(parcels.field_bindings["land_use_name"])
        zone_relation = self._relation(zones.source.physical_relation)
        zone_geom = self._quote(zones.source.geometry_column)
        zone_code = self._quote(zones.field_bindings["zone_code"])
        zone_name = self._quote(zones.field_bindings["zone_name"])
        return ", ".join(
            (
                (
                    "workflow_parameters AS (SELECT "
                    "CAST(:output_srid AS integer) AS output_srid)"
                ),
                (
                    f"parcel_source AS (SELECT {parcel_id}::text AS parcel_id, "
                    f"{land_use_code}::text AS land_use_code, "
                    f"{land_use_name}::text AS land_use_name, "
                    f"ST_Transform({parcel_geom}, {plan.output_srid}) AS geom "
                    f"FROM {parcel_relation} WHERE {parcel_geom} IS NOT NULL "
                    f"AND NOT ST_IsEmpty({parcel_geom}) "
                    f"AND ST_SRID({parcel_geom}) = {parcels.source.source_srid})"
                ),
                (
                    f"planning_zone_source AS (SELECT {zone_code}::text AS zone_code, "
                    f"{zone_name}::text AS zone_name, "
                    f"ST_Transform({zone_geom}, {plan.output_srid}) AS geom "
                    f"FROM {zone_relation} WHERE {zone_geom} IS NOT NULL "
                    f"AND NOT ST_IsEmpty({zone_geom}) "
                    f"AND ST_SRID({zone_geom}) = {zones.source.source_srid})"
                ),
                (
                    "intersections AS (SELECT zone.zone_code, zone.zone_name, "
                    "parcel.parcel_id, parcel.land_use_code, parcel.land_use_name, "
                    "ST_Intersection(parcel.geom, zone.geom) AS geom "
                    "FROM parcel_source AS parcel JOIN planning_zone_source AS zone "
                    "ON ST_Intersects(parcel.geom, zone.geom))"
                ),
                (
                    "non_empty AS (SELECT zone_code, zone_name, parcel_id, "
                    "land_use_code, land_use_name, geom, "
                    "ST_Area(ST_Transform(geom, 4326)::geography) AS area_m2 "
                    "FROM intersections WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom))"
                ),
            )
        )

    def _queries(self, plan: GISWorkflowPlan) -> tuple[str, str, dict[str, Any]]:
        if plan.intent.template_id == PLANNING_ZONE_LAND_USE_TEMPLATE_ID:
            ctes = self._planning_zone_ctes(plan)
            result_sql = (
                f"WITH {ctes} SELECT zone_code, zone_name, parcel_id, land_use_code, "
                "land_use_name, area_m2, ST_AsGeoJSON(geom, 9, 0) AS geometry_json "
                "FROM non_empty ORDER BY zone_code, land_use_code, parcel_id "
                f"LIMIT {plan.budget.max_features + 1}"
            )
            statistics_sql = (
                f"WITH {ctes} SELECT zone_code, zone_name, land_use_code, land_use_name, "
                "COUNT(DISTINCT parcel_id)::bigint AS parcel_count, "
                "COALESCE(SUM(area_m2), 0)::double precision AS area_m2 "
                "FROM non_empty GROUP BY zone_code, zone_name, land_use_code, "
                "land_use_name ORDER BY area_m2 DESC, zone_code, land_use_code"
            )
            return result_sql, statistics_sql, {"output_srid": plan.output_srid}
        ctes = self._parcel_ctes(plan)
        result_sql = (
            f"WITH {ctes} SELECT parcel_id, admin_code, admin_name, measured_area_m2, "
            "allocated_area_m2, ST_AsGeoJSON(geom, 9, 0) AS geometry_json "
            "FROM non_empty ORDER BY admin_code, parcel_id "
            f"LIMIT {plan.budget.max_features + 1}"
        )
        statistics_sql = (
            f"WITH {ctes} SELECT admin_code, admin_name, COUNT(DISTINCT parcel_id)::bigint "
            "AS parcel_count, COALESCE(SUM(allocated_area_m2), 0)::double precision AS area_m2 "
            "FROM non_empty GROUP BY admin_code, admin_name ORDER BY area_m2 DESC, admin_code"
        )
        parameters = {
            "output_srid": plan.output_srid,
            "distance_meters": plan.intent.distance_meters,
            "minimum_area_m2": plan.intent.minimum_area_m2,
        }
        return result_sql, statistics_sql, parameters

    def execute(self, plan: GISWorkflowPlan) -> GISWorkflowExecutionResult:
        started = time.monotonic()
        result_sql, statistics_sql, parameters = self._queries(plan)
        timeout_ms = min(plan.budget.max_duration_ms, self.statement_timeout_ceiling_ms)
        try:
            with self.engine.connect() as connection, connection.begin():
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{timeout_ms}ms"},
                )
                read_only = connection.execute(text("SHOW transaction_read_only")).scalar_one()
                isolation = connection.execute(text("SHOW transaction_isolation")).scalar_one()
                rows = connection.execute(text(result_sql), parameters).mappings().all()
                statistic_rows = (
                    connection.execute(text(statistics_sql), parameters)
                    .mappings()
                    .all()
                )
        except DBAPIError as exc:
            raise GISWorkflowExecutionError(
                "PostGIS 未能完成已确认的空间工作流"
            ) from exc
        except SQLAlchemyError as exc:
            raise GISWorkflowUnavailableError("PostGIS 工作流执行通道不可用") from exc
        if read_only != "on" or isolation != "repeatable read":
            raise GISWorkflowExecutionError("工作流未在规定的只读一致性事务中执行")
        if len(rows) > plan.budget.max_features:
            raise GISWorkflowExecutionError("工作流结果超过已确认的要素数量预算")
        planning_zone_workflow = (
            plan.intent.template_id == PLANNING_ZONE_LAND_USE_TEMPLATE_ID
        )
        if planning_zone_workflow:
            features = tuple(
                {
                    "type": "Feature",
                    "geometry": json.loads(row["geometry_json"]),
                    "properties": {
                        "parcel_id": str(row["parcel_id"]),
                        "zone_code": str(row["zone_code"]),
                        "zone_name": str(row["zone_name"]),
                        "land_use_code": str(row["land_use_code"]),
                        "land_use_name": str(row["land_use_name"]),
                        "area_m2": round(float(row["area_m2"]), 3),
                    },
                }
                for row in rows
            )
        else:
            features = tuple(
                {
                    "type": "Feature",
                    "geometry": json.loads(row["geometry_json"]),
                    "properties": {
                        "parcel_id": str(row["parcel_id"]),
                        "admin_code": str(row["admin_code"]),
                        "admin_name": str(row["admin_name"]),
                        "measured_area_m2": round(
                            float(row["measured_area_m2"]), 3
                        ),
                        "allocated_area_m2": round(
                            float(row["allocated_area_m2"]), 3
                        ),
                    },
                }
                for row in rows
            )
        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "gda": {
                "schema": "gda.gis_workflow_geojson.v1",
                "plan_fingerprint": plan.plan_fingerprint,
                "output_crs": f"EPSG:{plan.output_srid}",
            },
        }
        if planning_zone_workflow:
            statistics = tuple(
                GISWorkflowPlanningZoneLandUseStatistic(
                    zone_code=str(row["zone_code"]),
                    zone_name=str(row["zone_name"]),
                    land_use_code=str(row["land_use_code"]),
                    land_use_name=str(row["land_use_name"]),
                    parcel_count=int(row["parcel_count"]),
                    area_m2=round(float(row["area_m2"]), 3),
                    area_mu=round(float(row["area_m2"]) * 3 / 2_000, 3),
                )
                for row in statistic_rows
            )
        else:
            statistics = tuple(
                GISWorkflowAdminStatistic(
                    admin_code=str(row["admin_code"]),
                    admin_name=str(row["admin_name"]),
                    parcel_count=int(row["parcel_count"]),
                    area_m2=round(float(row["area_m2"]), 3),
                    area_mu=round(float(row["area_m2"]) * 3 / 2_000, 3),
                )
                for row in statistic_rows
            )
        parcel_count = len(
            {feature["properties"]["parcel_id"] for feature in features}
        )
        total_area_m2 = round(sum(item.area_m2 for item in statistics), 3)
        total_area_mu = round(sum(item.area_mu for item in statistics), 3)
        if planning_zone_workflow:
            zone_count = len({item.zone_code for item in statistics})
            land_use_count = len({item.land_use_code for item in statistics})
            summary = {
                "intersection_fragment_count": len(features),
                "parcel_count": parcel_count,
                "planning_zone_count": zone_count,
                "land_use_category_count": land_use_count,
                "total_intersection_area_m2": total_area_m2,
                "total_intersection_area_mu": total_area_mu,
                "conclusion": (
                    f"共叠加 {parcel_count} 宗现状地块，覆盖 {zone_count} 个规划区、"
                    f"{land_use_count} 类现状用地。"
                ),
            }
            map_title = "规划区现状用地叠加统计"
            layer_name = "规划区现状用地叠加结果"
            layer_style = {
                "color": "#155e75",
                "weight": 2,
                "opacity": 0.9,
                "fillColor": "#22c55e",
                "fillOpacity": 0.35,
            }
        else:
            summary = {
                "eligible_fragment_count": len(features),
                "eligible_parcel_count": parcel_count,
                "admin_unit_count": len(statistics),
                "total_allocated_area_m2": total_area_m2,
                "total_allocated_area_mu": total_area_mu,
                "conclusion": (
                    f"共识别 {parcel_count} 宗符合条件的地块，"
                    f"分布于 {len(statistics)} 个行政区。"
                ),
            }
            map_title = "生态红线与道路邻近地块分析"
            layer_name = "符合条件的地块"
            layer_style = {
                "color": "#b91c1c",
                "weight": 2,
                "opacity": 0.9,
                "fillColor": "#f59e0b",
                "fillOpacity": 0.35,
            }
        map_update = {
            "schema": "map_update.v1",
            "summary": {"title": map_title},
            "layers": [
                {
                    "name": layer_name,
                    "type": "geojson",
                    "geojsonData": geojson,
                    "style": layer_style,
                }
            ],
            "metadata": {
                "plan_fingerprint": plan.plan_fingerprint,
                "evidence_only": False,
            },
        }
        payload = json.dumps(
            {
                "geojson": geojson,
                "statistics": [
                    item.model_dump(mode="json") for item in statistics
                ],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > plan.budget.max_output_bytes:
            raise GISWorkflowExecutionError("工作流结果超过已确认的输出大小预算")
        duration_ms = max(0, round((time.monotonic() - started) * 1_000))
        if duration_ms > plan.budget.max_duration_ms:
            raise GISWorkflowExecutionError("工作流超过已确认的执行时间预算")
        execution_id = uuid5(
            NAMESPACE_URL,
            f"gda:gis-workflow:{plan.tenant_id}:{plan.plan_fingerprint}",
        )
        executed_at = datetime.now(UTC)
        return GISWorkflowExecutionResult(
            execution_id=execution_id,
            plan=plan,
            geojson=geojson,
            statistics=statistics,
            summary=summary,
            map_update=map_update,
            evidence=GISWorkflowExecutionEvidence(
                plan_fingerprint=plan.plan_fingerprint,
                source_resource_versions=tuple(
                    binding.source.resource_version_id for binding in plan.sources
                ),
                algorithm_spec_fingerprints=tuple(
                    step.algorithm.spec_fingerprint for step in plan.steps
                ),
                executed_at=executed_at,
                duration_ms=duration_ms,
                result_sha256=hashlib.sha256(payload).hexdigest(),
            ),
        )


__all__ = [
    "GISWorkflowAreaBasis",
    "GISWorkflowError",
    "GISWorkflowExecuteRequest",
    "GISWorkflowExecutionError",
    "GISWorkflowExecutionResult",
    "GISWorkflowPlan",
    "GISWorkflowPlanner",
    "GISWorkflowPreview",
    "GISWorkflowPreviewRequest",
    "GISWorkflowRedlineRelation",
    "GISWorkflowRoadDistanceBasis",
    "GISWorkflowSourceRole",
    "GISWorkflowUnavailableError",
    "GISWorkflowValidationError",
    "PostGISWorkflowProvider",
]
