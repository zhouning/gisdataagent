from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
    CompensationProposalImplementation,
    CompensationProposalReadiness,
    FederatedProjectionCompensationProposal,
    FederatedProjectionCompensationProposalError,
    FederatedProjectionCompensationProposalReadResponse,
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_federated_recovery import (
    FederatedProjectionRecoveryState,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    _coordinator,
    _dependencies,
    _plans,
)


def _blocked_unknown_outcome():
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )
    snapshot = _coordinator(plans, providers, authorities).advance()
    assert snapshot.state is FederatedProjectionRecoveryState.COMPENSATION_REQUIRED
    return plans, providers, snapshot


def test_proposal_binds_chongqing_dataset_ontology_and_sealed_snapshot() -> None:
    plans, providers, snapshot = _blocked_unknown_outcome()
    before = tuple(provider.execute_count for provider in providers.values())

    proposal = build_federated_projection_compensation_proposal(plans, snapshot)

    assert proposal.dataset_scope == "chongqing_customer_dataset"
    assert proposal.ontology.ontology_key == "natural-resource-one-map"
    assert proposal.ontology.semantic_version == "2.3.0"
    assert proposal.ontology.package_id == (
        "natural-resource-one-map:2.3.0:587915868b1221af"
    )
    assert proposal.source_snapshot_sha256 == snapshot.snapshot_sha256
    assert proposal.blocked_position == 1
    assert proposal.blocked_plan_sha256 == plans[1].plan_sha256
    assert proposal.review_state == "technical_baseline_unreviewed"
    assert proposal.intended_use == "assisted_precheck_not_for_production_decision"
    assert proposal.execution_allowed is False
    assert proposal.automatic_mutating_selection_allowed is False
    assert tuple(provider.execute_count for provider in providers.values()) == before
    assert FederatedProjectionCompensationProposal.model_validate(
        proposal.model_dump(mode="json")
    ) == proposal


def test_only_read_only_reconciliation_is_automatically_recommended() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()

    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    recommendation = next(
        candidate for candidate in proposal.candidates if candidate.recommended
    )

    assert recommendation.action is CompensationProposalAction.RECONCILE_PROVIDER_OUTCOME
    assert (
        recommendation.readiness
        is CompensationProposalReadiness.EVIDENCE_COLLECTION_READY
    )
    assert (
        recommendation.implementation
        is CompensationProposalImplementation.SUPPORTED_BOUNDED
    )
    assert recommendation.mutates_provider is False
    assert recommendation.approval_required is False
    assert proposal.recommended_candidate_sha256 == recommendation.candidate_sha256
    assert not any(
        candidate.recommended and candidate.mutates_provider
        for candidate in proposal.candidates
    )


def test_existing_reapply_executor_is_exposed_only_behind_approval_evidence() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()

    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    reapply = next(
        candidate
        for candidate in proposal.candidates
        if candidate.action is CompensationProposalAction.APPROVED_REAPPLY_SEALED_PLAN
    )

    assert reapply.readiness is CompensationProposalReadiness.APPROVAL_REQUIRED
    assert reapply.implementation is CompensationProposalImplementation.SUPPORTED_BOUNDED
    assert reapply.mutates_provider is True
    assert reapply.approval_required is True
    assert reapply.recommended is False
    assert set(reapply.required_evidence) == {
        "durable_worker_snapshot",
        "fresh_approval_case",
        "provider_not_committed_ruling",
        "target_identity_match",
    }


def test_unreviewed_business_actions_remain_non_executable_rule_gaps() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()

    proposal = build_federated_projection_compensation_proposal(plans, snapshot)
    customer_actions = tuple(
        candidate
        for candidate in proposal.candidates
        if candidate.implementation
        is CompensationProposalImplementation.REQUIRES_CUSTOMER_RULE
    )

    assert {
        candidate.action for candidate in customer_actions
    } == {
        CompensationProposalAction.CORRECTIVE_FORWARD,
        CompensationProposalAction.DELETE_TARGET,
        CompensationProposalAction.RESTORE_TARGET,
        CompensationProposalAction.ROLLBACK_COMMITTED_PREFIX,
    }
    assert all(
        candidate.readiness is CompensationProposalReadiness.CUSTOMER_RULE_REQUIRED
        and candidate.approval_required
        and candidate.mutates_provider
        and not candidate.recommended
        and candidate.missing_customer_rule_ids
        for candidate in customer_actions
    )
    assert set(proposal.missing_customer_rule_ids) == {
        "customer.compensation.corrective-forward.v1",
        "customer.compensation.delete.v1",
        "customer.compensation.restore.v1",
        "customer.compensation.rollback.v1",
    }


def test_failed_closed_run_does_not_guess_a_recommendation() -> None:
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "known_no_commit"},
    )
    snapshot = _coordinator(
        plans,
        providers,
        authorities,
        max_provider_attempts=1,
    ).advance()

    proposal = build_federated_projection_compensation_proposal(plans, snapshot)

    assert snapshot.state is FederatedProjectionRecoveryState.FAILED_CLOSED
    assert proposal.recommended_candidate_sha256 is None
    assert not any(candidate.recommended for candidate in proposal.candidates)
    assert all(
        candidate.implementation
        is CompensationProposalImplementation.REQUIRES_CUSTOMER_RULE
        for candidate in proposal.candidates
    )


def test_proposal_is_deterministic_and_rejects_drift_or_executable_tampering() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()

    first = build_federated_projection_compensation_proposal(plans, snapshot)
    second = build_federated_projection_compensation_proposal(plans, snapshot)
    assert first == second

    with pytest.raises(
        FederatedProjectionCompensationProposalError,
        match="plans differ",
    ):
        build_federated_projection_compensation_proposal(
            (plans[1], plans[0], plans[2]),
            snapshot,
        )

    tampered = first.model_dump(mode="json")
    tampered["execution_allowed"] = True
    with pytest.raises(ValidationError):
        FederatedProjectionCompensationProposal.model_validate(tampered)

    tampered = first.model_dump(mode="json")
    tampered["proposal_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="fingerprint"):
        FederatedProjectionCompensationProposal.model_validate(tampered)


def test_read_response_requires_one_identity_and_consistent_latest_history() -> None:
    plans, _, snapshot = _blocked_unknown_outcome()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)

    response = FederatedProjectionCompensationProposalReadResponse(
        tenant_id=snapshot.tenant_id,
        run_id=snapshot.run_id,
        current=proposal,
        history=(proposal,),
        history_count=1,
    )
    assert response.execution_allowed is False
    assert response.current == response.history[-1]

    with pytest.raises(ValidationError, match="history count"):
        FederatedProjectionCompensationProposalReadResponse(
            tenant_id=snapshot.tenant_id,
            run_id=snapshot.run_id,
            current=proposal,
            history=(proposal,),
            history_count=2,
        )
