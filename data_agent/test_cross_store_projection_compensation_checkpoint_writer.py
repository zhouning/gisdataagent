from __future__ import annotations

import os

import pytest

from data_agent.cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
    ProjectionCheckpointAuthorityForbiddenError,
)
from data_agent.cross_store_projection_compensation_checkpoint_writer import (
    FederatedProjectionCompensationCheckpointWriterError,
    record_federated_compensation_checkpoint_write_request_set,
)
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionCheckpointConflictError,
    ProjectionCheckpointWriteResult,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_checkpoint_write_request import (
    _build as _build_write_request_set,
)
from data_agent.test_cross_store_projection_compensation_checkpoint_write_request import (
    _write_request_inputs,
)


class _Authority:
    def __init__(self, *, fail_position=None, failure=None, current_override=None):
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.fail_position = fail_position
        self.failure = failure
        self.current_override = current_override or {}
        self.current_calls: list[str] = []
        self.record_calls: list[str] = []

    def current(self, *, tenant_id, projection_id, target_engine, target_ref):
        self.current_calls.append(projection_id)
        if projection_id in self.current_override:
            return self.current_override[projection_id]
        return self.ledger.current(
            tenant_id=tenant_id,
            projection_id=projection_id,
            target_engine=target_engine,
            target_ref=target_ref,
        )

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        self.record_calls.append(checkpoint.projection_id)
        if len(self.record_calls) - 1 == self.fail_position:
            raise self.failure
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )


def _request_set():
    return _build_write_request_set(_write_request_inputs())


def _record(request_set, authority):
    return record_federated_compensation_checkpoint_write_request_set(
        request_set,
        authority,
        writer_subject="workload:checkpoint-authority-writer",
    )


def test_writer_records_complete_set_and_replays_idempotently() -> None:
    request_set = _request_set()
    authority = _Authority()

    first = _record(request_set, authority)
    replay = _record(request_set, authority)

    assert first.all_checkpoints_recorded is True
    assert first.record_state == (
        "checkpoint_authority_records_complete_pending_compensation_completion"
    )
    assert tuple(record.record_status for record in first.records) == (
        "created",
        "created",
        "created",
    )
    assert tuple(record.record_status for record in replay.records) == (
        "idempotent_replay",
        "idempotent_replay",
        "idempotent_replay",
    )
    assert replay.all_checkpoints_recorded is True
    assert replay.compensation_completion_allowed is False
    assert replay.compensation_completion_recorded is False
    assert all(
        authority.ledger.current(
            tenant_id=request.tenant_id,
            projection_id=request.checkpoint.projection_id,
            target_engine=request.checkpoint.target_engine,
            target_ref=request.checkpoint.target_ref,
        )
        == request.checkpoint
        for request in request_set.requests
    )


def test_writer_preflight_drift_fails_before_first_record() -> None:
    request_set = _request_set()
    first = request_set.requests[0]
    authority = _Authority(
        current_override={
            first.checkpoint.projection_id: request_set.requests[1].checkpoint,
        }
    )

    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriterError,
        match="preflight predecessor differs",
    ):
        _record(request_set, authority)

    assert len(authority.current_calls) == 1
    assert authority.record_calls == []


def test_writer_stops_and_reports_partial_conflict() -> None:
    request_set = _request_set()
    authority = _Authority(
        fail_position=1,
        failure=ProjectionCheckpointConflictError("concurrent checkpoint"),
    )

    result = _record(request_set, authority)

    assert result.all_checkpoints_recorded is False
    assert result.record_state == ("checkpoint_authority_records_incomplete_pending_reconciliation")
    assert tuple(record.record_status for record in result.records) == (
        "created",
        "conflict",
    )
    assert result.unattempted_positions == (2,)
    assert authority.record_calls == [
        request_set.requests[0].checkpoint.projection_id,
        request_set.requests[1].checkpoint.projection_id,
    ]
    assert result.compensation_completion_allowed is False
    assert result.compensation_completion_recorded is False


def test_writer_reports_forbidden_without_attempting_later_targets() -> None:
    request_set = _request_set()
    authority = _Authority(
        fail_position=0,
        failure=ProjectionCheckpointAuthorityForbiddenError("RLS denied"),
    )

    result = _record(request_set, authority)

    assert tuple(record.record_status for record in result.records) == ("forbidden",)
    assert result.records[0].failure_code == "authority_forbidden"
    assert result.unattempted_positions == (1, 2)
    assert result.all_checkpoints_recorded is False


def test_writer_marks_authority_failure_as_unknown_and_stops() -> None:
    request_set = _request_set()
    authority = _Authority(
        fail_position=0,
        failure=ProjectionCheckpointAuthorityConfigurationError("connection lost"),
    )

    result = _record(request_set, authority)

    assert tuple(record.record_status for record in result.records) == (
        "authority_outcome_unknown",
    )
    assert result.records[0].record_state == "unknown"
    assert result.unattempted_positions == (1, 2)
    assert result.compensation_completion_allowed is False


def test_writer_rejects_mismatched_authority_response_as_unknown() -> None:
    request_set = _request_set()

    class _MismatchedAuthority(_Authority):
        def record(self, checkpoint, *, previous_checkpoint_sha256=None):
            self.record_calls.append(checkpoint.projection_id)
            return ProjectionCheckpointWriteResult(
                checkpoint=request_set.requests[1].checkpoint,
                created=True,
            )

    result = _record(request_set, _MismatchedAuthority())

    assert tuple(record.record_status for record in result.records) == (
        "authority_response_mismatch",
    )
    assert result.records[0].record_state == "unknown"
    assert result.all_checkpoints_recorded is False


def test_writer_requires_same_typed_subject_as_sealed_request() -> None:
    with pytest.raises(
        FederatedProjectionCompensationCheckpointWriterError,
        match="subject differs",
    ):
        record_federated_compensation_checkpoint_write_request_set(
            _request_set(),
            _Authority(),
            writer_subject="workload:other-writer",
        )


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_writer_real_postgres_rls_idempotency_and_current_state() -> None:
    request_set = _request_set()

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        authority = PostgresProjectionCheckpointAuthority(sandbox.runtime_engine)

        first = _record(request_set, authority)
        replay = _record(request_set, authority)

        assert first.all_checkpoints_recorded is True
        assert all(record.record_status == "created" for record in first.records)
        assert all(record.record_status == "idempotent_replay" for record in replay.records)
        assert all(
            authority.current(
                tenant_id=request.tenant_id,
                projection_id=request.checkpoint.projection_id,
                target_engine=request.checkpoint.target_engine,
                target_ref=request.checkpoint.target_ref,
            )
            == request.checkpoint
            for request in request_set.requests
        )
        assert all(
            authority.current(
                tenant_id="cq-other-tenant",
                projection_id=request.checkpoint.projection_id,
                target_engine=request.checkpoint.target_engine,
                target_ref=request.checkpoint.target_ref,
            )
            is None
            for request in request_set.requests
        )
