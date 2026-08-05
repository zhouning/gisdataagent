"""Contracts for fail-closed source schema promotion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    build_resource_urn,
)
from data_agent.source_connector_governance import SchemaDriftEvent, SchemaFieldChange
from data_agent.source_schema_drift_ledger import (
    PersistedSchemaDrift,
    SchemaDriftStatus,
)
from data_agent.source_schema_promotion import (
    SourceSchemaPromotionBlockedError,
    evaluate_source_schema_promotion,
    require_source_schema_promotion,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _drift(
    *,
    breaking: bool,
    status: SchemaDriftStatus,
    state_version: int,
) -> PersistedSchemaDrift:
    event = SchemaDriftEvent(
        source_id="postgresql-cdc-schema-promotion",
        previous_discovery_fingerprint="a" * 64,
        current_discovery_fingerprint="b" * 64,
        changed_resources=("public.osm_road_changes",),
        field_changes=(
            SchemaFieldChange(
                resource_name="public.osm_road_changes",
                field_name="observed_at",
                change_kind="nullable_tightened" if breaking else "added",
                previous_type="TIMESTAMP WITH TIME ZONE" if breaking else None,
                current_type="TIMESTAMP WITH TIME ZONE",
                previous_nullable=True if breaking else None,
                current_nullable=False if breaking else True,
                breaking=breaking,
            ),
        ),
        breaking=breaking,
    )
    return PersistedSchemaDrift(
        tenant_id="local-dev",
        drift_event_id=event.event_id,
        source_id=event.source_id,
        source_definition_fingerprint="c" * 64,
        previous_discovery_fingerprint=event.previous_discovery_fingerprint,
        current_discovery_fingerprint=event.current_discovery_fingerprint,
        breaking=breaking,
        event_payload=event,
        detected_by="workload:source-certifier",
        status=status,
        state_version=state_version,
        detected_at=NOW,
        updated_at=NOW,
    )


def _approval_case(
    drift: PersistedSchemaDrift,
    *,
    target: str | None = None,
    approved: bool = False,
) -> ApprovalCase:
    return ApprovalCase(
        tenant_id=drift.tenant_id,
        approval_case_ref=build_resource_urn(
            drift.tenant_id,
            "approval_case",
            "postgresql-cdc-schema-promotion",
        ),
        target_resource_urn=(
            target
            or build_resource_urn(
                drift.tenant_id,
                "schema_drift",
                drift.drift_event_id,
            )
        ),
        target_fingerprint=drift.drift_event_id,
        action="source_schema_drift.reconcile",
        requester_subject="workload:dataops-controller",
        request_reason="breaking source schema requires review",
        status=(
            ApprovalCaseStatus.APPROVED if approved else ApprovalCaseStatus.PENDING
        ),
        state_version=1 if approved else 0,
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        decided_by="human:data-steward" if approved else None,
        decision_reason="compatible migration approved" if approved else None,
        decided_at=NOW + timedelta(minutes=1) if approved else None,
    )


def test_reconciled_additive_schema_is_promotion_eligible() -> None:
    decision = require_source_schema_promotion(
        _drift(
            breaking=False,
            status=SchemaDriftStatus.RECONCILED,
            state_version=1,
        )
    )

    assert decision.allowed
    assert decision.reason == "schema_drift_reconciled"


def test_breaking_schema_with_pending_approval_fails_closed() -> None:
    drift = _drift(
        breaking=True,
        status=SchemaDriftStatus.APPROVAL_REQUIRED,
        state_version=0,
    )
    approval_case = _approval_case(drift)

    decision = evaluate_source_schema_promotion(drift, approval_case=approval_case)
    assert not decision.allowed
    assert decision.reason == "breaking_schema_drift_pending_approval"
    assert decision.approval_case_binding_valid
    with pytest.raises(SourceSchemaPromotionBlockedError) as captured:
        require_source_schema_promotion(drift, approval_case=approval_case)
    assert captured.value.decision == decision


def test_mismatched_approval_case_binding_fails_closed() -> None:
    drift = _drift(
        breaking=True,
        status=SchemaDriftStatus.APPROVAL_REQUIRED,
        state_version=0,
    )
    wrong_target = build_resource_urn("local-dev", "schema_drift", "d" * 64)

    decision = evaluate_source_schema_promotion(
        drift,
        approval_case=_approval_case(drift, target=wrong_target),
    )

    assert not decision.allowed
    assert decision.reason == "approval_case_binding_invalid"
    assert decision.approval_case_binding_valid is False


def test_observed_additive_schema_requires_reconciliation() -> None:
    decision = evaluate_source_schema_promotion(
        _drift(
            breaking=False,
            status=SchemaDriftStatus.OBSERVED,
            state_version=0,
        )
    )

    assert not decision.allowed
    assert decision.reason == "schema_drift_not_reconciled"


def test_breaking_reconciliation_requires_approved_bound_case() -> None:
    drift = _drift(
        breaking=True,
        status=SchemaDriftStatus.RECONCILED,
        state_version=2,
    )

    pending = evaluate_source_schema_promotion(
        drift,
        approval_case=_approval_case(drift),
    )
    approved = require_source_schema_promotion(
        drift,
        approval_case=_approval_case(drift, approved=True),
    )

    assert not pending.allowed
    assert pending.reason == "approval_case_not_approved"
    assert approved.allowed
