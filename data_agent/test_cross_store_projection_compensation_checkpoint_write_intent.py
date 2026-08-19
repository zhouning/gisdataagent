from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_agent.cross_store_projection_compensation_checkpoint_admission import (
    build_federated_compensation_checkpoint_admission_request,
)
from data_agent.cross_store_projection_compensation_checkpoint_authority_read import (
    build_federated_compensation_checkpoint_authority_read_preview,
)
from data_agent.cross_store_projection_compensation_checkpoint_write_intent import (
    FederatedProjectionCompensationCheckpointWriteIntentError,
    build_federated_compensation_checkpoint_write_intent_set,
)
from data_agent.test_cross_store_projection_compensation_checkpoint_admission import (
    _admission_inputs,
)


class _ReadOnlyAuthority:
    def current(self, *, tenant_id, projection_id, target_engine, target_ref):
        return None


def _intent_set_inputs():
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()
    request = build_federated_compensation_checkpoint_admission_request(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    authority_preview = build_federated_compensation_checkpoint_authority_read_preview(
        request,
        _ReadOnlyAuthority(),
    )
    return request, authority_preview


def test_write_intent_set_is_deterministic_and_non_writing() -> None:
    request, authority_preview = _intent_set_inputs()
    intent_set = build_federated_compensation_checkpoint_write_intent_set(
        request,
        authority_preview,
        prepared_by="workload:checkpoint-admission",
        prepared_at=datetime(2026, 8, 17, 12, tzinfo=UTC),
    )
    replay = build_federated_compensation_checkpoint_write_intent_set(
        request,
        authority_preview,
        prepared_by="workload:checkpoint-admission",
        prepared_at=datetime(2026, 8, 17, 12, tzinfo=UTC),
    )

    assert intent_set.intent_set_sha256 == replay.intent_set_sha256
    assert tuple(intent.position for intent in intent_set.intents) == (0, 1, 2)
    assert all(intent.checkpoint_version == 1 for intent in intent_set.intents)
    assert all(intent.previous_checkpoint_sha256 is None for intent in intent_set.intents)
    assert all(
        intent.target_commit_ref["plan_sha256"] == intent.plan_sha256
        and intent.target_commit_ref["idempotency_key"] == intent.plan_idempotency_key
        for intent in intent_set.intents
    )
    assert intent_set.authority_admission_performed is False
    assert intent_set.authority_write_allowed is False
    assert intent_set.checkpoint_write_allowed is False
    assert intent_set.compensation_completion_allowed is False
    document = intent_set.model_dump(mode="json")
    assert "ProjectionCheckpoint" not in str(document)
    assert "record_cross_store_projection_checkpoint" not in str(document)


def test_write_intent_rejects_authority_preview_drift() -> None:
    request, authority_preview = _intent_set_inputs()
    drifted = authority_preview.model_copy(update={"admission_request_sha256": "f" * 64})

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriteIntentError,
        match="input violates|differs from admission request",
    ):
        build_federated_compensation_checkpoint_write_intent_set(
            request,
            drifted,
            prepared_by="workload:checkpoint-admission",
            prepared_at=datetime(2026, 8, 17, 12, tzinfo=UTC),
        )


def test_write_intent_requires_typed_actor_and_aware_time() -> None:
    request, authority_preview = _intent_set_inputs()

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriteIntentError,
        match="input violates",
    ):
        build_federated_compensation_checkpoint_write_intent_set(
            request,
            authority_preview,
            prepared_by="operator",
            prepared_at=datetime(2026, 8, 17, 12),
        )
