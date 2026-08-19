"""Fail-closed ApprovalCase admission for customer-rule compensation candidates.

This module binds an operator-selected mutating candidate to persisted proposal
and trusted customer-rule evidence. ApprovalCase is human-review evidence only;
it is deliberately not an execution authorization or Provider call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .cross_store_projection_compensation_proposal import CompensationProposalAction
from .cross_store_projection_compensation_rule_authority import (
    PostgresCustomerCompensationRuleAuthorityStore,
)
from .cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAssessmentStatus,
    CustomerCompensationRuleStatus,
    CustomerRuleId,
    FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    SemanticVersion,
)
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    NonEmptyText,
    ResourceURNText,
    Sha256,
    ShortName,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)

COMPENSATION_CHANGE_REVIEW_ACTION = "projection.federated.compensation.review"
COMPENSATION_CHANGE_EXECUTE_ACTION = "projection.federated.compensation.execute"
_CUSTOMER_RULE_ACTIONS = frozenset(
    {
        CompensationProposalAction.CORRECTIVE_FORWARD,
        CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX,
        CompensationProposalAction.DELETE_TARGET,
        CompensationProposalAction.RESTORE_TARGET,
    }
)


class FederatedProjectionCompensationApprovalError(ValueError):
    """Persisted evidence cannot admit the requested human review."""


class FederatedProjectionCompensationApprovalNotFoundError(
    FederatedProjectionCompensationApprovalError
):
    """The tenant-scoped persisted proposal does not exist."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


class TrustedCustomerCompensationRuleBinding(_FrozenModel):
    """Immutable identity of one trusted customer-approved authority current."""

    schema_id: ClassVar[str] = (
        "gda.trusted-customer-compensation-rule-binding.v1"
    )
    rule_id: CustomerRuleId
    semantic_version: SemanticVersion
    rule_sha256: Sha256
    contract_sha256: Sha256
    approval_artifact_sha256: Sha256
    trust_anchor_sha256: Sha256
    authority_status: Literal["customer_approved"] = "customer_approved"
    assessment_status: Literal["approved_but_not_executable"] = (
        "approved_but_not_executable"
    )


class FederatedProjectionCompensationApprovalBinding(_FrozenModel):
    """Sealed human-review target for one explicitly selected candidate."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-approval-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    source_snapshot_sha256: Sha256
    candidate_sha256: Sha256
    candidate_action: CompensationProposalAction
    candidate_scope: Literal["blocked_plan", "committed_prefix", "federated_run"]
    candidate_plan_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=32)
    rule_assessment_sha256: Sha256
    approved_rules: tuple[TrustedCustomerCompensationRuleBinding, ...] = Field(
        min_length=1,
        max_length=8,
    )
    selection_mode: Literal["operator_selected_for_human_review"] = (
        "operator_selected_for_human_review"
    )
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    customer_rules_trusted: Literal[True] = True
    automatic_mutating_selection_allowed: Literal[False] = False
    approval_case_is_execution_authority: Literal[False] = False
    execution_allowed: Literal[False] = False
    binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_binding(self) -> FederatedProjectionCompensationApprovalBinding:
        if self.candidate_action not in _CUSTOMER_RULE_ACTIONS:
            raise ValueError("approval binding action is not customer-rule governed")
        if tuple(sorted(set(self.candidate_plan_sha256s))) != (
            self.candidate_plan_sha256s
        ):
            raise ValueError("approval binding plan identities must be unique and sorted")
        rule_ids = tuple(rule.rule_id for rule in self.approved_rules)
        if tuple(sorted(set(rule_ids))) != rule_ids:
            raise ValueError("approval binding rules must be unique and sorted")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"binding_sha256"}),
            "binding_sha256",
        )
        if self.binding_sha256 != expected:
            raise ValueError("compensation approval binding fingerprint is invalid")
        return self

    def approval_context(self, *, idempotency_key: str) -> dict[str, Any]:
        return {
            "schema": self.schema_id,
            "binding_sha256": self.binding_sha256,
            "run_id": self.run_id,
            "proposal_sha256": self.proposal_sha256,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "candidate_sha256": self.candidate_sha256,
            "candidate_action": self.candidate_action.value,
            "candidate_plan_sha256s": list(self.candidate_plan_sha256s),
            "rule_assessment_sha256": self.rule_assessment_sha256,
            "approved_rule_contract_sha256s": [
                rule.contract_sha256 for rule in self.approved_rules
            ],
            "selection_mode": self.selection_mode,
            "review_state": self.review_state,
            "intended_use": self.intended_use,
            "idempotency_key": idempotency_key,
            "automatic_mutating_selection_allowed": False,
            "approval_case_is_execution_authority": False,
            "execution_allowed": False,
        }


class FederatedProjectionCompensationApprovalCaseRequest(_FrozenModel):
    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-approval-case-request.v1"
    )
    run_id: NonEmptyText
    candidate_sha256: Sha256
    idempotency_key: ShortName
    request_reason: NonEmptyText
    requested_at: datetime
    expires_at: datetime

    @field_validator("requested_at", "expires_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("compensation approval timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_window(self) -> FederatedProjectionCompensationApprovalCaseRequest:
        if self.expires_at <= self.requested_at:
            raise ValueError("compensation approval expiry must follow request time")
        return self


class FederatedProjectionCompensationApprovalCaseResult(_FrozenModel):
    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-approval-case-result.v1"
    )
    binding: FederatedProjectionCompensationApprovalBinding
    approval_case: ApprovalCase
    idempotency_key: ShortName
    created: bool
    candidate_selection_automatic: Literal[False] = False
    approval_case_is_execution_authority: Literal[False] = False
    execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_result(
        self,
    ) -> FederatedProjectionCompensationApprovalCaseResult:
        case = self.approval_case
        binding = self.binding
        if (
            case.tenant_id != binding.tenant_id
            or case.target_resource_urn
            != build_resource_urn(
                binding.tenant_id,
                "compensation_proposal",
                binding.proposal_sha256,
            )
            or case.target_fingerprint != binding.binding_sha256
            or case.action != COMPENSATION_CHANGE_REVIEW_ACTION
            or case.request_context
            != binding.approval_context(idempotency_key=self.idempotency_key)
        ):
            raise ValueError("ApprovalCase differs from compensation binding")
        return self


def build_federated_projection_compensation_approval_binding(
    evidence: FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    candidate_sha256: str,
) -> FederatedProjectionCompensationApprovalBinding:
    """Admit only an explicitly selected candidate with all trusted rules."""

    proposal = evidence.proposal
    candidate = next(
        (
            item
            for item in proposal.candidates
            if item.candidate_sha256 == candidate_sha256
        ),
        None,
    )
    if candidate is None:
        raise FederatedProjectionCompensationApprovalError(
            "compensation candidate is not part of proposal current"
        )
    if (
        candidate.action not in _CUSTOMER_RULE_ACTIONS
        or not candidate.mutates_provider
        or not candidate.approval_required
        or candidate.recommended
        or not candidate.missing_customer_rule_ids
    ):
        raise FederatedProjectionCompensationApprovalError(
            "candidate is not a customer-rule governed mutating review target"
        )

    assessments = {
        item.rule_id: item for item in evidence.assessment.assessments
    }
    contracts = {
        contract.rule.rule_id: contract for contract in evidence.current_rules
    }
    approved_rules = []
    for rule_id in candidate.missing_customer_rule_ids:
        item = assessments.get(rule_id)
        contract = contracts.get(rule_id)
        if (
            item is None
            or item.status
            is not CustomerCompensationRuleAssessmentStatus.APPROVED_BUT_NOT_EXECUTABLE
            or not item.customer_approval_trusted
            or item.customer_approval_trust_anchor_sha256 is None
            or contract is None
            or contract.status is not CustomerCompensationRuleStatus.CUSTOMER_APPROVED
            or contract.approval_evidence is None
        ):
            raise FederatedProjectionCompensationApprovalError(
                f"trusted customer rule is not ready: {rule_id}"
            )
        approved_rules.append(
            TrustedCustomerCompensationRuleBinding(
                rule_id=rule_id,
                semantic_version=contract.rule.semantic_version,
                rule_sha256=contract.rule.rule_sha256,
                contract_sha256=contract.contract_sha256,
                approval_artifact_sha256=(
                    contract.approval_evidence.approval_artifact_sha256
                ),
                trust_anchor_sha256=item.customer_approval_trust_anchor_sha256,
            )
        )

    values = {
        "tenant_id": proposal.tenant_id,
        "run_id": proposal.run_id,
        "proposal_sha256": proposal.proposal_sha256,
        "source_snapshot_sha256": proposal.source_snapshot_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "candidate_action": candidate.action,
        "candidate_scope": candidate.scope,
        "candidate_plan_sha256s": candidate.plan_sha256s,
        "rule_assessment_sha256": evidence.assessment.assessment_sha256,
        "approved_rules": tuple(
            rule.model_dump(mode="json") for rule in approved_rules
        ),
        "selection_mode": "operator_selected_for_human_review",
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
        "customer_rules_trusted": True,
        "automatic_mutating_selection_allowed": False,
        "approval_case_is_execution_authority": False,
        "execution_allowed": False,
    }
    return FederatedProjectionCompensationApprovalBinding(
        **values,
        binding_sha256=_fingerprint(
            FederatedProjectionCompensationApprovalBinding.schema_id,
            values,
            "binding_sha256",
        ),
    )


def build_federated_projection_compensation_approval_case(
    binding: FederatedProjectionCompensationApprovalBinding,
    request: FederatedProjectionCompensationApprovalCaseRequest,
    *,
    requester_subject: str,
) -> ApprovalCase:
    if request.run_id != binding.run_id or (
        request.candidate_sha256 != binding.candidate_sha256
    ):
        raise FederatedProjectionCompensationApprovalError(
            "approval request differs from its compensation binding"
        )
    return ApprovalCase(
        tenant_id=binding.tenant_id,
        approval_case_ref=build_resource_urn(
            binding.tenant_id,
            "approval_case",
            f"compensation-{binding.binding_sha256}",
        ),
        target_resource_urn=build_resource_urn(
            binding.tenant_id,
            "compensation_proposal",
            binding.proposal_sha256,
        ),
        target_fingerprint=binding.binding_sha256,
        action=COMPENSATION_CHANGE_REVIEW_ACTION,
        requester_subject=requester_subject,
        request_reason=request.request_reason,
        request_context=binding.approval_context(
            idempotency_key=request.idempotency_key
        ),
        requested_at=request.requested_at,
        expires_at=request.expires_at,
    )


class FederatedProjectionCompensationApprovalService:
    """Create review-only ApprovalCase records from authority current evidence."""

    def __init__(
        self,
        rule_authority: PostgresCustomerCompensationRuleAuthorityStore,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._rule_authority = rule_authority
        self._approval_authority = approval_authority

    def request_review(
        self,
        request: FederatedProjectionCompensationApprovalCaseRequest,
        *,
        requester_subject: str,
        owner_ref: str,
    ) -> FederatedProjectionCompensationApprovalCaseResult:
        evidence = self._rule_authority.assessment_evidence_current(request.run_id)
        if evidence is None:
            raise FederatedProjectionCompensationApprovalNotFoundError(
                "persisted compensation proposal was not found"
            )
        binding = build_federated_projection_compensation_approval_binding(
            evidence,
            request.candidate_sha256,
        )
        case = build_federated_projection_compensation_approval_case(
            binding,
            request,
            requester_subject=requester_subject,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return FederatedProjectionCompensationApprovalCaseResult(
            binding=binding,
            approval_case=written.approval_case,
            idempotency_key=request.idempotency_key,
            created=written.created,
        )


class FederatedProjectionCompensationExecutionApprovalRequest(_FrozenModel):
    """Request a separate execution verdict after an approved review verdict."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-execution-approval-request.v1"
    )
    run_id: NonEmptyText
    candidate_sha256: Sha256
    review_approval_case_ref: ResourceURNText
    idempotency_key: ShortName
    request_reason: NonEmptyText
    requested_at: datetime
    expires_at: datetime

    @field_validator("requested_at", "expires_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution approval timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bounded_window(
        self,
    ) -> FederatedProjectionCompensationExecutionApprovalRequest:
        if self.expires_at <= self.requested_at:
            raise ValueError("execution approval expiry must follow request time")
        return self


class FederatedProjectionCompensationExecutionBinding(_FrozenModel):
    """Second-stage execution verdict target, still not a Provider invocation."""

    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-execution-binding.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    candidate_action: CompensationProposalAction
    review_approval_case_ref: ResourceURNText
    review_binding: FederatedProjectionCompensationApprovalBinding
    review_case_status: Literal["approved"] = "approved"
    review_case_state_version: Literal[1] = 1
    review_decided_by: NonEmptyText
    review_decided_at: datetime
    review_expires_at: datetime
    authorization_mode: Literal["separate_human_execution_verdict_required"] = (
        "separate_human_execution_verdict_required"
    )
    review_approval_is_execution_authority: Literal[False] = False
    execution_case_is_provider_execution: Literal[False] = False
    automatic_execution_allowed: Literal[False] = False
    provider_execution_performed: Literal[False] = False
    execution_authorization_sha256: Sha256

    @field_validator("review_decided_at", "review_expires_at")
    @classmethod
    def _aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review approval timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _sealed_execution_binding(
        self,
    ) -> FederatedProjectionCompensationExecutionBinding:
        review = self.review_binding
        if (
            self.tenant_id != review.tenant_id
            or self.run_id != review.run_id
            or self.proposal_sha256 != review.proposal_sha256
            or self.candidate_sha256 != review.candidate_sha256
            or self.candidate_action is not review.candidate_action
        ):
            raise ValueError("execution binding differs from approved review binding")
        if not self.review_decided_by.startswith("human:"):
            raise ValueError("execution binding review verdict must use human identity")
        if self.review_expires_at <= self.review_decided_at:
            raise ValueError("execution binding review expiry is invalid")
        identity = parse_resource_urn(self.review_approval_case_ref)
        if (
            identity["tenant_id"] != self.tenant_id
            or identity["resource_kind"] != "approval_case"
        ):
            raise ValueError("execution binding review case tenant differs")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(
                mode="json",
                exclude={"execution_authorization_sha256"},
            ),
            "execution_authorization_sha256",
        )
        if self.execution_authorization_sha256 != expected:
            raise ValueError("compensation execution binding fingerprint is invalid")
        return self

    def approval_context(self, *, idempotency_key: str) -> dict[str, Any]:
        return {
            "schema": self.schema_id,
            "execution_authorization_sha256": (
                self.execution_authorization_sha256
            ),
            "run_id": self.run_id,
            "proposal_sha256": self.proposal_sha256,
            "candidate_sha256": self.candidate_sha256,
            "candidate_action": self.candidate_action.value,
            "review_approval_case_ref": self.review_approval_case_ref,
            "review_binding_sha256": self.review_binding.binding_sha256,
            "approved_rules": [
                rule.model_dump(mode="json")
                for rule in self.review_binding.approved_rules
            ],
            "authorization_mode": self.authorization_mode,
            "idempotency_key": idempotency_key,
            "review_approval_is_execution_authority": False,
            "execution_case_is_provider_execution": False,
            "automatic_execution_allowed": False,
            "provider_execution_performed": False,
        }


class FederatedProjectionCompensationExecutionApprovalResult(_FrozenModel):
    schema_id: ClassVar[str] = (
        "gda.federated-projection-compensation-execution-approval-result.v1"
    )
    execution_binding: FederatedProjectionCompensationExecutionBinding
    approval_case: ApprovalCase
    idempotency_key: ShortName
    created: bool
    review_approval_is_execution_authority: Literal[False] = False
    execution_case_is_provider_execution: Literal[False] = False
    automatic_execution_allowed: Literal[False] = False
    provider_execution_performed: Literal[False] = False

    @model_validator(mode="after")
    def _consistent_result(
        self,
    ) -> FederatedProjectionCompensationExecutionApprovalResult:
        binding = self.execution_binding
        case = self.approval_case
        if (
            case.tenant_id != binding.tenant_id
            or case.target_resource_urn
            != build_resource_urn(
                binding.tenant_id,
                "compensation_candidate",
                binding.candidate_sha256,
            )
            or case.target_fingerprint
            != binding.execution_authorization_sha256
            or case.action != COMPENSATION_CHANGE_EXECUTE_ACTION
            or case.request_context
            != binding.approval_context(idempotency_key=self.idempotency_key)
        ):
            raise ValueError("execution ApprovalCase differs from sealed binding")
        return self


def build_federated_projection_compensation_execution_binding(
    review_binding: FederatedProjectionCompensationApprovalBinding,
    review_case: ApprovalCase,
    request: FederatedProjectionCompensationExecutionApprovalRequest,
) -> FederatedProjectionCompensationExecutionBinding:
    """Require an exact approved review case before requesting execution review."""

    if (
        request.run_id != review_binding.run_id
        or request.candidate_sha256 != review_binding.candidate_sha256
        or request.review_approval_case_ref != review_case.approval_case_ref
    ):
        raise FederatedProjectionCompensationApprovalError(
            "execution approval request differs from review binding"
        )
    idempotency_key = review_case.request_context.get("idempotency_key")
    if not isinstance(idempotency_key, str) or (
        review_case.request_context
        != review_binding.approval_context(idempotency_key=idempotency_key)
    ):
        raise FederatedProjectionCompensationApprovalError(
            "review ApprovalCase context differs from current trusted binding"
        )
    if (
        review_case.action != COMPENSATION_CHANGE_REVIEW_ACTION
        or review_case.status is not ApprovalCaseStatus.APPROVED
        or review_case.state_version != 1
        or review_case.decided_by is None
        or review_case.decided_at is None
        or review_case.target_resource_urn
        != build_resource_urn(
            review_binding.tenant_id,
            "compensation_proposal",
            review_binding.proposal_sha256,
        )
        or review_case.target_fingerprint != review_binding.binding_sha256
        or review_case.decided_at > request.requested_at
        or review_case.expires_at <= request.requested_at
        or request.expires_at > review_case.expires_at
    ):
        raise FederatedProjectionCompensationApprovalError(
            "review ApprovalCase does not authorize an execution verdict request"
        )
    values = {
        "tenant_id": review_binding.tenant_id,
        "run_id": review_binding.run_id,
        "proposal_sha256": review_binding.proposal_sha256,
        "candidate_sha256": review_binding.candidate_sha256,
        "candidate_action": review_binding.candidate_action,
        "review_approval_case_ref": review_case.approval_case_ref,
        "review_binding": review_binding,
        "review_case_status": "approved",
        "review_case_state_version": 1,
        "review_decided_by": review_case.decided_by,
        "review_decided_at": review_case.decided_at,
        "review_expires_at": review_case.expires_at,
        "authorization_mode": "separate_human_execution_verdict_required",
        "review_approval_is_execution_authority": False,
        "execution_case_is_provider_execution": False,
        "automatic_execution_allowed": False,
        "provider_execution_performed": False,
    }
    fingerprint_values = (
        FederatedProjectionCompensationExecutionBinding.model_construct(
            **values,
            execution_authorization_sha256="0" * 64,
        ).model_dump(
            mode="json",
            exclude={"execution_authorization_sha256"},
        )
    )
    return FederatedProjectionCompensationExecutionBinding(
        **values,
        execution_authorization_sha256=_fingerprint(
            FederatedProjectionCompensationExecutionBinding.schema_id,
            fingerprint_values,
            "execution_authorization_sha256",
        ),
    )


def build_federated_projection_compensation_execution_approval_case(
    binding: FederatedProjectionCompensationExecutionBinding,
    request: FederatedProjectionCompensationExecutionApprovalRequest,
    *,
    requester_subject: str,
) -> ApprovalCase:
    if (
        request.run_id != binding.run_id
        or request.candidate_sha256 != binding.candidate_sha256
        or request.review_approval_case_ref != binding.review_approval_case_ref
    ):
        raise FederatedProjectionCompensationApprovalError(
            "execution approval request differs from sealed execution binding"
        )
    return ApprovalCase(
        tenant_id=binding.tenant_id,
        approval_case_ref=build_resource_urn(
            binding.tenant_id,
            "approval_case",
            f"compensation-execute-{binding.execution_authorization_sha256}",
        ),
        target_resource_urn=build_resource_urn(
            binding.tenant_id,
            "compensation_candidate",
            binding.candidate_sha256,
        ),
        target_fingerprint=binding.execution_authorization_sha256,
        action=COMPENSATION_CHANGE_EXECUTE_ACTION,
        requester_subject=requester_subject,
        request_reason=request.request_reason,
        request_context=binding.approval_context(
            idempotency_key=request.idempotency_key
        ),
        requested_at=request.requested_at,
        expires_at=request.expires_at,
    )


class FederatedProjectionCompensationExecutionApprovalService:
    """Request a second verdict without treating review approval as execution."""

    def __init__(
        self,
        rule_authority: PostgresCustomerCompensationRuleAuthorityStore,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._rule_authority = rule_authority
        self._approval_authority = approval_authority

    def request_execution_authorization(
        self,
        request: FederatedProjectionCompensationExecutionApprovalRequest,
        *,
        requester_subject: str,
        owner_ref: str,
    ) -> FederatedProjectionCompensationExecutionApprovalResult:
        evidence = self._rule_authority.assessment_evidence_current(request.run_id)
        if evidence is None:
            raise FederatedProjectionCompensationApprovalNotFoundError(
                "persisted compensation proposal was not found"
            )
        review_binding = build_federated_projection_compensation_approval_binding(
            evidence,
            request.candidate_sha256,
        )
        review_case = self._approval_authority.get(
            review_binding.tenant_id,
            request.review_approval_case_ref,
        )
        execution_binding = (
            build_federated_projection_compensation_execution_binding(
                review_binding,
                review_case,
                request,
            )
        )
        case = build_federated_projection_compensation_execution_approval_case(
            execution_binding,
            request,
            requester_subject=requester_subject,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return FederatedProjectionCompensationExecutionApprovalResult(
            execution_binding=execution_binding,
            approval_case=written.approval_case,
            idempotency_key=request.idempotency_key,
            created=written.created,
        )


__all__ = [
    "COMPENSATION_CHANGE_EXECUTE_ACTION",
    "COMPENSATION_CHANGE_REVIEW_ACTION",
    "FederatedProjectionCompensationApprovalBinding",
    "FederatedProjectionCompensationApprovalCaseRequest",
    "FederatedProjectionCompensationApprovalCaseResult",
    "FederatedProjectionCompensationApprovalError",
    "FederatedProjectionCompensationApprovalNotFoundError",
    "FederatedProjectionCompensationApprovalService",
    "FederatedProjectionCompensationExecutionApprovalRequest",
    "FederatedProjectionCompensationExecutionApprovalResult",
    "FederatedProjectionCompensationExecutionApprovalService",
    "FederatedProjectionCompensationExecutionBinding",
    "TrustedCustomerCompensationRuleBinding",
    "build_federated_projection_compensation_approval_binding",
    "build_federated_projection_compensation_approval_case",
    "build_federated_projection_compensation_execution_approval_case",
    "build_federated_projection_compensation_execution_binding",
]
