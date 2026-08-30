from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.gis_service_endpoint_warmup import (
    GIS_SERVICE_ENDPOINT_WARMUP_ARTIFACT_SCHEMA,
    GISServiceEndpointWarmupReceipt,
    gis_service_endpoint_warmup_artifact_manifest,
    gis_service_endpoint_warmup_fingerprint,
)


def _values() -> dict[str, object]:
    completed_at = datetime(2026, 8, 21, 14, 0, 5, tzinfo=UTC)
    return {
        "tenant_id": "tenant-a",
        "warmup_id": UUID("00000000-0000-4000-8000-000000000001"),
        "service_urn": "gda://tenant-a/gis_service/parcels",
        "endpoint_revision_id": UUID("00000000-0000-4000-8000-000000000002"),
        "deployment_revision_id": UUID("00000000-0000-4000-8000-000000000003"),
        "service_definition_version_id": UUID(
            "00000000-0000-4000-8000-000000000004"
        ),
        "service_release_binding_id": UUID(
            "00000000-0000-4000-8000-000000000005"
        ),
        "cache_policy_version_id": UUID(
            "00000000-0000-4000-8000-000000000006"
        ),
        "cache_namespace": "tenant-a.parcels.release-v2",
        "run_id": UUID("00000000-0000-4000-8000-000000000007"),
        "evidence_artifact_id": UUID(
            "00000000-0000-4000-8000-000000000008"
        ),
        "requested_sample_count": 4,
        "successful_sample_count": 4,
        "sample_set_sha256": "a" * 64,
        "provider_receipt_sha256": "b" * 64,
        "started_at": completed_at - timedelta(seconds=5),
        "completed_at": completed_at,
        "valid_until": completed_at + timedelta(seconds=120),
        "recorded_by": "workload:gis-warmup-controller",
        "recorded_at": completed_at + timedelta(seconds=2),
    }


def test_warmup_receipt_fingerprint_and_artifact_manifest() -> None:
    values = _values()
    receipt = GISServiceEndpointWarmupReceipt(
        **values,
        warmup_sha256=gis_service_endpoint_warmup_fingerprint(values),
    )
    manifest = gis_service_endpoint_warmup_artifact_manifest(receipt)
    assert manifest["schema"] == GIS_SERVICE_ENDPOINT_WARMUP_ARTIFACT_SCHEMA
    assert manifest["endpoint_revision_id"] == str(receipt.endpoint_revision_id)
    assert manifest["completed_at"] == "2026-08-21T14:00:05.000000+00:00"


def test_warmup_receipt_requires_complete_samples_and_live_window() -> None:
    values = _values()
    values["successful_sample_count"] = 3
    values["warmup_sha256"] = gis_service_endpoint_warmup_fingerprint(values)
    with pytest.raises(ValidationError, match="every requested warmup sample"):
        GISServiceEndpointWarmupReceipt(**values)

    values = _values()
    values["recorded_at"] = values["valid_until"]
    values["warmup_sha256"] = gis_service_endpoint_warmup_fingerprint(values)
    with pytest.raises(ValidationError, match="live evidence window"):
        GISServiceEndpointWarmupReceipt(**values)


def test_warmup_receipt_rejects_stale_fingerprint() -> None:
    with pytest.raises(ValidationError, match="warmup_sha256"):
        GISServiceEndpointWarmupReceipt(**_values(), warmup_sha256="f" * 64)


def test_warmup_receipt_requires_workload_authority() -> None:
    values = _values()
    values["recorded_by"] = "human:operator"
    values["warmup_sha256"] = gis_service_endpoint_warmup_fingerprint(values)
    with pytest.raises(ValidationError, match="warmup workload"):
        GISServiceEndpointWarmupReceipt(**values)
