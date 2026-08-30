import json
import stat
import threading
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data_agent.dolphinscheduler_command_consumer import CommandBatchResult
from data_agent.dolphinscheduler_command_worker import (
    DolphinSchedulerCommandWorker,
    DolphinSchedulerCommandWorkerConfig,
    WorkerConfigurationError,
    WorkerStatusStore,
    evaluate_worker_health,
    evaluate_worker_liveness,
    main,
)
from data_agent.platform_gateway import GatewayUnavailableError

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=UTC)
TENANT = "tenant-a"
WORKER_ID = "worker:dolphinscheduler-command:pod-a"


def _config(tmp_path, **overrides):
    token_file = tmp_path / "dolphinscheduler.token"
    token_file.write_text("fixture-token-value\n", encoding="utf-8")
    token_file.chmod(0o600)
    values = {
        "tenant_id": TENANT,
        "worker_id": WORKER_ID,
        "base_url": "https://dolphinscheduler.example.com/dolphinscheduler",
        "token_file": token_file,
        "project_code": 1001,
        "workload_subject": "workload:dataops-adapter",
        "policy_evaluator_subject": "workload:policy-evaluator",
        "timezone_name": "Asia/Shanghai",
        "batch_size": 10,
        "lease_seconds": 60,
        "poll_interval_seconds": 5,
        "status_file": tmp_path / "worker-status.json",
        "health_max_age_seconds": 30,
    }
    values.update(overrides)
    return DolphinSchedulerCommandWorkerConfig(**values)


def _batch(**overrides):
    values = {
        "claimed": 1,
        "completed": 1,
        "deferred_to_reconcile": 0,
        "retry_pending": 0,
        "failed": 0,
        "command_ids": (),
    }
    values.update(overrides)
    return CommandBatchResult(**values)


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


def test_worker_config_requires_distinct_identity_and_safe_lease(tmp_path):
    with pytest.raises(ValidationError, match="lease"):
        _config(tmp_path, request_timeout_seconds=60, lease_seconds=60)
    with pytest.raises(ValidationError, match="worker_id"):
        _config(tmp_path, worker_id="shared-process-name")
    with pytest.raises(ValidationError, match="absolute"):
        _config(tmp_path, status_file="relative/status.json")


def test_worker_profile_reads_only_owner_scoped_token_file(tmp_path):
    config = _config(tmp_path)
    config.token_file.chmod(0o640)
    with pytest.raises(WorkerConfigurationError, match="profile"):
        config.build_profile()

    config.token_file.chmod(0o600)
    profile = config.build_profile()
    assert profile.access_token.get_secret_value() == "fixture-token-value"
    assert profile.timezone_name == "Asia/Shanghai"
    assert "fixture-token-value" not in json.dumps(config.safe_summary())


def test_worker_config_from_env_is_strict_and_keeps_token_out_of_summary(
    tmp_path, monkeypatch
):
    token_file = tmp_path / "provider.token"
    token_file.write_text("env-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    values = {
        "DOLPHINSCHEDULER_COMMAND_TENANT_ID": TENANT,
        "DOLPHINSCHEDULER_COMMAND_WORKER_ID": WORKER_ID,
        "DOLPHINSCHEDULER_BASE_URL": "https://ds.example.com",
        "DOLPHINSCHEDULER_TOKEN_FILE": str(token_file),
        "DOLPHINSCHEDULER_PROJECT_CODE": "1001",
        "DOLPHINSCHEDULER_WORKLOAD_SUBJECT": "workload:dataops-adapter",
        "DOLPHINSCHEDULER_POLICY_EVALUATOR_SUBJECT": (
            "workload:policy-evaluator"
        ),
        "DOLPHINSCHEDULER_TIMEZONE_NAME": "Asia/Tokyo",
        "DOLPHINSCHEDULER_COMMAND_STATUS_FILE": str(
            tmp_path / "worker.json"
        ),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    config = DolphinSchedulerCommandWorkerConfig.from_env()
    assert config.tenant_id == TENANT
    assert config.worker_id == WORKER_ID
    assert config.timezone_name == "Asia/Tokyo"
    assert "env-token" not in json.dumps(config.safe_summary())

    monkeypatch.delenv("DOLPHINSCHEDULER_COMMAND_WORKER_ID")
    with pytest.raises(WorkerConfigurationError):
        DolphinSchedulerCommandWorkerConfig.from_env()


def test_successful_cycle_writes_fresh_redacted_health_status(tmp_path):
    config = _config(tmp_path)
    consumer = _Consumer([_batch(claimed=2, completed=1, retry_pending=1)])
    worker = DolphinSchedulerCommandWorker(
        consumer,
        config,
        clock=lambda: NOW,
    )

    result = worker.run_cycle()

    assert result is not None
    assert consumer.calls == [(TENANT, WORKER_ID, 10, 60)]
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "ready"
    assert status.claimed == 2
    assert status.completed == 1
    assert status.retry_pending == 1
    assert stat.S_IMODE(config.status_file.stat().st_mode) == 0o600
    assert "fixture-token-value" not in config.status_file.read_text()
    health, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=NOW + timedelta(seconds=10),
    )
    assert healthy is True
    assert health["status"] == "healthy"


def test_gateway_failure_marks_worker_degraded_without_leaking_error(tmp_path):
    config = _config(tmp_path)
    consumer = _Consumer([GatewayUnavailableError("private database detail")])
    worker = DolphinSchedulerCommandWorker(
        consumer,
        config,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None

    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "degraded"
    assert status.last_error_code == "platform_unavailable"
    rendered = config.status_file.read_text()
    assert "private database detail" not in rendered
    health, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=NOW,
    )
    assert healthy is False
    assert health["reason"] == "worker_degraded"
    liveness, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=NOW,
    )
    assert live is True
    assert liveness["worker_state"] == "degraded"


def test_probe_cli_keeps_fresh_degraded_worker_live(tmp_path, capsys):
    config = _config(tmp_path)
    worker = DolphinSchedulerCommandWorker(
        _Consumer([GatewayUnavailableError("database unavailable")]),
        config,
        clock=lambda: datetime.now(UTC),
    )
    assert worker.run_cycle() is None

    probe_args = [
        "--status-file",
        str(config.status_file),
        "--max-age-seconds",
        "30",
    ]
    assert main(["health", *probe_args]) == 1
    readiness = json.loads(capsys.readouterr().out)
    assert readiness["reason"] == "worker_degraded"

    assert main(["liveness", *probe_args]) == 0
    liveness = json.loads(capsys.readouterr().out)
    assert liveness["status"] == "healthy"
    assert liveness["worker_state"] == "degraded"


def test_health_fails_closed_for_stale_or_missing_status(tmp_path):
    config = _config(tmp_path)
    worker = DolphinSchedulerCommandWorker(
        _Consumer([_batch()]),
        config,
        clock=lambda: NOW,
    )
    worker.run_cycle()

    health, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=NOW + timedelta(seconds=31),
    )
    assert healthy is False
    assert health["reason"] == "status_stale"

    missing, healthy = evaluate_worker_health(
        WorkerStatusStore(tmp_path / "missing.json"),
        max_age_seconds=30,
        now=NOW,
    )
    assert healthy is False
    assert missing == {"status": "unhealthy", "reason": "status_unavailable"}

    invalid, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=float("nan"),
        now=NOW,
    )
    assert healthy is False
    assert invalid["reason"] == "invalid_health_window"

    invalid_now, healthy = evaluate_worker_health(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=datetime(2026, 7, 25, 14, 0),  # noqa: DTZ001 - invalid input fixture
    )
    assert healthy is False
    assert invalid_now["reason"] == "invalid_health_window"

    stale_liveness, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=NOW + timedelta(seconds=31),
    )
    assert live is False
    assert stale_liveness["reason"] == "status_stale"


def test_worker_drains_current_batch_then_stops_on_signal_event(tmp_path):
    config = _config(tmp_path)
    stop_event = threading.Event()

    class _StoppingConsumer(_Consumer):
        def run_once(self, *args, **kwargs):
            result = super().run_once(*args, **kwargs)
            stop_event.set()
            return result

    consumer = _StoppingConsumer([_batch()])
    worker = DolphinSchedulerCommandWorker(
        consumer,
        config,
        stop_event=stop_event,
        clock=lambda: NOW,
    )

    assert worker.run() == 0
    assert len(consumer.calls) == 1
    assert WorkerStatusStore(config.status_file).read().state == "stopped"
    liveness, live = evaluate_worker_liveness(
        WorkerStatusStore(config.status_file),
        max_age_seconds=30,
        now=NOW,
    )
    assert live is False
    assert liveness["reason"] == "worker_stopped"


def test_unexpected_consumer_bug_stops_process_instead_of_retrying_forever(
    tmp_path,
):
    config = _config(tmp_path)
    worker = DolphinSchedulerCommandWorker(
        _Consumer([RuntimeError("programming error")]),
        config,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="programming error"):
        worker.run()
    assert WorkerStatusStore(config.status_file).read().state == "stopped"


def test_terminal_command_failure_keeps_worker_ready(tmp_path):
    config = _config(tmp_path)
    worker = DolphinSchedulerCommandWorker(
        _Consumer([_batch(failed=1)]),
        config,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is not None
    status = WorkerStatusStore(config.status_file).read()
    assert status.state == "ready"
    assert status.failed == 1
    assert status.last_error_code is None


def test_health_cli_rejects_explicit_non_positive_window(tmp_path, capsys):
    assert (
        main(
            [
                "health",
                "--status-file",
                str(tmp_path / "worker.json"),
                "--max-age-seconds",
                "0",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_max_age"
