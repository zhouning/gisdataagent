"""Read-only lineage graph contracts for the platform control ledger."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .platform_contracts import (
    LineageEvent,
    QualityResult,
    ResourceVersion,
    TenantId,
    canonical_json_fingerprint,
)


class LineageDirection(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    BOTH = "both"


class LineageTruncationReason(StrEnum):
    DEPTH_LIMIT = "depth_limit"
    EDGE_LIMIT = "edge_limit"


class ImpactChangeType(StrEnum):
    CONTENT = "content"
    SCHEMA = "schema"
    CRS = "crs"
    GEOMETRY = "geometry"
    TEMPORAL = "temporal"
    QUALITY = "quality"
    POLICY = "policy"
    CLASSIFICATION = "classification"
    DEPRECATION = "deprecation"


class ImpactDisposition(StrEnum):
    NO_RECORDED_DOWNSTREAM_IMPACT = "no_recorded_downstream_impact"
    REVIEW_REQUIRED = "review_required"
    QUALITY_ATTENTION_REQUIRED = "quality_attention_required"


class ImpactReviewReason(StrEnum):
    CHANGE_TYPE_REQUIRES_REVIEW = "change_type_requires_review"
    DOWNSTREAM_LINEAGE_PRESENT = "downstream_lineage_present"
    CURRENT_DATA_PRODUCT_AFFECTED = "current_data_product_affected"
    FAILED_QUALITY_EVIDENCE = "failed_quality_evidence"


class LineageQuerySpec(BaseModel):
    """Bounded traversal requested by an authenticated platform operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: LineageDirection = LineageDirection.BOTH
    max_depth: int = Field(default=6, ge=1, le=12)
    max_edges: int = Field(default=500, ge=1, le=1000)
    require_complete: bool = False


class LineageGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_version: ResourceVersion
    min_depth: int = Field(ge=0)
    is_root: bool = False


class LineageGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: LineageEvent
    depth: int = Field(ge=1)
    traversal_from_resource_version_id: UUID
    traversal_to_resource_version_id: UUID

    @model_validator(mode="after")
    def _traversal_follows_event(self) -> LineageGraphEdge:
        endpoints = {
            self.event.source_resource_version_id,
            self.event.target_resource_version_id,
        }
        if {
            self.traversal_from_resource_version_id,
            self.traversal_to_resource_version_id,
        } != endpoints:
            raise ValueError("lineage traversal endpoints must match the event endpoints")
        return self


class LineageGraph(BaseModel):
    """A bounded, deterministic projection over immutable LineageEvents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["gda.lineage_graph.v1"] = "gda.lineage_graph.v1"
    tenant_id: TenantId
    root_resource_version_id: UUID
    direction: LineageDirection
    requested_max_depth: int = Field(ge=1, le=12)
    requested_max_edges: int = Field(ge=1, le=1000)
    reached_depth: int = Field(ge=0)
    complete: bool
    truncation_reasons: tuple[LineageTruncationReason, ...] = ()
    nodes: tuple[LineageGraphNode, ...]
    edges: tuple[LineageGraphEdge, ...]
    node_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent_graph(self) -> LineageGraph:
        node_ids = [node.resource_version.resource_version_id for node in self.nodes]
        edge_ids = [edge.event.lineage_event_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("lineage graph nodes must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("lineage graph edges must be unique")
        if self.node_count != len(self.nodes) or self.edge_count != len(self.edges):
            raise ValueError("lineage graph counts must match its payload")
        if self.complete != (not self.truncation_reasons):
            raise ValueError("lineage graph completeness must match truncation reasons")
        roots = [
            node
            for node in self.nodes
            if node.resource_version.resource_version_id == self.root_resource_version_id
        ]
        if (
            len(roots) != 1
            or sum(node.is_root for node in self.nodes) != 1
            or not roots[0].is_root
            or roots[0].min_depth != 0
        ):
            raise ValueError("lineage graph must contain exactly one depth-zero root")
        node_id_set = set(node_ids)
        for node in self.nodes:
            if node.resource_version.tenant_id != self.tenant_id:
                raise ValueError("lineage graph nodes must belong to its tenant")
        for edge in self.edges:
            if edge.event.tenant_id != self.tenant_id:
                raise ValueError("lineage graph edges must belong to its tenant")
            if edge.depth > self.requested_max_depth:
                raise ValueError("lineage graph edge exceeds requested depth")
            if {
                edge.event.source_resource_version_id,
                edge.event.target_resource_version_id,
            } - node_id_set:
                raise ValueError("lineage graph edge references a missing node")
        expected_depth = max((edge.depth for edge in self.edges), default=0)
        if self.reached_depth != expected_depth:
            raise ValueError("lineage graph reached depth must match its edges")
        return self


class ImpactedDataProduct(BaseModel):
    """Current DataProductVersion whose source or output is in the impact set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    product_urn: str
    product_slug: str
    title: str
    domain: str
    owner_ref: str
    governance_ref: dict[str, Any]
    data_product_version_id: UUID
    version_key: str
    source_resource_version_id: UUID
    output_resource_version_id: UUID
    quality_verdict: Literal["passed"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: datetime
    matched_resource_version_ids: tuple[UUID, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _matched_versions_belong_to_product_version(self) -> ImpactedDataProduct:
        allowed = {
            self.source_resource_version_id,
            self.output_resource_version_id,
        }
        if set(self.matched_resource_version_ids) - allowed:
            raise ValueError("matched resource versions must belong to the product version")
        if len(self.matched_resource_version_ids) != len(set(self.matched_resource_version_ids)):
            raise ValueError("matched resource versions must be unique")
        return self


class ImpactQualitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: QualityResult
    resource_min_depth: int = Field(ge=0)


def lineage_impact_fingerprint(
    *,
    tenant_id: str,
    root_resource_version: ResourceVersion,
    change_type: ImpactChangeType | str,
    lineage: LineageGraph,
    impacted_data_products: tuple[ImpactedDataProduct, ...],
    quality_signals: tuple[ImpactQualitySignal, ...],
    disposition: ImpactDisposition | str,
    review_reasons: tuple[ImpactReviewReason | str, ...],
) -> str:
    """Bind an impact verdict to the exact immutable evidence it evaluated."""

    return canonical_json_fingerprint(
        {
            "tenant_id": tenant_id,
            "root_resource_version_id": str(root_resource_version.resource_version_id),
            "root_content_sha256": root_resource_version.content_sha256,
            "change_type": ImpactChangeType(change_type).value,
            "lineage_event_ids": [
                str(edge.event.lineage_event_id) for edge in lineage.edges
            ],
            "data_products": [
                {
                    "data_product_version_id": str(product.data_product_version_id),
                    "manifest_sha256": product.manifest_sha256,
                    "matched_resource_version_ids": [
                        str(version_id)
                        for version_id in product.matched_resource_version_ids
                    ],
                }
                for product in impacted_data_products
            ],
            "quality_result_ids": [
                str(signal.result.quality_result_id) for signal in quality_signals
            ],
            "disposition": ImpactDisposition(disposition).value,
            "review_reasons": [
                ImpactReviewReason(reason).value for reason in review_reasons
            ],
        }
    )


class LineageImpactAssessment(BaseModel):
    """Deterministic impact projection scoped to the GDA control ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["gda.lineage_impact.v1"] = "gda.lineage_impact.v1"
    scope: Literal["gda_control_ledger"] = "gda_control_ledger"
    tenant_id: TenantId
    root_resource_version: ResourceVersion
    change_type: ImpactChangeType
    lineage: LineageGraph
    impacted_data_products: tuple[ImpactedDataProduct, ...] = ()
    quality_signals: tuple[ImpactQualitySignal, ...] = ()
    disposition: ImpactDisposition
    review_reasons: tuple[ImpactReviewReason, ...] = ()
    impacted_resource_version_count: int = Field(ge=1)
    impacted_data_product_count: int = Field(ge=0)
    quality_signal_count: int = Field(ge=0)
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _consistent_assessment(self) -> LineageImpactAssessment:
        if self.lineage.tenant_id != self.tenant_id:
            raise ValueError("impact lineage must belong to the assessment tenant")
        if self.lineage.direction != LineageDirection.DOWNSTREAM:
            raise ValueError("impact assessment requires downstream lineage")
        if not self.lineage.complete:
            raise ValueError("impact assessment requires complete bounded lineage")
        if (
            self.root_resource_version.tenant_id != self.tenant_id
            or self.root_resource_version.resource_version_id
            != self.lineage.root_resource_version_id
        ):
            raise ValueError("impact root must match the lineage root")
        if self.impacted_resource_version_count != self.lineage.node_count:
            raise ValueError("impacted resource count must match lineage nodes")
        if self.impacted_data_product_count != len(self.impacted_data_products):
            raise ValueError("impacted data product count must match its payload")
        if self.quality_signal_count != len(self.quality_signals):
            raise ValueError("quality signal count must match its payload")
        lineage_depths = {
            node.resource_version.resource_version_id: node.min_depth
            for node in self.lineage.nodes
        }
        for product in self.impacted_data_products:
            if product.tenant_id != self.tenant_id:
                raise ValueError("impacted data products must belong to the assessment tenant")
            if set(product.matched_resource_version_ids) - set(lineage_depths):
                raise ValueError("product matches must belong to the lineage impact set")
        for signal in self.quality_signals:
            result = signal.result
            if result.tenant_id != self.tenant_id:
                raise ValueError("quality signals must belong to the assessment tenant")
            if lineage_depths.get(result.resource_version_id) != signal.resource_min_depth:
                raise ValueError("quality signal depth must match the lineage node")
        if len(self.review_reasons) != len(set(self.review_reasons)):
            raise ValueError("impact review reasons must be unique")
        expected = lineage_impact_fingerprint(
            tenant_id=self.tenant_id,
            root_resource_version=self.root_resource_version,
            change_type=self.change_type,
            lineage=self.lineage,
            impacted_data_products=self.impacted_data_products,
            quality_signals=self.quality_signals,
            disposition=self.disposition,
            review_reasons=self.review_reasons,
        )
        if self.assessment_sha256 != expected:
            raise ValueError("assessment_sha256 does not match impact evidence")
        return self
