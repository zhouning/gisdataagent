#!/usr/bin/env python3
"""Certify Spark/Flink interoperability on one real MinIO Iceberg table."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3

from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_SOURCE,
    DEFAULT_SOURCE_PRODUCT_SHA256,
    REPO_ROOT,
    _canonical_sha256,
    _sha256_file,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_postgres_cdc import build_cdc_plan
from scripts.certify_source_sync_authority import _settings

JAVA_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmIcebergInteropJob.java"
MAIN_CLASS = "ChongqingOsmIcebergInteropJob"
SPARK_MODULE = "scripts.spark_chongqing_osm_iceberg_interop"
DEFAULT_SPARK_IMAGE = "gisdataagent/mmfe-spark-runtime:local"
DEFAULT_NETWORK = "gisdataagent_agent-net"
DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/chongqing-osm-flink-iceberg-report.json"
)
BUCKET = "gis-agent-lakehouse"
PREFIX_RE = re.compile(
    r"^acceptance/flink-iceberg/gda_flink_iceberg_[0-9a-f]{10}/$"
)
BASELINE_RE = re.compile(r"GDA_ICEBERG_BASELINE rows=(\d+)")
FINAL_RE = re.compile(r"GDA_ICEBERG_FINAL rows=(\d+) appended=(\d+)")
RECOVERY_CHECKPOINT_RE = re.compile(
    r"GDA_ICEBERG_CHECKPOINT_COMPLETED id=(\d+) offset=(\d+)"
)
RECOVERY_FAILURE_RE = re.compile(
    r"GDA_ICEBERG_INTENTIONAL_FAILURE checkpoint=(\d+) offset=(\d+)"
)
RECOVERY_RESTORE_RE = re.compile(
    r"GDA_ICEBERG_SOURCE_OPEN attempt=(\d+) restored=true offset=(\d+)"
)
RECOVERY_FINISHED_RE = re.compile(r"GDA_ICEBERG_SOURCE_FINISHED offset=(\d+)")

FLINK_ICEBERG = {
    "coordinate": "org.apache.iceberg:iceberg-flink-runtime-1.19:1.7.2",
    "path": REPO_ROOT
    / ".tmp/connector-cache/iceberg-flink-runtime-1.19-1.7.2.jar",
    "bytes": 33_324_324,
    "maven_sha1": "576347c0dedd9e21e245946e3527769599edeb7d",
    "sha256": "d14239649c879910feabf0d6c97cf478466495243b2caa01630397625a26413b",
}
FLINK_AWS = {
    "coordinate": "org.apache.iceberg:iceberg-aws-bundle:1.7.2",
    "path": REPO_ROOT / ".tmp/connector-cache/iceberg-aws-bundle-1.7.2.jar",
    "bytes": 49_575_830,
    "maven_sha1": "41e743412b2af12f25896ef4a4cf41a46090d3a2",
    "sha256": "0ffa91f62084be22c5f03cdcf1d3ac4de031002b1958d1479c634cae23170526",
}
POSTGRES_JDBC = {
    "coordinate": "org.postgresql:postgresql:42.7.4",
    "path": REPO_ROOT / ".tmp/connector-cache/postgresql-42.7.4.jar",
    "bytes": 1_086_687,
    "maven_sha1": "264310fd7b2cd76738787dc0b9f7ea2e3b11adc1",
    "sha256": "188976721ead8e8627eb6d8389d500dccc0c9bebd885268a3047180274a6031e",
}
HADOOP_CLIENT_API = {
    "coordinate": "org.apache.hadoop:hadoop-client-api:3.3.4",
    "path": REPO_ROOT / ".tmp/connector-cache/hadoop-client-api-3.3.4.jar",
    "bytes": 19_458_635,
    "maven_sha1": "6339a8f7279310c8b1f7ef314b592d8c71ca72ef",
    "sha256": "e513d71b78086b5caaa439f4402b43e20df01446d56b66084ad419452878701c",
}
HADOOP_CLIENT_RUNTIME = {
    "coordinate": "org.apache.hadoop:hadoop-client-runtime:3.3.4",
    "path": REPO_ROOT / ".tmp/connector-cache/hadoop-client-runtime-3.3.4.jar",
    "bytes": 30_085_504,
    "maven_sha1": "21f7a9a2da446f1e5b3e5af16ebf956d3ee43ee0",
    "sha256": "9377a68071137ae5f5c8cdc2ed20d6f904a1df4d06df26b47ed8872a1b0d8d47",
}
SPARK_ICEBERG_SHA256 = "87e7184f31ef0caac415bbdfcf1bc4943346a58b98d747dc83434f7139e12acb"
SPARK_AWS_SHA256 = "d14a49ced66a20cbd30f73ebb379646248d784fc5cd49d7295d36524380330e3"
POSTGRES_JDBC_SHA256 = POSTGRES_JDBC["sha256"]


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()  # noqa: S324 - Maven artifact identity.
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(contract: dict[str, Any]) -> dict[str, Any]:
    path = Path(contract["path"])
    if not path.is_file():
        raise RuntimeError(f"verified artifact is missing: {contract['coordinate']}")
    evidence = {
        "coordinate": contract["coordinate"],
        "bytes": path.stat().st_size,
        "maven_sha1": _sha1_file(path),
        "sha256": _sha256_file(path),
    }
    expected = {key: contract[key] for key in evidence}
    if evidence != expected:
        raise RuntimeError(f"artifact integrity failed: {contract['coordinate']}")
    return evidence


def build_interop_plan(source_path: Path, *, commit_tag: str) -> dict[str, Any]:
    cdc = build_cdc_plan(source_path)
    baseline = [dict(row) for row in cdc["initial"]]
    append = dict(cdc["d_row"])
    final = [
        {**row, "flink_commit_tag": None}
        for row in baseline
    ] + [{**append, "flink_commit_tag": commit_tag}]
    baseline.sort(key=lambda row: row["road_id"])
    final.sort(key=lambda row: row["road_id"])
    return {
        "schema": "gda.chongqing_osm_flink_iceberg_plan.v1",
        "source": cdc["source"],
        "source_slice_sha256": cdc["source_slice_sha256"],
        "baseline_rows": baseline,
        "append_row": append,
        "final_rows": final,
        "baseline_content_sha256": _canonical_sha256(baseline),
        "final_content_sha256": _canonical_sha256(final),
        "commit_tag": commit_tag,
    }


def _run_command(
    command: list[str], *, stage: str, timeout: int
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout)[-6_000:]
        raise RuntimeError(f"{stage} failed: {details}")
    return completed


def _spark_artifacts(image: str, *, timeout: int) -> dict[str, Any]:
    paths = (
        "/opt/spark/jars-extra/iceberg-spark-runtime-3.5_2.12-1.6.1.jar",
        "/opt/spark/jars-extra/iceberg-aws-bundle-1.6.1.jar",
        "/opt/spark/jars-extra/postgresql-42.7.4.jar",
    )
    completed = _run_command(
        ["docker", "run", "--rm", image, "sha256sum", *paths],
        stage="inspect Spark Iceberg artifacts",
        timeout=timeout,
    )
    hashes = [line.split()[0] for line in completed.stdout.splitlines() if line]
    if hashes != [SPARK_ICEBERG_SHA256, SPARK_AWS_SHA256, POSTGRES_JDBC_SHA256]:
        raise RuntimeError("Spark Iceberg artifact identities do not match the frozen runtime")
    return {
        "iceberg_spark_runtime": {
            "coordinate": "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.6.1",
            "sha256": hashes[0],
        },
        "iceberg_aws_bundle": {
            "coordinate": "org.apache.iceberg:iceberg-aws-bundle:1.6.1",
            "sha256": hashes[1],
        },
        "postgresql_jdbc": {
            "coordinate": POSTGRES_JDBC["coordinate"],
            "sha256": hashes[2],
        },
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
    _run_command(command, stage=f"Spark Iceberg {phase}", timeout=args.timeout_seconds)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("phase") != phase:
        raise RuntimeError(f"Spark Iceberg {phase} returned failed evidence")
    return report


class IcebergCatalogSandbox:
    def __init__(self, *, image: str, network: str, token: str) -> None:
        self.image = image
        self.network = network
        self.container = f"gda-iceberg-pg-{token}"
        self.database = "iceberg_catalog"
        self.user = "iceberg_admin"
        self.password = secrets.token_hex(20)
        self.started = False

    @property
    def jdbc_uri(self) -> str:
        return f"jdbc:postgresql://{self.container}:5432/{self.database}"

    def start(self) -> dict[str, Any]:
        _run_command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.container,
                "--network",
                self.network,
                "-e",
                f"POSTGRES_USER={self.user}",
                "-e",
                f"POSTGRES_PASSWORD={self.password}",
                "-e",
                f"POSTGRES_DB={self.database}",
                self.image,
            ],
            stage="start isolated Iceberg JDBC catalog",
            timeout=60,
        )
        self.started = True
        for _ in range(120):
            completed = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "pg_isready",
                    "-U",
                    self.user,
                    "-d",
                    self.database,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                version = _run_command(
                    [
                        "docker",
                        "exec",
                        "-e",
                        f"PGPASSWORD={self.password}",
                        self.container,
                        "psql",
                        "-X",
                        "-U",
                        self.user,
                        "-d",
                        self.database,
                        "-At",
                        "-c",
                        "SHOW server_version;",
                    ],
                    stage="inspect Iceberg JDBC catalog",
                    timeout=30,
                ).stdout.strip()
                return {"version": version, "persistent": False}
            time.sleep(0.5)
        raise RuntimeError("isolated Iceberg JDBC catalog did not become ready")

    def cleanup(self) -> bool:
        if self.started:
            subprocess.run(
                ["docker", "rm", "-f", self.container],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        completed = subprocess.run(
            ["docker", "inspect", self.container],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return completed.returncode != 0


class FlinkIcebergSandbox:
    def __init__(
        self,
        *,
        args: argparse.Namespace,
        token: str,
        access_key: str,
        secret_key: str,
        catalog_password: str,
        extra_flink_properties: tuple[str, ...] = (),
    ) -> None:
        self.args = args
        self.container = f"gda-iceberg-flink-{token}"
        self.access_key = access_key
        self.secret_key = secret_key
        self.catalog_password = catalog_password
        self.extra_flink_properties = extra_flink_properties
        self.started = False

    def start(self) -> dict[str, int]:
        properties = "\n".join(
            (
                "jobmanager.rpc.address: localhost",
                "jobmanager.memory.process.size: 1024m",
                "taskmanager.memory.process.size: 1536m",
                "taskmanager.numberOfTaskSlots: 1",
                "parallelism.default: 1",
                "rest.bind-address: 0.0.0.0",
                *self.extra_flink_properties,
            )
        )
        _run_command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.container,
                "--network",
                self.args.docker_network,
                "-e",
                f"AWS_ACCESS_KEY_ID={self.access_key}",
                "-e",
                f"AWS_SECRET_ACCESS_KEY={self.secret_key}",
                "-e",
                "AWS_REGION=us-east-1",
                "-e",
                f"ICEBERG_CATALOG_PASSWORD={self.catalog_password}",
                "-e",
                f"FLINK_PROPERTIES={properties}",
                "-v",
                f"{REPO_ROOT}:/workspace",
                "-v",
                f"{FLINK_ICEBERG['path']}:/opt/flink/lib/{Path(FLINK_ICEBERG['path']).name}:ro",
                "-v",
                f"{FLINK_AWS['path']}:/opt/flink/lib/{Path(FLINK_AWS['path']).name}:ro",
                "-v",
                f"{POSTGRES_JDBC['path']}:/opt/flink/lib/{Path(POSTGRES_JDBC['path']).name}:ro",
                "-v",
                f"{HADOOP_CLIENT_API['path']}:/opt/flink/lib/{Path(HADOOP_CLIENT_API['path']).name}:ro",
                "-v",
                f"{HADOOP_CLIENT_RUNTIME['path']}:/opt/flink/lib/{Path(HADOOP_CLIENT_RUNTIME['path']).name}:ro",
                self.args.flink_image,
                "bash",
                "-lc",
                "/opt/flink/bin/start-cluster.sh && exec sleep infinity",
            ],
            stage="start isolated Flink Iceberg cluster",
            timeout=60,
        )
        self.started = True
        for _ in range(120):
            completed = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "curl",
                    "-fsS",
                    "http://localhost:8081/overview",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                overview = json.loads(completed.stdout)
                if int(overview.get("taskmanagers", 0)) == 1:
                    return {
                        "taskmanagers": 1,
                        "slots_total": int(overview["slots-total"]),
                    }
            time.sleep(0.5)
        raise RuntimeError("isolated Flink Iceberg cluster did not become ready")

    def run(
        self,
        *,
        jar_path: Path,
        warehouse_uri: str,
        table: str,
        plan: dict[str, Any],
        catalog_uri: str,
        catalog_user: str,
    ) -> dict[str, Any]:
        row = plan["append_row"]
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "flink",
                "run",
                "-p",
                "1",
                f"/workspace/{jar_path.relative_to(REPO_ROOT).as_posix()}",
                "--warehouse-uri",
                warehouse_uri,
                "--endpoint-url",
                self.args.container_endpoint_url,
                "--catalog-uri",
                catalog_uri,
                "--catalog-user",
                catalog_user,
                "--table",
                table,
                "--expected-baseline-rows",
                str(len(plan["baseline_rows"])),
                "--road-id",
                str(row["road_id"]),
                "--revision",
                str(row["revision"]),
                "--road-name-base64",
                row["road_name_base64"],
                "--geometry-sha256",
                row["geometry_sha256"],
                "--commit-tag",
                plan["commit_tag"],
            ],
            stage="run Flink Iceberg interoperability job",
            timeout=self.args.timeout_seconds,
        )
        baseline = BASELINE_RE.search(completed.stdout)
        final = FINAL_RE.search(completed.stdout)
        if not baseline or not final:
            raise RuntimeError("Flink Iceberg job did not emit reconciliation markers")
        return {
            "baseline_rows": int(baseline.group(1)),
            "final_rows": int(final.group(1)),
            "appended_rows": int(final.group(2)),
        }

    def run_recovery(
        self,
        *,
        jar_path: Path,
        warehouse_uri: str,
        table: str,
        input_path: Path,
        checkpoint_path: Path,
        catalog_uri: str,
        catalog_user: str,
    ) -> dict[str, Any]:
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "flink",
                "run",
                "-p",
                "1",
                f"/workspace/{jar_path.relative_to(REPO_ROOT).as_posix()}",
                "--warehouse-uri",
                warehouse_uri,
                "--endpoint-url",
                self.args.container_endpoint_url,
                "--catalog-uri",
                catalog_uri,
                "--catalog-user",
                catalog_user,
                "--table",
                table,
                "--input",
                f"/workspace/{input_path.relative_to(REPO_ROOT).as_posix()}",
                "--checkpoints",
                f"file:///workspace/{checkpoint_path.relative_to(REPO_ROOT).as_posix()}",
                "--expected-records",
                "4",
                "--fail-after-offset",
                "2",
            ],
            stage="run Flink Iceberg recovery job",
            timeout=self.args.timeout_seconds,
        )
        if "GDA_ICEBERG_RECOVERY_JOB_COMPLETED records=4" not in completed.stdout:
            raise RuntimeError("Flink Iceberg recovery job did not complete")
        task_output = self.task_output()
        checkpoints = [
            {"checkpoint_id": int(item[0]), "source_offset": int(item[1])}
            for item in RECOVERY_CHECKPOINT_RE.findall(task_output)
        ]
        failure = RECOVERY_FAILURE_RE.search(task_output)
        restore = RECOVERY_RESTORE_RE.search(task_output)
        finished = RECOVERY_FINISHED_RE.search(task_output)
        checks = {
            "checkpoint_completed_before_failure": bool(
                failure
                and any(
                    item["checkpoint_id"] == int(failure.group(1))
                    and item["source_offset"] == 2
                    for item in checkpoints
                )
                and int(failure.group(2)) == 2
            ),
            "source_restored_at_exact_offset": bool(
                restore
                and int(restore.group(1)) >= 1
                and int(restore.group(2)) == 2
            ),
            "recovered_source_completed": bool(
                finished
                and int(finished.group(1)) == 4
                and any(item["source_offset"] == 4 for item in checkpoints)
            ),
        }
        return {
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "checkpoints": checkpoints,
            "failure": {
                "checkpoint_id": int(failure.group(1)),
                "source_offset": int(failure.group(2)),
            }
            if failure
            else None,
            "restore": {
                "attempt": int(restore.group(1)),
                "source_offset": int(restore.group(2)),
            }
            if restore
            else None,
            "finished_offset": int(finished.group(1)) if finished else None,
        }

    def task_output(self) -> str:
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "bash",
                "-lc",
                "cat /opt/flink/log/*taskexecutor*.out",
            ],
            stage="read Flink Iceberg task evidence",
            timeout=30,
        )
        return completed.stdout

    def cleanup(self) -> bool:
        if self.started:
            subprocess.run(
                ["docker", "rm", "-f", self.container],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        completed = subprocess.run(
            ["docker", "inspect", self.container],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return completed.returncode != 0


def _object_inventory(client, prefix: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    continuation: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": BUCKET, "Prefix": prefix}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        response = client.list_objects_v2(**kwargs)
        items.extend(
            {
                "key": item["Key"],
                "bytes": int(item["Size"]),
                "etag": item["ETag"].strip('"'),
            }
            for item in response.get("Contents", ())
        )
        if not response.get("IsTruncated"):
            break
        continuation = response["NextContinuationToken"]
    items.sort(key=lambda item: item["key"])
    return {
        "object_count": len(items),
        "manifest_sha256": _canonical_sha256(items),
        "metadata_json_count": sum(item["key"].endswith(".metadata.json") for item in items),
        "manifest_avro_count": sum(item["key"].endswith(".avro") for item in items),
        "data_parquet_count": sum(item["key"].endswith(".parquet") for item in items),
    }


def _cleanup_prefix(client, prefix: str) -> dict[str, Any]:
    if not PREFIX_RE.fullmatch(prefix):
        raise RuntimeError("refusing to clean an unsafe Flink Iceberg prefix")
    removed = 0
    while True:
        response = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        objects = [{"Key": item["Key"]} for item in response.get("Contents", ())]
        if not objects:
            break
        client.delete_objects(Bucket=BUCKET, Delete={"Objects": objects, "Quiet": True})
        removed += len(objects)
    remaining = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("KeyCount", 0)
    return {"objects_removed": removed, "object_prefix_empty": remaining == 0}


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
    parser.add_argument("--timeout-seconds", type=int, default=240)
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
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / f"flink_iceberg_{token}"
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
    report: dict[str, Any] | None = None
    error: str | None = None
    cleanup: dict[str, Any] = {}
    flink: FlinkIcebergSandbox | None = None
    catalog: IcebergCatalogSandbox | None = None
    work_dir.mkdir(parents=True, exist_ok=False)
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
        plan = build_interop_plan(args.source, commit_tag=run_id)
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
        flink_result = flink.run(
            jar_path=jar_path,
            warehouse_uri=warehouse_uri,
            table=table,
            plan=plan,
            catalog_uri=catalog.jdbc_uri,
            catalog_user=catalog.user,
        )
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
        inventory = _object_inventory(client, prefix)
        checks = {
            "real_chongqing_osm_source_bound": (
                plan["source"]["source_feature_count"] == 50_366
                and plan["source"]["source_product_sha256"]
                == DEFAULT_SOURCE_PRODUCT_SHA256
            ),
            "supply_chain_artifacts_verified": True,
            "spark_iceberg_1_6_1_baseline_passed": all(baseline["checks"].values()),
            "flink_1_19_iceberg_1_7_2_read_evolve_write_passed": flink_result
            == {"baseline_rows": 3, "final_rows": 4, "appended_rows": 1},
            "spark_iceberg_1_6_1_reverse_read_and_time_travel_passed": all(
                verify["checks"].values()
            ),
            "iceberg_object_graph_materialized": (
                inventory["metadata_json_count"] >= 3
                and inventory["manifest_avro_count"] >= 4
                and inventory["data_parquet_count"] >= 2
            ),
        }
        report = {
            "schema": "gda.chongqing_osm_flink_iceberg_interop.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "source_slice_sha256": plan["source_slice_sha256"],
                "baseline_content_sha256": plan["baseline_content_sha256"],
                "final_content_sha256": plan["final_content_sha256"],
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
            "table": {
                "catalog": "jdbc",
                "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
                "warehouse_scope": "isolated-minio-prefix",
                "spark_baseline": baseline,
                "flink": flink_result,
                "spark_verify": verify,
                "object_inventory": inventory,
            },
            "correlation": {"run_id": run_id},
            "not_claimed": [
                "streaming checkpoint recovery into Iceberg",
                "cancel or uncertain commit reconciliation",
                "cross-engine concurrent write isolation",
                "cross-system exactly-once transaction",
                "Gravitino or REST catalog interoperability",
                "production throughput, freshness, HA, or Kubernetes runtime",
            ],
        }
        if report["status"] != "passed":
            raise RuntimeError(f"Flink Iceberg checks failed: {checks}")
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}"
        catalog_password = catalog.password if catalog is not None else ""
        for value in (access_key, secret_key, catalog_password):
            if not value:
                continue
            safe = safe.replace(value, "<redacted>")
        error = safe
    finally:
        if flink is not None:
            cleanup["flink_container_removed"] = flink.cleanup()
        else:
            cleanup["flink_container_removed"] = True
        if catalog is not None:
            cleanup["catalog_container_removed"] = catalog.cleanup()
        else:
            cleanup["catalog_container_removed"] = True
        cleanup.update(_cleanup_prefix(client, prefix))
        shutil.rmtree(work_dir, ignore_errors=True)
        cleanup["work_directory_removed"] = not work_dir.exists()
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_flink_iceberg_interop.acceptance.v1",
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
