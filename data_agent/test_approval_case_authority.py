"""Contract tests for the unified ApprovalCase authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.approval_case_authority import approval_case_resource
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseEvent,
    ApprovalCaseStatus,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
CASE_REF = "gda://tenant-a/approval_case/schema-drift-1"
TARGET_REF = "gda://tenant-a/schema_drift/" + "a" * 64


def _case(**changes) -> ApprovalCase:
    values = {
        "tenant_id": "tenant-a",
        "approval_case_ref": CASE_REF,
        "target_resource_urn": TARGET_REF,
        "target_fingerprint": "a" * 64,
        "action": "source_schema_drift.reconcile",
        "requester_subject": "workload:schema-drift-observer",
        "request_reason": "breaking schema drift requires a human verdict",
        "request_context": {"breaking": True},
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return ApprovalCase(**values)


def test_pending_case_is_frozen_and_projects_one_canonical_resource() -> None:
    case = _case()
    resource = approval_case_resource(case, owner_ref="team:data-platform")

    assert case.status is ApprovalCaseStatus.PENDING
    assert resource.resource_urn == CASE_REF
    assert resource.resource_kind == "approval_case"
    assert resource.authority_system == "gda_control"
    assert resource.governance_ref["target_resource_urn"] == TARGET_REF
    with pytest.raises(ValidationError, match="frozen"):
        case.status = ApprovalCaseStatus.APPROVED  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"approval_case_ref": "gda://tenant-b/approval_case/schema-drift-1"},
            "case_ref tenant",
        ),
        (
            {"approval_case_ref": "gda://tenant-a/dataset/schema-drift-1"},
            "resource kind 'approval_case'",
        ),
        (
            {"target_resource_urn": "gda://tenant-b/schema_drift/" + "a" * 64},
            "target tenant",
        ),
        ({"requester_subject": "anonymous"}, "typed subject"),
        ({"expires_at": NOW}, "expiry must follow"),
    ],
)
def test_case_rejects_unbound_or_unbounded_requests(changes, message) -> None:
    with pytest.raises(ValidationError, match=message):
        _case(**changes)


def test_terminal_verdict_requires_independent_human_and_complete_decision() -> None:
    approved = _case(
        status="approved",
        state_version=1,
        decided_by="human:data-steward",
        decision_reason="approved additive compatibility plan",
        decided_at=NOW + timedelta(minutes=5),
    )
    assert approved.status is ApprovalCaseStatus.APPROVED

    for actor in ("workload:reviewer", "workload:schema-drift-observer"):
        with pytest.raises(ValidationError, match="human identity|independent"):
            _case(
                status="approved",
                state_version=1,
                decided_by=actor,
                decision_reason="invalid approver",
                decided_at=NOW + timedelta(minutes=5),
            )
    with pytest.raises(ValidationError, match="set together"):
        _case(status="approved", state_version=1)


def test_case_event_allows_only_initialization_then_one_terminal_decision() -> None:
    initial = ApprovalCaseEvent(
        tenant_id="tenant-a",
        approval_event_id=UUID("00000000-0000-4000-8000-000000000001"),
        approval_case_ref=CASE_REF,
        sequence_no=0,
        to_status="pending",
        actor_subject="workload:schema-drift-observer",
        reason="breaking drift detected",
        occurred_at=NOW,
    )
    decision = ApprovalCaseEvent(
        tenant_id="tenant-a",
        approval_event_id=UUID("00000000-0000-4000-8000-000000000002"),
        approval_case_ref=CASE_REF,
        sequence_no=1,
        from_status="pending",
        to_status="approved",
        actor_subject="human:data-steward",
        reason="approved compatibility plan",
        occurred_at=NOW + timedelta(minutes=5),
    )
    assert initial.to_status is ApprovalCaseStatus.PENDING
    assert decision.to_status is ApprovalCaseStatus.APPROVED
    with pytest.raises(ValidationError, match="human identity"):
        ApprovalCaseEvent.model_validate(
            {**decision.model_dump(), "actor_subject": "workload:auto-approver"}
        )


def test_migration_enforces_authority_rls_cas_and_real_drift_binding() -> None:
    sql = (
        Path(__file__).parent / "migrations/103_unified_approval_case_authority.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.approval_case",
        "CREATE TABLE IF NOT EXISTS gda_control.approval_case_event",
        "FOREIGN KEY (tenant_id, approval_case_ref)",
        "FORCE ROW LEVEL SECURITY",
        "transition_approval_case",
        "p_expected_state_version INTEGER",
        "independent human approver",
        "ApprovalCase does not authorize this drift verdict",
        "source_schema_drift.reconcile",
        "GRANT SELECT, INSERT ON gda_control.approval_case",
        "GRANT SELECT ON gda_control.approval_case_event",
    ):
        assert marker in sql
    assert "GRANT UPDATE ON gda_control.approval_case" not in sql
    assert "GRANT INSERT ON gda_control.approval_case_event" not in sql
