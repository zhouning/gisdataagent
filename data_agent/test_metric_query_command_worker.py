import json
import stat
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import data_agent.metric_query_command_worker as worker_module
from data_agent.metric_query_command_consumer import MetricQueryCommandBatchResult
from data_agent.metric_query_command_worker import (
    MetricQueryCommandWorker,
    MetricQueryCommandWorkerConfig,
    WorkerConfigurationError,
    WorkerProviderUnavailable,
    WorkerStatusStore,
    _build_result_store,
    _probe_result_store,
    evaluate_worker_health,
    evaluate_worker_liveness,
    main,
)
from data_agent.metric_query_result_store import MetricQueryResultStoreUnavailable
from data_agent.platform_gateway import GatewayUnavailableError

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
TENANT = "tenant-a"
WORKER_ID = "worker:metric-query-postgis:pod-a"
PROVIDER_SECRET = "provider-password-fixture"


def _config(tmp_path, **overrides):
    database_url_file = tmp_path / "postgis.url"
    database_url_file.write_text(
        f"postgresql://metric_reader:{PROVIDER_SECRET}@postgis/metrics\n",
        encoding="utf-8",
    )
    database_url_file.chmod(0o600)
    values = {
        "tenant_id": TENANT,
        "worker_id": WORKER_ID,
        "provider_database_url_file": database_url_file,
        "provider_database_role": "metric_reader",
        "result_root": tmp_path / "results",
        "relation_authority": "serving-a",
        "statement_timeout_ms": 30_000,
        "max_result_rows": 1000,
        "batch_size": 10,
        "lease_seconds": 90,
        "poll_interval_seconds": 5,
        "status_file": tmp_path / "worker-status.json",
        "health_max_age_seconds": 120,
    }
    values.update(overrides)
    return MetricQueryCommandWorkerConfig(**values)


def _batch(**overrides):
    values = {
        "claimed": 1,
        "completed": 1,
        "query_succeeded": 1,
        "query_failed": 0,
        "retry_pending": 0,
        "failed": 0,
        "command_ids": (),
    }
    values.update(overrides)
    return MetricQueryCommandBatchResult(**values)


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


def test_worker_config_bounds_cover_full_query_and_health_budgets(tmp_path):
    with pytest.raises(ValidationError, match="connection and query"):
        _config(tmp_path, lease_seconds=60)
    with pytest.raises(ValidationError, match="health max age"):
        _config(tmp_path, health_max_age_seconds=109)
    with pytest.raises(ValidationError, match="absolute"):
        _config(tmp_path, result_root="relative/results")
    with pytest.raises(ValidationError, match="filesystem root"):
        _config(tmp_path, result_root="/")
    with pytest.raises(ValidationError, match="worker_id"):
        _config(tmp_path, worker_id="shared-process-name")

    with pytest.raises(ValidationError, match="S3 bucket"):
        _config(
            tmp_path,
            result_backend="s3",
            result_root=None,
            result_s3_bucket=None,
        )
    with pytest.raises(ValidationError, match="cannot configure a local root"):
        _config(
            tmp_path,
            result_backend="s3",
            result_s3_bucket="gis-agent-results",
        )
    with pytest.raises(ValidationError, match="health max age"):
        _config(
            tmp_path,
            result_backend="s3",
            result_root=None,
            result_s3_bucket="gis-agent-results",
            health_max_age_seconds=139,
        )


def test_provider_database_url_is_owner_only_postgresql_and_redacted(tmp_path):
    config = _config(tmp_path)
    config.provider_database_url_file.chmod(0o640)
    with pytest.raises(WorkerConfigurationError, match="owner-only"):
        config.provider_database_url()

    config.provider_database_url_file.chmod(0o600)
    assert PROVIDER_SECRET in config.provider_database_url()
    rendered = json.dumps(config.safe_summary())
    assert PROVIDER_SECRET not in rendered
    assert "postgresql://" not in rendered

    wrong_role = _config(tmp_path, provider_database_role="another_reader")
    with pytest.raises(WorkerConfigurationError, match="governed role"):
        wrong_role.provider_database_url()

    config.provider_database_url_file.write_text("sqlite:///tmp.db\n", encoding="utf-8")
    with pytest.raises(WorkerConfigurationError, match="PostgreSQL"):
        config.provider_database_url()

    config.provider_database_url_file.write_text(
        "postgresql://reader:secret@db/metrics\nsecond-line\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkerConfigurationError, match="one URL"):
        config.provider_database_url()


def test_worker_config_from_env_is_strict_and_redacted(tmp_path, monkeypatch):
    config = _config(tmp_path)
    values = {
        "GDA_METRIC_QUERY_TENANT_ID": TENANT,
        "GDA_METRIC_QUERY_WORKER_ID": WORKER_ID,
        "GDA_METRIC_QUERY_POSTGIS_DATABASE_URL_FILE": str(
            config.provider_database_url_file
        ),
        "GDA_METRIC_QUERY_POSTGIS_DATABASE_ROLE": "metric_reader",
        "GDA_METRIC_QUERY_RESULT_ROOT": str(config.result_root),
        "GDA_METRIC_QUERY_POSTGIS_RELATION_AUTHORITY": "serving-env",
        "GDA_METRIC_QUERY_STATUS_FILE": str(config.status_file),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    loaded = MetricQueryCommandWorkerConfig.from_env()
    assert loaded.tenant_id == TENANT
    assert loaded.worker_id == WORKER_ID
    assert loaded.relation_authority == "serving-env"
    assert PROVIDER_SECRET not in json.dumps(loaded.safe_summary())

    monkeypatch.delenv("GDA_METRIC_QUERY_WORKER_ID")
    with pytest.raises(WorkerConfigurationError):
        MetricQueryCommandWorkerConfig.from_env()


def test_s3_worker_config_from_env_is_credential_free(tmp_path, monkeypatch):
    config = _config(tmp_path)
    values = {
        "GDA_METRIC_QUERY_TENANT_ID": TENANT,
        "GDA_METRIC_QUERY_WORKER_ID": WORKER_ID,
        "GDA_METRIC_QUERY_POSTGIS_DATABASE_URL_FILE": str(
            config.provider_database_url_file
        ),
        "GDA_METRIC_QUERY_POSTGIS_DATABASE_ROLE": "metric_reader",
        "GDA_METRIC_QUERY_POSTGIS_RELATION_AUTHORITY": "serving-env",
        "GDA_METRIC_QUERY_STATUS_FILE": str(config.status_file),
        "GDA_METRIC_QUERY_RESULT_BACKEND": "s3",
        "GDA_METRIC_QUERY_RESULT_S3_BUCKET": "gis-agent-results",
        "GDA_METRIC_QUERY_RESULT_S3_PREFIX": "metric-query-results/v1",
        "GDA_METRIC_QUERY_HEALTH_MAX_AGE_SECONDS": "180",
        "AWS_ENDPOINT_URL": "http://private-minio:9000",
        "AWS_ACCESS_KEY_ID": "private-access-key",
        "AWS_SECRET_ACCESS_KEY": "private-secret-key",
    }
    monkeypatch.delenv("GDA_METRIC_QUERY_RESULT_ROOT", raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    loaded = MetricQueryCommandWorkerConfig.from_env()
    summary = json.dumps(loaded.safe_summary())

    assert loaded.result_backend == "s3"
    assert loaded.result_root is None
    assert "s3://gis-agent-results/metric-query-results/v1/" in summary
    assert "private-minio" not in summary
    assert "private-access-key" not in summary
    assert "private-secret-key" not in summary


def test_result_store_probe_failure_is_redacted() -> None:
    class _UnavailableStore:
        backend_name = "s3"

        def probe(self):
            raise MetricQueryResultStoreUnavailable("private endpoint detail")

    with pytest.raises(
        WorkerProviderUnavailable,
        match="result store probe failed",
    ) as raised:
        _probe_result_store(_UnavailableStore())

    assert "private endpoint detail" not in str(raised.value)


def test_s3_result_store_builder_uses_bounded_path_style_client(
    tmp_path,
    monkeypatch,
):
    config = _config(
        tmp_path,
        result_backend="s3",
        result_root=None,
        result_s3_bucket="gis-agent-results",
        health_max_age_seconds=180,
    )
    client = object()
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    with patch("boto3.client", return_value=client) as factory:
        store = _build_result_store(config)

    assert store.backend_name == "s3"
    assert store.bucket == "gis-agent-results"
    factory.assert_called_once()
    service, options = factory.call_args.args[0], factory.call_args.kwargs
    assert service == "s3"
    assert options["endpoint_url"] == "http://minio:9000"
    assert options["config"].connect_timeout == 10
    assert options["config"].read_timeout == 10
    assert options["config"].s3["addressing_style"] == "path"


def test_successful_cycle_probes_before_claim_and_writes_redacted_status(tmp_path):
    config = _config(tmp_path)
    consumer = _Consumer([_batch(claimed=2, completed=1, retry_pending=1)])
    probe_calls = []
    worker = MetricQueryCommandWorker(
        consumer,
        config,
        provider_probe=lambda: probe_calls.append("probe"),
        clock=lambda: NOW,
    )

    result = worker.run_cycle()

    assert result is not None
    assert probe_calls == ["probe"]
    assert consumer.calls == [(TENANT, WORKER_ID, 10, 90)]
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "ready"
    assert status.claimed == 2
    assert status.completed == 1
    assert status.query_succeeded == 1
    assert status.retry_pending == 1
    assert stat.S_IMODE(config.status_file.stat().st_mode) == 0o600
    assert PROVIDER_SECRET not in config.status_file.read_text(encoding="utf-8")

    report, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=120,
        now=NOW + timedelta(seconds=10),
    )
    assert healthy is True
    assert report["status"] == "healthy"
    assert report["query_succeeded"] == 1


def test_provider_failure_degrades_before_claim_without_leaking_detail(tmp_path):
    config = _config(tmp_path)
    consumer = _Consumer([_batch()])

    def fail_probe():
        raise WorkerProviderUnavailable("private provider database detail")

    worker = MetricQueryCommandWorker(
        consumer,
        config,
        provider_probe=fail_probe,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    assert consumer.calls == []
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "degraded"
    assert status.last_error_code == "postgis_provider_unavailable"
    assert "private provider database detail" not in config.status_file.read_text()

    readiness, ready = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=120,
        now=NOW,
    )
    assert ready is False
    assert readiness["reason"] == "worker_degraded"
    liveness, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file),
        max_age_seconds=120,
        now=NOW,
    )
    assert live is True
    assert liveness["worker_state"] == "degraded"


def test_worker_recovers_from_provider_degradation_on_next_cycle(tmp_path):
    config = _config(tmp_path)
    consumer = _Consumer([_batch()])
    probe_attempts = []

    def recovering_probe():
        probe_attempts.append(len(probe_attempts) + 1)
        if len(probe_attempts) == 1:
            raise WorkerProviderUnavailable("temporary outage")

    worker = MetricQueryCommandWorker(
        consumer,
        config,
        provider_probe=recovering_probe,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    assert worker.run_cycle() is not None

    status = WorkerStatusStore(config.status_file).read()
    assert probe_attempts == [1, 2]
    assert status.state == "ready"
    assert status.cycles == 1
    assert status.consecutive_dependency_failures == 0
    assert status.last_error_code is None


def test_gateway_failure_marks_worker_degraded_without_leaking_detail(tmp_path):
    config = _config(tmp_path)
    worker = MetricQueryCommandWorker(
        _Consumer([GatewayUnavailableError("private platform database detail")]),
        config,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "degraded"
    assert status.last_error_code == "platform_unavailable"
    assert "private platform database detail" not in config.status_file.read_text()


def test_command_level_query_failure_keeps_process_ready(tmp_path):
    config = _config(tmp_path)
    worker = MetricQueryCommandWorker(
        _Consumer(
            [
                _batch(
                    completed=0,
                    query_succeeded=0,
                    query_failed=1,
                    failed=1,
                )
            ]
        ),
        config,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is not None
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "ready"
    assert status.query_failed == 1
    assert status.failed == 1
    assert status.last_error_code is None


def test_health_and_liveness_fail_closed_for_stale_or_missing_status(tmp_path):
    config = _config(tmp_path)
    worker = MetricQueryCommandWorker(
        _Consumer([_batch()]),
        config,
        clock=lambda: NOW,
    )
    worker.run_cycle()
    store = WorkerStatusStore(config.status_file)

    stale, healthy = evaluate_worker_health(
        store,
        max_age_seconds=120,
        now=NOW + timedelta(seconds=121),
    )
    assert healthy is False
    assert stale["reason"] == "status_stale"

    missing, healthy = evaluate_worker_health(
        WorkerStatusStore(tmp_path / "missing.json"),
        max_age_seconds=120,
        now=NOW,
    )
    assert healthy is False
    assert missing == {"status": "unhealthy", "reason": "status_unavailable"}

    invalid, healthy = evaluate_worker_health(
        store,
        max_age_seconds=float("nan"),
        now=NOW,
    )
    assert healthy is False
    assert invalid["reason"] == "invalid_health_window"

    invalid_now, live = evaluate_worker_liveness(
        store,
        max_age_seconds=120,
        now=datetime(2026, 8, 5, 12, 0),  # noqa: DTZ001 - invalid fixture
    )
    assert live is False
    assert invalid_now["reason"] == "invalid_liveness_window"


def test_worker_drains_current_batch_then_stops_on_event(tmp_path):
    config = _config(tmp_path)
    stop_event = threading.Event()

    class _StoppingConsumer(_Consumer):
        def run_once(self, *args, **kwargs):
            result = super().run_once(*args, **kwargs)
            stop_event.set()
            return result

    consumer = _StoppingConsumer([_batch()])
    worker = MetricQueryCommandWorker(
        consumer,
        config,
        stop_event=stop_event,
        clock=lambda: NOW,
    )

    assert worker.run() == 0
    assert len(consumer.calls) == 1
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "stopped"
    _, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file),
        max_age_seconds=120,
        now=NOW,
    )
    assert live is False


def test_unexpected_consumer_bug_stops_instead_of_retrying_forever(tmp_path):
    config = _config(tmp_path)
    worker = MetricQueryCommandWorker(
        _Consumer([RuntimeError("programming error")]),
        config,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="programming error"):
        worker.run()
    assert WorkerStatusStore(config.status_file).read().state == "stopped"


def test_probe_cli_reports_readiness_and_liveness(tmp_path, capsys):
    config = _config(tmp_path)
    worker = MetricQueryCommandWorker(
        _Consumer([_batch()]),
        config,
        clock=lambda: datetime.now(UTC),
    )
    worker.run_cycle()
    probe_args = [
        "--status-file",
        str(config.status_file),
        "--max-age-seconds",
        "120",
    ]

    assert main(["health", *probe_args]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "healthy"
    assert main(["liveness", *probe_args]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "healthy"

    assert (
        main(
            [
                "health",
                "--status-file",
                str(config.status_file),
                "--max-age-seconds",
                "nan",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_max_age"


def test_validate_cli_probes_all_dependencies_and_disposes_provider_engine(
    tmp_path, capsys
):
    config = _config(tmp_path)

    class _ProviderEngine:
        disposed = False

        def dispose(self):
            self.disposed = True

    provider_engine = _ProviderEngine()
    result_store = object()
    probes = []
    with (
        patch.object(
            worker_module.MetricQueryCommandWorkerConfig,
            "from_env",
            return_value=config,
        ),
        patch.object(worker_module, "_platform_engine", return_value=object()),
        patch.object(
            worker_module, "_provider_engine", return_value=provider_engine
        ),
        patch.object(
            worker_module, "_build_result_store", return_value=result_store
        ),
        patch.object(
            worker_module,
            "_probe_platform_database",
            side_effect=lambda _engine: probes.append("platform"),
        ),
        patch.object(
            worker_module,
            "_probe_postgis",
            side_effect=lambda *_args, **_kwargs: probes.append("postgis"),
        ),
        patch.object(
            worker_module,
            "_probe_result_store",
            side_effect=lambda _store: probes.append("result-store"),
        ),
    ):
        assert main(["validate"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "valid"
    assert probes == ["platform", "postgis", "result-store"]
    assert provider_engine.disposed is True
    assert PROVIDER_SECRET not in json.dumps(report)
