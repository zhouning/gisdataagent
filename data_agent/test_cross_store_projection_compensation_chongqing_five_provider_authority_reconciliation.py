from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from data_agent.cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
)
from data_agent.cross_store_projection_compensation_completion_authority import (
    FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION,
    FederatedProjectionCompensationCompletionReceipt,
    FederatedProjectionCompensationCompletionWriteResult,
    PostgresFederatedProjectionCompensationCompletionAuthority,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_checkpoint_writer import _Authority
from data_agent.test_cross_store_projection_compensation_chongqing_five_provider_authority import (
    COMPLETED_BY,
    PREPARED_AT,
    PREPARED_BY,
    UPDATED_AT,
    WRITER_SUBJECT,
    _authority_inputs,
    _record_with_authorities,
)

from .cross_store_projection_compensation_chongqing_five_provider_authority_reconciliation import (
    ChongqingFiveProviderAuthorityReconciliationError,
    reconcile_chongqing_five_provider_authority,
    reconcile_chongqing_five_provider_postgres_authority,
)

COMPLETED_AT = datetime(2026, 8, 17, 13, 30, tzinfo=UTC)


class _CommitThenLoseResponse:
    def __init__(self, authority):
        self.authority = authority
        self.response_lost = False

    def current(self, **kwargs):
        return self.authority.current(**kwargs)

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        result = self.authority.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )
        if not self.response_lost:
            self.response_lost = True
            raise ProjectionCheckpointAuthorityConfigurationError(
                "checkpoint committed but response was lost"
            )
        return result


class _MemoryCompletionAuthority:
    def __init__(self):
        self.receipt = None
        self.record_calls = 0

    def current(self, run_id):
        if self.receipt is None or self.receipt.run_id != run_id:
            return None
        return self.receipt

    def record(self, request):
        self.record_calls += 1
        created = self.receipt is None
        if created:
            self.receipt = FederatedProjectionCompensationCompletionReceipt(
                tenant_id=request.tenant_id,
                run_id=request.run_id,
                write_request_set_sha256=request.write_request_set_sha256,
                authority_record_set_sha256=request.authority_record_set_sha256,
                targets=request.targets,
                completion_idempotency_key=request.completion_idempotency_key,
                completion_request_sha256=request.request_sha256,
                completed_by=request.completed_by,
                completed_at=COMPLETED_AT,
            )
        return FederatedProjectionCompensationCompletionWriteResult(
            receipt=self.receipt,
            created=created,
        )


def _reconcile(inputs, prior, checkpoint_authority, completion_authority, **overrides):
    arguments = {
        "prepared_by": PREPARED_BY,
        "writer_subject": WRITER_SUBJECT,
        "completed_by": COMPLETED_BY,
        "prepared_at": PREPARED_AT,
        "updated_at": UPDATED_AT,
        **overrides,
    }
    return reconcile_chongqing_five_provider_authority(
        prior,
        *inputs,
        checkpoint_authority,
        completion_authority,
        **arguments,
    )


def test_commit_then_response_loss_is_reconciled_without_provider_reexecution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _authority_inputs(monkeypatch)
    checkpoint_authority = _Authority()
    completion_authority = _MemoryCompletionAuthority()
    prior = _record_with_authorities(
        inputs,
        _CommitThenLoseResponse(checkpoint_authority),
        completion_authority,
    )

    assert prior.authority_record_set.records[0].record_status == (
        "authority_outcome_unknown"
    )
    assert prior.checkpoint_count_recorded == 0
    assert len(checkpoint_authority.ledger._current) == 1
    assert completion_authority.record_calls == 0

    reconciled = _reconcile(
        inputs,
        prior,
        checkpoint_authority,
        completion_authority,
    )

    assert reconciled.reconciliation_state == (
        "checkpoint_authority_reconciliation_completed"
    )
    assert reconciled.prior_uncertain_positions == (0,)
    assert reconciled.authority_current_replay_positions == (0,)
    assert reconciled.recovery_recorded_positions == (0, 1, 2, 3, 4)
    assert tuple(
        record.record_status
        for record in reconciled.recovery_authority_result.authority_record_set.records
    ) == (
        "idempotent_replay",
        "created",
        "created",
        "created",
        "created",
    )
    assert reconciled.compensation_completion_recorded is True
    assert reconciled.provider_execution_repeated is False
    assert completion_authority.record_calls == 1


def test_reconciliation_rejects_completed_or_timestamp_drift_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _authority_inputs(monkeypatch)
    checkpoint_authority = _Authority()
    completion_authority = _MemoryCompletionAuthority()
    completed = _record_with_authorities(
        inputs,
        checkpoint_authority,
        completion_authority,
    )
    calls_before = len(checkpoint_authority.record_calls)

    with pytest.raises(
        ChongqingFiveProviderAuthorityReconciliationError,
        match="same incomplete sealed attempt",
    ):
        _reconcile(inputs, completed, checkpoint_authority, completion_authority)

    assert len(checkpoint_authority.record_calls) == calls_before

    incomplete_authority = _Authority()
    incomplete = _record_with_authorities(
        inputs,
        _CommitThenLoseResponse(incomplete_authority),
        _MemoryCompletionAuthority(),
    )
    incomplete_calls = len(incomplete_authority.record_calls)
    with pytest.raises(
        ChongqingFiveProviderAuthorityReconciliationError,
        match="same incomplete sealed attempt",
    ):
        _reconcile(
            inputs,
            incomplete,
            incomplete_authority,
            _MemoryCompletionAuthority(),
            updated_at=UPDATED_AT + timedelta(seconds=1),
        )
    assert len(incomplete_authority.record_calls) == incomplete_calls


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_commit_response_loss_reconciles_to_five_checkpoints_and_completion(
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
        checkpoint_authority = PostgresProjectionCheckpointAuthority(
            sandbox.runtime_engine
        )
        completion_authority = (
            PostgresFederatedProjectionCompensationCompletionAuthority(
                tenant_id,
                sandbox.runtime_engine,
            )
        )
        prior = _record_with_authorities(
            inputs,
            _CommitThenLoseResponse(checkpoint_authority),
            completion_authority,
        )

        with sandbox.admin_connection() as connection:
            before = (
                connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.cross_store_projection_checkpoint_current "
                        "WHERE tenant_id = :tenant"
                    ),
                    {"tenant": tenant_id},
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control."
                        "federated_projection_compensation_checkpoint_completion "
                        "WHERE tenant_id = :tenant AND run_id = :run_id"
                    ),
                    {"tenant": tenant_id, "run_id": run_id},
                ).scalar_one(),
            )
        assert before == (1, 0)

        reconciled = reconcile_chongqing_five_provider_postgres_authority(
            prior,
            *inputs,
            sandbox.runtime_engine,
            prepared_by=PREPARED_BY,
            writer_subject=WRITER_SUBJECT,
            completed_by=COMPLETED_BY,
            prepared_at=PREPARED_AT,
            updated_at=UPDATED_AT,
        )

        with sandbox.admin_connection() as connection:
            after = (
                connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.cross_store_projection_checkpoint_current "
                        "WHERE tenant_id = :tenant"
                    ),
                    {"tenant": tenant_id},
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM "
                        "gda_control.cross_store_projection_checkpoint_history "
                        "WHERE tenant_id = :tenant"
                    ),
                    {"tenant": tenant_id},
                ).scalar_one(),
                connection.execute(
                    text(
                        "SELECT count(*) FROM gda_control."
                        "federated_projection_compensation_checkpoint_completion "
                        "WHERE tenant_id = :tenant AND run_id = :run_id"
                    ),
                    {"tenant": tenant_id, "run_id": run_id},
                ).scalar_one(),
            )
        assert after == (5, 5, 1)
        assert reconciled.authority_current_replay_positions == (0,)
        assert reconciled.compensation_completion_recorded is True
        assert reconciled.provider_execution_repeated is False
