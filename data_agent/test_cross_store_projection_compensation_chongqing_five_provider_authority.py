from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from data_agent.cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
)
from data_agent.cross_store_projection_compensation_chongqing_five_provider_authority import (
    ChongqingFederatedCompensationFiveProviderAuthorityValidationError,
    record_chongqing_federated_compensation_five_provider_authority,
    record_chongqing_federated_compensation_five_provider_postgres_authority,
)
from data_agent.cross_store_projection_compensation_completion_authority import (
    FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION,
    PostgresFederatedProjectionCompensationCompletionAuthority,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionCheckpointConflictError,
    ProjectionTargetObservation,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_checkpoint_writer import _Authority
from data_agent.test_cross_store_projection_compensation_chongqing_five_provider_execution import (
    _execute_five_provider_inputs,
    _five_provider_inputs,
    _five_provider_registry,
)

PREPARED_BY = "workload:chongqing-five-provider-checkpoint-preparer"
WRITER_SUBJECT = "workload:chongqing-five-provider-checkpoint-writer"
COMPLETED_BY = "workload:chongqing-five-provider-completion-writer"
PREPARED_AT = datetime(2026, 8, 17, 12, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 17, 12, 30, tzinfo=UTC)
UPDATED_AT = datetime(2026, 8, 17, 13, tzinfo=UTC)


class _CompletionMustNotRun:
    def __init__(self):
        self.current_calls = 0
        self.record_calls = 0

    def current(self, run_id):
        self.current_calls += 1
        return None

    def record(self, request):
        self.record_calls += 1
        raise AssertionError("incomplete checkpoint set must not invoke completion")


def _authority_inputs(monkeypatch: pytest.MonkeyPatch):
    inputs = _five_provider_inputs(monkeypatch)
    materialization = inputs[2]
    requests = inputs[-2]
    request_bundle = inputs[-1]
    registry, calls = _five_provider_registry(materialization)
    execution_result = _execute_five_provider_inputs(
        inputs,
        registry,
        request_bundle=request_bundle,
        requests=requests,
    )
    repair_plans = tuple(
        request.execution_plan.source_plan
        for request in sorted(
            requests.values(),
            key=lambda item: item.execution_plan.position,
        )
    )
    observations = tuple(
        ProjectionTargetObservation(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_engine=plan.target_engine,
            target_ref=plan.target_ref,
            target_exists=plan.desired_state.target_exists,
            observed_content_sha256=(
                plan.desired_state.expected_target_content_sha256
            ),
            observed_row_count=plan.desired_state.expected_row_count,
            observed_by="workload:chongqing-five-provider-final-observer",
            observed_at=OBSERVED_AT,
        )
        for plan in repair_plans
    )
    assert len(calls) == 5
    return (
        execution_result,
        request_bundle,
        inputs[1],
        materialization,
        repair_plans,
        observations,
    )


def _record_with_authorities(inputs, checkpoint_authority, completion_authority):
    return record_chongqing_federated_compensation_five_provider_authority(
        *inputs,
        checkpoint_authority,
        completion_authority,
        prepared_by=PREPARED_BY,
        writer_subject=WRITER_SUBJECT,
        completed_by=COMPLETED_BY,
        prepared_at=PREPARED_AT,
        updated_at=UPDATED_AT,
    )


def _record_postgres(inputs, engine):
    return record_chongqing_federated_compensation_five_provider_postgres_authority(
        *inputs,
        engine,
        prepared_by=PREPARED_BY,
        writer_subject=WRITER_SUBJECT,
        completed_by=COMPLETED_BY,
        prepared_at=PREPARED_AT,
        updated_at=UPDATED_AT,
    )


def test_partial_checkpoint_record_set_never_invokes_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _authority_inputs(monkeypatch)
    checkpoint_authority = _Authority(
        fail_position=1,
        failure=ProjectionCheckpointConflictError("concurrent checkpoint"),
    )
    completion_authority = _CompletionMustNotRun()

    result = _record_with_authorities(
        inputs,
        checkpoint_authority,
        completion_authority,
    )

    assert result.authority_state == (
        "checkpoint_authority_records_incomplete_pending_reconciliation"
    )
    assert result.checkpoint_count_recorded == 1
    assert result.authority_record_set.unattempted_positions == (2, 3, 4)
    assert result.compensation_completion_recorded is False
    assert result.completion_authority_record_invoked is False
    assert completion_authority.current_calls == 0
    assert completion_authority.record_calls == 0


@pytest.mark.parametrize("drift", ["observation", "request_bundle"])
def test_input_drift_is_rejected_before_first_authority_write(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    inputs = list(_authority_inputs(monkeypatch))
    if drift == "observation":
        observations = inputs[5]
        inputs[5] = (
            observations[0].model_copy(update={"observed_content_sha256": "f" * 64}),
            *observations[1:],
        )
    else:
        inputs[1] = inputs[1].model_copy(update={"request_bundle_sha256": "f" * 64})
    checkpoint_authority = _Authority()

    with pytest.raises(
        ChongqingFederatedCompensationFiveProviderAuthorityValidationError,
        match="before the first checkpoint write|violates a sealed contract",
    ):
        _record_with_authorities(
            tuple(inputs),
            checkpoint_authority,
            _CompletionMustNotRun(),
        )

    assert checkpoint_authority.record_calls == []


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_five_provider_authority_is_rls_isolated_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _authority_inputs(monkeypatch)
    tenant_id = inputs[0].tenant_id
    run_id = inputs[0].run_id

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )

        first = _record_postgres(inputs, sandbox.runtime_engine)
        replay = _record_postgres(inputs, sandbox.runtime_engine)

        assert first.authority_state == (
            "five_provider_compensation_completion_recorded"
        )
        assert first.checkpoint_count_recorded == 5
        assert first.completion_created is True
        assert first.completion_authority_record_invoked is True
        assert all(
            record.record_status == "created"
            for record in first.authority_record_set.records
        )
        assert replay.authority_state == (
            "five_provider_compensation_completion_reused"
        )
        assert replay.completion_created is False
        assert replay.completion_authority_record_invoked is False
        assert all(
            record.record_status == "idempotent_replay"
            for record in replay.authority_record_set.records
        )
        assert all(
            snapshot.authority_current_state == "requested_checkpoint_replay"
            for snapshot in replay.authority_read_preview.snapshots
        )

        with sandbox.admin_connection() as connection:
            current_count = connection.execute(
                text(
                    "SELECT count(*) FROM "
                    "gda_control.cross_store_projection_checkpoint_current "
                    "WHERE tenant_id = :tenant"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
            history_count = connection.execute(
                text(
                    "SELECT count(*) FROM "
                    "gda_control.cross_store_projection_checkpoint_history "
                    "WHERE tenant_id = :tenant"
                ),
                {"tenant": tenant_id},
            ).scalar_one()
            completion_count = connection.execute(
                text(
                    "SELECT count(*) FROM gda_control."
                    "federated_projection_compensation_checkpoint_completion "
                    "WHERE tenant_id = :tenant AND run_id = :run_id"
                ),
                {"tenant": tenant_id, "run_id": run_id},
            ).scalar_one()
        assert (current_count, history_count, completion_count) == (5, 5, 1)

        checkpoint_authority = PostgresProjectionCheckpointAuthority(
            sandbox.runtime_engine
        )
        assert all(
            checkpoint_authority.current(
                tenant_id="cq-other-tenant",
                projection_id=request.checkpoint.projection_id,
                target_engine=request.checkpoint.target_engine,
                target_ref=request.checkpoint.target_ref,
            )
            is None
            for request in first.write_request_set.requests
        )
        assert (
            PostgresFederatedProjectionCompensationCompletionAuthority(
                "cq-other-tenant",
                sandbox.runtime_engine,
            ).current(run_id)
            is None
        )
