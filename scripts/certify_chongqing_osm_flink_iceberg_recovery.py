#!/usr/bin/env python3
"""Certify checkpoint recovery into a real MinIO Iceberg table."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3

from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    BUCKET,
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_NETWORK,
    DEFAULT_SOURCE,
    DEFAULT_SOURCE_PRODUCT_SHA256,
    DEFAULT_SPARK_IMAGE,
    FLINK_AWS,
    FLINK_ICEBERG,
    HADOOP_CLIENT_API,
    HADOOP_CLIENT_RUNTIME,
    POSTGRES_JDBC,
    FlinkIcebergSandbox,
    IcebergCatalogSandbox,
    _cleanup_prefix,
    _object_inventory,
    _spark_artifacts,
    _spark_phase,
    verify_artifact,
)
from scripts.certify_chongqing_osm_flink_stream import (
    REPO_ROOT,
    _canonical_sha256,
    _sha256_file,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_postgres_cdc import build_cdc_plan
from scripts.certify_source_sync_authority import _settings

JAVA_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergRecoveryJob.java"
MAIN_CLASS = "ChongqingOsmIcebergRecoveryJob"
DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/"
    "chongqing-osm-flink-iceberg-recovery-report.json"
)


def build_recovery_plan(source_path: Path, *, commit_tag: str) -> dict[str, Any]:
    cdc = build_cdc_plan(source_path)
    baseline = [dict(row) for row in cdc["initial"]]
    baseline.sort(key=lambda row: row["road_id"])
    source_rows = [*baseline, dict(cdc["d_row"])]
    stream_rows = [
        {
            **row,
            "stream_event_id": f"iceberg_event_{index:02d}",
            "flink_commit_tag": commit_tag,
        }
        for index, row in enumerate(source_rows, start=1)
    ]
    final_rows = [
        {**row, "stream_event_id": None, "flink_commit_tag": None}
        for row in baseline
    ] + stream_rows
    final_rows.sort(
        key=lambda row: (row["road_id"], row["stream_event_id"] or "")
    )
    return {
        "schema": "gda.chongqing_osm_flink_iceberg_recovery_plan.v1",
        "source": cdc["source"],
        "source_slice_sha256": cdc["source_slice_sha256"],
        "baseline_rows": baseline,
        "stream_rows": stream_rows,
        "stream_event_ids": [row["stream_event_id"] for row in stream_rows],
        "final_rows": final_rows,
        "baseline_content_sha256": _canonical_sha256(baseline),
        "final_content_sha256": _canonical_sha256(final_rows),
        "commit_tag": commit_tag,
    }


def render_recovery_input(plan: dict[str, Any]) -> str:
    return "".join(
        "\t".join(
            (
                str(row["road_id"]),
                str(row["revision"]),
                row["road_name_base64"],
                row["geometry_sha256"],
                row["stream_event_id"],
                row["flink_commit_tag"],
            )
        )
        + "\n"
        for row in plan["stream_rows"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--spark-image", default=DEFAULT_SPARK_IMAGE)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--container-endpoint-url", default="http://minio:9000")
    parser.add_argument("--host-endpoint-url", default="http://127.0.0.1:9000")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    settings = _settings()
    access_key = settings.get("MINIO_ROOT_USER", "minio_admin")
    secret_key = settings.get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret")
    token = secrets.token_hex(5)
    run_id = str(uuid4())
    prefix = f"acceptance/flink-iceberg/gda_flink_iceberg_{token}/"
    warehouse_uri = f"s3://{BUCKET}/{prefix}warehouse"
    table = f"lakehouse.gda_interop_{token}.chongqing_osm_roads"
    work_dir = (
        REPO_ROOT
        / ".tmp/source-sync-certification"
        / f"flink_iceberg_recovery_{token}"
    )
    plan_path = work_dir / "plan.json"
    input_path = work_dir / "events.tsv"
    checkpoint_path = work_dir / "checkpoints"
    baseline_path = work_dir / "spark-baseline.json"
    verify_path = work_dir / "spark-recovery-verify.json"
    client = boto3.client(
        "s3",
        endpoint_url=args.host_endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    report: dict[str, Any] | None = None
    error: str | None = None
    cleanup: dict[str, Any] = {}
    flink: FlinkIcebergSandbox | None = None
    catalog: IcebergCatalogSandbox | None = None
    work_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_path.mkdir()
    try:
        flink_artifacts = {
            "runtime": verify_artifact(FLINK_ICEBERG),
            "aws_bundle": verify_artifact(FLINK_AWS),
            "postgresql_jdbc": verify_artifact(POSTGRES_JDBC),
            "hadoop_client_api": verify_artifact(HADOOP_CLIENT_API),
            "hadoop_client_runtime": verify_artifact(HADOOP_CLIENT_RUNTIME),
        }
        spark_artifacts = _spark_artifacts(
            args.spark_image, timeout=args.timeout_seconds
        )
        plan = build_recovery_plan(args.source, commit_tag=run_id)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        input_path.write_text(render_recovery_input(plan), encoding="utf-8")
        catalog = IcebergCatalogSandbox(
            image=args.postgres_image,
            network=args.docker_network,
            token=token,
        )
        catalog_evidence = catalog.start()
        baseline = _spark_phase(
            args,
            phase="baseline",
            plan_path=plan_path,
            report_path=baseline_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
        )
        jar_path = compile_flink_job(
            work_dir=work_dir,
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=JAVA_SOURCE,
            main_class=MAIN_CLASS,
        )
        flink = FlinkIcebergSandbox(
            args=args,
            token=token,
            access_key=access_key,
            secret_key=secret_key,
            catalog_password=catalog.password,
        )
        cluster = flink.start()
        recovery = flink.run_recovery(
            jar_path=jar_path,
            warehouse_uri=warehouse_uri,
            table=table,
            input_path=input_path,
            checkpoint_path=checkpoint_path,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
        )
        if recovery["status"] != "passed":
            raise RuntimeError(f"Flink Iceberg recovery markers failed: {recovery}")
        verify = _spark_phase(
            args,
            phase="recovery-verify",
            plan_path=plan_path,
            report_path=verify_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
        )
        inventory = _object_inventory(client, prefix)
        checks = {
            "real_chongqing_osm_source_bound": (
                plan["source"]["source_feature_count"] == 50_366
                and plan["source"]["source_product_sha256"]
                == DEFAULT_SOURCE_PRODUCT_SHA256
            ),
            "supply_chain_artifacts_verified": True,
            "spark_baseline_passed": all(baseline["checks"].values()),
            "flink_checkpoint_failure_restore_passed": all(
                recovery["checks"].values()
            ),
            "spark_exactly_once_readback_and_time_travel_passed": all(
                verify["checks"].values()
            ),
            "checkpointed_iceberg_object_graph_materialized": (
                inventory["metadata_json_count"] >= 4
                and inventory["manifest_avro_count"] >= 6
                and inventory["data_parquet_count"] >= 3
            ),
        }
        report = {
            "schema": "gda.chongqing_osm_flink_iceberg_recovery.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "source_slice_sha256": plan["source_slice_sha256"],
                "baseline_content_sha256": plan["baseline_content_sha256"],
                "final_content_sha256": plan["final_content_sha256"],
                "stream_event_ids": plan["stream_event_ids"],
            },
            "runtime": {
                "spark_image": args.spark_image,
                "spark_image_id": docker_image_id(
                    args.spark_image, timeout=args.timeout_seconds
                ),
                "flink_image": args.flink_image,
                "flink_image_id": docker_image_id(
                    args.flink_image, timeout=args.timeout_seconds
                ),
                "spark_artifacts": spark_artifacts,
                "flink_artifacts": flink_artifacts,
                "flink_job_source_sha256": _sha256_file(JAVA_SOURCE),
                "flink_job_jar_sha256": _sha256_file(jar_path),
                "flink_cluster": cluster,
                "catalog": {
                    **catalog_evidence,
                    "provider": "org.apache.iceberg.jdbc.JdbcCatalog",
                    "image": args.postgres_image,
                    "image_id": docker_image_id(
                        args.postgres_image, timeout=args.timeout_seconds
                    ),
                },
            },
            "recovery": recovery,
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "warehouse_scope": "isolated-minio-prefix",
                "spark_baseline": baseline,
                "spark_verify": verify,
                "object_inventory": inventory,
            },
            "correlation": {"run_id": run_id},
            "not_claimed": [
                "cancel or uncertain commit reconciliation",
                "cross-engine concurrent write isolation",
                "cross-system exactly-once transaction",
                "REST or Gravitino catalog interoperability",
                "production throughput, freshness, HA, or Kubernetes runtime",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"Flink Iceberg recovery checks failed: {checks}")
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}"
        catalog_password = catalog.password if catalog is not None else ""
        for value in (access_key, secret_key, catalog_password):
            if value:
                safe = safe.replace(value, "<redacted>")
        error = safe
    finally:
        cleanup["flink_container_removed"] = (
            flink.cleanup() if flink is not None else True
        )
        cleanup["catalog_container_removed"] = (
            catalog.cleanup() if catalog is not None else True
        )
        cleanup.update(_cleanup_prefix(client, prefix))
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_flink_iceberg_recovery.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    cleanup_passed = (
        cleanup.get("flink_container_removed") is True
        and cleanup.get("catalog_container_removed") is True
        and cleanup.get("object_prefix_empty") is True
        and cleanup.get("work_directory_removed") is True
        and isinstance(cleanup.get("objects_removed"), int)
    )
    if not cleanup_passed:
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
                "error": report.get("error"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
