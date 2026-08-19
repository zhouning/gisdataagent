from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from data_agent.cross_store_projection_compensation_rule_authority import (
    PostgresCustomerCompensationRuleAuthorityStore,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAssessmentStatus,
    CustomerCompensationRuleStatus,
    CustomerCompensationRuleTargetScope,
    assess_federated_projection_compensation_rules,
    build_customer_compensation_rule,
    build_customer_compensation_rule_contract,
    build_customer_compensation_rule_technical_baseline_drafts,
)
from data_agent.cross_store_projection_compensation_trust import (
    build_customer_compensation_approval_trust_registry,
)
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _proposal,
)


def test_technical_baseline_drafts_are_deterministic_and_never_approved() -> None:
    proposal = _proposal()

    first = build_customer_compensation_rule_technical_baseline_drafts(proposal)
    second = build_customer_compensation_rule_technical_baseline_drafts(proposal)

    assert first == second
    assert tuple(contract.rule.rule_id for contract in first) == (
        proposal.missing_customer_rule_ids
    )
    assert all(
        contract.status is CustomerCompensationRuleStatus.DRAFT_UNREVIEWED
        and contract.approval_evidence is None
        and contract.review_state == "technical_baseline_unreviewed"
        and contract.intended_use
        == "assisted_precheck_not_for_production_decision"
        and not contract.execution_allowed
        and not contract.automatic_mutating_selection_allowed
        for contract in first
    )
    assessment = assess_federated_projection_compensation_rules(proposal, first)
    assert assessment.draft_unreviewed_rule_ids == (
        proposal.missing_customer_rule_ids
    )
    assert all(
        item.status is CustomerCompensationRuleAssessmentStatus.DRAFT_UNREVIEWED
        for item in assessment.assessments
    )


def test_technical_baseline_bootstrap_is_idempotent_without_replacing_current() -> None:
    proposal = _proposal()
    stored = {}

    def record_if_absent(contract):
        current = stored.get(contract.rule.rule_id)
        if current is not None:
            return current, False
        stored[contract.rule.rule_id] = contract
        return contract, True

    store = PostgresCustomerCompensationRuleAuthorityStore(
        proposal.tenant_id,
        trust_registry=build_customer_compensation_approval_trust_registry(),
    )
    with patch.object(
        store,
        "_record_technical_baseline_if_absent",
        side_effect=record_if_absent,
    ):
        first = store.bootstrap_technical_baseline(proposal)
        second = store.bootstrap_technical_baseline(proposal)

    assert first.created_draft_rule_ids == proposal.missing_customer_rule_ids
    assert first.reused_current_rule_ids == ()
    assert second.created_draft_rule_ids == ()
    assert second.reused_current_rule_ids == proposal.missing_customer_rule_ids
    assert first.assessment == second.assessment
    assert second.execution_allowed is False
    assert second.automatic_mutating_selection_allowed is False


def test_technical_baseline_bootstrap_reports_existing_rule_drift() -> None:
    proposal = _proposal()
    desired = build_customer_compensation_rule_technical_baseline_drafts(proposal)
    victim = desired[0]
    original_target = victim.rule.applicable_targets[0]
    drifted_target = CustomerCompensationRuleTargetScope(
        target_engine=original_target.target_engine,
        target_ref=f"{original_target.target_ref}:outside-sealed-proposal",
    )
    drifted_rule = build_customer_compensation_rule(
        rule_id=victim.rule.rule_id,
        semantic_version=victim.rule.semantic_version,
        action=victim.rule.action,
        applicable_targets=(drifted_target,),
        required_evidence=victim.rule.required_evidence,
    )
    drifted_contract = build_customer_compensation_rule_contract(
        tenant_id=proposal.tenant_id,
        rule=drifted_rule,
        status=CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )

    def record_if_absent(contract):
        if contract.rule.rule_id == victim.rule.rule_id:
            return drifted_contract, False
        return contract, True

    store = PostgresCustomerCompensationRuleAuthorityStore(
        proposal.tenant_id,
        trust_registry=build_customer_compensation_approval_trust_registry(),
    )
    with patch.object(
        store,
        "_record_technical_baseline_if_absent",
        side_effect=record_if_absent,
    ):
        result = store.bootstrap_technical_baseline(proposal)

    assert result.reused_current_rule_ids == (victim.rule.rule_id,)
    assert result.invalid_or_drifted_rule_ids == (victim.rule.rule_id,)
    assert result.assessment.execution_allowed is False


def test_authority_assessment_reads_proposal_and_rule_current_in_one_query() -> None:
    proposal = _proposal()
    contracts = build_customer_compensation_rule_technical_baseline_drafts(proposal)
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "proposal_document": proposal.model_dump(mode="json"),
        "current_rule_documents": [
            contract.model_dump(mode="json") for contract in contracts
        ],
    }

    @contextmanager
    def transaction():
        yield connection

    store = PostgresCustomerCompensationRuleAuthorityStore(
        proposal.tenant_id,
        trust_registry=build_customer_compensation_approval_trust_registry(),
    )
    with patch.object(store, "_transaction", transaction):
        result = store.assess_current(proposal.run_id)

    assert result is not None
    assert result.proposal_sha256 == proposal.proposal_sha256
    assert result.draft_unreviewed_rule_ids == proposal.missing_customer_rule_ids
    assert result.execution_allowed is False
    connection.execute.assert_called_once()
    assert connection.execute.call_args.args[1] == {
        "tenant_id": proposal.tenant_id,
        "run_id": proposal.run_id,
    }
