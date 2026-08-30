"""Step-bound HITL contracts for governed Temporal write activities.

Temporal owns the durable wait. ``ApprovalCaseAuthority`` remains the only approval
authority: a read-only verification activity reloads the case before the workflow can
dispatch the bound provider activity.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from .agentops_contracts import AgentRole, AgentSideEffect
from .agentops_task_execution import derive_agent_tool_call_id
from .agentops_temporal_contracts import (
    TemporalSignalKind,
    temporal_contract_fingerprint,
)
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseAssignmentStatus,
    ApprovalCaseStatus,
    FrozenContract,
    NonEmptyText,
    ResourceURNText,
    Sha256,
    SubjectContext,
    TenantId,
    build_resource_urn,
    parse_resource_urn,
)

TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA = "gda.temporal_step_approval_binding.v1"
TEMPORAL_STEP_APPROVAL_SIGNAL_SCHEMA = "gda.temporal_step_approval_signal.v1"
TEMPORAL_APPROVAL_VERIFICATION_RESULT_SCHEMA = (
    "gda.temporal_approval_verification_result.v1"
)
TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE = "gda.agentops.approval.verify"
TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE = "gda.agentops.approval.create"
TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE = "gda.agentops.approval.expire"
TEMPORAL_APPROVAL_SIGNAL_NAME = "gda_agentops_step_approval"
TEMPORAL_APPROVAL_QUERY_NAME = "gda_agentops_pending_approval"
TEMPORAL_APPROVAL_ACTION = "agentops.tool_call.execute"

_HIGH_RISK_SIDE_EFFECTS = frozenset(
    {AgentSideEffect.CONTROL_WRITE, AgentSideEffect.EXTERNAL_WRITE}
)


class ApprovalCaseReader(Protocol):
    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase: ...


class ApprovalCaseWriter(ApprovalCaseReader, Protocol):
    def create(self, case: ApprovalCase, *, owner_ref: str) -> Any: ...

    def expire(
        self,
        *,
        tenant_id: str,
        approval_case_ref: str,
        expected_state_version: int,
        actor_subject: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> ApprovalCase: ...


class TemporalStepApprovalBinding(FrozenContract):
    """Immutable identity of the exact write action submitted for human review."""

    schema_id: ClassVar[str] = TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    graph_sha256: Sha256
    step_id: UUID
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    role: AgentRole
    tool_call_id: UUID
    tool_ref: NonEmptyText
    capability_ref: NonEmptyText
    policy_decision_ref: NonEmptyText
    subject_context: SubjectContext
    side_effect: AgentSideEffect
    idempotency_key: NonEmptyText
    approval_case_ref: ResourceURNText
    approval_owner_ref: NonEmptyText
    approver_scope_ref: NonEmptyText
    expected_approval_state_version: int = Field(default=1, ge=1)
    action: NonEmptyText = TEMPORAL_APPROVAL_ACTION
    binding_sha256: Sha256

    @property
    def target_resource_urn(self) -> str:
        return build_resource_urn(
            self.tenant_id,
            "agent_tool_call",
            self.tool_call_id.hex,
        )

    def approval_request_context(self) -> dict[str, Any]:
        return {
            "schema": self.schema_id,
            "workflow_id": self.workflow_id,
            "run_id": str(self.run_id),
            "graph_sha256": self.graph_sha256,
            "step_id": str(self.step_id),
            "agent_id": self.agent_id,
            "role": self.role.value,
            "tool_call_id": str(self.tool_call_id),
            "tool_ref": self.tool_ref,
            "capability_ref": self.capability_ref,
            "policy_decision_ref": self.policy_decision_ref,
            "side_effect": self.side_effect.value,
            "idempotency_key": self.idempotency_key,
            "approval_owner_ref": self.approval_owner_ref,
            "approver_scope_ref": self.approver_scope_ref,
            "expected_approval_state_version": self.expected_approval_state_version,
            "binding_sha256": self.binding_sha256,
        }

    @model_validator(mode="after")
    def _consistent_binding(self) -> TemporalStepApprovalBinding:
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("approval binding subject tenant differs")
        if self.side_effect not in _HIGH_RISK_SIDE_EFFECTS:
            raise ValueError("approval binding requires a high-risk side effect")
        if self.expected_approval_state_version != 1:
            raise ValueError("ApprovalCase currently supports decision state version one")
        identity = parse_resource_urn(self.approval_case_ref)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("approval binding case tenant differs")
        if identity["resource_kind"] != "approval_case":
            raise ValueError("approval binding must reference an ApprovalCase")
        expected_tool_call_id = derive_agent_tool_call_id(
            run_id=self.run_id,
            step_id=self.step_id,
            idempotency_key=self.idempotency_key,
        )
        if self.tool_call_id != expected_tool_call_id:
            raise ValueError("approval binding ToolCall identity differs")
        expected = temporal_contract_fingerprint(
            self.schema_id,
            self.model_dump(mode="json"),
            "binding_sha256",
        )
        if self.binding_sha256 != expected:
            raise ValueError("binding_sha256 does not match approval binding")
        return self


class TemporalStepApprovalSignal(FrozenContract):
    """One untrusted signal request; authority is checked by an activity before use."""

    schema_id: ClassVar[str] = TEMPORAL_STEP_APPROVAL_SIGNAL_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    signal_id: UUID
    kind: TemporalSignalKind
    expected_state_version: int = Field(ge=0)
    approval_case_ref: ResourceURNText
    binding_sha256: Sha256
    requested_by: NonEmptyText
    reason: NonEmptyText
    signal_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_signal(self) -> TemporalStepApprovalSignal:
        if self.kind not in {TemporalSignalKind.APPROVE, TemporalSignalKind.REJECT}:
            raise ValueError("step approval signal must approve or reject")
        expected = temporal_contract_fingerprint(
            self.schema_id,
            self.model_dump(mode="json"),
            "signal_sha256",
        )
        if self.signal_sha256 != expected:
            raise ValueError("signal_sha256 does not match step approval signal")
        return self


class TemporalApprovalVerificationResult(FrozenContract):
    """Authority observation recorded in Temporal history before write dispatch."""

    schema_id: ClassVar[str] = TEMPORAL_APPROVAL_VERIFICATION_RESULT_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    signal_id: UUID
    signal_sha256: Sha256
    binding_sha256: Sha256
    approval_case_ref: ResourceURNText
    accepted: bool
    reason_code: NonEmptyText
    observed_approval_case: ApprovalCase | None = None
    verified_at: datetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalApprovalVerificationResult:
        if self.verified_at.tzinfo is None:
            raise ValueError("approval verification timestamp must be timezone-aware")
        if self.accepted != (self.reason_code == "accepted"):
            raise ValueError("approval verification disposition differs from reason")
        if self.accepted and self.observed_approval_case is None:
            raise ValueError("accepted approval verification requires authority evidence")
        expected = temporal_contract_fingerprint(
            self.schema_id,
            self.model_dump(mode="json"),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match approval verification")
        return self


class TemporalApprovalCaseCreationResult(FrozenContract):
    """Idempotent ApprovalCase creation receipt recorded by Temporal."""

    schema_id: ClassVar[str] = "gda.temporal_approval_case_creation_result.v1"
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    binding_sha256: Sha256
    approval_case_ref: ResourceURNText
    created: bool
    approval_case: ApprovalCase
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalApprovalCaseCreationResult:
        if self.approval_case.tenant_id != self.tenant_id:
            raise ValueError("created ApprovalCase tenant differs")
        if self.approval_case.approval_case_ref != self.approval_case_ref:
            raise ValueError("created ApprovalCase ref differs")
        if self.approval_case.target_fingerprint != self.binding_sha256:
            raise ValueError("created ApprovalCase fingerprint differs")
        expected = temporal_contract_fingerprint(
            self.schema_id,
            self.model_dump(mode="json"),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match ApprovalCase creation")
        return self


TEMPORAL_APPROVAL_EXPIRY_RESULT_SCHEMA = "gda.temporal_approval_expiry_result.v1"


class TemporalApprovalExpiryResult(FrozenContract):
    """Authoritative expiry observation recorded before workflow cancellation."""

    schema_id: ClassVar[str] = TEMPORAL_APPROVAL_EXPIRY_RESULT_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    binding_sha256: Sha256
    approval_case_ref: ResourceURNText
    expected_state_version: int = Field(ge=0)
    expiry_actor: NonEmptyText
    expiry_reason: NonEmptyText
    expired: bool
    reason_code: NonEmptyText
    observed_approval_case: ApprovalCase | None = None
    expired_at: datetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalApprovalExpiryResult:
        if self.expired:
            if self.reason_code != "expired_cancelled":
                raise ValueError("expired result must record expired_cancelled")
            if self.observed_approval_case is None:
                raise ValueError("expired result requires cancelled ApprovalCase evidence")
            if self.observed_approval_case.status is not ApprovalCaseStatus.CANCELLED:
                raise ValueError("expired result requires a cancelled ApprovalCase")
        expected = temporal_contract_fingerprint(
            self.schema_id,
            self.model_dump(mode="json"),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match approval expiry")
        return self


class TemporalStepApprovalInbox:
    """Deterministic FIFO with exact duplicate idempotency for workflow signals."""

    def __init__(self) -> None:
        self._signals: dict[UUID, TemporalStepApprovalSignal] = {}
        self._pending: list[TemporalStepApprovalSignal] = []

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    def submit(self, payload: dict[str, Any]) -> bool:
        signal = TemporalStepApprovalSignal.model_validate(payload)
        existing = self._signals.get(signal.signal_id)
        if existing is not None:
            if existing != signal:
                raise ValueError("approval signal id was reused with different content")
            return False
        self._signals[signal.signal_id] = signal
        self._pending.append(signal)
        return True

    def pop(self) -> TemporalStepApprovalSignal:
        if not self._pending:
            raise ValueError("approval signal inbox is empty")
        return self._pending.pop(0)


def compile_temporal_step_approval_binding(
    *,
    tenant_id: str,
    workflow_id: str,
    run_id: UUID,
    graph_sha256: str,
    step_id: UUID,
    agent_id: str,
    role: AgentRole,
    tool_ref: str,
    capability_ref: str,
    policy_decision_ref: str,
    subject_context: SubjectContext,
    side_effect: AgentSideEffect,
    idempotency_key: str,
    approval_owner_ref: str,
    approver_scope_ref: str,
) -> TemporalStepApprovalBinding:
    tool_call_id = derive_agent_tool_call_id(
        run_id=run_id,
        step_id=step_id,
        idempotency_key=idempotency_key,
    )
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "graph_sha256": graph_sha256,
        "step_id": step_id,
        "agent_id": agent_id,
        "role": role,
        "tool_call_id": tool_call_id,
        "tool_ref": tool_ref,
        "capability_ref": capability_ref,
        "policy_decision_ref": policy_decision_ref,
        "subject_context": subject_context,
        "side_effect": side_effect,
        "idempotency_key": idempotency_key,
        "approval_case_ref": build_resource_urn(
            tenant_id,
            "approval_case",
            f"agentops-{tool_call_id.hex}",
        ),
        "approval_owner_ref": approval_owner_ref,
        "approver_scope_ref": approver_scope_ref,
        "expected_approval_state_version": 1,
        "action": TEMPORAL_APPROVAL_ACTION,
    }
    values["binding_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA,
        values,
        "binding_sha256",
    )
    return TemporalStepApprovalBinding(**values)


def build_temporal_step_approval_case(
    binding: TemporalStepApprovalBinding,
    *,
    requested_at: datetime,
    expires_at: datetime,
    request_reason: str,
) -> ApprovalCase:
    """Create the pending case submitted to the existing PostgreSQL authority."""

    return ApprovalCase(
        tenant_id=binding.tenant_id,
        approval_case_ref=binding.approval_case_ref,
        target_resource_urn=binding.target_resource_urn,
        target_fingerprint=binding.binding_sha256,
        action=binding.action,
        requester_subject=binding.subject_context.subject_id,
        request_reason=request_reason,
        request_context=binding.approval_request_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


def build_temporal_step_approval_signal(
    binding: TemporalStepApprovalBinding,
    *,
    signal_id: UUID,
    kind: TemporalSignalKind,
    expected_state_version: int,
    requested_by: str,
    reason: str,
) -> TemporalStepApprovalSignal:
    values: dict[str, Any] = {
        "tenant_id": binding.tenant_id,
        "workflow_id": binding.workflow_id,
        "run_id": binding.run_id,
        "signal_id": signal_id,
        "kind": kind,
        "expected_state_version": expected_state_version,
        "approval_case_ref": binding.approval_case_ref,
        "binding_sha256": binding.binding_sha256,
        "requested_by": requested_by,
        "reason": reason,
    }
    values["signal_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_STEP_APPROVAL_SIGNAL_SCHEMA,
        values,
        "signal_sha256",
    )
    return TemporalStepApprovalSignal(**values)


def build_temporal_approval_case_creation_result(
    binding: TemporalStepApprovalBinding,
    case: ApprovalCase,
    *,
    created: bool,
) -> TemporalApprovalCaseCreationResult:
    values: dict[str, Any] = {
        "tenant_id": binding.tenant_id,
        "workflow_id": binding.workflow_id,
        "run_id": binding.run_id,
        "step_id": binding.step_id,
        "binding_sha256": binding.binding_sha256,
        "approval_case_ref": binding.approval_case_ref,
        "created": created,
        "approval_case": case,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalApprovalCaseCreationResult.schema_id,
        values,
        "result_sha256",
    )
    return TemporalApprovalCaseCreationResult(**values)


def derive_approval_verification_activity_id(
    binding: TemporalStepApprovalBinding,
    signal: TemporalStepApprovalSignal,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"gda-agentops-approval-verify:{binding.run_id}:{binding.step_id}:{signal.signal_id}",
    )


def derive_approval_expiry_activity_id(binding: TemporalStepApprovalBinding) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"gda-agentops-approval-expire:{binding.run_id}:{binding.step_id}",
    )


def build_temporal_approval_expiry_result(
    binding: TemporalStepApprovalBinding,
    case: ApprovalCase,
    *,
    expiry_actor: str,
    expiry_reason: str,
    expired_at: datetime,
) -> TemporalApprovalExpiryResult:
    values: dict[str, Any] = {
        "tenant_id": binding.tenant_id,
        "workflow_id": binding.workflow_id,
        "run_id": binding.run_id,
        "step_id": binding.step_id,
        "tool_call_id": binding.tool_call_id,
        "binding_sha256": binding.binding_sha256,
        "approval_case_ref": binding.approval_case_ref,
        "expected_state_version": binding.expected_approval_state_version - 1,
        "expiry_actor": expiry_actor,
        "expiry_reason": expiry_reason,
        "expired": case.status is ApprovalCaseStatus.CANCELLED,
        "reason_code": (
            "expired_cancelled"
            if case.status is ApprovalCaseStatus.CANCELLED
            else "approval_case_terminal_race"
        ),
        "observed_approval_case": case,
        "expired_at": expired_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_APPROVAL_EXPIRY_RESULT_SCHEMA,
        values,
        "result_sha256",
    )
    return TemporalApprovalExpiryResult(**values)


def _case_rejection_reason(
    binding: TemporalStepApprovalBinding,
    signal: TemporalStepApprovalSignal,
    case: ApprovalCase,
    *,
    now: datetime,
) -> str | None:
    if (
        signal.tenant_id != binding.tenant_id
        or signal.workflow_id != binding.workflow_id
        or signal.run_id != binding.run_id
        or signal.binding_sha256 != binding.binding_sha256
        or signal.approval_case_ref != binding.approval_case_ref
    ):
        return "signal_binding_mismatch"
    if (
        case.tenant_id != binding.tenant_id
        or case.approval_case_ref != binding.approval_case_ref
        or case.target_resource_urn != binding.target_resource_urn
        or case.target_fingerprint != binding.binding_sha256
        or case.action != binding.action
        or case.requester_subject != binding.subject_context.subject_id
        or case.request_context != binding.approval_request_context()
    ):
        return "approval_case_binding_mismatch"
    if case.state_version != binding.expected_approval_state_version:
        return "approval_state_version_mismatch"
    if case.expires_at <= now:
        return "approval_case_expired"
    expected_status = (
        ApprovalCaseStatus.APPROVED
        if signal.kind is TemporalSignalKind.APPROVE
        else ApprovalCaseStatus.REJECTED
    )
    if case.status is not expected_status:
        return "approval_status_mismatch"
    if case.decided_by != signal.requested_by or case.decision_reason != signal.reason:
        return "approval_decision_actor_mismatch"
    if not signal.requested_by.startswith("human:"):
        return "approval_actor_not_human"
    if case.request_context.get("approver_scope_ref") != binding.approver_scope_ref:
        return "approval_scope_mismatch"
    return None


def _assignment_rejection_reason(
    binding: TemporalStepApprovalBinding,
    signal: TemporalStepApprovalSignal,
    case: ApprovalCase,
    authority: Any,
) -> str | None:
    """Bind a terminal verdict to the assignment closed by that exact decision."""

    assignment_reader = getattr(authority, "assignment", None)
    if not callable(assignment_reader):
        return "approval_assignment_authority_unavailable"
    try:
        assignment = assignment_reader(
            binding.tenant_id,
            binding.approval_case_ref,
        )
    except Exception:
        return "approval_assignment_authority_unavailable"
    if assignment is None:
        return "approval_assignment_missing"
    if assignment.assignee_subject != binding.approver_scope_ref:
        return "approval_scope_mismatch"
    if assignment.status is not ApprovalCaseAssignmentStatus.CLOSED:
        return "approval_assignment_not_closed"
    if (
        assignment.last_actor_subject != signal.requested_by
        or assignment.closed_at != case.decided_at
        or assignment.updated_at != case.decided_at
    ):
        return "approval_assignment_decision_mismatch"
    if (
        assignment.assignee_subject.startswith("human:")
        and assignment.assignee_subject != signal.requested_by
    ):
        return "approval_assignment_actor_mismatch"
    return None


class TemporalApprovalAuthorityVerifier:
    """Read and validate one ApprovalCase without granting approval itself."""

    def __init__(
        self,
        authority: ApprovalCaseReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authority = authority
        self._clock = clock or (lambda: datetime.now(UTC))

    def verify(
        self,
        binding: TemporalStepApprovalBinding,
        signal: TemporalStepApprovalSignal,
    ) -> TemporalApprovalVerificationResult:
        case: ApprovalCase | None = None
        try:
            case = self._authority.get(
                binding.tenant_id,
                binding.approval_case_ref,
            )
            reason = _case_rejection_reason(
                binding,
                signal,
                case,
                now=self._clock(),
            )
            if reason is None:
                reason = _assignment_rejection_reason(
                    binding,
                    signal,
                    case,
                    self._authority,
                )
        except Exception:
            reason = "approval_authority_unavailable"
        values: dict[str, Any] = {
            "tenant_id": binding.tenant_id,
            "workflow_id": binding.workflow_id,
            "run_id": binding.run_id,
            "step_id": binding.step_id,
            "tool_call_id": binding.tool_call_id,
            "signal_id": signal.signal_id,
            "signal_sha256": signal.signal_sha256,
            "binding_sha256": binding.binding_sha256,
            "approval_case_ref": binding.approval_case_ref,
            "accepted": reason is None,
            "reason_code": "accepted" if reason is None else reason,
            "observed_approval_case": (
                case.model_dump(mode="json") if case is not None else None
            ),
            "verified_at": self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        values["result_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_APPROVAL_VERIFICATION_RESULT_SCHEMA,
            values,
            "result_sha256",
        )
        return TemporalApprovalVerificationResult(**values)


__all__ = [
    "TEMPORAL_APPROVAL_ACTION",
    "TEMPORAL_APPROVAL_CREATE_ACTIVITY_TYPE",
    "TEMPORAL_APPROVAL_EXPIRE_ACTIVITY_TYPE",
    "TEMPORAL_APPROVAL_QUERY_NAME",
    "TEMPORAL_APPROVAL_SIGNAL_NAME",
    "TEMPORAL_APPROVAL_VERIFICATION_RESULT_SCHEMA",
    "TEMPORAL_APPROVAL_EXPIRY_RESULT_SCHEMA",
    "TEMPORAL_APPROVAL_VERIFY_ACTIVITY_TYPE",
    "TEMPORAL_STEP_APPROVAL_BINDING_SCHEMA",
    "TEMPORAL_STEP_APPROVAL_SIGNAL_SCHEMA",
    "TemporalApprovalAuthorityVerifier",
    "TemporalApprovalCaseCreationResult",
    "TemporalApprovalExpiryResult",
    "TemporalApprovalVerificationResult",
    "TemporalStepApprovalBinding",
    "TemporalStepApprovalInbox",
    "TemporalStepApprovalSignal",
    "build_temporal_step_approval_case",
    "build_temporal_approval_case_creation_result",
    "build_temporal_step_approval_signal",
    "compile_temporal_step_approval_binding",
    "derive_approval_verification_activity_id",
    "derive_approval_expiry_activity_id",
    "build_temporal_approval_expiry_result",
]
