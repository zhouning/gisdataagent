"""Focused cancellation invariants for governed PostGIS analysis."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.gis_analysis_command_consumer import (
    GISAnalysisCancelCommandConsumer,
    GISAnalysisProviderTransientError,
    PostGISBackendCanceller,
)
from data_agent.gis_analysis_execution import (
    GIS_POSTGIS_CANCELLER_WORKLOAD,
    GISAnalysisBackendBinding,
    GISAnalysisCancelAdmission,
    GISAnalysisCancelOutcome,
    GISAnalysisCancelReceipt,
)
from data_agent.platform_contracts import PlatformCommand, PlatformCommandStatus
from data_agent.test_gis_analysis_command_consumer import (
    BACKEND,
    NOW,
    PLAN_ID,
    RUN_ID,
    TENANT,
    _record,
)

START_OBSERVATION_ID = UUID("00000000-0000-4000-8000-000000000104")
CANCEL_COMMAND_ID = UUID("00000000-0000-4000-8000-000000000105")
CANCEL_OBSERVATION_ID = UUID("00000000-0000-4000-8000-000000000106")
CANCEL_REQUEST_ID = "gis-cancel-101"
CANCEL_REQUESTED_AT = NOW + timedelta(seconds=1)


def _cancel_record(
    *,
    outcome: GISAnalysisCancelOutcome | None = None,
):
    record = _record()
    admission = GISAnalysisCancelAdmission(
        tenant_id=TENANT,
        run_id=RUN_ID,
        cancel_request_id=CANCEL_REQUEST_ID,
        cancel_command_id=CANCEL_COMMAND_ID,
        start_observation_id=START_OBSERVATION_ID,
        requested_by="human:analyst",
        reason="source snapshot was superseded",
        backend=BACKEND,
        requested_at=CANCEL_REQUESTED_AT,
    )
    receipt = None
    if outcome is not None:
        receipt = GISAnalysisCancelReceipt(
            tenant_id=TENANT,
            run_id=RUN_ID,
            cancel_command_id=CANCEL_COMMAND_ID,
            cancel_observation_id=CANCEL_OBSERVATION_ID,
            outcome=outcome,
            backend=BACKEND,
            observed_at=CANCEL_REQUESTED_AT + timedelta(seconds=1),
            recorded_by=GIS_POSTGIS_CANCELLER_WORKLOAD,
        )
    status = "cancelled" if outcome is GISAnalysisCancelOutcome.SIGNALLED else (
        "reconciling" if outcome is not None else "cancelling"
    )
    return record.model_copy(
        update={
            "run": record.run.model_copy(
                update={"status": status, "state_version": 3}
            ),
            "cancel_admission": admission,
            "cancel_receipt": receipt,
        }
    )


def _cancel_command(
    *,
    dedupe_key: str | None = None,
    backend_start: str | None = None,
) -> PlatformCommand:
    expected_dedupe = (
        f"gis_analysis.cancel:{TENANT}:{RUN_ID}:{CANCEL_REQUEST_ID}:"
        f"{BACKEND.binding_fingerprint}"
    )
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=CANCEL_COMMAND_ID,
        run_id=RUN_ID,
        command_type="gis_analysis.cancel",
        execution_plan_artifact_id=PLAN_ID,
        trigger_observation_id=START_OBSERVATION_ID,
        dedupe_key=dedupe_key or expected_dedupe,
        actor_subject=GIS_POSTGIS_CANCELLER_WORKLOAD,
        payload={
            "schema": "gda.gis_analysis_cancel_command.v1",
            "run_id": str(RUN_ID),
            "plan_artifact_id": str(PLAN_ID),
            "backend_pid": BACKEND.backend_pid,
            "backend_start": backend_start
            or BACKEND.backend_start.isoformat().replace("+00:00", "Z"),
            "database_oid": BACKEND.database_oid,
            "user_oid": BACKEND.user_oid,
            "application_name": BACKEND.application_name,
            "backend_binding_fingerprint": BACKEND.binding_fingerprint,
        },
        status="in_flight",
        attempt_count=1,
        max_attempts=5,
        available_at=CANCEL_REQUESTED_AT,
        claimed_by="worker:gis-analysis-canceller-1",
        claimed_until=CANCEL_REQUESTED_AT + timedelta(minutes=1),
        created_at=CANCEL_REQUESTED_AT,
    )


class _CancelGateway:
    def __init__(self, command: PlatformCommand):
        self.command = command
        self.completed: list[UUID] = []
        self.failures: list[tuple[str, int]] = []

    def claim_commands(self, tenant_id, worker_id, *, actor_subject, limit, lease_seconds):
        return [self.command]

    def complete_command(self, tenant_id, command_id, *, worker_id):
        self.completed.append(command_id)
        return self.command

    def fail_command(
        self,
        tenant_id,
        command_id,
        *,
        worker_id,
        error,
        retry_delay_seconds,
    ):
        self.failures.append((error, retry_delay_seconds))
        return self.command.model_copy(update={"status": PlatformCommandStatus.PENDING})


class _CancelAuthority:
    def __init__(self, record):
        self.record = record
        self.signal_receipts: list[dict] = []

    def get(self, tenant_id, run_id):
        return self.record

    def record_cancel_signal(self, tenant_id, run_id, **values):
        self.signal_receipts.append(values)
        return self.record


class _Canceller:
    workload_subject = GIS_POSTGIS_CANCELLER_WORKLOAD

    def __init__(self, result):
        self.result = result
        self.bindings: list[GISAnalysisBackendBinding] = []

    def cancel(self, binding):
        self.bindings.append(binding)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("outcome", "signalled", "reconciliation_required"),
    [
        (GISAnalysisCancelOutcome.SIGNALLED, 1, 0),
        (GISAnalysisCancelOutcome.NOT_FOUND, 0, 1),
        (GISAnalysisCancelOutcome.UNKNOWN, 0, 1),
    ],
)
def test_cancel_consumer_records_outcome_before_completing_command(
    outcome,
    signalled,
    reconciliation_required,
) -> None:
    command = _cancel_command()
    gateway = _CancelGateway(command)
    authority = _CancelAuthority(_cancel_record())
    canceller = _Canceller(outcome)

    result = GISAnalysisCancelCommandConsumer(
        canceller,
        gateway=gateway,
        authority=authority,
    ).run_once(TENANT, worker_id="worker:gis-analysis-canceller-1")

    assert result.completed == 1
    assert result.signalled == signalled
    assert result.reconciliation_required == reconciliation_required
    assert canceller.bindings == [BACKEND]
    assert authority.signal_receipts[0]["outcome"] is outcome
    assert gateway.completed == [CANCEL_COMMAND_ID]


def test_cancel_consumer_reuses_durable_receipt_after_outbox_completion_failure() -> None:
    command = _cancel_command()
    gateway = _CancelGateway(command)
    authority = _CancelAuthority(
        _cancel_record(outcome=GISAnalysisCancelOutcome.SIGNALLED)
    )
    canceller = _Canceller(AssertionError("backend must not be signalled twice"))

    result = GISAnalysisCancelCommandConsumer(
        canceller,
        gateway=gateway,
        authority=authority,
    ).run_once(TENANT, worker_id="worker:gis-analysis-canceller-1")

    assert result.completed == 1
    assert result.signalled == 1
    assert canceller.bindings == []
    assert authority.signal_receipts == []
    assert gateway.completed == [CANCEL_COMMAND_ID]


def test_cancel_consumer_accepts_postgresql_equivalent_utc_timestamp() -> None:
    command = _cancel_command(backend_start=BACKEND.backend_start.isoformat())
    gateway = _CancelGateway(command)
    authority = _CancelAuthority(_cancel_record())
    canceller = _Canceller(GISAnalysisCancelOutcome.SIGNALLED)

    result = GISAnalysisCancelCommandConsumer(
        canceller,
        gateway=gateway,
        authority=authority,
    ).run_once(TENANT, worker_id="worker:gis-analysis-canceller-1")

    assert result.completed == 1
    assert canceller.bindings == [BACKEND]


def test_cancel_consumer_retries_transient_transport_failure() -> None:
    command = _cancel_command()
    gateway = _CancelGateway(command)
    authority = _CancelAuthority(_cancel_record())
    canceller = _Canceller(GISAnalysisProviderTransientError("temporary"))

    result = GISAnalysisCancelCommandConsumer(
        canceller,
        gateway=gateway,
        authority=authority,
    ).run_once(TENANT, worker_id="worker:gis-analysis-canceller-1")

    assert result.retry_pending == 1
    assert result.completed == 0
    assert authority.signal_receipts == []
    assert gateway.completed == []
    assert gateway.failures[0][1] == 2


def test_cancel_consumer_rejects_tampered_dedupe_identity() -> None:
    command = _cancel_command(dedupe_key="gis_analysis.cancel:tampered")
    gateway = _CancelGateway(command)
    authority = _CancelAuthority(_cancel_record())
    canceller = _Canceller(GISAnalysisCancelOutcome.SIGNALLED)

    result = GISAnalysisCancelCommandConsumer(
        canceller,
        gateway=gateway,
        authority=authority,
    ).run_once(TENANT, worker_id="worker:gis-analysis-canceller-1")

    assert result.retry_pending == 1
    assert canceller.bindings == []
    assert authority.signal_receipts == []


def test_backend_binding_fingerprint_rejects_identity_tampering() -> None:
    document = BACKEND.model_dump(mode="python")
    document["database_oid"] += 1
    with pytest.raises(ValidationError, match="binding fingerprint is invalid"):
        GISAnalysisBackendBinding.model_validate(document)


@pytest.mark.parametrize(
    ("database_result", "expected"),
    [
        (True, GISAnalysisCancelOutcome.SIGNALLED),
        (False, GISAnalysisCancelOutcome.UNKNOWN),
        (None, GISAnalysisCancelOutcome.NOT_FOUND),
    ],
)
def test_backend_canceller_matches_and_signals_atomically(database_result, expected) -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one_or_none.return_value = database_result

    outcome = PostGISBackendCanceller(engine).cancel(BACKEND)

    assert outcome is expected
    connection.execute.assert_called_once()
    sql, parameters = connection.execute.call_args.args
    statement = str(sql)
    assert "SELECT pg_cancel_backend(pid) FROM pg_stat_activity" in statement
    for predicate in (
        "pid = :backend_pid",
        "backend_start = :backend_start",
        "datid = :database_oid",
        "usesysid = :user_oid",
        "application_name = :application_name",
    ):
        assert predicate in statement
    assert parameters == BACKEND.model_dump(
        mode="python", exclude={"schema_id", "binding_fingerprint"}
    )
