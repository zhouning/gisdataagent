import stat
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data_agent.active_metadata_consumer import ActiveMetadataBatchResult
from data_agent.active_metadata_consumer_worker import (
    ActiveMetadataConsumerStatusStore,
    ActiveMetadataConsumerWorker,
    ActiveMetadataConsumerWorkerConfig,
    ActiveMetadataWorkerConfigurationError,
    evaluate_worker_health,
    evaluate_worker_liveness,
)
from data_agent.platform_gateway import GatewayUnavailableError

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _config(tmp_path, **overrides):
    values = {
        "enabled": True,
        "tenant_id": "tenant-a",
        "worker_id": "worker:active-metadata:pod-a",
        "consumer_subject": "workload:metadata-router",
        "batch_size": 10,
        "lease_seconds": 60,
        "poll_interval_seconds": 5,
        "status_file": tmp_path / "active-metadata-status.json",
        "health_max_age_seconds": 30,
    }
    values.update(overrides)
    return ActiveMetadataConsumerWorkerConfig(**values)


def _batch(**overrides):
    values = {
        "claimed": 1,
        "staged": 1,
        "replayed": 0,
        "retry_pending": 0,
        "failed": 0,
        "request_ids": (),
    }
    values.update(overrides)
    return ActiveMetadataBatchResult(**values)


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


def test_worker_config_is_strict_and_has_no_provider_credentials(tmp_path):
    with pytest.raises(ValidationError, match="worker_id"):
        _config(tmp_path, worker_id="shared-process")
    with pytest.raises(ValidationError, match="consumer_subject"):
        _config(tmp_path, consumer_subject="human:operator")
    with pytest.raises(ValidationError, match="absolute"):
        _config(tmp_path, status_file="relative/status.json")

    summary = _config(tmp_path).safe_summary()
    assert summary["provider_credentials_configured"] is False
    assert summary["scheduler_credentials_configured"] is False


def test_config_from_env_requires_identity_and_safe_health_window(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ACTIVE_METADATA_CONSUMER_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_METADATA_CONSUMER_TENANT_ID", "tenant-a")
    monkeypatch.setenv(
        "ACTIVE_METADATA_CONSUMER_WORKER_ID", "worker:active-metadata:pod-a"
    )
    monkeypatch.setenv(
        "ACTIVE_METADATA_CONSUMER_SUBJECT", "workload:metadata-router"
    )
    monkeypatch.setenv(
        "ACTIVE_METADATA_CONSUMER_STATUS_FILE", str(tmp_path / "status.json")
    )
    config = ActiveMetadataConsumerWorkerConfig.from_env()
    assert config.tenant_id == "tenant-a"

    monkeypatch.setenv("ACTIVE_METADATA_CONSUMER_ENABLED", "false")
    with pytest.raises(ActiveMetadataWorkerConfigurationError):
        ActiveMetadataConsumerWorkerConfig.from_env()

    monkeypatch.setenv("ACTIVE_METADATA_CONSUMER_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_METADATA_CONSUMER_HEALTH_MAX_AGE_SECONDS", "5")
    with pytest.raises(ActiveMetadataWorkerConfigurationError, match="two polling"):
        ActiveMetadataConsumerWorkerConfig.from_env()


def test_worker_writes_sanitized_atomic_status_and_accumulates_counts(tmp_path):
    config = _config(tmp_path)
    store = ActiveMetadataConsumerStatusStore(config.status_file)
    consumer = _Consumer([_batch(replayed=1, retry_pending=1)])
    worker = ActiveMetadataConsumerWorker(
        consumer,
        config,
        status_store=store,
        clock=lambda: NOW,
    )

    result = worker.run_cycle()

    assert result is not None
    status = store.read()
    assert status.state == "ready"
    assert status.claimed == status.staged == status.replayed == 1
    assert status.retry_pending == 1
    assert stat.S_IMODE(config.status_file.stat().st_mode) == 0o600
    rendered = config.status_file.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in rendered
    assert "provider" not in rendered


def test_worker_degrades_on_gateway_error_and_recovers_next_cycle(tmp_path):
    config = _config(tmp_path)
    store = ActiveMetadataConsumerStatusStore(config.status_file)
    consumer = _Consumer(
        [GatewayUnavailableError("database unavailable"), _batch(claimed=0, staged=0)]
    )
    worker = ActiveMetadataConsumerWorker(
        consumer,
        config,
        status_store=store,
        clock=lambda: NOW,
    )

    assert worker.run_cycle() is None
    assert store.read().state == "degraded"
    assert store.read().last_error_code == "platform_unavailable"

    assert worker.run_cycle() is not None
    assert store.read().state == "ready"
    assert store.read().consecutive_gateway_failures == 0


def test_health_and_liveness_separate_database_readiness_from_process(tmp_path):
    config = _config(tmp_path)
    store = ActiveMetadataConsumerStatusStore(config.status_file)
    worker = ActiveMetadataConsumerWorker(
        _Consumer([_batch(claimed=0, staged=0)]),
        config,
        status_store=store,
        clock=lambda: NOW,
    )
    worker.run_cycle()

    health, ready = evaluate_worker_health(
        store,
        max_age_seconds=30,
        now=NOW + timedelta(seconds=10),
    )
    liveness, alive = evaluate_worker_liveness(
        store,
        max_age_seconds=30,
        now=NOW + timedelta(seconds=10),
    )
    assert ready is alive is True
    assert health["status"] == liveness["status"] == "healthy"

    stale, ready = evaluate_worker_health(
        store,
        max_age_seconds=5,
        now=NOW + timedelta(seconds=10),
    )
    assert ready is False
    assert stale["reason"] == "status_stale"


def test_once_mode_stops_after_one_cycle_and_returns_failure_on_gateway_error(
    tmp_path,
):
    config = _config(tmp_path)
    success = ActiveMetadataConsumerWorker(
        _Consumer([_batch(claimed=0, staged=0)]),
        config,
        clock=lambda: NOW,
    )
    assert success.run(once=True) == 0
    assert success.status is not None and success.status.state == "stopped"

    failed = ActiveMetadataConsumerWorker(
        _Consumer([GatewayUnavailableError("database unavailable")]),
        config,
        clock=lambda: NOW,
    )
    assert failed.run(once=True) == 1
    assert failed.status is not None and failed.status.state == "stopped"
