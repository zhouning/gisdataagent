"""Contract tests for immutable metric-query result storage backends."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from uuid import UUID

import pytest

from data_agent.metric_query_result_store import (
    METRIC_QUERY_RESULT_MEDIA_TYPE,
    LocalMetricQueryResultStore,
    MetricQueryResultStoreConflict,
    MetricQueryResultStoreUnavailable,
    S3MetricQueryResultStore,
    validate_s3_result_location,
)

TENANT = "tenant-a"
RUN_ID = UUID("5e268bf1-86dd-5de4-8a94-10dd41aa120f")
PAYLOAD = b'{"schema":"gda.metric_query_result.v1","rows":[]}\n'


class _S3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[dict] = []
        self.probe_calls: list[str] = []
        self.fail_operation: str | None = None
        self.versioning_status = "Enabled"
        self.object_lock_enabled = "Enabled"
        self.default_retention: dict = {"Mode": "GOVERNANCE", "Days": 1}
        self.version_ids: dict[tuple[str, str], str] = {}
        self.metadata: dict[tuple[str, str], dict] = {}
        self.content_types: dict[tuple[str, str], str] = {}

    def put_object(self, **kwargs):
        if self.fail_operation == "put":
            raise _S3Error("ServiceUnavailable")
        self.put_calls.append(kwargs)
        identity = (kwargs["Bucket"], kwargs["Key"])
        if kwargs.get("IfNoneMatch") == "*" and identity in self.objects:
            raise _S3Error("PreconditionFailed")
        self.objects[identity] = kwargs["Body"]
        self.version_ids[identity] = "version-1"
        self.metadata[identity] = kwargs["Metadata"]
        self.content_types[identity] = kwargs["ContentType"]
        return {"VersionId": "version-1", "ETag": '"etag-1"'}

    def get_object(self, *, Bucket, Key, VersionId):
        if self.fail_operation == "get":
            raise _S3Error("ServiceUnavailable")
        assert VersionId == self.version_ids.get((Bucket, Key), "version-existing")
        try:
            payload = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise _S3Error("NoSuchKey") from exc
        return {"Body": io.BytesIO(payload), "VersionId": VersionId}

    def head_object(self, *, Bucket, Key, VersionId=None):
        identity = (Bucket, Key)
        try:
            payload = self.objects[identity]
        except KeyError as exc:
            raise _S3Error("NoSuchKey") from exc
        version_id = self.version_ids.setdefault(identity, "version-existing")
        if VersionId is not None and VersionId != version_id:
            raise _S3Error("NoSuchVersion")
        return {
            "VersionId": version_id,
            "ETag": '"etag-1"' if version_id == "version-1" else '"etag-existing"',
            "ContentLength": len(payload),
            "ContentType": self.content_types.get(
                identity, METRIC_QUERY_RESULT_MEDIA_TYPE
            ),
            "Metadata": self.metadata.get(
                identity, {"sha256": hashlib.sha256(payload).hexdigest()}
            ),
        }

    def get_bucket_versioning(self, *, Bucket):
        self.probe_calls.append(f"versioning:{Bucket}")
        if self.fail_operation == "head":
            raise _S3Error("AccessDenied")
        return {"Status": self.versioning_status}

    def get_object_lock_configuration(self, *, Bucket):
        self.probe_calls.append(f"object-lock:{Bucket}")
        if self.fail_operation == "head":
            raise _S3Error("AccessDenied")
        return {
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": self.object_lock_enabled,
                "Rule": {"DefaultRetention": self.default_retention},
            }
        }


def test_local_store_is_write_once_and_replayable(tmp_path: Path) -> None:
    store = LocalMetricQueryResultStore(tmp_path / "results")

    first = store.put(TENANT, RUN_ID, PAYLOAD)
    replay = store.put(TENANT, RUN_ID, PAYLOAD)

    assert first == replay
    assert first.storage_uri.startswith("file://")
    assert first.storage_evidence() == {
        "schema": "gda.local_result_publication.v1"
    }
    assert Path(first.storage_uri.removeprefix("file://")).read_bytes() == PAYLOAD
    with pytest.raises(MetricQueryResultStoreConflict, match="different content"):
        store.put(TENANT, RUN_ID, b"different")
    with pytest.raises(MetricQueryResultStoreConflict, match="tenant identity"):
        store.put("../escape", RUN_ID, PAYLOAD)


def test_local_store_probe_is_non_persistent_and_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "results"
    store = LocalMetricQueryResultStore(root)

    store.probe()

    assert list(root.iterdir()) == []
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(MetricQueryResultStoreUnavailable, match="probe failed"):
        LocalMetricQueryResultStore(blocked).probe()


def test_s3_store_conditionally_creates_and_verifies_exact_bytes() -> None:
    client = _MemoryS3()
    store = S3MetricQueryResultStore(
        client,
        bucket="gis-agent-results",
        prefix="metric-query-results/v1",
    )

    first = store.put(TENANT, RUN_ID, PAYLOAD)
    replay = store.put(TENANT, RUN_ID, PAYLOAD)

    expected_key = f"metric-query-results/v1/{TENANT}/{RUN_ID}.json"
    assert first == replay
    assert first.storage_uri == f"s3://gis-agent-results/{expected_key}"
    assert first.version_id == "version-1"
    assert first.storage_evidence() == {
        "schema": "gda.s3_object_version.v1",
        "version_id": "version-1",
        "etag": "etag-1",
    }
    assert len(client.put_calls) == 2
    assert client.put_calls[0]["IfNoneMatch"] == "*"
    assert client.put_calls[0]["ContentType"] == METRIC_QUERY_RESULT_MEDIA_TYPE
    assert client.put_calls[0]["Metadata"] == {
        "sha256": hashlib.sha256(PAYLOAD).hexdigest()
    }


def test_s3_store_rejects_existing_different_bytes_without_overwrite() -> None:
    client = _MemoryS3()
    store = S3MetricQueryResultStore(
        client,
        bucket="gis-agent-results",
        prefix="metric-query-results",
    )
    key = f"metric-query-results/{TENANT}/{RUN_ID}.json"
    client.objects[("gis-agent-results", key)] = b"different"

    with pytest.raises(MetricQueryResultStoreConflict, match="different content"):
        store.put(TENANT, RUN_ID, PAYLOAD)

    assert client.objects[("gis-agent-results", key)] == b"different"


@pytest.mark.parametrize("missing_contract", ["versioning", "object_lock", "retention"])
def test_s3_store_probe_requires_versioning_and_object_lock_retention(
    missing_contract: str,
) -> None:
    client = _MemoryS3()
    if missing_contract == "versioning":
        client.versioning_status = "Suspended"
    elif missing_contract == "object_lock":
        client.object_lock_enabled = "Disabled"
    else:
        client.default_retention = {}
    store = S3MetricQueryResultStore(
        client,
        bucket="gis-agent-results",
        prefix="metric-query-results",
    )

    with pytest.raises(MetricQueryResultStoreUnavailable, match="versioning"):
        store.probe()


@pytest.mark.parametrize("operation", ["put", "get", "head"])
def test_s3_store_dependency_failures_are_redacted(operation: str) -> None:
    client = _MemoryS3()
    client.fail_operation = operation
    store = S3MetricQueryResultStore(
        client,
        bucket="gis-agent-results",
        prefix="metric-query-results",
    )

    with pytest.raises(MetricQueryResultStoreUnavailable) as raised:
        if operation == "head":
            store.probe()
        else:
            store.put(TENANT, RUN_ID, PAYLOAD)

    assert "AccessDenied" not in str(raised.value)
    assert "ServiceUnavailable" not in str(raised.value)
    assert "endpoint" not in str(raised.value)


@pytest.mark.parametrize(
    ("bucket", "prefix"),
    [
        ("UPPERCASE", "metric-query-results"),
        ("gis-agent-results", "../escape"),
        ("gis-agent-results", "/"),
        ("gis-agent-results", "metric query results"),
    ],
)
def test_s3_location_rejects_unsafe_bucket_or_prefix(
    bucket: str,
    prefix: str,
) -> None:
    with pytest.raises(ValueError, match="metric result S3"):
        validate_s3_result_location(bucket, prefix)
