"""Lifecycle tests for the governed GIS analysis command worker."""

from __future__ import annotations

import json
import stat
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import data_agent.gis_analysis_command_worker as worker_module
from data_agent.gis_analysis_command_consumer import (
    GISAnalysisCancelBatchResult,
    GISAnalysisCommandBatchResult,
)
from data_agent.gis_analysis_command_worker import (
    GISAnalysisCommandWorker,
    GISAnalysisCommandWorkerConfig,
    WorkerConfigurationError,
    WorkerProviderUnavailable,
    WorkerStatusStore,
    evaluate_worker_health,
    evaluate_worker_liveness,
    main,
)
from data_agent.platform_gateway import GatewayUnavailableError

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
TENANT = "tenant-a"
WORKER_ID = "worker:gis-analysis-postgis:pod-a"
PROVIDER_SECRET = "gis-provider-password-fixture"


def _config(tmp_path, **overrides):
    database_url_file = tmp_path / "postgis.url"
    canceller_database_url_file = tmp_path / "postgis-canceller.url"
    database_url_file.write_text(
        f"postgresql://gis_reader:{PROVIDER_SECRET}@postgis/gis\n",
        encoding="utf-8",
    )
    database_url_file.chmod(0o600)
    canceller_database_url_file.write_text(
        f"postgresql://gis_canceller:{PROVIDER_SECRET}@postgis/gis\n",
        encoding="utf-8",
    )
    canceller_database_url_file.chmod(0o600)
    values = {
        "tenant_id": TENANT,
        "worker_id": WORKER_ID,
        "provider_database_url_file": database_url_file,
        "provider_database_role": "gis_reader",
        "canceller_database_url_file": canceller_database_url_file,
        "canceller_database_role": "gis_canceller",
        "result_root": tmp_path / "results",
        "statement_timeout_ceiling_ms": 30_000,
        "batch_size": 10,
        "lease_seconds": 120,
        "poll_interval_seconds": 5,
        "status_file": tmp_path / "worker-status.json",
        "health_max_age_seconds": 180,
    }
    values.update(overrides)
    return GISAnalysisCommandWorkerConfig(**values)


def _batch(**overrides):
    values = {
        "claimed": 1,
        "completed": 1,
        "analysis_succeeded": 1,
        "analysis_failed": 0,
        "retry_pending": 0,
        "failed": 0,
        "command_ids": (),
    }
    values.update(overrides)
    return GISAnalysisCommandBatchResult(**values)


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


def test_config_bounds_cover_query_publication_and_health_budgets(tmp_path) -> None:
    with pytest.raises(ValidationError, match="lease"):
        _config(tmp_path, lease_seconds=60)
    with pytest.raises(ValidationError, match="health max age"):
        _config(tmp_path, health_max_age_seconds=109)
    with pytest.raises(ValidationError, match="absolute"):
        _config(tmp_path, result_root="relative/results")
    with pytest.raises(ValidationError, match="filesystem root"):
        _config(tmp_path, result_root="/")
    with pytest.raises(ValidationError, match="worker_id"):
        _config(tmp_path, worker_id="shared-process-name")
    with pytest.raises(ValidationError, match="must be distinct"):
        _config(tmp_path, canceller_database_role="gis_reader")
    with pytest.raises(ValidationError, match="paths must be distinct"):
        _config(
            tmp_path,
            canceller_database_url_file=_config(tmp_path).provider_database_url_file,
        )
    with pytest.raises(ValidationError, match="S3 bucket"):
        _config(
            tmp_path,
            result_backend="s3",
            result_root=None,
            result_s3_bucket=None,
        )


def test_provider_database_url_is_owner_only_postgresql_and_redacted(tmp_path) -> None:
    config = _config(tmp_path)
    config.provider_database_url_file.chmod(0o640)
    with pytest.raises(WorkerConfigurationError, match="owner-only"):
        config.provider_database_url()

    config.provider_database_url_file.chmod(0o600)
    assert PROVIDER_SECRET in config.provider_database_url()
    rendered = json.dumps(config.safe_summary())
    assert PROVIDER_SECRET not in rendered
    assert "postgresql://" not in rendered
    assert PROVIDER_SECRET in config.canceller_database_url()

    wrong_role = _config(tmp_path, provider_database_role="another_reader")
    with pytest.raises(WorkerConfigurationError, match="governed role"):
        wrong_role.provider_database_url()


def test_config_from_env_uses_gis_namespace_and_hides_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    values = {
        "GDA_GIS_ANALYSIS_TENANT_ID": TENANT,
        "GDA_GIS_ANALYSIS_WORKER_ID": WORKER_ID,
        "GDA_GIS_ANALYSIS_POSTGIS_DATABASE_URL_FILE": str(
            config.provider_database_url_file
        ),
        "GDA_GIS_ANALYSIS_POSTGIS_DATABASE_ROLE": "gis_reader",
        "GDA_GIS_ANALYSIS_POSTGIS_CANCELLER_DATABASE_URL_FILE": str(
            config.canceller_database_url_file
        ),
        "GDA_GIS_ANALYSIS_POSTGIS_CANCELLER_DATABASE_ROLE": "gis_canceller",
        "GDA_GIS_ANALYSIS_RESULT_ROOT": str(config.result_root),
        "GDA_GIS_ANALYSIS_STATUS_FILE": str(config.status_file),
        "GDA_GIS_ANALYSIS_CANCEL_RECEIPT_WAIT_SECONDS": "3.5",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    loaded = GISAnalysisCommandWorkerConfig.from_env()
    assert loaded.tenant_id == TENANT
    assert loaded.worker_id == WORKER_ID
    assert loaded.cancel_receipt_wait_seconds == 3.5
    assert PROVIDER_SECRET not in json.dumps(loaded.safe_summary())

    monkeypatch.delenv("GDA_GIS_ANALYSIS_WORKER_ID")
    with pytest.raises(WorkerConfigurationError):
        GISAnalysisCommandWorkerConfig.from_env()


def test_successful_cycle_probes_before_claim_and_writes_private_status(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    consumer = _Consumer([_batch(claimed=2, completed=1, retry_pending=1)])
    probes = []
    worker = GISAnalysisCommandWorker(
        consumer,
        config,
        provider_probe=lambda: probes.append("probe"),
        clock=lambda: NOW,
    )

    result = worker.run_cycle()

    assert result is not None
    assert probes == ["probe"]
    assert consumer.calls == [(TENANT, WORKER_ID, 10, 120)]
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "ready"
    assert status.analysis_succeeded == 1
    assert status.retry_pending == 1
    assert stat.S_IMODE(config.status_file.stat().st_mode) == 0o600
    assert PROVIDER_SECRET not in config.status_file.read_text(encoding="utf-8")

    report, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=180,
        now=NOW + timedelta(seconds=10),
    )
    assert healthy is True
    assert report["analysis_succeeded"] == 1


def test_provider_failure_degrades_before_claim_and_remains_live(tmp_path) -> None:
    config = _config(tmp_path)
    consumer = _Consumer([_batch()])

    def fail_probe():
        raise WorkerProviderUnavailable("private database detail")

    worker = GISAnalysisCommandWorker(
        consumer,
        config,
        provider_probe=fail_probe,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    assert consumer.calls == []
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "degraded"
    assert status.last_error_code == "gis_postgis_provider_unavailable"
    assert "private database detail" not in config.status_file.read_text()
    _, ready = evaluate_worker_health(
        WorkerStatusStore(config.status_file), max_age_seconds=180, now=NOW
    )
    liveness, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file), max_age_seconds=180, now=NOW
    )
    assert ready is False
    assert live is True
    assert liveness["worker_state"] == "degraded"


def test_gateway_failure_marks_worker_degraded_without_detail(tmp_path) -> None:
    config = _config(tmp_path)
    worker = GISAnalysisCommandWorker(
        _Consumer([GatewayUnavailableError("private platform detail")]),
        config,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "degraded"
    assert status.last_error_code == "platform_unavailable"
    assert "private platform detail" not in config.status_file.read_text()


def test_worker_drains_current_batch_then_stops(tmp_path) -> None:
    config = _config(tmp_path)
    stop_event = threading.Event()

    class _StoppingConsumer(_Consumer):
        def run_once(self, *args, **kwargs):
            result = super().run_once(*args, **kwargs)
            stop_event.set()
            return result

    worker = GISAnalysisCommandWorker(
        _StoppingConsumer([_batch()]),
        config,
        stop_event=stop_event,
        clock=lambda: NOW,
    )

    assert worker.run() == 0
    assert WorkerStatusStore(config.status_file).read().state == "stopped"


def test_cancel_monitor_runs_while_execution_consumer_is_blocked(tmp_path) -> None:
    config = _config(tmp_path, cancel_poll_interval_seconds=0.1)
    cancel_delivered = threading.Event()

    class _BlockingConsumer:
        def run_once(self, tenant_id, *, worker_id, limit, lease_seconds):
            assert cancel_delivered.wait(timeout=2)
            return _batch()

    class _CancelConsumer:
        calls = 0

        def run_once(self, tenant_id, *, worker_id, limit, lease_seconds):
            self.calls += 1
            cancel_delivered.set()
            return GISAnalysisCancelBatchResult(
                claimed=0,
                completed=0,
                signalled=0,
                reconciliation_required=0,
                retry_pending=0,
                failed=0,
                command_ids=(),
            )

    cancel_consumer = _CancelConsumer()
    worker = GISAnalysisCommandWorker(
        _BlockingConsumer(),
        config,
        cancel_consumer=cancel_consumer,
        clock=lambda: NOW,
    )

    assert worker.run(once=True) == 0
    assert cancel_delivered.is_set()
    assert cancel_consumer.calls >= 1


def test_probe_cli_reports_health_and_invalid_window(tmp_path, capsys) -> None:
    config = _config(tmp_path)
    GISAnalysisCommandWorker(
        _Consumer([_batch()]),
        config,
        clock=lambda: datetime.now(UTC),
    ).run_cycle()
    probe_args = [
        "--status-file",
        str(config.status_file),
        "--max-age-seconds",
        "180",
    ]

    assert main(["health", *probe_args]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "healthy"
    assert main(["liveness", *probe_args]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "healthy"
    assert main(["health", "--max-age-seconds", "nan"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_max_age"


def test_validate_cli_probes_dependencies_and_disposes_provider_engine(
    tmp_path,
    capsys,
) -> None:
    config = _config(tmp_path)

    class _ProviderEngine:
        disposed = False

        def dispose(self):
            self.disposed = True

    provider_engine = _ProviderEngine()
    canceller_engine = _ProviderEngine()
    probes = []
    with (
        patch.object(
            worker_module.GISAnalysisCommandWorkerConfig,
            "from_env",
            return_value=config,
        ),
        patch.object(worker_module, "_platform_engine", return_value=object()),
        patch.object(worker_module, "_provider_engine", return_value=provider_engine),
        patch.object(worker_module, "_canceller_engine", return_value=canceller_engine),
        patch.object(worker_module, "_build_result_store", return_value=object()),
        patch.object(
            worker_module,
            "_probe_platform_database",
            side_effect=lambda _: probes.append("platform"),
        ),
        patch.object(
            worker_module,
            "_probe_provider_dependencies",
            side_effect=lambda *_: probes.append("provider"),
        ),
    ):
        assert main(["validate"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "gda.gis_analysis_command_worker.v1"
    assert report["status"] == "valid"
    assert probes == ["platform", "provider"]
    assert provider_engine.disposed is True
    assert canceller_engine.disposed is True
    assert PROVIDER_SECRET not in json.dumps(report)
