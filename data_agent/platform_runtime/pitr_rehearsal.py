"""Fail-closed physical backup and streamed-WAL PITR rehearsal for Compose."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .deployment_profile import DeploymentProfile
from .recovery_rehearsal import (
    RECOVERY_LIMITATIONS,
    RecoveryContract,
    collect_database_state,
    database_logical_identity,
    resolve_recovery_contract,
)
from .runtime_probe import DeploymentProfileVerifier

REPORT_SCHEMA = "gis-data-agent.pitr-rehearsal.v1"
PITR_SCOPE = "compose_isolated_streamed_wal_pitr"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
CONTAINER_RE = re.compile(r"^gda-pitr-[a-z]+-[0-9a-f]{12}$")
NETWORK_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
LSN_RE = re.compile(r"^[0-9A-F]+/[0-9A-F]+$")
WAL_SEGMENT_RE = re.compile(r"^[0-9A-F]{24}$")
CLIENT_ENTRYPOINT = (
    "set -eu; chown postgres:postgres /run/gda-pgpass; "
    'chmod 600 /run/gda-pgpass; exec gosu postgres "$@"'
)
PITR_LIMITATIONS = tuple(
    dict.fromkeys(
        (
            *RECOVERY_LIMITATIONS,
            "continuous_wal_archiving_not_configured",
            "replication_slot_monitoring_not_configured",
            "restore_failover_not_proven",
            "object_storage_pitr_not_proven",
        )
    )
)


class PITRRehearsalError(RuntimeError):
    """A PITR stage failed without exposing command output or credentials."""

    def __init__(self, stage: str):
        super().__init__(f"PITR rehearsal failed at {stage}")
        self.stage = stage


@dataclass(frozen=True)
class PITRContract:
    database: RecoveryContract
    network_name: str
    database_password: str = field(repr=False)


def failure_report(
    *, profile_id: str | None, stage: str, error_type: str
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "profile_id": profile_id,
        "technical_pass": False,
        "promotion_ready": False,
        "failed_stage": stage,
        "error_type": error_type,
        "promotion_blockers": list(PITR_LIMITATIONS),
    }


def resolve_pitr_contract(
    profile: DeploymentProfile, compose_model: dict[str, Any]
) -> PITRContract:
    database = resolve_recovery_contract(profile, compose_model)
    services = compose_model.get("services") or {}
    environment = (services.get(database.database_service) or {}).get(
        "environment"
    ) or {}
    password = environment.get("POSTGRES_PASSWORD")
    network = (compose_model.get("networks") or {}).get(profile.compose.network) or {}
    network_name = network.get("name")
    if not isinstance(password, str) or not password:
        raise PITRRehearsalError("contract.database_auth")
    if not isinstance(network_name, str) or not NETWORK_RE.fullmatch(network_name):
        raise PITRRehearsalError("contract.network")
    return PITRContract(
        database=database,
        network_name=network_name,
        database_password=password,
    )


def pgpass_line(contract: PITRContract) -> str:
    """Render libpq credentials without putting the password in a command."""
    password = contract.database_password.replace("\\", "\\\\").replace(
        ":", "\\:"
    )
    database = contract.database
    return (
        f"127.0.0.1:5432:*:{database.database_user}:{password}\n"
    )


def recovery_settings(target_time: datetime) -> str:
    """Render a bounded target configuration for a network-isolated clone."""
    if target_time.tzinfo is None or target_time.utcoffset() is None:
        raise PITRRehearsalError("recovery.target_timezone")
    timestamp = target_time.astimezone(UTC).isoformat()
    return (
        "\n# GIS Data Agent isolated PITR rehearsal\n"
        "restore_command = 'cp /recovery-wal/%f %p'\n"
        f"recovery_target_time = '{timestamp}'\n"
        "recovery_target_inclusive = 'true'\n"
        "recovery_target_action = 'promote'\n"
        "recovery_target_timeline = 'latest'\n"
    )


class ComposePITRRehearsal:
    """Recover a real cluster to a transaction after its physical base backup."""

    def __init__(
        self,
        *,
        profile: DeploymentProfile,
        profile_path: Path,
        repo_root: Path,
    ) -> None:
        self.profile = profile
        self.profile_path = profile_path.resolve()
        self.repo_root = repo_root.resolve()
        self._slot_name: str | None = None
        self._probe_database: str | None = None
        self._database_container_id: str | None = None
        self._containers: dict[str, str] = {}

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        deployment = DeploymentProfileVerifier(
            profile=self.profile,
            profile_path=self.profile_path,
            repo_root=self.repo_root,
        ).verify()
        if not deployment.technical_pass or deployment.profile_contamination:
            raise PITRRehearsalError("deployment_verification")

        compose_model = self._compose_model()
        contract = resolve_pitr_contract(self.profile, compose_model)
        self._database_container_id = self._resolve_database_container(contract)
        source_capability = self._source_capability(contract)
        self._validate_source_capability(source_capability)
        self._allocate_identities()

        with tempfile.TemporaryDirectory(prefix="gda-pitr-") as temp_name:
            work_dir = Path(temp_name)
            pgpass_path = work_dir / "pgpass"
            pgpass_path.write_text(pgpass_line(contract), encoding="utf-8")
            pgpass_path.chmod(0o600)
            work_dir.chmod(0o755)
            for directory in (work_dir / "base", work_dir / "wal"):
                directory.mkdir()
                directory.chmod(0o777)
            try:
                result = self._run_rehearsal(contract, work_dir, pgpass_path)
            except Exception:
                self._best_effort_cleanup(contract)
                raise
            else:
                self._best_effort_cleanup(contract)
                self._assert_cleanup(contract)

        blockers = list(
            dict.fromkeys(
                (*self.profile.governance.promotion_blockers, *PITR_LIMITATIONS)
            )
        )
        return {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "profile_id": self.profile.profile_id,
            "environment": self.profile.environment,
            "scope": PITR_SCOPE,
            "technical_pass": True,
            "promotion_ready": False,
            "promotion_blockers": blockers,
            "deployment": {
                "technical_pass": deployment.technical_pass,
                "profile_contamination": deployment.profile_contamination,
            },
            "source_capability": source_capability,
            **result,
            "cleanup": {
                "probe_database_removed": True,
                "replication_slot_removed": True,
                "temporary_containers_removed": True,
                "temporary_media_retained": False,
            },
            "observed_total_seconds": round(time.monotonic() - started, 3),
            "rpo_status": "not_defined",
            "rto_status": "not_approved",
        }

    def _run_rehearsal(
        self, contract: PITRContract, work_dir: Path, pgpass_path: Path
    ) -> dict[str, Any]:
        self._prepare_probe(contract)
        self._create_slot(contract)
        backup = self._base_backup(contract, work_dir, pgpass_path)
        source_state = self._database_state(contract, container=None)
        verification_seconds = self._verify_base_backup(contract, work_dir)
        wal_stream, target_time = self._stream_target_wal(
            contract, work_dir, pgpass_path
        )
        self._configure_recovery(work_dir, target_time)
        restored_state, recovery = self._recover_target(contract, work_dir)
        if database_logical_identity(source_state) != database_logical_identity(
            restored_state
        ):
            raise PITRRehearsalError("recovery.database_identity")
        return {
            "physical_backup": {
                **backup,
                "manifest_verified": True,
                "manifest_verification_seconds": round(verification_seconds, 3),
                "artifact_retained": False,
            },
            "wal_stream": wal_stream,
            "target_recovery": recovery,
            "database": {
                "source": source_state,
                "restored": restored_state,
            },
        }

    def _compose_command(self, *args: str) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.profile.compose.project_name,
        ]
        for compose_file in self.profile.compose.files:
            command.extend(("-f", compose_file))
        for compose_profile in self.profile.compose.model_profiles:
            command.extend(("--profile", compose_profile))
        command.extend(args)
        return command

    def _compose_model(self) -> dict[str, Any]:
        output = self._run_text(
            self._compose_command("config", "--format", "json"),
            stage="compose.config",
        )
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PITRRehearsalError("compose.config_json") from exc
        if not isinstance(value, dict):
            raise PITRRehearsalError("compose.config_shape")
        return value

    def _allocate_identities(self) -> None:
        token = secrets.token_hex(6)
        slot_name = f"gda_pitr_{token}"
        probe_database = f"gda_pitr_probe_{token}"
        containers = {
            stage: f"gda-pitr-{stage}-{token}"
            for stage in ("backup", "verify", "receiver", "restore")
        }
        if (
            not IDENTIFIER_RE.fullmatch(slot_name)
            or not IDENTIFIER_RE.fullmatch(probe_database)
            or any(not CONTAINER_RE.fullmatch(name) for name in containers.values())
        ):
            raise PITRRehearsalError("identity")
        self._slot_name = slot_name
        self._probe_database = probe_database
        self._containers = containers

    def _resolve_database_container(self, contract: PITRContract) -> str:
        container_id = self._run_text(
            self._compose_command(
                "ps", "--quiet", contract.database.database_service
            ),
            stage="source.container",
        ).strip()
        if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
            raise PITRRehearsalError("source.container_identity")
        return container_id

    def _source_capability(self, contract: PITRContract) -> dict[str, Any]:
        raw = self._source_psql(
            contract,
            """
            SELECT json_build_object(
                'server_version_num', current_setting('server_version_num')::int,
                'server_version', current_setting('server_version'),
                'wal_level', current_setting('wal_level'),
                'archive_mode', current_setting('archive_mode'),
                'max_wal_senders', current_setting('max_wal_senders')::int,
                'max_replication_slots', current_setting('max_replication_slots')::int,
                'in_recovery', pg_is_in_recovery()
            )::text
            """,
            database="postgres",
        )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PITRRehearsalError("source.capability_json") from exc
        if not isinstance(value, dict):
            raise PITRRehearsalError("source.capability_shape")
        return value

    @staticmethod
    def _validate_source_capability(value: dict[str, Any]) -> None:
        if (
            int(value.get("server_version_num") or 0) < 120000
            or value.get("wal_level") not in {"replica", "logical"}
            or int(value.get("max_wal_senders") or 0) < 2
            or int(value.get("max_replication_slots") or 0) < 1
            or value.get("in_recovery") is not False
        ):
            raise PITRRehearsalError("source.capability")

    def _prepare_probe(self, contract: PITRContract) -> None:
        probe = self._required_probe_database()
        self._source_psql(
            contract,
            f'CREATE DATABASE "{probe}" TEMPLATE template0',
            database="postgres",
        )
        self._source_psql(
            contract,
            """
            CREATE TABLE pitr_marker (
                id integer PRIMARY KEY CHECK (id = 1),
                phase text NOT NULL
            );
            INSERT INTO pitr_marker (id, phase) VALUES (1, 'base');
            """,
            database=probe,
        )

    def _create_slot(self, contract: PITRContract) -> None:
        slot = self._required_slot_name()
        created = self._source_psql(
            contract,
            f"SELECT slot_name FROM pg_create_physical_replication_slot('{slot}', true, false)",
            database="postgres",
        )
        if created != slot:
            raise PITRRehearsalError("wal.slot_create")

    def _base_backup(
        self, contract: PITRContract, work_dir: Path, pgpass_path: Path
    ) -> dict[str, Any]:
        name = self._containers["backup"]
        self._create_client_container(
            name=name,
            contract=contract,
            work_dir=work_dir,
            pgpass_path=pgpass_path,
            client_args=[
                "pg_basebackup",
                "--pgdata=/recovery/base",
                "--format=plain",
                "--wal-method=stream",
                f"--slot={self._required_slot_name()}",
                "--checkpoint=fast",
                "--manifest-checksums=SHA256",
                "--no-password",
            ],
        )
        started = time.monotonic()
        self._start_attached(name, stage="backup.base", timeout=7200)
        duration = time.monotonic() - started
        base_dir = work_dir / "base"
        manifest = base_dir / "backup_manifest"
        if not (base_dir / "PG_VERSION").is_file() or not manifest.is_file():
            raise PITRRehearsalError("backup.artifacts")
        return {
            "duration_seconds": round(duration, 3),
            "bytes": _tree_bytes(base_dir),
            "manifest_sha256": _sha256_file(manifest),
        }

    def _verify_base_backup(self, contract: PITRContract, work_dir: Path) -> float:
        name = self._containers["verify"]
        self._run_text(
            [
                "docker",
                "create",
                "--name",
                name,
                "--network",
                "none",
                "--volume",
                f"{work_dir}:/recovery",
                "--entrypoint",
                "pg_verifybackup",
                contract.database.database_image,
                "/recovery/base",
            ],
            stage="backup.verify_create",
        )
        started = time.monotonic()
        self._start_attached(name, stage="backup.verify", timeout=7200)
        return time.monotonic() - started

    def _stream_target_wal(
        self, contract: PITRContract, work_dir: Path, pgpass_path: Path
    ) -> tuple[dict[str, Any], datetime]:
        name = self._containers["receiver"]
        self._create_client_container(
            name=name,
            contract=contract,
            work_dir=work_dir,
            pgpass_path=pgpass_path,
            client_args=[
                "pg_receivewal",
                "--directory=/recovery/wal",
                f"--slot={self._required_slot_name()}",
                "--synchronous",
                "--no-password",
            ],
        )
        started = time.monotonic()
        self._run_text(["docker", "start", name], stage="wal.receiver_start")
        self._wait_receiver_active(contract)

        probe = self._required_probe_database()
        self._source_psql(
            contract,
            "UPDATE pitr_marker SET phase = 'target' WHERE id = 1",
            database=probe,
        )
        target_time, target_lsn = self._current_time_lsn(contract)
        time.sleep(1)
        self._source_psql(
            contract,
            "UPDATE pitr_marker SET phase = 'after_target' WHERE id = 1",
            database=probe,
        )
        later_time, later_lsn = self._current_time_lsn(contract)
        if not target_time < later_time:
            raise PITRRehearsalError("wal.timeline_order")
        self._source_psql(contract, "SELECT pg_switch_wal()", database="postgres")
        self._wait_slot_flush(contract, later_lsn)
        source_phase = self._source_psql(
            contract,
            "SELECT phase FROM pitr_marker WHERE id = 1",
            database=probe,
        )
        if source_phase != "after_target":
            raise PITRRehearsalError("wal.source_later_state")
        self._stop_container(name, stage="wal.receiver_stop")
        wal_facts = _wal_directory_facts(work_dir / "wal")
        return (
            {
                **wal_facts,
                "duration_seconds": round(time.monotonic() - started, 3),
                "target_after_base_backup": True,
                "target_timestamp": target_time.isoformat(),
                "later_timestamp": later_time.isoformat(),
                "target_lsn_observed": bool(target_lsn),
                "later_lsn_observed": bool(later_lsn),
                "source_later_state_observed": True,
                "continuous_archive_configured": False,
            },
            target_time,
        )

    def _configure_recovery(self, work_dir: Path, target_time: datetime) -> None:
        data_dir = work_dir / "base"
        auto_conf = data_dir / "postgresql.auto.conf"
        with auto_conf.open("a", encoding="utf-8") as output:
            output.write(recovery_settings(target_time))
        (data_dir / "recovery.signal").write_bytes(b"")

    def _recover_target(
        self, contract: PITRContract, work_dir: Path
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        name = self._containers["restore"]
        self._run_text(
            [
                "docker",
                "create",
                "--name",
                name,
                "--network",
                "none",
                "--volume",
                f"{work_dir / 'base'}:/var/lib/postgresql/data",
                "--volume",
                f"{work_dir / 'wal'}:/recovery-wal:ro",
                contract.database.database_image,
            ],
            stage="recovery.container_create",
        )
        started = time.monotonic()
        self._run_text(["docker", "start", name], stage="recovery.container_start")
        self._wait_postgres(contract, name)
        phase = self._container_psql(
            contract,
            name,
            "SELECT phase FROM pitr_marker WHERE id = 1",
            database=self._required_probe_database(),
        )
        if phase != "target":
            raise PITRRehearsalError("recovery.target_state")
        in_recovery = self._container_psql(
            contract,
            name,
            "SELECT pg_is_in_recovery()",
            database="postgres",
        )
        if in_recovery != "f":
            raise PITRRehearsalError("recovery.not_promoted")
        state = self._database_state(contract, container=name)
        return state, {
            "duration_seconds": round(time.monotonic() - started, 3),
            "restored_target_state_observed": True,
            "later_state_excluded": True,
            "promoted": True,
            "network_isolated": True,
        }

    def _create_client_container(
        self,
        *,
        name: str,
        contract: PITRContract,
        work_dir: Path,
        pgpass_path: Path,
        client_args: list[str],
    ) -> None:
        database = contract.database
        self._run_text(
            [
                "docker",
                "create",
                "--name",
                name,
                "--user",
                "root",
                "--network",
                f"container:{self._required_database_container_id()}",
                "--volume",
                f"{work_dir}:/recovery",
                "--env",
                "PGPASSFILE=/run/gda-pgpass",
                "--env",
                "PGHOST=127.0.0.1",
                "--env",
                "PGPORT=5432",
                "--env",
                f"PGUSER={database.database_user}",
                "--env",
                "PGDATABASE=postgres",
                "--entrypoint",
                "/bin/sh",
                database.database_image,
                "-c",
                CLIENT_ENTRYPOINT,
                "--",
                *client_args,
            ],
            stage="client.container_create",
        )
        self._run_text(
            ["docker", "cp", str(pgpass_path), f"{name}:/run/gda-pgpass"],
            stage="client.credential_copy",
        )

    def _start_attached(self, name: str, *, stage: str, timeout: int) -> None:
        self._run_text(
            ["docker", "start", "--attach", name], stage=stage, timeout=timeout
        )

    def _wait_receiver_active(self, contract: PITRContract) -> None:
        slot = self._required_slot_name()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            active = self._source_psql(
                contract,
                f"SELECT active FROM pg_replication_slots WHERE slot_name = '{slot}'",
                database="postgres",
            )
            if active == "t":
                return
            if not self._container_running(self._containers["receiver"]):
                raise PITRRehearsalError("wal.receiver_exited")
            time.sleep(1)
        raise PITRRehearsalError("wal.receiver_readiness")

    def _wait_slot_flush(self, contract: PITRContract, required_lsn: str) -> None:
        if not LSN_RE.fullmatch(required_lsn):
            raise PITRRehearsalError("wal.lsn")
        slot = self._required_slot_name()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            caught_up = self._source_psql(
                contract,
                f"""
                SELECT COALESCE(
                    pg_wal_lsn_diff(restart_lsn, '{required_lsn}') >= 0,
                    false
                )
                FROM pg_replication_slots
                WHERE slot_name = '{slot}'
                """,
                database="postgres",
            )
            if caught_up == "t":
                return
            if not self._container_running(self._containers["receiver"]):
                raise PITRRehearsalError("wal.receiver_exited")
            time.sleep(1)
        raise PITRRehearsalError("wal.receiver_flush")

    def _current_time_lsn(self, contract: PITRContract) -> tuple[datetime, str]:
        raw = self._source_psql(
            contract,
            "SELECT clock_timestamp()::text, pg_current_wal_flush_lsn()::text",
            database="postgres",
        )
        parts = raw.split("\t")
        if len(parts) != 2 or not LSN_RE.fullmatch(parts[1]):
            raise PITRRehearsalError("wal.timeline_fact")
        try:
            timestamp = datetime.fromisoformat(parts[0])
        except ValueError as exc:
            raise PITRRehearsalError("wal.timeline_timestamp") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise PITRRehearsalError("wal.timeline_timezone")
        return timestamp.astimezone(UTC), parts[1]

    def _database_state(
        self, contract: PITRContract, *, container: str | None
    ) -> dict[str, Any]:
        return collect_database_state(
            profile=self.profile,
            query=lambda sql, database: (
                self._container_psql(
                    contract,
                    container,
                    sql,
                    database=database or contract.database.database_name,
                )
                if container
                else self._source_psql(
                    contract,
                    sql,
                    database=database or contract.database.database_name,
                )
            ),
        )

    def _source_psql(
        self,
        contract: PITRContract,
        sql: str,
        *,
        database: str,
    ) -> str:
        command = self._compose_command(
            "exec",
            "-T",
            contract.database.database_service,
            *self._psql_args(contract, sql, database),
        )
        return self._run_text(command, stage="source.query").strip()

    def _container_psql(
        self,
        contract: PITRContract,
        container: str,
        sql: str,
        *,
        database: str,
    ) -> str:
        return self._run_text(
            ["docker", "exec", container, *self._psql_args(contract, sql, database)],
            stage="recovery.query",
        ).strip()

    @staticmethod
    def _psql_args(contract: PITRContract, sql: str, database: str) -> list[str]:
        return [
            "psql",
            "--no-psqlrc",
            "--set",
            "ON_ERROR_STOP=1",
            "--username",
            contract.database.database_user,
            "--dbname",
            database,
            "--tuples-only",
            "--no-align",
            "--field-separator=\t",
            "--command",
            sql,
        ]

    def _wait_postgres(
        self, contract: PITRContract, container: str
    ) -> None:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            completed = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_isready",
                    "--username",
                    contract.database.database_user,
                    "--dbname",
                    "postgres",
                ],
                cwd=self.repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            if completed.returncode == 0:
                return
            if not self._container_running(container):
                raise PITRRehearsalError("recovery.container_exited")
            time.sleep(1)
        raise PITRRehearsalError("recovery.readiness")

    def _stop_container(self, name: str, *, stage: str) -> None:
        if self._container_running(name):
            self._run_text(
                ["docker", "stop", "--time", "30", name], stage=stage, timeout=60
            )

    def _container_running(self, name: str) -> bool:
        completed = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return completed.returncode == 0 and completed.stdout.strip() == "true"

    def _best_effort_cleanup(self, contract: PITRContract) -> None:
        receiver = self._containers.get("receiver")
        if receiver:
            try:
                self._stop_container(receiver, stage="cleanup.receiver_stop")
            except (OSError, subprocess.TimeoutExpired, PITRRehearsalError):
                pass
        for name in self._containers.values():
            try:
                subprocess.run(
                    ["docker", "rm", "--force", "--volumes", name],
                    cwd=self.repo_root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=120,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        slot = self._slot_name
        if slot:
            for _ in range(5):
                try:
                    active = self._source_psql(
                        contract,
                        f"SELECT active FROM pg_replication_slots WHERE slot_name = '{slot}'",
                        database="postgres",
                    )
                except PITRRehearsalError:
                    pass
                else:
                    if not active:
                        break
                    if active == "f":
                        try:
                            self._source_psql(
                                contract,
                                f"SELECT pg_drop_replication_slot('{slot}')",
                                database="postgres",
                            )
                        except PITRRehearsalError:
                            pass
                        else:
                            break
                time.sleep(1)
        probe = self._probe_database
        if probe:
            try:
                self._source_psql(
                    contract,
                    f'DROP DATABASE IF EXISTS "{probe}" WITH (FORCE)',
                    database="postgres",
                )
            except PITRRehearsalError:
                pass

    def _assert_cleanup(self, contract: PITRContract) -> None:
        if any(self._container_exists(name) for name in self._containers.values()):
            raise PITRRehearsalError("cleanup.container")
        slot = self._required_slot_name()
        probe = self._required_probe_database()
        count = self._source_psql(
            contract,
            f"""
            SELECT
                (SELECT count(*) FROM pg_replication_slots WHERE slot_name = '{slot}')
                + (SELECT count(*) FROM pg_database WHERE datname = '{probe}')
            """,
            database="postgres",
        )
        if count != "0":
            raise PITRRehearsalError("cleanup.source")

    def _container_exists(self, name: str) -> bool:
        completed = subprocess.run(
            ["docker", "inspect", name],
            cwd=self.repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        return completed.returncode == 0

    def _required_slot_name(self) -> str:
        if not self._slot_name:
            raise PITRRehearsalError("identity.slot")
        return self._slot_name

    def _required_probe_database(self) -> str:
        if not self._probe_database:
            raise PITRRehearsalError("identity.probe")
        return self._probe_database

    def _required_database_container_id(self) -> str:
        if not self._database_container_id:
            raise PITRRehearsalError("identity.database_container")
        return self._database_container_id

    def _run_text(
        self,
        command: list[str],
        *,
        stage: str,
        timeout: int = 300,
    ) -> str:
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PITRRehearsalError(stage) from exc
        if completed.returncode != 0:
            raise PITRRehearsalError(_classify_command_failure(stage, completed.stderr))
        return completed.stdout


def _tree_bytes(root: Path) -> int:
    if not root.is_dir():
        raise PITRRehearsalError("backup.directory")
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _classify_command_failure(stage: str, stderr: str) -> str:
    message = stderr.lower()
    if "permission denied" in message:
        return f"{stage}.permission"
    if "no space left on device" in message:
        return f"{stage}.capacity"
    if "replication slot" in message and "does not exist" in message:
        return f"{stage}.slot_missing"
    if "password authentication failed" in message or "no password supplied" in message:
        return f"{stage}.authentication"
    if "could not translate host name" in message or "connection refused" in message:
        return f"{stage}.connectivity"
    if "no pg_hba.conf entry for replication" in message:
        return f"{stage}.replication_hba"
    if "exists but is not empty" in message:
        return f"{stage}.target_not_empty"
    if "unrecognized option" in message:
        return f"{stage}.client_contract"
    return stage


def _wal_directory_facts(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise PITRRehearsalError("wal.directory")
    entries = []
    partial_count = 0
    for path in sorted(root.iterdir()):
        if path.name.endswith(".partial"):
            partial_count += 1
            continue
        if path.is_file() and WAL_SEGMENT_RE.fullmatch(path.name):
            entries.append((path.name, path.stat().st_size, _sha256_file(path)))
    if not entries:
        raise PITRRehearsalError("wal.complete_segment")
    digest = hashlib.sha256()
    for name, size, content_sha256 in entries:
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(content_sha256.encode("ascii"))
        digest.update(b"\n")
    return {
        "complete_segment_count": len(entries),
        "partial_segment_count": partial_count,
        "bytes": sum(item[1] for item in entries),
        "inventory_sha256": digest.hexdigest(),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
