"""Isolated, fail-closed recovery rehearsal for a Compose deployment profile."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.standards_platform.application.acceptance import (
    standard_elements_fingerprint,
)
from data_agent.standards_platform.application.contracts import StandardDataElement

from .deployment_profile import DeploymentProfile
from .runtime_probe import DeploymentProfileVerifier

REPORT_SCHEMA = "gis-data-agent.recovery-rehearsal.v1"
POSTGRES_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
S3_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
SCRATCH_PREFIX = "gda-recovery-db-"
RESTORE_BUCKET_PREFIX = "gda-recovery-"
REPRESENTATIVE_TABLES = (
    "twm_state_object",
    "twm_state_relation",
    "twm_evidence_item",
)
RECOVERY_LIMITATIONS = (
    "backup_restore",
    "rpo_not_defined",
    "rto_not_approved",
    "offsite_copy_not_verified",
    "backup_encryption_not_verified",
    "cross_system_point_in_time_not_proven",
)


class RecoveryRehearsalError(RuntimeError):
    """A recovery stage failed without exposing command output or credentials."""

    def __init__(self, stage: str):
        super().__init__(f"recovery rehearsal failed at {stage}")
        self.stage = stage


@dataclass(frozen=True)
class RecoveryContract:
    database_service: str
    database_name: str
    database_user: str
    database_image: str
    object_client_service: str
    buckets: tuple[str, ...]


def failure_report(
    *, profile_id: str | None, stage: str, error_type: str
) -> dict[str, Any]:
    """Return a deliberately sparse failure report."""
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "profile_id": profile_id,
        "technical_pass": False,
        "promotion_ready": False,
        "failed_stage": stage,
        "error_type": error_type,
        "promotion_blockers": list(RECOVERY_LIMITATIONS),
    }


def resolve_recovery_contract(
    profile: DeploymentProfile, compose_model: dict[str, Any]
) -> RecoveryContract:
    """Resolve non-secret recovery inputs from a validated profile and Compose model."""
    capabilities = {item.capability: item for item in profile.capabilities}
    postgis = capabilities.get("postgis")
    object_storage = capabilities.get("object_storage")
    if not postgis or not postgis.configured_service:
        raise RecoveryRehearsalError("contract.postgis")
    if not object_storage or not object_storage.configured_service:
        raise RecoveryRehearsalError("contract.object_storage")

    services = compose_model.get("services") or {}
    database = services.get(postgis.configured_service) or {}
    database_environment = database.get("environment") or {}
    database_name = str(database_environment.get("POSTGRES_DB") or "")
    database_user = str(database_environment.get("POSTGRES_USER") or "")
    database_image = str(database.get("image") or "")
    if not POSTGRES_IDENTIFIER_RE.fullmatch(database_name):
        raise RecoveryRehearsalError("contract.database_name")
    if not POSTGRES_IDENTIFIER_RE.fullmatch(database_user):
        raise RecoveryRehearsalError("contract.database_user")
    if not database_image:
        raise RecoveryRehearsalError("contract.database_image")

    object_client_service = "minio-bucket-init"
    object_client = services.get(object_client_service) or {}
    object_environment = object_client.get("environment") or {}
    buckets = tuple(
        str(object_environment.get(name) or "")
        for name in ("AWS_S3_BUCKET", "MMFE_LAKEHOUSE_BUCKET")
    )
    if object_storage.configured_service not in services or not object_client:
        raise RecoveryRehearsalError("contract.object_storage_services")
    if len(set(buckets)) != len(buckets) or any(
        not S3_BUCKET_RE.fullmatch(bucket) for bucket in buckets
    ):
        raise RecoveryRehearsalError("contract.bucket_names")
    return RecoveryContract(
        database_service=postgis.configured_service,
        database_name=database_name,
        database_user=database_user,
        database_image=database_image,
        object_client_service=object_client_service,
        buckets=buckets,
    )


def migration_entries_fingerprint(entries: list[tuple[str, str]]) -> str:
    """Fingerprint restored ledger entries with migration-runner semantics."""
    digest = hashlib.sha256()
    for migration_id, checksum in sorted(entries):
        digest.update(migration_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(checksum.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def database_logical_identity(state: dict[str, Any]) -> dict[str, Any]:
    """Exclude storage-layout bytes from logical source/restore comparison."""
    return {key: value for key, value in state.items() if key != "database_bytes"}


DatabaseQuery = Callable[[str, str | None], str]


def collect_database_state(
    *, profile: DeploymentProfile, query: DatabaseQuery
) -> dict[str, Any]:
    """Collect one profile-bound logical database identity through a query adapter."""
    facts_raw = query(_DATABASE_FACTS_SQL, None)
    try:
        facts = json.loads(facts_raw.strip())
    except json.JSONDecodeError as exc:
        raise RecoveryRehearsalError("database.facts_json") from exc

    migration_rows = query(
        "SELECT migration_id, checksum FROM schema_migrations ORDER BY migration_id",
        None,
    )
    entries = []
    for row in migration_rows.splitlines():
        parts = row.split("\t")
        if len(parts) != 2 or not parts[0] or not re.fullmatch(r"[0-9a-f]{64}", parts[1]):
            raise RecoveryRehearsalError("database.migration_rows")
        entries.append((parts[0], parts[1]))

    element_rows = query(_STANDARD_ELEMENTS_SQL, None)
    try:
        elements = [
            _standard_element_from_json(json.loads(row))
            for row in element_rows.splitlines()
            if row.strip()
        ]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RecoveryRehearsalError("database.standard_rows") from exc

    migration_fingerprint = migration_entries_fingerprint(entries)
    standard_fingerprint = standard_elements_fingerprint(elements)
    if len(entries) != profile.migrations.count:
        raise RecoveryRehearsalError("database.migration_count")
    if migration_fingerprint != profile.migrations.fingerprint:
        raise RecoveryRehearsalError("database.migration_fingerprint")
    if len(elements) != profile.released_standard.element_count:
        raise RecoveryRehearsalError("database.standard_count")
    if standard_fingerprint != profile.released_standard.elements_sha256:
        raise RecoveryRehearsalError("database.standard_fingerprint")
    standard = facts.get("standard") or {}
    expected_standard = profile.released_standard
    if standard != {
        "doc_code": expected_standard.doc_code,
        "version_label": expected_standard.version_label,
        "status": "released",
        "element_count": expected_standard.element_count,
    }:
        raise RecoveryRehearsalError("database.standard_identity")
    return {
        "database_bytes": int(facts["database_bytes"]),
        "migration_count": len(entries),
        "migration_fingerprint": migration_fingerprint,
        "standard": {
            **standard,
            "elements_sha256": standard_fingerprint,
        },
        "representative_table_counts": {
            name: int((facts.get("representative_table_counts") or {})[name])
            for name in REPRESENTATIVE_TABLES
        },
        "geometry_column_count": int(facts["geometry_column_count"]),
        "extensions": facts.get("extensions") or {},
    }


def local_object_tree_facts(root: Path) -> dict[str, Any]:
    """Hash a mirrored object tree without exposing object keys in the report."""
    if not root.is_dir():
        raise RecoveryRehearsalError("object_storage.mirror_missing")
    entries: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(root).as_posix()
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise RecoveryRehearsalError("object_storage.inventory_key")
        entries.append((key, path.stat().st_size, _sha256_file(path)))
    digest = hashlib.sha256()
    for key, size, content_sha256 in entries:
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(content_sha256.encode("ascii"))
        digest.update(b"\n")
    return {
        "object_count": len(entries),
        "bytes": sum(item[1] for item in entries),
        "inventory_sha256": digest.hexdigest(),
    }


class ComposeRecoveryRehearsal:
    """Back up and restore PostGIS and MinIO into isolated temporary targets."""

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
        self._scratch_container: str | None = None

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        deployment = DeploymentProfileVerifier(
            profile=self.profile,
            profile_path=self.profile_path,
            repo_root=self.repo_root,
        ).verify()
        if not deployment.technical_pass or deployment.profile_contamination:
            raise RecoveryRehearsalError("deployment_verification")

        compose_model = self._compose_model()
        contract = resolve_recovery_contract(self.profile, compose_model)
        source_before = self._database_state(contract, scratch=False)

        with tempfile.TemporaryDirectory(prefix="gda-recovery-") as temp_name:
            work_dir = Path(temp_name)
            dump_path = work_dir / "database.dump"
            backup_seconds = self._dump_database(contract, dump_path)
            dump_bytes = dump_path.stat().st_size
            dump_sha256 = _sha256_file(dump_path)
            source_after = self._database_state(contract, scratch=False)
            if database_logical_identity(source_before) != database_logical_identity(
                source_after
            ):
                raise RecoveryRehearsalError("database.source_changed_during_backup")
            restored_state, restore_seconds = self._restore_database(contract, dump_path)
            if database_logical_identity(restored_state) != database_logical_identity(
                source_after
            ):
                raise RecoveryRehearsalError("database.restored_state_mismatch")
            object_storage, object_seconds = self._rehearse_object_storage(
                contract, work_dir
            )

        blockers = list(dict.fromkeys(
            (*self.profile.governance.promotion_blockers, *RECOVERY_LIMITATIONS)
        ))
        return {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "profile_id": self.profile.profile_id,
            "environment": self.profile.environment,
            "scope": "compose_isolated_logical_recovery",
            "technical_pass": True,
            "promotion_ready": False,
            "promotion_blockers": blockers,
            "deployment": {
                "technical_pass": deployment.technical_pass,
                "profile_contamination": deployment.profile_contamination,
                "capability_status": dict(deployment.capability_status),
            },
            "database": {
                "service": contract.database_service,
                "image": contract.database_image,
                "dump_bytes": dump_bytes,
                "dump_sha256": dump_sha256,
                "backup_artifact_retained": False,
                "backup_duration_seconds": round(backup_seconds, 3),
                "restore_duration_seconds": round(restore_seconds, 3),
                "source": source_after,
                "restored": restored_state,
            },
            "object_storage": {
                "rehearsal_duration_seconds": round(object_seconds, 3),
                "backup_artifact_retained": False,
                "buckets": object_storage,
            },
            "observed_total_seconds": round(time.monotonic() - started, 3),
            "slo_status": "observed_not_approved",
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
            raise RecoveryRehearsalError("compose.config_json") from exc
        if not isinstance(value, dict):
            raise RecoveryRehearsalError("compose.config_shape")
        return value

    def _dump_database(self, contract: RecoveryContract, dump_path: Path) -> float:
        command = self._compose_command(
            "exec",
            "-T",
            contract.database_service,
            "pg_dump",
            "--username",
            contract.database_user,
            "--dbname",
            contract.database_name,
            "--format=custom",
            "--no-owner",
            "--no-acl",
        )
        started = time.monotonic()
        try:
            with dump_path.open("wb") as output:
                completed = subprocess.run(
                    command,
                    cwd=self.repo_root,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=7200,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RecoveryRehearsalError("database.backup") from exc
        if completed.returncode != 0 or not dump_path.is_file() or not dump_path.stat().st_size:
            raise RecoveryRehearsalError("database.backup")
        return time.monotonic() - started

    def _restore_database(
        self, contract: RecoveryContract, dump_path: Path
    ) -> tuple[dict[str, Any], float]:
        scratch_name = SCRATCH_PREFIX + secrets.token_hex(6)
        if not re.fullmatch(r"gda-recovery-db-[0-9a-f]{12}", scratch_name):
            raise RecoveryRehearsalError("database.scratch_identity")
        started = time.monotonic()
        created = False
        try:
            self._run_text(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    scratch_name,
                    "--network",
                    "none",
                    "--env",
                    "POSTGRES_DB=postgres",
                    "--env",
                    f"POSTGRES_USER={contract.database_user}",
                    "--env",
                    "POSTGRES_HOST_AUTH_METHOD=trust",
                    contract.database_image,
                ],
                stage="database.scratch_start",
            )
            created = True
            self._scratch_container = scratch_name
            self._assert_isolated_storage(scratch_name)
            self._wait_for_postgres(contract, scratch_name)
            self._prepare_scratch_database(contract)
            command = [
                "docker",
                "exec",
                "-i",
                scratch_name,
                "pg_restore",
                "--username",
                contract.database_user,
                "--dbname",
                contract.database_name,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
            ]
            try:
                with dump_path.open("rb") as source:
                    completed = subprocess.run(
                        command,
                        cwd=self.repo_root,
                        stdin=source,
                        capture_output=True,
                        check=False,
                        timeout=7200,
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RecoveryRehearsalError("database.restore") from exc
            if completed.returncode != 0:
                raise RecoveryRehearsalError(
                    _classify_restore_failure(completed.stderr)
                )
            restored = self._database_state(contract, scratch=True)
            return restored, time.monotonic() - started
        finally:
            self._scratch_container = None
            if created:
                subprocess.run(
                    ["docker", "rm", "--force", "--volumes", scratch_name],
                    cwd=self.repo_root,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=120,
                )

    def _assert_isolated_storage(self, scratch_name: str) -> None:
        output = self._run_text(
            ["docker", "inspect", scratch_name], stage="database.scratch_inspect"
        )
        try:
            inspected = json.loads(output)[0]
        except (json.JSONDecodeError, IndexError, TypeError) as exc:
            raise RecoveryRehearsalError("database.scratch_inspect") from exc
        mounts = inspected.get("Mounts") or []
        data_mounts = [
            mount
            for mount in mounts
            if mount.get("Destination") == "/var/lib/postgresql/data"
        ]
        if len(data_mounts) != 1 or data_mounts[0].get("Type") != "volume":
            raise RecoveryRehearsalError("database.scratch_storage")
        source_volume_names = {
            f"{self.profile.compose.project_name}_{volume.logical_name}"
            for volume in self.profile.compose.volumes
        }
        if data_mounts[0].get("Name") in source_volume_names:
            raise RecoveryRehearsalError("database.scratch_storage")

    def _wait_for_postgres(
        self, contract: RecoveryContract, scratch_name: str
    ) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            completed = subprocess.run(
                [
                    "docker",
                    "exec",
                    scratch_name,
                    "pg_isready",
                    "--username",
                    contract.database_user,
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
            time.sleep(1)
        raise RecoveryRehearsalError("database.scratch_readiness")

    def _prepare_scratch_database(self, contract: RecoveryContract) -> None:
        self._psql(
            contract,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') THEN
                    CREATE ROLE agent_user NOLOGIN NOSUPERUSER NOBYPASSRLS;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_reader') THEN
                    CREATE ROLE agent_reader NOLOGIN NOSUPERUSER NOBYPASSRLS;
                END IF;
            END
            $$
            """,
            scratch=True,
            database="postgres",
        )
        self._psql(
            contract,
            f'CREATE DATABASE "{contract.database_name}" TEMPLATE template0',
            scratch=True,
            database="postgres",
        )

    def _database_state(
        self, contract: RecoveryContract, *, scratch: bool
    ) -> dict[str, Any]:
        return collect_database_state(
            profile=self.profile,
            query=lambda sql, database: self._psql(
                contract,
                sql,
                scratch=scratch,
                database=database,
            ),
        )

    def _psql(
        self,
        contract: RecoveryContract,
        sql: str,
        *,
        scratch: bool,
        database: str | None = None,
    ) -> str:
        psql_args = [
            "psql",
            "--no-psqlrc",
            "--set",
            "ON_ERROR_STOP=1",
            "--username",
            contract.database_user,
            "--dbname",
            database or contract.database_name,
            "--tuples-only",
            "--no-align",
            "--field-separator=\t",
            "--command",
            sql,
        ]
        if scratch:
            if not self._scratch_container:
                raise RecoveryRehearsalError("database.scratch_missing")
            command = ["docker", "exec", self._scratch_container, *psql_args]
        else:
            command = self._compose_command(
                "exec", "-T", contract.database_service, *psql_args
            )
        return self._run_text(command, stage="database.query")

    def _rehearse_object_storage(
        self, contract: RecoveryContract, work_dir: Path
    ) -> tuple[list[dict[str, Any]], float]:
        restore_prefix = RESTORE_BUCKET_PREFIX + secrets.token_hex(6)
        if not re.fullmatch(r"gda-recovery-[0-9a-f]{12}", restore_prefix):
            raise RecoveryRehearsalError("object_storage.restore_identity")
        command = self._compose_command(
            "run",
            "--rm",
            "--no-deps",
            "--volume",
            f"{work_dir}:/recovery",
            "--entrypoint",
            "/bin/sh",
            contract.object_client_service,
            "-c",
            _OBJECT_RECOVERY_SCRIPT,
            "--",
            restore_prefix,
            *contract.buckets,
        )
        started = time.monotonic()
        try:
            self._run_text(command, stage="object_storage.rehearsal", timeout=7200)
        finally:
            self._cleanup_restore_buckets(
                contract,
                restore_prefix=restore_prefix,
                bucket_count=len(contract.buckets),
            )
        duration = time.monotonic() - started
        results = []
        for index, bucket in enumerate(contract.buckets):
            source = local_object_tree_facts(work_dir / "source-objects" / str(index))
            restored = local_object_tree_facts(
                work_dir / "restored-objects" / str(index)
            )
            if source != restored:
                raise RecoveryRehearsalError("object_storage.inventory_mismatch")
            results.append({"bucket": bucket, "source": source, "restored": restored})
        return results, duration

    def _cleanup_restore_buckets(
        self,
        contract: RecoveryContract,
        *,
        restore_prefix: str,
        bucket_count: int,
    ) -> None:
        command = self._compose_command(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/bin/sh",
            contract.object_client_service,
            "-c",
            _OBJECT_CLEANUP_SCRIPT,
            "--",
            restore_prefix,
            str(bucket_count),
        )
        try:
            subprocess.run(
                command,
                cwd=self.repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

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
            raise RecoveryRehearsalError(stage) from exc
        if completed.returncode != 0:
            raise RecoveryRehearsalError(stage)
        return completed.stdout


def _standard_element_from_json(value: dict[str, Any]) -> StandardDataElement:
    return StandardDataElement(
        id="restored",
        document_version_id="restored",
        code=str(value["code"]),
        name_zh=str(value["name_zh"]),
        name_en=str(value.get("name_en") or ""),
        definition=str(value.get("definition") or ""),
        representation_class=str(value.get("representation_class") or ""),
        datatype=str(value.get("datatype") or ""),
        unit=str(value.get("unit") or ""),
        obligation=str(value["obligation"]),
        bound_table=str(value.get("bound_table") or ""),
        bound_column=str(value.get("bound_column") or ""),
        aliases=tuple(str(item) for item in (value.get("aliases") or [])),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_restore_failure(stderr: bytes) -> str:
    message = stderr.decode("utf-8", errors="replace").lower()
    if "role" in message and "does not exist" in message:
        return "database.restore.missing_role"
    if "no space left on device" in message:
        return "database.restore.capacity"
    if "already exists" in message:
        return "database.restore.object_conflict"
    if "violates" in message or "constraint" in message:
        return "database.restore.constraint"
    return "database.restore"


_DATABASE_FACTS_SQL = """
SELECT jsonb_build_object(
    'database_bytes', pg_database_size(current_database()),
    'standard', (
        SELECT jsonb_build_object(
            'doc_code', d.doc_code,
            'version_label', v.version_label,
            'status', v.status,
            'element_count', COUNT(e.id)
        )
        FROM std_document d
        JOIN std_document_version v ON v.document_id = d.id
        LEFT JOIN std_data_element e ON e.document_version_id = v.id
        WHERE d.doc_code = 'NR_ONE_MAP_TWM_CORE_2026'
          AND v.version_label = '2026-06-16-draft'
        GROUP BY d.doc_code, v.version_label, v.status
    ),
    'representative_table_counts', jsonb_build_object(
        'twm_state_object', (SELECT COUNT(*) FROM twm_state_object),
        'twm_state_relation', (SELECT COUNT(*) FROM twm_state_relation),
        'twm_evidence_item', (SELECT COUNT(*) FROM twm_evidence_item)
    ),
    'geometry_column_count', (SELECT COUNT(*) FROM geometry_columns),
    'extensions', (
        SELECT jsonb_object_agg(extname, extversion ORDER BY extname)
        FROM pg_extension
        WHERE extname IN ('ltree', 'postgis', 'vector')
    )
)::text
"""

_STANDARD_ELEMENTS_SQL = """
SELECT jsonb_build_object(
    'code', e.code,
    'name_zh', e.name_zh,
    'name_en', COALESCE(e.name_en, ''),
    'definition', COALESCE(e.definition, ''),
    'representation_class', COALESCE(e.representation_class, ''),
    'datatype', COALESCE(e.datatype, ''),
    'unit', COALESCE(e.unit, ''),
    'obligation', e.obligation,
    'bound_table', COALESCE(e.bound_table, ''),
    'bound_column', COALESCE(e.bound_column, ''),
    'aliases', COALESCE(to_jsonb(t.aliases), '[]'::jsonb)
)::text
FROM std_data_element e
JOIN std_document_version v ON v.id = e.document_version_id
JOIN std_document d ON d.id = v.document_id
LEFT JOIN std_term t ON t.id = e.term_id
WHERE d.doc_code = 'NR_ONE_MAP_TWM_CORE_2026'
  AND v.version_label = '2026-06-16-draft'
  AND v.status = 'released'
ORDER BY e.bound_table, e.code, e.bound_column
"""

_OBJECT_RECOVERY_SCRIPT = r"""
set -eu
restore_prefix="$1"
shift
bucket_count="$#"
alias_name="recovery"
mc alias set "$alias_name" http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
cleanup() {
    index=0
    while [ "$index" -lt "$bucket_count" ]; do
        mc rb --force "$alias_name/${restore_prefix}-${index}" >/dev/null 2>&1 || true
        index=$((index + 1))
    done
    chmod -R a+rwx /recovery >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM
index=0
for bucket in "$@"; do
    restore_bucket="${restore_prefix}-${index}"
    mkdir -p "/recovery/source-objects/${index}"
    mkdir -p "/recovery/restored-objects/${index}"
    mc mirror --overwrite "$alias_name/$bucket" "/recovery/source-objects/${index}"
    mc mb "$alias_name/$restore_bucket" >/dev/null
    mc anonymous set none "$alias_name/$restore_bucket" >/dev/null
    mc mirror --overwrite "/recovery/source-objects/${index}" "$alias_name/$restore_bucket"
    mc mirror --overwrite "$alias_name/$restore_bucket" "/recovery/restored-objects/${index}"
    index=$((index + 1))
done
"""

_OBJECT_CLEANUP_SCRIPT = r"""
set -eu
restore_prefix="$1"
bucket_count="$2"
alias_name="recovery"
mc alias set "$alias_name" http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
index=0
while [ "$index" -lt "$bucket_count" ]; do
    mc rb --force "$alias_name/${restore_prefix}-${index}" >/dev/null 2>&1 || true
    index=$((index + 1))
done
"""
