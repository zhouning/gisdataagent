from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_checkpoint_candidate import (
    FederatedProjectionCompensationCheckpointCandidateError,
    FederatedProjectionCompensationCheckpointPredecessor,
    build_federated_compensation_checkpoint_candidate_set,
)
from data_agent.cross_store_projection_compensation_provider_receipt_set import (
    build_federated_compensation_provider_receipt_validation_set,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


def _candidate_inputs():
    intent, plan_set, materialization, validations = _receipt_set_inputs()
    receipt_set = build_federated_compensation_provider_receipt_validation_set(
        intent,
        plan_set,
        materialization,
        validations,
    )
    predecessors = tuple(
        FederatedProjectionCompensationCheckpointPredecessor(
            position=binding.position,
            tenant_id=materialization.tenant_id,
            projection_id=binding.projection_id,
            target_engine=binding.target_engine,
            target_ref=binding.target_ref,
            previous_checkpoint_sha256=None,
            next_checkpoint_version=1,
        )
        for binding in materialization.bindings
    )
    return receipt_set, plan_set, materialization, predecessors


def test_checkpoint_candidate_set_is_complete_but_non_writing() -> None:
    receipt_set, plan_set, materialization, predecessors = _candidate_inputs()

    candidate_set = build_federated_compensation_checkpoint_candidate_set(
        receipt_set,
        plan_set,
        materialization,
        predecessors,
    )
    replay = build_federated_compensation_checkpoint_candidate_set(
        receipt_set,
        plan_set,
        materialization,
        predecessors,
    )

    assert candidate_set.candidate_set_sha256 == replay.candidate_set_sha256
    assert tuple(item.position for item in candidate_set.candidates) == (0, 1, 2)
    assert all(item.next_checkpoint_version == 1 for item in candidate_set.candidates)
    assert all(item.previous_checkpoint_sha256 is None for item in candidate_set.candidates)
    assert candidate_set.candidate_state == ("checkpoint_candidates_pending_authority_admission")
    assert candidate_set.authority_admission_performed is False
    assert candidate_set.authority_write_allowed is False
    assert candidate_set.checkpoint_write_allowed is False
    assert candidate_set.compensation_completion_allowed is False
    assert all(
        item.authority_write_allowed is False and item.checkpoint_write_allowed is False
        for item in candidate_set.candidates
    )
    document = candidate_set.model_dump(mode="json")
    assert "receipt_document" not in str(document)
    assert "provider_commit_ref" not in str(document)
    assert candidate_set.candidates[0].target_engine is ProjectionEngine.POSTGIS


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_checkpoint_candidates_require_every_predecessor_exactly_once(mode: str) -> None:
    receipt_set, plan_set, materialization, predecessors = _candidate_inputs()
    invalid = predecessors[:-1] if mode == "missing" else (*predecessors, predecessors[0])

    with pytest.raises(
        FederatedProjectionCompensationCheckpointCandidateError,
        match="predecessors",
    ):
        build_federated_compensation_checkpoint_candidate_set(
            receipt_set,
            plan_set,
            materialization,
            invalid,
        )


def test_checkpoint_candidate_rejects_predecessor_target_drift() -> None:
    receipt_set, plan_set, materialization, predecessors = _candidate_inputs()
    drifted = predecessors[0].model_copy(update={"target_ref": "postgis://drifted"})
    invalid = (drifted, *predecessors[1:])

    with pytest.raises(
        FederatedProjectionCompensationCheckpointCandidateError,
        match="predecessor or receipt outcome",
    ):
        build_federated_compensation_checkpoint_candidate_set(
            receipt_set,
            plan_set,
            materialization,
            invalid,
        )


def test_checkpoint_predecessor_version_requires_a_real_successor() -> None:
    with pytest.raises(ValidationError, match="initial checkpoint candidate"):
        FederatedProjectionCompensationCheckpointPredecessor(
            position=0,
            tenant_id="cq-federated-recovery",
            projection_id="customer-projection-0",
            target_engine=ProjectionEngine.POSTGIS,
            target_ref="postgis://cq-customer/cq.federated.postgis",
            next_checkpoint_version=2,
        )

    predecessor = FederatedProjectionCompensationCheckpointPredecessor(
        position=0,
        tenant_id="cq-federated-recovery",
        projection_id="customer-projection-0",
        target_engine=ProjectionEngine.POSTGIS,
        target_ref="postgis://cq-customer/cq.federated.postgis",
        previous_checkpoint_sha256="a" * 64,
        next_checkpoint_version=2,
    )
    assert predecessor.next_checkpoint_version == 2
