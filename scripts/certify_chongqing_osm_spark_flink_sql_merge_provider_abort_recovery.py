#!/usr/bin/env python3
"""Certify bounded Spark SQL MERGE provider-abort recovery by snapshot reconciliation."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

from scripts import certify_chongqing_osm_spark_flink_sql_merge_auto_retry as base
from scripts.certify_chongqing_osm_spark_flink_sql_merge_auto_retry import (
    build_sql_merge_auto_retry_plan,
)

REPORT_SCHEMA = (
    "gda.chongqing_osm_spark_flink_sql_merge_provider_abort_recovery.acceptance.v1"
)
DEFAULT_REPORT = base.REPO_ROOT / (
    "docs/reports/chongqing_osm_spark_flink_sql_merge_provider_abort_recovery_2026-08-24.json"
)
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_merge_abort_recovery"
SPARK_SOURCE = base.REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_merge_abort_recovery.py"


def _wait_for_commit_marker(
    process: subprocess.Popen[str], marker: Path, *, timeout: int
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.is_file():
            return json.loads(marker.read_text(encoding="utf-8"))
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                "abort-after-commit worker exited before commit marker: "
                f"returncode={process.returncode}, stdout={stdout[-2000:]}, stderr={stderr[-2000:]}"
            )
        time.sleep(0.1)
    raise RuntimeError("abort-after-commit worker did not write commit marker")


def _kill_container(name: str, *, timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "kill", "--signal", "KILL", name],
        cwd=base.REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-1000:],
        "stderr": completed.stderr[-1000:],
    }


def _worker_exit_after_kill(
    process: subprocess.Popen[str], *, timeout: int
) -> dict[str, Any]:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=30)
    return {
        "returncode": process.returncode,
        "expected_sigkill_exit": process.returncode in {-9, 137},
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
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
    settings = base._settings()
    access_key = settings.get("MINIO_ROOT_USER", "minio_admin")
    secret_key = settings.get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret")
    token = secrets.token_hex(5)
    prefix = f"acceptance/flink-iceberg/gda_flink_iceberg_{token}/"
    warehouse_uri = f"s3://{base.BUCKET}/{prefix}warehouse"
    namespace = f"gda_interop_{token}"
    table_name = "chongqing_osm_roads"
    table = f"lakehouse.{namespace}.{table_name}"
    work_dir = base.REPO_ROOT / ".tmp/source-sync-certification" / f"provider_abort_{token}"
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    reconcile_path = work_dir / "spark-abort-reconcile.json"
    verify_path = work_dir / "spark-verify.json"
    commit_marker = work_dir / "spark-commit.json"
    release_marker = work_dir / "spark-release.json"
    abort_container = f"gda-iceberg-spark-provider-abort-{token}"
    reconcile_container = f"gda-iceberg-spark-provider-reconcile-{token}"
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
    abort_process: subprocess.Popen[str] | None = None
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
        plan = build_sql_merge_auto_retry_plan(args.source)
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

        abort_command = base._spark_command(
            args,
            phase="abort-after-commit",
            plan_path=plan_path,
            report_path=work_dir / "spark-abort-after-commit.json",
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
            release_marker=release_marker,
            commit_marker=commit_marker,
            container_name=abort_container,
        )
        abort_process = subprocess.Popen(
            abort_command,
            cwd=base.REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        marker = _wait_for_commit_marker(abort_process, commit_marker, timeout=args.timeout_seconds)
        marker_checks = {
            "schema_exact": marker.get("schema") == "gda.spark_sql_merge_abort_after_commit.v1",
            "snapshot_count_is_three": marker.get("snapshot_count") == 3,
            "marker_snapshot_parent_is_flink": marker.get("parent_snapshot_id")
            == flink_snapshot_id,
            "marker_commit_token_is_fresh": marker.get("commit_token")
            == plan["merge_source_fresh"]["commit_token"],
            "marker_source_row_is_fresh": marker.get("source_row_id")
            == plan["merge_source_fresh"]["source_row_id"],
        }
        kill_result = _kill_container(abort_container, timeout=30)
        abort_exit = _worker_exit_after_kill(abort_process, timeout=60)
        abort_process = None
        reconcile = base._spark_phase(
            args,
            phase="abort-reconcile",
            plan_path=plan_path,
            report_path=reconcile_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
            commit_marker=commit_marker,
            container_name=reconcile_container,
        )
        reconciled_location = base._catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        reconciled_metadata = base._metadata_evidence(client, reconciled_location)
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
            "flink_same_key_append_passed": all(flink_result["checks"].values()),
            "catalog_advanced_to_flink_child": after_flink_metadata["snapshot_count"] == 2
            and after_flink_metadata["current_snapshot"]["parent_id"]
            == baseline["baseline_snapshot_id"],
            "commit_marker_exact": all(marker_checks.values()),
            "provider_container_killed": kill_result["returncode"] == 0
            and abort_exit["expected_sigkill_exit"],
            "independent_reconciliation_passed": all(reconcile["checks"].values())
            and reconcile["reconciliation_status"] == "committed_unacknowledged",
            "reconciliation_did_not_add_snapshot": reconciled_metadata["snapshot_count"]
            == marker["snapshot_count"]
            and reconciled_metadata["current_snapshot"]["snapshot_id"] == marker["snapshot_id"],
            "independent_time_travel_verify_passed": all(verify["checks"].values()),
            "final_snapshot_is_marker_snapshot": reconciled_metadata["current_snapshot"][
                "snapshot_id"
            ]
            == marker["snapshot_id"],
            "sql_merge_abort_recovery_object_graph_materialized": inventory[
                "metadata_json_count"
            ]
            >= 3
            and inventory["manifest_avro_count"] >= 4
            and inventory["data_parquet_count"] >= 5,
        }
        report = {
            "schema": REPORT_SCHEMA,
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "target_road_id": plan["target_road_id"],
                "fresh_source_row_id": plan["merge_source_fresh"]["source_row_id"],
            },
            "fault": {
                "injection": "docker kill --signal KILL after commit marker persisted",
                "marker": marker,
                "kill": kill_result,
                "worker_exit": abort_exit,
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
                "reconciliation": reconcile,
                "verify": verify,
                "final_catalog": reconciled_metadata,
                "object_inventory": inventory,
            },
            "control_plane": {
                "source_sync_advanced": False,
                "data_product_version_created": False,
                "reconciliation_status": "committed_unacknowledged",
            },
            "not_claimed": [
                "production HA, automatic restart, fencing, lease ownership or Kubernetes recovery",
                "cross-system exactly-once, arbitrary network partitions or production RPO/RTO/SLO",
                "SQL UPDATE joins/subqueries, MERGE deletes/inserts, multi-table or multi-file "
                "writes",
                "REST or Gravitino destructive-write conformance",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"provider abort recovery checks failed: {checks}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if abort_process is not None and abort_process.poll() is None:
            abort_process.terminate()
            try:
                abort_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                abort_process.kill()
                abort_process.wait(timeout=15)
        cleanup["abort_spark_container_removed"] = base._remove_container(abort_container)
        cleanup["reconcile_spark_container_removed"] = base._remove_container(reconcile_container)
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
            "schema": REPORT_SCHEMA,
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not all(
        cleanup.get(name) is True
        for name in (
            "abort_spark_container_removed",
            "reconcile_spark_container_removed",
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
