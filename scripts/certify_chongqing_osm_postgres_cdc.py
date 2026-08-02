#!/usr/bin/env python3
"""Certify PostgreSQL logical CDC, Flink recovery, and SourceSync replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from data_agent.connectors.database import _connection_url
from data_agent.platform_contracts import (
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_sync_authority import SourceSyncAuthority
from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_SOURCE,
    DEFAULT_SOURCE_PRODUCT_SHA256,
    REPO_ROOT,
    _canonical_sha256,
    _committed_lines,
    _sha256_file,
    build_event_slice,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_incremental_sync import _main_sync_counts
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _definition_registration,
    _PostgresDatabaseSandbox,
    _run,
    _settings,
    _submit_run,
)

JAVA_SOURCE = REPO_ROOT / "scripts/flink/ChongqingOsmPostgresCdcJob.java"
MAIN_CLASS = "ChongqingOsmPostgresCdcJob"
DEFAULT_CONNECTOR = (
    REPO_ROOT
    / ".tmp/connector-cache/flink-sql-connector-postgres-cdc-3.3.0.jar"
)
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp/source-sync-certification/chongqing-osm-postgres-cdc-report.json"
)
DEFAULT_POSTGRES_IMAGE = "postgres:16-alpine"
DEFAULT_NETWORK = "gisdataagent_agent-net"
CONNECTOR_COORDINATE = "org.apache.flink:flink-sql-connector-postgres-cdc:3.3.0"
CONNECTOR_SHA1 = "a44e29908024ab34ee9923759ef9f26cde67a2f8"
CONNECTOR_SHA256 = "e47ae8276a4acc10d77325f2a919f445a306d35184e11dcef969f692dbb28002"
CONNECTOR_BYTES = 19_541_037
CONTAINER_RE = re.compile(r"^gda-cdc-(?:pg|flink)-[0-9a-f]{10}$")
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
JOB_ID_RE = re.compile(r"\b([0-9a-f]{32})\b")
CHECKPOINT_RE = re.compile(r"GDA_CDC_CHECKPOINT_COMPLETED id=(\d+) count=(\d+)")
FAILURE_RE = re.compile(r"GDA_CDC_INTENTIONAL_FAILURE checkpoint=(\d+) count=(\d+)")
RESTORE_RE = re.compile(r"GDA_CDC_PROCESS_OPEN attempt=(\d+) restored=true count=(\d+)")


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()  # noqa: S324 - Maven publication integrity identity.
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_connector_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError("verified PostgreSQL CDC connector artifact is missing")
    evidence = {
        "coordinate": CONNECTOR_COORDINATE,
        "bytes": path.stat().st_size,
        "maven_sha1": _sha1_file(path),
        "sha256": _sha256_file(path),
    }
    if evidence != {
        "coordinate": CONNECTOR_COORDINATE,
        "bytes": CONNECTOR_BYTES,
        "maven_sha1": CONNECTOR_SHA1,
        "sha256": CONNECTOR_SHA256,
    }:
        raise RuntimeError("PostgreSQL CDC connector artifact failed integrity checks")
    return evidence


def build_cdc_plan(source_path: Path) -> dict[str, Any]:
    events, source = build_event_slice(source_path)
    a_insert, b_insert, c_insert = events[0], events[1], events[2]
    a_update = events[3]
    d_insert = events[6]
    c_update = events[8]

    def record(event: dict[str, Any], revision: int) -> dict[str, Any]:
        return {
            "road_id": int(event["road_id"]),
            "revision": revision,
            "road_name_base64": event["road_name_base64"],
            "geometry_sha256": event["geometry_sha256"],
        }

    initial = (
        record(a_insert, 1),
        record(b_insert, 1),
        record(c_insert, 1),
    )
    a_after = record(a_update, 2)
    c_after = record(c_update, 2)
    d_row = record(d_insert, 1)
    expected_changelog = {
        _encode_expected("+I", initial[0]),
        _encode_expected("+I", initial[1]),
        _encode_expected("+I", initial[2]),
        _encode_expected("-U", initial[0]),
        _encode_expected("+U", a_after),
        _encode_expected("-D", initial[1]),
        _encode_expected("+I", d_row),
        _encode_expected("-U", initial[2]),
        _encode_expected("+U", c_after),
        _encode_expected("-D", d_row),
    }
    final_rows = tuple(sorted((a_after, c_after), key=lambda row: row["road_id"]))
    source_slice = {
        "initial": initial,
        "mutations": (
            {"operation": "update", "before": initial[0], "after": a_after},
            {"operation": "delete", "before": initial[1]},
            {"operation": "insert", "after": d_row},
            {"operation": "update", "before": initial[2], "after": c_after},
            {"operation": "delete", "before": d_row},
        ),
    }
    return {
        "source": source,
        "initial": initial,
        "a_after": a_after,
        "c_after": c_after,
        "d_row": d_row,
        "expected_changelog": expected_changelog,
        "final_rows": final_rows,
        "source_slice_sha256": _canonical_sha256(source_slice),
        "final_state_sha256": _canonical_sha256(final_rows),
    }


def _encode_expected(kind: str, row: dict[str, Any]) -> str:
    return "\t".join(
        (
            kind,
            str(row["road_id"]),
            str(row["revision"]),
            row["road_name_base64"],
            row["geometry_sha256"],
        )
    )


def _run_command(
    command: list[str],
    *,
    stage: str,
    timeout: int = 60,
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


def _container_absent(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "inspect", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return completed.returncode != 0


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class CdcPostgresSandbox:
    def __init__(self, *, image: str, network: str, token: str) -> None:
        self.image = image
        self.network = network
        self.container = f"gda-cdc-pg-{token}"
        self.database = "cdc_acceptance"
        self.admin_user = "cdc_admin"
        self.admin_password = secrets.token_hex(20)
        self.reader_user = "cdc_reader"
        self.reader_password = secrets.token_hex(20)
        self.table = "osm_road_changes"
        self.publication = f"gda_pub_{token}"
        self.slot = f"gda_slot_{token}"
        self.started = False
        for value in (self.container, self.publication, self.slot):
            expression = CONTAINER_RE if value == self.container else IDENTIFIER_RE
            if not expression.fullmatch(value):
                raise RuntimeError("generated CDC sandbox identity is invalid")

    def start(self, initial: tuple[dict[str, Any], ...]) -> dict[str, Any]:
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
                f"POSTGRES_USER={self.admin_user}",
                "-e",
                f"POSTGRES_PASSWORD={self.admin_password}",
                "-e",
                f"POSTGRES_DB={self.database}",
                self.image,
                "-c",
                "wal_level=logical",
                "-c",
                "max_replication_slots=10",
                "-c",
                "max_wal_senders=10",
            ],
            stage="start isolated PostgreSQL CDC source",
        )
        self.started = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "pg_isready",
                    "-U",
                    self.admin_user,
                    "-d",
                    self.database,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("isolated PostgreSQL CDC source did not become ready")

        value_rows = ",".join(
            "(" + ",".join(
                (
                    str(row["road_id"]),
                    str(row["revision"]),
                    _sql_literal(row["road_name_base64"]),
                    _sql_literal(row["geometry_sha256"]),
                )
            ) + ")"
            for row in initial
        )
        self._psql(
            f"""
            CREATE TABLE public.{self.table} (
                road_id BIGINT PRIMARY KEY,
                revision INTEGER NOT NULL,
                road_name_base64 TEXT NOT NULL,
                geometry_sha256 TEXT NOT NULL
            );
            ALTER TABLE public.{self.table} REPLICA IDENTITY FULL;
            INSERT INTO public.{self.table} VALUES {value_rows};
            CREATE ROLE {self.reader_user} WITH LOGIN REPLICATION PASSWORD
                {_sql_literal(self.reader_password)};
            GRANT CONNECT ON DATABASE {self.database} TO {self.reader_user};
            GRANT USAGE ON SCHEMA public TO {self.reader_user};
            GRANT SELECT ON public.{self.table} TO {self.reader_user};
            CREATE PUBLICATION {self.publication} FOR TABLE public.{self.table};
            """
        )
        return {
            "version": self._psql("SHOW server_version;").strip(),
            "wal_level": self._psql("SHOW wal_level;").strip(),
            "initial_lsn": self.current_lsn(),
            "initial_rows": int(
                self._psql(f"SELECT count(*) FROM public.{self.table};").strip()
            ),
        }

    def _psql(self, sql: str) -> str:
        completed = _run_command(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={self.admin_password}",
                self.container,
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                self.admin_user,
                "-d",
                self.database,
                "-At",
                "-c",
                sql,
            ],
            stage="execute isolated PostgreSQL CDC statement",
        )
        return completed.stdout

    def current_lsn(self) -> str:
        value = self._psql("SELECT pg_current_wal_lsn()::text;").strip()
        if not re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", value):
            raise RuntimeError("PostgreSQL returned an invalid WAL LSN")
        return value

    def mutate(self, plan: dict[str, Any]) -> str:
        initial = plan["initial"]
        a_after = plan["a_after"]
        c_after = plan["c_after"]
        d_row = plan["d_row"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = 2,
                road_name_base64 = {_sql_literal(a_after['road_name_base64'])},
                geometry_sha256 = {_sql_literal(a_after['geometry_sha256'])}
            WHERE road_id = {a_after['road_id']};
            DELETE FROM public.{self.table} WHERE road_id = {initial[1]['road_id']};
            INSERT INTO public.{self.table} VALUES (
                {d_row['road_id']}, 1,
                {_sql_literal(d_row['road_name_base64'])},
                {_sql_literal(d_row['geometry_sha256'])}
            );
            UPDATE public.{self.table}
            SET revision = 2,
                road_name_base64 = {_sql_literal(c_after['road_name_base64'])},
                geometry_sha256 = {_sql_literal(c_after['geometry_sha256'])}
            WHERE road_id = {c_after['road_id']};
            DELETE FROM public.{self.table} WHERE road_id = {d_row['road_id']};
            """
        )
        return self.current_lsn()

    def final_rows(self) -> tuple[dict[str, Any], ...]:
        lines = self._psql(
            f"""
            SELECT road_id::text || E'\\t' || revision::text || E'\\t' ||
                   road_name_base64 || E'\\t' || geometry_sha256
            FROM public.{self.table}
            ORDER BY road_id;
            """
        ).splitlines()
        return tuple(
            {
                "road_id": int(fields[0]),
                "revision": int(fields[1]),
                "road_name_base64": fields[2],
                "geometry_sha256": fields[3],
            }
            for fields in (line.split("\t") for line in lines if line)
        )

    def slot_evidence(self) -> dict[str, Any]:
        value = self._psql(
            "SELECT slot_name || E'\\t' || plugin || E'\\t' || "
            "COALESCE(confirmed_flush_lsn::text, '') || E'\\t' || active::text "
            f"FROM pg_replication_slots WHERE slot_name = {_sql_literal(self.slot)};"
        ).strip()
        fields = value.split("\t") if value else []
        if len(fields) != 4:
            raise RuntimeError("PostgreSQL CDC replication slot evidence is missing")
        return {
            "slot_name": fields[0],
            "plugin": fields[1],
            "confirmed_flush_lsn": fields[2],
            "active": fields[3] == "t",
        }

    def cleanup(self) -> dict[str, bool]:
        if self.started and not _container_absent(self.container):
            subprocess.run(
                ["docker", "rm", "-f", self.container],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        return {"cdc_postgres_container_removed": _container_absent(self.container)}


class FlinkCdcSandbox:
    def __init__(
        self,
        *,
        image: str,
        network: str,
        token: str,
        connector: Path,
        password: str,
        work_dir: Path,
    ) -> None:
        self.image = image
        self.network = network
        self.container = f"gda-cdc-flink-{token}"
        self.connector = connector
        self.password = password
        self.work_dir = work_dir
        self.started = False
        if not CONTAINER_RE.fullmatch(self.container):
            raise RuntimeError("generated Flink CDC sandbox identity is invalid")

    def start(self) -> dict[str, Any]:
        properties = "\n".join(
            (
                "jobmanager.rpc.address: localhost",
                "jobmanager.memory.process.size: 1024m",
                "taskmanager.memory.process.size: 1536m",
                "taskmanager.numberOfTaskSlots: 1",
                "parallelism.default: 1",
                "rest.bind-address: 0.0.0.0",
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
                self.network,
                "-e",
                f"CDC_PASSWORD={self.password}",
                "-e",
                f"FLINK_PROPERTIES={properties}",
                "-v",
                f"{REPO_ROOT}:/workspace",
                "-v",
                f"{self.connector}:/opt/flink/lib/{self.connector.name}:ro",
                self.image,
                "bash",
                "-lc",
                "/opt/flink/bin/start-cluster.sh && exec sleep infinity",
            ],
            stage="start isolated Flink CDC cluster",
        )
        self.started = True
        deadline = time.monotonic() + 60
        overview: dict[str, Any] | None = None
        while time.monotonic() < deadline:
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
                    break
            time.sleep(0.5)
        if overview is None or int(overview.get("taskmanagers", 0)) != 1:
            raise RuntimeError("isolated Flink CDC cluster did not become ready")
        return {
            "taskmanagers": int(overview["taskmanagers"]),
            "slots_total": int(overview["slots-total"]),
        }

    def submit(self, *, jar_path: Path, source: CdcPostgresSandbox) -> str:
        checkpoints = self.work_dir / "checkpoints"
        output = self.work_dir / "bronze/v1/changelog"
        checkpoints.mkdir(parents=True, exist_ok=True)
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "flink",
                "run",
                "-d",
                "-p",
                "1",
                f"/workspace/{jar_path.relative_to(REPO_ROOT).as_posix()}",
                "--hostname",
                source.container,
                "--username",
                source.reader_user,
                "--database",
                source.database,
                "--schema",
                "public",
                "--table",
                source.table,
                "--slot-name",
                source.slot,
                "--publication-name",
                source.publication,
                "--checkpoints",
                f"file:///workspace/{checkpoints.relative_to(REPO_ROOT).as_posix()}",
                "--output",
                f"file:///workspace/{output.relative_to(REPO_ROOT).as_posix()}",
                "--fail-after-count",
                "5",
            ],
            stage="submit PostgreSQL CDC Flink job",
            timeout=120,
        )
        matches = JOB_ID_RE.findall(completed.stdout)
        if len(matches) != 1:
            raise RuntimeError("Flink did not return one CDC JobID")
        return matches[0]

    def job_status(self, job_id: str) -> str:
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "curl",
                "-fsS",
                f"http://localhost:8081/jobs/{job_id}",
            ],
            stage="read Flink CDC job state",
        )
        return str(json.loads(completed.stdout)["state"])

    def wait_for_output(self, *, expected: int, job_id: str, timeout: int) -> list[str]:
        output = self.work_dir / "bronze/v1/changelog"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines, _ = _committed_lines(output)
            if len(lines) >= expected:
                return lines
            status = self.job_status(job_id)
            if status in {"FAILED", "CANCELED", "FINISHED"}:
                raise RuntimeError(
                    f"Flink CDC job entered {status} before {expected} committed records"
                )
            time.sleep(0.5)
        raise RuntimeError(f"Flink CDC output did not reach {expected} records")

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
            stage="read Flink CDC task evidence",
        )
        return completed.stdout

    def wait_for_marker(self, marker: str, *, timeout: int) -> str:
        deadline = time.monotonic() + timeout
        output = ""
        while time.monotonic() < deadline:
            output = self.task_output()
            if marker in output:
                return output
            time.sleep(0.5)
        raise RuntimeError(f"Flink CDC runtime marker was not observed: {marker}")

    def stop_with_savepoint(self, job_id: str) -> Path:
        savepoint_root = self.work_dir / "savepoints"
        savepoint_root.mkdir(parents=True, exist_ok=True)
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "flink",
                "stop",
                "--drain",
                "-p",
                f"file:///workspace/{savepoint_root.relative_to(REPO_ROOT).as_posix()}",
                job_id,
            ],
            stage="drain and stop Flink CDC job",
            timeout=180,
        )
        matches = re.findall(r"(file:[^\s]+/savepoint-[^\s]+)", completed.stdout)
        if len(matches) != 1:
            raise RuntimeError("Flink CDC stop did not return one savepoint path")
        parsed = urlparse(matches[0])
        if parsed.scheme != "file" or parsed.netloc:
            raise RuntimeError("Flink CDC stop returned an invalid savepoint URI")
        container_path = parsed.path
        prefix = "/workspace/"
        if not container_path.startswith(prefix):
            raise RuntimeError("Flink CDC savepoint escaped the isolated workspace")
        path = REPO_ROOT / container_path.removeprefix(prefix)
        if not path.is_dir():
            raise RuntimeError("Flink CDC savepoint was not materialized")
        return path

    def cleanup(self) -> dict[str, bool]:
        if self.started and not _container_absent(self.container):
            subprocess.run(
                ["docker", "rm", "-f", self.container],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        return {"flink_cdc_container_removed": _container_absent(self.container)}


def _file_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    items = [
        {
            "name": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    ]
    return items, _canonical_sha256(items)


def verify_provider_output(
    *,
    plan: dict[str, Any],
    work_dir: Path,
    task_output: str,
    final_rows: tuple[dict[str, Any], ...],
    savepoint: Path,
) -> dict[str, Any]:
    lines, output_inventory = _committed_lines(work_dir / "bronze/v1/changelog")
    checkpoints = [
        {"checkpoint_id": int(item[0]), "processed_count": int(item[1])}
        for item in CHECKPOINT_RE.findall(task_output)
    ]
    failure = FAILURE_RE.search(task_output)
    restore = RESTORE_RE.search(task_output)
    savepoint_inventory, savepoint_sha256 = _file_manifest(savepoint)
    checks = {
        "initial_snapshot_and_wal_changes_exact": (
            len(lines) == 10
            and len(set(lines)) == 10
            and set(lines) == plan["expected_changelog"]
        ),
        "checkpoint_completed_before_failure": bool(
            checkpoints
            and failure
            and int(failure.group(1)) >= checkpoints[0]["checkpoint_id"]
            and int(failure.group(2)) == 5
        ),
        "operator_restored_from_checkpoint": bool(
            restore
            and int(restore.group(1)) >= 1
            and 0 < int(restore.group(2)) <= 5
        ),
        "checkpoint_committed_all_changes": any(
            item["processed_count"] >= 10 for item in checkpoints
        ),
        "source_final_state_exact": final_rows == plan["final_rows"],
        "source_deletes_applied": len(final_rows) == 2,
        "drain_savepoint_materialized": bool(savepoint_inventory),
        "versioned_bronze_files_committed": bool(output_inventory),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "accepted_changelog_records": len(lines),
        "changelog_manifest_sha256": _canonical_sha256(output_inventory),
        "final_state_rows": len(final_rows),
        "final_state_sha256": _canonical_sha256(final_rows),
        "checkpoints": checkpoints,
        "failure": (
            {"checkpoint_id": int(failure.group(1)), "processed_count": int(failure.group(2))}
            if failure
            else None
        ),
        "restore": (
            {"attempt": int(restore.group(1)), "processed_count": int(restore.group(2))}
            if restore
            else None
        ),
        "savepoint": {
            "name": savepoint.name,
            "file_count": len(savepoint_inventory),
            "manifest_sha256": savepoint_sha256,
        },
    }


def _sync_definition(
    *,
    sync_definition_version_id: UUID,
    platform_definition_version_id: UUID,
    namespace: str,
    source_slice_sha256: str,
    connector: dict[str, Any],
    flink_image: str,
    flink_image_id: str,
    job_source_sha256: str,
    created_at: datetime,
) -> SourceSyncDefinitionVersion:
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_definition_urn": f"gda://local-dev/sync_definition/{namespace}",
        "sync_definition_version_id": sync_definition_version_id,
        "platform_definition_version_id": platform_definition_version_id,
        "source_resource_urn": "gda://local-dev/data_product/chongqing-osm-roads",
        "source_definition_fingerprint": DEFAULT_SOURCE_PRODUCT_SHA256,
        "target_resource_urn": f"gda://local-dev/table/{namespace}",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "provider_token",
        "cursor_field": None,
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {
            "provider": "flink-postgres-cdc-filesystem",
            "connector": connector,
            "flink_runtime_image": flink_image,
            "flink_runtime_image_id": flink_image_id,
            "job_source_sha256": job_source_sha256,
            "source_slice_sha256": source_slice_sha256,
            "checkpoint_interval_ms": 300,
            "acceptance_scope": "isolated",
        },
    }
    return SourceSyncDefinitionVersion(
        **values,
        definition_sha256=source_sync_definition_fingerprint(**values),
        created_by=WORKLOAD,
        created_at=created_at,
    )


def _commit_from_provider(
    *,
    sync_definition_version_id: UUID,
    run_id: UUID,
    source_slice_sha256: str,
    provider: dict[str, Any],
    committed_at: datetime,
) -> SourceSyncCommit:
    previous_cursor = {"change_set_sequence": 0, "source_slice_sha256": None}
    next_cursor = {
        "change_set_sequence": 1,
        "source_slice_sha256": source_slice_sha256,
    }
    values: dict[str, Any] = {
        "tenant_id": "local-dev",
        "sync_commit_id": uuid4(),
        "sync_definition_version_id": sync_definition_version_id,
        "run_id": run_id,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": previous_cursor,
        "next_cursor": next_cursor,
        "source_slice_sha256": source_slice_sha256,
        "target_commit_ref": {
            "provider": "flink-postgres-cdc-filesystem",
            "source_initial_lsn": provider["postgres"]["initial_lsn"],
            "source_final_lsn": provider["postgres"]["final_lsn"],
            "replication_slot": provider["postgres"]["slot"],
            "flink_image_id": provider["runtime"]["flink_image_id"],
            "connector_sha256": provider["runtime"]["connector"]["sha256"],
            "job_source_sha256": provider["runtime"]["job_source_sha256"],
            "job_jar_sha256": provider["runtime"]["job_jar_sha256"],
            "changelog_manifest_sha256": provider["verification"][
                "changelog_manifest_sha256"
            ],
            "savepoint": provider["verification"]["savepoint"],
        },
        "target_content_sha256": provider["verification"]["final_state_sha256"],
        "records_read": 10,
        "records_inserted": 4,
        "records_updated": 2,
        "records_deleted": 2,
        "records_output": 2,
        "committed_by": WORKLOAD,
        "committed_at": committed_at,
    }
    return SourceSyncCommit(
        **values,
        previous_cursor_sha256=canonical_json_fingerprint(previous_cursor),
        next_cursor_sha256=canonical_json_fingerprint(next_cursor),
        commit_sha256=source_sync_commit_fingerprint(**values),
    )


def run_provider(
    *,
    args: argparse.Namespace,
    work_dir: Path,
    token: str,
    plan: dict[str, Any],
    connector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    java_source_sha256 = _sha256_file(JAVA_SOURCE)
    jar_path = compile_flink_job(
        work_dir=work_dir,
        flink_image=args.flink_image,
        jdk_image=args.jdk_image,
        java_home=args.java_home,
        timeout=args.timeout_seconds,
        java_source=JAVA_SOURCE,
        main_class=MAIN_CLASS,
    )
    postgres = CdcPostgresSandbox(
        image=args.postgres_image,
        network=args.docker_network,
        token=token,
    )
    flink = FlinkCdcSandbox(
        image=args.flink_image,
        network=args.docker_network,
        token=token,
        connector=args.connector,
        password=postgres.reader_password,
        work_dir=work_dir,
    )
    cleanup: dict[str, bool] = {}
    try:
        postgres_evidence = postgres.start(plan["initial"])
        flink_cluster = flink.start()
        job_id = flink.submit(jar_path=jar_path, source=postgres)
        initial_lines = flink.wait_for_output(
            expected=3,
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        if len(initial_lines) != 3:
            raise RuntimeError("PostgreSQL CDC initial snapshot was not exactly three rows")
        final_lsn = postgres.mutate(plan)
        flink.wait_for_output(
            expected=10,
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        task_output = flink.wait_for_marker(
            "GDA_CDC_CHECKPOINT_COMPLETED",
            timeout=args.timeout_seconds,
        )
        deadline = time.monotonic() + args.timeout_seconds
        while not (
            FAILURE_RE.search(task_output)
            and RESTORE_RE.search(task_output)
            and any(int(count) >= 10 for _, count in CHECKPOINT_RE.findall(task_output))
        ):
            if time.monotonic() >= deadline:
                raise RuntimeError("Flink CDC recovery markers did not converge")
            time.sleep(0.5)
            task_output = flink.task_output()
        savepoint = flink.stop_with_savepoint(job_id)
        final_rows = postgres.final_rows()
        slot = postgres.slot_evidence()
        verification = verify_provider_output(
            plan=plan,
            work_dir=work_dir,
            task_output=task_output,
            final_rows=final_rows,
            savepoint=savepoint,
        )
        if verification["status"] != "passed":
            raise RuntimeError(f"PostgreSQL CDC provider checks failed: {verification['checks']}")
        provider = {
            "postgres": {
                **postgres_evidence,
                "image": args.postgres_image,
                "image_id": docker_image_id(
                    args.postgres_image, timeout=args.timeout_seconds
                ),
                "publication": postgres.publication,
                "slot": slot,
                "final_lsn": final_lsn,
                "final_rows": len(final_rows),
            },
            "runtime": {
                "flink_image": args.flink_image,
                "flink_image_id": docker_image_id(
                    args.flink_image, timeout=args.timeout_seconds
                ),
                "cluster": flink_cluster,
                "connector": connector,
                "job_source_sha256": java_source_sha256,
                "job_jar_sha256": _sha256_file(jar_path),
            },
            "verification": verification,
        }
        return provider, cleanup
    finally:
        cleanup.update(flink.cleanup())
        cleanup.update(postgres.cleanup())


def _certify(
    engine,
    args: argparse.Namespace,
    *,
    namespace: str,
    token: str,
    work_dir: Path,
    connector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    now = datetime.now(UTC).replace(microsecond=0)
    plan = build_cdc_plan(args.source)
    platform_definition_id = uuid4()
    sync_definition_version_id = uuid4()
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)
    gateway.register_definition(
        _definition_registration(
            "local-dev",
            platform_definition_id,
            namespace,
            now,
        )
    )
    definition = _sync_definition(
        sync_definition_version_id=sync_definition_version_id,
        platform_definition_version_id=platform_definition_id,
        namespace=namespace,
        source_slice_sha256=plan["source_slice_sha256"],
        connector=connector,
        flink_image=args.flink_image,
        flink_image_id=docker_image_id(
            args.flink_image, timeout=args.timeout_seconds
        ),
        job_source_sha256=_sha256_file(JAVA_SOURCE),
        created_at=now,
    )
    initial_cursor = {"change_set_sequence": 0, "source_slice_sha256": None}
    next_cursor = {
        "change_set_sequence": 1,
        "source_slice_sha256": plan["source_slice_sha256"],
    }
    definition_write = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )
    primary_run_id = uuid4()
    replay_run_id = uuid4()
    for index, (phase, run_id) in enumerate(
        (("primary", primary_run_id), ("replay", replay_run_id)),
        start=1,
    ):
        _submit_run(
            gateway,
            _run(
                "local-dev",
                run_id,
                platform_definition_id,
                now + timedelta(seconds=index),
                sequence=f"{namespace}:{phase}",
            ),
        )
    preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor=next_cursor,
        source_slice_sha256=plan["source_slice_sha256"],
    )
    provider, provider_cleanup = run_provider(
        args=args,
        work_dir=work_dir,
        token=token,
        plan=plan,
        connector=connector,
    )
    commit = _commit_from_provider(
        sync_definition_version_id=sync_definition_version_id,
        run_id=primary_run_id,
        source_slice_sha256=plan["source_slice_sha256"],
        provider=provider,
        committed_at=datetime.now(UTC),
    )
    commit_write = authority.commit(commit)
    replay_preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor=next_cursor,
        source_slice_sha256=plan["source_slice_sha256"],
    )
    replay_values = commit.model_dump(mode="python")
    replay_values.update(
        {
            "sync_commit_id": uuid4(),
            "run_id": replay_run_id,
            "committed_at": datetime.now(UTC),
        }
    )
    replay_values["commit_sha256"] = source_sync_commit_fingerprint(
        **{
            key: value
            for key, value in replay_values.items()
            if key
            not in {
                "previous_cursor_sha256",
                "next_cursor_sha256",
                "commit_sha256",
            }
        }
    )
    replay_write = authority.commit(SourceSyncCommit(**replay_values))
    checkpoint = authority.get_checkpoint("local-dev", sync_definition_version_id)
    commits = authority.commits("local-dev", sync_definition_version_id)
    checks = {
        "real_chongqing_osm_source_bound": (
            plan["source"]["source_feature_count"] == 50_366
            and plan["source"]["source_product_sha256"]
            == DEFAULT_SOURCE_PRODUCT_SHA256
        ),
        "connector_supply_chain_verified": connector["sha256"] == CONNECTOR_SHA256,
        "definition_and_initial_checkpoint_created": (
            definition_write.created
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "provider_preflight_was_empty": preflight is None,
        "postgres_logical_cdc_and_flink_recovery_passed": all(
            provider["verification"]["checks"].values()
        ),
        "source_sync_commit_advanced_once": (
            commit_write.created
            and commit_write.checkpoint.state_version == 1
            and commit_write.commit == commit
        ),
        "replay_preflight_skipped_second_provider": replay_preflight == commit,
        "cross_run_replay_recovered_commit": (
            not replay_write.created
            and replay_write.commit == commit
            and replay_write.replayed_commit_id == commit.sync_commit_id
        ),
        "checkpoint_and_commit_history_exact": (
            checkpoint.state_version == 1
            and checkpoint.last_sync_commit_id == commit.sync_commit_id
            and len(commits) == 1
        ),
    }
    return (
        {
            "schema": "gda.chongqing_osm_postgres_cdc_source_sync.acceptance.v1",
            "status": "passed" if all(checks.values()) else "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "source_slice_sha256": plan["source_slice_sha256"],
            },
            "provider": provider,
            "authority": {
                "sync_definition_version_id": str(sync_definition_version_id),
                "checkpoint": checkpoint.model_dump(mode="json"),
                "commits": [item.model_dump(mode="json") for item in commits],
                "replay_run_id": str(replay_run_id),
                "provider_write_invocations": 1,
            },
            "not_claimed": [
                "Flink to Iceberg interoperability",
                "cross-system exactly-once transaction",
                "production throughput or freshness SLO",
                "multi-cluster or Kubernetes high availability",
                "schema evolution during active CDC",
            ],
        },
        provider_cleanup,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--connector", type=Path, default=DEFAULT_CONNECTOR)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    connector = verify_connector_artifact(args.connector)
    settings = _settings()
    admin_auth = {
        "type": "basic",
        "username": settings.get("POSTGRES_USER", "postgres"),
        "password": settings.get(
            "POSTGRES_ADMIN_PASSWORD",
            settings.get("POSTGRES_PASSWORD", "postgres"),
        ),
    }
    admin_url = _connection_url(args.postgres_url, admin_auth)
    token = secrets.token_hex(5)
    namespace = f"chongqing_osm_cdc_{token}"
    work_dir = REPO_ROOT / ".tmp/source-sync-certification" / namespace
    sandbox = _PostgresDatabaseSandbox(admin_url)
    report: dict[str, Any] | None = None
    error: str | None = None
    cleanup: dict[str, bool] = {}
    main_counts_before = _main_sync_counts(admin_url)
    work_dir.mkdir(parents=True, exist_ok=False)
    try:
        sandbox.setup()
        if sandbox.engine is None:
            raise RuntimeError("certification control database engine was not created")
        report, provider_cleanup = _certify(
            sandbox.engine,
            args,
            namespace=namespace,
            token=token,
            work_dir=work_dir,
            connector=connector,
        )
        cleanup.update(provider_cleanup)
        report["sandbox"] = {"database": sandbox.database, "persistent": False}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup.update(sandbox.cleanup())
        shutil.rmtree(work_dir)
        cleanup["work_directory_removed"] = not work_dir.exists()
        for prefix in ("gda-cdc-pg-", "gda-cdc-flink-"):
            cleanup[f"no_runtime_container_with_prefix_{prefix.rstrip('-')}"] = not bool(
                subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"name=^{prefix}{token}$"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                ).stdout.strip()
            )
    main_counts_after = _main_sync_counts(admin_url)
    cleanup["main_sync_tables_unchanged_empty"] = (
        main_counts_before == (0, 0, 0) and main_counts_after == (0, 0, 0)
    )
    if report is None:
        report = {
            "schema": "gda.chongqing_osm_postgres_cdc_source_sync.acceptance.v1",
            "status": "failed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": {},
            "error": error,
        }
    report["cleanup"] = cleanup
    if not cleanup or not all(cleanup.values()):
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
