"""Contract tests for the unified ApprovalCase authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.approval_case_authority import ApprovalCaseAuthority, approval_case_resource
from data_agent.platform_contracts import (
    ApprovalAssignmentActorAccess,
    ApprovalCase,
    ApprovalCaseAssignment,
    ApprovalCaseAssignmentEvent,
    ApprovalCaseAssignmentOperation,
    ApprovalCaseEscalation,
    ApprovalCaseEscalationPlan,
    ApprovalCaseEscalationStatus,
    ApprovalCaseEvent,
    ApprovalCaseNotification,
    ApprovalCaseNotificationRecoveryEvent,
    ApprovalCaseStatus,
    ApprovalPrincipal,
    ApprovalTeamMembership,
    approval_case_escalation_idempotency_key,
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


def test_sla_notification_migration_is_transactional_bounded_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/118_approval_case_sla_notification_outbox.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.approval_case_notification_outbox",
        "AFTER INSERT ON gda_control.approval_case_event",
        "'expired', 'alertmanager', 'alertmanager:approval-default'",
        "status = 'suppressed'",
        "FOR UPDATE OF notification SKIP LOCKED",
        "FORCE ROW LEVEL SECURITY",
        "claim_approval_case_notifications",
        "complete_approval_case_notification",
        "fail_approval_case_notification",
        "GRANT SELECT ON TABLE gda_control.approval_case_notification_outbox",
    ):
        assert marker in sql
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "UPDATE gda_control.approval_case\n" not in sql


def test_escalation_plan_recomputes_scope_bound_idempotency_key() -> None:
    due_at = NOW + timedelta(minutes=30)
    key = approval_case_escalation_idempotency_key(
        tenant_id="tenant-a",
        approval_case_ref=CASE_REF,
        expected_state_version=0,
        action="source_schema_drift.reconcile",
        target_fingerprint="a" * 64,
        escalation_stage=1,
        due_at=due_at,
        target_team_subject="team:data-governance",
        on_call_ref="oncall:data-governance",
    )
    plan = ApprovalCaseEscalationPlan(
        tenant_id="tenant-a",
        approval_case_ref=CASE_REF,
        expected_state_version=0,
        action="source_schema_drift.reconcile",
        target_fingerprint="a" * 64,
        escalation_stage=1,
        due_at=due_at,
        target_team_subject="team:data-governance",
        on_call_ref="oncall:data-governance",
        actor_subject="workload:sla-policy-controller",
        reason="notify standby approver",
        idempotency_key=key,
    )
    assert plan.idempotency_key == key
    with pytest.raises(ValidationError, match="idempotency key"):
        ApprovalCaseEscalationPlan.model_validate(
            {**plan.model_dump(), "on_call_ref": "oncall:other"}
        )


def test_sla_escalation_migration_is_pre_expiry_idempotent_and_verdict_neutral() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/249_agentops_approval_sla_escalation.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "approval_case_sla_escalation",
        "schedule_approval_case_sla_escalation",
        "materialize_due_approval_case_sla_escalations",
        "UNIQUE (tenant_id, approval_case_ref, escalation_stage)",
        "idempotency_key",
        "FOR UPDATE OF escalation SKIP LOCKED",
        "status = 'suppressed'",
        "ApprovalCase escalation must be due between request and expiry",
        "GRANT SELECT ON TABLE gda_control.approval_case_sla_escalation",
    ):
        assert marker in sql
    assert "UPDATE gda_control.approval_case AS" not in sql
    assert "GRANT INSERT ON TABLE gda_control.approval_case_sla_escalation" not in sql


def test_sla_escalation_stage_forward_migration_separates_delivery_identity() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/250_agentops_approval_sla_escalation_outbox_stage_key.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "DROP CONSTRAINT IF EXISTS uq_gda_approval_notification_delivery",
        "uq_gda_approval_notification_delivery",
        "escalation_stage",
        "materialize_due_approval_case_sla_escalations",
        "ON CONFLICT (",
        "status = 'suppressed'",
        "claimed_by = NULL",
    ):
        assert marker in sql
    assert "notification.idempotency_key = v_due.idempotency_key" in sql


def test_materialized_escalation_suppression_keeps_materialization_evidence() -> None:
    escalation = ApprovalCaseEscalation(
        tenant_id="tenant-a",
        escalation_id=UUID("00000000-0000-4000-8000-000000000110"),
        approval_case_ref=CASE_REF,
        expected_state_version=0,
        action="source_schema_drift.reconcile",
        target_fingerprint="a" * 64,
        escalation_stage=1,
        due_at=NOW + timedelta(minutes=30),
        target_team_subject="team:data-governance",
        on_call_ref="oncall:data-governance",
        actor_subject="workload:sla-policy-controller",
        reason="notify standby approver",
        idempotency_key=approval_case_escalation_idempotency_key(
            tenant_id="tenant-a",
            approval_case_ref=CASE_REF,
            expected_state_version=0,
            action="source_schema_drift.reconcile",
            target_fingerprint="a" * 64,
            escalation_stage=1,
            due_at=NOW + timedelta(minutes=30),
            target_team_subject="team:data-governance",
            on_call_ref="oncall:data-governance",
        ),
        status=ApprovalCaseEscalationStatus.SUPPRESSED,
        created_at=NOW,
        materialized_at=NOW + timedelta(minutes=31),
        suppressed_at=NOW + timedelta(minutes=32),
    )
    assert escalation.materialized_at is not None
    assert escalation.suppressed_at is not None


def test_notification_recovery_contract_requires_complete_human_evidence() -> None:
    recovered = ApprovalCaseNotification(
        tenant_id="tenant-a",
        notification_id=UUID("00000000-0000-4000-8000-000000000102"),
        approval_case_ref=CASE_REF,
        approval_event_sequence_no=0,
        notification_kind="requested",
        channel="alertmanager",
        destination_ref="alertmanager:approval-default",
        delivery_order=0,
        status="pending",
        available_at=NOW,
        created_at=NOW,
        recovery_count=1,
        last_recovered_by="human:platform-admin",
        last_recovery_reason="receiver route repaired",
        last_recovered_at=NOW,
    )
    event = ApprovalCaseNotificationRecoveryEvent(
        tenant_id="tenant-a",
        recovery_event_id=UUID("00000000-0000-4000-8000-000000000103"),
        notification_id=recovered.notification_id,
        approval_case_ref=CASE_REF,
        recovery_no=1,
        actor_subject="human:platform-admin",
        reason="receiver route repaired",
        previous_attempt_count=10,
        previous_last_error="Alertmanager unavailable",
        occurred_at=NOW,
    )

    assert recovered.recovery_count == event.recovery_no
    with pytest.raises(ValidationError, match="complete recovery evidence"):
        ApprovalCaseNotification.model_validate(
            {**recovered.model_dump(), "last_recovery_reason": None}
        )
    with pytest.raises(ValidationError, match="human identity"):
        ApprovalCaseNotificationRecoveryEvent.model_validate(
            {**event.model_dump(), "actor_subject": "workload:auto-retry"}
        )


def test_governed_recovery_migration_is_cas_bounded_audited_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/119_approval_notification_governed_recovery.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE gda_control.approval_case_notification_recovery_event",
        "BEFORE UPDATE OR DELETE",
        "FORCE ROW LEVEL SECURITY",
        "retry_approval_case_notification",
        "p_expected_attempt_count INTEGER",
        "only a failed notification may be recovered",
        "notification manual recovery limit reached",
        "a terminal ApprovalCase expiry alert cannot be replayed",
        "recovery_count = v_recovery_no",
        "GRANT SELECT ON TABLE gda_control.approval_case_notification_recovery_event",
    ):
        assert marker in sql
    assert "UPDATE gda_control.approval_case AS" not in sql
    assert "GRANT UPDATE" not in sql


def test_assignment_contract_separates_routing_from_approval_verdict() -> None:
    assignment = ApprovalCaseAssignment(
        tenant_id="tenant-a",
        approval_case_ref=CASE_REF,
        assignment_version=1,
        status="assigned",
        assignee_subject="human:data-steward",
        last_actor_subject="human:platform-admin",
        last_reason="route breaking schema review",
        assigned_at=NOW,
        updated_at=NOW,
    )
    event = ApprovalCaseAssignmentEvent(
        tenant_id="tenant-a",
        assignment_event_id=UUID("00000000-0000-4000-8000-000000000105"),
        approval_case_ref=CASE_REF,
        assignment_version=1,
        action="assigned",
        to_assignee_subject="human:data-steward",
        actor_subject="human:platform-admin",
        reason="route breaking schema review",
        occurred_at=NOW,
    )

    assert assignment.status.value == event.action.value
    team_assignment = ApprovalCaseAssignment.model_validate(
        {**assignment.model_dump(), "assignee_subject": "team:data-governance"}
    )
    assert team_assignment.assignee_subject == "team:data-governance"
    with pytest.raises(ValidationError, match="human or team assignee"):
        ApprovalCaseAssignment.model_validate(
            {**assignment.model_dump(), "assignee_subject": "workload:auto-reviewer"}
        )
    with pytest.raises(ValidationError, match="action does not match"):
        ApprovalCaseAssignmentEvent.model_validate(
            {**event.model_dump(), "from_assignee_subject": "human:old-steward"}
        )


def test_assignment_migration_is_cas_audited_and_decision_enforced() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/120_approval_case_assignment_authority.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE gda_control.approval_case_assignment",
        "CREATE TABLE gda_control.approval_case_assignment_event",
        "transition_approval_case_assignment",
        "p_expected_assignment_version INTEGER",
        "only the current assignee may delegate",
        "ApprovalCase decision is reserved for the current assignee",
        "ApprovalCase requester cannot be assigned as approver",
        "ApprovalCase delegation depth limit reached",
        "close_approval_case_assignment",
        "FORCE ROW LEVEL SECURITY",
        "BEFORE UPDATE OR DELETE ON gda_control.approval_case_assignment_event",
        "GRANT SELECT ON TABLE gda_control.approval_case_assignment_event",
    ):
        assert marker in sql
    assert "GRANT UPDATE" not in sql
    assert "UPDATE gda_control.approval_case\n" in sql


def test_expiry_migration_is_atomic_and_allows_only_authoritative_late_cancel() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/243_agentops_approval_expiry_authority.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "expire_approval_case",
        "FOR UPDATE",
        "clock_timestamp()",
        "ApprovalCase terminal state conflicts with expiry evidence",
        "ApprovalCase has not expired",
        "status = 'cancelled' OR decided_at < expires_at",
        "GRANT EXECUTE ON FUNCTION gda_control.expire_approval_case",
    ):
        assert marker in sql
    assert "GRANT UPDATE ON TABLE gda_control.approval_case" not in sql


def test_approval_directory_contracts_bind_typed_effective_subjects() -> None:
    principal = ApprovalPrincipal(
        tenant_id="tenant-a",
        principal_subject="team:data-governance",
        principal_type="team",
        display_name="Data Governance",
        directory_version=1,
        status="active",
        approval_eligible=True,
        availability_status="available",
        valid_from=NOW,
        last_actor_subject="human:platform-admin",
        last_reason="register approval team",
        updated_at=NOW,
        eligible_now=True,
        eligibility_reason="eligible",
    )
    membership = ApprovalTeamMembership(
        tenant_id="tenant-a",
        team_subject=principal.principal_subject,
        member_subject="human:data-steward",
        membership_version=1,
        status="active",
        can_delegate=True,
        valid_from=NOW,
        last_actor_subject="human:platform-admin",
        last_reason="add team lead",
        updated_at=NOW,
    )
    access = ApprovalAssignmentActorAccess(
        actor_subject=membership.member_subject,
        can_decide=True,
        can_delegate=True,
        access_reason="team_delegate",
    )

    assert access.can_delegate is True
    with pytest.raises(ValidationError, match="type must match"):
        ApprovalPrincipal.model_validate(
            {**principal.model_dump(), "principal_type": "human"}
        )
    with pytest.raises(ValidationError, match="requires decision access"):
        ApprovalAssignmentActorAccess.model_validate(
            {**access.model_dump(), "can_decide": False}
        )


def test_approval_directory_migration_is_fail_closed_cas_and_team_aware() -> None:
    sql = (
        Path(__file__).parent / "migrations/121_approval_principal_directory.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE gda_control.approval_principal",
        "CREATE TABLE gda_control.approval_team_member",
        "CREATE TABLE gda_control.approval_principal_event",
        "CREATE TABLE gda_control.approval_team_member_event",
        "upsert_approval_principal",
        "p_expected_directory_version INTEGER",
        "upsert_approval_team_member",
        "p_expected_membership_version INTEGER",
        "approval_principal_eligibility_reason",
        "team_without_eligible_member",
        "approval_team_authorizes_actor",
        "approval_assignment_actor_access",
        "eligible independent human approver",
        "FORCE ROW LEVEL SECURITY",
        "BEFORE UPDATE OR DELETE ON gda_control.approval_principal_event",
    ):
        assert marker in sql
    assert "agent_team_members" not in sql
    assert "GRANT UPDATE" not in sql


def test_notification_claim_builds_one_tenant_scoped_event_envelope() -> None:
    case = _case()
    event = ApprovalCaseEvent(
        tenant_id="tenant-a",
        approval_event_id=UUID("00000000-0000-4000-8000-000000000091"),
        approval_case_ref=CASE_REF,
        sequence_no=0,
        to_status="pending",
        actor_subject=case.requester_subject,
        reason=case.request_reason,
        occurred_at=NOW,
    )
    notification = ApprovalCaseNotification(
        tenant_id="tenant-a",
        notification_id=UUID("00000000-0000-4000-8000-000000000101"),
        approval_case_ref=CASE_REF,
        approval_event_sequence_no=0,
        notification_kind="requested",
        channel="alertmanager",
        destination_ref="alertmanager:approval-default",
        delivery_order=0,
        status="in_flight",
        attempt_count=1,
        available_at=NOW,
        claimed_by="worker:test",
        claimed_until=NOW + timedelta(minutes=1),
        created_at=NOW,
    )
    claim_result = MagicMock()
    claim_result.mappings.return_value.all.return_value = [
        notification.model_dump(mode="python")
    ]
    case_result = MagicMock()
    case_result.mappings.return_value.one_or_none.return_value = case.model_dump(
        mode="python"
    )
    event_result = MagicMock()
    event_result.mappings.return_value.one_or_none.return_value = event.model_dump(
        mode="python"
    )
    connection = MagicMock()
    connection.execute.side_effect = [claim_result, case_result, event_result]
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = ApprovalCaseAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        envelopes = authority.claim_notifications(
            "tenant-a",
            "worker:test",
            limit=1,
            lease_seconds=30,
        )

    assert envelopes[0].approval_case == case
    assert envelopes[0].event == event
    assert connection.execute.call_args_list[0].args[1] == {
        "tenant_id": "tenant-a",
        "worker_id": "worker:test",
        "limit": 1,
        "lease_seconds": 30,
    }


def test_notification_recovery_uses_tenant_case_attempt_cas_and_human_actor() -> None:
    recovered = ApprovalCaseNotification(
        tenant_id="tenant-a",
        notification_id=UUID("00000000-0000-4000-8000-000000000104"),
        approval_case_ref=CASE_REF,
        approval_event_sequence_no=0,
        notification_kind="requested",
        channel="alertmanager",
        destination_ref="alertmanager:approval-default",
        delivery_order=0,
        status="pending",
        available_at=NOW,
        created_at=NOW,
        recovery_count=1,
        last_recovered_by="human:platform-admin",
        last_recovery_reason="receiver route repaired",
        last_recovered_at=NOW,
    )
    result = MagicMock()
    result.mappings.return_value.one.return_value = recovered.model_dump(mode="python")
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = ApprovalCaseAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        value = authority.retry_notification(
            tenant_id="tenant-a",
            approval_case_ref=CASE_REF,
            notification_id=recovered.notification_id,
            expected_attempt_count=10,
            actor_subject="human:platform-admin",
            reason="receiver route repaired",
        )

    assert value == recovered
    assert connection.execute.call_args.args[1] == {
        "tenant_id": "tenant-a",
        "approval_case_ref": CASE_REF,
        "notification_id": recovered.notification_id,
        "expected_attempt_count": 10,
        "actor_subject": "human:platform-admin",
        "reason": "receiver route repaired",
    }


def test_assignment_transition_uses_tenant_version_operation_and_derived_subjects() -> None:
    assignment = ApprovalCaseAssignment(
        tenant_id="tenant-a",
        approval_case_ref=CASE_REF,
        assignment_version=2,
        status="assigned",
        assignee_subject="human:next-steward",
        last_actor_subject="human:data-steward",
        last_reason="delegate to domain owner",
        delegation_depth=1,
        assigned_at=NOW,
        updated_at=NOW + timedelta(minutes=1),
    )
    result = MagicMock()
    result.mappings.return_value.one.return_value = assignment.model_dump(mode="python")
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = ApprovalCaseAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        value = authority.transition_assignment(
            tenant_id="tenant-a",
            approval_case_ref=CASE_REF,
            expected_assignment_version=1,
            operation=ApprovalCaseAssignmentOperation.DELEGATE,
            actor_subject="human:data-steward",
            assignee_subject="human:next-steward",
            reason="delegate to domain owner",
        )

    assert value == assignment
    assert connection.execute.call_args.args[1] == {
        "tenant_id": "tenant-a",
        "approval_case_ref": CASE_REF,
        "expected_assignment_version": 1,
        "operation": "delegate",
        "actor_subject": "human:data-steward",
        "assignee_subject": "human:next-steward",
        "reason": "delegate to domain owner",
    }
