from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.agentops_contracts import AgentRunStatus, AgentSideEffect
from data_agent.agentops_temporal_approval import (
    TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA,
    TEMPORAL_STEP_APPROVAL_SIGNAL_SCHEMA,
    TemporalApprovalAuthorityVerifier,
    TemporalApprovalCaseCreationResult,
    TemporalApprovalExpiryResult,
    TemporalStepApprovalBinding,
    TemporalStepApprovalInbox,
    TemporalStepApprovalSignal,
    build_temporal_approval_expiry_result,
    build_temporal_step_approval_case,
    build_temporal_step_approval_signal,
)
from data_agent.agentops_temporal_contracts import (
    TemporalSignalKind,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_task_graph_execution import (
    TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA,
    TemporalTaskGraphExecutionInput,
)
from data_agent.agentops_temporal_task_graph_runtime import (
    build_approval_case_creation_activity_definition,
    build_approval_case_expiry_activity_definition,
    build_approval_verification_activity_definition,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseAssignment,
    ApprovalCaseStatus,
)
from data_agent.test_agentops_temporal_task_graph_execution import _execution_input

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)
SIGNAL_ID = UUID("00000000-0000-4000-8000-000000003371")


class _CaseAuthority:
    def __init__(
        self,
        case: ApprovalCase | None = None,
        error: Exception | None = None,
        assignment: ApprovalCaseAssignment | None = None,
    ):
        self.case = case
        self.error = error
        self._assignment = assignment
        self.reads: list[tuple[str, str]] = []

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase:
        self.reads.append((tenant_id, approval_case_ref))
        if self.error is not None:
            raise self.error
        assert self.case is not None
        return self.case

    def create(self, case: ApprovalCase, *, owner_ref: str):
        assert owner_ref
        self.case = case
        return type("WriteResult", (), {"approval_case": case, "created": True})()

    def expire(self, **kwargs):
        if self.error is not None:
            raise self.error
        assert self.case is not None
        values = self.case.model_dump(mode="json")
        now = NOW + timedelta(hours=2)
        values.update(
            {
                "status": "cancelled",
                "state_version": 1,
                "decided_by": kwargs["actor_subject"],
                "decision_reason": kwargs["reason"],
                "decided_at": now.isoformat(),
            }
        )
        self.case = ApprovalCase.model_validate(values)
        return self.case

    def assignment(self, tenant_id: str, approval_case_ref: str):
        if self.error is not None:
            raise self.error
        if self._assignment is not None:
            return self._assignment
        assert self.case is not None and self.case.decided_at is not None
        return ApprovalCaseAssignment(
            tenant_id=tenant_id,
            approval_case_ref=approval_case_ref,
            assignment_version=2,
            status="closed",
            assignee_subject="team:geo-platform-approvers",
            last_actor_subject=self.case.decided_by or "human:geo-platform-approver",
            last_reason=f"ApprovalCase reached terminal state: {self.case.status.value}",
            assigned_at=NOW,
            updated_at=self.case.decided_at,
            closed_at=self.case.decided_at,
        )


def _binding() -> TemporalStepApprovalBinding:
    execution_input = _execution_input(
        side_effect_by_agent={"quality": AgentSideEffect.EXTERNAL_WRITE}
    )
    return execution_input.approval_bindings[0]


def _approved_case(
    binding: TemporalStepApprovalBinding,
    *,
    status: ApprovalCaseStatus = ApprovalCaseStatus.APPROVED,
    actor: str = "human:geo-platform-approver",
    reason: str = "approved exact external write",
) -> ApprovalCase:
    pending = build_temporal_step_approval_case(
        binding,
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        request_reason="external write requires independent review",
    )
    values = pending.model_dump(mode="json")
    values.update(
        {
            "status": status.value,
            "state_version": 1,
            "decided_by": actor,
            "decision_reason": reason,
            "decided_at": (NOW + timedelta(minutes=5)).isoformat(),
        }
    )
    return ApprovalCase.model_validate(values)


def _signal(
    binding: TemporalStepApprovalBinding,
    *,
    kind: TemporalSignalKind = TemporalSignalKind.APPROVE,
    actor: str = "human:geo-platform-approver",
    reason: str = "approved exact external write",
):
    return build_temporal_step_approval_signal(
        binding,
        signal_id=SIGNAL_ID,
        kind=kind,
        expected_state_version=1,
        requested_by=actor,
        reason=reason,
    )


def _rehash_binding(binding: TemporalStepApprovalBinding, **updates):
    values = binding.model_dump(mode="json")
    values.update(updates)
    values["binding_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA,
        values,
        "binding_sha256",
    )
    return TemporalStepApprovalBinding(**values)


def _rehash_signal(signal: TemporalStepApprovalSignal, **updates):
    values = signal.model_dump(mode="json")
    values.update(updates)
    values["signal_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_STEP_APPROVAL_SIGNAL_SCHEMA,
        values,
        "signal_sha256",
    )
    return TemporalStepApprovalSignal(**values)


def test_execution_input_binds_every_high_risk_step_to_exact_tool_call() -> None:
    execution_input = _execution_input(
        side_effect_by_agent={
            "coordinator": AgentSideEffect.CONTROL_WRITE,
            "quality": AgentSideEffect.EXTERNAL_WRITE,
        },
        approval_owner_ref_by_agent={
            "coordinator": "team:control-plane",
            "quality": "team:data-quality",
        },
        approver_scope_by_agent={
            "coordinator": "team:control-plane-approvers",
            "quality": "team:data-stewards",
        },
    )

    assert tuple(binding.agent_id for binding in execution_input.approval_bindings) == (
        "coordinator",
        "quality",
    )
    coordinator = execution_input.approval_bindings[0]
    assert coordinator.approval_owner_ref == "team:control-plane"
    assert coordinator.approver_scope_ref == "team:control-plane-approvers"
    assert coordinator.target_resource_urn.endswith(coordinator.tool_call_id.hex)


def test_execution_input_rejects_rehashed_cross_graph_binding() -> None:
    execution_input = _execution_input(
        side_effect_by_agent={"quality": AgentSideEffect.EXTERNAL_WRITE}
    )
    drifted = _rehash_binding(
        execution_input.approval_bindings[0],
        graph_sha256="f" * 64,
    )
    values = execution_input.model_dump(mode="json")
    values["approval_bindings"] = [drifted.model_dump(mode="json")]
    values["execution_input_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_TASK_GRAPH_EXECUTION_INPUT_SCHEMA,
        values,
        "execution_input_sha256",
    )

    with pytest.raises(ValueError, match="differs from high-risk task step"):
        TemporalTaskGraphExecutionInput(**values)


def test_binding_rejects_tool_call_or_case_identity_tampering() -> None:
    binding = _binding()
    for changes, message in (
        ({"tool_call_id": UUID(int=99)}, "ToolCall identity"),
        (
            {"approval_case_ref": "gda://tenant-b/approval_case/agentops-other"},
            "case tenant differs",
        ),
    ):
        values = binding.model_dump(mode="json")
        values.update(changes)
        values["binding_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA,
            values,
            "binding_sha256",
        )
        with pytest.raises(ValidationError, match=message):
            TemporalStepApprovalBinding(**values)


@pytest.mark.parametrize(
    ("case_factory", "signal_factory", "reason"),
    (
        (
            lambda binding: build_temporal_step_approval_case(
                binding,
                requested_at=NOW,
                expires_at=NOW + timedelta(hours=1),
                request_reason="pending review",
            ),
            _signal,
            "approval_state_version_mismatch",
        ),
        (
            _approved_case,
            lambda binding: _rehash_signal(
                _signal(binding), binding_sha256="e" * 64
            ),
            "signal_binding_mismatch",
        ),
        (
            _approved_case,
            lambda binding: _signal(binding, actor="human:different-approver"),
            "approval_decision_actor_mismatch",
        ),
    ),
)
def test_authority_verification_fails_closed_on_stale_or_drifted_evidence(
    case_factory, signal_factory, reason
) -> None:
    binding = _binding()
    authority = _CaseAuthority(case_factory(binding))
    verifier = TemporalApprovalAuthorityVerifier(authority, clock=lambda: NOW)

    result = verifier.verify(binding, signal_factory(binding))

    assert result.accepted is False
    assert result.reason_code == reason
    assert authority.reads == [(binding.tenant_id, binding.approval_case_ref)]


def test_authority_verification_accepts_matching_approved_or_rejected_case() -> None:
    binding = _binding()
    for kind, status, reason in (
        (
            TemporalSignalKind.APPROVE,
            ApprovalCaseStatus.APPROVED,
            "approved exact external write",
        ),
        (
            TemporalSignalKind.REJECT,
            ApprovalCaseStatus.REJECTED,
            "rejected exact external write",
        ),
    ):
        case = _approved_case(binding, status=status, reason=reason)
        result = TemporalApprovalAuthorityVerifier(
            _CaseAuthority(case), clock=lambda: NOW
        ).verify(binding, _signal(binding, kind=kind, reason=reason))
        assert result.accepted is True
        assert result.reason_code == "accepted"
        assert result.observed_approval_case == case


def test_authority_verification_requires_live_assignment_scope_and_actor_access() -> None:
    binding = _binding()
    case = _approved_case(binding)
    assigned = ApprovalCaseAssignment(
        tenant_id=binding.tenant_id,
        approval_case_ref=binding.approval_case_ref,
        assignment_version=2,
        status="closed",
        assignee_subject="team:other-approvers",
        last_actor_subject="human:geo-platform-approver",
        last_reason="ApprovalCase reached terminal state: approved",
        assigned_at=NOW,
        updated_at=case.decided_at,
        closed_at=case.decided_at,
    )
    authority = _CaseAuthority(case, assignment=assigned)
    result = TemporalApprovalAuthorityVerifier(authority, clock=lambda: NOW).verify(
        binding, _signal(binding)
    )
    assert result.accepted is False
    assert result.reason_code == "approval_scope_mismatch"

def test_authority_verification_fails_closed_when_case_is_not_assigned() -> None:
    binding = _binding()
    case = _approved_case(binding)
    authority = _CaseAuthority(case, assignment=None)
    authority._assignment = None
    # An eligible open-pool actor is not sufficient for a step-bound scope.
    authority.assignment = lambda tenant_id, approval_case_ref: None
    result = TemporalApprovalAuthorityVerifier(authority, clock=lambda: NOW).verify(
        binding, _signal(binding)
    )
    assert result.accepted is False
    assert result.reason_code == "approval_assignment_missing"


def test_authority_verification_rejects_open_or_mismatched_terminal_assignment() -> None:
    binding = _binding()
    case = _approved_case(binding)
    open_assignment = ApprovalCaseAssignment(
        tenant_id=binding.tenant_id,
        approval_case_ref=binding.approval_case_ref,
        assignment_version=2,
        status="assigned",
        assignee_subject=binding.approver_scope_ref,
        last_actor_subject="human:agentops-rehearsal-approver",
        last_reason="still under review",
        assigned_at=NOW,
        updated_at=NOW,
    )
    result = TemporalApprovalAuthorityVerifier(
        _CaseAuthority(case, assignment=open_assignment), clock=lambda: NOW
    ).verify(binding, _signal(binding))
    assert result.accepted is False
    assert result.reason_code == "approval_assignment_not_closed"

    mismatched_assignment = ApprovalCaseAssignment(
        tenant_id=binding.tenant_id,
        approval_case_ref=binding.approval_case_ref,
        assignment_version=3,
        status="closed",
        assignee_subject=binding.approver_scope_ref,
        last_actor_subject="human:other-approver",
        last_reason="ApprovalCase reached terminal state: approved",
        assigned_at=NOW,
        updated_at=case.decided_at,
        closed_at=case.decided_at,
    )
    result = TemporalApprovalAuthorityVerifier(
        _CaseAuthority(case, assignment=mismatched_assignment), clock=lambda: NOW
    ).verify(binding, _signal(binding))
    assert result.accepted is False
    assert result.reason_code == "approval_assignment_decision_mismatch"


def test_authority_verification_fails_closed_when_assignment_authority_is_unavailable() -> None:
    binding = _binding()
    case = _approved_case(binding)
    authority = _CaseAuthority(case)
    authority.assignment = lambda tenant_id, approval_case_ref: (_ for _ in ()).throw(
        RuntimeError("assignment projection unavailable")
    )
    result = TemporalApprovalAuthorityVerifier(authority, clock=lambda: NOW).verify(
        binding, _signal(binding)
    )
    assert result.accepted is False
    assert result.reason_code == "approval_assignment_authority_unavailable"


def test_verification_activity_returns_hash_bound_authority_observation() -> None:
    binding = _binding()
    case = _approved_case(binding)
    signal = _signal(binding)
    definition = build_approval_verification_activity_definition(
        _CaseAuthority(case), clock=lambda: NOW
    )

    result = asyncio.run(
        definition(
            {
                "binding": binding.model_dump(mode="json"),
                "signal": signal.model_dump(mode="json"),
            }
        )
    )

    assert result["accepted"] is True
    assert result["approval_case_ref"] == binding.approval_case_ref
    assert len(result["result_sha256"]) == 64


def test_creation_activity_is_idempotent_authority_boundary() -> None:
    binding = _binding()
    authority = _CaseAuthority()
    definition = build_approval_case_creation_activity_definition(authority)

    result = asyncio.run(
        definition({"binding": binding.model_dump(mode="json")})
    )
    parsed = TemporalApprovalCaseCreationResult.model_validate(result)

    assert parsed.created is True
    assert parsed.approval_case.status is ApprovalCaseStatus.PENDING
    assert parsed.approval_case.target_fingerprint == binding.binding_sha256
    assert authority.case == parsed.approval_case


def test_expired_case_contract_and_activity_bind_authoritative_cancellation() -> None:
    binding = _binding()
    pending = build_temporal_step_approval_case(
        binding,
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        request_reason="external write requires independent review",
    )
    authority = _CaseAuthority(pending)
    definition = build_approval_case_expiry_activity_definition(authority)
    result = asyncio.run(
        definition({"binding": binding.model_dump(mode="json")})
    )
    parsed = TemporalApprovalExpiryResult.model_validate(result)
    assert parsed.expired is True
    assert parsed.reason_code == "expired_cancelled"
    assert parsed.expected_state_version == 0
    assert parsed.observed_approval_case is not None
    assert parsed.observed_approval_case.status is ApprovalCaseStatus.CANCELLED
    assert parsed.observed_approval_case.decided_at is not None
    assert parsed.observed_approval_case.decided_at >= pending.expires_at


def test_expiry_result_rejects_non_cancelled_terminal_evidence() -> None:
    binding = _binding()
    case = _approved_case(binding)
    result = build_temporal_approval_expiry_result(
        binding,
        case,
        expiry_actor="workload:agentops-temporal-expiry",
        expiry_reason="expiry",
        expired_at=NOW,
    )
    assert result.expired is False
    assert result.reason_code == "approval_case_terminal_race"


def test_signal_inbox_is_idempotent_and_rejects_id_content_reuse() -> None:
    binding = _binding()
    signal = _signal(binding)
    inbox = TemporalStepApprovalInbox()

    assert inbox.submit(signal.model_dump(mode="json")) is True
    assert inbox.submit(signal.model_dump(mode="json")) is False
    assert inbox.pop() == signal
    assert inbox.has_pending is False

    changed = _rehash_signal(signal, reason="changed after signal id reuse")
    with pytest.raises(ValueError, match="reused with different content"):
        inbox.submit(changed.model_dump(mode="json"))


def test_harness_approval_resumes_or_rejection_denies_before_dispatch() -> None:
    execution_input = _execution_input(
        side_effect_by_agent={"coordinator": AgentSideEffect.CONTROL_WRITE}
    )
    workflow_input = execution_input.workflow_input
    binding = execution_input.approval_bindings[0]
    plan = execution_input.execution_manifest.plans[0]
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    harness.start_step(workflow_id, binding.step_id)
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=binding.step_id,
        tool_ref=plan.tool_ref,
        capability_ref=plan.capability_ref,
        subject_context=plan.subject_context,
        side_effect=plan.side_effect,
        policy_decision_ref=plan.policy_decision_ref,
        idempotency_key=plan.idempotency_key,
    )
    assert snapshot.execution.tool_calls[0].tool_call_id == binding.tool_call_id
    waiting = harness.wait_for_review(
        workflow_id,
        step_id=binding.step_id,
        tool_call_id=binding.tool_call_id,
    )
    assert waiting.workflow.run.status is AgentRunStatus.WAITING_REVIEW
    assert waiting.activity_schedules == ()

    from data_agent.agentops_temporal_task_graph_runtime import _project_approval_signal

    signal = _signal(binding, kind=TemporalSignalKind.REJECT, reason="rejected write")
    harness.apply_signal(
        _project_approval_signal(
            execution_input,
            signal,
            expected_state_version=waiting.workflow.run.state_version,
        )
    )
    denied = harness.deny_after_review(
        workflow_id,
        step_id=binding.step_id,
        tool_call_id=binding.tool_call_id,
    )
    assert denied.workflow.run.status is AgentRunStatus.CANCELLED
    assert denied.execution.tool_calls[0].status.value == "denied"
    assert denied.execution.step_states[0].status.value == "failed"
    assert denied.activity_schedules == ()


def test_harness_expiry_cancels_waiting_step_without_activity_schedule() -> None:
    execution_input = _execution_input(
        side_effect_by_agent={"coordinator": AgentSideEffect.CONTROL_WRITE}
    )
    workflow_input = execution_input.workflow_input
    binding = execution_input.approval_bindings[0]
    plan = execution_input.execution_manifest.plans[0]
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    harness.start(workflow_input)
    harness.start_step(workflow_id, binding.step_id)
    harness.bind_tool_call(
        workflow_id,
        step_id=binding.step_id,
        tool_ref=plan.tool_ref,
        capability_ref=plan.capability_ref,
        subject_context=plan.subject_context,
        side_effect=plan.side_effect,
        policy_decision_ref=plan.policy_decision_ref,
        idempotency_key=plan.idempotency_key,
    )
    harness.wait_for_review(
        workflow_id,
        step_id=binding.step_id,
        tool_call_id=binding.tool_call_id,
    )
    cancelled = harness.cancel_after_review(
        workflow_id,
        step_id=binding.step_id,
        tool_call_id=binding.tool_call_id,
        actor_ref="workload:agentops-temporal-expiry",
        reason="ApprovalCase expired",
    )
    assert cancelled.workflow.run.status is AgentRunStatus.CANCELLED
    assert cancelled.execution.tool_calls[0].status.value == "denied"
    assert cancelled.execution.step_states[0].status.value == "failed"
    assert cancelled.activity_schedules == ()
