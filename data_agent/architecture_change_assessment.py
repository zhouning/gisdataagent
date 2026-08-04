"""Compatibility- and lineage-bound review for one architecture schema drift."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .architecture_change_approval import (
    ArchitectureChangeReview,
    build_architecture_change_review,
)
from .data_architecture_ledger import ArchitectureReconciliationStatus
from .platform_contracts import (
    ApprovalCase,
    ResourceURNText,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .platform_gateway import PlatformGateway
from .platform_lineage import (
    ImpactChangeType,
    ImpactDisposition,
    LineageImpactAssessment,
)
from .postgis_schema_evidence import (
    PostgisSchemaCompatibilityAssessment,
    PostgisSchemaSnapshot,
    SchemaCompatibilityVerdict,
    assess_postgis_schema_compatibility,
)

ASSESSED_ARCHITECTURE_CHANGE_SCHEMA = "gda.assessed_architecture_change.v1"
ASSESSED_ARCHITECTURE_CHANGE_ACTION = "data_architecture.assessed_change_review"

SuccessorBlocker = Literal[
    "new_content_snapshot_required",
    "successor_data_contract_required",
]
SUCCESSOR_BLOCKERS: tuple[SuccessorBlocker, ...] = (
    "new_content_snapshot_required",
    "successor_data_contract_required",
)


class ArchitectureChangeAssessmentError(ValueError):
    """Compatibility or impact evidence cannot support assessed review."""


def assessed_architecture_change_fingerprint(
    *,
    tenant_id: str,
    target_resource_urn: str,
    resource_version_id: UUID,
    observation_id: UUID,
    observation_sha256: str,
    binding_sha256: str,
    base_review_sha256: str,
    compatibility_assessment_sha256: str,
    compatibility_verdict: SchemaCompatibilityVerdict | str,
    baseline_schema_artifact_id: UUID,
    candidate_schema_artifact_id: UUID,
    baseline_schema_evidence_sha256: str,
    candidate_schema_evidence_sha256: str,
    breaking_change_count: int,
    indeterminate_change_count: int,
    lineage_impact_sha256: str,
    impact_disposition: ImpactDisposition | str,
    lineage_edge_count: int,
    impacted_resource_version_count: int,
    impacted_data_product_count: int,
    successor_blockers: tuple[SuccessorBlocker, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": ASSESSED_ARCHITECTURE_CHANGE_SCHEMA,
            "tenant_id": tenant_id,
            "target_resource_urn": target_resource_urn,
            "resource_version_id": str(resource_version_id),
            "observation_id": str(observation_id),
            "observation_sha256": observation_sha256,
            "binding_sha256": binding_sha256,
            "base_review_sha256": base_review_sha256,
            "compatibility_assessment_sha256": compatibility_assessment_sha256,
            "compatibility_verdict": SchemaCompatibilityVerdict(compatibility_verdict).value,
            "baseline_schema_artifact_id": str(baseline_schema_artifact_id),
            "candidate_schema_artifact_id": str(candidate_schema_artifact_id),
            "baseline_schema_evidence_sha256": baseline_schema_evidence_sha256,
            "candidate_schema_evidence_sha256": candidate_schema_evidence_sha256,
            "breaking_change_count": breaking_change_count,
            "indeterminate_change_count": indeterminate_change_count,
            "lineage_impact_sha256": lineage_impact_sha256,
            "impact_disposition": ImpactDisposition(impact_disposition).value,
            "lineage_edge_count": lineage_edge_count,
            "impacted_resource_version_count": impacted_resource_version_count,
            "impacted_data_product_count": impacted_data_product_count,
            "successor_blockers": list(successor_blockers),
        }
    )


class AssessedArchitectureChangeReview(BaseModel):
    """Bounded compatibility and downstream-impact evidence for human review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    target_resource_urn: ResourceURNText
    resource_version_id: UUID
    observation_id: UUID
    observation_sha256: Sha256
    binding_sha256: Sha256
    base_review_sha256: Sha256
    compatibility_assessment_sha256: Sha256
    compatibility_verdict: SchemaCompatibilityVerdict
    baseline_schema_artifact_id: UUID
    candidate_schema_artifact_id: UUID
    baseline_schema_evidence_sha256: Sha256
    candidate_schema_evidence_sha256: Sha256
    breaking_change_count: int = Field(ge=0)
    indeterminate_change_count: int = Field(ge=0)
    lineage_impact_sha256: Sha256
    impact_disposition: ImpactDisposition
    lineage_edge_count: int = Field(ge=0)
    impacted_resource_version_count: int = Field(ge=1)
    impacted_data_product_count: int = Field(ge=0)
    successor_blockers: tuple[SuccessorBlocker, ...]
    assessment_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_review(self) -> AssessedArchitectureChangeReview:
        identity = parse_resource_urn(self.target_resource_urn)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("assessed architecture target tenant must match")
        if identity["resource_kind"] != "dataset":
            raise ValueError("assessed architecture target must be a dataset")
        if self.successor_blockers != SUCCESSOR_BLOCKERS:
            raise ValueError("assessed review must retain successor creation blockers")
        expected = assessed_architecture_change_fingerprint(
            tenant_id=self.tenant_id,
            target_resource_urn=self.target_resource_urn,
            resource_version_id=self.resource_version_id,
            observation_id=self.observation_id,
            observation_sha256=self.observation_sha256,
            binding_sha256=self.binding_sha256,
            base_review_sha256=self.base_review_sha256,
            compatibility_assessment_sha256=self.compatibility_assessment_sha256,
            compatibility_verdict=self.compatibility_verdict,
            baseline_schema_artifact_id=self.baseline_schema_artifact_id,
            candidate_schema_artifact_id=self.candidate_schema_artifact_id,
            baseline_schema_evidence_sha256=self.baseline_schema_evidence_sha256,
            candidate_schema_evidence_sha256=self.candidate_schema_evidence_sha256,
            breaking_change_count=self.breaking_change_count,
            indeterminate_change_count=self.indeterminate_change_count,
            lineage_impact_sha256=self.lineage_impact_sha256,
            impact_disposition=self.impact_disposition,
            lineage_edge_count=self.lineage_edge_count,
            impacted_resource_version_count=self.impacted_resource_version_count,
            impacted_data_product_count=self.impacted_data_product_count,
            successor_blockers=self.successor_blockers,
        )
        if self.assessment_sha256 != expected:
            raise ValueError("assessment_sha256 does not match assessed change review")
        return self

    def approval_context(self) -> dict[str, Any]:
        return {
            "resource_version_id": str(self.resource_version_id),
            "observation_id": str(self.observation_id),
            "observation_sha256": self.observation_sha256,
            "binding_sha256": self.binding_sha256,
            "base_review_sha256": self.base_review_sha256,
            "compatibility_assessment_sha256": (self.compatibility_assessment_sha256),
            "compatibility_verdict": self.compatibility_verdict.value,
            "baseline_schema_artifact_id": str(self.baseline_schema_artifact_id),
            "candidate_schema_artifact_id": str(self.candidate_schema_artifact_id),
            "breaking_change_count": self.breaking_change_count,
            "indeterminate_change_count": self.indeterminate_change_count,
            "lineage_impact_sha256": self.lineage_impact_sha256,
            "impact_disposition": self.impact_disposition.value,
            "lineage_edge_count": self.lineage_edge_count,
            "impacted_resource_version_count": self.impacted_resource_version_count,
            "impacted_data_product_count": self.impacted_data_product_count,
            "successor_blockers": list(self.successor_blockers),
        }


def build_assessed_architecture_change_review(
    base_review: ArchitectureChangeReview,
    compatibility: PostgisSchemaCompatibilityAssessment,
    impact: LineageImpactAssessment,
) -> AssessedArchitectureChangeReview:
    if base_review.reconciliation_status not in {
        ArchitectureReconciliationStatus.SCHEMA_DRIFT,
        ArchitectureReconciliationStatus.SCHEMA_AND_LOCATION_DRIFT,
    }:
        raise ArchitectureChangeAssessmentError("assessed review requires schema drift")
    if (
        compatibility.tenant_id != base_review.tenant_id
        or compatibility.resource_version_id != base_review.resource_version_id
        or compatibility.candidate_observation_id != base_review.observation_id
    ):
        raise ArchitectureChangeAssessmentError(
            "compatibility evidence does not match architecture drift"
        )
    if (
        impact.tenant_id != base_review.tenant_id
        or impact.root_resource_version.resource_version_id != base_review.resource_version_id
        or impact.change_type is not ImpactChangeType.SCHEMA
    ):
        raise ArchitectureChangeAssessmentError(
            "lineage impact does not match architecture schema drift"
        )
    values = {
        "tenant_id": base_review.tenant_id,
        "target_resource_urn": base_review.target_resource_urn,
        "resource_version_id": base_review.resource_version_id,
        "observation_id": base_review.observation_id,
        "observation_sha256": base_review.observation_sha256,
        "binding_sha256": base_review.binding_sha256,
        "base_review_sha256": base_review.review_sha256,
        "compatibility_assessment_sha256": compatibility.assessment_sha256,
        "compatibility_verdict": compatibility.verdict,
        "baseline_schema_artifact_id": compatibility.baseline_evidence_artifact_id,
        "candidate_schema_artifact_id": compatibility.candidate_evidence_artifact_id,
        "baseline_schema_evidence_sha256": compatibility.baseline_evidence_sha256,
        "candidate_schema_evidence_sha256": compatibility.candidate_evidence_sha256,
        "breaking_change_count": compatibility.breaking_change_count,
        "indeterminate_change_count": compatibility.indeterminate_change_count,
        "lineage_impact_sha256": impact.assessment_sha256,
        "impact_disposition": impact.disposition,
        "lineage_edge_count": impact.lineage.edge_count,
        "impacted_resource_version_count": impact.impacted_resource_version_count,
        "impacted_data_product_count": impact.impacted_data_product_count,
        "successor_blockers": SUCCESSOR_BLOCKERS,
    }
    return AssessedArchitectureChangeReview(
        assessment_sha256=assessed_architecture_change_fingerprint(**values),
        **values,
    )


def build_assessed_architecture_change_approval_case(
    review: AssessedArchitectureChangeReview,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    return ApprovalCase(
        tenant_id=review.tenant_id,
        approval_case_ref=build_resource_urn(
            review.tenant_id,
            "approval_case",
            f"architecture-assessment-{review.observation_id.hex}",
        ),
        target_resource_urn=review.target_resource_urn,
        target_fingerprint=review.assessment_sha256,
        action=ASSESSED_ARCHITECTURE_CHANGE_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=review.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ArchitectureChangeAssessmentRequestResult:
    base_review: ArchitectureChangeReview
    compatibility: PostgisSchemaCompatibilityAssessment
    impact: LineageImpactAssessment
    review: AssessedArchitectureChangeReview
    approval_case: ApprovalCase
    created: bool


class ArchitectureChangeAssessmentService:
    """Recompute compatibility and impact before admitting assessed review."""

    def __init__(
        self,
        gateway: PlatformGateway,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._gateway = gateway
        self._approval_authority = approval_authority

    def request_review(
        self,
        *,
        tenant_id: str,
        resource_version_id: UUID,
        baseline_snapshot: PostgisSchemaSnapshot,
        candidate_snapshot: PostgisSchemaSnapshot,
        baseline_schema_artifact_id: UUID,
        candidate_schema_artifact_id: UUID,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
        evaluated_at: datetime | None = None,
        max_lineage_depth: int = 6,
        max_lineage_edges: int = 500,
    ) -> ArchitectureChangeAssessmentRequestResult:
        resource_version = self._gateway.get_resource_version(
            tenant_id,
            resource_version_id,
        )
        reconciliation = self._gateway.reconcile_resource_version_architecture(
            tenant_id,
            resource_version_id,
            evaluated_at=evaluated_at or requested_at,
        )
        base_review = build_architecture_change_review(
            resource_version,
            reconciliation,
        )
        candidate_observation = reconciliation.latest_observation
        if candidate_observation is None:
            raise ArchitectureChangeAssessmentError(
                "assessed review requires a candidate observation"
            )
        baseline_artifact = self._gateway.get_artifact(
            tenant_id,
            baseline_schema_artifact_id,
        )
        candidate_artifact = self._gateway.get_artifact(
            tenant_id,
            candidate_schema_artifact_id,
        )
        try:
            baseline_observation_id = UUID(str(baseline_artifact.manifest["observation_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ArchitectureChangeAssessmentError(
                "baseline schema Artifact has no valid observation identity"
            ) from exc
        baseline_observation = self._gateway.get_architecture_provider_observation(
            tenant_id,
            baseline_observation_id,
        )
        if candidate_artifact.manifest.get("observation_id") != str(
            candidate_observation.observation_id
        ):
            raise ArchitectureChangeAssessmentError(
                "candidate schema Artifact does not bind the latest observation"
            )
        try:
            compatibility = assess_postgis_schema_compatibility(
                baseline_snapshot,
                candidate_snapshot,
                baseline_observation,
                candidate_observation,
                baseline_artifact,
                candidate_artifact,
            )
        except ValueError as exc:
            raise ArchitectureChangeAssessmentError(str(exc)) from exc
        accepted_schema = reconciliation.architecture.schema_version_record
        if accepted_schema is None or accepted_schema.authority_version_ref != (
            f"schema-sha256:{baseline_snapshot.snapshot_sha256}"
        ):
            raise ArchitectureChangeAssessmentError(
                "baseline schema evidence does not match accepted architecture"
            )
        impact = self._gateway.assess_lineage_impact(
            tenant_id,
            resource_version_id,
            change_type=ImpactChangeType.SCHEMA,
            max_depth=max_lineage_depth,
            max_edges=max_lineage_edges,
        )
        review = build_assessed_architecture_change_review(
            base_review,
            compatibility,
            impact,
        )
        case = build_assessed_architecture_change_approval_case(
            review,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ArchitectureChangeAssessmentRequestResult(
            base_review=base_review,
            compatibility=compatibility,
            impact=impact,
            review=review,
            approval_case=written.approval_case,
            created=written.created,
        )
