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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    LineageEvent,
    QualityResult,
    SourceSyncCommit,
    SourceSyncCommitGovernanceEvidence,
    SourceSyncDefinitionVersion,
    build_resource_urn,
    canonical_json_bytes,
    canonical_json_fingerprint,
    quality_result_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_connector_governance import (
    DiscoveredResource,
    DiscoverySnapshot,
    ProfileField,
    SchemaDriftEvent,
    detect_schema_drift,
)
from data_agent.source_schema_drift_ledger import (
    SchemaDriftStatus,
    SourceSchemaDriftLedger,
    SourceSchemaDriftValidationError,
)
from data_agent.source_schema_promotion import (
    SourceSchemaPromotionBlockedError,
    require_source_schema_promotion,
)
from data_agent.source_sync_authority import SourceSyncAuthority
from data_agent.source_sync_quarantine import (
    ProviderQuarantineReceipt,
    SourceSyncQuarantineContract,
    SourceSyncQuarantineRecorder,
)
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
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _commit_governance_evidence,
    _definition_registration,
    _metadata_change_id,
    _PostgresDatabaseSandbox,
    _register_resource_version,
    _run,
    _settings,
    _submit_run,
)
from scripts.source_sync_certification_support import connection_url as _connection_url
from scripts.source_sync_certification_support import main_sync_counts

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
DOCKER_HOST_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
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
    a_projection_after = {**a_after, "revision": 3}
    a_flap_after = {**a_after, "revision": 4}
    a_long_outage_after = {**a_after, "revision": 5}
    a_sustained_flap_after = {**a_after, "revision": 6}
    c_after = record(c_update, 2)
    d_row = record(d_insert, 1)
    invalid_row = {
        **d_row,
        "revision": 2,
        "geometry_sha256": "invalid-geometry-sha256",
    }
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
        _encode_expected("-U", a_after),
        _encode_expected("+U", a_projection_after),
        _encode_expected("-U", a_projection_after),
        _encode_expected("+U", a_flap_after),
        _encode_expected("-U", a_flap_after),
        _encode_expected("+U", a_long_outage_after),
        _encode_expected("-U", a_long_outage_after),
        _encode_expected("+U", a_sustained_flap_after),
    }
    expected_quarantine = {
        "invalid_geometry_sha256\t" + _encode_expected("+I", invalid_row),
        "invalid_geometry_sha256\t" + _encode_expected("-D", invalid_row),
    }
    final_rows = tuple(
        sorted((a_sustained_flap_after, c_after), key=lambda row: row["road_id"])
    )
    source_slice = {
        "initial": initial,
        "mutations": (
            {"operation": "update", "before": initial[0], "after": a_after},
            {"operation": "delete", "before": initial[1]},
            {"operation": "insert", "after": d_row},
            {"operation": "update", "before": initial[2], "after": c_after},
            {"operation": "delete", "before": d_row},
            {"operation": "insert", "after": invalid_row},
            {"operation": "delete", "before": invalid_row},
            {
                "operation": "update",
                "before": a_after,
                "after": a_projection_after,
                "schema_context": "nullable_observed_at_added",
            },
            {
                "operation": "update",
                "before": a_projection_after,
                "after": a_flap_after,
                "schema_context": "rapid_network_flapping",
            },
            {
                "operation": "update",
                "before": a_flap_after,
                "after": a_long_outage_after,
                "schema_context": "long_duration_network_outage",
            },
            {
                "operation": "update",
                "before": a_long_outage_after,
                "after": a_sustained_flap_after,
                "schema_context": "sustained_high_frequency_network_flapping",
            },
        ),
    }
    return {
        "source": source,
        "initial": initial,
        "a_after": a_after,
        "a_projection_after": a_projection_after,
        "a_flap_after": a_flap_after,
        "a_long_outage_after": a_long_outage_after,
        "a_sustained_flap_after": a_sustained_flap_after,
        "c_after": c_after,
        "d_row": d_row,
        "invalid_row": invalid_row,
        "expected_changelog": expected_changelog,
        "expected_quarantine": expected_quarantine,
        "final_rows": final_rows,
        "milestone_counts": {
            "initial_snapshot_accepted": 3,
            "base_mutations_accepted": 10,
            "additive_schema_accepted": 12,
            "rapid_flapping_accepted": 14,
            "long_outage_accepted": 16,
            "sustained_flapping_accepted": len(expected_changelog),
            "quarantined": len(expected_quarantine),
        },
        "operation_counts": {
            "read": len(expected_changelog) + len(expected_quarantine),
            "inserted": 5,
            "updated": 6,
            "deleted": 3,
            "output": len(final_rows),
        },
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


def _container_network_attached(name: str, network: str) -> bool:
    completed = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            name,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        return False
    networks = json.loads(completed.stdout)
    return network in networks


def _lsn_value(value: str) -> int:
    if not re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", value):
        raise ValueError("invalid PostgreSQL WAL LSN")
    high, low = value.split("/", 1)
    return (int(high, 16) << 32) + int(low, 16)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _postgres_bool(value: str) -> bool:
    if value in {"t", "true"}:
        return True
    if value in {"f", "false"}:
        return False
    raise RuntimeError("PostgreSQL returned an invalid boolean value")


class CdcPostgresSandbox:
    def __init__(
        self,
        *,
        image: str,
        network: str,
        token: str,
        max_slot_wal_keep_size_mb: int | None = None,
        network_alias: str | None = None,
    ) -> None:
        self.image = image
        self.network = network
        self.max_slot_wal_keep_size_mb = max_slot_wal_keep_size_mb
        self.network_alias = network_alias
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
        if max_slot_wal_keep_size_mb is not None and not (
            1 <= max_slot_wal_keep_size_mb <= 1_024
        ):
            raise ValueError("max slot WAL keep size must be between 1 and 1024 MiB")
        if network_alias is not None and not DOCKER_HOST_RE.fullmatch(network_alias):
            raise ValueError("PostgreSQL CDC network alias is invalid")

    def start(self, initial: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        postgres_options = [
            "-c",
            "wal_level=logical",
            "-c",
            "max_replication_slots=10",
            "-c",
            "max_wal_senders=10",
        ]
        if self.max_slot_wal_keep_size_mb is not None:
            postgres_options.extend(
                [
                    "-c",
                    (
                        "max_slot_wal_keep_size="
                        f"{self.max_slot_wal_keep_size_mb}MB"
                    ),
                ]
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
                *(
                    ["--network-alias", self.network_alias]
                    if self.network_alias
                    else []
                ),
                "-e",
                f"POSTGRES_USER={self.admin_user}",
                "-e",
                f"POSTGRES_PASSWORD={self.admin_password}",
                "-e",
                f"POSTGRES_DB={self.database}",
                self.image,
                *postgres_options,
            ],
            stage="start isolated PostgreSQL CDC source",
        )
        self.started = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            logs = subprocess.run(
                ["docker", "logs", self.container],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
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
            initialization_complete = (
                "PostgreSQL init process complete; ready for start up."
                in (logs.stdout + logs.stderr)
            )
            if initialization_complete and ready.returncode == 0:
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

    def replication_identity(self) -> dict[str, Any]:
        payload = self._psql(
            "SELECT json_build_object("
            "'system_identifier', system_identifier::text, "
            "'timeline_id', timeline_id, "
            "'previous_timeline_id', prev_timeline_id, "
            "'checkpoint_lsn', checkpoint_lsn::text, "
            "'redo_lsn', redo_lsn::text, "
            "'in_recovery', pg_is_in_recovery(), "
            "'observation_lsn', CASE WHEN pg_is_in_recovery() "
            "THEN pg_last_wal_replay_lsn()::text "
            "ELSE pg_current_wal_lsn()::text END, "
            "'receive_lsn', COALESCE(pg_last_wal_receive_lsn()::text, ''), "
            "'replay_lsn', COALESCE(pg_last_wal_replay_lsn()::text, ''))::text "
            "FROM pg_control_system() CROSS JOIN pg_control_checkpoint();"
        ).strip()
        try:
            identity = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "PostgreSQL replication identity evidence is malformed"
            ) from exc
        required = {
            "system_identifier",
            "timeline_id",
            "previous_timeline_id",
            "checkpoint_lsn",
            "redo_lsn",
            "in_recovery",
            "observation_lsn",
            "receive_lsn",
            "replay_lsn",
        }
        if not required.issubset(identity):
            raise RuntimeError("PostgreSQL replication identity evidence is incomplete")
        return identity

    def wal_capacity_configuration(self) -> dict[str, Any]:
        values = self._psql(
            "SELECT current_setting('max_slot_wal_keep_size') || E'\\t' || "
            "CASE WHEN current_setting('max_slot_wal_keep_size') = '-1' "
            "THEN '' ELSE pg_size_bytes("
            "current_setting('max_slot_wal_keep_size'))::text END || E'\\t' || "
            "current_setting('wal_segment_size') || E'\\t' || "
            "pg_size_bytes(current_setting('wal_segment_size'))::text || E'\\t' || "
            "current_setting('data_directory');"
        ).strip().split("\t")
        if len(values) != 5:
            raise RuntimeError("PostgreSQL WAL capacity configuration is malformed")
        return {
            "max_slot_wal_keep_size": values[0],
            "max_slot_wal_keep_size_bytes": int(values[1]) if values[1] else None,
            "wal_segment_size": values[2],
            "wal_segment_size_bytes": int(values[3]),
            "data_directory": values[4],
        }

    def wal_storage_evidence(self) -> dict[str, Any]:
        wal_usage = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "du",
                "-sk",
                "/var/lib/postgresql/data/pg_wal",
            ],
            stage="measure isolated PostgreSQL WAL directory",
        ).stdout.split()
        filesystem = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "df",
                "-Pk",
                "/var/lib/postgresql/data",
            ],
            stage="measure isolated PostgreSQL data filesystem",
        ).stdout.splitlines()
        if len(wal_usage) < 2 or len(filesystem) < 2:
            raise RuntimeError("PostgreSQL WAL storage evidence is missing")
        fields = filesystem[-1].split()
        if len(fields) < 6:
            raise RuntimeError("PostgreSQL filesystem evidence is malformed")
        return {
            "measurement_path": "/var/lib/postgresql/data",
            "pg_wal_bytes": int(wal_usage[0]) * 1_024,
            "filesystem_bytes": int(fields[-5]) * 1_024,
            "filesystem_used_bytes": int(fields[-4]) * 1_024,
            "filesystem_available_bytes": int(fields[-3]) * 1_024,
            "filesystem_capacity_percent": fields[-2],
            "filesystem_mount_reported": fields[-1],
        }

    def generate_wal_pressure(
        self,
        *,
        cycle: int,
        message_count: int,
        message_bytes: int,
    ) -> dict[str, Any]:
        if cycle <= 0 or not 1 <= message_count <= 64:
            raise ValueError("WAL pressure cycle and message count must be bounded")
        if not 65_536 <= message_bytes <= 524_288 or message_bytes % 16:
            raise ValueError(
                "WAL pressure message bytes must be a 16-byte multiple from 64 KiB "
                "through 512 KiB"
            )
        words_per_message = message_bytes // 16
        start_lsn = self.current_lsn()
        emitted_lsn = self._psql(
            "WITH payloads AS ("
            "SELECT message_number, "
            "decode(string_agg(md5(("
            f"{cycle}::bigint * 1000000000 + "
            "message_number::bigint * 1000000 + word_number"
            ")::text), '' ORDER BY word_number), 'hex') AS payload "
            f"FROM generate_series(1, {message_count}) AS message_number "
            f"CROSS JOIN generate_series(1, {words_per_message}) AS word_number "
            "GROUP BY message_number"
            ") SELECT max(pg_logical_emit_message("
            "true, 'gda_wal_capacity', payload)::text) FROM payloads;"
        ).strip()
        self._psql("SELECT pg_switch_wal()::text;")
        self._psql("CHECKPOINT;")
        checkpoint_lsn = self.current_lsn()
        return {
            "cycle": cycle,
            "message_count": message_count,
            "message_bytes": message_bytes,
            "requested_payload_bytes": message_count * message_bytes,
            "start_lsn": start_lsn,
            "emitted_lsn": emitted_lsn,
            "checkpoint_lsn": checkpoint_lsn,
            "observed_wal_bytes": _lsn_value(checkpoint_lsn)
            - _lsn_value(start_lsn),
        }

    def discover_schema(self, *, provider_version: str) -> DiscoverySnapshot:
        lines = self._psql(
            "SELECT column_name || E'\\t' || upper(data_type) || E'\\t' || "
            "is_nullable FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND table_name = {_sql_literal(self.table)} "
            "ORDER BY ordinal_position;"
        ).splitlines()
        fields = tuple(
            ProfileField(
                name=parts[0],
                data_type=parts[1],
                nullable=parts[2] == "YES",
            )
            for parts in (line.split("\t") for line in lines if line)
        )
        if not fields:
            raise RuntimeError("PostgreSQL CDC source schema discovery returned no fields")
        return DiscoverySnapshot(
            provider="PostgreSQL",
            provider_version=provider_version,
            resources=(
                DiscoveredResource(
                    name=f"public.{self.table}",
                    resource_type="table",
                    fields=fields,
                ),
            ),
        )

    def add_nullable_observed_at(self) -> str:
        self._psql(
            f"ALTER TABLE public.{self.table} ADD COLUMN observed_at TIMESTAMPTZ "
            "NULL DEFAULT TIMESTAMPTZ '2026-08-05 00:00:00+00';"
        )
        return self.current_lsn()

    def mutate_after_additive_schema(self, plan: dict[str, Any]) -> str:
        row = plan["a_projection_after"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = {row['revision']},
                observed_at = TIMESTAMPTZ '2026-08-05 00:01:00+00'
            WHERE road_id = {row['road_id']};
            """
        )
        return self.current_lsn()

    def mutate_during_rapid_flapping(self, plan: dict[str, Any]) -> str:
        row = plan["a_flap_after"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = {row['revision']},
                observed_at = TIMESTAMPTZ '2026-08-05 00:02:00+00'
            WHERE road_id = {row['road_id']};
            """
        )
        return self.current_lsn()

    def mutate_during_long_outage(self, plan: dict[str, Any]) -> str:
        row = plan["a_long_outage_after"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = {row['revision']},
                observed_at = TIMESTAMPTZ '2026-08-05 00:03:00+00'
            WHERE road_id = {row['road_id']};
            """
        )
        return self.current_lsn()

    def mutate_during_sustained_flapping(self, plan: dict[str, Any]) -> str:
        row = plan["a_sustained_flap_after"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = {row['revision']},
                observed_at = TIMESTAMPTZ '2026-08-05 00:04:00+00'
            WHERE road_id = {row['road_id']};
            """
        )
        return self.current_lsn()

    def tighten_observed_at_nullability(self) -> str:
        self._psql(
            f"ALTER TABLE public.{self.table} "
            "ALTER COLUMN observed_at SET NOT NULL;"
        )
        return self.current_lsn()

    def mutate(self, plan: dict[str, Any]) -> str:
        initial = plan["initial"]
        a_after = plan["a_after"]
        c_after = plan["c_after"]
        d_row = plan["d_row"]
        invalid_row = plan["invalid_row"]
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
            INSERT INTO public.{self.table} VALUES (
                {invalid_row['road_id']}, {invalid_row['revision']},
                {_sql_literal(invalid_row['road_name_base64'])},
                {_sql_literal(invalid_row['geometry_sha256'])}
            );
            DELETE FROM public.{self.table}
            WHERE road_id = {invalid_row['road_id']};
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
            "active": _postgres_bool(fields[3]),
        }

    def slot_observation(self) -> dict[str, Any]:
        system_identifier = self._psql(
            "SELECT system_identifier::text FROM pg_control_system();"
        ).strip()
        value = self._psql(
            "SELECT slot_name || E'\\t' || plugin || E'\\t' || slot_type || "
            "E'\\t' || database::text || E'\\t' || active::text || E'\\t' || "
            "COALESCE(active_pid::text, '') || E'\\t' || "
            "COALESCE(restart_lsn::text, '') || E'\\t' || "
            "COALESCE(confirmed_flush_lsn::text, '') || E'\\t' || "
            "COALESCE(xmin::text, '') || E'\\t' || "
            "COALESCE(catalog_xmin::text, '') || E'\\t' || "
            "COALESCE(wal_status, '') || E'\\t' || "
            "COALESCE(safe_wal_size::text, '') || E'\\t' || two_phase::text "
            f"FROM pg_replication_slots WHERE slot_name = {_sql_literal(self.slot)};"
        ).strip()
        if not value:
            return {
                "exists": False,
                "slot_name": self.slot,
                "system_identifier": system_identifier,
            }
        fields = value.split("\t")
        if len(fields) != 13:
            raise RuntimeError("PostgreSQL CDC slot observation is malformed")
        return {
            "exists": True,
            "slot_name": fields[0],
            "plugin": fields[1],
            "slot_type": fields[2],
            "database_identity": fields[3],
            "active": _postgres_bool(fields[4]),
            "active_pid": int(fields[5]) if fields[5] else None,
            "restart_lsn": fields[6],
            "confirmed_flush_lsn": fields[7],
            "xmin": fields[8] or None,
            "catalog_xmin": fields[9] or None,
            "wal_status": fields[10],
            "safe_wal_size": int(fields[11]) if fields[11] else None,
            "two_phase": _postgres_bool(fields[12]),
            "system_identifier": system_identifier,
        }

    def wait_for_slot_inactive(self, *, timeout: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        observation: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            observation = self.slot_observation()
            if observation["exists"] and not observation["active"]:
                return observation
            time.sleep(0.25)
        raise RuntimeError(
            "PostgreSQL CDC slot did not become inactive after disconnect: "
            f"slot={observation}"
        )

    def wait_for_slot_active(self, *, timeout: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        observation: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            observation = self.slot_observation()
            if observation["exists"] and observation["active"]:
                return observation
            time.sleep(0.25)
        raise RuntimeError(
            "PostgreSQL CDC slot did not become active before fault injection: "
            f"slot={observation}"
        )

    def terminate_slot_backend(self) -> dict[str, Any]:
        before = self.slot_observation()
        if not before["exists"] or not before["active"]:
            raise RuntimeError("CDC slot has no active backend to terminate")
        active_pid = before["active_pid"]
        if active_pid is None:
            raise RuntimeError("active CDC slot is missing its backend PID")
        terminated = _postgres_bool(
            self._psql(f"SELECT pg_terminate_backend({active_pid})::text;").strip()
        )
        if not terminated:
            raise RuntimeError("PostgreSQL refused to terminate the CDC slot backend")
        return {
            "active_pid": active_pid,
            "terminated": True,
            "slot_before": before,
        }

    def drop_replication_slot(self) -> dict[str, Any]:
        before = self.slot_observation()
        if not before["exists"] or before["active"]:
            raise RuntimeError("only an existing inactive CDC slot may be dropped")
        command_lsn = self.current_lsn()
        self._psql(f"SELECT pg_drop_replication_slot({_sql_literal(self.slot)});")
        after = self.slot_observation()
        if after["exists"]:
            raise RuntimeError("PostgreSQL CDC slot still exists after teardown")
        return {
            "slot_before": before,
            "drop_command_lsn": command_lsn,
            "slot_after": after,
            "absence_witnessed": True,
        }

    def recreate_replication_slot(self) -> dict[str, Any]:
        value = self._psql(
            "SELECT slot_name || E'\\t' || lsn::text "
            "FROM pg_create_logical_replication_slot("
            f"{_sql_literal(self.slot)}, 'pgoutput');"
        ).strip()
        fields = value.split("\t") if value else []
        if len(fields) != 2 or fields[0] != self.slot:
            raise RuntimeError("PostgreSQL did not recreate the expected CDC slot name")
        observation = self.slot_observation()
        if not observation["exists"] or observation["active"]:
            raise RuntimeError("recreated PostgreSQL CDC slot is not inactive")
        return {
            "slot_name": fields[0],
            "consistent_lsn": fields[1],
            "observation": observation,
        }

    def mutate_after_slot_loss(self, plan: dict[str, Any]) -> str:
        row = plan["a_after"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = {row['revision']},
                road_name_base64 = {_sql_literal(row['road_name_base64'])},
                geometry_sha256 = {_sql_literal(row['geometry_sha256'])}
            WHERE road_id = {row['road_id']};
            """
        )
        return self.current_lsn()

    def mutate_for_failover(self, plan: dict[str, Any]) -> dict[str, Any]:
        row = plan["a_after"]
        self._psql(
            f"""
            UPDATE public.{self.table}
            SET revision = {row['revision']},
                road_name_base64 = {_sql_literal(row['road_name_base64'])},
                geometry_sha256 = {_sql_literal(row['geometry_sha256'])}
            WHERE road_id = {row['road_id']};
            """
        )
        return {
            "target_lsn": self.current_lsn(),
            "row": row,
        }

    def slot_lag_bytes(self) -> int:
        value = self._psql(
            "SELECT COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), "
            "confirmed_flush_lsn), 0)::bigint::text "
            f"FROM pg_replication_slots WHERE slot_name = {_sql_literal(self.slot)};"
        ).strip()
        if not value or not re.fullmatch(r"[0-9]+", value):
            raise RuntimeError("PostgreSQL CDC slot WAL lag evidence is missing")
        return int(value)

    def wait_for_slot_recovery(
        self,
        *,
        stalled_lsn: str,
        target_lsn: str,
        peak_lag_bytes: int,
        timeout: int,
        max_recovery_lag_bytes: int | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_slot: dict[str, Any] | None = None
        last_lag: int | None = None
        while time.monotonic() < deadline:
            last_slot = self.slot_evidence()
            last_lag = self.slot_lag_bytes()
            lag_recovered = (
                last_lag < peak_lag_bytes
                if max_recovery_lag_bytes is None
                else last_lag <= max_recovery_lag_bytes
            )
            if (
                _lsn_value(last_slot["confirmed_flush_lsn"])
                >= _lsn_value(target_lsn)
                and _lsn_value(last_slot["confirmed_flush_lsn"])
                > _lsn_value(stalled_lsn)
                and lag_recovered
            ):
                return {"slot": last_slot, "wal_lag_bytes": last_lag}
            time.sleep(0.25)
        raise RuntimeError(
            "PostgreSQL CDC slot did not recover after reconnect: "
            f"slot={last_slot}, wal_lag_bytes={last_lag}, "
            f"target_lsn={target_lsn}, peak_lag_bytes={peak_lag_bytes}, "
            f"max_recovery_lag_bytes={max_recovery_lag_bytes}"
        )

    def disconnect_network(self) -> dict[str, Any]:
        if not self.started or not _container_network_attached(
            self.container, self.network
        ):
            raise RuntimeError("PostgreSQL CDC source is not attached to its network")
        _run_command(
            ["docker", "network", "disconnect", self.network, self.container],
            stage="disconnect PostgreSQL CDC source network",
        )
        if _container_network_attached(self.container, self.network):
            raise RuntimeError("PostgreSQL CDC source network disconnect did not apply")
        return {"network": self.network, "disconnected": True}

    def reconnect_network(self) -> dict[str, Any]:
        if not self.started:
            raise RuntimeError("PostgreSQL CDC source was not started")
        if not _container_network_attached(self.container, self.network):
            _run_command(
                ["docker", "network", "connect", self.network, self.container],
                stage="reconnect PostgreSQL CDC source network",
            )
        if not _container_network_attached(self.container, self.network):
            raise RuntimeError("PostgreSQL CDC source network reconnect did not apply")
        return {"network": self.network, "reconnected": True}

    def stop(self, *, timeout: int = 30) -> dict[str, Any]:
        if not self.started or _container_absent(self.container):
            raise RuntimeError("PostgreSQL CDC source is not running")
        _run_command(
            ["docker", "stop", "--time", str(timeout), self.container],
            stage="stop isolated PostgreSQL CDC source",
            timeout=timeout + 15,
        )
        running = subprocess.run(
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
            timeout=10,
            check=False,
        )
        stopped = running.returncode == 0 and running.stdout.strip() == "false"
        if not stopped:
            raise RuntimeError("PostgreSQL CDC source did not stop exactly")
        return {"container": self.container, "stopped": True, "timeout": timeout}

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


def _run_bounded_network_partition(
    source: CdcPostgresSandbox,
    *,
    phase: str,
    work_dir: Path,
    duration_seconds: float,
    mutation: Callable[[], dict[str, Any]],
    observe_during: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    accepted_before, _ = _committed_lines(work_dir / "silver/v1/changelog")
    rejected_before, _ = _committed_lines(work_dir / "quarantine/v1/rejected")
    slot_before = source.slot_evidence()
    wal_lag_bytes_before = source.slot_lag_bytes()
    disconnect = source.disconnect_network()
    partition_started = time.monotonic()
    try:
        mutation_evidence = mutation()
        time.sleep(duration_seconds)
        accepted_during, _ = _committed_lines(work_dir / "silver/v1/changelog")
        rejected_during, _ = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        slot_during = source.slot_evidence()
        wal_lag_bytes_during = source.slot_lag_bytes()
        during_observation = observe_during() if observe_during else {}
        partition_ended = time.monotonic()
    finally:
        reconnect = source.reconnect_network()
        recovery_started_monotonic = time.monotonic()
    return {
        "phase": phase,
        "accepted_before": len(accepted_before),
        "accepted_during": len(accepted_during),
        "disconnect": disconnect,
        "duration_seconds": round(partition_ended - partition_started, 3),
        "during_observation": during_observation,
        "mutation": mutation_evidence,
        "reconnect": reconnect,
        "rejected_before": len(rejected_before),
        "rejected_during": len(rejected_during),
        "slot_before": slot_before,
        "slot_during": slot_during,
        "wal_lag_bytes_before": wal_lag_bytes_before,
        "wal_lag_bytes_during": wal_lag_bytes_during,
        "_recovery_started_monotonic": recovery_started_monotonic,
    }


def _complete_network_partition(
    source: CdcPostgresSandbox,
    partition: dict[str, Any],
    *,
    accepted_after: int,
    rejected_after: int,
    target_lsn: str,
    timeout: int,
) -> dict[str, Any]:
    recovery_started_monotonic = float(partition["_recovery_started_monotonic"])
    recovery = source.wait_for_slot_recovery(
        stalled_lsn=partition["slot_during"]["confirmed_flush_lsn"],
        target_lsn=target_lsn,
        peak_lag_bytes=partition["wal_lag_bytes_during"],
        timeout=timeout,
    )
    public_partition = {
        key: value
        for key, value in partition.items()
        if key != "_recovery_started_monotonic"
    }
    return {
        **public_partition,
        "accepted_after": accepted_after,
        "rejected_after": rejected_after,
        "target_lsn": target_lsn,
        "slot_after": recovery["slot"],
        "wal_lag_bytes_after": recovery["wal_lag_bytes"],
        "recovery_duration_seconds": round(
            time.monotonic() - recovery_started_monotonic,
            3,
        ),
    }


def _partition_slot_recovered(partition: dict[str, Any]) -> bool:
    return bool(
        partition["disconnect"]["disconnected"]
        and partition["reconnect"]["reconnected"]
        and partition["slot_before"]["slot_name"]
        == partition["slot_during"]["slot_name"]
        == partition["slot_after"]["slot_name"]
        and partition["slot_before"]["confirmed_flush_lsn"]
        == partition["slot_during"]["confirmed_flush_lsn"]
        and partition["wal_lag_bytes_during"]
        > partition["wal_lag_bytes_before"]
        and _lsn_value(partition["slot_after"]["confirmed_flush_lsn"])
        >= _lsn_value(partition["target_lsn"])
        and _lsn_value(partition["slot_after"]["confirmed_flush_lsn"])
        > _lsn_value(partition["slot_during"]["confirmed_flush_lsn"])
        and partition["wal_lag_bytes_after"]
        < partition["wal_lag_bytes_during"]
    )


def _run_rapid_network_flapping(
    source: CdcPostgresSandbox,
    *,
    work_dir: Path,
    flap_count: int,
    interval_seconds: float,
    mutation: Callable[[], dict[str, Any]],
    phase: str = "rapid_network_flapping",
    observe_during: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if flap_count < 2:
        raise ValueError("rapid network flapping requires at least two cycles")
    cycles: list[dict[str, Any]] = []
    mutation_evidence: dict[str, Any] | None = None
    disconnected = False
    started = time.monotonic()
    try:
        for cycle_number in range(1, flap_count + 1):
            accepted_before, _ = _committed_lines(work_dir / "silver/v1/changelog")
            rejected_before, _ = _committed_lines(
                work_dir / "quarantine/v1/rejected"
            )
            slot_before = source.slot_evidence()
            wal_lag_bytes_before = source.slot_lag_bytes()
            disconnect = source.disconnect_network()
            disconnected = True
            slot_disconnected = source.slot_evidence()
            wal_lag_bytes_disconnected = source.slot_lag_bytes()
            if cycle_number == 1:
                mutation_evidence = mutation()
            time.sleep(interval_seconds)
            accepted_during, _ = _committed_lines(
                work_dir / "silver/v1/changelog"
            )
            rejected_during, _ = _committed_lines(
                work_dir / "quarantine/v1/rejected"
            )
            slot_during = source.slot_evidence()
            wal_lag_bytes_during = source.slot_lag_bytes()
            during_observation = observe_during() if observe_during else {}
            reconnect = source.reconnect_network()
            disconnected = False
            cycles.append(
                {
                    "cycle": cycle_number,
                    "accepted_before": len(accepted_before),
                    "accepted_during": len(accepted_during),
                    "disconnect": disconnect,
                    "during_observation": during_observation,
                    "reconnect": reconnect,
                    "rejected_before": len(rejected_before),
                    "rejected_during": len(rejected_during),
                    "slot_before": slot_before,
                    "slot_disconnected": slot_disconnected,
                    "slot_during": slot_during,
                    "wal_lag_bytes_before": wal_lag_bytes_before,
                    "wal_lag_bytes_disconnected": wal_lag_bytes_disconnected,
                    "wal_lag_bytes_during": wal_lag_bytes_during,
                }
            )
            if cycle_number < flap_count:
                time.sleep(interval_seconds)
    finally:
        if disconnected:
            source.reconnect_network()
    if mutation_evidence is None:
        raise RuntimeError("rapid network flapping did not apply its mutation")
    recovery_started_monotonic = time.monotonic()
    return {
        "phase": phase,
        "flap_count": flap_count,
        "interval_seconds": interval_seconds,
        "duration_seconds": round(time.monotonic() - started, 3),
        "cycles": cycles,
        "mutation": mutation_evidence,
        "_recovery_started_monotonic": recovery_started_monotonic,
    }


def _complete_rapid_network_flapping(
    source: CdcPostgresSandbox,
    flapping: dict[str, Any],
    *,
    accepted_after: int,
    rejected_after: int,
    target_lsn: str,
    timeout: int,
    max_recovery_lag_bytes: int | None = None,
) -> dict[str, Any]:
    cycles = flapping["cycles"]
    peak_lag_bytes = max(item["wal_lag_bytes_during"] for item in cycles)
    recovery_started_monotonic = float(
        flapping["_recovery_started_monotonic"]
    )
    recovery = source.wait_for_slot_recovery(
        stalled_lsn=cycles[0]["slot_during"]["confirmed_flush_lsn"],
        target_lsn=target_lsn,
        peak_lag_bytes=peak_lag_bytes,
        timeout=timeout,
        max_recovery_lag_bytes=max_recovery_lag_bytes,
    )
    public_flapping = {
        key: value
        for key, value in flapping.items()
        if key != "_recovery_started_monotonic"
    }
    return {
        **public_flapping,
        "accepted_after": accepted_after,
        "rejected_after": rejected_after,
        "target_lsn": target_lsn,
        "slot_after": recovery["slot"],
        "wal_lag_bytes_after": recovery["wal_lag_bytes"],
        "wal_lag_bytes_peak": peak_lag_bytes,
        "recovery_duration_seconds": round(
            time.monotonic() - recovery_started_monotonic,
            3,
        ),
    }


def _network_flapping_cursor_checks(
    flapping: dict[str, Any],
) -> dict[str, bool]:
    cycles = flapping["cycles"]
    if len(cycles) < 2:
        return {"multiple_cycles_observed": False}
    slot_names = {
        sample["slot_name"]
        for cycle in cycles
        for sample in (
            cycle["slot_before"],
            cycle["slot_disconnected"],
            cycle["slot_during"],
        )
    }
    slot_names.add(flapping["slot_after"]["slot_name"])
    first_cycle = cycles[0]
    return {
        "multiple_cycles_observed": True,
        "one_slot_name_throughout": len(slot_names) == 1,
        "physical_cycles_and_disconnected_lsn_stall": all(
            cycle["disconnect"]["disconnected"]
            and cycle["reconnect"]["reconnected"]
            and cycle["slot_disconnected"]["confirmed_flush_lsn"]
            == cycle["slot_during"]["confirmed_flush_lsn"]
            for cycle in cycles
        ),
        "first_disconnected_sink_boundary_stable": (
            first_cycle["accepted_before"] == first_cycle["accepted_during"]
            and first_cycle["rejected_before"]
            == first_cycle["rejected_during"]
        ),
        "first_mutation_increased_disconnected_wal_lag": (
            first_cycle["wal_lag_bytes_during"]
            > first_cycle["wal_lag_bytes_disconnected"]
        ),
        "exact_target_lsn_recovered": (
            _lsn_value(flapping["slot_after"]["confirmed_flush_lsn"])
            >= _lsn_value(flapping["target_lsn"])
            and _lsn_value(flapping["slot_after"]["confirmed_flush_lsn"])
            > _lsn_value(first_cycle["slot_during"]["confirmed_flush_lsn"])
        ),
    }


def _network_flapping_cursor_recovered(flapping: dict[str, Any]) -> bool:
    return all(_network_flapping_cursor_checks(flapping).values())


def _rapid_network_flapping_recovered(flapping: dict[str, Any]) -> bool:
    return bool(
        _network_flapping_cursor_recovered(flapping)
        and flapping["wal_lag_bytes_after"] < flapping["wal_lag_bytes_peak"]
    )


def _sustained_network_flapping_checks(
    flapping: dict[str, Any],
) -> dict[str, bool]:
    cycles = flapping["cycles"]
    cursor_checks = {
        f"cursor_{name}": value
        for name, value in _network_flapping_cursor_checks(flapping).items()
    }
    return {
        "phase_and_frequency_exact": (
            flapping["phase"] == "sustained_high_frequency_network_flapping"
            and flapping["flap_count"] >= 20
            and len(cycles) == flapping["flap_count"]
            and [cycle["cycle"] for cycle in cycles]
            == list(range(1, flapping["flap_count"] + 1))
            and 0 < flapping["interval_seconds"] <= 0.1
        ),
        "job_running_throughout": (
            all(
            cycle["during_observation"]["job_status"] == "RUNNING"
            for cycle in cycles
            )
            and flapping["job_status_after_recovery"] == "RUNNING"
        ),
        "combined_recovery_within_budget": (
            0 <= flapping["recovery_duration_seconds"]
            <= flapping["recovery_budget_seconds"]
        ),
        "residual_wal_lag_within_safety_budget": (
            0 <= flapping["wal_lag_bytes_after"]
            <= flapping["recovery_wal_lag_budget_bytes"]
        ),
        **cursor_checks,
    }


def _sustained_network_flapping_recovered(flapping: dict[str, Any]) -> bool:
    return all(_sustained_network_flapping_checks(flapping).values())


def _long_duration_outage_recovered(outage: dict[str, Any]) -> bool:
    return bool(
        outage["outage_objective_seconds"] > outage["checkpoint_timeout_seconds"]
        and outage["duration_seconds"] >= outage["outage_objective_seconds"]
        and outage["accepted_before"] == outage["accepted_during"]
        and outage["rejected_before"] == outage["rejected_during"]
        and outage["during_observation"]["job_status"] == "RUNNING"
        and outage["job_status_after_reconnect"] == "RUNNING"
        and 0 <= outage["recovery_duration_seconds"]
        <= outage["recovery_budget_seconds"]
        and _partition_slot_recovered(outage)
    )


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

    def submit(
        self,
        *,
        jar_path: Path,
        source: CdcPostgresSandbox,
        source_hostname: str | None = None,
        fail_after_count: int = 5,
    ) -> str:
        hostname = source_hostname or source.container
        if not DOCKER_HOST_RE.fullmatch(hostname):
            raise ValueError("Flink CDC source hostname is invalid")
        if not 1 <= fail_after_count <= 1_000_000:
            raise ValueError("Flink CDC failure threshold is invalid")
        checkpoints = self.work_dir / "checkpoints"
        output = self.work_dir / "silver/v1/changelog"
        quarantine_output = self.work_dir / "quarantine/v1/rejected"
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
                hostname,
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
                "--quarantine-output",
                (
                    "file:///workspace/"
                    f"{quarantine_output.relative_to(REPO_ROOT).as_posix()}"
                ),
                "--fail-after-count",
                str(fail_after_count),
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

    def job_exceptions(self, job_id: str) -> dict[str, Any]:
        completed = _run_command(
            [
                "docker",
                "exec",
                self.container,
                "curl",
                "-fsS",
                f"http://localhost:8081/jobs/{job_id}/exceptions?maxExceptions=20",
            ],
            stage="read Flink CDC job exceptions",
        )
        return dict(json.loads(completed.stdout))

    def wait_for_job_status(
        self,
        job_id: str,
        *,
        expected: set[str],
        timeout: int,
    ) -> str:
        deadline = time.monotonic() + timeout
        status = "UNKNOWN"
        while time.monotonic() < deadline:
            status = self.job_status(job_id)
            if status in expected:
                return status
            time.sleep(0.25)
        raise RuntimeError(
            f"Flink CDC job did not enter {sorted(expected)}: status={status}"
        )

    def cancel(self, job_id: str, *, timeout: int) -> str:
        status = self.job_status(job_id)
        if status not in {"FAILED", "CANCELED", "FINISHED"}:
            _run_command(
                [
                    "docker",
                    "exec",
                    self.container,
                    "flink",
                    "cancel",
                    job_id,
                ],
                stage="cancel invalidated PostgreSQL CDC Flink job",
                timeout=timeout,
            )
        return self.wait_for_job_status(
            job_id,
            expected={"FAILED", "CANCELED", "FINISHED"},
            timeout=timeout,
        )

    def wait_for_output(self, *, expected: int, job_id: str, timeout: int) -> list[str]:
        output = self.work_dir / "silver/v1/changelog"
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

    def wait_for_quarantine(
        self, *, expected: int, job_id: str, timeout: int
    ) -> list[str]:
        output = self.work_dir / "quarantine/v1/rejected"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines, _ = _committed_lines(output)
            if len(lines) >= expected:
                return lines
            status = self.job_status(job_id)
            if status in {"FAILED", "CANCELED", "FINISHED"}:
                raise RuntimeError(
                    f"Flink CDC job entered {status} before {expected} rejected records"
                )
            time.sleep(0.5)
        raise RuntimeError(f"Flink CDC quarantine did not reach {expected} records")

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
    final_slot: dict[str, Any],
    savepoint: Path,
    network_partition: dict[str, Any],
    rapid_network_flapping: dict[str, Any],
    long_duration_outage: dict[str, Any],
    sustained_network_flapping: dict[str, Any],
    schema_evolution: dict[str, Any],
) -> dict[str, Any]:
    lines, output_inventory = _committed_lines(work_dir / "silver/v1/changelog")
    rejected_lines, rejected_inventory = _committed_lines(
        work_dir / "quarantine/v1/rejected"
    )
    checkpoints = [
        {"checkpoint_id": int(item[0]), "processed_count": int(item[1])}
        for item in CHECKPOINT_RE.findall(task_output)
    ]
    failure = FAILURE_RE.search(task_output)
    restore = RESTORE_RE.search(task_output)
    savepoint_inventory, savepoint_sha256 = _file_manifest(savepoint)
    additive_event = SchemaDriftEvent.model_validate(
        schema_evolution["additive_drift_event"]
    )
    breaking_event = SchemaDriftEvent.model_validate(
        schema_evolution["breaking_drift_event"]
    )
    schema_partition = schema_evolution["network_partition"]
    expected_accepted = len(plan["expected_changelog"])
    expected_total = expected_accepted + len(plan["expected_quarantine"])
    sustained_flapping_checks = _sustained_network_flapping_checks(
        sustained_network_flapping
    )
    checks = {
        "initial_snapshot_wal_and_schema_continuity_changes_exact": (
            len(lines) == expected_accepted
            and len(set(lines)) == expected_accepted
            and set(lines) == plan["expected_changelog"]
        ),
        "invalid_cdc_records_quarantined_exactly_once": (
            len(rejected_lines) == 2
            and len(set(rejected_lines)) == 2
            and set(rejected_lines) == plan["expected_quarantine"]
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
            item["processed_count"] >= expected_total for item in checkpoints
        ),
        "source_final_state_exact": final_rows == plan["final_rows"],
        "source_deletes_applied": len(final_rows) == 2,
        "drain_savepoint_materialized": bool(savepoint_inventory),
        "versioned_silver_files_committed": bool(output_inventory),
        "versioned_quarantine_files_committed": bool(rejected_inventory),
        "network_partition_prevented_partial_sink_commits": (
            network_partition["accepted_before"]
            == plan["milestone_counts"]["initial_snapshot_accepted"]
            and network_partition["accepted_during"]
            == plan["milestone_counts"]["initial_snapshot_accepted"]
            and network_partition["accepted_after"]
            == plan["milestone_counts"]["base_mutations_accepted"]
            and network_partition["rejected_before"] == 0
            and network_partition["rejected_during"] == 0
            and network_partition["rejected_after"]
            == plan["milestone_counts"]["quarantined"]
        ),
        "slot_retained_wal_and_caught_up_after_reconnect": (
            _partition_slot_recovered(network_partition)
        ),
        "schema_partition_prevented_partial_sink_commits": (
            schema_partition["accepted_before"]
            == plan["milestone_counts"]["base_mutations_accepted"]
            and schema_partition["accepted_during"]
            == plan["milestone_counts"]["base_mutations_accepted"]
            and schema_partition["accepted_after"]
            == plan["milestone_counts"]["additive_schema_accepted"]
            and schema_partition["rejected_before"]
            == plan["milestone_counts"]["quarantined"]
            and schema_partition["rejected_during"]
            == plan["milestone_counts"]["quarantined"]
            and schema_partition["rejected_after"]
            == plan["milestone_counts"]["quarantined"]
        ),
        "repeated_partitions_preserved_one_slot_and_recovered": (
            _partition_slot_recovered(schema_partition)
            and network_partition["slot_before"]["slot_name"]
            == schema_partition["slot_before"]["slot_name"]
        ),
        "rapid_network_flapping_preserved_slot_and_recovered": (
            _rapid_network_flapping_recovered(rapid_network_flapping)
            and rapid_network_flapping["flap_count"] >= 3
            and rapid_network_flapping["accepted_after"]
            == long_duration_outage["accepted_before"]
            and rapid_network_flapping["rejected_after"]
            == long_duration_outage["rejected_before"]
            and schema_evolution["job_status_after_flapping"] == "RUNNING"
            and network_partition["slot_before"]["slot_name"]
            == rapid_network_flapping["slot_after"]["slot_name"]
        ),
        "long_duration_outage_met_recovery_budget": (
            _long_duration_outage_recovered(long_duration_outage)
            and long_duration_outage["accepted_after"]
            == sustained_network_flapping["cycles"][0]["accepted_before"]
            and long_duration_outage["rejected_after"]
            == sustained_network_flapping["cycles"][0]["rejected_before"]
            and rapid_network_flapping["slot_after"]["slot_name"]
            == long_duration_outage["slot_before"]["slot_name"]
        ),
        "sustained_high_frequency_flapping_met_recovery_budget": (
            all(sustained_flapping_checks.values())
            and sustained_network_flapping["accepted_after"]
            == expected_accepted
            and sustained_network_flapping["rejected_after"]
            == plan["milestone_counts"]["quarantined"]
            and long_duration_outage["slot_after"]["slot_name"]
            == sustained_network_flapping["cycles"][0]["slot_before"][
                "slot_name"
            ]
        ),
        "slot_inactive_after_drain_savepoint": (
            not final_slot["active"]
            and final_slot["slot_name"]
            == sustained_network_flapping["slot_after"]["slot_name"]
        ),
        "active_additive_schema_change_preserved_projection": (
            not additive_event.breaking
            and len(additive_event.field_changes) == 1
            and additive_event.field_changes[0].field_name == "observed_at"
            and additive_event.field_changes[0].change_kind == "added"
            and additive_event.field_changes[0].current_nullable is True
            and schema_evolution["job_status_after_additive"] == "RUNNING"
            and schema_evolution["accepted_before_additive"]
            == plan["milestone_counts"]["base_mutations_accepted"]
            and schema_evolution["accepted_after_additive"]
            == plan["milestone_counts"]["additive_schema_accepted"]
            and schema_evolution["rejected_before_additive"]
            == plan["milestone_counts"]["quarantined"]
            and schema_evolution["rejected_after_additive"]
            == plan["milestone_counts"]["quarantined"]
            and schema_partition["disconnect"]["disconnected"]
            and schema_partition["reconnect"]["reconnected"]
        ),
        "breaking_schema_change_detected_while_projection_running": (
            breaking_event.breaking
            and len(breaking_event.field_changes) == 1
            and breaking_event.field_changes[0].field_name == "observed_at"
            and breaking_event.field_changes[0].change_kind == "nullable_tightened"
            and schema_evolution["job_status_after_breaking"] == "RUNNING"
            and additive_event.current_discovery_fingerprint
            == breaking_event.previous_discovery_fingerprint
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "accepted_changelog_records": len(lines),
        "changelog_manifest_sha256": _canonical_sha256(output_inventory),
        "accepted_files": output_inventory,
        "rejected_changelog_records": len(rejected_lines),
        "rejected_records": rejected_lines,
        "rejected_files": rejected_inventory,
        "rejected_manifest_sha256": _canonical_sha256(rejected_inventory),
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
        "network_partition": network_partition,
        "network_partitions": [network_partition, schema_partition],
        "rapid_network_flapping": rapid_network_flapping,
        "long_duration_outage": long_duration_outage,
        "sustained_network_flapping": sustained_network_flapping,
        "sustained_network_flapping_checks": sustained_flapping_checks,
        "final_slot": final_slot,
        "schema_evolution": schema_evolution,
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
    additional_config: dict[str, Any] | None = None,
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
            "source_projection_fields": [
                "road_id",
                "revision",
                "road_name_base64",
                "geometry_sha256",
            ],
            "schema_evolution_mode": "explicit_projection_with_drift_gate",
            **(additional_config or {}),
        },
        "governance_contract": {
            "schema": "gda.source_sync_governance.v1",
            "target_layer": "silver",
            "data_kind": "vector",
            "capture_kind": "cdc",
            "source_adapter": {
                "adapter_id": "flink-postgres-cdc",
                "adapter_version": "3.3.0",
                "adapter_fingerprint": canonical_json_fingerprint(
                    {
                        "connector_sha256": CONNECTOR_SHA256,
                        "runtime_image_id": flink_image_id,
                        "job_source_sha256": job_source_sha256,
                    }
                ),
            },
            "standard_mapping_contract_id": uuid4(),
            "standard_version_id": uuid4(),
            "data_model_version_id": uuid4(),
            "quality_rule_version_refs": ["quality:cdc-changelog-integrity-v1"],
            "classification_policy_version_ref": "classification:internal-v1",
            "retention_policy_version_ref": "retention:silver-v1",
            "schema_change_policy": "approval_required",
            "promotion_mode": "quality_gated",
            "quarantine_resource_urn": (
                f"gda://local-dev/table/{namespace}-quarantine"
            ),
            "event_time_field": None,
            "watermark_delay_seconds": None,
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
    plan: dict[str, Any],
    provider: dict[str, Any],
    schema_governance: dict[str, Any],
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
            "network_partition": provider["verification"]["network_partition"],
            "network_partitions": provider["verification"]["network_partitions"],
            "rapid_network_flapping": provider["verification"][
                "rapid_network_flapping"
            ],
            "long_duration_outage": provider["verification"][
                "long_duration_outage"
            ],
            "sustained_network_flapping": provider["verification"][
                "sustained_network_flapping"
            ],
            "sustained_network_flapping_checks": provider["verification"][
                "sustained_network_flapping_checks"
            ],
            "schema_evolution": {
                "running_projection_fields": provider["verification"][
                    "schema_evolution"
                ]["running_projection_fields"],
                "additive_drift_event_id": schema_governance["additive"]["drift"][
                    "drift_event_id"
                ],
                "breaking_drift_event_id": schema_governance["breaking"]["drift"][
                    "drift_event_id"
                ],
                "breaking_successor_promotion": schema_governance["breaking"][
                    "promotion_decision"
                ],
                "approval_case_ref": schema_governance["breaking"]["approval_case"][
                    "approval_case_ref"
                ],
            },
            "savepoint": provider["verification"]["savepoint"],
        },
        "target_content_sha256": provider["verification"]["target_content_sha256"],
        "records_read": plan["operation_counts"]["read"],
        "records_inserted": plan["operation_counts"]["inserted"],
        "records_updated": plan["operation_counts"]["updated"],
        "records_deleted": plan["operation_counts"]["deleted"],
        "records_output": plan["operation_counts"]["output"],
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
        initial_schema = postgres.discover_schema(
            provider_version=postgres_evidence["version"]
        )
        flink_cluster = flink.start()
        job_id = flink.submit(jar_path=jar_path, source=postgres)
        initial_lines = flink.wait_for_output(
            expected=3,
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        if len(initial_lines) != plan["milestone_counts"][
            "initial_snapshot_accepted"
        ]:
            raise RuntimeError("PostgreSQL CDC initial snapshot was not exactly three rows")
        network_partition = _run_bounded_network_partition(
            postgres,
            phase="base_mutations",
            work_dir=work_dir,
            duration_seconds=args.network_partition_seconds,
            mutation=lambda: {"source_final_lsn": postgres.mutate(plan)},
        )
        base_accepted_after = flink.wait_for_output(
            expected=plan["milestone_counts"]["base_mutations_accepted"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        base_rejected_after = flink.wait_for_quarantine(
            expected=plan["milestone_counts"]["quarantined"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        network_partition = _complete_network_partition(
            postgres,
            network_partition,
            accepted_after=len(base_accepted_after),
            rejected_after=len(base_rejected_after),
            target_lsn=network_partition["mutation"]["source_final_lsn"],
            timeout=args.timeout_seconds,
        )
        network_partition = {
            **network_partition,
            "source_final_lsn": network_partition["mutation"]["source_final_lsn"],
        }

        drift_source_id = f"chongqing-osm-cdc-{token}"

        def mutate_additive_schema() -> dict[str, Any]:
            additive_ddl_lsn = postgres.add_nullable_observed_at()
            additive_schema = postgres.discover_schema(
                provider_version=postgres_evidence["version"]
            )
            additive_event = detect_schema_drift(
                drift_source_id,
                initial_schema,
                additive_schema,
            )
            if additive_event is None or additive_event.breaking:
                raise RuntimeError("active nullable column addition was not additive drift")
            additive_mutation_lsn = postgres.mutate_after_additive_schema(plan)
            return {
                "additive_ddl_lsn": additive_ddl_lsn,
                "additive_discovery": additive_schema.model_dump(mode="json"),
                "additive_drift_event": additive_event.model_dump(mode="json"),
                "additive_projection_mutation_lsn": additive_mutation_lsn,
            }

        schema_partition = _run_bounded_network_partition(
            postgres,
            phase="additive_schema_evolution",
            work_dir=work_dir,
            duration_seconds=args.network_partition_seconds,
            mutation=mutate_additive_schema,
        )
        accepted_after_additive = flink.wait_for_output(
            expected=plan["milestone_counts"]["additive_schema_accepted"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        rejected_after_additive, _ = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        schema_partition = _complete_network_partition(
            postgres,
            schema_partition,
            accepted_after=len(accepted_after_additive),
            rejected_after=len(rejected_after_additive),
            target_lsn=schema_partition["mutation"][
                "additive_projection_mutation_lsn"
            ],
            timeout=args.timeout_seconds,
        )
        additive_schema = DiscoverySnapshot.model_validate(
            schema_partition["mutation"]["additive_discovery"]
        )
        additive_event = SchemaDriftEvent.model_validate(
            schema_partition["mutation"]["additive_drift_event"]
        )
        additive_ddl_lsn = schema_partition["mutation"]["additive_ddl_lsn"]
        additive_mutation_lsn = schema_partition["mutation"][
            "additive_projection_mutation_lsn"
        ]
        job_status_after_additive = flink.job_status(job_id)
        rapid_network_flapping = _run_rapid_network_flapping(
            postgres,
            work_dir=work_dir,
            flap_count=args.network_flap_count,
            interval_seconds=args.network_flap_seconds,
            mutation=lambda: {
                "projection_mutation_lsn": postgres.mutate_during_rapid_flapping(
                    plan
                )
            },
        )
        accepted_after_flapping = flink.wait_for_output(
            expected=plan["milestone_counts"]["rapid_flapping_accepted"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        rejected_after_flapping, _ = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        rapid_network_flapping = _complete_rapid_network_flapping(
            postgres,
            rapid_network_flapping,
            accepted_after=len(accepted_after_flapping),
            rejected_after=len(rejected_after_flapping),
            target_lsn=rapid_network_flapping["mutation"][
                "projection_mutation_lsn"
            ],
            timeout=args.timeout_seconds,
        )
        job_status_after_flapping = flink.job_status(job_id)
        long_duration_outage = _run_bounded_network_partition(
            postgres,
            phase="long_duration_network_outage",
            work_dir=work_dir,
            duration_seconds=args.long_outage_seconds,
            mutation=lambda: {
                "projection_mutation_lsn": postgres.mutate_during_long_outage(
                    plan
                )
            },
            observe_during=lambda: {"job_status": flink.job_status(job_id)},
        )
        long_duration_outage = {
            **long_duration_outage,
            "outage_objective_seconds": args.long_outage_seconds,
            "checkpoint_timeout_seconds": 15,
            "recovery_budget_seconds": args.long_outage_recovery_budget_seconds,
            "job_status_after_reconnect": flink.job_status(job_id),
        }
        accepted_after_long_outage = flink.wait_for_output(
            expected=plan["milestone_counts"]["long_outage_accepted"],
            job_id=job_id,
            timeout=min(
                args.timeout_seconds,
                args.long_outage_recovery_budget_seconds,
            ),
        )
        rejected_after_long_outage, _ = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        elapsed_recovery = (
            time.monotonic()
            - long_duration_outage["_recovery_started_monotonic"]
        )
        remaining_recovery_budget = (
            args.long_outage_recovery_budget_seconds - elapsed_recovery
        )
        if remaining_recovery_budget <= 0:
            raise RuntimeError(
                "PostgreSQL CDC long-outage sink recovery exceeded its budget"
            )
        long_duration_outage = _complete_network_partition(
            postgres,
            long_duration_outage,
            accepted_after=len(accepted_after_long_outage),
            rejected_after=len(rejected_after_long_outage),
            target_lsn=long_duration_outage["mutation"][
                "projection_mutation_lsn"
            ],
            timeout=min(args.timeout_seconds, remaining_recovery_budget),
        )
        sustained_network_flapping = _run_rapid_network_flapping(
            postgres,
            phase="sustained_high_frequency_network_flapping",
            work_dir=work_dir,
            flap_count=args.sustained_flap_count,
            interval_seconds=args.sustained_flap_seconds,
            mutation=lambda: {
                "projection_mutation_lsn": (
                    postgres.mutate_during_sustained_flapping(plan)
                )
            },
            observe_during=lambda: {"job_status": flink.job_status(job_id)},
        )
        sustained_network_flapping = {
            **sustained_network_flapping,
            "recovery_budget_seconds": (
                args.sustained_flap_recovery_budget_seconds
            ),
            "recovery_wal_lag_budget_bytes": (
                args.sustained_flap_recovery_wal_lag_budget_bytes
            ),
        }
        accepted_after_sustained_flapping = flink.wait_for_output(
            expected=plan["milestone_counts"]["sustained_flapping_accepted"],
            job_id=job_id,
            timeout=min(
                args.timeout_seconds,
                args.sustained_flap_recovery_budget_seconds,
            ),
        )
        rejected_after_sustained_flapping, _ = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        elapsed_sustained_recovery = (
            time.monotonic()
            - sustained_network_flapping["_recovery_started_monotonic"]
        )
        remaining_sustained_recovery_budget = (
            args.sustained_flap_recovery_budget_seconds
            - elapsed_sustained_recovery
        )
        if remaining_sustained_recovery_budget <= 0:
            raise RuntimeError(
                "PostgreSQL CDC sustained-flapping sink recovery exceeded its budget"
            )
        sustained_network_flapping = _complete_rapid_network_flapping(
            postgres,
            sustained_network_flapping,
            accepted_after=len(accepted_after_sustained_flapping),
            rejected_after=len(rejected_after_sustained_flapping),
            target_lsn=sustained_network_flapping["mutation"][
                "projection_mutation_lsn"
            ],
            timeout=min(
                args.timeout_seconds,
                remaining_sustained_recovery_budget,
            ),
            max_recovery_lag_bytes=(
                args.sustained_flap_recovery_wal_lag_budget_bytes
            ),
        )
        sustained_network_flapping = {
            **sustained_network_flapping,
            "job_status_after_recovery": flink.job_status(job_id),
        }
        breaking_ddl_lsn = postgres.tighten_observed_at_nullability()
        breaking_schema = postgres.discover_schema(
            provider_version=postgres_evidence["version"]
        )
        breaking_event = detect_schema_drift(
            drift_source_id,
            additive_schema,
            breaking_schema,
        )
        if breaking_event is None or not breaking_event.breaking:
            raise RuntimeError("active nullability tightening was not breaking drift")
        job_status_after_breaking = flink.job_status(job_id)
        final_lsn = breaking_ddl_lsn
        schema_evolution = {
            "initial_discovery": initial_schema.model_dump(mode="json"),
            "additive_discovery": additive_schema.model_dump(mode="json"),
            "breaking_discovery": breaking_schema.model_dump(mode="json"),
            "additive_drift_event": additive_event.model_dump(mode="json"),
            "breaking_drift_event": breaking_event.model_dump(mode="json"),
            "accepted_before_additive": schema_partition["accepted_before"],
            "accepted_after_additive": len(accepted_after_additive),
            "rejected_before_additive": schema_partition["rejected_before"],
            "rejected_after_additive": len(rejected_after_additive),
            "job_status_after_additive": job_status_after_additive,
            "job_status_after_flapping": job_status_after_flapping,
            "job_status_after_long_outage": long_duration_outage[
                "job_status_after_reconnect"
            ],
            "job_status_after_sustained_flapping": (
                sustained_network_flapping["job_status_after_recovery"]
            ),
            "job_status_after_breaking": job_status_after_breaking,
            "lsn": {
                "additive_ddl": additive_ddl_lsn,
                "additive_projection_mutation": additive_mutation_lsn,
                "rapid_flapping_projection_mutation": rapid_network_flapping[
                    "mutation"
                ]["projection_mutation_lsn"],
                "long_outage_projection_mutation": long_duration_outage[
                    "mutation"
                ]["projection_mutation_lsn"],
                "sustained_flapping_projection_mutation": (
                    sustained_network_flapping["mutation"][
                        "projection_mutation_lsn"
                    ]
                ),
                "breaking_ddl": breaking_ddl_lsn,
            },
            "network_partition": schema_partition,
            "running_projection_fields": [
                "road_id",
                "revision",
                "road_name_base64",
                "geometry_sha256",
            ],
        }
        task_output = flink.wait_for_marker(
            "GDA_CDC_CHECKPOINT_COMPLETED",
            timeout=args.timeout_seconds,
        )
        deadline = time.monotonic() + args.timeout_seconds
        while not (
            FAILURE_RE.search(task_output)
            and RESTORE_RE.search(task_output)
            and any(
                int(count) >= plan["operation_counts"]["read"]
                for _, count in CHECKPOINT_RE.findall(task_output)
            )
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
            final_slot=slot,
            savepoint=savepoint,
            network_partition=network_partition,
            rapid_network_flapping=rapid_network_flapping,
            long_duration_outage=long_duration_outage,
            sustained_network_flapping=sustained_network_flapping,
            schema_evolution=schema_evolution,
        )
        if verification["status"] != "passed":
            raise RuntimeError(
                "PostgreSQL CDC provider checks failed: "
                f"checks={verification['checks']}, "
                "sustained_flapping_checks="
                f"{verification['sustained_network_flapping_checks']}"
            )
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


def govern_schema_evolution(
    engine,
    *,
    definition: SourceSyncDefinitionVersion,
    namespace: str,
    provider: dict[str, Any],
    detected_at: datetime,
) -> dict[str, Any]:
    """Reconcile additive drift and fail closed on a breaking successor."""

    evolution = provider["verification"]["schema_evolution"]
    additive_event = SchemaDriftEvent.model_validate(evolution["additive_drift_event"])
    breaking_event = SchemaDriftEvent.model_validate(evolution["breaking_drift_event"])
    ledger = SourceSchemaDriftLedger(engine)
    approval_authority = ApprovalCaseAuthority(engine)
    detected_by = "workload:postgresql-cdc-schema-observer"

    try:
        additive_write = ledger.record(
            tenant_id="local-dev",
            source_definition_fingerprint=definition.definition_sha256,
            event=additive_event,
            detected_by=detected_by,
        )
    except SourceSchemaDriftValidationError as exc:
        raise RuntimeError("record additive active CDC schema drift failed") from exc
    try:
        additive_reconciled = ledger.transition(
            tenant_id="local-dev",
            drift_event_id=additive_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.RECONCILED,
            actor_subject="workload:schema-reconciler",
            reason="nullable source column addition preserved the declared CDC projection",
            details={
                "schema": "gda.active_cdc_additive_reconciliation.v1",
                "projection_fields": evolution["running_projection_fields"],
            },
        )
    except SourceSchemaDriftValidationError as exc:
        raise RuntimeError("reconcile additive active CDC schema drift failed") from exc
    running_projection_decision = require_source_schema_promotion(
        additive_reconciled
    )

    try:
        breaking_write = ledger.record(
            tenant_id="local-dev",
            source_definition_fingerprint=definition.definition_sha256,
            event=breaking_event,
            detected_by=detected_by,
        )
    except SourceSchemaDriftValidationError as exc:
        raise RuntimeError("record breaking active CDC schema drift failed") from exc
    approval_case = ApprovalCase(
        tenant_id="local-dev",
        approval_case_ref=build_resource_urn(
            "local-dev",
            "approval_case",
            f"{namespace}-breaking-schema",
        ),
        target_resource_urn=build_resource_urn(
            "local-dev",
            "schema_drift",
            breaking_event.event_id,
        ),
        target_fingerprint=breaking_event.event_id,
        action="source_schema_drift.reconcile",
        requester_subject="workload:postgresql-cdc-schema-observer",
        request_reason="active CDC nullability tightening requires human review",
        request_context={
            "drift_event_id": breaking_event.event_id,
            "current_discovery_fingerprint": (
                breaking_event.current_discovery_fingerprint
            ),
            "running_projection_fields": evolution["running_projection_fields"],
        },
        requested_at=detected_at,
        expires_at=detected_at + timedelta(hours=1),
    )
    approval_write = approval_authority.create(
        approval_case,
        owner_ref="team:data-platform",
    )

    direct_reconcile_blocked = False
    try:
        ledger.transition(
            tenant_id="local-dev",
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.RECONCILED,
            actor_subject="workload:schema-reconciler",
            reason="automatic successor promotion must not bypass approval",
        )
    except SourceSchemaDriftValidationError:
        direct_reconcile_blocked = True

    successor_promotion_blocked = False
    successor_decision = None
    try:
        require_source_schema_promotion(
            breaking_write.drift,
            approval_case=approval_write.approval_case,
        )
    except SourceSchemaPromotionBlockedError as exc:
        successor_promotion_blocked = True
        successor_decision = exc.decision
    if successor_decision is None:
        raise RuntimeError("breaking source schema successor was not blocked")

    additive_lifecycle = ledger.lifecycle("local-dev", additive_event.event_id)
    breaking_lifecycle = ledger.lifecycle("local-dev", breaking_event.event_id)
    approval_events = approval_authority.events(
        "local-dev",
        approval_case.approval_case_ref,
    )
    checks = {
        "additive_drift_reconciled_for_running_projection": (
            additive_write.created
            and additive_write.drift.status is SchemaDriftStatus.OBSERVED
            and additive_reconciled.status is SchemaDriftStatus.RECONCILED
            and running_projection_decision.allowed
            and [entry.to_status for entry in additive_lifecycle]
            == [SchemaDriftStatus.OBSERVED, SchemaDriftStatus.RECONCILED]
        ),
        "breaking_drift_requires_external_approval": (
            breaking_write.created
            and breaking_write.drift.status is SchemaDriftStatus.APPROVAL_REQUIRED
            and direct_reconcile_blocked
            and [entry.to_status for entry in breaking_lifecycle]
            == [SchemaDriftStatus.APPROVAL_REQUIRED]
        ),
        "pending_approval_case_did_not_fabricate_verdict": (
            approval_write.created
            and approval_write.approval_case.status is ApprovalCaseStatus.PENDING
            and approval_write.approval_case.state_version == 0
            and approval_write.approval_case.decided_by is None
            and len(approval_events) == 1
            and approval_events[0].to_status is ApprovalCaseStatus.PENDING
        ),
        "breaking_successor_promotion_failed_closed": (
            successor_promotion_blocked
            and not successor_decision.allowed
            and successor_decision.reason
            == "breaking_schema_drift_pending_approval"
            and successor_decision.approval_case_binding_valid is True
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "additive": {
            "drift": additive_reconciled.model_dump(mode="json"),
            "lifecycle": [entry.model_dump(mode="json") for entry in additive_lifecycle],
            "promotion_decision": running_projection_decision.model_dump(mode="json"),
        },
        "breaking": {
            "drift": breaking_write.drift.model_dump(mode="json"),
            "lifecycle": [entry.model_dump(mode="json") for entry in breaking_lifecycle],
            "approval_case": approval_write.approval_case.model_dump(mode="json"),
            "approval_events": [event.model_dump(mode="json") for event in approval_events],
            "promotion_decision": successor_decision.model_dump(mode="json"),
        },
    }


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

    evidence_time = datetime.now(UTC)
    schema_governance = govern_schema_evolution(
        engine,
        definition=definition,
        namespace=namespace,
        provider=provider,
        detected_at=evidence_time,
    )
    if schema_governance["status"] != "passed":
        raise RuntimeError(
            f"active CDC schema governance failed: {schema_governance['checks']}"
        )
    evidence_dir = work_dir / "governance-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "cdc-silver-output-manifest.json"
    quality_path = evidence_dir / "quality-manifest.json"
    quarantine_path = evidence_dir / "quarantine-manifest.json"

    output_document = {
        "schema": "gda.postgres_cdc_silver_output.v1",
        "accepted_files": provider["verification"]["accepted_files"],
        "accepted_records": provider["verification"]["accepted_changelog_records"],
        "changelog_manifest_sha256": provider["verification"][
            "changelog_manifest_sha256"
        ],
        "final_state_rows": provider["verification"]["final_state_rows"],
        "final_state_sha256": provider["verification"]["final_state_sha256"],
        "source_initial_lsn": provider["postgres"]["initial_lsn"],
        "source_final_lsn": provider["postgres"]["final_lsn"],
        "source_slice_sha256": plan["source_slice_sha256"],
        "schema_evolution": {
            "provider": provider["verification"]["schema_evolution"],
            "governance_checks": schema_governance["checks"],
            "additive_promotion_decision": schema_governance["additive"][
                "promotion_decision"
            ],
            "breaking_promotion_decision": schema_governance["breaking"][
                "promotion_decision"
            ],
        },
    }
    output_path.write_bytes(canonical_json_bytes(output_document))
    target_content_sha256 = _sha256_file(output_path)
    provider["verification"]["target_content_sha256"] = target_content_sha256

    quality_rule_ref = "quality:cdc-changelog-integrity-v1"
    quality_document = {
        "schema": "gda.postgres_cdc_quality.v1",
        "checks": provider["verification"]["checks"],
        "quality_rule_version_ref": quality_rule_ref,
        "records_accepted": provider["verification"]["accepted_changelog_records"],
        "records_read": plan["operation_counts"]["read"],
        "records_rejected": provider["verification"]["rejected_changelog_records"],
        "source_slice_sha256": plan["source_slice_sha256"],
        "target_content_sha256": target_content_sha256,
    }
    quality_path.write_bytes(canonical_json_bytes(quality_document))
    quality_content_sha256 = _sha256_file(quality_path)

    reason_counts = {"invalid_geometry_sha256": 2}
    quarantine_provider_document = {
        "schema": "gda.postgres_cdc_rejected_output.v1",
        "reason_counts": reason_counts,
        "rejected_files": provider["verification"]["rejected_files"],
        "rejected_records": provider["verification"]["rejected_records"],
    }
    quarantine_path.write_bytes(canonical_json_bytes(quarantine_provider_document))
    rejected_content_sha256 = _sha256_file(quarantine_path)

    source_version_id = uuid4()
    target_version_id = uuid4()
    _register_resource_version(
        gateway,
        tenant_id="local-dev",
        resource_urn=definition.source_resource_urn,
        resource_version_id=source_version_id,
        content_sha256=plan["source_slice_sha256"],
        created_at=evidence_time,
    )
    _register_resource_version(
        gateway,
        tenant_id="local-dev",
        resource_urn=definition.target_resource_urn,
        resource_version_id=target_version_id,
        content_sha256=target_content_sha256,
        created_at=evidence_time,
    )
    output_artifact = Artifact(
        tenant_id="local-dev",
        artifact_id=uuid4(),
        artifact_key=f"{namespace}-silver-output",
        artifact_role="output",
        storage_uri=output_path.resolve().as_uri(),
        media_type="application/json",
        content_sha256=target_content_sha256,
        size_bytes=output_path.stat().st_size,
        run_id=primary_run_id,
        resource_version_id=target_version_id,
        manifest=output_document,
        created_by=WORKLOAD,
        created_at=evidence_time,
    )
    quality_evaluator = "workload:quality-evaluator"
    quality_artifact = Artifact(
        tenant_id="local-dev",
        artifact_id=uuid4(),
        artifact_key=f"{namespace}-quality-evidence",
        artifact_role="evidence",
        storage_uri=quality_path.resolve().as_uri(),
        media_type="application/vnd.gda.quality-evidence+json",
        content_sha256=quality_content_sha256,
        size_bytes=quality_path.stat().st_size,
        run_id=primary_run_id,
        resource_version_id=target_version_id,
        manifest=quality_document,
        created_by=quality_evaluator,
        created_at=evidence_time,
    )
    for artifact in (output_artifact, quality_artifact):
        gateway.record_artifact(artifact)

    quality_metrics = {
        "accepted": provider["verification"]["accepted_changelog_records"],
        "checked": plan["operation_counts"]["read"],
        "rejected": provider["verification"]["rejected_changelog_records"],
        "violations": 0,
    }
    quality_result = QualityResult(
        tenant_id="local-dev",
        quality_result_id=uuid4(),
        run_id=primary_run_id,
        resource_version_id=target_version_id,
        rule_version_ref=quality_rule_ref,
        verdict="passed",
        metrics=quality_metrics,
        evidence_artifact_id=quality_artifact.artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id="local-dev",
            run_id=primary_run_id,
            resource_version_id=target_version_id,
            rule_version_ref=quality_rule_ref,
            verdict="passed",
            metrics=quality_metrics,
            evidence_artifact_id=quality_artifact.artifact_id,
            evaluated_by=quality_evaluator,
            evaluated_at=evidence_time,
        ),
        evaluated_by=quality_evaluator,
        evaluated_at=evidence_time,
    )
    gateway.record_quality_result(quality_result)
    lineage = LineageEvent(
        tenant_id="local-dev",
        lineage_event_id=uuid4(),
        event_type="materialize",
        source_resource_version_id=source_version_id,
        target_resource_version_id=target_version_id,
        producer=WORKLOAD,
        event_sha256=canonical_json_fingerprint(
            {
                "artifact_id": str(output_artifact.artifact_id),
                "run_id": str(primary_run_id),
                "source_version_id": str(source_version_id),
                "target_version_id": str(target_version_id),
            }
        ),
        run_id=primary_run_id,
        definition_version_id=platform_definition_id,
        artifact_id=output_artifact.artifact_id,
        facets={
            "capture_kind": "cdc",
            "rejected_content_sha256": rejected_content_sha256,
            "source_final_lsn": provider["postgres"]["final_lsn"],
            "target_layer": "silver",
        },
        occurred_at=evidence_time,
    )
    gateway.record_lineage(lineage)
    metadata_change_id = _metadata_change_id(
        engine, "local-dev", lineage.lineage_event_id
    )
    commit = _commit_from_provider(
        sync_definition_version_id=sync_definition_version_id,
        run_id=primary_run_id,
        source_slice_sha256=plan["source_slice_sha256"],
        plan=plan,
        provider=provider,
        schema_governance=schema_governance,
        committed_at=evidence_time + timedelta(seconds=1),
    )
    governance_evidence: SourceSyncCommitGovernanceEvidence = (
        _commit_governance_evidence(
            tenant_id="local-dev",
            sync_commit_id=commit.sync_commit_id,
            target_resource_version_id=target_version_id,
            output_artifact_id=output_artifact.artifact_id,
            quality_result_ids=(quality_result.quality_result_id,),
            lineage_event_id=lineage.lineage_event_id,
            metadata_change_id=metadata_change_id,
        )
    )
    quarantine_urn = definition.governance_contract.quarantine_resource_urn
    if quarantine_urn is None:
        raise RuntimeError("Silver CDC definition lacks a quarantine Resource")
    quarantine_record = SourceSyncQuarantineRecorder(
        SourceSyncQuarantineContract(
            quarantine_resource_urn=quarantine_urn,
            authority_system="flink-postgres-cdc-filesystem",
            authority_locator=quarantine_path.resolve().as_uri(),
            owner_ref="team:data-platform",
            artifact_key_prefix=f"{namespace}_quarantine",
            governance_ref={"retention_policy": "retention:silver-v1"},
        ),
        gateway=gateway,
    ).record(
        definition=definition,
        commit=commit,
        receipt=ProviderQuarantineReceipt(
            storage_uri=quarantine_path.resolve().as_uri(),
            media_type="application/json",
            content_sha256=rejected_content_sha256,
            size_bytes=quarantine_path.stat().st_size,
            records_rejected=2,
            reason_counts=reason_counts,
            manifest_facets={
                "provider_output_schema": quarantine_provider_document["schema"],
                "rejected_files": provider["verification"]["rejected_files"],
                "rejected_manifest_sha256": provider["verification"][
                    "rejected_manifest_sha256"
                ],
                "rejected_records": provider["verification"]["rejected_records"],
                "source_final_lsn": provider["postgres"]["final_lsn"],
            },
        ),
        recorded_at=evidence_time,
    )
    commit_write = authority.commit(
        commit, governance_evidence, quarantine_record.evidence
    )
    same_id_replay = authority.commit(
        commit, governance_evidence, quarantine_record.evidence
    )
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
        "network_partition_slot_recovery_verified": (
            provider["verification"]["checks"][
                "network_partition_prevented_partial_sink_commits"
            ]
            and provider["verification"]["checks"][
                "slot_retained_wal_and_caught_up_after_reconnect"
            ]
        ),
        "repeated_network_partition_schema_recovery_verified": (
            provider["verification"]["checks"][
                "schema_partition_prevented_partial_sink_commits"
            ]
            and provider["verification"]["checks"][
                "repeated_partitions_preserved_one_slot_and_recovered"
            ]
            and provider["verification"]["checks"][
                "slot_inactive_after_drain_savepoint"
            ]
        ),
        "rapid_network_flapping_recovery_verified": provider["verification"][
            "checks"
        ]["rapid_network_flapping_preserved_slot_and_recovered"],
        "long_duration_outage_recovery_budget_verified": provider[
            "verification"
        ]["checks"]["long_duration_outage_met_recovery_budget"],
        "sustained_high_frequency_flapping_recovery_verified": provider[
            "verification"
        ]["checks"]["sustained_high_frequency_flapping_met_recovery_budget"],
        "active_schema_evolution_and_promotion_gate_verified": (
            all(schema_governance["checks"].values())
            and provider["verification"]["checks"][
                "active_additive_schema_change_preserved_projection"
            ]
            and provider["verification"]["checks"][
                "breaking_schema_change_detected_while_projection_running"
            ]
        ),
        "physical_nonzero_quarantine_receipt_verified": (
            provider["verification"]["rejected_changelog_records"] == 2
            and set(provider["verification"]["rejected_records"])
            == plan["expected_quarantine"]
            and hashlib.sha256(quarantine_path.read_bytes()).hexdigest()
            == rejected_content_sha256
            and quarantine_record.evidence.records_rejected == 2
            and quarantine_record.evidence.reason_counts == reason_counts
        ),
        "source_sync_commit_advanced_once": (
            commit_write.created
            and commit_write.checkpoint.state_version == 1
            and commit_write.commit == commit
        ),
        "silver_governance_and_quarantine_bound": (
            commit_write.governance_evidence == governance_evidence
            and commit_write.quarantine_evidence == quarantine_record.evidence
        ),
        "same_id_replay_preserved_dual_evidence": (
            not same_id_replay.created
            and same_id_replay.commit == commit
            and same_id_replay.governance_evidence == governance_evidence
            and same_id_replay.quarantine_evidence == quarantine_record.evidence
        ),
        "replay_preflight_skipped_second_provider": replay_preflight == commit,
        "cross_run_replay_recovered_commit": (
            not replay_write.created
            and replay_write.commit == commit
            and replay_write.replayed_commit_id == commit.sync_commit_id
            and replay_write.governance_evidence == governance_evidence
            and replay_write.quarantine_evidence == quarantine_record.evidence
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
                "governance_evidence": governance_evidence.model_dump(mode="json"),
                "output_artifact": output_artifact.model_dump(mode="json"),
                "quarantine_evidence": quarantine_record.evidence.model_dump(
                    mode="json"
                ),
                "quarantine_artifact": quarantine_record.artifact.model_dump(
                    mode="json"
                ),
                "schema_evolution_governance": schema_governance,
                "replay_run_id": str(replay_run_id),
                "provider_write_invocations": 1,
            },
            "not_claimed": [
                "Flink to Iceberg interoperability",
                "cross-system exactly-once transaction",
                "production throughput or freshness SLO",
                "multi-cluster or Kubernetes high availability",
                "automatic application of an unapproved breaking schema successor",
                "reconnect-backoff exhaustion",
                "replication-slot invalidation or teardown recovery",
                "production WAL capacity or PostgreSQL failover",
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
    parser.add_argument("--network-partition-seconds", type=float, default=3.0)
    parser.add_argument("--network-flap-count", type=int, default=3)
    parser.add_argument("--network-flap-seconds", type=float, default=0.5)
    parser.add_argument("--long-outage-seconds", type=float, default=20.0)
    parser.add_argument(
        "--long-outage-recovery-budget-seconds",
        type=int,
        default=60,
    )
    parser.add_argument("--sustained-flap-count", type=int, default=20)
    parser.add_argument("--sustained-flap-seconds", type=float, default=0.1)
    parser.add_argument(
        "--sustained-flap-recovery-budget-seconds",
        type=int,
        default=60,
    )
    parser.add_argument(
        "--sustained-flap-recovery-wal-lag-budget-bytes",
        type=int,
        default=1_048_576,
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 1.0 <= args.network_partition_seconds <= 30.0:
        parser.error("--network-partition-seconds must be between 1 and 30")
    if not 3 <= args.network_flap_count <= 10:
        parser.error("--network-flap-count must be between 3 and 10")
    if not 0.1 <= args.network_flap_seconds <= 2.0:
        parser.error("--network-flap-seconds must be between 0.1 and 2")
    if not 16.0 <= args.long_outage_seconds <= 120.0:
        parser.error("--long-outage-seconds must be between 16 and 120")
    if not 5 <= args.long_outage_recovery_budget_seconds <= 180:
        parser.error(
            "--long-outage-recovery-budget-seconds must be between 5 and 180"
        )
    if not 20 <= args.sustained_flap_count <= 50:
        parser.error("--sustained-flap-count must be between 20 and 50")
    if not 0.05 <= args.sustained_flap_seconds <= 0.1:
        parser.error("--sustained-flap-seconds must be between 0.05 and 0.1")
    if not 5 <= args.sustained_flap_recovery_budget_seconds <= 180:
        parser.error(
            "--sustained-flap-recovery-budget-seconds must be between 5 and 180"
        )
    if not 65_536 <= args.sustained_flap_recovery_wal_lag_budget_bytes <= 16_777_216:
        parser.error(
            "--sustained-flap-recovery-wal-lag-budget-bytes must be between "
            "65536 and 16777216"
        )
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
    main_counts_before = main_sync_counts(admin_url)
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
    main_counts_after = main_sync_counts(admin_url)
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
