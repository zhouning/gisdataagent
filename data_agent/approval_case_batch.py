"""Bounded batch orchestration over the existing ApprovalCase authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseAuthorityError,
    ApprovalCaseConflictError,
    ApprovalCaseForbiddenError,
    ApprovalCaseNotFoundError,
    ApprovalCaseValidationError,
)
from .platform_contracts import (
    ApprovalCaseEscalation,
    FrozenContract,
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)

ApprovalCaseBatchOutcome = Literal[
    "scheduled",
    "conflict",
    "not_found",
    "forbidden",
    "rejected",
]


class ApprovalCaseBatchEscalationItem(FrozenContract):
    """One case-scoped escalation request inside a bounded batch."""

    schema_id: Literal["gda.approval-case-batch-escalation-item.v1"] = (
        "gda.approval-case-batch-escalation-item.v1"
    )
    approval_case_ref: ResourceURNText
    expected_state_version: Annotated[int, Field(ge=0)]
    escalation_stage: Annotated[int, Field(ge=1, le=2)]
    due_at: datetime
    target_team_subject: Annotated[
        str,
        Field(pattern=r"^team:[^\s:][^\s]{0,127}$"),
    ]
    on_call_ref: Annotated[
        str,
        Field(pattern=r"^oncall:[^\s:][^\s]{0,127}$"),
    ]
    reason: NonEmptyText

    @field_validator("due_at")
    @classmethod
    def _utc_due_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("batch escalation due_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _case_identity(self) -> ApprovalCaseBatchEscalationItem:
        if parse_resource_urn(self.approval_case_ref)["resource_kind"] != "approval_case":
            raise ValueError("batch escalation item must reference an ApprovalCase")
        return self


class ApprovalCaseBatchEscalationRequest(FrozenContract):
    """A bounded request whose items keep independent authority outcomes."""

    schema_id: Literal["gda.approval-case-batch-escalation-request.v1"] = (
        "gda.approval-case-batch-escalation-request.v1"
    )
    tenant_id: TenantId
    actor_subject: Annotated[
        str,
        Field(pattern=r"^(human|workload|agent):[^\s:][^\s]{0,127}$"),
    ]
    items: tuple[ApprovalCaseBatchEscalationItem, ...] = Field(
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def _single_tenant_and_unique_cases(self) -> ApprovalCaseBatchEscalationRequest:
        case_refs = [item.approval_case_ref for item in self.items]
        if any(
            parse_resource_urn(case_ref)["tenant_id"] != self.tenant_id
            for case_ref in case_refs
        ):
            raise ValueError("batch tenant_id must match every ApprovalCase item")
        if len(case_refs) != len(set(case_refs)):
            raise ValueError("batch escalation cannot repeat an ApprovalCase")
        return self

    @property
    def request_sha256(self) -> Sha256:
        return canonical_json_fingerprint(self.model_dump(mode="json"))


class ApprovalCaseBatchEscalationResult(FrozenContract):
    """One independently authorized outcome in request order."""

    schema_id: Literal["gda.approval-case-batch-escalation-result.v1"] = (
        "gda.approval-case-batch-escalation-result.v1"
    )
    item_index: Annotated[int, Field(ge=0)]
    approval_case_ref: ResourceURNText
    outcome: ApprovalCaseBatchOutcome
    error_code: str | None = None
    escalation: ApprovalCaseEscalation | None = None

    @model_validator(mode="after")
    def _coherent_outcome(self) -> ApprovalCaseBatchEscalationResult:
        if self.outcome == "scheduled":
            if self.escalation is None or self.error_code is not None:
                raise ValueError("scheduled batch result requires only escalation evidence")
        elif self.escalation is not None or self.error_code is None:
            raise ValueError("failed batch result requires only an error code")
        return self


class ApprovalCaseBatchEscalationResponse(FrozenContract):
    """Complete partial-success result for one batch request."""

    schema_id: Literal["gda.approval-case-batch-escalation-response.v1"] = (
        "gda.approval-case-batch-escalation-response.v1"
    )
    tenant_id: TenantId
    actor_subject: str
    request_sha256: Sha256
    requested_count: Annotated[int, Field(ge=1, le=100)]
    scheduled_count: Annotated[int, Field(ge=0)]
    conflict_count: Annotated[int, Field(ge=0)]
    not_found_count: Annotated[int, Field(ge=0)]
    forbidden_count: Annotated[int, Field(ge=0)]
    rejected_count: Annotated[int, Field(ge=0)]
    results: tuple[ApprovalCaseBatchEscalationResult, ...]

    @model_validator(mode="after")
    def _counts_match_results(self) -> ApprovalCaseBatchEscalationResponse:
        if self.requested_count != len(self.results):
            raise ValueError("batch requested_count must match result count")
        expected = {
            "scheduled": self.scheduled_count,
            "conflict": self.conflict_count,
            "not_found": self.not_found_count,
            "forbidden": self.forbidden_count,
            "rejected": self.rejected_count,
        }
        actual = {
            outcome: sum(result.outcome == outcome for result in self.results)
            for outcome in expected
        }
        if actual != expected:
            raise ValueError("batch outcome counts must match results")
        return self


def _failure_outcome(error: ApprovalCaseAuthorityError) -> ApprovalCaseBatchOutcome:
    if isinstance(error, ApprovalCaseConflictError):
        return "conflict"
    if isinstance(error, ApprovalCaseNotFoundError):
        return "not_found"
    if isinstance(error, ApprovalCaseForbiddenError):
        return "forbidden"
    return "rejected"


def execute_approval_case_batch_escalation(
    request: ApprovalCaseBatchEscalationRequest,
    *,
    authority: ApprovalCaseAuthority | None = None,
) -> ApprovalCaseBatchEscalationResponse:
    """Schedule every item through the existing per-case authority boundary."""

    approvals = authority or ApprovalCaseAuthority()
    results: list[ApprovalCaseBatchEscalationResult] = []
    for item_index, item in enumerate(request.items):
        try:
            escalation = approvals.schedule_sla_escalation(
                tenant_id=request.tenant_id,
                approval_case_ref=item.approval_case_ref,
                expected_state_version=item.expected_state_version,
                escalation_stage=item.escalation_stage,
                due_at=item.due_at,
                target_team_subject=item.target_team_subject,
                on_call_ref=item.on_call_ref,
                actor_subject=request.actor_subject,
                reason=item.reason,
            )
            results.append(
                ApprovalCaseBatchEscalationResult(
                    item_index=item_index,
                    approval_case_ref=item.approval_case_ref,
                    outcome="scheduled",
                    escalation=escalation,
                )
            )
        except (
            ApprovalCaseConflictError,
            ApprovalCaseNotFoundError,
            ApprovalCaseForbiddenError,
            ApprovalCaseValidationError,
        ) as error:
            results.append(
                ApprovalCaseBatchEscalationResult(
                    item_index=item_index,
                    approval_case_ref=item.approval_case_ref,
                    outcome=_failure_outcome(error),
                    error_code=error.code,
                )
            )

    counts = {
        outcome: sum(result.outcome == outcome for result in results)
        for outcome in ("scheduled", "conflict", "not_found", "forbidden", "rejected")
    }
    return ApprovalCaseBatchEscalationResponse(
        tenant_id=request.tenant_id,
        actor_subject=request.actor_subject,
        request_sha256=request.request_sha256,
        requested_count=len(request.items),
        scheduled_count=counts["scheduled"],
        conflict_count=counts["conflict"],
        not_found_count=counts["not_found"],
        forbidden_count=counts["forbidden"],
        rejected_count=counts["rejected"],
        results=tuple(results),
    )


__all__ = [
    "ApprovalCaseBatchEscalationItem",
    "ApprovalCaseBatchEscalationRequest",
    "ApprovalCaseBatchEscalationResponse",
    "ApprovalCaseBatchEscalationResult",
    "ApprovalCaseBatchOutcome",
    "execute_approval_case_batch_escalation",
]
