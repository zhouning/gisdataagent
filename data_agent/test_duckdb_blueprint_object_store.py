"""Contract tests for immutable DuckDB Blueprint object-store I/O."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from data_agent.duckdb_blueprint_object_store import (
    DUCKDB_BLUEPRINT_PARQUET_MEDIA_TYPE,
    DuckDBBlueprintObjectStoreConflict,
    DuckDBBlueprintObjectStoreUnavailable,
    S3DuckDBBlueprintObjectStore,
    blueprint_s3_output_uri,
    build_s3_duckdb_blueprint_object_store,
)
from data_agent.duckdb_blueprint_provider import (
    DuckDBBlueprintExecutionSpec,
    DuckDBBlueprintInput,
    DuckDBBlueprintPipeline,
    DuckDBBlueprintProvider,
    DuckDBBlueprintProviderUnavailableError,
    verify_duckdb_blueprint_output,
)
from data_agent.platform_gateway import GatewayConfigurationError, PlatformGateway

TENANT = "planning"
RUN_ID = UUID("00000000-0000-4000-8000-000000000a01")
OUTPUT_BUCKET = "gis-agent-blueprint-results"
OUTPUT_PREFIX = "blueprint-results/v1"


class _S3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.version_ids: dict[tuple[str, str], str] = {}
        self.etags: dict[tuple[str, str], str] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.content_types: dict[tuple[str, str], str] = {}
        self.put_calls: list[dict] = []
        self.fail_operation: str | None = None
        self.versioning_status = "Enabled"
        self.object_lock_enabled = "Enabled"
        self.default_retention: dict = {"Mode": "GOVERNANCE", "Days": 1}

    def seed(
        self,
        bucket: str,
        key: str,
        payload: bytes,
        *,
        version_id: str,
        content_type: str = DUCKDB_BLUEPRINT_PARQUET_MEDIA_TYPE,
    ) -> None:
        identity = (bucket, key)
        self.objects[identity] = payload
        self.version_ids[identity] = version_id
        self.etags[identity] = f"etag-{version_id}"
        self.metadata[identity] = {"sha256": hashlib.sha256(payload).hexdigest()}
        self.content_types[identity] = content_type

    def put_object(self, **kwargs):
        if self.fail_operation == "put":
            raise _S3Error("ServiceUnavailable")
        identity = (kwargs["Bucket"], kwargs["Key"])
        self.put_calls.append(kwargs)
        if kwargs.get("IfNoneMatch") == "*" and identity in self.objects:
            raise _S3Error("PreconditionFailed")
        body = kwargs["Body"]
        payload = body.read() if hasattr(body, "read") else bytes(body)
        self.objects[identity] = payload
        self.version_ids[identity] = "output-v1"
        self.etags[identity] = "etag-output-v1"
        self.metadata[identity] = dict(kwargs["Metadata"])
        self.content_types[identity] = kwargs["ContentType"]
        return {"VersionId": "output-v1", "ETag": '"etag-output-v1"'}

    def get_object(self, *, Bucket, Key, VersionId):
        if self.fail_operation == "get":
            raise _S3Error("SlowDown")
        identity = (Bucket, Key)
        if identity not in self.objects:
            raise _S3Error("NoSuchKey")
        if self.version_ids[identity] != VersionId:
            raise _S3Error("NoSuchVersion")
        payload = self.objects[identity]
        return {
            "Body": io.BytesIO(payload),
            "VersionId": VersionId,
            "ContentLength": len(payload),
        }

    def head_object(self, *, Bucket, Key, VersionId=None):
        identity = (Bucket, Key)
        if identity not in self.objects:
            raise _S3Error("NoSuchKey")
        observed_version = self.version_ids[identity]
        if VersionId is not None and VersionId != observed_version:
            raise _S3Error("NoSuchVersion")
        payload = self.objects[identity]
        return {
            "VersionId": observed_version,
            "ETag": f'"{self.etags[identity]}"',
            "ContentLength": len(payload),
            "ContentType": self.content_types[identity],
            "Metadata": self.metadata[identity],
        }

    def get_bucket_versioning(self, *, Bucket):
        assert Bucket == OUTPUT_BUCKET
        return {"Status": self.versioning_status}

    def get_object_lock_configuration(self, *, Bucket):
        assert Bucket == OUTPUT_BUCKET
        return {
            "ObjectLockConfiguration": {
                "ObjectLockEnabled": self.object_lock_enabled,
                "Rule": {"DefaultRetention": self.default_retention},
            }
        }


def _parquet_bytes() -> bytes:
    output = io.BytesIO()
    pq.write_table(
        pa.table({"district": ["a", "a", "b"], "area": [10.5, 4.5, 7.0]}),
        output,
    )
    return output.getvalue()


def _store(client: _MemoryS3) -> S3DuckDBBlueprintObjectStore:
    return S3DuckDBBlueprintObjectStore(
        client,
        bucket=OUTPUT_BUCKET,
        prefix=OUTPUT_PREFIX,
        input_prefixes=("s3://source-bucket/bound",),
    )


def test_object_store_downloads_exact_input_version_and_enforces_bounds(
    tmp_path: Path,
) -> None:
    client = _MemoryS3()
    payload = _parquet_bytes()
    client.seed("source-bucket", "bound/source.parquet", payload, version_id="input-v7")
    store = _store(client)
    destination = tmp_path / "source.parquet"

    size = store.download_input(
        "s3://source-bucket/bound/source.parquet",
        version_id="input-v7",
        destination=destination,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        max_bytes=len(payload),
    )

    assert size == len(payload)
    assert destination.read_bytes() == payload
    with pytest.raises(DuckDBBlueprintObjectStoreConflict, match="byte limit"):
        store.download_input(
            "s3://source-bucket/bound/source.parquet",
            version_id="input-v7",
            destination=tmp_path / "too-large.parquet",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            max_bytes=len(payload) - 1,
        )
    with pytest.raises(DuckDBBlueprintObjectStoreUnavailable):
        store.download_input(
            "s3://source-bucket/bound/source.parquet",
            version_id="other-version",
            destination=tmp_path / "wrong-version.parquet",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            max_bytes=len(payload),
        )


def test_gateway_builds_tenant_scoped_s3_output_without_data_plane_credentials() -> None:
    gateway = PlatformGateway(
        blueprint_duckdb_result_backend="s3",
        blueprint_duckdb_output_s3_bucket=OUTPUT_BUCKET,
        blueprint_duckdb_output_s3_prefix=OUTPUT_PREFIX,
        blueprint_duckdb_input_s3_prefixes=("s3://source-bucket/bound",),
    )

    assert gateway._blueprint_duckdb_output_uri(TENANT, RUN_ID) == (
        f"s3://{OUTPUT_BUCKET}/{OUTPUT_PREFIX}/{TENANT}/{RUN_ID}.parquet"
    )
    with pytest.raises(GatewayConfigurationError, match="S3 result location"):
        PlatformGateway(
            blueprint_duckdb_result_backend="s3",
            blueprint_duckdb_output_s3_bucket=OUTPUT_BUCKET,
            blueprint_duckdb_output_s3_prefix=OUTPUT_PREFIX,
            blueprint_duckdb_input_s3_prefixes=(),
        )
    with pytest.raises(GatewayConfigurationError, match="managed worker"):
        gateway.execute_blueprint_duckdb_test_run(
            TENANT,
            object(),
            actor_subject="workload:blueprint-duckdb-executor",
        )


def test_s3_input_contract_rejects_null_object_version() -> None:
    with pytest.raises(ValidationError, match="must be immutable"):
        DuckDBBlueprintInput(
            binding_name="source",
            resource_version_id=UUID("00000000-0000-4000-8000-000000000a04"),
            resource_urn="gda://planning/dataset/source",
            content_sha256="1" * 64,
            physical_location_id=UUID("00000000-0000-4000-8000-000000000a05"),
            location_sha256="2" * 64,
            provider_system="s3",
            provider_locator="s3://source-bucket/bound/source.parquet",
            object_version_id="null",
            content_checksum="1" * 64,
        )


def test_s3_builder_disables_sdk_retries_and_bounds_timeouts(monkeypatch) -> None:
    import boto3

    captured = {}
    client = _MemoryS3()

    def build_client(service_name, **kwargs):
        captured.update(kwargs)
        assert service_name == "s3"
        return client

    monkeypatch.setattr(boto3, "client", build_client)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://minio.internal:9000")

    store = build_s3_duckdb_blueprint_object_store(
        bucket=OUTPUT_BUCKET,
        prefix=OUTPUT_PREFIX,
        input_prefixes=("s3://source-bucket/bound",),
        connect_timeout_seconds=3,
        read_timeout_seconds=45,
    )

    assert isinstance(store, S3DuckDBBlueprintObjectStore)
    assert captured["config"].connect_timeout == 3
    assert captured["config"].read_timeout == 45
    assert captured["config"].retries == {
        "max_attempts": 0,
        "mode": "standard",
    }
    assert captured["config"].s3 == {"addressing_style": "path"}
def test_object_store_conditionally_publishes_and_never_overwrites(
    tmp_path: Path,
) -> None:
    client = _MemoryS3()
    store = _store(client)
    payload = _parquet_bytes()
    source = tmp_path / "result.parquet"
    source.write_bytes(payload)
    sha256 = hashlib.sha256(payload).hexdigest()
    uri = blueprint_s3_output_uri(OUTPUT_BUCKET, OUTPUT_PREFIX, TENANT, RUN_ID)

    first = store.publish_output(
        TENANT,
        RUN_ID,
        uri,
        source=source,
        expected_sha256=sha256,
    )
    replay = store.publish_output(
        TENANT,
        RUN_ID,
        uri,
        source=source,
        expected_sha256=sha256,
    )

    assert first == replay
    assert first.version_id == "output-v1"
    assert len(client.put_calls) == 2
    assert client.put_calls[0]["IfNoneMatch"] == "*"
    key = f"{OUTPUT_PREFIX}/{TENANT}/{RUN_ID}.parquet"
    assert client.objects[(OUTPUT_BUCKET, key)] == payload

    source.write_bytes(b"different")
    with pytest.raises(DuckDBBlueprintObjectStoreConflict, match="different"):
        store.publish_output(
            TENANT,
            RUN_ID,
            uri,
            source=source,
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
        )
    assert client.objects[(OUTPUT_BUCKET, key)] == payload


@pytest.mark.parametrize("missing", ["versioning", "lock", "retention"])
def test_object_store_probe_requires_versioning_and_retention(missing: str) -> None:
    client = _MemoryS3()
    if missing == "versioning":
        client.versioning_status = "Suspended"
    elif missing == "lock":
        client.object_lock_enabled = "Disabled"
    else:
        client.default_retention = {}

    with pytest.raises(DuckDBBlueprintObjectStoreUnavailable, match="versioning"):
        _store(client).probe()


def test_provider_stages_s3_input_and_publishes_version_bound_output(
    tmp_path: Path,
) -> None:
    client = _MemoryS3()
    payload = _parquet_bytes()
    input_sha256 = hashlib.sha256(payload).hexdigest()
    client.seed("source-bucket", "bound/source.parquet", payload, version_id="input-v7")
    store = _store(client)
    output_uri = blueprint_s3_output_uri(
        OUTPUT_BUCKET,
        OUTPUT_PREFIX,
        TENANT,
        RUN_ID,
    )
    spec = DuckDBBlueprintExecutionSpec(
        tenant_id=TENANT,
        run_id=RUN_ID,
        execution_plan_artifact_id=UUID(
            "00000000-0000-4000-8000-000000000a02"
        ),
        execution_plan_sha256="1" * 64,
        definition_version_id=UUID("00000000-0000-4000-8000-000000000a03"),
        definition_sha256="2" * 64,
        pipeline=DuckDBBlueprintPipeline(
            engine="duckdb",
            sql=(
                "SELECT district, sum(area) AS area FROM source "
                "GROUP BY district ORDER BY district"
            ),
        ),
        inputs=(
            DuckDBBlueprintInput(
                binding_name="source",
                resource_version_id=UUID(
                    "00000000-0000-4000-8000-000000000a04"
                ),
                resource_urn="gda://planning/dataset/district-source",
                content_sha256=input_sha256,
                physical_location_id=UUID(
                    "00000000-0000-4000-8000-000000000a05"
                ),
                location_sha256="3" * 64,
                provider_system="s3",
                provider_locator="s3://source-bucket/bound/source.parquet",
                object_version_id="input-v7",
                content_checksum=input_sha256,
            ),
        ),
        output_uri=output_uri,
        admitted_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    provider = DuckDBBlueprintProvider(object_store=store, workspace_root=tmp_path)

    receipt = provider.execute(spec)
    verify_duckdb_blueprint_output(receipt, object_store=store)

    assert receipt.output_uri == output_uri
    assert receipt.output_storage_evidence is not None
    assert receipt.output_storage_evidence.version_id == "output-v1"
    key = f"{OUTPUT_PREFIX}/{TENANT}/{RUN_ID}.parquet"
    assert pq.read_table(io.BytesIO(client.objects[(OUTPUT_BUCKET, key)])).to_pylist() == [
        {"district": "a", "area": 15.0},
        {"district": "b", "area": 7.0},
    ]
    assert list(tmp_path.iterdir()) == []


def test_provider_classifies_temporary_object_store_failure_as_retryable(
    tmp_path: Path,
) -> None:
    client = _MemoryS3()
    payload = _parquet_bytes()
    input_sha256 = hashlib.sha256(payload).hexdigest()
    client.seed("source-bucket", "bound/source.parquet", payload, version_id="input-v7")
    client.fail_operation = "get"
    store = _store(client)
    spec = DuckDBBlueprintExecutionSpec(
        tenant_id=TENANT,
        run_id=RUN_ID,
        execution_plan_artifact_id=UUID(
            "00000000-0000-4000-8000-000000000a02"
        ),
        execution_plan_sha256="1" * 64,
        definition_version_id=UUID("00000000-0000-4000-8000-000000000a03"),
        definition_sha256="2" * 64,
        pipeline=DuckDBBlueprintPipeline(
            engine="duckdb",
            sql="SELECT * FROM source ORDER BY district, area",
        ),
        inputs=(
            DuckDBBlueprintInput(
                binding_name="source",
                resource_version_id=UUID(
                    "00000000-0000-4000-8000-000000000a04"
                ),
                resource_urn="gda://planning/dataset/district-source",
                content_sha256=input_sha256,
                physical_location_id=UUID(
                    "00000000-0000-4000-8000-000000000a05"
                ),
                location_sha256="3" * 64,
                provider_system="s3",
                provider_locator="s3://source-bucket/bound/source.parquet",
                object_version_id="input-v7",
                content_checksum=input_sha256,
            ),
        ),
        output_uri=blueprint_s3_output_uri(
            OUTPUT_BUCKET,
            OUTPUT_PREFIX,
            TENANT,
            RUN_ID,
        ),
        admitted_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises(DuckDBBlueprintProviderUnavailableError):
        DuckDBBlueprintProvider(
            object_store=store,
            workspace_root=tmp_path,
        ).execute(spec)
    assert list(tmp_path.iterdir()) == []
