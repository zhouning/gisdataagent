"""Behavioral contracts for uncertain PostGIS cancellation reconciliation."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from data_agent.gis_analysis_command_consumer import (
    GISAnalysisProviderTransientError,
    GISAnalysisReconciliationCommandConsumer,
)
from data_agent.gis_analysis_execution import (
    GIS_POSTGIS_RECONCILER_WORKLOAD,
    GISAnalysisCancelOutcome,
)
from data_agent.platform_contracts import PlatformCommand, PlatformCommandStatus
from data_agent.test_gis_analysis_cancellation import (
    CANCEL_COMMAND_ID,
    CANCEL_OBSERVATION_ID,
    START_OBSERVATION_ID,
    _cancel_record,
)
from data_agent.test_gis_analysis_command_consumer import (
    BACKEND,
    NOW,
    PLAN_ID,
    RUN_ID,
    TENANT,
)

RECONCILE_COMMAND_ID = UUID("00000000-0000-4000-8000-000000000107")
RECONCILE_WORKER = "worker:gis-analysis-reconciler-1"


def _reconcile_command(*, attempt_count: int = 1) -> PlatformCommand:
    created_at = NOW + timedelta(seconds=2)
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=RECONCILE_COMMAND_ID,
        run_id=RUN_ID,
        command_type="gis_analysis.reconcile",
        execution_plan_artifact_id=PLAN_ID,
        trigger_observation_id=START_OBSERVATION_ID,
        dedupe_key=(
            f"gis_analysis.reconcile:{TENANT}:{RUN_ID}:"
            f"{CANCEL_OBSERVATION_ID}"
        ),
        actor_subject=GIS_POSTGIS_RECONCILER_WORKLOAD,
        payload={
            "schema": "gda.gis_analysis_reconcile_command.v1",
            "run_id": str(RUN_ID),
            "plan_artifact_id": str(PLAN_ID),
            "cancel_command_id": str(CANCEL_COMMAND_ID),
            "cancel_observation_id": str(CANCEL_OBSERVATION_ID),
            "initial_cancel_outcome": "unknown",
            "backend_pid": BACKEND.backend_pid,
            "backend_start": BACKEND.backend_start.isoformat().replace(
                "+00:00", "Z"
            ),
            "database_oid": BACKEND.database_oid,
            "user_oid": BACKEND.user_oid,
            "application_name": BACKEND.application_name,
            "backend_binding_fingerprint": BACKEND.binding_fingerprint,
            "reconciliation_deadline": (
                created_at + timedelta(minutes=10)
            ).isoformat().replace("+00:00", "Z"),
            "max_reconciliation_attempts": 5,
        },
        status="in_flight",
        attempt_count=attempt_count,
        max_attempts=100,
        available_at=created_at,
        claimed_by=RECONCILE_WORKER,
        claimed_until=created_at + timedelta(minutes=1),
        created_at=created_at,
    )


class _Gateway:
    def __init__(self, command: PlatformCommand):
        self.command = command
        self.completed: list[UUID] = []
        self.failures: list[str] = []

    def claim_commands(self, *_args, **_kwargs):
        return [self.command]

    def complete_command(self, _tenant, command_id, *, worker_id):
        assert worker_id == RECONCILE_WORKER
        self.completed.append(command_id)
        return self.command

    def fail_command(
        self,
        _tenant,
        _command_id,
        *,
        worker_id,
        error,
        retry_delay_seconds,
    ):
        assert worker_id == RECONCILE_WORKER
        assert retry_delay_seconds >= 0
        self.failures.append(error)
        return self.command.model_copy(update={"status": "pending", "claimed_by": None,
                                               "claimed_until": None})


class _Authority:
    def __init__(
        self,
        record,
        delivery_status=PlatformCommandStatus.PENDING,
    ):
        self.record = record
        self.delivery_status = delivery_status
        self.settlements: list[dict] = []

    def get(self, _tenant, _run_id):
        return self.record

    def settle_reconciliation(self, command, **values):
        self.settlements.append(values)
        return command.model_copy(
            update={
                "status": self.delivery_status,
                "claimed_by": None,
                "claimed_until": None,
                "completed_at": (
                    NOW
                    if self.delivery_status is PlatformCommandStatus.FAILED
                    else None
                ),
            }
        )


class _Canceller:
    workload_subject = "workload:gis-analysis-postgis-canceller"

    def __init__(self, outcome):
        self.outcome = outcome
        self.bindings = []

    def cancel(self, binding):
        self.bindings.append(binding)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _reconciling_record(*, terminal: str | None = None):
    record = _cancel_record(outcome=GISAnalysisCancelOutcome.UNKNOWN)
    status = terminal or "reconciling"
    version = 4 if terminal is None else 5
    return record.model_copy(
        update={"run": record.run.model_copy(
            update={"status": status, "state_version": version}
        )}
    )


def test_reconciliation_reprobes_exact_backend_and_records_unknown() -> None:
    command = _reconcile_command()
    gateway = _Gateway(command)
    authority = _Authority(_reconciling_record())
    canceller = _Canceller(GISAnalysisCancelOutcome.NOT_FOUND)

    result = GISAnalysisReconciliationCommandConsumer(
        canceller, gateway=gateway, authority=authority
    ).run_once(TENANT, worker_id=RECONCILE_WORKER)

    assert result.observations_recorded == 1
    assert result.retry_pending == 1
    assert result.escalated == 0
    assert canceller.bindings == [BACKEND]
    assert authority.settlements[0]["outcome"] is GISAnalysisCancelOutcome.NOT_FOUND
    assert gateway.completed == []


def test_reconciliation_transport_failure_becomes_audited_unknown_observation() -> None:
    command = _reconcile_command()
    authority = _Authority(_reconciling_record())

    result = GISAnalysisReconciliationCommandConsumer(
        _Canceller(GISAnalysisProviderTransientError("network timeout")),
        gateway=_Gateway(command),
        authority=authority,
    ).run_once(TENANT, worker_id=RECONCILE_WORKER)

    assert result.observations_recorded == 1
    assert authority.settlements[0]["outcome"] is GISAnalysisCancelOutcome.UNKNOWN


def test_reconciliation_escalation_is_not_reported_as_cancelled() -> None:
    command = _reconcile_command(attempt_count=5)
    authority = _Authority(
        _reconciling_record(), delivery_status=PlatformCommandStatus.FAILED
    )

    result = GISAnalysisReconciliationCommandConsumer(
        _Canceller(GISAnalysisCancelOutcome.SIGNALLED),
        gateway=_Gateway(command),
        authority=authority,
    ).run_once(TENANT, worker_id=RECONCILE_WORKER)

    assert result.signalled == 1
    assert result.escalated == 1
    assert result.terminal_converged == 0
    assert str(authority.record.run.status) == "reconciling"


def test_terminal_provider_evidence_completes_reconcile_without_resignalling() -> None:
    command = _reconcile_command()
    gateway = _Gateway(command)
    authority = _Authority(_reconciling_record(terminal="cancelled"))
    canceller = _Canceller(AssertionError("terminal Run must not be re-signalled"))

    result = GISAnalysisReconciliationCommandConsumer(
        canceller, gateway=gateway, authority=authority
    ).run_once(TENANT, worker_id=RECONCILE_WORKER)

    assert result.terminal_converged == 1
    assert gateway.completed == [RECONCILE_COMMAND_ID]
    assert canceller.bindings == []
    assert authority.settlements == []
