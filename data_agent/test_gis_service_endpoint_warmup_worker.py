import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from data_agent.gis_service_endpoint_warmup_consumer import (
    GISServiceEndpointWarmupBatchResult,
    GISServiceEndpointWarmupConsumer,
)
from data_agent.gis_service_endpoint_warmup_worker import (
    WORKER_SCHEMA,
    GISServiceEndpointWarmupWorker,
    GISServiceEndpointWarmupWorkerConfig,
)


def _config(tmp_path, **changes):
    values = {
        "tenant_id": "planning",
        "worker_id": "worker:warmup-1",
        "martin_origin_uri": "http://martin:3000",
        "receipt_root": tmp_path / "receipts",
        "provider_timeout_seconds": 1,
        "batch_size": 1,
        "lease_seconds": 120,
        "retry_delay_seconds": 7,
        "poll_interval_seconds": 0.1,
        "status_file": tmp_path / "status" / "warmup.json",
    }
    values.update(changes)
    return GISServiceEndpointWarmupWorkerConfig(**values)


def test_worker_config_requires_lease_for_every_claimed_provider_budget(tmp_path):
    with pytest.raises(ValidationError, match="lease must cover"):
        _config(
            tmp_path,
            provider_timeout_seconds=10,
            batch_size=2,
            lease_seconds=1200,
        )


def test_worker_run_once_updates_machine_readable_status(tmp_path):
    config = _config(tmp_path)
    consumer = MagicMock(spec=GISServiceEndpointWarmupConsumer)
    command_id = uuid4()
    consumer.run_once.return_value = GISServiceEndpointWarmupBatchResult(
        claimed=1,
        completed=1,
        succeeded=1,
        retry_pending=0,
        failed=0,
        command_ids=(command_id,),
    )
    worker = GISServiceEndpointWarmupWorker(config, consumer)

    result = worker.run_once()

    assert result.command_ids == (command_id,)
    status = json.loads(config.status_file.read_text(encoding="utf-8"))
    assert status["schema"] == WORKER_SCHEMA
    assert status["state"] == "ready"
    assert status["claimed"] == 1
    assert status["succeeded"] == 1
    consumer.run_once.assert_called_once_with(
        "planning",
        worker_id="worker:warmup-1",
        limit=1,
        lease_seconds=120,
    )


def test_worker_config_keeps_status_outside_receipt_evidence(tmp_path):
    with pytest.raises(ValidationError, match="outside the receipt root"):
        _config(
            tmp_path,
            status_file=tmp_path / "receipts" / "status.json",
        )


def test_worker_config_requires_exactly_one_receipt_backend(tmp_path):
    with pytest.raises(ValidationError, match="cannot configure S3"):
        _config(
            tmp_path,
            s3_bucket="gis-agent-evidence",
            s3_prefix="gis-warmup-receipts/v1",
        )
    with pytest.raises(ValidationError, match="cannot configure receipt root"):
        _config(
            tmp_path,
            receipt_backend="s3",
            s3_bucket="gis-agent-evidence",
            s3_prefix="gis-warmup-receipts/v1",
        )
    with pytest.raises(ValidationError, match="requires bucket and prefix"):
        _config(
            tmp_path,
            receipt_backend="s3",
            receipt_root=None,
        )


def test_worker_config_accepts_versioned_s3_receipt_profile(tmp_path):
    config = _config(
        tmp_path,
        receipt_backend="s3",
        receipt_root=None,
        s3_bucket="gis-agent-evidence",
        s3_prefix="gis-warmup-receipts/v1",
        s3_connect_timeout_seconds=1,
        s3_read_timeout_seconds=1,
    )

    assert config.receipt_backend == "s3"
    assert config.s3_bucket == "gis-agent-evidence"
    assert config.receipt_root is None


def test_worker_from_config_builds_and_probes_s3_store(tmp_path):
    config = _config(
        tmp_path,
        receipt_backend="s3",
        receipt_root=None,
        s3_bucket="gis-agent-evidence",
        s3_prefix="gis-warmup-receipts/v1",
        s3_connect_timeout_seconds=1,
        s3_read_timeout_seconds=1,
    )
    receipt_store = MagicMock()

    with (
        patch(
            "data_agent.gis_service_endpoint_warmup_worker.get_engine",
            return_value=MagicMock(),
        ),
        patch(
            "data_agent.gis_service_endpoint_warmup_worker.PlatformGateway"
        ),
        patch(
            "data_agent.gis_service_endpoint_warmup_worker."
            "build_s3_warmup_receipt_store",
            return_value=receipt_store,
        ) as build_store,
    ):
        worker = GISServiceEndpointWarmupWorker.from_config(config)

    build_store.assert_called_once_with(
        bucket="gis-agent-evidence",
        prefix="gis-warmup-receipts/v1",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
    )
    receipt_store.probe.assert_called_once_with()
    assert worker.consumer.receipt_store is receipt_store


def test_worker_s3_profile_status_excludes_bucket_and_credentials(tmp_path):
    config = _config(
        tmp_path,
        receipt_backend="s3",
        receipt_root=None,
        s3_bucket="gis-agent-evidence",
        s3_prefix="gis-warmup-receipts/v1",
        s3_connect_timeout_seconds=1,
        s3_read_timeout_seconds=1,
    )
    worker = GISServiceEndpointWarmupWorker(
        config,
        MagicMock(spec=GISServiceEndpointWarmupConsumer),
    )

    status = worker._status("starting")

    assert status["receipt_backend"] == "s3"
    assert "s3_bucket" not in status
    assert all("credential" not in key and "secret" not in key for key in status)


def test_worker_loads_s3_profile_from_environment(monkeypatch, tmp_path):
    values = {
        "GDA_GIS_WARMUP_TENANT_ID": "planning",
        "GDA_GIS_WARMUP_WORKER_ID": "worker:warmup-1",
        "GDA_GIS_WARMUP_MARTIN_ORIGIN_URI": "http://martin:3000",
        "GDA_GIS_WARMUP_RECEIPT_BACKEND": "s3",
        "GDA_GIS_WARMUP_S3_BUCKET": "gis-agent-evidence",
        "GDA_GIS_WARMUP_S3_PREFIX": "gis-warmup-receipts/v1",
        "GDA_GIS_WARMUP_S3_CONNECT_TIMEOUT_SECONDS": "1",
        "GDA_GIS_WARMUP_S3_READ_TIMEOUT_SECONDS": "1",
        "GDA_GIS_WARMUP_PROVIDER_TIMEOUT_SECONDS": "1",
        "GDA_GIS_WARMUP_LEASE_SECONDS": "120",
        "GDA_GIS_WARMUP_STATUS_FILE": str(tmp_path / "status.json"),
    }
    monkeypatch.delenv("GDA_GIS_WARMUP_RECEIPT_ROOT", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = GISServiceEndpointWarmupWorkerConfig.from_env()

    assert config.receipt_backend == "s3"
    assert config.s3_bucket == "gis-agent-evidence"
    assert config.receipt_root is None
