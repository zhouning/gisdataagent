#!/usr/bin/env python3
"""Certify partitioned Spark update isolation against a same-key Flink append."""

from __future__ import annotations

import argparse
import base64
import json
import re
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
    _remove_container,
    _wait_for_spark_ready,
    build_concurrent_append_plan,
)
from scripts.certify_source_sync_authority import _settings

SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_update_conflict.py"
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_update_conflict"
FLINK_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergPartitionAppendJob.java"
FLINK_MAIN_CLASS = "ChongqingOsmIcebergPartitionAppendJob"
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp/source-sync-certification/"
    "chongqing-osm-spark-flink-update-conflict-no-override-report.json"
)
FLINK_STARTED_RE = re.compile(
    r"GDA_PARTITION_FLINK_STARTED road_id=(\d+) revision=(\d+) token=([0-9a-f]{64})"
)
FLINK_COMMITTED_RE = re.compile(
    r"GDA_PARTITION_FLINK_COMMITTED road_id=(\d+) revision=(\d+) token=([0-9a-f]{64})"
)


def _row_order(row: dict[str, Any]) -> tuple[int, int, str]:
    return (int(row["road_id"]), int(row["revision"]), str(row["writer_engine"]))


def build_update_conflict_plan(source_path: Path) -> dict[str, Any]:
    append = build_concurrent_append_plan(source_path)
    baseline = [dict(row) for row in append["baseline_rows"]]
    target = dict(baseline[0])
    target_id = int(target["road_id"])
    source_name = base64.b64decode(target["road_name_base64"]).decode("utf-8")
    flink_name = base64.b64encode(f"{source_name} [Flink revision 2]".encode()).decode("ascii")
    flink_payload = {
        "road_id": target_id,
        "revision": 2,
        "road_name_base64": flink_name,
        "geometry_sha256": target["geometry_sha256"],
        "writer_engine": "flink-1.19.3",
    }
    flink_token = _canonical_sha256(
        {
            "engine": "flink-1.19.3",
            "operation": "same-key-revision-append",
            "row": flink_payload,
            "source_sha256": append["source"]["source_parquet_sha256"],
        }
    )
    flink_row = {**flink_payload, "commit_token": flink_token}
    spark_token = _canonical_sha256(
        {
            "engine": "spark-3.5",
            "operation": "partition-update-by-road-id",
            "target_road_id": target_id,
            "baseline_payload": target,
            "source_sha256": append["source"]["source_parquet_sha256"],
        }
    )
    stale_update_row = {
        **target,
        "revision": 2,
        "writer_engine": "spark-3.5-update",
        "commit_token": spark_token,
    }
    fresh_update_row = {
        **flink_row,
        "revision": 3,
        "writer_engine": "spark-3.5-update",
        "commit_token": spark_token,
    }
    non_target = [row for row in baseline if row["road_id"] != target_id]
    after_flink = sorted([*baseline, flink_row], key=_row_order)
    stale_update = sorted([*non_target, stale_update_row], key=_row_order)
    final = sorted([*non_target, fresh_update_row], key=_row_order)
    return {
        "schema": "gda.chongqing_osm_spark_flink_update_conflict_plan.v1",
        "source": append["source"],
        "baseline_rows": baseline,
        "flink_row": flink_row,
        "stale_update_row": stale_update_row,
        "fresh_update_row": fresh_update_row,
        "after_flink_rows": after_flink,
        "stale_update_rows": stale_update,
        "final_rows": final,
        "target_road_id": target_id,
        "flink_commit_token": flink_token,
        "spark_update_token": spark_token,
        "baseline_content_sha256": _canonical_sha256(baseline),
        "after_flink_content_sha256": _canonical_sha256(after_flink),
        "stale_update_content_sha256": _canonical_sha256(stale_update),
        "final_content_sha256": _canonical_sha256(final),
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
            (
                "--ready-marker",
                f"/workspace/{ready_marker.relative_to(REPO_ROOT).as_posix()}",
            )
        )
    if release_marker:
        command.extend(
            (
                "--release-marker",
                f"/workspace/{release_marker.relative_to(REPO_ROOT).as_posix()}",
            )
        )
    return command


def _spark_phase(args: argparse.Namespace, **kwargs: Any) -> dict[str, Any]:
    phase = str(kwargs["phase"])
    report_path = Path(kwargs["report_path"])
    _run_command(
        _spark_command(args, **kwargs),
        stage=f"Spark update conflict {phase}",
        timeout=args.timeout_seconds,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("phase") != phase:
        raise RuntimeError(f"Spark update conflict {phase} returned failed evidence")
    return report


def _run_flink_partition_append(
    flink: FlinkIcebergSandbox,
    *,
    jar_path: Path,
    plan: dict[str, Any],
    warehouse_uri: str,
    table: str,
    catalog_uri: str,
    catalog_user: str,
    timeout: int,
) -> dict[str, Any]:
    row = plan["flink_row"]
    completed = _run_command(
        [
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
            "--road-id",
            str(row["road_id"]),
            "--revision",
            str(row["revision"]),
            "--road-name-base64",
            row["road_name_base64"],
            "--geometry-sha256",
            row["geometry_sha256"],
            "--commit-token",
            plan["flink_commit_token"],
        ],
        stage="run isolated Flink partition append",
        timeout=timeout,
    )
    started = FLINK_STARTED_RE.search(completed.stdout)
    committed = FLINK_COMMITTED_RE.search(completed.stdout)
    expected = (
        str(row["road_id"]),
        str(row["revision"]),
        plan["flink_commit_token"],
    )
    checks = {
        "single_operation_job_started_exact_row": bool(started and started.groups() == expected),
        "single_operation_job_committed_exact_row": bool(
            committed and committed.groups() == expected
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "road_id": row["road_id"],
        "revision": row["revision"],
        "commit_token": plan["flink_commit_token"],
    }


def _flink_jobmanager_config(
    flink: FlinkIcebergSandbox,
    *,
    timeout: int,
) -> dict[str, str]:
    completed = _run_command(
        [
            "docker",
            "exec",
            flink.container,
            "curl",
            "-fsS",
            "http://localhost:8081/jobmanager/config",
        ],
        stage="read isolated Flink JobManager config",
        timeout=min(timeout, 30),
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list):
        raise RuntimeError("Flink JobManager config returned invalid evidence")
    return {
        str(item["key"]): str(item["value"])
        for item in payload
        if isinstance(item, dict) and "key" in item and "value" in item
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
        REPO_ROOT / ".tmp/source-sync-certification" / f"flink_iceberg_update_conflict_{token}"
    )
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    conflict_path = work_dir / "spark-conflict.json"
    retry_path = work_dir / "spark-retry.json"
    verify_path = work_dir / "spark-verify.json"
    ready_marker = work_dir / "spark-ready.json"
    release_marker = work_dir / "spark-release.json"
    spark_container = f"gda-iceberg-spark-{token}"
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
                "POSTGRES_ADMIN_PASSWORD",
                settings.get("POSTGRES_PASSWORD", "postgres"),
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
        plan = build_update_conflict_plan(args.source)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
        spark_started_at = datetime.now(UTC)
        spark_process = subprocess.Popen(
            spark_command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = _wait_for_spark_ready(
            spark_process,
            ready_marker,
            timeout=args.timeout_seconds,
        )
        spark_ready_at = datetime.now(UTC)
        ready_exact = ready == {
            "schema": "gda.spark_iceberg_update_conflict_ready.v1",
            "baseline_snapshot_id": baseline["baseline_snapshot_id"],
            "commit_token": plan["spark_update_token"],
            "target_road_id": plan["target_road_id"],
            "stale_content_sha256": plan["stale_update_content_sha256"],
        }
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
        flink_committed_at = datetime.now(UTC)
        after_flink_location = _catalog_metadata_location(
            catalog,
            namespace=namespace,
            table_name=table_name,
            timeout=30,
        )
        after_flink_metadata = _metadata_evidence(client, after_flink_location)
        flink_snapshot_id = after_flink_metadata["current_snapshot"]["snapshot_id"]
        release = {
            "schema": "gda.spark_iceberg_update_conflict_release.v1",
            "flink_snapshot_id": flink_snapshot_id,
            "flink_commit_token": plan["flink_commit_token"],
        }
        release_marker.write_text(
            json.dumps(release, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        spark_released_at = datetime.now(UTC)
        stdout, stderr = spark_process.communicate(timeout=args.timeout_seconds)
        if not conflict_path.is_file():
            output = f"stdout={stdout[-3000:]} stderr={stderr[-3000:]}"
            raise RuntimeError(f"Spark update conflict emitted no evidence: {output}")
        conflict = json.loads(conflict_path.read_text(encoding="utf-8"))
        if spark_process.returncode != 0 or conflict.get("status") != "passed":
            raise RuntimeError(
                "Spark stale update was not rejected safely: "
                f"returncode={spark_process.returncode}, "
                f"checks={conflict.get('checks')}, conflict={conflict.get('conflict')}"
            )
        spark_rejected_at = datetime.now(UTC)
        after_conflict_location = _catalog_metadata_location(
            catalog,
            namespace=namespace,
            table_name=table_name,
            timeout=30,
        )
        after_conflict_metadata = _metadata_evidence(client, after_conflict_location)
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
        retry_committed_at = datetime.now(UTC)
        final_location = _catalog_metadata_location(
            catalog,
            namespace=namespace,
            table_name=table_name,
            timeout=30,
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
            "spark_partitioned_baseline_passed": all(baseline["checks"].values()),
            "spark_update_intent_in_flight_before_flink_commit": (
                ready_exact
                and spark_process.returncode is not None
                and spark_started_at < spark_ready_at < flink_committed_at
            ),
            "flink_same_partition_revision_append_passed": all(flink_result["checks"].values()),
            "catalog_pointer_advanced_to_flink_before_release": (
                after_flink_metadata["snapshot_count"] == 2
                and after_flink_metadata["current_snapshot"]["parent_id"]
                == baseline["baseline_snapshot_id"]
                and spark_ready_at < flink_committed_at < spark_released_at
            ),
            "stale_spark_partition_update_failed_closed": all(conflict["checks"].values()),
            "catalog_pointer_unchanged_after_rejection": (
                after_conflict_location == after_flink_location
                and after_conflict_metadata == after_flink_metadata
            ),
            "fresh_state_retry_replaced_target_partition_only": all(retry["checks"].values()),
            "retry_advanced_catalog_once": (
                final_metadata["snapshot_count"] == 3
                and final_metadata["current_snapshot"]["snapshot_id"] == retry["retry_snapshot_id"]
                and final_metadata["current_snapshot"]["parent_id"] == flink_snapshot_id
            ),
            "spark_independent_final_verification_passed": all(verify["checks"].values()),
            "partition_update_object_graph_materialized": (
                inventory["metadata_json_count"] >= 3
                and inventory["manifest_avro_count"] >= 4
                and inventory["data_parquet_count"] >= 5
            ),
        }
        report = {
            "schema": "gda.chongqing_osm_spark_flink_update_conflict.acceptance.v2",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "selected_road_ids": sorted({row["road_id"] for row in plan["baseline_rows"]}),
                "target_road_id": plan["target_road_id"],
                "flink_commit_token": plan["flink_commit_token"],
                "spark_update_token": plan["spark_update_token"],
                "baseline_content_sha256": plan["baseline_content_sha256"],
                "after_flink_content_sha256": plan["after_flink_content_sha256"],
                "stale_update_content_sha256": plan["stale_update_content_sha256"],
                "final_content_sha256": plan["final_content_sha256"],
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
                    "job_operations": ["insert"],
                    "verification_owners": ["spark", "jdbc-catalog"],
                },
                "catalog": {
                    **catalog_evidence,
                    "provider": "org.apache.iceberg.jdbc.JdbcCatalog",
                    "image": args.postgres_image,
                    "image_id": docker_image_id(args.postgres_image, timeout=args.timeout_seconds),
                },
            },
            "concurrency": {
                "spark_ready": ready,
                "flink_result": flink_result,
                "after_flink_catalog": after_flink_metadata,
                "spark_release": release,
                "after_conflict_catalog": after_conflict_metadata,
                "final_catalog": final_metadata,
                "timeline": {
                    "spark_started_at": spark_started_at.isoformat(),
                    "spark_ready_at": spark_ready_at.isoformat(),
                    "flink_committed_at": flink_committed_at.isoformat(),
                    "spark_released_at": spark_released_at.isoformat(),
                    "spark_rejected_at": spark_rejected_at.isoformat(),
                    "retry_committed_at": retry_committed_at.isoformat(),
                },
            },
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "partition_spec": "identity(road_id)",
                "baseline": baseline,
                "stale_update": conflict,
                "retry": retry,
                "verify": verify,
                "object_inventory": inventory,
            },
            "control_plane": {
                "source_sync_advanced": False,
                "data_product_version_created": False,
                "retry_mode": "explicit_fresh_state",
                "update_semantics": "replace one identity road_id partition",
            },
            "not_claimed": [
                "general SQL UPDATE or MERGE conflict isolation",
                "partitioned, equality, position, or merge-on-read delete",
                "automatic retry policy or retry fairness",
                "concurrent streaming checkpoint writers",
                "multi-writer production throughput",
                "cross-system exactly-once transaction",
                "REST or Gravitino catalog interoperability",
                "HA or Kubernetes runtime",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"update conflict checks failed: {checks}")
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
        cleanup.update(_cleanup_prefix(client, prefix))
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
        main_counts_after = _main_sync_counts(admin_url)
        cleanup["main_source_sync_unchanged"] = main_counts_after == main_counts_before
        cleanup["main_source_sync_counts"] = list(main_counts_after)
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_spark_flink_update_conflict.acceptance.v2",
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
