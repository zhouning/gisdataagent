from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_agent.cross_store_projection_compensation_approval import (
    build_federated_projection_compensation_execution_approval_case,
    build_federated_projection_compensation_execution_binding,
)
from data_agent.cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchError,
    build_federated_projection_compensation_dispatch_intent,
    build_federated_projection_compensation_dispatch_rule_current_binding,
)
from data_agent.cross_store_projection_compensation_execution_authority import (
    FederatedCompensationExecutionAuthorizationConsumptionReceipt,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleStatus,
    FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    assess_federated_projection_compensation_rules,
    build_customer_compensation_rule,
    build_customer_compensation_rule_contract,
)
from data_agent.test_cross_store_projection_compensation_approval import (
    _approved_review,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _build_approval_evidence,
    _trust_registry,
)


def _dispatch_inputs():
    evidence, _, review_binding, _, approved, request = _approved_review()
    execution_binding = build_federated_projection_compensation_execution_binding(
        review_binding,
        approved,
        request,
    )
    execution_case = build_federated_projection_compensation_execution_approval_case(
        execution_binding,
        request,
        requester_subject="human:operator-1",
    )
    receipt = FederatedCompensationExecutionAuthorizationConsumptionReceipt(
        tenant_id=execution_binding.tenant_id,
        execution_approval_case_ref=execution_case.approval_case_ref,
        review_approval_case_ref=execution_binding.review_approval_case_ref,
        proposal_sha256=execution_binding.proposal_sha256,
        candidate_sha256=execution_binding.candidate_sha256,
        execution_authorization_sha256=(
            execution_binding.execution_authorization_sha256
        ),
        review_binding_sha256=review_binding.binding_sha256,
        execution_decided_by="human:execution-reviewer",
        review_decided_by="human:reviewer-1",
        consumed_by="workload:controlled-compensation-executor",
        consume_reason="Reserve one approved customer-rule dispatch",
        consumed_at=datetime(2026, 8, 16, 14, tzinfo=UTC),
    )
    return evidence, execution_binding, receipt


def _updated_rule_evidence(evidence):
    def updated_contract(contract):
        rule = build_customer_compensation_rule(
            rule_id=contract.rule.rule_id,
            semantic_version="1.0.1",
            action=contract.rule.action,
            applicable_targets=contract.rule.applicable_targets,
            required_evidence=contract.rule.required_evidence,
        )
        return build_customer_compensation_rule_contract(
            tenant_id=contract.tenant_id,
            rule=rule,
            status=CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
            approval_evidence=_build_approval_evidence(rule),
        )

    contracts = tuple(updated_contract(contract) for contract in evidence.current_rules)
    assessment = assess_federated_projection_compensation_rules(
        evidence.proposal,
        contracts,
        _trust_registry(contracts),
    )
    return FederatedProjectionCompensationRuleAuthorityAssessmentEvidence(
        proposal=evidence.proposal,
        current_rules=contracts,
        assessment=assessment,
    )


def test_consumed_authorization_prepares_non_executing_dispatch_intent() -> None:
    evidence, execution_binding, receipt = _dispatch_inputs()

    intent = build_federated_projection_compensation_dispatch_intent(
        evidence,
        execution_binding,
        receipt,
    )

    assert intent.dispatch_state == "provider_adapter_pending"
    assert intent.provider_dispatch_performed is False
    assert intent.execution_allowed is False
    assert intent.review_state == "technical_baseline_unreviewed"
    assert intent.intended_use == "assisted_precheck_not_for_production_decision"
    assert tuple(binding.plan_sha256 for binding in intent.plan_bindings) == tuple(
        binding.plan_sha256
        for binding in evidence.proposal.source_bindings
        if binding.plan_sha256
        in execution_binding.review_binding.candidate_plan_sha256s
    )
    assert intent.approved_rule_ids == tuple(
        rule.rule_id for rule in execution_binding.review_binding.approved_rules
    )


def test_dispatch_intent_rejects_receipt_or_current_evidence_drift() -> None:
    evidence, execution_binding, receipt = _dispatch_inputs()

    with pytest.raises(
        FederatedProjectionCompensationDispatchError,
        match="execution ApprovalCase differs",
    ):
        build_federated_projection_compensation_dispatch_intent(
            evidence,
            execution_binding,
            receipt.model_copy(
                update={
                    "execution_approval_case_ref": (
                        f"gda://{receipt.tenant_id}/approval_case/other-execution"
                    )
                }
            ),
        )

    drifted = evidence.model_copy(
        update={"proposal": evidence.proposal.model_copy(update={"run_id": "drifted"})}
    )
    with pytest.raises(FederatedProjectionCompensationDispatchError):
        build_federated_projection_compensation_dispatch_intent(
            drifted,
            execution_binding,
            receipt,
        )


def test_dispatch_rule_current_binding_is_hash_only_and_non_authorizing() -> None:
    evidence, execution_binding, receipt = _dispatch_inputs()
    intent = build_federated_projection_compensation_dispatch_intent(
        evidence,
        execution_binding,
        receipt,
    )

    binding = build_federated_projection_compensation_dispatch_rule_current_binding(
        evidence,
        intent,
    )

    assert binding.dispatch_intent_sha256 == intent.dispatch_intent_sha256
    assert tuple(rule.rule_id for rule in binding.approved_rules) == intent.approved_rule_ids
    assert binding.customer_approval_evidence_present is True
    assert binding.customer_rules_trusted is True
    assert binding.binding_grants_execution_authority is False
    assert binding.production_execution_authorized is False
    assert binding.provider_dispatch_performed is False
    document = str(binding.model_dump(mode="json"))
    assert "public_key_pem" not in document
    assert "detached_signature_base64" not in document


def test_dispatch_rule_current_binding_rejects_approved_version_drift() -> None:
    evidence, execution_binding, receipt = _dispatch_inputs()
    intent = build_federated_projection_compensation_dispatch_intent(
        evidence,
        execution_binding,
        receipt,
    )
    updated_evidence = _updated_rule_evidence(evidence)

    with pytest.raises(
        FederatedProjectionCompensationDispatchError,
        match="differs from the sealed dispatch",
    ):
        build_federated_projection_compensation_dispatch_rule_current_binding(
            updated_evidence,
            intent,
        )
