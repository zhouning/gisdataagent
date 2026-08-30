#!/usr/bin/env python3
"""Certify Flink Iceberg writes through the Gravitino REST catalog."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from data_agent.iceberg_architecture_harvester import (
    IcebergArchitectureTarget,
    harvest_gravitino_iceberg_table,
)
from data_agent.platform_contracts import canonical_json_fingerprint
from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    DEFAULT_SPARK_IMAGE,
    FLINK_AWS,
    FLINK_ICEBERG,
    HADOOP_CLIENT_API,
    HADOOP_CLIENT_RUNTIME,
    JAVA_SOURCE,
    MAIN_CLASS,
    POSTGRES_JDBC,
    FlinkIcebergSandbox,
    IcebergCatalogSandbox,
    _spark_artifacts,
    build_interop_plan,
    verify_artifact,
)
from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_SOURCE,
    compile_flink_job,
)
from scripts.certify_gravitino_iceberg_rest_catalog import (
    DEFAULT_GRAVITINO_IMAGE,
    DEFAULT_POSTGRES_IMAGE,
    GravitinoRestSandbox,
    _run,
)
from scripts.certify_iceberg_architecture_observation import _record_ledger
from scripts.certify_object_storage_architecture_observation import (
    DEFAULT_IMAGE as DEFAULT_MINIO_IMAGE,
)
from scripts.certify_object_storage_architecture_observation import (
    _TemporaryMinio,
    _TemporaryPostgres,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/gravitino-rest/flink-acceptance-report.json"


def _spark_phase(
    *,
    image: str,
    network: str,
    table: str,
    report: Path,
    mode: str,
    access_key: str,
    secret_key: str,
    plan_path: Path | None = None,
    commit_tag: str = "rest_catalog_acceptance",
) -> None:
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "-e",
        f"JAVA_HOME={DEFAULT_JAVA_HOME}",
        "-e",
        f"AWS_ACCESS_KEY_ID={access_key}",
        "-e",
        f"AWS_SECRET_ACCESS_KEY={secret_key}",
        "-e",
        "AWS_REGION=us-east-1",
        "-e",
        "GRAVITINO_ICEBERG_REST_URI=http://gravitino:9001/iceberg",
        "-e",
        "GRAVITINO_ICEBERG_REST_PREFIX=default_catalog",
        "-v",
        f"{REPO_ROOT}:/workspace",
        "-w",
        "/workspace",
        image,
        "python",
        "-m",
        "scripts.spark_gravitino_iceberg_rest_acceptance",
        "--table",
        table,
        "--report",
        f"/workspace/{report.relative_to(REPO_ROOT).as_posix()}",
        f"--commit-tag={commit_tag}",
        f"--{mode}-only",
    ]
    if plan_path is not None:
        command.extend(("--plan", f"/workspace/{plan_path.relative_to(REPO_ROOT).as_posix()}"))
    _run(command, stage=f"Spark REST {mode}", timeout=300)


def run_acceptance(
    *,
    report_path: Path,
    gravitino_image: str = DEFAULT_GRAVITINO_IMAGE,
    minio_image: str = DEFAULT_MINIO_IMAGE,
    postgres_image: str = DEFAULT_POSTGRES_IMAGE,
    spark_image: str = DEFAULT_SPARK_IMAGE,
    flink_image: str = DEFAULT_FLINK_IMAGE,
    jdk_image: str = DEFAULT_JDK_IMAGE,
    timeout_seconds: int = 420,
) -> dict:
    token = secrets.token_hex(5)
    namespace = f"gda_rest_{token}"
    # The engines use local catalog aliases; namespace and object remain shared.
    spark_table = f"rest.{namespace}.chongqing_osm_roads"
    flink_table = f"lakehouse.{namespace}.chongqing_osm_roads"
    warehouse_uri = f"s3://gis-agent-lakehouse/acceptance/gravitino-rest/{namespace}/warehouse"
    work_dir = REPO_ROOT / ".tmp/gravitino-rest" / f"flink-run-{token}"
    spark_prepare_path = work_dir / "spark-prepare.json"
    spark_verify_path = work_dir / "spark-verify.json"
    minio = _TemporaryMinio(minio_image)
    minio.bucket = "gis-agent-lakehouse"
    catalog: IcebergCatalogSandbox | None = None
    gravitino: GravitinoRestSandbox | None = None
    flink: FlinkIcebergSandbox | None = None
    control: _TemporaryPostgres | None = None
    report: dict | None = None
    cleanup: dict[str, bool] = {}
    commit_tag = "flink_gravitino_rest_acceptance"
    try:
        work_dir.mkdir(parents=True, exist_ok=False)
        plan = build_interop_plan(DEFAULT_SOURCE, commit_tag=commit_tag)
        plan_path = work_dir / "interop-plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        minio.start()
        catalog = IcebergCatalogSandbox(image=postgres_image, network=minio.network, token=token)
        catalog_evidence = catalog.start()
        gravitino = GravitinoRestSandbox(
            image=gravitino_image,
            network=minio.network,
            token=token,
            catalog=catalog,
            minio=minio,
            warehouse_uri=warehouse_uri,
        )
        rest_evidence = gravitino.start(timeout=timeout_seconds)
        spark_artifacts = _spark_artifacts(spark_image, timeout=timeout_seconds)
        _spark_phase(
            image=spark_image,
            network=minio.network,
            table=spark_table,
            report=spark_prepare_path,
            mode="prepare",
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            plan_path=plan_path,
            commit_tag=commit_tag,
        )
        spark_prepare = json.loads(spark_prepare_path.read_text(encoding="utf-8"))
        jar_path = compile_flink_job(
            work_dir=work_dir,
            flink_image=flink_image,
            jdk_image=jdk_image,
            java_home=DEFAULT_JAVA_HOME,
            timeout=timeout_seconds,
            java_source=JAVA_SOURCE,
            main_class=MAIN_CLASS,
        )
        args = SimpleNamespace(
            docker_network=minio.network,
            flink_image=flink_image,
            container_endpoint_url="http://minio:9000",
            timeout_seconds=timeout_seconds,
        )
        flink = FlinkIcebergSandbox(
            args=args,
            token=token,
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            catalog_password="anonymous",
        )
        flink_cluster = flink.start()
        flink_result = flink.run(
            jar_path=jar_path,
            warehouse_uri=warehouse_uri,
            table=flink_table,
            plan=plan,
            catalog_uri="http://gravitino:9001/iceberg",
            catalog_user="anonymous",
            catalog_mode="rest",
            catalog_prefix="default_catalog",
        )
        _spark_phase(
            image=spark_image,
            network=minio.network,
            table=spark_table,
            report=spark_verify_path,
            mode="verify",
            access_key=minio.access_key,
            secret_key=minio.secret_key,
            plan_path=plan_path,
            commit_tag=commit_tag,
        )
        spark_verify = json.loads(spark_verify_path.read_text(encoding="utf-8"))
        observation = spark_verify["architecture_harvest"]["observation"]
        target = IcebergArchitectureTarget(
            tenant_id=observation["tenant_id"],
            resource_urn=f"gda://{observation['tenant_id']}/dataset/chongqing_osm_roads",
            resource_version_id=UUID(observation["resource_version_id"]),
            metalake="rest",
            catalog="default_catalog",
            namespace=namespace,
            object_name="chongqing_osm_roads",
            snapshot_ref=f"iceberg-table:{spark_table}",
            content_checksum=spark_verify["final"]["content_sha256"],
        )
        harvest = harvest_gravitino_iceberg_table(
            spark_verify["rest"]["table"],
            target,
            observed_by="workload:gravitino-rest-flink-acceptance",
            observed_at=datetime.now(UTC),
        )
        control = _TemporaryPostgres(postgres_image)
        control.start()
        ledger = _record_ledger(
            postgres=control,
            target=target,
            harvest=harvest,
            actor="workload:gravitino-rest-flink-acceptance",
        )
        checks = {
            "gravitino_rest_ready": rest_evidence["rest_config_status"] == 200,
            "spark_prepare_passed": spark_prepare.get("status") == "passed",
            "flink_rest_append_passed": flink_result
            == {"baseline_rows": 3, "final_rows": 4, "appended_rows": 1},
            "spark_verify_passed": spark_verify.get("status") == "passed",
            **{f"spark_{key}": value for key, value in spark_verify.get("checks", {}).items()},
            **{f"ledger_{key}": value for key, value in ledger["checks"].items()},
        }
        report = {
            "schema": "gda.gravitino_iceberg_rest.flink_acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "table": spark_table,
            "flink_table": flink_table,
            "warehouse_uri": warehouse_uri,
            "provider": {
                "gravitino_image": gravitino_image,
                "spark_image": spark_image,
                "flink_image": flink_image,
                "catalog_backend": "jdbc",
                "catalog_evidence": catalog_evidence,
                "rest_evidence": rest_evidence,
                "spark_artifacts": spark_artifacts,
                "flink_artifacts": {
                    "iceberg": verify_artifact(FLINK_ICEBERG),
                    "aws": verify_artifact(FLINK_AWS),
                    "postgresql": verify_artifact(POSTGRES_JDBC),
                    "hadoop_api": verify_artifact(HADOOP_CLIENT_API),
                    "hadoop_runtime": verify_artifact(HADOOP_CLIENT_RUNTIME),
                },
            },
            "spark_prepare": spark_prepare,
            "flink": {"cluster": flink_cluster, "result": flink_result},
            "spark_verify": spark_verify,
            "ledger": ledger,
            "checks": checks,
            "not_claimed": [
                "production Flink/Gravitino REST HA and workload identity",
                "production metadata fabric binding and backup/restore",
                "multi-table and multi-parallelism conformance",
            ],
        }
    finally:
        if flink is not None:
            cleanup["flink_container_absent"] = flink.cleanup()
        else:
            cleanup["flink_container_absent"] = True
        if gravitino is not None:
            cleanup.update(gravitino.cleanup())
        if catalog is not None:
            cleanup["catalog_container_absent"] = catalog.cleanup()
        else:
            cleanup["catalog_container_absent"] = True
        if control is not None:
            cleanup["control_postgres_container_absent"] = control.stop_and_verify()
        else:
            cleanup["control_postgres_container_absent"] = True
        cleanup["bucket_absent"] = minio.delete_all_versions()
        cleanup.update(minio.stop_and_verify())
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_absent"] = not work_dir.exists()
    if report is None:
        raise RuntimeError("Flink Gravitino REST acceptance did not produce a report")
    report["cleanup"] = cleanup
    report["status"] = (
        "passed"
        if report["status"] == "passed" and all(cleanup.values())
        else "failed"
    )
    report["report_sha256"] = canonical_json_fingerprint(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    args = parser.parse_args()
    report = run_acceptance(report_path=args.report, timeout_seconds=args.timeout_seconds)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": report["cleanup"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
