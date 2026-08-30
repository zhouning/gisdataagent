from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from data_agent.gis_mvt_cache_purge import (
    GIS_MVT_CACHE_PURGE_WORKLOAD,
    GISMVTCachePurgeProvider,
    GISMVTCachePurgeStatus,
    GISMVTCachePurgeTask,
)
from data_agent.gis_mvt_cache_purge_worker import (
    GISMVTCachePurgeWorker,
    GISMVTCachePurgeWorkerConfig,
)
from data_agent.gis_mvt_response_cache import MVTCachePurgeError, MVTCachePurgeResult

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
TENANT = "planning"


def _task(*, status: GISMVTCachePurgeStatus = GISMVTCachePurgeStatus.IN_FLIGHT):
    release_id = uuid4()
    endpoint_id = uuid4()
    context = {
        "schema": "gda.gis_mvt_cache_namespace.v1",
        "namespace": "district-features-v1",
        "tenant_id": TENANT,
        "service_urn": "gda://planning/gis_service/district-features",
        "service_release_binding_id": str(release_id),
        "service_release_sha256": "a" * 64,
        "cache_policy_version_id": str(uuid4()),
        "cache_policy_sha256": "b" * 64,
        "service_policy_binding_id": str(uuid4()),
        "service_policy_sha256": "c" * 64,
        "mvt_serving_projection_version_id": str(uuid4()),
        "mvt_serving_projection_sha256": "d" * 64,
        "endpoint_state_version": 4,
        "endpoint_revision_id": str(endpoint_id),
        "endpoint_sha256": "e" * 64,
    }
    from data_agent.gis_mvt_response_cache import mvt_response_cache_namespace

    token = mvt_response_cache_namespace(context)
    return GISMVTCachePurgeTask(
        tenant_id=TENANT,
        purge_task_id=uuid4(),
        source_kind="cutover",
        source_receipt_id=uuid4(),
        source_receipt_sha256="f" * 64,
        service_urn=context["service_urn"],
        endpoint_revision_id=endpoint_id,
        service_definition_version_id=uuid4(),
        service_release_binding_id=release_id,
        endpoint_state_version=4,
        cache_namespace=context["namespace"],
        cache_context=context,
        generation_token=token,
        status=status,
        attempt_count=1,
        max_attempts=5,
        available_at=NOW,
        claimed_by="worker-1" if status == GISMVTCachePurgeStatus.IN_FLIGHT else None,
        claimed_until=NOW,
        created_at=NOW,
    )


class _Gateway:
    def __init__(self, task):
        self.task = task
        self.completed = []
        self.failed = []

    def claim_gis_mvt_cache_purges(self, *_args, **kwargs):
        assert kwargs["actor_subject"] == GIS_MVT_CACHE_PURGE_WORKLOAD
        return (self.task,)

    def complete_gis_mvt_cache_purge(self, *args, **kwargs):
        self.completed.append((args, kwargs))
        return SimpleNamespace(status=GISMVTCachePurgeStatus.DONE)

    def fail_gis_mvt_cache_purge(self, *args, **kwargs):
        self.failed.append((args, kwargs))
        return SimpleNamespace(status=GISMVTCachePurgeStatus.PENDING)


class _Cache:
    enabled = True

    async def purge_namespace(self, namespace, *, max_keys, scan_count):
        return MVTCachePurgeResult(True, namespace, 2, 2, 0)


class _BrokenCache(_Cache):
    async def purge_namespace(self, *_args, **_kwargs):
        raise MVTCachePurgeError("Redis unavailable")


class _AlternatePurgeProvider:
    provider_kind = "alternate-cache"
    enabled = True

    def __init__(self):
        self.calls = []
        self.closed = False

    async def purge_generation(self, generation_token, *, max_keys, scan_count):
        self.calls.append((generation_token, max_keys, scan_count))
        return MVTCachePurgeResult(True, generation_token, 3, 3, 0)

    async def aclose(self):
        self.closed = True


def test_task_rejects_generation_context_mismatch():
    task = _task()
    with pytest.raises(ValueError, match="generation"):
        GISMVTCachePurgeTask.model_validate(
            task.model_dump(mode="python") | {"generation_token": "0" * 64}
        )


def test_worker_rejects_purge_bound_above_cache_adapter_limit():
    with pytest.raises(ValueError, match="100000"):
        GISMVTCachePurgeWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker-1",
            max_keys=100_001,
        ).validate()


def test_worker_completes_exact_generation_and_records_counts():
    gateway = _Gateway(_task())
    worker = GISMVTCachePurgeWorker(
        GISMVTCachePurgeWorkerConfig(tenant_id=TENANT, worker_id="worker-1"),
        gateway=gateway,
        cache=_Cache(),
    )
    try:
        cycle = worker.run_once()
    finally:
        worker.close()
    assert cycle.claimed == 1
    assert cycle.completed == 1
    assert cycle.retrying == 0
    assert gateway.completed[0][1]["matched_keys"] == 2
    assert gateway.completed[0][1]["remaining_keys"] == 0


def test_worker_retries_when_redis_purge_cannot_be_certified():
    gateway = _Gateway(_task())
    worker = GISMVTCachePurgeWorker(
        GISMVTCachePurgeWorkerConfig(tenant_id=TENANT, worker_id="worker-1"),
        gateway=gateway,
        cache=_BrokenCache(),
    )
    try:
        cycle = worker.run_once()
    finally:
        worker.close()
    assert cycle == cycle.__class__(1, 0, 1, 0)
    assert "MVTCachePurgeError" in gateway.failed[0][1]["error"]


def test_worker_accepts_provider_neutral_purge_adapter():
    task = _task()
    gateway = _Gateway(task)
    provider = _AlternatePurgeProvider()
    assert isinstance(provider, GISMVTCachePurgeProvider)
    worker = GISMVTCachePurgeWorker(
        GISMVTCachePurgeWorkerConfig(tenant_id=TENANT, worker_id="worker-1"),
        gateway=gateway,
        purge_provider=provider,
    )
    cycle = worker.run_once()
    worker.close()
    assert cycle == cycle.__class__(1, 1, 0, 0)
    assert provider.calls == [(task.generation_token, 10_000, 100)]
    assert provider.closed is True


def test_worker_rejects_two_purge_provider_inputs():
    with pytest.raises(ValueError, match="not both"):
        GISMVTCachePurgeWorker(
            GISMVTCachePurgeWorkerConfig(tenant_id=TENANT, worker_id="worker-1"),
            cache=_Cache(),
            purge_provider=_AlternatePurgeProvider(),
        )


def test_worker_config_selects_http_provider_from_environment(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("token", encoding="utf-8")
    monkeypatch.setenv("GDA_GIS_MVT_CACHE_PURGE_TENANT_ID", TENANT)
    monkeypatch.setenv("GDA_GIS_MVT_CACHE_PURGE_PROVIDER", "http")
    monkeypatch.setenv(
        "GDA_GIS_MVT_CACHE_PURGE_HTTP_ENDPOINT_URL", "http://127.0.0.1:8080/purge"
    )
    monkeypatch.setenv(
        "GDA_GIS_MVT_CACHE_PURGE_HTTP_BEARER_TOKEN_FILE", str(token_file)
    )
    config = GISMVTCachePurgeWorkerConfig.from_env()
    assert config.provider_kind == "http"
    assert config.http_endpoint_url.endswith("/purge")
    assert config.http_bearer_token_file == token_file


def test_worker_config_rejects_http_without_endpoint():
    with pytest.raises(ValueError, match="endpoint"):
        GISMVTCachePurgeWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker-1",
            provider_kind="http",
        ).validate()


def test_worker_config_rejects_unknown_provider():
    with pytest.raises(ValueError, match="redis or http"):
        GISMVTCachePurgeWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker-1",
            provider_kind="cdn",
        ).validate()


def test_worker_builds_http_provider_from_explicit_config(tmp_path: Path):
    token_file = tmp_path / "token"
    token_file.write_text("token", encoding="utf-8")
    config = GISMVTCachePurgeWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker-1",
        provider_kind="http",
        http_endpoint_url="http://127.0.0.1:8080/purge",
        http_bearer_token_file=token_file,
    )
    worker = GISMVTCachePurgeWorker(config, gateway=_Gateway(_task()))
    try:
        assert worker.purge_provider.provider_kind == "http_cache_purge"
    finally:
        worker.close()
