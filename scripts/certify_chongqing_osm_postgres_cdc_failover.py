#!/usr/bin/env python3
"""Certify fail-closed PostgreSQL CDC admission across physical failover."""

from __future__ import annotations

import argparse
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

from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_sync_authority import SourceSyncAuthority
from scripts.certify_chongqing_osm_flink_stream import (
    DEFAULT_FLINK_IMAGE,
    DEFAULT_JAVA_HOME,
    DEFAULT_JDK_IMAGE,
    DEFAULT_SOURCE,
    REPO_ROOT,
    _committed_lines,
    _sha256_file,
    compile_flink_job,
    docker_image_id,
)
from scripts.certify_chongqing_osm_postgres_cdc import (
    CHECKPOINT_RE,
    DEFAULT_CONNECTOR,
    DEFAULT_NETWORK,
    DEFAULT_POSTGRES_IMAGE,
    JAVA_SOURCE,
    MAIN_CLASS,
    CdcPostgresSandbox,
    FlinkCdcSandbox,
    _container_absent,
    _container_network_attached,
    _lsn_value,
    _run_command,
    _sql_literal,
    _sync_definition,
    build_cdc_plan,
    verify_connector_artifact,
)
from scripts.certify_chongqing_osm_postgres_cdc_slot_invalidation import (
    TERMINAL_FLINK_STATES,
    _exception_summary,
    _success_evidence_counts,
)
from scripts.certify_source_sync_authority import (
    WORKLOAD,
    _definition_registration,
    _PostgresDatabaseSandbox,
    _run,
    _settings,
    _submit_run,
)
from scripts.source_sync_certification_support import connection_url as _connection_url
from scripts.source_sync_certification_support import main_sync_counts

DEFAULT_REPORT = (
    REPO_ROOT
    / ".tmp/source-sync-certification/"
    "chongqing-osm-postgres-cdc-failover-report.json"
)
STANDBY_RESOURCE_RE = re.compile(
    r"^gda-cdc-(?:standby|standby-data)-[0-9a-f]{10}$"
)


def assess_failover_continuity(evidence: dict[str, Any]) -> dict[str, Any]:
    """Admit only a replayed, promoted source with continuous slot identity."""

    primary = evidence.get("primary_identity")
    standby = evidence.get("standby_identity_before_promotion")
    promoted = evidence.get("promoted_identity")
    primary_slot = evidence.get("primary_slot")
    promoted_slot = evidence.get("promoted_slot")
    reasons: list[str] = []

    identities = (primary, standby, promoted)
    if not all(isinstance(identity, dict) for identity in identities):
        reasons.append("postgresql_failover_identity_evidence_missing")
    else:
        required = {"system_identifier", "timeline_id", "in_recovery"}
        if any(not required.issubset(identity) for identity in identities) or any(
            not isinstance(identity["system_identifier"], str)
            or not isinstance(identity["timeline_id"], int)
            or not isinstance(identity["in_recovery"], bool)
            for identity in identities
        ):
            reasons.append("postgresql_failover_identity_evidence_incomplete")
        else:
            system_identifiers = {
                identity["system_identifier"] for identity in identities
            }
            if len(system_identifiers) != 1:
                reasons.append("postgresql_system_identifier_changed")
            if primary["in_recovery"] is not False:
                reasons.append("postgresql_original_primary_role_unproven")
            if standby["in_recovery"] is not True:
                reasons.append("postgresql_physical_standby_role_unproven")
            if promoted["in_recovery"] is not False:
                reasons.append("postgresql_standby_promotion_unproven")
            if promoted["timeline_id"] != primary["timeline_id"] + 1:
                reasons.append("postgresql_timeline_did_not_increment_once")

    if evidence.get("mutation_replayed_before_promotion") is not True:
        reasons.append("postgresql_failover_mutation_replay_unproven")
    if evidence.get("primary_stopped_before_promotion") is not True:
        reasons.append("postgresql_primary_stop_order_unproven")
    if evidence.get("publication_present_after_promotion") is not True:
        reasons.append("postgresql_publication_missing_after_promotion")

    required_slot = {
        "exists",
        "slot_name",
        "plugin",
        "slot_type",
        "database_identity",
        "system_identifier",
    }
    if not isinstance(primary_slot, dict) or not required_slot.issubset(primary_slot):
        reasons.append("logical_replication_slot_primary_evidence_missing")
    elif primary_slot["exists"] is not True:
        reasons.append("logical_replication_slot_missing_before_failover")
    if not isinstance(promoted_slot, dict):
        reasons.append("logical_replication_slot_promoted_evidence_missing")
    elif promoted_slot.get("exists") is not True:
        reasons.append("logical_replication_slot_missing_after_promotion")
    elif isinstance(primary_slot, dict) and required_slot.issubset(primary_slot):
        comparable = {
            "slot_name",
            "plugin",
            "slot_type",
            "database_identity",
            "system_identifier",
        }
        if any(primary_slot[key] != promoted_slot.get(key) for key in comparable):
            reasons.append("logical_replication_slot_identity_changed_after_promotion")

    admitted = not reasons
    return {
        "schema": "gda.postgres_cdc_failover_continuity_admission.v1",
        "admitted": admitted,
        "disposition": "admitted" if admitted else "rejected_fail_closed",
        "reason_codes": sorted(set(reasons)),
        "system_identifier": (
            primary.get("system_identifier") if isinstance(primary, dict) else None
        ),
        "original_timeline_id": (
            primary.get("timeline_id") if isinstance(primary, dict) else None
        ),
        "promoted_timeline_id": (
            promoted.get("timeline_id") if isinstance(promoted, dict) else None
        ),
    }


def _failover_fault_checks(evidence: dict[str, Any]) -> dict[str, bool]:
    primary = evidence["primary_identity"]
    standby = evidence["standby_identity_before_promotion"]
    promoted = evidence["promoted_identity"]
    replay = evidence["standby_replay"]
    post_probe = evidence["post_promotion_probe"]
    admission = evidence["admission"]
    return {
        "physical_standby_was_built_and_streaming": (
            evidence["basebackup"]["completed"]
            and evidence["physical_replication"]["state"] == "streaming"
            and evidence["physical_replication"]["application_name"]
            == evidence["basebackup"]["application_name"]
            and standby["in_recovery"] is True
        ),
        "same_cluster_system_identifier_was_preserved": (
            primary["system_identifier"]
            == standby["system_identifier"]
            == promoted["system_identifier"]
        ),
        "exact_source_mutation_replayed_before_promotion": (
            evidence["event_sequence"]["source_mutated"]
            < evidence["event_sequence"]["standby_replay_reached_target"]
            < evidence["event_sequence"]["primary_stopped"]
            and _lsn_value(replay["replay_lsn"])
            >= _lsn_value(evidence["source_mutation"]["target_lsn"])
            and replay["row"] == evidence["source_mutation"]["row"]
            and evidence["mutation_replayed_before_promotion"]
        ),
        "pre_failover_sink_state_was_checkpoint_protected": (
            evidence["pre_failover_sink"]["accepted"] == 5
            and evidence["pre_failover_sink"]["rejected"] == 0
            and evidence["pre_failover_sink"]["checkpoint_count"] >= 5
        ),
        "primary_stop_preceded_standby_promotion": (
            evidence["event_sequence"]["primary_stopped"]
            < evidence["event_sequence"]["standby_promoted"]
            and evidence["primary_stop"]["stopped"]
            and evidence["primary_stopped_before_promotion"]
        ),
        "promotion_incremented_exactly_one_timeline": (
            promoted["timeline_id"] == primary["timeline_id"] + 1
            and promoted["in_recovery"] is False
        ),
        "promoted_source_preserved_publication_and_replayed_row": (
            evidence["publication_present_after_promotion"]
            and evidence["promoted_row"] == evidence["source_mutation"]["row"]
        ),
        "postgresql_16_promoted_source_lacked_original_logical_slot": (
            evidence["postgres_major_version"] == 16
            and evidence["primary_slot"]["exists"]
            and evidence["primary_slot"]["active"]
            and not evidence["promoted_slot"]["exists"]
        ),
        "controller_rejected_only_missing_slot_continuity": (
            not admission["admitted"]
            and admission["disposition"] == "rejected_fail_closed"
            and admission["reason_codes"]
            == ["logical_replication_slot_missing_after_promotion"]
            and evidence["event_sequence"]["admission_rejected"]
            < evidence["event_sequence"]["post_promotion_probe_mutated"]
            < evidence["event_sequence"]["runtime_terminated"]
        ),
        "stable_source_alias_moved_only_after_primary_stop": (
            evidence["source_alias_transfer"]["primary_detached"]
            and evidence["source_alias_transfer"]["standby_attached"]
            and evidence["source_alias_transfer"]["source_alias"]
            in evidence["source_alias_transfer"]["standby_network_aliases"]
            and evidence["event_sequence"]["primary_stopped"]
            < evidence["event_sequence"]["source_alias_transferred"]
        ),
        "post_promotion_probe_advanced_source_but_not_sink": (
            _lsn_value(post_probe["target_lsn"])
            > _lsn_value(evidence["source_mutation"]["target_lsn"])
            and post_probe["row"]["revision"]
            > evidence["source_mutation"]["row"]["revision"]
            and evidence["sink"]["accepted_after"]
            == evidence["sink"]["accepted_before"]
            and evidence["sink"]["rejected_after"]
            == evidence["sink"]["rejected_before"]
            and evidence["sink"]["post_failover_accepted_delta"] == 0
            and evidence["sink"]["post_failover_rejected_delta"] == 0
            and evidence["post_failover_observation_seconds"] >= 1.0
        ),
        "runtime_terminal_state_remained_separate_evidence": (
            evidence["runtime_termination"]["final_job_status"]
            in TERMINAL_FLINK_STATES
            and evidence["runtime_termination"]["origin"]
            == "controller_cancel_after_failover_admission_rejection"
        ),
    }


def _docker_volume_absent(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "volume", "inspect", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return completed.returncode != 0


def _container_network_aliases(name: str, network: str) -> list[str]:
    completed = _run_command(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            name,
        ],
        stage="inspect promoted PostgreSQL source aliases",
    )
    try:
        networks = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker network alias evidence is malformed") from exc
    attachment = networks.get(network)
    if not isinstance(attachment, dict):
        raise RuntimeError("promoted PostgreSQL source network evidence is missing")
    aliases = attachment.get("Aliases")
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) for alias in aliases
    ):
        raise RuntimeError("promoted PostgreSQL source aliases are missing")
    return sorted(set(aliases))


class PhysicalStandbySandbox:
    def __init__(
        self,
        *,
        source: CdcPostgresSandbox,
        image: str,
        network: str,
        token: str,
        source_alias: str,
    ) -> None:
        self.source = source
        self.image = image
        self.network = network
        self.source_alias = source_alias
        self.container = f"gda-cdc-standby-{token}"
        self.volume = f"gda-cdc-standby-data-{token}"
        self.application_name = f"gda_physical_standby_{token}"
        self.started = False
        self.volume_created = False
        for resource in (self.container, self.volume):
            if not STANDBY_RESOURCE_RE.fullmatch(resource):
                raise RuntimeError("generated physical standby resource is invalid")

    def _psql(self, sql: str) -> str:
        completed = _run_command(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={self.source.admin_password}",
                self.container,
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                self.source.admin_user,
                "-d",
                self.source.database,
                "-At",
                "-c",
                sql,
            ],
            stage="execute isolated PostgreSQL standby statement",
        )
        return completed.stdout

    def build_and_start(self) -> dict[str, Any]:
        _run_command(
            ["docker", "volume", "create", self.volume],
            stage="create isolated PostgreSQL standby volume",
        )
        self.volume_created = True
        _run_command(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self.volume}:/var/lib/postgresql/data",
                self.image,
                "chown",
                "postgres:postgres",
                "/var/lib/postgresql/data",
            ],
            stage="prepare isolated PostgreSQL standby volume ownership",
        )
        _run_command(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "postgres",
                "--network",
                self.network,
                "-e",
                f"PGPASSWORD={self.source.reader_password}",
                "-v",
                f"{self.volume}:/var/lib/postgresql/data",
                self.image,
                "pg_basebackup",
                "--host",
                self.source.container,
                "--port",
                "5432",
                "--username",
                self.source.reader_user,
                "--pgdata",
                "/var/lib/postgresql/data",
                "--write-recovery-conf",
                "--wal-method=stream",
                "--checkpoint=fast",
                "--no-password",
                "--dbname",
                (
                    f"host={self.source.container} port=5432 "
                    f"user={self.source.reader_user} "
                    f"application_name={self.application_name}"
                ),
            ],
            stage="build PostgreSQL physical standby with pg_basebackup",
            timeout=180,
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
                "-v",
                f"{self.volume}:/var/lib/postgresql/data",
                self.image,
                "postgres",
            ],
            stage="start PostgreSQL physical standby",
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
                    self.source.admin_user,
                    "-d",
                    self.source.database,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if ready.returncode == 0:
                identity = self.replication_identity()
                if identity["in_recovery"] is True:
                    return {
                        "completed": True,
                        "application_name": self.application_name,
                        "container": self.container,
                        "volume": self.volume,
                        "identity": identity,
                    }
            time.sleep(0.5)
        raise RuntimeError("PostgreSQL physical standby did not enter recovery")

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
            return dict(json.loads(payload))
        except json.JSONDecodeError as exc:
            raise RuntimeError("PostgreSQL standby identity is malformed") from exc

    def wait_for_replay(
        self,
        *,
        target_lsn: str,
        expected_row: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_identity: dict[str, Any] | None = None
        last_row: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last_identity = self.replication_identity()
            last_row = self.row(int(expected_row["road_id"]))
            replay_lsn = last_identity["replay_lsn"]
            if (
                replay_lsn
                and _lsn_value(replay_lsn) >= _lsn_value(target_lsn)
                and last_row == expected_row
            ):
                return {
                    "target_lsn": target_lsn,
                    "replay_lsn": replay_lsn,
                    "row": last_row,
                    "identity": last_identity,
                }
            time.sleep(0.25)
        raise RuntimeError(
            "PostgreSQL standby did not replay the exact source mutation: "
            f"identity={last_identity}, row={last_row}, target_lsn={target_lsn}"
        )

    def row(self, road_id: int) -> dict[str, Any]:
        value = self._psql(
            "SELECT road_id::text || E'\\t' || revision::text || E'\\t' || "
            "road_name_base64 || E'\\t' || geometry_sha256 "
            f"FROM public.{self.source.table} WHERE road_id = {road_id};"
        ).strip()
        fields = value.split("\t") if value else []
        if len(fields) != 4:
            raise RuntimeError("PostgreSQL standby source row is missing")
        return {
            "road_id": int(fields[0]),
            "revision": int(fields[1]),
            "road_name_base64": fields[2],
            "geometry_sha256": fields[3],
        }

    def slot_observation(self) -> dict[str, Any]:
        system_identifier = self.replication_identity()["system_identifier"]
        value = self._psql(
            "SELECT slot_name || E'\\t' || plugin || E'\\t' || slot_type || "
            "E'\\t' || database::text || E'\\t' || active::text "
            "FROM pg_replication_slots WHERE slot_name = "
            f"{_sql_literal(self.source.slot)};"
        ).strip()
        if not value:
            return {
                "exists": False,
                "slot_name": self.source.slot,
                "system_identifier": system_identifier,
            }
        fields = value.split("\t")
        if len(fields) != 5:
            raise RuntimeError("promoted PostgreSQL slot observation is malformed")
        return {
            "exists": True,
            "slot_name": fields[0],
            "plugin": fields[1],
            "slot_type": fields[2],
            "database_identity": fields[3],
            "active": fields[4] in {"t", "true"},
            "system_identifier": system_identifier,
        }

    def publication_present(self) -> bool:
        value = self._psql(
            "SELECT EXISTS(SELECT 1 FROM pg_publication WHERE pubname = "
            f"{_sql_literal(self.source.publication)})::text;"
        ).strip()
        return value in {"t", "true"}

    def promote(self, *, timeout: int) -> dict[str, Any]:
        _run_command(
            [
                "docker",
                "exec",
                "--user",
                "postgres",
                self.container,
                "pg_ctl",
                "-D",
                "/var/lib/postgresql/data",
                "promote",
                "-w",
                "-t",
                str(timeout),
            ],
            stage="promote PostgreSQL physical standby",
            timeout=timeout + 15,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            identity = self.replication_identity()
            if identity["in_recovery"] is False:
                self._psql("CHECKPOINT;")
                identity = self.replication_identity()
                return {"promoted": True, "identity": identity}
            time.sleep(0.25)
        raise RuntimeError("PostgreSQL standby promotion did not complete")

    def transfer_source_alias(self) -> dict[str, Any]:
        if _container_network_attached(self.container, self.network):
            _run_command(
                ["docker", "network", "disconnect", self.network, self.container],
                stage="detach promoted PostgreSQL source before alias transfer",
            )
        _run_command(
            [
                "docker",
                "network",
                "connect",
                "--alias",
                self.source_alias,
                self.network,
                self.container,
            ],
            stage="attach promoted PostgreSQL source alias",
        )
        attached = _container_network_attached(self.container, self.network)
        if not attached:
            raise RuntimeError("promoted PostgreSQL source alias was not attached")
        aliases = _container_network_aliases(self.container, self.network)
        if self.source_alias not in aliases:
            raise RuntimeError("promoted PostgreSQL stable source alias is missing")
        return {
            "source_alias": self.source_alias,
            "primary_detached": not _container_network_attached(
                self.source.container, self.network
            ),
            "standby_attached": attached,
            "standby_network_aliases": aliases,
        }

    def mutate_after_promotion(self, source_row: dict[str, Any]) -> dict[str, Any]:
        revision = int(source_row["revision"]) + 1
        self._psql(
            f"UPDATE public.{self.source.table} SET revision = {revision} "
            f"WHERE road_id = {int(source_row['road_id'])};"
        )
        return {
            "target_lsn": self.replication_identity()["observation_lsn"],
            "row": self.row(int(source_row["road_id"])),
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
        if self.volume_created and not _docker_volume_absent(self.volume):
            subprocess.run(
                ["docker", "volume", "rm", self.volume],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        return {
            "cdc_standby_container_removed": _container_absent(self.container),
            "cdc_standby_volume_removed": _docker_volume_absent(self.volume),
        }


def _physical_replication_observation(
    source: CdcPostgresSandbox,
    *,
    application_name: str,
    timeout: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        value = source._psql(
            "SELECT application_name || E'\\t' || state || E'\\t' || sync_state || "
            "E'\\t' || COALESCE(sent_lsn::text, '') || E'\\t' || "
            "COALESCE(write_lsn::text, '') || E'\\t' || "
            "COALESCE(flush_lsn::text, '') || E'\\t' || "
            "COALESCE(replay_lsn::text, '') FROM pg_stat_replication "
            f"WHERE application_name = {_sql_literal(application_name)};"
        ).strip()
        fields = value.split("\t") if value else []
        if len(fields) == 7:
            last = {
                "application_name": fields[0],
                "state": fields[1],
                "sync_state": fields[2],
                "sent_lsn": fields[3],
                "write_lsn": fields[4],
                "flush_lsn": fields[5],
                "replay_lsn": fields[6],
            }
            if last["state"] == "streaming":
                return last
        time.sleep(0.25)
    raise RuntimeError(
        "PostgreSQL physical replication did not become streaming: "
        f"observation={last}"
    )


def _enable_isolated_physical_replication(
    source: CdcPostgresSandbox,
) -> dict[str, Any]:
    hba_file = source._psql("SHOW hba_file;").strip()
    if not re.fullmatch(r"/var/lib/postgresql/data/[a-z0-9_.-]+", hba_file):
        raise RuntimeError("PostgreSQL HBA path escaped the isolated data directory")
    rule = (
        f"host replication {source.reader_user} samenet scram-sha-256"
    )
    _run_command(
        [
            "docker",
            "exec",
            "--user",
            "postgres",
            source.container,
            "sed",
            "-i",
            f"$a{rule}",
            hba_file,
        ],
        stage="enable isolated PostgreSQL physical replication access",
    )
    reloaded = source._psql("SELECT pg_reload_conf()::text;").strip()
    observation = source._psql(
        "SELECT type || E'\\t' || database::text || E'\\t' || "
        "user_name::text || E'\\t' || COALESCE(address, '') || E'\\t' || "
        "auth_method || E'\\t' || COALESCE(error, '<none>') "
        "FROM pg_hba_file_rules WHERE database = ARRAY['replication'] "
        f"AND user_name = ARRAY[{_sql_literal(source.reader_user)}] "
        "ORDER BY line_number DESC LIMIT 1;"
    ).strip()
    fields = observation.split("\t") if observation else []
    if (
        reloaded not in {"t", "true"}
        or len(fields) != 6
        or fields[0] != "host"
        or fields[3] != "samenet"
        or fields[4] != "scram-sha-256"
        or fields[5] != "<none>"
    ):
        raise RuntimeError(
            "isolated PostgreSQL physical replication HBA rule was not loaded: "
            f"reloaded={reloaded}, fields={fields}"
        )
    return {
        "database": "replication",
        "role": source.reader_user,
        "address_scope": "samenet",
        "auth_method": "scram-sha-256",
        "loaded": True,
        "rule_sha256": canonical_json_fingerprint({"rule": rule}),
    }


def _wait_for_checkpoint_count(
    flink: FlinkCdcSandbox,
    *,
    job_id: str,
    minimum_count: int,
    timeout: int,
) -> int:
    deadline = time.monotonic() + timeout
    maximum = 0
    while time.monotonic() < deadline:
        output = flink.task_output()
        counts = [int(count) for _, count in CHECKPOINT_RE.findall(output)]
        maximum = max(counts, default=0)
        if maximum >= minimum_count:
            return maximum
        status = flink.job_status(job_id)
        if status in TERMINAL_FLINK_STATES:
            raise RuntimeError(
                "Flink terminated before the pre-failover checkpoint: "
                f"status={status}, checkpoint_count={maximum}"
            )
        time.sleep(0.5)
    raise RuntimeError(
        "Flink did not checkpoint the pre-failover source mutation: "
        f"checkpoint_count={maximum}"
    )


def run_failover_provider(
    *,
    args: argparse.Namespace,
    work_dir: Path,
    token: str,
    plan: dict[str, Any],
    connector: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    jar_path = compile_flink_job(
        work_dir=work_dir,
        flink_image=args.flink_image,
        jdk_image=args.jdk_image,
        java_home=args.java_home,
        timeout=args.timeout_seconds,
        java_source=JAVA_SOURCE,
        main_class=MAIN_CLASS,
    )
    source_alias = f"gda-cdc-source-{token}"
    postgres = CdcPostgresSandbox(
        image=args.postgres_image,
        network=args.docker_network,
        token=token,
        network_alias=source_alias,
    )
    standby = PhysicalStandbySandbox(
        source=postgres,
        image=args.postgres_image,
        network=args.docker_network,
        token=token,
        source_alias=source_alias,
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
        postgres_start = postgres.start(plan["initial"])
        physical_replication_access = _enable_isolated_physical_replication(
            postgres
        )
        flink_cluster = flink.start()
        job_id = flink.submit(
            jar_path=jar_path,
            source=postgres,
            source_hostname=source_alias,
            fail_after_count=1_000_000,
        )
        initial_lines = flink.wait_for_output(
            expected=plan["milestone_counts"]["initial_snapshot_accepted"],
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        _wait_for_checkpoint_count(
            flink,
            job_id=job_id,
            minimum_count=len(initial_lines),
            timeout=args.timeout_seconds,
        )
        postgres.wait_for_slot_active(timeout=args.timeout_seconds)

        basebackup = standby.build_and_start()
        physical_replication = _physical_replication_observation(
            postgres,
            application_name=standby.application_name,
            timeout=args.timeout_seconds,
        )
        source_mutation = postgres.mutate_for_failover(plan)
        standby_replay = standby.wait_for_replay(
            target_lsn=source_mutation["target_lsn"],
            expected_row=source_mutation["row"],
            timeout=args.timeout_seconds,
        )
        pre_failover_lines = flink.wait_for_output(
            expected=5,
            job_id=job_id,
            timeout=args.timeout_seconds,
        )
        checkpoint_count = _wait_for_checkpoint_count(
            flink,
            job_id=job_id,
            minimum_count=len(pre_failover_lines),
            timeout=args.timeout_seconds,
        )
        accepted_before, accepted_files_before = _committed_lines(
            work_dir / "silver/v1/changelog"
        )
        rejected_before, rejected_files_before = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        primary_identity = postgres.replication_identity()
        standby_identity = standby.replication_identity()
        primary_slot = postgres.slot_observation()

        primary_stop = postgres.stop(timeout=args.primary_stop_timeout_seconds)
        primary_detach = postgres.disconnect_network()
        promotion = standby.promote(timeout=args.promotion_timeout_seconds)
        promoted_identity = promotion["identity"]
        promoted_slot = standby.slot_observation()
        publication_present = standby.publication_present()
        promoted_row = standby.row(int(source_mutation["row"]["road_id"]))
        admission_evidence = {
            "primary_identity": primary_identity,
            "standby_identity_before_promotion": standby_identity,
            "promoted_identity": promoted_identity,
            "primary_slot": primary_slot,
            "promoted_slot": promoted_slot,
            "mutation_replayed_before_promotion": True,
            "primary_stopped_before_promotion": True,
            "publication_present_after_promotion": publication_present,
        }
        admission = assess_failover_continuity(admission_evidence)
        if admission["admitted"]:
            raise RuntimeError("controller admitted failover without slot continuity")

        alias_transfer = standby.transfer_source_alias()
        post_probe = standby.mutate_after_promotion(source_mutation["row"])
        time.sleep(args.post_failover_observation_seconds)
        status_before_cancel = flink.job_status(job_id)
        exceptions_before_cancel = _exception_summary(flink.job_exceptions(job_id))
        final_status = flink.cancel(job_id, timeout=args.timeout_seconds)
        exceptions_after_cancel = _exception_summary(flink.job_exceptions(job_id))
        accepted_after, accepted_files_after = _committed_lines(
            work_dir / "silver/v1/changelog"
        )
        rejected_after, rejected_files_after = _committed_lines(
            work_dir / "quarantine/v1/rejected"
        )
        failover = {
            "event_sequence": {
                "initial_checkpoint_completed": 1,
                "physical_basebackup_completed": 2,
                "source_mutated": 3,
                "standby_replay_reached_target": 4,
                "pre_failover_sink_checkpoint_completed": 5,
                "primary_stopped": 6,
                "standby_promoted": 7,
                "admission_rejected": 8,
                "source_alias_transferred": 9,
                "post_promotion_probe_mutated": 10,
                "runtime_terminated": 11,
            },
            "postgres_major_version": int(postgres_start["version"].split(".", 1)[0]),
            "basebackup": basebackup,
            "physical_replication_access": physical_replication_access,
            "physical_replication": physical_replication,
            "source_mutation": source_mutation,
            "standby_replay": standby_replay,
            "primary_identity": primary_identity,
            "standby_identity_before_promotion": standby_identity,
            "primary_slot": primary_slot,
            "pre_failover_sink": {
                "accepted": len(accepted_before),
                "rejected": len(rejected_before),
                "checkpoint_count": checkpoint_count,
                "accepted_files": accepted_files_before,
                "rejected_files": rejected_files_before,
            },
            "primary_stop": primary_stop,
            "primary_network_detach": primary_detach,
            "primary_stopped_before_promotion": True,
            "promotion": promotion,
            "promoted_identity": promoted_identity,
            "promoted_slot": promoted_slot,
            "publication_present_after_promotion": publication_present,
            "promoted_row": promoted_row,
            "mutation_replayed_before_promotion": True,
            "admission": admission,
            "source_alias_transfer": alias_transfer,
            "post_promotion_probe": post_probe,
            "post_failover_observation_seconds": (
                args.post_failover_observation_seconds
            ),
            "runtime_termination": {
                "status_before_controller_cancel": status_before_cancel,
                "final_job_status": final_status,
                "origin": "controller_cancel_after_failover_admission_rejection",
                "exceptions_before_cancel": exceptions_before_cancel,
                "exceptions_after_cancel": exceptions_after_cancel,
            },
            "sink": {
                "accepted_before": len(accepted_before),
                "accepted_after": len(accepted_after),
                "rejected_before": len(rejected_before),
                "rejected_after": len(rejected_after),
                "post_failover_accepted_delta": len(accepted_after)
                - len(accepted_before),
                "post_failover_rejected_delta": len(rejected_after)
                - len(rejected_before),
                "accepted_files_after": accepted_files_after,
                "accepted_manifest_sha256": canonical_json_fingerprint(
                    accepted_files_after
                ),
                "rejected_files_after": rejected_files_after,
                "rejected_manifest_sha256": canonical_json_fingerprint(
                    rejected_files_after
                ),
            },
        }
        checks = _failover_fault_checks(failover)
        return (
            {
                "schema": "gda.postgres_cdc_physical_failover_provider.negative.v1",
                "status": "passed" if all(checks.values()) else "failed",
                "expected_outcome": "rejected_fail_closed",
                "checks": checks,
                "failover": failover,
                "postgres": {
                    **postgres_start,
                    "image": args.postgres_image,
                    "image_id": docker_image_id(
                        args.postgres_image, timeout=args.timeout_seconds
                    ),
                    "publication": postgres.publication,
                    "source_alias": source_alias,
                },
                "runtime": {
                    "flink_image": args.flink_image,
                    "flink_image_id": docker_image_id(
                        args.flink_image, timeout=args.timeout_seconds
                    ),
                    "cluster": flink_cluster,
                    "connector": connector,
                    "job_source_sha256": _sha256_file(JAVA_SOURCE),
                    "job_jar_sha256": _sha256_file(jar_path),
                },
            },
            cleanup,
        )
    finally:
        cleanup.update(flink.cleanup())
        cleanup.update(standby.cleanup())
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
    run_id = uuid4()
    gateway = PlatformGateway(engine)
    authority = SourceSyncAuthority(engine)
    gateway.register_definition(
        _definition_registration(
            "local-dev", platform_definition_id, namespace, now
        )
    )
    failover_policy = {
        "schema": "gda.postgres_cdc_failover_admission_policy.v1",
        "require_same_system_identifier": True,
        "require_timeline_increment": True,
        "require_exact_mutation_replay": True,
        "require_logical_slot_continuity": True,
        "on_missing_continuity": "reject_fail_closed",
    }
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
        additional_config={"failover_admission_policy": failover_policy},
    )
    initial_cursor = {"change_set_sequence": 0, "source_slice_sha256": None}
    definition_write = authority.create_definition(
        definition,
        owner_ref="team:data-platform",
        initial_cursor=initial_cursor,
    )
    running = _submit_run(
        gateway,
        _run(
            "local-dev",
            run_id,
            platform_definition_id,
            now,
            sequence=f"{namespace}:physical-failover-negative",
        ),
    )
    preflight = authority.find_source_slice_commit(
        "local-dev",
        sync_definition_version_id,
        previous_cursor=initial_cursor,
        next_cursor={
            "change_set_sequence": 1,
            "source_slice_sha256": plan["source_slice_sha256"],
        },
        source_slice_sha256=plan["source_slice_sha256"],
    )
    provider, provider_cleanup = run_failover_provider(
        args=args,
        work_dir=work_dir,
        token=token,
        plan=plan,
        connector=connector,
    )
    admission = provider["failover"]["admission"]
    if provider["status"] != "passed" or admission["admitted"]:
        failed_provider_checks = sorted(
            name for name, passed in provider["checks"].items() if not passed
        )
        raise RuntimeError(
            "PostgreSQL failover provider did not produce expected rejection: "
            f"failed_checks={failed_provider_checks}, "
            f"reason_codes={admission['reason_codes']}"
        )
    failed_run = gateway.transition_run(
        "local-dev",
        run_id,
        running.state_version,
        "failed",
        WORKLOAD,
        "logical replication slot continuity missing after physical failover",
        details={
            "schema": admission["schema"],
            "disposition": admission["disposition"],
            "reason_codes": admission["reason_codes"],
            "system_identifier": admission["system_identifier"],
            "original_timeline_id": admission["original_timeline_id"],
            "promoted_timeline_id": admission["promoted_timeline_id"],
        },
    )
    checkpoint = authority.get_checkpoint(
        "local-dev", sync_definition_version_id
    )
    commits = authority.commits("local-dev", sync_definition_version_id)
    success_counts = _success_evidence_counts(
        engine,
        run_id=run_id,
        sync_definition_version_id=sync_definition_version_id,
        target_urn=definition.target_resource_urn,
    )
    checks = {
        "failover_policy_bound_to_definition_and_checkpoint_zero": (
            definition_write.created
            and definition.config["failover_admission_policy"] == failover_policy
            and definition_write.checkpoint.state_version == 0
            and definition_write.checkpoint.cursor == initial_cursor
        ),
        "provider_preflight_was_empty": preflight is None,
        "physical_postgresql_failover_negative_provider_passed": all(
            provider["checks"].values()
        ),
        "missing_promoted_logical_slot_rejected_fail_closed": (
            not admission["admitted"]
            and admission["disposition"] == "rejected_fail_closed"
            and admission["reason_codes"]
            == ["logical_replication_slot_missing_after_promotion"]
        ),
        "source_sync_checkpoint_remained_zero": (
            checkpoint.state_version == 0
            and checkpoint.cursor == initial_cursor
            and checkpoint.last_sync_commit_id is None
        ),
        "source_sync_commit_history_remained_empty": len(commits) == 0,
        "no_provider_success_evidence_fabricated": all(
            value == 0 for value in success_counts.values()
        ),
        "platform_run_failed_with_no_success_admission": (
            failed_run.status.value == "failed"
            and failed_run.state_version == running.state_version + 1
        ),
        "post_failover_physical_sink_remained_stable": provider["checks"][
            "post_promotion_probe_advanced_source_but_not_sink"
        ],
    }
    return (
        {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_physical_failover."
                "negative_acceptance.v1"
            ),
            "status": "passed" if all(checks.values()) else "failed",
            "expected_outcome": "rejected_fail_closed",
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "source": {
                **plan["source"],
                "source_slice_sha256": plan["source_slice_sha256"],
            },
            "provider": provider,
            "authority": {
                "sync_definition_version_id": str(sync_definition_version_id),
                "run": failed_run.model_dump(mode="json"),
                "checkpoint": checkpoint.model_dump(mode="json"),
                "commits": [],
                "success_evidence_counts": success_counts,
                "failover_admission_policy": failover_policy,
                "diagnostic_provider_invocations": 1,
                "successful_provider_admissions": 0,
            },
            "not_claimed": [
                "automatic logical replication slot synchronization or repair",
                "automatic CDC resume after PostgreSQL promotion",
                "production RPO, RTO, throughput, or freshness SLO",
                "multi-cluster high availability or Kubernetes recovery",
                "external durable event boundary or distributed exactly-once commit",
            ],
        },
        provider_cleanup,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres-url", default="postgresql://127.0.0.1:5433/gis_agent"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--connector", type=Path, default=DEFAULT_CONNECTOR)
    parser.add_argument("--flink-image", default=DEFAULT_FLINK_IMAGE)
    parser.add_argument("--jdk-image", default=DEFAULT_JDK_IMAGE)
    parser.add_argument("--java-home", default=DEFAULT_JAVA_HOME)
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--docker-network", default=DEFAULT_NETWORK)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--primary-stop-timeout-seconds", type=int, default=30)
    parser.add_argument("--promotion-timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--post-failover-observation-seconds", type=float, default=2.0
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if not 10 <= args.primary_stop_timeout_seconds <= 60:
        parser.error("--primary-stop-timeout-seconds must be between 10 and 60")
    if not 10 <= args.promotion_timeout_seconds <= 120:
        parser.error("--promotion-timeout-seconds must be between 10 and 120")
    if not 1.0 <= args.post_failover_observation_seconds <= 10.0:
        parser.error(
            "--post-failover-observation-seconds must be between 1 and 10"
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
    namespace = f"chongqing_osm_cdc_failover_{token}"
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
        cleanup["primary_container_removed"] = _container_absent(
            f"gda-cdc-pg-{token}"
        )
        cleanup["flink_container_removed"] = _container_absent(
            f"gda-cdc-flink-{token}"
        )
        cleanup["standby_container_removed"] = _container_absent(
            f"gda-cdc-standby-{token}"
        )
        cleanup["standby_volume_removed"] = _docker_volume_absent(
            f"gda-cdc-standby-data-{token}"
        )
    main_counts_after = main_sync_counts(admin_url)
    cleanup["main_sync_tables_unchanged_empty"] = (
        main_counts_before == (0, 0, 0) and main_counts_after == (0, 0, 0)
    )
    if report is None:
        report = {
            "schema": (
                "gda.chongqing_osm_postgres_cdc_physical_failover."
                "negative_acceptance.v1"
            ),
            "status": "failed",
            "expected_outcome": "rejected_fail_closed",
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
                "expected_outcome": report["expected_outcome"],
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
