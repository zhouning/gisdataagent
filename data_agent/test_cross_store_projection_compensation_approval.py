from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data_agent.approval_case_authority import ApprovalCaseWriteResult
from data_agent.cross_store_projection_compensation_approval import (
    COMPENSATION_CHANGE_EXECUTE_ACTION,
    COMPENSATION_CHANGE_REVIEW_ACTION,
    FederatedProjectionCompensationApprovalBinding,
    FederatedProjectionCompensationApprovalCaseRequest,
    FederatedProjectionCompensationApprovalError,
    FederatedProjectionCompensationApprovalNotFoundError,
    FederatedProjectionCompensationApprovalService,
    FederatedProjectionCompensationExecutionApprovalRequest,
    FederatedProjectionCompensationExecutionApprovalService,
    build_federated_projection_compensation_approval_binding,
    build_federated_projection_compensation_approval_case,
    build_federated_projection_compensation_execution_approval_case,
    build_federated_projection_compensation_execution_binding,
)
from data_agent.cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleStatus,
    FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    assess_federated_projection_compensation_rules,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _proposal,
    _rule_contract,
    _trust_registry,
)

NOW = datetime(2026, 8, 16, 12, tzinfo=UTC)


def _candidate(proposal, action: CompensationProposalAction):
    return next(item for item in proposal.candidates if item.action is action)


def _evidence(
    action: CompensationProposalAction = CompensationProposalAction.CORRECTIVE_FORWARD,
    *,
    status: CustomerCompensationRuleStatus | None = (
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED
    ),
    trusted: bool = True,
):
    proposal = _proposal()
    candidate = _candidate(proposal, action)
    contracts = ()
    if status is not None:
        contracts = tuple(
            _rule_contract(proposal, rule_id, status)
            for rule_id in candidate.missing_customer_rule_ids
        )
    registry = (
        _trust_registry(contracts)
        if contracts
        and trusted
        and all(contract.approval_evidence is not None for contract in contracts)
        else None
    )
    assessment = assess_federated_projection_compensation_rules(
        proposal,
        contracts,
        registry,
    )
    return (
        FederatedProjectionCompensationRuleAuthorityAssessmentEvidence(
            proposal=proposal,
            current_rules=contracts,
            assessment=assessment,
        ),
        candidate,
    )


def _request(candidate) -> FederatedProjectionCompensationApprovalCaseRequest:
    return FederatedProjectionCompensationApprovalCaseRequest(
        run_id=_proposal().run_id,
        candidate_sha256=candidate.candidate_sha256,
        idempotency_key="compensation-review-001",
        request_reason="Review the bounded corrective action evidence",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=8),
    )


def _approved_review():
    evidence, candidate = _evidence()
    binding = build_federated_projection_compensation_approval_binding(
        evidence,
        candidate.candidate_sha256,
    )
    request = _request(candidate)
    pending = build_federated_projection_compensation_approval_case(
        binding,
        request,
        requester_subject="human:operator-1",
    )
    approved = pending.__class__.model_validate(
        {
            **pending.model_dump(mode="python"),
            "status": "approved",
            "state_version": 1,
            "decided_by": "human:reviewer-1",
            "decision_reason": "Technical evidence is internally consistent",
            "decided_at": NOW + timedelta(hours=1),
        }
    )
    execution_request = FederatedProjectionCompensationExecutionApprovalRequest(
        run_id=binding.run_id,
        candidate_sha256=binding.candidate_sha256,
        review_approval_case_ref=approved.approval_case_ref,
        idempotency_key="compensation-execution-review-001",
        request_reason="Request a separate human execution verdict",
        requested_at=NOW + timedelta(hours=2),
        expires_at=NOW + timedelta(hours=6),
    )
    return evidence, candidate, binding, pending, approved, execution_request


@pytest.mark.parametrize(
    "status",
    [
        None,
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
        CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL,
    ],
)
def test_missing_or_unapproved_customer_rule_cannot_create_binding(status) -> None:
    evidence, candidate = _evidence(status=status)

    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="trusted customer rule is not ready",
    ):
        build_federated_projection_compensation_approval_binding(
            evidence,
            candidate.candidate_sha256,
        )


def test_untrusted_customer_approved_rule_cannot_create_binding() -> None:
    evidence, candidate = _evidence(trusted=False)

    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="trusted customer rule is not ready",
    ):
        build_federated_projection_compensation_approval_binding(
            evidence,
            candidate.candidate_sha256,
        )


def test_trusted_customer_rule_seals_review_only_binding_and_case() -> None:
    evidence, candidate = _evidence()

    binding = build_federated_projection_compensation_approval_binding(
        evidence,
        candidate.candidate_sha256,
    )
    request = _request(candidate)
    case = build_federated_projection_compensation_approval_case(
        binding,
        request,
        requester_subject="human:operator-1",
    )

    assert binding.candidate_action is CompensationProposalAction.CORRECTIVE_FORWARD
    assert binding.customer_rules_trusted is True
    assert binding.automatic_mutating_selection_allowed is False
    assert binding.approval_case_is_execution_authority is False
    assert binding.execution_allowed is False
    assert case.action == COMPENSATION_CHANGE_REVIEW_ACTION
    assert case.target_fingerprint == binding.binding_sha256
    assert case.request_context["approval_case_is_execution_authority"] is False
    assert case.request_context["execution_allowed"] is False


@pytest.mark.parametrize(
    "action",
    [
        CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME,
        CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN,
    ],
)
def test_reconciliation_and_reapply_candidates_are_not_customer_rule_reviews(
    action,
) -> None:
    evidence, candidate = _evidence(action, status=None)

    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="not a customer-rule governed mutating review target",
    ):
        build_federated_projection_compensation_approval_binding(
            evidence,
            candidate.candidate_sha256,
        )


def test_unknown_candidate_and_tampered_binding_fail_closed() -> None:
    evidence, candidate = _evidence()
    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="not part of proposal current",
    ):
        build_federated_projection_compensation_approval_binding(evidence, "f" * 64)

    binding = build_federated_projection_compensation_approval_binding(
        evidence,
        candidate.candidate_sha256,
    )
    tampered = binding.model_dump(mode="json")
    tampered["proposal_sha256"] = "e" * 64
    with pytest.raises(ValidationError, match="fingerprint is invalid"):
        FederatedProjectionCompensationApprovalBinding.model_validate(tampered)


def test_approval_case_requires_typed_requester_and_matching_request() -> None:
    evidence, candidate = _evidence()
    binding = build_federated_projection_compensation_approval_binding(
        evidence,
        candidate.candidate_sha256,
    )
    request = _request(candidate)

    with pytest.raises(ValidationError, match="typed subject identity"):
        build_federated_projection_compensation_approval_case(
            binding,
            request,
            requester_subject="operator-1",
        )
    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="differs from its compensation binding",
    ):
        build_federated_projection_compensation_approval_case(
            binding,
            request.model_copy(update={"candidate_sha256": "f" * 64}),
            requester_subject="human:operator-1",
        )


class _RuleAuthority:
    def __init__(self, evidence):
        self.evidence = evidence

    def assessment_evidence_current(self, run_id: str):
        if self.evidence is None or self.evidence.proposal.run_id != run_id:
            return None
        return self.evidence


class _ApprovalAuthority:
    def __init__(self):
        self.case = None

    def create(self, case, *, owner_ref: str):
        assert owner_ref == "team:data-platform"
        if self.case is None:
            self.case = case
            return ApprovalCaseWriteResult(case, True)
        assert self.case == case
        return ApprovalCaseWriteResult(case, False)


def test_service_reports_not_found_and_create_is_idempotent() -> None:
    evidence, candidate = _evidence()
    request = _request(candidate)
    with pytest.raises(FederatedProjectionCompensationApprovalNotFoundError):
        FederatedProjectionCompensationApprovalService(
            _RuleAuthority(None),
            _ApprovalAuthority(),
        ).request_review(
            request,
            requester_subject="human:operator-1",
            owner_ref="team:data-platform",
        )

    approval_authority = _ApprovalAuthority()
    service = FederatedProjectionCompensationApprovalService(
        _RuleAuthority(evidence),
        approval_authority,
    )
    first = service.request_review(
        request,
        requester_subject="human:operator-1",
        owner_ref="team:data-platform",
    )
    second = service.request_review(
        request,
        requester_subject="human:operator-1",
        owner_ref="team:data-platform",
    )

    assert first.created is True
    assert second.created is False
    assert first.approval_case == second.approval_case
    assert first.approval_case_is_execution_authority is False
    assert first.execution_allowed is False


def test_approved_review_creates_a_distinct_non_executing_execution_case() -> None:
    _, _, review_binding, pending, approved, request = _approved_review()

    execution_binding = build_federated_projection_compensation_execution_binding(
        review_binding,
        approved,
        request,
    )
    execution_case = (
        build_federated_projection_compensation_execution_approval_case(
            execution_binding,
            request,
            requester_subject="human:operator-1",
        )
    )

    assert pending.action == COMPENSATION_CHANGE_REVIEW_ACTION
    assert execution_case.action == COMPENSATION_CHANGE_EXECUTE_ACTION
    assert execution_case.approval_case_ref != pending.approval_case_ref
    assert execution_case.target_resource_urn != pending.target_resource_urn
    assert execution_case.target_fingerprint != pending.target_fingerprint
    assert execution_binding.review_approval_is_execution_authority is False
    assert execution_binding.execution_case_is_provider_execution is False
    assert execution_binding.automatic_execution_allowed is False
    assert execution_binding.provider_execution_performed is False


@pytest.mark.parametrize("review_state", ["pending", "rejected", "expired"])
def test_non_approved_or_expired_review_cannot_request_execution_verdict(
    review_state,
) -> None:
    _, _, review_binding, pending, approved, request = _approved_review()
    if review_state == "pending":
        review_case = pending
    elif review_state == "rejected":
        review_case = approved.__class__.model_validate(
            {
                **approved.model_dump(mode="python"),
                "status": "rejected",
                "decision_reason": "Technical evidence requires correction",
            }
        )
    else:
        review_case = approved
        request = request.model_copy(
            update={
                "requested_at": approved.expires_at + timedelta(minutes=1),
                "expires_at": approved.expires_at + timedelta(hours=1),
            }
        )

    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="does not authorize",
    ):
        build_federated_projection_compensation_execution_binding(
            review_binding,
            review_case,
            request,
        )


def test_review_context_or_execution_request_drift_fails_closed() -> None:
    _, _, review_binding, _, approved, request = _approved_review()
    drifted_case = approved.model_copy(
        update={"request_context": {**approved.request_context, "run_id": "other-run"}}
    )
    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="context differs",
    ):
        build_federated_projection_compensation_execution_binding(
            review_binding,
            drifted_case,
            request,
        )

    with pytest.raises(
        FederatedProjectionCompensationApprovalError,
        match="request differs",
    ):
        build_federated_projection_compensation_execution_binding(
            review_binding,
            approved,
            request.model_copy(update={"candidate_sha256": "f" * 64}),
        )


class _ExecutionApprovalAuthority(_ApprovalAuthority):
    def __init__(self, review_case):
        super().__init__()
        self.review_case = review_case

    def get(self, tenant_id: str, approval_case_ref: str):
        assert tenant_id == self.review_case.tenant_id
        assert approval_case_ref == self.review_case.approval_case_ref
        return self.review_case


def test_execution_approval_service_rechecks_authority_and_is_idempotent() -> None:
    evidence, _, _, _, approved, request = _approved_review()
    approval_authority = _ExecutionApprovalAuthority(approved)
    service = FederatedProjectionCompensationExecutionApprovalService(
        _RuleAuthority(evidence),
        approval_authority,
    )

    first = service.request_execution_authorization(
        request,
        requester_subject="human:operator-1",
        owner_ref="team:data-platform",
    )
    second = service.request_execution_authorization(
        request,
        requester_subject="human:operator-1",
        owner_ref="team:data-platform",
    )

    assert first.created is True
    assert second.created is False
    assert first.approval_case == second.approval_case
    assert first.review_approval_is_execution_authority is False
    assert first.provider_execution_performed is False
