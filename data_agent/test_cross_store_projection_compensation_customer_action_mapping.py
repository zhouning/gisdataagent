from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_customer_action_mapping import (
    CustomerCompensationRuleProviderActionMap,
    build_customer_compensation_rule_provider_action_map,
)
from data_agent.cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleStatus,
)
from data_agent.test_cross_store_projection_compensation_approval import _evidence
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _rule_contract,
)


def _signed_mapping():
    evidence, candidate = _evidence()
    rule_id = candidate.missing_customer_rule_ids[0]
    contract = next(
        item for item in evidence.current_rules if item.rule.rule_id == rule_id
    )
    mapping = build_customer_compensation_rule_provider_action_map(
        evidence.proposal,
        candidate.candidate_sha256,
        contract.rule,
    )
    return evidence, candidate, contract, mapping


def test_customer_signed_action_map_covers_every_corrective_provider_plan() -> None:
    evidence, candidate, contract, mapping = _signed_mapping()

    assert candidate.action is CompensationProposalAction.CORRECTIVE_FORWARD
    assert mapping.tenant_id == evidence.proposal.tenant_id
    assert mapping.run_id == evidence.proposal.run_id
    assert mapping.candidate_sha256 == candidate.candidate_sha256
    assert mapping.customer_rule_sha256 == contract.rule.rule_sha256
    assert tuple(item.position for item in mapping.items) == tuple(
        range(len(evidence.proposal.source_bindings))
    )
    assert tuple(item.plan_sha256 for item in mapping.items) == tuple(
        binding.plan_sha256 for binding in evidence.proposal.source_bindings
    )
    assert {item.provider_action for item in mapping.items} == {"rebuild"}
    assert {
        item.unknown_outcome_policy for item in mapping.items
    } == {"observe_receipt_and_target_then_resume_if_safe"}
    assert contract.approval_evidence is not None
    assert (
        contract.approval_evidence.approval_artifact_sha256
        == mapping.action_map_sha256
    )
    assert mapping.production_execution_authorized is False
    assert mapping.provider_dispatch_performed is False


def test_customer_action_map_item_tampering_breaks_the_sealed_contract() -> None:
    _, _, _, mapping = _signed_mapping()
    document = mapping.model_dump(mode="json")
    document["items"][0]["provider_action"] = "delete"

    with pytest.raises(ValidationError, match="fingerprint"):
        CustomerCompensationRuleProviderActionMap.model_validate(document)


@pytest.mark.parametrize(
    ("action", "expected_provider_action"),
    (
        (CompensationProposalAction.DELETE_TARGET, "delete"),
        (CompensationProposalAction.RESTORE_TARGET, "rebuild"),
    ),
)
def test_customer_action_map_uses_customer_semantics_for_delete_and_restore(
    action: CompensationProposalAction,
    expected_provider_action: str,
) -> None:
    evidence, candidate = _evidence(action)
    rule_id = candidate.missing_customer_rule_ids[0]
    contract = next(
        item for item in evidence.current_rules if item.rule.rule_id == rule_id
    )

    mapping = build_customer_compensation_rule_provider_action_map(
        evidence.proposal,
        candidate.candidate_sha256,
        contract.rule,
    )

    assert {item.provider_action for item in mapping.items} == {
        expected_provider_action
    }
    assert contract.approval_evidence is not None
    assert (
        contract.approval_evidence.approval_artifact_sha256
        == mapping.action_map_sha256
    )


def test_rollback_cannot_be_signed_without_customer_derived_reverse_plans() -> None:
    evidence, candidate = _evidence(
        CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX,
        status=None,
    )
    rule_id = candidate.missing_customer_rule_ids[0]
    contract = _rule_contract(
        evidence.proposal,
        rule_id,
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )
    with pytest.raises(ValueError, match="reverse plans"):
        build_customer_compensation_rule_provider_action_map(
            evidence.proposal,
            candidate.candidate_sha256,
            contract.rule,
        )
