"""Delivery and lifecycle tests for the DuckDB Blueprint command worker."""

from __future__ import annotations

import stat
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.duckdb_blueprint_command_consumer import (
    DuckDBBlueprintCommandBatchResult,
    DuckDBBlueprintCommandConsumer,
)
from data_agent.duckdb_blueprint_command_worker import (
    DuckDBBlueprintCommandWorker,
    DuckDBBlueprintCommandWorkerConfig,
    WorkerProviderUnavailable,
    WorkerStatusStore,
    evaluate_worker_health,
    evaluate_worker_liveness,
)
from data_agent.duckdb_blueprint_provider import DUCKDB_BLUEPRINT_WORKLOAD
from data_agent.platform_contracts import (
    OrchestrationClass,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    PlatformRun,
    RunStatus,
    SubjectContext,
    SubjectType,
)
from data_agent.platform_gateway import GatewayUnavailableError, GatewayValidationError

NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)
TENANT = "planning"
RUN_ID = UUID("00000000-0000-4000-8000-000000000901")
PLAN_ID = UUID("00000000-0000-4000-8000-000000000902")
COMMAND_ID = UUID("00000000-0000-4000-8000-000000000903")


def _run(status: RunStatus = RunStatus.ACCEPTED) -> PlatformRun:
    return PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=UUID("00000000-0000-4000-8000-000000000904"),
        orchestration_class=OrchestrationClass.DATAOPS,
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id="blueprint-duckdb-executor",
            subject_type=SubjectType.WORKLOAD,
            purpose="test",
        ),
        idempotency_key="duckdb-worker-test",
        config_fingerprint="1" * 64,
        status=status,
        state_version=0 if status is RunStatus.ACCEPTED else 2,
        submitted_at=NOW,
    )


def _command(
    *,
    command_type: PlatformCommandType = PlatformCommandType.BLUEPRINT_PROVIDER_EXECUTE,
    status: PlatformCommandStatus = PlatformCommandStatus.IN_FLIGHT,
) -> PlatformCommand:
    if command_type is PlatformCommandType.BLUEPRINT_PROVIDER_EXECUTE:
        payload = {
            "schema": "gda.data_product_blueprint_duckdb_execute_command.v1",
            "run_id": str(RUN_ID),
            "execution_plan_artifact_id": str(PLAN_ID),
            "execution_plan_sha256": "1" * 64,
            "definition_version_id": "00000000-0000-4000-8000-000000000904",
            "definition_sha256": "2" * 64,
            "engine": "duckdb",
            "attempt_no": 1,
        }
    else:
        payload = {
            "schema": "gda.metric_query_execute_command.v1",
            "run_id": str(RUN_ID),
            "plan_artifact_id": str(PLAN_ID),
            "plan_fingerprint": "1" * 64,
            "cache_key": "2" * 64,
            "engine": "postgis",
            "execution_mode": "synchronous",
        }
    terminal = status in {PlatformCommandStatus.DONE, PlatformCommandStatus.FAILED}
    return PlatformCommand(
        tenant_id=TENANT,
        command_id=COMMAND_ID,
        run_id=RUN_ID,
        command_type=command_type,
        execution_plan_artifact_id=PLAN_ID,
        dedupe_key="duckdb-blueprint-command-test",
        actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
        payload=payload,
        status=status,
        attempt_count=1,
        max_attempts=5,
        available_at=NOW,
        claimed_by=None if terminal or status is PlatformCommandStatus.PENDING else "worker:test",
        claimed_until=(
            None
            if terminal or status is PlatformCommandStatus.PENDING
            else NOW + timedelta(minutes=15)
        ),
        created_at=NOW,
        completed_at=NOW if terminal else None,
    )


def _pending_delivery(command: PlatformCommand) -> PlatformCommand:
    return command.model_copy(
        update={
            "status": PlatformCommandStatus.PENDING,
            "claimed_by": None,
            "claimed_until": None,
        }
    )


def test_consumer_executes_and_completes_exact_command() -> None:
    gateway = MagicMock()
    command = _command()
    gateway.claim_commands.return_value = [command]
    gateway.get_run.return_value = _run()
    consumer = DuckDBBlueprintCommandConsumer(gateway=gateway)

    result = consumer.run_once(
        TENANT,
        worker_id="worker:test",
        limit=1,
        lease_seconds=900,
    )

    assert result.execution_succeeded == 1
    assert result.completed == 1
    gateway.execute_blueprint_duckdb_test_run.assert_called_once()
    gateway.complete_command.assert_called_once_with(
        TENANT,
        COMMAND_ID,
        worker_id="worker:test",
    )


def test_consumer_reconciles_terminal_run_without_reexecution() -> None:
    gateway = MagicMock()
    gateway.claim_commands.return_value = [_command()]
    gateway.get_run.return_value = _run(RunStatus.SUCCEEDED)

    result = DuckDBBlueprintCommandConsumer(gateway=gateway).run_once(
        TENANT,
        worker_id="worker:test",
    )

    assert result.terminal_reconciled == 1
    assert result.completed == 1
    gateway.execute_blueprint_duckdb_test_run.assert_not_called()
    gateway.complete_command.assert_called_once()


def test_consumer_completes_command_when_provider_failure_already_terminalized_run() -> None:
    gateway = MagicMock()
    gateway.claim_commands.return_value = [_command()]
    gateway.get_run.side_effect = [_run(), _run(RunStatus.FAILED)]
    gateway.execute_blueprint_duckdb_test_run.side_effect = GatewayValidationError(
        "private provider detail"
    )

    result = DuckDBBlueprintCommandConsumer(gateway=gateway).run_once(
        TENANT,
        worker_id="worker:test",
    )

    assert result.execution_failed == 1
    assert result.terminal_reconciled == 1
    assert result.completed == 1
    gateway.complete_command.assert_called_once()
    gateway.fail_command.assert_not_called()


def test_consumer_retries_control_plane_failure_and_rejects_other_command_types() -> None:
    gateway = MagicMock()
    command = _command()
    gateway.claim_commands.return_value = [command]
    gateway.get_run.side_effect = GatewayUnavailableError("private database detail")
    gateway.fail_command.return_value = _pending_delivery(command)

    result = DuckDBBlueprintCommandConsumer(gateway=gateway).run_once(
        TENANT,
        worker_id="worker:test",
    )

    assert result.retry_pending == 1
    assert gateway.fail_command.call_args.kwargs["error"] == (
        "DuckDB Blueprint control-plane delivery failed"
    )
    assert "private database detail" not in gateway.fail_command.call_args.kwargs["error"]

    other = _command(command_type=PlatformCommandType.METRIC_QUERY_EXECUTE)
    gateway.reset_mock()
    gateway.claim_commands.return_value = [other]
    gateway.fail_command.return_value = _pending_delivery(other)
    rejected = DuckDBBlueprintCommandConsumer(gateway=gateway).run_once(
        TENANT,
        worker_id="worker:test",
    )
    assert rejected.retry_pending == 1
    gateway.get_run.assert_not_called()


def _config(tmp_path, **overrides) -> DuckDBBlueprintCommandWorkerConfig:
    values = {
        "tenant_id": TENANT,
        "worker_id": "worker:duckdb-blueprint:test",
        "output_root": tmp_path / "outputs",
        "batch_size": 1,
        "lease_seconds": 900,
        "provider_timeout_ceiling_seconds": 600,
        "poll_interval_seconds": 5,
        "status_file": tmp_path / "status.json",
        "health_max_age_seconds": 1200,
    }
    values.update(overrides)
    return DuckDBBlueprintCommandWorkerConfig(**values)


class _Consumer:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def run_once(self, tenant_id, *, worker_id, limit, lease_seconds):
        self.calls.append((tenant_id, worker_id, limit, lease_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _batch(**overrides) -> DuckDBBlueprintCommandBatchResult:
    values = {
        "claimed": 1,
        "completed": 1,
        "execution_succeeded": 1,
        "execution_failed": 0,
        "terminal_reconciled": 0,
        "retry_pending": 0,
        "failed": 0,
        "command_ids": (COMMAND_ID,),
    }
    values.update(overrides)
    return DuckDBBlueprintCommandBatchResult(**values)


def test_worker_config_covers_batch_lease_and_health_budgets(tmp_path) -> None:
    with pytest.raises(ValidationError, match="600"):
        _config(tmp_path, provider_timeout_ceiling_seconds=60)
    with pytest.raises(ValidationError, match="full claimed execution batch"):
        _config(tmp_path, batch_size=2, lease_seconds=900)
    with pytest.raises(ValidationError, match="health max age"):
        _config(tmp_path, health_max_age_seconds=900)
    with pytest.raises(ValidationError, match="filesystem root"):
        _config(tmp_path, output_root="/")
    with pytest.raises(ValidationError, match="outside"):
        _config(tmp_path, status_file=tmp_path / "outputs" / "status.json")


def test_worker_s3_config_requires_managed_output_and_input_prefixes(tmp_path) -> None:
    with pytest.raises(ValidationError, match="S3 result location"):
        _config(tmp_path, result_backend="s3")

    config = _config(
        tmp_path,
        result_backend="s3",
        output_s3_bucket="gis-agent-blueprint-results",
        output_s3_prefix="blueprint-results/v1",
        input_s3_prefixes=("s3://gis-agent-inputs/admitted",),
    )

    assert config.safe_summary()["result_backend"] == "s3"
    assert config.safe_summary()["input_s3_prefixes"] == [
        "s3://gis-agent-inputs/admitted"
    ]


def test_worker_cycle_writes_private_status_and_health(tmp_path) -> None:
    config = _config(tmp_path)
    consumer = _Consumer([_batch()])
    probes = []
    worker = DuckDBBlueprintCommandWorker(
        consumer,
        config,
        provider_probe=lambda: probes.append("probe"),
        clock=lambda: NOW,
    )

    assert worker.run_cycle() == _batch()
    assert probes == ["probe"]
    assert consumer.calls == [(TENANT, config.worker_id, 1, 900)]
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "ready"
    assert status.execution_succeeded == 1
    assert stat.S_IMODE(config.status_file.stat().st_mode) == 0o600

    health, ready = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=1200,
        now=NOW + timedelta(seconds=10),
    )
    assert ready is True
    assert health["execution_succeeded"] == 1


def test_worker_provider_failure_degrades_but_remains_live(tmp_path) -> None:
    config = _config(tmp_path)

    def fail_probe() -> None:
        raise WorkerProviderUnavailable("private runtime detail")

    consumer = _Consumer([_batch()])
    worker = DuckDBBlueprintCommandWorker(
        consumer,
        config,
        provider_probe=fail_probe,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    assert consumer.calls == []
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "degraded"
    assert status.last_error_code == "duckdb_blueprint_provider_unavailable"
    assert "private runtime detail" not in config.status_file.read_text(encoding="utf-8")
    _, ready = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=1200,
        now=NOW,
    )
    liveness, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file),
        max_age_seconds=1200,
        now=NOW,
    )
    assert ready is False
    assert live is True
    assert liveness["worker_state"] == "degraded"


def test_worker_stops_after_current_cycle(tmp_path) -> None:
    config = _config(tmp_path)
    stop_event = threading.Event()

    class _StoppingConsumer(_Consumer):
        def run_once(self, *args, **kwargs):
            result = super().run_once(*args, **kwargs)
            stop_event.set()
            return result

    worker = DuckDBBlueprintCommandWorker(
        _StoppingConsumer([_batch()]),
        config,
        stop_event=stop_event,
        clock=lambda: NOW,
    )

    assert worker.run() == 0
    assert WorkerStatusStore(config.status_file).read().state == "stopped"
