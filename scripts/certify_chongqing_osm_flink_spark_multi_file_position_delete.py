#!/usr/bin/env python3
"""Certify one Flink RowDelta deleting positions from two Spark data files."""

from __future__ import annotations

import argparse
import io
import json
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import pyarrow.parquet as pq

from data_agent.connectors.database import _connection_url
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
    _run_command,
    _spark_artifacts,
    verify_artifact,
)
from scripts.certify_chongqing_osm_flink_stream import (
    REPO_ROOT,
    _canonical_sha256,
    _sha256_file,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_incremental_sync import _main_sync_counts
from scripts.certify_chongqing_osm_spark_flink_concurrent_append import (
    _catalog_metadata_location,
    _metadata_evidence,
)
from scripts.certify_chongqing_osm_spark_flink_position_delete_interop import (
    build_position_delete_plan,
)
from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
    _flink_jobmanager_config,
)
from scripts.certify_source_sync_authority import _settings

JAVA_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergMultiPositionDeleteWriteJob.java"
MAIN_CLASS = "ChongqingOsmIcebergMultiPositionDeleteWriteJob"
SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_multi_file_position_delete.py"
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_multi_file_position_delete"
DEFAULT_REPORT = (
    REPO_ROOT
    / "docs/reports/chongqing_osm_flink_spark_multi_file_position_delete_2026-08-25.json"
)
COMMITTED_RE = re.compile(
    r"GDA_MULTI_POSITION_DELETE_FLINK_COMMITTED snapshot_id=(\d+) "
    r"delete_file=(\S+) entries=(\d+) token=([0-9a-f]{64})"
)
CONFLICT_RE = re.compile(
    r"GDA_MULTI_POSITION_DELETE_CONFLICT_REJECTED baseline=(\d+) "
    r"current=(\d+) entries=(\d+) token=([0-9a-f]{64}) orphan_cleanup=(true|false)"
)


def build_multi_file_position_delete_plan(source_path: Path) -> dict[str, Any]:
    base = build_position_delete_plan(source_path)
    ordered = sorted(base["baseline_rows"], key=lambda row: int(row["road_id"]))
    target_road_ids = [int(ordered[0]["road_id"]), int(ordered[1]["road_id"])]
    final = [row for row in base["baseline_rows"] if row["road_id"] not in target_road_ids]
    token = _canonical_sha256(
        {
            "engine": "flink-1.19.3-iceberg-1.7.2",
            "operation": "multi-file-position-delete",
            "target_road_ids": target_road_ids,
            "baseline_content_sha256": base["baseline_content_sha256"],
            "source_sha256": base["source"]["source_parquet_sha256"],
        }
    )
    return {
        **base,
        "schema": "gda.chongqing_osm_flink_spark_multi_file_position_delete_plan.v1",
        "target_road_ids": target_road_ids,
        "final_rows": final,
        "final_content_sha256": _canonical_sha256(final),
        "flink_commit_token": token,
    }


def _spark_command(
    args: argparse.Namespace,
    *,
    phase: str,
    plan_path: Path,
    report_path: Path,
    warehouse_uri: str,
    table: str,
    access_key: str,
    secret_key: str,
    catalog_uri: str,
    catalog_user: str,
    catalog_password: str,
    baseline_snapshot_id: str | None = None,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        args.docker_network,
        "-e",
        f"JAVA_HOME={args.java_home}",
        "-e",
        f"AWS_ACCESS_KEY_ID={access_key}",
        "-e",
        f"AWS_SECRET_ACCESS_KEY={secret_key}",
        "-e",
        "AWS_REGION=us-east-1",
        "-e",
        f"ICEBERG_CATALOG_URI={catalog_uri}",
        "-e",
        f"ICEBERG_CATALOG_USER={catalog_user}",
        "-e",
        f"ICEBERG_CATALOG_PASSWORD={catalog_password}",
        "-v",
        f"{REPO_ROOT}:/workspace",
        "-w",
        "/workspace",
        args.spark_image,
        "python",
        "-m",
        SPARK_MODULE,
        phase,
        "--plan",
        plan_path.relative_to(REPO_ROOT).as_posix(),
        "--report",
        report_path.relative_to(REPO_ROOT).as_posix(),
        "--warehouse-uri",
        warehouse_uri,
        "--table",
        table,
        "--endpoint-url",
        args.container_endpoint_url,
    ]
    if baseline_snapshot_id:
        command.extend(("--baseline-snapshot-id", baseline_snapshot_id))
    return command


def _spark_phase(args: argparse.Namespace, **kwargs: Any) -> dict[str, Any]:
    phase = str(kwargs["phase"])
    report_path = Path(kwargs["report_path"])
    _run_command(
        _spark_command(args, **kwargs),
        stage=f"Spark multi-file position delete {phase}",
        timeout=args.timeout_seconds,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("phase") != phase:
        raise RuntimeError(f"Spark multi-file position delete {phase} failed evidence")
    return report


def _run_flink(
    flink: FlinkIcebergSandbox,
    *,
    jar_path: Path,
    baseline: dict[str, Any],
    plan: dict[str, Any],
    warehouse_uri: str,
    table: str,
    catalog_uri: str,
    catalog_user: str,
    timeout: int,
    expect_conflict: bool = False,
    commit_token: str | None = None,
) -> dict[str, Any]:
    bindings = sorted(baseline["target_bindings"], key=lambda row: row["road_id"])
    encoded = ",".join(
        f"{item['file_path']}|{item['pos']}|{item['road_id']}" for item in bindings
    )
    command = [
            "docker",
            "exec",
            flink.container,
            "flink",
            "run",
            "-p",
            "1",
            f"/workspace/{jar_path.relative_to(REPO_ROOT).as_posix()}",
            "--warehouse-uri",
            warehouse_uri,
            "--endpoint-url",
            flink.args.container_endpoint_url,
            "--catalog-uri",
            catalog_uri,
            "--catalog-user",
            catalog_user,
            "--table",
            table,
            "--baseline-snapshot-id",
            baseline["baseline_snapshot_id"],
            "--deletes",
            encoded,
            "--commit-token",
            commit_token or plan["flink_commit_token"],
        ]
    if expect_conflict:
        command.append("--expect-conflict")
    completed = _run_command(
        command,
        stage="run isolated Flink multi-file position delete writer",
        timeout=timeout,
    )
    marker = COMMITTED_RE.search(completed.stdout)
    conflict = CONFLICT_RE.search(completed.stdout)
    if expect_conflict:
        checks = {
            "conflict_marker_observed": conflict is not None,
            "baseline_snapshot_bound": bool(
                conflict and conflict.group(1) == baseline["baseline_snapshot_id"]
            ),
            "current_snapshot_advanced": bool(
                conflict and conflict.group(2) != conflict.group(1)
            ),
            "entry_count_exact": bool(conflict and int(conflict.group(3)) == 2),
            "commit_token_exact": bool(
                conflict and conflict.group(4) == (commit_token or plan["flink_commit_token"])
            ),
            "orphan_delete_file_cleaned": bool(conflict and conflict.group(5) == "true"),
        }
        return {
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "baseline_snapshot_id": conflict.group(1) if conflict else None,
            "current_snapshot_id": conflict.group(2) if conflict else None,
            "entries": int(conflict.group(3)) if conflict else None,
            "commit_token": conflict.group(4) if conflict else None,
            "orphan_delete_file_cleaned": conflict.group(5) == "true" if conflict else None,
            "stdout": completed.stdout[-4000:],
        }
    checks = {
        "commit_marker_observed": marker is not None,
        "delete_file_in_acceptance_table": bool(
            marker
            and marker.group(2).startswith(f"{warehouse_uri}/")
            and marker.group(2).endswith(".parquet")
        ),
        "entry_count_exact": bool(marker and int(marker.group(3)) == 2),
        "commit_token_exact": bool(marker and marker.group(4) == plan["flink_commit_token"]),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "snapshot_id": marker.group(1) if marker else None,
        "delete_file_path": marker.group(2) if marker else None,
        "entries": int(marker.group(3)) if marker else None,
        "commit_token": marker.group(4) if marker else None,
        "stdout": completed.stdout[-4000:],
    }


def _flink_job_evidence(flink: FlinkIcebergSandbox, *, timeout: int) -> dict[str, Any]:
    completed = _run_command(
        [
            "docker",
            "exec",
            flink.container,
            "curl",
            "-fsS",
            "http://localhost:8081/jobs/overview",
        ],
        stage="inspect Flink multi-file position delete job",
        timeout=timeout,
    )
    jobs = json.loads(completed.stdout).get("jobs", [])
    return {
        "jobs": jobs,
        "one_finished_job": len(jobs) == 1
        and jobs[0].get("state") == "FINISHED"
        and jobs[0].get("tasks", {}).get("total") == 1
        and jobs[0].get("tasks", {}).get("finished") == 1,
    }


def _read_delete_payload(client: Any, *, file_path: str, prefix: str) -> dict[str, Any]:
    expected = f"s3://{BUCKET}/{prefix}"
    if not file_path.startswith(expected) or not file_path.endswith(".parquet"):
        raise RuntimeError("multi-file position delete file is outside acceptance prefix")
    payload = client.get_object(
        Bucket=BUCKET,
        Key=file_path.removeprefix(f"s3://{BUCKET}/"),
    )["Body"].read()
    table = pq.read_table(io.BytesIO(payload))
    if table.column_names[:2] != ["file_path", "pos"]:
        raise RuntimeError(f"unexpected position delete columns: {table.column_names}")
    return {
        "file_path": file_path,
        "bytes": len(payload),
        "rows": table.num_rows,
        "referenced_data_files": [str(value) for value in table["file_path"].to_pylist()],
        "positions": [int(value) for value in table["pos"].to_pylist()],
    }


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
    parser.add_argument("--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--conflict", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    settings = _settings()
    access_key = settings.get("MINIO_ROOT_USER", "minio_admin")
    secret_key = settings.get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret")
    token = secrets.token_hex(5)
    prefix = f"acceptance/flink-iceberg/gda_flink_iceberg_{token}/"
    warehouse_uri = f"s3://{BUCKET}/{prefix}warehouse"
    namespace = f"gda_interop_{token}"
    table_name = "chongqing_osm_roads"
    table = f"lakehouse.{namespace}.{table_name}"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / f"multi_position_delete_{token}"
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    verify_path = work_dir / "spark-verify.json"
    client = boto3.client(
        "s3",
        endpoint_url=args.host_endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    admin_url = _connection_url(
        args.postgres_url,
        {
            "type": "basic",
            "username": settings.get("POSTGRES_USER", "postgres"),
            "password": settings.get(
                "POSTGRES_ADMIN_PASSWORD", settings.get("POSTGRES_PASSWORD", "postgres")
            ),
        },
    )
    main_counts_before = _main_sync_counts(admin_url)
    catalog: IcebergCatalogSandbox | None = None
    flink: FlinkIcebergSandbox | None = None
    report: dict[str, Any] | None = None
    cleanup: dict[str, Any] = {}
    error: str | None = None
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        flink_artifacts = {
            "runtime": verify_artifact(FLINK_ICEBERG),
            "aws_bundle": verify_artifact(FLINK_AWS),
            "postgresql_jdbc": verify_artifact(POSTGRES_JDBC),
            "hadoop_client_api": verify_artifact(HADOOP_CLIENT_API),
            "hadoop_client_runtime": verify_artifact(HADOOP_CLIENT_RUNTIME),
        }
        spark_artifacts = _spark_artifacts(args.spark_image, timeout=args.timeout_seconds)
        plan = build_multi_file_position_delete_plan(args.source)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        catalog = IcebergCatalogSandbox(
            image=args.postgres_image,
            network=args.docker_network,
            token=token,
        )
        catalog.start()
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
        baseline_location = _catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        baseline_metadata = _metadata_evidence(client, baseline_location)
        jar_path = compile_flink_job(
            work_dir=work_dir / "build",
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=JAVA_SOURCE,
            main_class=MAIN_CLASS,
            extra_compile_classpath=(Path(FLINK_ICEBERG["path"]),),
        )
        flink = FlinkIcebergSandbox(
            args=args,
            token=token,
            access_key=access_key,
            secret_key=secret_key,
            catalog_password=catalog.password,
            extra_flink_properties=("classloader.check-leaked-classloader: true",),
        )
        cluster = flink.start()
        flink_config = _flink_jobmanager_config(flink, timeout=args.timeout_seconds)
        flink_commit = _run_flink(
            flink,
            jar_path=jar_path,
            baseline=baseline,
            plan=plan,
            warehouse_uri=warehouse_uri,
            table=table,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            timeout=args.timeout_seconds,
        )
        if flink_commit["status"] != "passed":
            raise RuntimeError(f"initial multi-file position delete failed: {flink_commit}")
        flink_job = _flink_job_evidence(flink, timeout=args.timeout_seconds)
        delete_location = _catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        delete_metadata = _metadata_evidence(client, delete_location)
        conflict_probe: dict[str, Any] | None = None
        conflict_metadata: dict[str, Any] | None = None
        if args.conflict:
            conflict_probe = _run_flink(
                flink,
                jar_path=jar_path,
                baseline=baseline,
                plan=plan,
                warehouse_uri=warehouse_uri,
                table=table,
                catalog_uri=catalog.jdbc_uri,
                catalog_user=catalog.user,
                timeout=args.timeout_seconds,
                expect_conflict=True,
                commit_token=_canonical_sha256(
                    {
                        "base": plan["flink_commit_token"],
                        "operation": "stale-multi-file-position-delete",
                    }
                ),
            )
            if conflict_probe["status"] != "passed":
                raise RuntimeError(
                    "stale multi-file position delete was not rejected: "
                    f"{conflict_probe}"
                )
            conflict_metadata = _metadata_evidence(client, delete_location)
        verify = _spark_phase(
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
        )
        physical_delete = _read_delete_payload(
            client, file_path=flink_commit["delete_file_path"], prefix=prefix
        )
        expected_bindings = sorted(
            (item["file_path"], item["pos"]) for item in baseline["target_bindings"]
        )
        actual_bindings = sorted(
            zip(
                physical_delete["referenced_data_files"],
                physical_delete["positions"],
                strict=True,
            )
        )
        inventory = _object_inventory(client, prefix)
        checks = {
            "real_chongqing_osm_source_bound": plan["source"]["source_feature_count"] == 50_366
            and plan["source"]["source_product_sha256"] == DEFAULT_SOURCE_PRODUCT_SHA256,
            "supply_chain_artifacts_verified": True,
            "flink_classloader_safety_check_enabled": flink_config.get(
                "classloader.check-leaked-classloader"
            )
            == "true",
            "spark_multi_file_baseline_passed": all(baseline["checks"].values()),
            "baseline_snapshot_is_catalog_current": baseline_metadata["current_snapshot"][
                "snapshot_id"
            ]
            == baseline["baseline_snapshot_id"],
            "flink_multi_position_delete_commit_passed": all(flink_commit["checks"].values()),
            "flink_taskmanager_job_finished_once": flink_job["one_finished_job"],
            "catalog_advanced_to_flink_delete_child": delete_metadata["snapshot_count"] == 3
            and delete_metadata["current_snapshot"]["snapshot_id"] == flink_commit["snapshot_id"]
            and delete_metadata["current_snapshot"]["parent_id"]
            == baseline["baseline_snapshot_id"],
            "independent_spark_multi_file_verify_passed": all(verify["checks"].values()),
            "physical_delete_payload_has_two_exact_bindings": physical_delete["rows"] == 2
            and actual_bindings == expected_bindings,
            "multi_file_object_graph_materialized": inventory["metadata_json_count"] >= 3
            and inventory["manifest_avro_count"] >= 4
            and inventory["data_parquet_count"] >= 3,
            "stale_multi_file_conflict_rejected": not args.conflict
            or all(conflict_probe["checks"].values()),
            "stale_conflict_left_catalog_unchanged": not args.conflict
            or (
                conflict_metadata["current_snapshot"]["snapshot_id"]
                == flink_commit["snapshot_id"]
                and conflict_metadata["snapshot_count"] == 3
            ),
        }
        report = {
            "schema": "gda.chongqing_osm_flink_spark_multi_file_position_delete.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {**plan["source"], "target_road_ids": plan["target_road_ids"]},
            "runtime": {
                "spark_image": args.spark_image,
                "spark_image_id": docker_image_id(args.spark_image, timeout=args.timeout_seconds),
                "flink_image": args.flink_image,
                "flink_image_id": docker_image_id(args.flink_image, timeout=args.timeout_seconds),
                "spark_artifacts": spark_artifacts,
                "spark_job_source_sha256": _sha256_file(SPARK_SOURCE),
                "flink_artifacts": flink_artifacts,
                "flink_job_source_sha256": _sha256_file(JAVA_SOURCE),
                "flink_job_jar_sha256": _sha256_file(jar_path),
                "flink_cluster": cluster,
            },
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "format_version": 2,
                "baseline": baseline,
                "flink_commit": flink_commit,
                "stale_conflict": conflict_probe,
                "final_catalog": delete_metadata,
                "conflict_catalog": conflict_metadata,
                "verify": verify,
                "physical_delete": physical_delete,
                "object_inventory": inventory,
            },
            "control_plane": {
                "source_sync_advanced": False,
                "data_product_version_created": False,
                "delete_mode": "merge-on-read",
                "observed_provider_delete_mode": "position-delete",
                "writer_engine": "flink-1.19.3",
                "writer_recovery_mode": "explicit_bounded_multi_file_delete",
                "stale_conflict_probe": args.conflict,
            },
            "not_claimed": [
                "partitioned tables, more than two data files, multiple delete files, "
                "or compaction",
                "SQL UPDATE/MERGE, equality-delete semantics, checkpoint exactly-once, "
                "REST/Gravitino, production HA/RPO/RTO",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"multi-file position delete checks failed: {checks}")
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}"
        for value in (access_key, secret_key, catalog.password if catalog else ""):
            if value:
                safe = safe.replace(value, "<redacted>")
        error = safe
    finally:
        cleanup["flink_container_removed"] = flink.cleanup() if flink is not None else True
        cleanup["catalog_container_removed"] = catalog.cleanup() if catalog is not None else True
        cleanup.update(_cleanup_prefix(client, prefix))
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
        main_counts_after = _main_sync_counts(admin_url)
        cleanup["main_source_sync_unchanged"] = main_counts_after == main_counts_before
        cleanup["main_source_sync_counts"] = list(main_counts_after)
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_flink_spark_multi_file_position_delete.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    required_cleanup = (
        "flink_container_removed",
        "catalog_container_removed",
        "object_prefix_empty",
        "work_directory_removed",
        "main_source_sync_unchanged",
    )
    if not all(cleanup.get(name) is True for name in required_cleanup):
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
