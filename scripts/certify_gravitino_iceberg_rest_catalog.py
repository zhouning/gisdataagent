#!/usr/bin/env python3
"""Certify Spark Iceberg data-plane access through Gravitino REST catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from data_agent.iceberg_architecture_harvester import (
    IcebergArchitectureTarget,
    harvest_gravitino_iceberg_table,
)
from scripts.certify_chongqing_osm_flink_iceberg_interop import (
    DEFAULT_SPARK_IMAGE,
    IcebergCatalogSandbox,
    _spark_artifacts,
    docker_image_id,
)
from scripts.certify_chongqing_osm_flink_stream import DEFAULT_JAVA_HOME
from scripts.certify_iceberg_architecture_observation import _record_ledger
from scripts.certify_object_storage_architecture_observation import (
    DEFAULT_IMAGE as DEFAULT_MINIO_IMAGE,
)
from scripts.certify_object_storage_architecture_observation import (
    _TemporaryMinio,
    _TemporaryPostgres,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAVITINO_IMAGE = "gda/gravitino:1.3.0-local-arm64"
DEFAULT_POSTGRES_IMAGE = "postgres:16-alpine"
DEFAULT_REPORT = REPO_ROOT / ".tmp/gravitino-rest/acceptance-report.json"


def _run(command: list[str], *, stage: str, timeout: int) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr + "\n" + completed.stdout)[-8_000:]
        raise RuntimeError(f"{stage} failed: {detail}")
    return completed


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GravitinoRestSandbox:
    def __init__(
        self,
        *,
        image: str,
        network: str,
        token: str,
        catalog: IcebergCatalogSandbox,
        minio: _TemporaryMinio,
        warehouse_uri: str,
    ) -> None:
        self.image = image
        self.network = network
        self.token = token
        self.catalog = catalog
        self.minio = minio
        self.warehouse_uri = warehouse_uri
        self.container = f"gda-iceberg-rest-{token}"
        self.entity_volume = f"gda-iceberg-rest-entity-{token}"
        self.host_port: int | None = None
        self.rest_host_port: int | None = None
        self.started = False

    @property
    def rest_uri_inside_network(self) -> str:
        return "http://gravitino:9001/iceberg"

    def start(self, *, timeout: int) -> dict[str, Any]:
        _run(
            ["docker", "volume", "create", self.entity_volume],
            stage="create Gravitino entity volume",
            timeout=30,
        )
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0",
                "--entrypoint",
                "/bin/sh",
                "-v",
                f"{self.entity_volume}:/var/lib/gda",
                self.image,
                "-c",
                "chown -R 1000:0 /var/lib/gda",
            ],
            stage="prepare Gravitino entity volume",
            timeout=60,
        )
        config_lines = [
            "gravitino.entity.store.relational.jdbcUrl = jdbc:h2:file:/var/lib/gda/entity-store",
            "gravitino.iceberg-rest.catalog-backend = jdbc",
            "gravitino.iceberg-rest.jdbc-driver = org.postgresql.Driver",
            f"gravitino.iceberg-rest.uri = {self.catalog.jdbc_uri}",
            f"gravitino.iceberg-rest.jdbc-user = {self.catalog.user}",
            f"gravitino.iceberg-rest.jdbc-password = {self.catalog.password}",
            "gravitino.iceberg-rest.jdbc-initialize = true",
            f"gravitino.iceberg-rest.warehouse = {self.warehouse_uri}",
            "gravitino.iceberg-rest.io-impl = org.apache.iceberg.aws.s3.S3FileIO",
            f"gravitino.iceberg-rest.s3-access-key-id = {self.minio.access_key}",
            f"gravitino.iceberg-rest.s3-secret-access-key = {self.minio.secret_key}",
            "gravitino.iceberg-rest.s3-endpoint = http://minio:9000",
            "gravitino.iceberg-rest.s3-path-style-access = true",
            "gravitino.iceberg-rest.s3-region = us-east-1",
        ]
        shell = (
            "cp -a /opt/gravitino/conf /tmp/gda-conf; "
            "cp /opt/gravitino/catalogs/glue/libs/*-2.31.73.jar "
            "/opt/gravitino/iceberg-rest-server/libs/; "
            "cp /opt/gravitino/catalogs/glue/libs/reactive-streams-1.0.4.jar "
            "/opt/gravitino/iceberg-rest-server/libs/; "
            "cp /tmp/gda-postgresql.jar /opt/gravitino/iceberg-rest-server/libs/; "
            "printf '%s\\n' "
            + " ".join(f"'{line}'" for line in config_lines)
            + " >> /tmp/gda-conf/gravitino.conf; "
            "exec /opt/gravitino/bin/gravitino.sh --config /tmp/gda-conf run"
        )
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.container,
                "--network",
                self.network,
                "--network-alias",
                "gravitino",
                "--publish",
                "127.0.0.1::8090",
                "--publish",
                "127.0.0.1::9001",
                "--volume",
                f"{self.entity_volume}:/var/lib/gda",
                "--volume",
                (
                    f"{REPO_ROOT / '.tmp/connector-cache/postgresql-42.7.4.jar'}"
                    ":/tmp/gda-postgresql.jar:ro"
                ),
                self.image,
                "sh",
                "-lc",
                shell,
            ],
            stage="start Gravitino REST catalog",
            timeout=60,
        )
        self.started = True
        last_probe: dict[str, Any] = {}
        for _ in range(120):
            state = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    self.container,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if state.returncode != 0 or state.stdout.strip() != "true":
                logs = subprocess.run(
                    ["docker", "logs", "--tail=160", self.container],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                detail = (logs.stdout + logs.stderr)[-8_000:]
                raise RuntimeError(
                    f"Gravitino REST catalog exited before readiness: {detail}"
                )
            port = _run(
                ["docker", "port", self.container, "8090/tcp"],
                stage="inspect Gravitino HTTP port",
                timeout=15,
            ).stdout.strip()
            rest_port = _run(
                ["docker", "port", self.container, "9001/tcp"],
                stage="inspect Gravitino REST port",
                timeout=15,
            ).stdout.strip()
            if port and rest_port:
                self.host_port = int(port.rsplit(":", 1)[-1])
                self.rest_host_port = int(rest_port.rsplit(":", 1)[-1])
                try:
                    health = httpx.get(
                        f"http://127.0.0.1:{self.host_port}/health", timeout=2
                    )
                    config = httpx.get(
                        f"http://127.0.0.1:{self.rest_host_port}/iceberg/v1/config",
                        timeout=2,
                    )
                    last_probe = {
                        "health_status": health.status_code,
                        "health_body": health.text[:500],
                        "rest_config_status": config.status_code,
                        "rest_config_body": config.text[:500],
                    }
                    if health.is_success and config.is_success:
                        payload = config.json()
                        return {
                            "main_health_status": health.status_code,
                            "rest_config_status": config.status_code,
                            "rest_endpoints": payload.get("endpoints", []),
                            "host_port": self.host_port,
                            "rest_host_port": self.rest_host_port,
                        }
                except (httpx.HTTPError, ValueError):
                    pass
            time.sleep(1)
        logs = subprocess.run(
            ["docker", "logs", "--tail=160", self.container],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        raise RuntimeError(
            "Gravitino REST catalog did not become ready: "
            + json.dumps(last_probe, ensure_ascii=True)
            + "\n"
            + (logs.stdout + logs.stderr)[-8_000:]
        )

    def cleanup(self) -> dict[str, bool]:
        subprocess.run(
            ["docker", "rm", "-f", self.container],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        container_absent = subprocess.run(
            ["docker", "inspect", self.container],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).returncode != 0
        subprocess.run(
            ["docker", "volume", "rm", self.entity_volume],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        volume_absent = subprocess.run(
            ["docker", "volume", "inspect", self.entity_volume],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).returncode != 0
        return {
            "gravitino_container_absent": container_absent,
            "gravitino_entity_volume_absent": volume_absent,
        }

    def logs(self) -> str:
        completed = subprocess.run(
            [
                "docker",
                "exec",
                self.container,
                "sh",
                "-lc",
                "find /opt/gravitino/logs -maxdepth 1 -type f -print "
                "-exec sh -c 'echo --- $1; tail -240 \"$1\"' sh {} \\;",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        docker_logs = subprocess.run(
            ["docker", "logs", "--tail=240", self.container],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        details = (
            completed.stdout
            + completed.stderr
            + docker_logs.stdout
            + docker_logs.stderr
        )
        return details[-24_000:]


def run_acceptance(
    *,
    report_path: Path,
    gravitino_image: str = DEFAULT_GRAVITINO_IMAGE,
    minio_image: str = DEFAULT_MINIO_IMAGE,
    postgres_image: str = DEFAULT_POSTGRES_IMAGE,
    spark_image: str = DEFAULT_SPARK_IMAGE,
    timeout_seconds: int = 360,
) -> dict[str, Any]:
    token = secrets.token_hex(5)
    prefix = f"acceptance/gravitino-rest/gda_rest_{token}/"
    warehouse_uri = f"s3://gis-agent-lakehouse/{prefix}warehouse"
    table = f"rest.gda_rest_{token}.chongqing_osm_roads"
    work_dir = REPO_ROOT / ".tmp/gravitino-rest" / f"run-{token}"
    spark_report_path = work_dir / "spark-report.json"
    minio = _TemporaryMinio(minio_image)
    minio.bucket = "gis-agent-lakehouse"
    catalog: IcebergCatalogSandbox | None = None
    gravitino: GravitinoRestSandbox | None = None
    control: _TemporaryPostgres | None = None
    report: dict[str, Any] | None = None
    cleanup: dict[str, bool] = {}
    try:
        work_dir.mkdir(parents=True, exist_ok=False)
        minio.start()
        catalog = IcebergCatalogSandbox(
            image=postgres_image,
            network=minio.network,
            token=token,
        )
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
        try:
            _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    minio.network,
                    "-e",
                    f"JAVA_HOME={DEFAULT_JAVA_HOME}",
                    "-e",
                    f"AWS_ACCESS_KEY_ID={minio.access_key}",
                    "-e",
                    f"AWS_SECRET_ACCESS_KEY={minio.secret_key}",
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
                    spark_image,
                    "python",
                    "-m",
                    "scripts.spark_gravitino_iceberg_rest_acceptance",
                    "--table",
                    table,
                    "--report",
                    f"/workspace/{spark_report_path.relative_to(REPO_ROOT).as_posix()}",
                ],
                stage="run Spark through Gravitino Iceberg REST catalog",
                timeout=timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                f"{exc}\nGravitino server logs:\n{gravitino.logs()}"
            ) from exc
        spark_report = json.loads(spark_report_path.read_text(encoding="utf-8"))
        table_parts = table.split(".")
        final_content_sha256 = spark_report["final"]["content_sha256"]
        architecture_observation = spark_report["architecture_harvest"]["observation"]
        target = IcebergArchitectureTarget(
            tenant_id="gravitino-rest-acceptance",
            resource_urn="gda://gravitino-rest-acceptance/dataset/chongqing_osm_roads",
            resource_version_id=architecture_observation["resource_version_id"],
            metalake="rest",
            catalog="default_catalog",
            namespace=table_parts[1],
            object_name=table_parts[2],
            snapshot_ref=f"iceberg-table:{table}",
            content_checksum=final_content_sha256,
        )
        observed_at = datetime.fromisoformat(architecture_observation["observed_at"])
        harvest = harvest_gravitino_iceberg_table(
            spark_report["rest"]["table"],
            target,
            observed_by="workload:gravitino-rest-acceptance",
            observed_at=observed_at,
        )
        control = _TemporaryPostgres(postgres_image)
        control.start()
        ledger = _record_ledger(
            postgres=control,
            target=target,
            harvest=harvest,
            actor="workload:gravitino-rest-acceptance",
        )
        checks = {
            "gravitino_rest_ready": rest_evidence["rest_config_status"] == 200,
            "spark_rest_catalog_passed": spark_report.get("status") == "passed",
            **{
                f"spark_{key}": value
                for key, value in spark_report.get("checks", {}).items()
            },
            **{f"ledger_{key}": value for key, value in ledger["checks"].items()},
        }
        report = {
            "schema": "gda.gravitino_iceberg_rest.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "provider": {
                "gravitino_image": gravitino_image,
                "gravitino_image_id": docker_image_id(
                    gravitino_image, timeout=timeout_seconds
                ),
                "spark_image": spark_image,
                "spark_artifacts": spark_artifacts,
                "catalog": catalog_evidence,
                "catalog_backend": "jdbc",
                "rest_uri": "http://gravitino:9001/iceberg",
                "rest_evidence": rest_evidence,
            },
            "table": table,
            "warehouse_uri": warehouse_uri,
            "spark": spark_report,
            "ledger": ledger,
            "checks": checks,
            "not_claimed": [
                "Flink through Gravitino REST catalog",
                "production Gravitino REST to GDA architecture ledger binding",
                "production HA, backup/restore, RPO/RTO or cross-region replication",
                "multi-table and multi-parallelism conformance",
            ],
        }
    finally:
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
        raise RuntimeError("Gravitino REST acceptance did not produce a report")
    report["cleanup"] = cleanup
    report["status"] = (
        "passed" if report["status"] == "passed" and all(cleanup.values()) else "failed"
    )
    report["report_sha256"] = _sha256(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--gravitino-image", default=DEFAULT_GRAVITINO_IMAGE)
    parser.add_argument("--minio-image", default=DEFAULT_MINIO_IMAGE)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--spark-image", default=DEFAULT_SPARK_IMAGE)
    parser.add_argument("--timeout-seconds", type=int, default=360)
    args = parser.parse_args()
    report = run_acceptance(
        report_path=args.report,
        gravitino_image=args.gravitino_image,
        minio_image=args.minio_image,
        postgres_image=args.postgres_image,
        spark_image=args.spark_image,
        timeout_seconds=args.timeout_seconds,
    )
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
