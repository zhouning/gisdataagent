#!/usr/bin/env python3
"""Certify DuckDB Blueprint immutable I/O against disposable MinIO."""

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

import pyarrow as pa
import pyarrow.parquet as pq
from certify_metric_query_s3_result_store import _DisposableMinio

from data_agent.duckdb_blueprint_object_store import (
    S3DuckDBBlueprintObjectStore,
    blueprint_s3_output_uri,
)
from data_agent.duckdb_blueprint_provider import (
    DuckDBBlueprintExecutionSpec,
    DuckDBBlueprintInput,
    DuckDBBlueprintPipeline,
    DuckDBBlueprintProvider,
    DuckDBBlueprintProviderContractError,
    verify_duckdb_blueprint_output,
)
from data_agent.platform_contracts import canonical_json_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/duckdb-blueprint-object-store/report.json"
TENANT = "blueprint-object-certification"
OUTPUT_PREFIX = "blueprint-duckdb-results/v1"
INPUT_PREFIX = "blueprint-inputs/v1"


def _parquet_bytes(*, altered: bool = False) -> bytes:
    output = io.BytesIO()
    pq.write_table(
        pa.table(
            {
                "district": ["changed"] if altered else ["a", "a", "b"],
                "area": [99.0] if altered else [10.5, 4.5, 7.0],
            }
        ),
        output,
    )
    return output.getvalue()


def _spec(
    *,
    bucket: str,
    run_id: UUID,
    input_version_id: str,
    input_sha256: str,
    sql: str | None = None,
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
            sql=sql
            or (
                "SELECT district, sum(area) AS area FROM source "
                "GROUP BY district ORDER BY district"
            ),
        ),
        inputs=(
            DuckDBBlueprintInput(
                binding_name="source",
                resource_version_id=uuid5(run_id, "input-version"),
                resource_urn=f"gda://{TENANT}/dataset/source",
                content_sha256=input_sha256,
                physical_location_id=uuid5(run_id, "input-location"),
                location_sha256="3" * 64,
                provider_system="s3",
                provider_locator=f"s3://{bucket}/{INPUT_PREFIX}/source.parquet",
                object_version_id=input_version_id,
                content_checksum=input_sha256,
            ),
        ),
        output_uri=blueprint_s3_output_uri(
            bucket,
            OUTPUT_PREFIX,
            TENANT,
            run_id,
        ),
        admitted_at=datetime.now(UTC),
    )


def certify() -> dict[str, Any]:
    sandbox = _DisposableMinio()
    checks: dict[str, bool] = {}
    cleanup: dict[str, bool] = {}
    output_uri = ""
    output_version_id = ""
    try:
        sandbox.start()
        assert sandbox.admin is not None
        input_payload = _parquet_bytes()
        input_sha256 = hashlib.sha256(input_payload).hexdigest()
        input_key = f"{INPUT_PREFIX}/source.parquet"
        admitted = sandbox.admin.put_object(
            Bucket=sandbox.bucket,
            Key=input_key,
            Body=input_payload,
            ContentType="application/vnd.apache.parquet",
            Metadata={"sha256": input_sha256},
        )
        input_version_id = str(admitted.get("VersionId") or "")
        checks["input_version_captured"] = bool(
            input_version_id and input_version_id != "null"
        )

        run_id = uuid5(
            UUID("93db5d7e-dfd7-5bb8-ac93-a77363da8e2c"),
            sandbox.container,
        )
        spec = _spec(
            bucket=sandbox.bucket,
            run_id=run_id,
            input_version_id=input_version_id,
            input_sha256=input_sha256,
        )

        # Change the current object after admission. Exact-VersionId GET must
        # continue to execute the originally admitted bytes.
        sandbox.admin.put_object(
            Bucket=sandbox.bucket,
            Key=input_key,
            Body=_parquet_bytes(altered=True),
            ContentType="application/vnd.apache.parquet",
        )
        store = S3DuckDBBlueprintObjectStore(
            sandbox.admin,
            bucket=sandbox.bucket,
            prefix=OUTPUT_PREFIX,
            input_prefixes=(f"s3://{sandbox.bucket}/{INPUT_PREFIX}",),
        )
        store.probe()
        checks["versioning_object_lock_probe"] = True

        with tempfile.TemporaryDirectory(prefix="gda-blueprint-minio-") as temp:
            workspace = Path(temp)
            provider = DuckDBBlueprintProvider(
                object_store=store,
                workspace_root=workspace,
            )
            receipt = provider.execute(spec)
            verify_duckdb_blueprint_output(receipt, object_store=store)
            checks["admitted_input_version_used"] = receipt.input_rows == 3
            checks["exact_output_version_verified"] = (
                receipt.output_storage_evidence is not None
                and receipt.output_storage_evidence.version_id != "null"
            )
            output_uri = receipt.output_uri
            output_version_id = (
                receipt.output_storage_evidence.version_id
                if receipt.output_storage_evidence is not None
                else ""
            )

            replay = provider.execute(spec)
            checks["same_byte_replay_reuses_version"] = (
                replay.output_storage_evidence == receipt.output_storage_evidence
                and replay.output_content_sha256 == receipt.output_content_sha256
            )
            try:
                provider.execute(
                    _spec(
                        bucket=sandbox.bucket,
                        run_id=run_id,
                        input_version_id=input_version_id,
                        input_sha256=input_sha256,
                        sql=(
                            "SELECT district, area FROM source "
                            "ORDER BY district, area"
                        ),
                    )
                )
            except DuckDBBlueprintProviderContractError:
                checks["different_byte_replay_rejected"] = True
            else:
                checks["different_byte_replay_rejected"] = False
            output_bucket, output_key = receipt.output_uri.removeprefix("s3://").split(
                "/", 1
            )
            sandbox.admin.put_object(
                Bucket=output_bucket,
                Key=output_key,
                Body=b"new-current-version",
                ContentType="application/octet-stream",
            )
            verify_duckdb_blueprint_output(receipt, object_store=store)
            checks["exact_output_version_survives_current_overwrite"] = True
            checks["workspace_cleaned"] = list(workspace.iterdir()) == []

        checks["credential_free_output_uri"] = output_uri.startswith(
            f"s3://{sandbox.bucket}/{OUTPUT_PREFIX}/{TENANT}/"
        )
        checks["output_version_captured"] = bool(output_version_id)
    finally:
        cleanup = sandbox.cleanup()
        checks["bucket_removed"] = cleanup.get("bucket_removed", False)
        checks["container_removed"] = cleanup.get("container_removed", False)

    passed = sum(checks.values())
    report: dict[str, Any] = {
        "schema": "gda.duckdb_blueprint_object_store_certification.v1",
        "status": "passed" if passed == len(checks) else "failed",
        "scope": "disposable_minio",
        "checks": checks,
        "passed_checks": passed,
        "total_checks": len(checks),
        "output_uri": output_uri,
        "output_version_id": output_version_id,
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
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
