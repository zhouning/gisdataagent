from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
)
from data_agent.cross_store_projection_compensation_checkpoint_writer import (
    record_federated_compensation_checkpoint_write_request_set,
)
from data_agent.cross_store_projection_compensation_completion_authority import (
    FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION,
    FederatedProjectionCompensationCompletionAdmissionError,
    FederatedProjectionCompensationCompletionAuthorityConfigurationError,
    FederatedProjectionCompensationCompletionAuthorityForbiddenError,
    FederatedProjectionCompensationCompletionAuthorityValidationError,
    PostgresFederatedProjectionCompensationCompletionAuthority,
    build_federated_projection_compensation_completion_request,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    projection_checkpoint_fingerprint,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_checkpoint_writer import (
    _Authority,
    _record,
    _request_set,
)

COMPLETED_BY = "workload:compensation-completion-recorder"


def _completion_inputs():
    write_request_set = _request_set()
    checkpoint_authority = _Authority()
    record_set = _record(write_request_set, checkpoint_authority)
    return write_request_set, record_set, checkpoint_authority


def _completion_request(inputs):
    write_request_set, record_set, checkpoint_authority = inputs
    return build_federated_projection_compensation_completion_request(
        write_request_set,
        record_set,
        checkpoint_authority,
        completed_by=COMPLETED_BY,
    )


def test_completion_admission_rechecks_all_current_checkpoints_deterministically() -> None:
    inputs = _completion_inputs()

    request = _completion_request(inputs)
    replay = _completion_request(inputs)

    assert request.request_sha256 == replay.request_sha256
    assert tuple(target.position for target in request.targets) == (0, 1, 2)
    assert request.all_authority_currents_verified is True
    assert request.completion_record_allowed is True
    assert request.completion_recorded is False
    assert request.provider_execution_performed_by_completion_authority is False


def test_completion_admission_rejects_partial_record_set_before_current_reads() -> None:
    write_request_set = _request_set()
    checkpoint_authority = _Authority(
        fail_position=1,
        failure=ProjectionCheckpointConflictError("concurrent checkpoint"),
    )
    record_set = _record(write_request_set, checkpoint_authority)
    reads_before = len(checkpoint_authority.current_calls)

    with pytest.raises(
        FederatedProjectionCompensationCompletionAdmissionError,
        match="only a complete",
    ):
        build_federated_projection_compensation_completion_request(
            write_request_set,
            record_set,
            checkpoint_authority,
            completed_by=COMPLETED_BY,
        )

    assert len(checkpoint_authority.current_calls) == reads_before


def test_completion_admission_rejects_live_current_drift() -> None:
    write_request_set, record_set, checkpoint_authority = _completion_inputs()
    first = write_request_set.requests[0]
    checkpoint_authority.current_override[first.checkpoint.projection_id] = (
        write_request_set.requests[1].checkpoint
    )

    with pytest.raises(
        FederatedProjectionCompensationCompletionAdmissionError,
        match="current drifted",
    ):
        build_federated_projection_compensation_completion_request(
            write_request_set,
            record_set,
            checkpoint_authority,
            completed_by=COMPLETED_BY,
        )


def test_completion_migration_is_append_only_rls_and_current_guarded() -> None:
    migration = FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION.read_text(encoding="utf-8")

    assert "federated_projection_compensation_checkpoint_completion" in migration
    assert "cross_store_projection_checkpoint_current" in migration
    assert "checkpoint authority current drifted before completion" in migration
    assert "OR NOT target.value ?& ARRAY[" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "projection-checkpoint-target|" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "GRANT INSERT" not in migration
    assert "GRANT UPDATE" not in migration
    assert "GRANT DELETE" not in migration


def test_completion_authority_requires_postgresql_and_tenant_match() -> None:
    request = _completion_request(_completion_inputs())

    with pytest.raises(
        FederatedProjectionCompensationCompletionAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        PostgresFederatedProjectionCompensationCompletionAuthority(
            request.tenant_id,
            create_engine("sqlite://"),
        ).record(request)

    with pytest.raises(
        FederatedProjectionCompensationCompletionAuthorityForbiddenError,
        match="tenant differs",
    ):
        PostgresFederatedProjectionCompensationCompletionAuthority("cq-other-tenant").record(
            request
        )


def test_mocked_postgres_completion_record_builds_durable_receipt() -> None:
    request = _completion_request(_completion_inputs())
    completion_document = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "write_request_set_sha256": request.write_request_set_sha256,
        "authority_record_set_sha256": request.authority_record_set_sha256,
        "checkpoint_targets": [target.model_dump(mode="json") for target in request.targets],
        "completion_idempotency_key": request.completion_idempotency_key,
        "completion_request_sha256": request.request_sha256,
        "completed_by": request.completed_by,
        "completed_at": datetime(2026, 8, 17, 13, tzinfo=UTC),
    }
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    query_result = MagicMock()
    query_result.mappings.return_value.one.return_value = {
        "completion_document": completion_document,
        "created": True,
    }
    connection.execute.side_effect = [MagicMock(), query_result]

    result = PostgresFederatedProjectionCompensationCompletionAuthority(
        request.tenant_id,
        engine,
    ).record(request)

    assert result.created is True
    assert result.receipt.checkpoint_compensation_completion_recorded is True
    assert result.receipt.provider_execution_performed_by_completion_authority is False
    assert result.receipt.completion_request_sha256 == request.request_sha256


@pytest.mark.parametrize("tampered_field", ["completed_by", "created"])
def test_mocked_postgres_completion_rejects_tampered_response(tampered_field: str) -> None:
    request = _completion_request(_completion_inputs())
    completion_document = {
        "tenant_id": request.tenant_id,
        "run_id": request.run_id,
        "write_request_set_sha256": request.write_request_set_sha256,
        "authority_record_set_sha256": request.authority_record_set_sha256,
        "checkpoint_targets": [target.model_dump(mode="json") for target in request.targets],
        "completion_idempotency_key": request.completion_idempotency_key,
        "completion_request_sha256": request.request_sha256,
        "completed_by": request.completed_by,
        "completed_at": datetime(2026, 8, 17, 13, tzinfo=UTC),
    }
    created: bool | str = True
    if tampered_field == "completed_by":
        completion_document["completed_by"] = "workload:different-recorder"
    else:
        created = "true"
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    query_result = MagicMock()
    query_result.mappings.return_value.one.return_value = {
        "completion_document": completion_document,
        "created": created,
    }
    connection.execute.side_effect = [MagicMock(), query_result]

    with pytest.raises(
        FederatedProjectionCompensationCompletionAuthorityConfigurationError,
        match="stored compensation completion record is invalid|invalid creation status",
    ):
        PostgresFederatedProjectionCompensationCompletionAuthority(
            request.tenant_id,
            engine,
        ).record(request)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_completion_is_current_guarded_idempotent_and_rls_isolated() -> None:
    write_request_set = _request_set()

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )
        checkpoint_authority = PostgresProjectionCheckpointAuthority(sandbox.runtime_engine)
        record_set = record_federated_compensation_checkpoint_write_request_set(
            write_request_set,
            checkpoint_authority,
            writer_subject="workload:checkpoint-authority-writer",
        )
        request = build_federated_projection_compensation_completion_request(
            write_request_set,
            record_set,
            checkpoint_authority,
            completed_by=COMPLETED_BY,
        )
        authority = PostgresFederatedProjectionCompensationCompletionAuthority(
            request.tenant_id,
            sandbox.runtime_engine,
        )

        invalid_targets = [target.model_dump(mode="json") for target in request.targets]
        invalid_targets[0]["unknown_sha256"] = invalid_targets[0].pop("target_sha256")
        with sandbox.runtime_engine.connect() as connection:
            with pytest.raises(DBAPIError, match="target evidence is invalid"):
                with connection.begin():
                    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": request.tenant_id},
                    )
                    connection.execute(
                        text(
                            """
                            SELECT completion_document, created
                            FROM gda_control.
                            record_federated_projection_compensation_checkpoint_completion(
                                :tenant_id, :run_id, :write_request_set_sha256,
                                :authority_record_set_sha256,
                                CAST(:checkpoint_targets AS jsonb),
                                :completion_idempotency_key,
                                :completion_request_sha256, :completed_by
                            )
                            """
                        ),
                        {
                            "tenant_id": request.tenant_id,
                            "run_id": request.run_id,
                            "write_request_set_sha256": request.write_request_set_sha256,
                            "authority_record_set_sha256": request.authority_record_set_sha256,
                            "checkpoint_targets": json.dumps(invalid_targets),
                            "completion_idempotency_key": request.completion_idempotency_key,
                            "completion_request_sha256": request.request_sha256,
                            "completed_by": request.completed_by,
                        },
                    )

        first = authority.record(request)
        replay = authority.record(request)

        assert first.created is True
        assert replay.created is False
        assert replay.receipt == first.receipt
        assert authority.current(request.run_id) == first.receipt
        assert (
            PostgresFederatedProjectionCompensationCompletionAuthority(
                "cq-other-tenant",
                sandbox.runtime_engine,
            ).current(request.run_id)
            is None
        )


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_completion_rejects_drift_after_admission() -> None:
    write_request_set = _request_set()

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                FEDERATED_PROJECTION_COMPENSATION_COMPLETION_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )
        checkpoint_authority = PostgresProjectionCheckpointAuthority(sandbox.runtime_engine)
        record_set = record_federated_compensation_checkpoint_write_request_set(
            write_request_set,
            checkpoint_authority,
            writer_subject="workload:checkpoint-authority-writer",
        )
        request = build_federated_projection_compensation_completion_request(
            write_request_set,
            record_set,
            checkpoint_authority,
            completed_by=COMPLETED_BY,
        )

        previous = write_request_set.requests[0].checkpoint
        next_values = previous.model_dump(mode="python", exclude={"checkpoint_sha256"})
        next_values.update(
            {
                "source_content_sha256": "d" * 64,
                "checkpoint_version": previous.checkpoint_version + 1,
                "target_commit_ref": {
                    "provider": "postgis",
                    "commit": "concurrent-v2",
                    "plan_sha256": "e" * 64,
                    "idempotency_key": "f" * 64,
                },
                "updated_at": previous.updated_at + timedelta(seconds=1),
            }
        )
        concurrent = ProjectionCheckpoint(
            **next_values,
            checkpoint_sha256=projection_checkpoint_fingerprint(**next_values),
        )
        checkpoint_authority.record(
            concurrent,
            previous_checkpoint_sha256=previous.checkpoint_sha256,
        )

        with pytest.raises(
            FederatedProjectionCompensationCompletionAuthorityValidationError,
            match="current or idempotency evidence differs",
        ):
            PostgresFederatedProjectionCompensationCompletionAuthority(
                request.tenant_id,
                sandbox.runtime_engine,
            ).record(request)
