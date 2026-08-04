"""Tests for compatibility- and lineage-bound architecture change review."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.architecture_change_approval import (
    ArchitectureChangeReview,
    architecture_change_review_fingerprint,
)
from data_agent.architecture_change_assessment import (
    ASSESSED_ARCHITECTURE_CHANGE_ACTION,
    SUCCESSOR_BLOCKERS,
    ArchitectureChangeAssessmentError,
    AssessedArchitectureChangeReview,
    build_assessed_architecture_change_approval_case,
    build_assessed_architecture_change_review,
)
from data_agent.platform_contracts import ResourceVersion
from data_agent.platform_lineage import (
    ImpactChangeType,
    ImpactDisposition,
    ImpactReviewReason,
    LineageDirection,
    LineageGraph,
    LineageGraphNode,
    LineageImpactAssessment,
    lineage_impact_fingerprint,
)
from data_agent.postgis_schema_evidence import (
    PostgisSchemaCompatibilityAssessment,
    PostgisSchemaCompatibilityChange,
    SchemaCompatibilityChangeKind,
    SchemaCompatibilityVerdict,
    postgis_schema_compatibility_fingerprint,
)

NOW = datetime(2026, 8, 3, 11, tzinfo=UTC)
TENANT = "assessed-change"
RESOURCE_VERSION_ID = UUID("10000000-0000-4000-8000-000000000001")
OBSERVATION_ID = UUID("20000000-0000-4000-8000-000000000002")
RESOURCE_URN = f"gda://{TENANT}/dataset/parcels"


def _base_review(*, status: str = "schema_drift") -> ArchitectureChangeReview:
    actions = {
        "schema_drift": ("review_schema_drift",),
        "schema_and_location_drift": (
            "review_schema_drift",
            "review_location_drift",
        ),
        "tombstoned": ("investigate_tombstone",),
    }[status]
    values = {
        "tenant_id": TENANT,
        "target_resource_urn": RESOURCE_URN,
        "resource_version_id": RESOURCE_VERSION_ID,
        "observation_id": OBSERVATION_ID,
        "observation_sha256": "a" * 64,
        "binding_sha256": "b" * 64,
        "reconciliation_status": status,
        "candidate_schema_sha256": None if status == "tombstoned" else "c" * 64,
        "candidate_location_sha256": (None if status == "tombstoned" else "d" * 64),
        "required_actions": actions,
    }
    return ArchitectureChangeReview(
        review_sha256=architecture_change_review_fingerprint(**values),
        **values,
    )


def _compatibility(
    *,
    candidate_observation_id: UUID = OBSERVATION_ID,
) -> PostgisSchemaCompatibilityAssessment:
    change = PostgisSchemaCompatibilityChange(
        component="column",
        subject="zoning_code",
        change_kind=SchemaCompatibilityChangeKind.COLUMN_ADDED,
        verdict=SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE,
        current_fingerprint="e" * 64,
    )
    values = {
        "tenant_id": TENANT,
        "resource_version_id": RESOURCE_VERSION_ID,
        "baseline_observation_id": UUID("20000000-0000-4000-8000-000000000001"),
        "candidate_observation_id": candidate_observation_id,
        "baseline_evidence_artifact_id": UUID("30000000-0000-4000-8000-000000000001"),
        "candidate_evidence_artifact_id": UUID("30000000-0000-4000-8000-000000000002"),
        "baseline_snapshot_sha256": "f" * 64,
        "candidate_snapshot_sha256": "1" * 64,
        "baseline_evidence_sha256": "2" * 64,
        "candidate_evidence_sha256": "3" * 64,
        "changes": (change,),
        "verdict": SchemaCompatibilityVerdict.BACKWARD_COMPATIBLE,
    }
    return PostgisSchemaCompatibilityAssessment(
        breaking_change_count=0,
        indeterminate_change_count=0,
        assessment_sha256=postgis_schema_compatibility_fingerprint(**values),
        **values,
    )


def _impact() -> LineageImpactAssessment:
    version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=RESOURCE_URN,
        resource_version_id=RESOURCE_VERSION_ID,
        version_key="snapshot-1",
        content_sha256="4" * 64,
        authority_version_ref={"snapshot": "snapshot-1"},
        created_by="workload:source-controller",
        created_at=NOW,
    )
    lineage = LineageGraph(
        tenant_id=TENANT,
        root_resource_version_id=RESOURCE_VERSION_ID,
        direction=LineageDirection.DOWNSTREAM,
        requested_max_depth=6,
        requested_max_edges=500,
        reached_depth=0,
        complete=True,
        nodes=(
            LineageGraphNode(
                resource_version=version,
                min_depth=0,
                is_root=True,
            ),
        ),
        edges=(),
        node_count=1,
        edge_count=0,
    )
    values = {
        "tenant_id": TENANT,
        "root_resource_version": version,
        "change_type": ImpactChangeType.SCHEMA,
        "lineage": lineage,
        "impacted_data_products": (),
        "quality_signals": (),
        "disposition": ImpactDisposition.REVIEW_REQUIRED,
        "review_reasons": (ImpactReviewReason.CHANGE_TYPE_REQUIRES_REVIEW,),
    }
    return LineageImpactAssessment(
        impacted_resource_version_count=1,
        impacted_data_product_count=0,
        quality_signal_count=0,
        assessment_sha256=lineage_impact_fingerprint(**values),
        **values,
    )


def test_assessed_review_binds_compatibility_impact_and_successor_blockers() -> None:
    review = build_assessed_architecture_change_review(
        _base_review(),
        _compatibility(),
        _impact(),
    )
    case = build_assessed_architecture_change_approval_case(
        review,
        requester_subject="agent:architecture-reviewer",
        request_reason="review compatibility and downstream impact",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert case.action == ASSESSED_ARCHITECTURE_CHANGE_ACTION
    assert case.target_fingerprint == review.assessment_sha256
    assert case.request_context["compatibility_verdict"] == "backward_compatible"
    assert case.request_context["impact_disposition"] == "review_required"
    assert case.request_context["successor_blockers"] == list(SUCCESSOR_BLOCKERS)
    assert "columns" not in case.model_dump_json()
    assert "constraints" not in case.model_dump_json()


def test_assessed_review_rejects_non_schema_change() -> None:
    with pytest.raises(ArchitectureChangeAssessmentError, match="requires schema drift"):
        build_assessed_architecture_change_review(
            _base_review(status="tombstoned"),
            _compatibility(),
            _impact(),
        )


def test_assessed_review_rejects_compatibility_for_another_observation() -> None:
    with pytest.raises(
        ArchitectureChangeAssessmentError,
        match="does not match architecture drift",
    ):
        build_assessed_architecture_change_review(
            _base_review(),
            _compatibility(candidate_observation_id=UUID("20000000-0000-4000-8000-000000000099")),
            _impact(),
        )


def test_assessed_review_rejects_tampered_composite_fingerprint() -> None:
    review = build_assessed_architecture_change_review(
        _base_review(),
        _compatibility(),
        _impact(),
    )

    with pytest.raises(ValidationError, match="assessment_sha256"):
        AssessedArchitectureChangeReview.model_validate(
            review.model_dump() | {"assessment_sha256": "0" * 64}
        )
