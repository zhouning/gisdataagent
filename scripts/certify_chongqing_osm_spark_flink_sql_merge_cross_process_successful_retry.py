#!/usr/bin/env python3
"""Certify successful SQL MERGE retries across two independent Spark workers."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from scripts import certify_chongqing_osm_spark_flink_sql_merge_auto_retry as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import REPO_ROOT
from scripts.certify_chongqing_osm_spark_flink_sql_merge_multiple_successful_retries import (
    build_sql_merge_multiple_successful_retries_plan,
)

DEFAULT_REPORT = (
    REPO_ROOT
    / (
        "docs/reports/"
        "chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry_2026-08-24.json"
    )
)
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_cross_process_successful_retry"
SPARK_SOURCE = (
    REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_cross_process_successful_retry.py"
)


def _worker_report(
    process: subprocess.Popen[str], report_path: Path, phase: str, timeout: int
) -> dict[str, Any]:
    stdout, stderr = process.communicate(timeout=timeout)
    if not report_path.exists():
        raise RuntimeError(
            f"{phase} worker did not write evidence: returncode={process.returncode}, "
            f"stdout={stdout[-1500:]}, stderr={stderr[-1500:]}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if process.returncode != 0 or report.get("status") != "passed":
        raise RuntimeError(
            f"{phase} worker failed: returncode={process.returncode}, "
            f"checks={report.get('checks')}, stdout={stdout[-1500:]}, stderr={stderr[-1500:]}"
        )
    return report


def _release_payload(plan: dict[str, Any], flink_snapshot_id: str) -> dict[str, Any]:
    return {
        "schema": "gda.spark_sql_merge_auto_retry_release.v1",
        "flink_snapshot_id": flink_snapshot_id,
        "flink_commit_token": plan["flink_commit_token"],
        "source_row_count": len(plan["merge_source_stale_rows"]),
        "source_row_ids": plan["stale_source_row_ids"],
        "expected_revision": plan["merge_source_stale_rows"][0]["expected_revision"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=base.DEFAULT_SOURCE)
    parser.add_argument("--spark-image", default=base.DEFAULT_SPARK_IMAGE)
    parser.add_argument("--flink-image", default=base.DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=base.DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=base.DEFAULT_JAVA_HOME)
    parser.add_argument("--docker-network", default=base.DEFAULT_NETWORK)
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--container-endpoint-url", default="http://minio:9000")
    parser.add_argument("--host-endpoint-url", default="http://127.0.0.1:9000")
    parser.add_argument("--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    base.SPARK_MODULE = SPARK_MODULE
    base.SPARK_SOURCE = SPARK_SOURCE
    access_key, secret_key = (
        base._settings().get("MINIO_ROOT_USER", "minio_admin"),
        base._settings().get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret"),
    )
    settings = base._settings()
    token = secrets.token_hex(5)
    prefix = f"acceptance/flink-iceberg/gda_flink_iceberg_{token}/"
    warehouse_uri = f"s3://{base.BUCKET}/{prefix}warehouse"
    namespace = f"gda_interop_{token}"
    table_name = "chongqing_osm_roads"
    table = f"lakehouse.{namespace}.{table_name}"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / f"cross_process_retry_{token}"
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    first_path = work_dir / "spark-cross-process-first.json"
    second_path = work_dir / "spark-cross-process-second.json"
    verify_path = work_dir / "spark-verify.json"
    release_marker = work_dir / "spark-release.json"
    first_container = f"gda-iceberg-spark-cross-process-first-{token}"
    second_container = f"gda-iceberg-spark-cross-process-second-{token}"
    client = boto3.client(
        "s3",
        endpoint_url=args.host_endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    admin_url = base._connection_url(
        args.postgres_url,
        {
            "type": "basic",
            "username": settings.get("POSTGRES_USER", "postgres"),
            "password": settings.get(
                "POSTGRES_ADMIN_PASSWORD", settings.get("POSTGRES_PASSWORD", "postgres")
            ),
        },
    )
    main_counts_before = base._main_sync_counts(admin_url)
    catalog: base.IcebergCatalogSandbox | None = None
    flink: base.FlinkIcebergSandbox | None = None
    workers: list[subprocess.Popen[str]] = []
    report: dict[str, Any] | None = None
    cleanup: dict[str, Any] = {}
    error: str | None = None
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        flink_artifacts = {
            "runtime": base.verify_artifact(base.FLINK_ICEBERG),
            "aws_bundle": base.verify_artifact(base.FLINK_AWS),
            "postgresql_jdbc": base.verify_artifact(base.POSTGRES_JDBC),
            "hadoop_client_api": base.verify_artifact(base.HADOOP_CLIENT_API),
            "hadoop_client_runtime": base.verify_artifact(base.HADOOP_CLIENT_RUNTIME),
        }
        spark_artifacts = base._spark_artifacts(args.spark_image, timeout=args.timeout_seconds)
        plan = build_sql_merge_multiple_successful_retries_plan(args.source)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        catalog = base.IcebergCatalogSandbox(
            image=args.postgres_image, network=args.docker_network, token=token
        )
        catalog_evidence = catalog.start()
        baseline = base._spark_phase(
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
        jar_path = base.compile_flink_job(
            work_dir=work_dir / "build",
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=base.FLINK_SOURCE,
            main_class=base.FLINK_MAIN_CLASS,
        )
        flink = base.FlinkIcebergSandbox(
            args=args,
            token=token,
            access_key=access_key,
            secret_key=secret_key,
            catalog_password=catalog.password,
            extra_flink_properties=("classloader.check-leaked-classloader: true",),
        )
        cluster = flink.start()
        flink_config = base._flink_jobmanager_config(flink, timeout=args.timeout_seconds)
        first_command = base._spark_command(
            args,
            phase="cross-process-first",
            plan_path=plan_path,
            report_path=first_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
            release_marker=release_marker,
            container_name=first_container,
        )
        first_worker = subprocess.Popen(
            first_command, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        workers.append(first_worker)
        flink_result = base._run_flink_partition_append(
            flink,
            jar_path=jar_path,
            plan=plan,
            warehouse_uri=warehouse_uri,
            table=table,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            timeout=args.timeout_seconds,
        )
        after_flink_location = base._catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        after_flink_metadata = base._metadata_evidence(client, after_flink_location)
        flink_snapshot_id = after_flink_metadata["current_snapshot"]["snapshot_id"]
        release_marker.write_text(
            json.dumps(_release_payload(plan, flink_snapshot_id), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        first_report = _worker_report(
            first_worker, first_path, "cross-process-first", args.timeout_seconds
        )
        second_command = base._spark_command(
            args,
            phase="cross-process-second",
            plan_path=plan_path,
            report_path=second_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
            container_name=second_container,
        )
        second_worker = subprocess.Popen(
            second_command, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        workers.append(second_worker)
        second_report = _worker_report(
            second_worker, second_path, "cross-process-second", args.timeout_seconds
        )
        auto_retry = {
            "phase": "cross-process-successful-retry",
            "status": "passed",
            "checks": {
                "first_worker_passed": all(first_report["checks"].values()),
                "second_worker_passed": all(second_report["checks"].values()),
                "workers_are_distinct": first_container != second_container,
                "shared_snapshot_chain": second_report["snapshots"][-1]["parent_id"]
                == second_report["snapshots"][-2]["snapshot_id"],
            },
            "snapshots": second_report["snapshots"],
            "first_worker": first_report,
            "second_worker": second_report,
        }
        final_location = base._catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        final_metadata = base._metadata_evidence(client, final_location)
        verify = base._spark_phase(
            args,
            phase="verify",
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
            flink_snapshot_id=flink_snapshot_id,
        )
        inventory = base._object_inventory(client, prefix)
        checks = {
            "real_chongqing_osm_source_bound": plan["source"]["source_feature_count"] == 50_366
            and plan["source"]["source_product_sha256"] == base.DEFAULT_SOURCE_PRODUCT_SHA256,
            "supply_chain_artifacts_verified": True,
            "flink_classloader_safety_check_enabled": flink_config.get(
                "classloader.check-leaked-classloader"
            )
            == "true",
            "release_marker_bound_to_flink_child": json.loads(release_marker.read_text())[
                "flink_snapshot_id"
            ]
            == flink_snapshot_id,
            "flink_same_key_append_passed": all(flink_result["checks"].values()),
            "catalog_advanced_to_flink_child": after_flink_metadata["snapshot_count"] == 2
            and after_flink_metadata["current_snapshot"]["parent_id"]
            == baseline["baseline_snapshot_id"],
            "cross_process_retry_passed": all(auto_retry["checks"].values()),
            "independent_multi_source_sql_merge_verify_passed": all(verify["checks"].values()),
            "final_snapshot_parent_is_second_worker": final_metadata["current_snapshot"][
                "parent_id"
            ]
            == auto_retry["snapshots"][-2]["snapshot_id"],
            "sql_merge_cross_process_object_graph_materialized": inventory[
                "metadata_json_count"
            ]
            >= 4
            and inventory["manifest_avro_count"] >= 4
            and inventory["data_parquet_count"] >= 5,
        }
        report = {
            "schema": (
                "gda.chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry.acceptance.v1"
            ),
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "target_road_id": plan["target_road_id"],
                "stale_source_row_ids": plan["stale_source_row_ids"],
                "fresh_source_row_id": plan["merge_source_fresh"]["source_row_id"],
                "second_retry_source_row_id": plan["successful_retry_sequence"][0]["source_row_id"],
            },
            "runtime": {
                "spark_image": args.spark_image,
                "spark_image_id": base.docker_image_id(
                    args.spark_image, timeout=args.timeout_seconds
                ),
                "flink_image": args.flink_image,
                "flink_image_id": base.docker_image_id(
                    args.flink_image, timeout=args.timeout_seconds
                ),
                "spark_artifacts": spark_artifacts,
                "spark_job_source_sha256": base._sha256_file(base.SPARK_SOURCE),
                "flink_artifacts": flink_artifacts,
                "flink_job_source_sha256": base._sha256_file(base.FLINK_SOURCE),
                "flink_job_jar_sha256": base._sha256_file(jar_path),
                "flink_cluster": cluster,
                "catalog": {
                    **catalog_evidence,
                    "provider": "org.apache.iceberg.jdbc.JdbcCatalog",
                    "image": args.postgres_image,
                    "image_id": base.docker_image_id(
                        args.postgres_image, timeout=args.timeout_seconds
                    ),
                },
            },
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "partition_spec": "identity(road_id)",
                "format_version": 2,
                "baseline": baseline,
                "after_flink_catalog": after_flink_metadata,
                "automatic_retry": auto_retry,
                "verify": verify,
                "final_catalog": final_metadata,
                "object_inventory": inventory,
            },
            "control_plane": {
                "source_sync_advanced": False,
                "data_product_version_created": False,
                "retry_mode": "cross_process_successful_fresh_retry",
            },
            "not_claimed": [
                "provider abort recovery, cross-system exactly-once or production HA/RPO/RTO",
                "SQL UPDATE joins/subqueries, MERGE deletes/inserts or multi-file writes",
                "REST or Gravitino destructive-write conformance and production SLO",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"cross-process SQL MERGE checks failed: {checks}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=15)
        cleanup["first_spark_container_removed"] = base._remove_container(first_container)
        cleanup["second_spark_container_removed"] = base._remove_container(second_container)
        cleanup["flink_container_removed"] = flink.cleanup() if flink is not None else True
        cleanup["catalog_container_removed"] = catalog.cleanup() if catalog is not None else True
        cleanup.update(base._cleanup_prefix_safe(client, prefix))
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
        main_counts_after = base._main_sync_counts(admin_url)
        cleanup["main_source_sync_unchanged"] = main_counts_after == main_counts_before
        cleanup["main_source_sync_counts"] = list(main_counts_after)
    if report is None:
        report = {
            "schema": (
                "gda.chongqing_osm_spark_flink_sql_merge_cross_process_successful_retry.acceptance.v1"
            ),
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not all(
        cleanup.get(name) is True
        for name in (
            "first_spark_container_removed",
            "second_spark_container_removed",
            "flink_container_removed",
            "catalog_container_removed",
            "object_prefix_empty",
            "work_directory_removed",
            "main_source_sync_unchanged",
        )
    ):
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
