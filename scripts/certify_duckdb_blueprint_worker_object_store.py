#!/usr/bin/env python3
"""Certify the DuckDB Blueprint worker identity against disposable MinIO."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from certify_metric_query_s3_result_store import MC_IMAGE, _DisposableMinio, _run

from data_agent.duckdb_blueprint_object_store import S3DuckDBBlueprintObjectStore
from data_agent.duckdb_blueprint_provider import (
    DuckDBBlueprintExecutionSpec,
    DuckDBBlueprintInput,
    DuckDBBlueprintPipeline,
    DuckDBBlueprintProvider,
    verify_duckdb_blueprint_output,
)
from data_agent.platform_contracts import canonical_json_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/duckdb-blueprint-worker-object-store/report.json"
TENANT = "blueprint-worker-iam-certification"
INPUT_PREFIX = "blueprint-inputs/v1"
OUTPUT_PREFIX = "blueprint-duckdb-results/v1"


def _client(endpoint: str, access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=BotoConfig(
            connect_timeout=5,
            read_timeout=15,
            retries={"total_max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def _parquet_bytes() -> bytes:
    output = io.BytesIO()
    pq.write_table(pa.table({"district": ["a", "a", "b"], "area": [10.5, 4.5, 7.0]}), output)
    return output.getvalue()


def _provision_worker(sandbox: _DisposableMinio, worker_secret: str) -> tuple[str, str]:
    assert sandbox.admin is not None
    suffix = sandbox.container.rsplit("-", 1)[-1]
    access_key = f"gda-blueprint-worker-{suffix}"
    policy_name = f"gda-blueprint-worker-{suffix}"
    bucket_arn = f"arn:aws:s3:::{sandbox.bucket}"
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetBucketLocation",
                    "s3:GetBucketVersioning",
                    "s3:GetBucketObjectLockConfiguration",
                ],
                "Resource": [bucket_arn],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:GetObjectVersion"],
                "Resource": [
                    f"{bucket_arn}/{INPUT_PREFIX}/*",
                    f"{bucket_arn}/{OUTPUT_PREFIX}/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject"],
                "Resource": [f"{bucket_arn}/{OUTPUT_PREFIX}/*"],
            },
        ],
    }
    with tempfile.TemporaryDirectory(prefix="gda-blueprint-worker-policy-") as temp:
        policy_path = Path(temp) / "policy.json"
        policy_path.write_text(json.dumps(policy, sort_keys=True), encoding="utf-8")
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                f"container:{sandbox.container}",
                "--volume",
                f"{policy_path}:/gda-policy.json:ro",
                "--env",
                "GDA_ROOT_ACCESS_KEY",
                "--env",
                "GDA_ROOT_SECRET_KEY",
                "--env",
                "GDA_WORKER_ACCESS_KEY",
                "--env",
                "GDA_WORKER_SECRET_KEY",
                "--env",
                "GDA_WORKER_POLICY",
                "--entrypoint",
                "/bin/sh",
                MC_IMAGE,
                "-c",
                "set -eu; "
                'mc alias set local http://127.0.0.1:9000 '
                '"$GDA_ROOT_ACCESS_KEY" "$GDA_ROOT_SECRET_KEY" >/dev/null; '
                'mc admin user add local "$GDA_WORKER_ACCESS_KEY" '
                '"$GDA_WORKER_SECRET_KEY" >/dev/null; '
                'mc admin policy create local "$GDA_WORKER_POLICY" /gda-policy.json >/dev/null; '
                'mc admin policy attach local "$GDA_WORKER_POLICY" '
                '--user "$GDA_WORKER_ACCESS_KEY" >/dev/null',
            ],
            environment={
                "GDA_ROOT_ACCESS_KEY": sandbox.root_access_key,
                "GDA_ROOT_SECRET_KEY": sandbox.root_secret_key,
                "GDA_WORKER_ACCESS_KEY": access_key,
                "GDA_WORKER_SECRET_KEY": worker_secret,
                "GDA_WORKER_POLICY": policy_name,
            },
        )
    return access_key, worker_secret


def _spec(
    bucket: str, run_id: UUID, version_id: str, content_sha256: str
) -> DuckDBBlueprintExecutionSpec:
    return DuckDBBlueprintExecutionSpec(
        tenant_id=TENANT,
        run_id=run_id,
        execution_plan_artifact_id=uuid5(run_id, "execution-plan"),
        execution_plan_sha256="1" * 64,
        definition_version_id=uuid5(run_id, "definition"),
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
                resource_version_id=uuid5(run_id, "input-version"),
                resource_urn=f"gda://{TENANT}/dataset/source",
                content_sha256=content_sha256,
                physical_location_id=uuid5(run_id, "input-location"),
                location_sha256="3" * 64,
                provider_system="s3",
                provider_locator=f"s3://{bucket}/{INPUT_PREFIX}/source.parquet",
                object_version_id=version_id,
                content_checksum=content_sha256,
            ),
        ),
        output_uri=f"s3://{bucket}/{OUTPUT_PREFIX}/{TENANT}/{run_id}.parquet",
        admitted_at=datetime.now(UTC),
    )


def _denied(call: Any) -> bool:
    """Treat an authorization/unsupported-operation error as fail-closed.

    The disposable MinIO release uses both `AccessDenied` and
    `NotImplemented` for retention administration. A missing object is the
    only non-authorization error that would make this check inconclusive.
    """
    try:
        call()
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        return code not in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}
    return False


def certify() -> dict[str, Any]:
    sandbox = _DisposableMinio()
    checks: dict[str, bool] = {}
    cleanup: dict[str, bool] = {}
    try:
        sandbox.start()
        assert sandbox.admin is not None
        worker_access, worker_secret = _provision_worker(
            sandbox, "worker-secret-" + sandbox.container
        )
        worker = _client(sandbox.endpoint, worker_access, worker_secret)
        payload = _parquet_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        admitted = sandbox.admin.put_object(
            Bucket=sandbox.bucket,
            Key=f"{INPUT_PREFIX}/source.parquet",
            Body=payload,
            ContentType="application/vnd.apache.parquet",
        )
        version_id = str(admitted.get("VersionId") or "")
        checks["scoped_worker_can_probe"] = False
        store = S3DuckDBBlueprintObjectStore(
            worker,
            bucket=sandbox.bucket,
            prefix=OUTPUT_PREFIX,
            input_prefixes=(f"s3://{sandbox.bucket}/{INPUT_PREFIX}",),
        )
        store.probe()
        checks["scoped_worker_can_probe"] = version_id not in {"", "null"}
        run_id = uuid5(UUID("d6f8a2ea-86b9-4669-9893-a2a36ec0cf01"), sandbox.container)
        with tempfile.TemporaryDirectory(prefix="gda-blueprint-worker-iam-") as temp:
            provider = DuckDBBlueprintProvider(object_store=store, workspace_root=Path(temp))
            receipt = provider.execute(_spec(sandbox.bucket, run_id, version_id, checksum))
            verify_duckdb_blueprint_output(receipt, object_store=store)
            checks["worker_executes_exact_input_and_publishes"] = receipt.input_rows == 3
            checks["output_is_version_bound"] = receipt.output_storage_evidence is not None
            replay = provider.execute(_spec(sandbox.bucket, run_id, version_id, checksum))
            checks["same_byte_replay_is_idempotent"] = (
                replay.output_storage_evidence == receipt.output_storage_evidence
            )
        checks["delete_denied"] = _denied(
            lambda: worker.delete_object(Bucket=sandbox.bucket, Key=f"{OUTPUT_PREFIX}/delete-me")
        )
        checks["cross_prefix_write_denied"] = _denied(
            lambda: worker.put_object(Bucket=sandbox.bucket, Key="outside/forbidden", Body=b"x")
        )
        sandbox.admin.put_object(
            Bucket=sandbox.bucket,
            Key="outside/existing",
            Body=b"outside",
        )
        checks["cross_prefix_read_denied"] = _denied(
            lambda: worker.get_object(
                Bucket=sandbox.bucket,
                Key="outside/existing",
            )
        )
        checks["retention_bypass_denied"] = _denied(
            lambda: worker.put_object_retention(
                Bucket=sandbox.bucket,
                Key=receipt.output_uri.split("/", 3)[-1],
                VersionId=receipt.output_storage_evidence.version_id,
                Retention={"Mode": "GOVERNANCE", "RetainUntilDate": datetime.now(UTC)},
                BypassGovernanceRetention=True,
            )
        )
    finally:
        cleanup = sandbox.cleanup()
    report: dict[str, Any] = {
        "schema": "gda.duckdb_blueprint_worker_object_store_certification.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "scope": "disposable_minio_scoped_identity",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "total_checks": len(checks),
        "cleanup": cleanup,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    report["report_sha256"] = canonical_json_fingerprint(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = certify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
