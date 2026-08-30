from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.approval_case_authority import (
    ApprovalCaseConflictError,
    ApprovalCaseNotFoundError,
)
from data_agent.approval_case_batch import (
    ApprovalCaseBatchEscalationItem,
    ApprovalCaseBatchEscalationRequest,
    execute_approval_case_batch_escalation,
)
from data_agent.platform_contracts import (
    ApprovalCaseEscalation,
    approval_case_escalation_idempotency_key,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
TENANT = "tenant-a"


def _case_ref(case_id: str, *, tenant: str = TENANT) -> str:
    return f"gda://{tenant}/approval_case/{case_id}"


def _item(case_id: str, **changes) -> ApprovalCaseBatchEscalationItem:
    values = {
        "approval_case_ref": _case_ref(case_id),
        "expected_state_version": 0,
        "escalation_stage": 1,
        "due_at": NOW + timedelta(minutes=5),
        "target_team_subject": "team:data-governance",
        "on_call_ref": "oncall:data-governance",
        "reason": f"escalate {case_id}",
    }
    values.update(changes)
    return ApprovalCaseBatchEscalationItem(**values)


def _request(*items: ApprovalCaseBatchEscalationItem) -> ApprovalCaseBatchEscalationRequest:
    return ApprovalCaseBatchEscalationRequest(
        tenant_id=TENANT,
        actor_subject="workload:sla-policy-controller",
        items=items,
    )


def _escalation(item: ApprovalCaseBatchEscalationItem) -> ApprovalCaseEscalation:
    return ApprovalCaseEscalation(
        tenant_id=TENANT,
        escalation_id=UUID("00000000-0000-4000-8000-000000000120"),
        approval_case_ref=item.approval_case_ref,
        expected_state_version=item.expected_state_version,
        action="data_product.release",
        target_fingerprint="a" * 64,
        escalation_stage=item.escalation_stage,
        due_at=item.due_at,
        target_team_subject=item.target_team_subject,
        on_call_ref=item.on_call_ref,
        actor_subject="workload:sla-policy-controller",
        reason=item.reason,
        idempotency_key=approval_case_escalation_idempotency_key(
            tenant_id=TENANT,
            approval_case_ref=item.approval_case_ref,
            expected_state_version=item.expected_state_version,
            action="data_product.release",
            target_fingerprint="a" * 64,
            escalation_stage=item.escalation_stage,
            due_at=item.due_at,
            target_team_subject=item.target_team_subject,
            on_call_ref=item.on_call_ref,
        ),
        created_at=NOW,
    )


class _FakeAuthority:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def schedule_sla_escalation(self, **values):
        case_ref = values["approval_case_ref"]
        self.calls.append(case_ref)
        if case_ref.endswith("conflict"):
            raise ApprovalCaseConflictError("stale case")
        if case_ref.endswith("missing"):
            raise ApprovalCaseNotFoundError("missing case")
        return _escalation(ApprovalCaseBatchEscalationItem(**{
            key: values[key]
            for key in (
                "approval_case_ref",
                "expected_state_version",
                "escalation_stage",
                "due_at",
                "target_team_subject",
                "on_call_ref",
                "reason",
            )
        }))


def test_batch_contract_rejects_cross_tenant_and_duplicate_cases() -> None:
    with pytest.raises(ValidationError, match="tenant_id"):
        _request(_item("one", approval_case_ref=_case_ref("one", tenant="tenant-b")))
    with pytest.raises(ValidationError, match="repeat"):
        _request(_item("one"), _item("one", escalation_stage=2))
    with pytest.raises(ValidationError, match="timezone"):
        _item("naive", due_at=datetime(2026, 8, 30, 12))


def test_batch_executor_preserves_order_and_independent_outcomes() -> None:
    request = _request(_item("ok"), _item("conflict"), _item("missing"))
    authority = _FakeAuthority()

    response = execute_approval_case_batch_escalation(request, authority=authority)

    assert authority.calls == [item.approval_case_ref for item in request.items]
    assert [result.outcome for result in response.results] == [
        "scheduled",
        "conflict",
        "not_found",
    ]
    assert response.request_sha256 == request.request_sha256
    assert response.scheduled_count == 1
    assert response.conflict_count == 1
    assert response.not_found_count == 1
    assert response.rejected_count == 0


def test_batch_request_is_bounded_to_one_hundred_cases() -> None:
    with pytest.raises(ValidationError, match="at most 100"):
        _request(*(_item(f"case-{index}") for index in range(101)))
