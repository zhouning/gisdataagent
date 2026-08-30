#!/usr/bin/env python3
"""Certify real Spark SQL UPDATE conflict isolation against a Flink append."""

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
    _remove_container,
    _wait_for_spark_ready,
)
from scripts.certify_chongqing_osm_spark_flink_sql_merge_conflict import (
    _cleanup_prefix_safe,
    _keys,
    _remove_keys,
)
from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
    _flink_jobmanager_config,
    _run_flink_partition_append,
    build_update_conflict_plan,
)
from scripts.certify_source_sync_authority import _settings

SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_sql_update_conflict.py"
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_sql_update_conflict"
FLINK_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergPartitionAppendJob.java"
FLINK_MAIN_CLASS = "ChongqingOsmIcebergPartitionAppendJob"
DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/chongqing-osm-spark-flink-sql-update-conflict-report.json"
)


def build_sql_update_conflict_plan(source_path: Path) -> dict[str, Any]:
    base = build_update_conflict_plan(source_path)
    target = next(row for row in base["baseline_rows"] if row["road_id"] == base["target_road_id"])
    flink = base["flink_row"]
    stale_token = _canonical_sha256(
        {
            "engine": "spark-3.5-sql",
            "operation": "update-stale-baseline-revision",
            "target_road_id": base["target_road_id"],
            "source_sha256": base["source"]["source_parquet_sha256"],
            "baseline_content_sha256": base["baseline_content_sha256"],
        }
    )
    fresh_token = _canonical_sha256(
        {
            "engine": "spark-3.5-sql",
            "operation": "update-fresh-flink-revision",
            "target_road_id": base["target_road_id"],
            "flink_token": base["flink_commit_token"],
            "source_sha256": base["source"]["source_parquet_sha256"],
        }
    )
    stale = {
        "road_id": target["road_id"],
        "expected_revision": 1,
        "new_revision": 2,
        "road_name_base64": target["road_name_base64"],
        "geometry_sha256": target["geometry_sha256"],
        "writer_engine": "spark-sql-update",
        "commit_token": stale_token,
    }
    fresh = {
        "road_id": flink["road_id"],
        "expected_revision": 2,
        "new_revision": 3,
        "road_name_base64": flink["road_name_base64"],
        "geometry_sha256": flink["geometry_sha256"],
        "writer_engine": "spark-sql-update",
        "commit_token": fresh_token,
    }
    fresh_row = {
        "road_id": flink["road_id"],
        "revision": 3,
        "road_name_base64": flink["road_name_base64"],
        "geometry_sha256": flink["geometry_sha256"],
        "writer_engine": "spark-sql-update",
        "commit_token": fresh_token,
    }
    final_rows = sorted(
        [row for row in base["after_flink_rows"] if row["road_id"] != base["target_road_id"]]
        + [
            row
            for row in base["after_flink_rows"]
            if row["road_id"] == base["target_road_id"] and row["revision"] == 1
        ]
        + [fresh_row],
        key=lambda row: (int(row["road_id"]), int(row["revision"]), str(row["writer_engine"])),
    )
    return {
        **base,
        "schema": "gda.chongqing_osm_spark_flink_sql_update_conflict_plan.v1",
        "sql_update_stale": stale,
        "sql_update_fresh": fresh,
        "sql_update_stale_token": stale_token,
        "sql_update_fresh_token": fresh_token,
        "sql_update_stale_expected_revision": 1,
        "final_sql_update_rows": final_rows,
        "final_sql_update_content_sha256": _canonical_sha256(final_rows),
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
    flink_snapshot_id: str | None = None,
    ready_marker: Path | None = None,
    release_marker: Path | None = None,
    container_name: str | None = None,
) -> list[str]:
    command = ["docker", "run", "--rm"]
    if container_name:
        command.extend(("--name", container_name))
    command.extend(
        (
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
        )
    )
    if baseline_snapshot_id:
        command.extend(("--baseline-snapshot-id", baseline_snapshot_id))
    if flink_snapshot_id:
        command.extend(("--flink-snapshot-id", flink_snapshot_id))
    if ready_marker:
        command.extend(
            ("--ready-marker", f"/workspace/{ready_marker.relative_to(REPO_ROOT).as_posix()}")
        )
    if release_marker:
        command.extend(
            ("--release-marker", f"/workspace/{release_marker.relative_to(REPO_ROOT).as_posix()}")
        )
    return command


def _spark_phase(args: argparse.Namespace, **kwargs: Any) -> dict[str, Any]:
    report_path = Path(kwargs["report_path"])
    _run_command(
        _spark_command(args, **kwargs),
        stage=f"Spark SQL UPDATE {kwargs['phase']}",
        timeout=args.timeout_seconds,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("phase") != kwargs["phase"]:
        raise RuntimeError(f"Spark SQL UPDATE {kwargs['phase']} returned failed evidence")
    return report


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
    work_dir = (
        REPO_ROOT / ".tmp/source-sync-certification" / f"flink_iceberg_sql_update_conflict_{token}"
    )
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    conflict_path = work_dir / "spark-conflict.json"
    retry_path = work_dir / "spark-retry.json"
    verify_path = work_dir / "spark-verify.json"
    ready_marker = work_dir / "spark-ready.json"
    release_marker = work_dir / "spark-release.json"
    spark_container = f"gda-iceberg-spark-sql-update-{token}"
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
    spark_process: subprocess.Popen[str] | None = None
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
        plan = build_sql_update_conflict_plan(args.source)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        catalog = IcebergCatalogSandbox(
            image=args.postgres_image, network=args.docker_network, token=token
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
            work_dir=work_dir / "build",
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=FLINK_SOURCE,
            main_class=FLINK_MAIN_CLASS,
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
        spark_command = _spark_command(
            args,
            phase="concurrent-update",
            plan_path=plan_path,
            report_path=conflict_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
            ready_marker=ready_marker,
            release_marker=release_marker,
            container_name=spark_container,
        )
        spark_process = subprocess.Popen(
            spark_command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = _wait_for_spark_ready(spark_process, ready_marker, timeout=args.timeout_seconds)
        flink_result = _run_flink_partition_append(
            flink,
            jar_path=jar_path,
            plan=plan,
            warehouse_uri=warehouse_uri,
            table=table,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            timeout=args.timeout_seconds,
        )
        after_flink_location = _catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        after_flink_metadata = _metadata_evidence(client, after_flink_location)
        after_flink_keys = _keys(client, prefix)
        flink_snapshot_id = after_flink_metadata["current_snapshot"]["snapshot_id"]
        release_marker.write_text(
            json.dumps(
                {
                    "schema": "gda.spark_sql_update_conflict_release.v1",
                    "flink_snapshot_id": flink_snapshot_id,
                    "flink_commit_token": plan["flink_commit_token"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        stdout, stderr = spark_process.communicate(timeout=args.timeout_seconds)
        conflict = json.loads(conflict_path.read_text(encoding="utf-8"))
        if spark_process.returncode != 0 or conflict.get("status") != "passed":
            raise RuntimeError(
                "SQL UPDATE conflict was not rejected: "
                f"returncode={spark_process.returncode}, checks={conflict.get('checks')}, "
                f"stdout={stdout[-1500:]}, stderr={stderr[-1500:]}"
            )
        after_conflict_location = _catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        after_conflict_metadata = _metadata_evidence(client, after_conflict_location)
        orphan_keys = _keys(client, prefix) - after_flink_keys
        orphan_cleanup = _remove_keys(client, orphan_keys, prefix=prefix)
        orphan_cleanup.update(
            {
                "detected_keys": sorted(orphan_keys),
                "catalog_unchanged_before_cleanup": (
                    after_conflict_location == after_flink_location
                    and after_conflict_metadata == after_flink_metadata
                ),
            }
        )
        retry = _spark_phase(
            args,
            phase="retry",
            plan_path=plan_path,
            report_path=retry_path,
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
        final_location = _catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        final_metadata = _metadata_evidence(client, final_location)
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
            flink_snapshot_id=flink_snapshot_id,
        )
        inventory = _object_inventory(client, prefix)
        checks = {
            "real_chongqing_osm_source_bound": (
                plan["source"]["source_feature_count"] == 50_366
                and plan["source"]["source_product_sha256"] == DEFAULT_SOURCE_PRODUCT_SHA256
            ),
            "supply_chain_artifacts_verified": True,
            "flink_classloader_safety_check_enabled": (
                flink_config.get("classloader.check-leaked-classloader") == "true"
            ),
            "spark_sql_update_ready_marker_exact": ready
            == {
                "schema": "gda.spark_sql_update_conflict_ready.v1",
                "baseline_snapshot_id": baseline["baseline_snapshot_id"],
                "commit_token": plan["sql_update_stale_token"],
                "target_road_id": plan["target_road_id"],
                "expected_revision": 1,
            },
            "flink_same_key_append_passed": all(flink_result["checks"].values()),
            "catalog_advanced_to_flink_child": (
                after_flink_metadata["snapshot_count"] == 2
                and after_flink_metadata["current_snapshot"]["parent_id"]
                == baseline["baseline_snapshot_id"]
            ),
            "stale_sql_update_rejected": all(conflict["checks"].values()),
            "catalog_unchanged_after_stale_update": (
                after_conflict_location == after_flink_location
                and after_conflict_metadata == after_flink_metadata
            ),
            "stale_update_orphans_explicitly_cleaned": (
                orphan_cleanup["keys_removed"] == len(orphan_keys)
                and orphan_cleanup["remaining_keys"] == len(after_flink_keys)
            ),
            "fresh_sql_update_retry_passed": all(retry["checks"].values()),
            "independent_sql_update_verify_passed": all(verify["checks"].values()),
            "final_snapshot_child_of_flink": (
                final_metadata["current_snapshot"]["parent_id"] == flink_snapshot_id
            ),
            "sql_update_object_graph_materialized": (
                inventory["metadata_json_count"] >= 3
                and inventory["manifest_avro_count"] >= 4
                and inventory["data_parquet_count"] >= 5
            ),
        }
        report = {
            "schema": "gda.chongqing_osm_spark_flink_sql_update_conflict.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "target_road_id": plan["target_road_id"],
                "baseline_content_sha256": plan["baseline_content_sha256"],
                "after_flink_content_sha256": plan["after_flink_content_sha256"],
                "final_sql_update_content_sha256": plan["final_sql_update_content_sha256"],
                "stale_token": plan["sql_update_stale_token"],
                "fresh_token": plan["sql_update_fresh_token"],
            },
            "runtime": {
                "spark_image": args.spark_image,
                "spark_image_id": docker_image_id(args.spark_image, timeout=args.timeout_seconds),
                "flink_image": args.flink_image,
                "flink_image_id": docker_image_id(args.flink_image, timeout=args.timeout_seconds),
                "spark_artifacts": spark_artifacts,
                "spark_job_source_sha256": _sha256_file(SPARK_SOURCE),
                "flink_artifacts": flink_artifacts,
                "flink_job_source_sha256": _sha256_file(FLINK_SOURCE),
                "flink_job_jar_sha256": _sha256_file(jar_path),
                "flink_cluster": cluster,
                "flink_classloader_safety": {
                    "expected": {"classloader.check-leaked-classloader": "true"},
                    "observed": {
                        "classloader.check-leaked-classloader": flink_config.get(
                            "classloader.check-leaked-classloader"
                        )
                    },
                },
                "catalog": {
                    **catalog_evidence,
                    "provider": "org.apache.iceberg.jdbc.JdbcCatalog",
                    "image": args.postgres_image,
                    "image_id": docker_image_id(args.postgres_image, timeout=args.timeout_seconds),
                },
            },
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "partition_spec": "identity(road_id)",
                "format_version": 2,
                "baseline": baseline,
                "after_flink_catalog": after_flink_metadata,
                "stale_sql_update": conflict,
                "after_stale_catalog": after_conflict_metadata,
                "orphan_cleanup": orphan_cleanup,
                "retry": retry,
                "verify": verify,
                "final_catalog": final_metadata,
                "object_inventory": inventory,
            },
            "control_plane": {
                "source_sync_advanced": False,
                "data_product_version_created": False,
                "retry_mode": "explicit_fresh_state_sql_update",
            },
            "not_claimed": [
                "SQL MERGE semantics beyond ADR-256",
                "SQL UPDATE with joins, subqueries, multiple predicates, deletes or inserts",
                "partition evolution, equality/position delete or MOR",
                "automatic retry, streaming checkpoint writers, REST or Gravitino catalog",
                "HA, Kubernetes, production SLO/RPO/RTO",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"SQL UPDATE checks failed: {checks}")
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}"
        catalog_password = catalog.password if catalog is not None else ""
        for value in (access_key, secret_key, catalog_password):
            if value:
                safe = safe.replace(value, "<redacted>")
        error = safe
    finally:
        if spark_process is not None and spark_process.poll() is None:
            spark_process.terminate()
            try:
                spark_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                spark_process.kill()
                spark_process.wait(timeout=15)
        cleanup["spark_container_removed"] = _remove_container(spark_container)
        cleanup["flink_container_removed"] = flink.cleanup() if flink is not None else True
        cleanup["catalog_container_removed"] = catalog.cleanup() if catalog is not None else True
        cleanup.update(_cleanup_prefix_safe(client, prefix))
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
        main_counts_after = _main_sync_counts(admin_url)
        cleanup["main_source_sync_unchanged"] = main_counts_after == main_counts_before
        cleanup["main_source_sync_counts"] = list(main_counts_after)
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_spark_flink_sql_update_conflict.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not all(
        cleanup.get(name) is True
        for name in (
            "spark_container_removed",
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
