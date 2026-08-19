from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_agent.cross_store_projection_compensation_checkpoint_write_intent import (
    build_federated_compensation_checkpoint_write_intent_set,
)
from data_agent.cross_store_projection_compensation_checkpoint_write_request import (
    FederatedProjectionCompensationCheckpointWriteRequestError,
    build_federated_compensation_checkpoint_write_request_set,
)
from data_agent.cross_store_projection_consistency import ProjectionTargetObservation
from data_agent.test_cross_store_projection_compensation_checkpoint_write_intent import (
    _intent_set_inputs,
)

UPDATED_AT = datetime(2026, 8, 17, 12, tzinfo=UTC)


def _write_request_inputs():
    request, authority_preview = _intent_set_inputs()
    intent_set = build_federated_compensation_checkpoint_write_intent_set(
        request,
        authority_preview,
        prepared_by="workload:checkpoint-admission",
        prepared_at=UPDATED_AT,
    )
    observations = tuple(
        ProjectionTargetObservation(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_engine=plan.target_engine,
            target_ref=plan.target_ref,
            target_exists=plan.desired_state.target_exists,
            observed_content_sha256=(plan.desired_state.expected_target_content_sha256),
            observed_row_count=plan.desired_state.expected_row_count,
            observed_by="workload:checkpoint-final-observer",
            observed_at=datetime(2026, 8, 17, 11, tzinfo=UTC),
        )
        for plan in request.repair_plans
    )
    return request, authority_preview, intent_set, observations


def _build(inputs, *, observations=None, updated_at=UPDATED_AT):
    request, authority_preview, intent_set, default_observations = inputs
    return build_federated_compensation_checkpoint_write_request_set(
        request,
        authority_preview,
        intent_set,
        default_observations if observations is None else observations,
        updated_by="workload:checkpoint-authority-writer",
        updated_at=updated_at,
    )


def test_write_request_set_binds_three_final_observations_deterministically() -> None:
    inputs = _write_request_inputs()

    request_set = _build(inputs)
    replay = _build(inputs)

    assert request_set.request_set_sha256 == replay.request_set_sha256
    assert tuple(request.position for request in request_set.requests) == (0, 1, 2)
    assert all(request.checkpoint.checkpoint_version == 1 for request in request_set.requests)
    assert all(
        request.checkpoint.target_content_sha256
        == request.final_observation.observed_content_sha256
        for request in request_set.requests
    )
    assert all(
        request.checkpoint.target_commit_ref["plan_sha256"] == request.plan_sha256
        and request.checkpoint.target_commit_ref["idempotency_key"] == request.plan_idempotency_key
        for request in request_set.requests
    )
    assert request_set.write_state == "checkpoint_write_requests_pending_authority_record"


def test_write_request_rejects_final_target_content_drift() -> None:
    inputs = _write_request_inputs()
    observations = inputs[3]
    drifted = observations[0].model_copy(update={"observed_content_sha256": "f" * 64})

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriteRequestError,
        match="final target observation differs",
    ):
        _build(inputs, observations=(drifted, *observations[1:]))


def test_write_request_rejects_missing_or_duplicate_final_observation() -> None:
    inputs = _write_request_inputs()
    observations = inputs[3]

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriteRequestError,
        match="cover every intent target exactly once",
    ):
        _build(inputs, observations=observations[:-1])

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriteRequestError,
        match="must be unique",
    ):
        _build(inputs, observations=(*observations, observations[0]))


def test_write_request_rejects_checkpoint_time_before_final_observation() -> None:
    inputs = _write_request_inputs()

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriteRequestError,
        match="cannot produce a checkpoint write request",
    ):
        _build(
            inputs,
            updated_at=datetime(2026, 8, 17, 10, 59, tzinfo=UTC),
        )


def test_write_request_set_remains_non_writing() -> None:
    request_set = _build(_write_request_inputs())

    assert request_set.authority_admission_performed is False
    assert request_set.authority_write_allowed is False
    assert request_set.checkpoint_write_allowed is False
    assert request_set.compensation_completion_allowed is False
    assert all(
        request.authority_admission_performed is False
        and request.authority_write_allowed is False
        and request.checkpoint_write_allowed is False
        and request.compensation_completion_allowed is False
        for request in request_set.requests
    )
    document = request_set.model_dump(mode="json")
    assert "record_cross_store_projection_checkpoint" not in str(document)
    assert "checkpoint_write_request_pending_authority_record" in str(document)
