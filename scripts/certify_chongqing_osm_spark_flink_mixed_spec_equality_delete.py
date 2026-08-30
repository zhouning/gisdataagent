#!/usr/bin/env python3
"""Certify a real Flink equality delete across two Iceberg partition specs."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_agent.connectors.database import _connection_url
from data_agent.fusion.lakehouse_publisher import build_iceberg_equality_delete_admission
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
from scripts.certify_chongqing_osm_flink_spark_equality_delete_interop import (
    _run_flink_equality_delete,
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
from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
    FLINK_MAIN_CLASS as FLINK_APPEND_MAIN_CLASS,
)
from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
    FLINK_SOURCE as FLINK_APPEND_SOURCE,
)
from scripts.certify_chongqing_osm_spark_flink_update_conflict import (
    _flink_jobmanager_config,
    _run_flink_partition_append,
    build_update_conflict_plan,
)
from scripts.certify_source_sync_authority import _settings

SPARK_SOURCE = REPO_ROOT / "scripts/spark_chongqing_osm_iceberg_mixed_spec_equality_delete.py"
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_mixed_spec_equality_delete"
FLINK_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergEqualityDeleteJob.java"
FLINK_MAIN_CLASS = "ChongqingOsmIcebergEqualityDeleteJob"
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp/source-sync-certification/"
    "chongqing-osm-spark-flink-mixed-spec-equality-delete-report.json"
)


def build_mixed_spec_equality_delete_plan(source_path: Path) -> dict[str, Any]:
    base = build_update_conflict_plan(source_path)
    append_token = base["flink_commit_token"]
    target = next(row for row in base["baseline_rows"] if row["road_id"] == base["target_road_id"])
    delete_token = _canonical_sha256(
        {
            "engine": "flink-1.19.3",
            "operation": "mixed-spec-equality-delete",
            "target_road_id": base["target_road_id"],
            "source_sha256": base["source"]["source_parquet_sha256"],
        }
    )
    final = [row for row in base["after_flink_rows"] if row["road_id"] != base["target_road_id"]]
    return {
        **base,
        "schema": "gda.chongqing_osm_spark_flink_mixed_spec_equality_delete_plan.v1",
        "delete_row": target,
        "flink_append_commit_token": append_token,
        "flink_commit_token": delete_token,
        "after_mixed_delete_rows": final,
        "after_mixed_delete_content_sha256": _canonical_sha256(final),
    }


def _spark_phase(
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
    rewrite_snapshot_id: str | None = None,
) -> dict[str, Any]:
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
    if flink_snapshot_id:
        command.extend(("--flink-snapshot-id", flink_snapshot_id))
    if rewrite_snapshot_id:
        command.extend(("--rewrite-snapshot-id", rewrite_snapshot_id))
    try:
        _run_command(
            command,
            stage=f"Spark mixed-spec equality delete {phase}",
            timeout=args.timeout_seconds,
        )
    except RuntimeError as exc:
        if report_path.is_file():
            phase_report = json.loads(report_path.read_text(encoding="utf-8"))
            if phase == "verify" and phase_report.get("phase") == phase:
                return phase_report
            raise RuntimeError(
                f"{exc}; phase_report={json.dumps(phase_report, sort_keys=True)}"
            ) from exc
        raise
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("phase") != phase:
        raise RuntimeError(f"Spark mixed-spec equality delete {phase} returned failed evidence")
    if report.get("status") != "passed" and phase != "verify":
        raise RuntimeError(f"Spark mixed-spec equality delete {phase} returned failed evidence")
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
    parser.add_argument("--controlled-rewrite", action="store_true")
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
        REPO_ROOT
        / ".tmp/source-sync-certification"
        / f"flink_iceberg_mixed_spec_equality_delete_{token}"
    )
    plan_path = work_dir / "plan.json"
    baseline_path = work_dir / "spark-baseline.json"
    evolve_path = work_dir / "spark-evolve.json"
    rewrite_path = work_dir / "spark-rewrite.json"
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
        plan = build_mixed_spec_equality_delete_plan(args.source)
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
        evolve = _spark_phase(
            args,
            phase="evolve",
            plan_path=plan_path,
            report_path=evolve_path,
            warehouse_uri=warehouse_uri,
            table=table,
            access_key=access_key,
            secret_key=secret_key,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            catalog_password=catalog.password,
            baseline_snapshot_id=baseline["baseline_snapshot_id"],
        )
        jar_path = compile_flink_job(
            work_dir=work_dir / "build-append",
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=FLINK_APPEND_SOURCE,
            main_class=FLINK_APPEND_MAIN_CLASS,
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
        flink_append_result = _run_flink_partition_append(
            flink,
            jar_path=jar_path,
            plan={**plan, "flink_commit_token": plan["flink_append_commit_token"]},
            warehouse_uri=warehouse_uri,
            table=table,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            timeout=args.timeout_seconds,
        )
        after_append_location = _catalog_metadata_location(
            catalog, namespace=namespace, table_name=table_name, timeout=30
        )
        after_append_metadata = _metadata_evidence(client, after_append_location)
        flink_snapshot_id = after_append_metadata["current_snapshot"]["snapshot_id"]
        rewrite = None
        rewrite_snapshot_id = None
        if args.controlled_rewrite:
            rewrite = _spark_phase(
                args,
                phase="rewrite",
                plan_path=plan_path,
                report_path=rewrite_path,
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
            rewrite_snapshot_id = rewrite["rewrite_snapshot_id"]
        equality_jar_path = compile_flink_job(
            work_dir=work_dir / "build-equality-delete",
            flink_image=args.flink_image,
            jdk_image=args.jdk_image,
            java_home=args.java_home,
            timeout=args.timeout_seconds,
            java_source=FLINK_SOURCE,
            main_class=FLINK_MAIN_CLASS,
        )
        flink_result = _run_flink_equality_delete(
            flink,
            jar_path=equality_jar_path,
            plan=plan,
            warehouse_uri=warehouse_uri,
            table=table,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
            timeout=args.timeout_seconds,
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
            rewrite_snapshot_id=rewrite_snapshot_id,
        )
        inventory = _object_inventory(client, prefix)
        data_spec_ids = sorted(
            {int(item["spec_id"]) for item in verify["files"] if int(item["content"]) == 0}
        )
        equality_delete_admission = build_iceberg_equality_delete_admission(
            data_spec_ids,
            current_spec_id=max(data_spec_ids) if data_spec_ids else None,
            rewrite_completed=args.controlled_rewrite,
        )
        pre_rewrite_files = rewrite["before_files"] if rewrite else verify["files"]
        pre_rewrite_spec_ids = sorted(
            {
                int(item["spec_id"])
                for item in pre_rewrite_files
                if int(item["content"]) == 0
            }
        )
        pre_rewrite_admission = build_iceberg_equality_delete_admission(
            pre_rewrite_spec_ids,
            current_spec_id=max(pre_rewrite_spec_ids) if pre_rewrite_spec_ids else None,
        )
        delete_parent_snapshot_id = rewrite_snapshot_id or flink_snapshot_id
        checks = {
            "real_chongqing_osm_source_bound": plan["source"]["source_feature_count"] == 50_366
            and plan["source"]["source_product_sha256"] == DEFAULT_SOURCE_PRODUCT_SHA256,
            "supply_chain_artifacts_verified": True,
            "spark_baseline_passed": all(baseline["checks"].values()),
            "spark_partition_evolution_passed": all(evolve["checks"].values()),
            "flink_revision_two_append_passed": all(flink_append_result["checks"].values()),
            "flink_equality_delete_passed": all(flink_result["checks"].values()),
            "independent_final_verification_passed": all(verify["checks"].values()),
            "mixed_spec_equality_delete_admission_fail_closed": (
                not equality_delete_admission["admitted"]
                if not args.controlled_rewrite
                else equality_delete_admission["admitted"]
            ),
            "controlled_rewrite_passed": not args.controlled_rewrite
            or all(rewrite["checks"].values()),
            "pre_rewrite_admission_rejected": not args.controlled_rewrite
            or not pre_rewrite_admission["admitted"],
            "post_rewrite_admission_admitted": not args.controlled_rewrite
            or equality_delete_admission["admitted"],
            "catalog_append_child_of_flink_baseline": after_append_metadata["current_snapshot"][
                "parent_id"
            ]
            == baseline["baseline_snapshot_id"],
            "catalog_delete_child_of_rewrite_or_flink": final_metadata["current_snapshot"][
                "parent_id"
            ]
            == delete_parent_snapshot_id,
            "mixed_spec_equality_delete_object_graph_materialized": inventory["metadata_json_count"]
            >= 3
            and inventory["manifest_avro_count"] >= 3
            and inventory["data_parquet_count"] >= 3,
        }
        report = {
            "schema": "gda.chongqing_osm_spark_flink_mixed_spec_equality_delete.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "controlled_rewrite" if args.controlled_rewrite else "mixed_spec_probe",
            "checks": checks,
            "source": {
                **plan["source"],
                "baseline_content_sha256": plan["baseline_content_sha256"],
                "after_flink_content_sha256": plan["after_flink_content_sha256"],
                "after_mixed_delete_content_sha256": plan["after_mixed_delete_content_sha256"],
                "target_road_id": plan["target_road_id"],
                "flink_append_commit_token": plan["flink_append_commit_token"],
                "flink_commit_token": plan["flink_commit_token"],
            },
            "runtime": {
                "spark_image": args.spark_image,
                "spark_image_id": docker_image_id(args.spark_image, timeout=args.timeout_seconds),
                "flink_image": args.flink_image,
                "flink_image_id": docker_image_id(args.flink_image, timeout=args.timeout_seconds),
                "spark_artifacts": spark_artifacts,
                "spark_job_source_sha256": _sha256_file(SPARK_SOURCE),
                "flink_artifacts": flink_artifacts,
                "flink_append_job_source_sha256": _sha256_file(FLINK_APPEND_SOURCE),
                "flink_append_job_jar_sha256": _sha256_file(jar_path),
                "flink_job_source_sha256": _sha256_file(FLINK_SOURCE),
                "flink_job_jar_sha256": _sha256_file(equality_jar_path),
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
                "format_version": 2,
                "baseline": baseline,
                "evolution": evolve,
                "flink_append": flink_append_result,
                "rewrite": rewrite,
                "final_catalog": final_metadata,
                "verify": verify,
                "pre_rewrite_equality_delete_admission": pre_rewrite_admission,
                "equality_delete_admission": equality_delete_admission,
                "object_inventory": inventory,
            },
            "control_plane": {
                "source_sync_advanced": False,
                "data_product_version_created": False,
                "partition_evolution": "identity(road_id)",
                "controlled_rewrite": args.controlled_rewrite,
                "delete_mode": "merge-on-read",
                "observed_provider_delete_mode": (
                    "equality-delete-after-controlled-rewrite"
                    if args.controlled_rewrite
                    else "equality-delete-evolved-spec-only"
                ),
                "writer_engine": "flink-1.19.3",
                "writer_recovery_mode": "explicit_bounded_delete",
            },
            "not_claimed": [
                "multiple equality-delete files, composite identifiers, concurrent writers, "
                "or compaction",
                "mixed-spec UPDATE/MERGE, schema evolution, or partition evolution beyond "
                "one field",
                "REST/Gravitino, production HA, Kubernetes, exactly-once, SLO/RPO/RTO",
            ],
            "capability_probe": {
                "status": (
                    "supported_after_controlled_rewrite"
                    if args.controlled_rewrite
                    else "unsupported"
                ),
                "capability": "equality-delete-after-controlled-rewrite",
                "evidence": [
                    "Flink equality-delete files were materialized with equality_ids bound to "
                    "road_id",
                    (
                        "the final table had one current partition spec before equality delete"
                        if args.controlled_rewrite
                        else "the evolved-spec revision-2 row was removed"
                    ),
                    (
                        "the legacy spec-0 row was removed by the pre-delete controlled rewrite"
                        if args.controlled_rewrite
                        else "the legacy spec-0 revision-1 row survived"
                    ),
                ],
                "provider_scope": "org.apache.iceberg.jdbc.JdbcCatalog + Iceberg "
                "Spark/Flink runtime",
            },
        }
        if report["status"] != "passed":
            raise RuntimeError(f"mixed-spec equality delete checks failed: {checks}")
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
            "schema": "gda.chongqing_osm_spark_flink_mixed_spec_equality_delete.acceptance.v1",
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
