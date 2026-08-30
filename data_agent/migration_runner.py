"""Fail-closed SQL migration runner, audit, and legacy reconciliation.

The full migration filename without ``.sql`` is the stable migration ID. The
numeric prefix only controls ordering. Applied content is immutable through a
SHA-256 checksum recorded in PostgreSQL.

Historical databases may contain schema created outside the ledger. Those
states are never auto-baselined: an operator must run ``reconcile`` with an
actor and reason, and every pending migration must pass its catalog probes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from .db_engine import get_engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
T_MIGRATIONS = "schema_migrations"
MIGRATION_FILENAME_RE = re.compile(
    r"^(?P<version>\d{3,})_(?P<slug>[a-z0-9][a-z0-9_]*)\.sql$"
)
MIGRATION_LOCK_ID = 0x4749534441544130  # "GISDATA0" as a signed bigint.
MIGRATION_RUNTIME_ROLE_ENV = "MIGRATION_RUNTIME_DB_ROLE"
DEFAULT_MIGRATION_RUNTIME_ROLE = "agent_user"
POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
LEDGER_SEQUENCE = f"{T_MIGRATIONS}_id_seq"

# These collisions predate the strict ledger. Their exact filename sets are
# frozen. Any new collision or change to a frozen set fails catalog discovery.
LEGACY_VERSION_COLLISIONS = {
    "011": frozenset(
        {"011_create_semantic_metrics.sql", "011_create_stream_tables.sql"}
    ),
    "012": frozenset({"012_create_teams.sql", "012_virtual_sources.sql"}),
    "013": frozenset(
        {"013_extend_rls_for_teams.sql", "013_rating_clone.sql"}
    ),
    "014": frozenset(
        {"014_create_data_catalog.sql", "014_workflow_checkpoints.sql"}
    ),
    "015": frozenset({"015_add_email_column.sql", "015_version_tags.sql"}),
    "016": frozenset(
        {"016_create_map_annotations.sql", "016_skill_approval.sql"}
    ),
    "017": frozenset(
        {"017_create_workflows.sql", "017_skill_deps_webhook.sql"}
    ),
    # The standards-application slice and the platform-control slice were
    # developed on parallel branches and both 092 identities reached a real
    # migration ledger before the branches converged. Preserve both immutable
    # histories; any third 092 filename still fails catalog discovery.
    "092": frozenset(
        {
            "092_platform_control_ledger.sql",
            "092_std_application_mapping_contract.sql",
        }
    ),
}

# These old files depend on tables introduced by later numeric versions.
LEGACY_DEFERRED_ORDER = {
    "014_workflow_checkpoints": (17, 1),
    "013_rating_clone": (21, 1),
    "015_version_tags": (21, 2),
    "016_skill_approval": (21, 3),
    "017_skill_deps_webhook": (21, 4),
}


@dataclass(frozen=True)
class Migration:
    migration_id: str
    version: str
    filename: str
    path: Path
    checksum: str

    def __getitem__(self, key: str) -> Any:
        """Keep consumers written against the former mapping contract working."""
        return getattr(self, key)


@dataclass(frozen=True)
class MigrationReport:
    status: str
    generated_at: str
    catalog_fingerprint: str
    catalog_count: int
    database_fingerprint: str | None = None
    applied_count: int = 0
    pending: tuple[str, ...] = ()
    unknown_applied: tuple[str, ...] = ()
    duplicate_applied_ids: tuple[str, ...] = ()
    missing_checksums: tuple[str, ...] = ()
    checksum_mismatches: tuple[dict[str, str], ...] = ()
    metadata_mismatches: tuple[dict[str, str], ...] = ()
    ledger_present: bool | None = None
    ledger_format: str | None = None
    applied_this_run: tuple[str, ...] = ()
    reconciled_this_run: tuple[str, ...] = ()
    probe_failures: tuple[dict[str, Any], ...] = ()
    legacy_version_collisions: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "pending",
            "unknown_applied",
            "duplicate_applied_ids",
            "missing_checksums",
            "checksum_mismatches",
            "metadata_mismatches",
            "applied_this_run",
            "reconciled_this_run",
            "probe_failures",
        ):
            payload[key] = list(payload[key])
        return payload

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


class MigrationFailure(RuntimeError):
    """Base class for catalog, ledger, lock, and execution failures."""

    def __init__(self, message: str, report: MigrationReport | None = None):
        super().__init__(message)
        self.report = report


# Backward-compatible name used by older deployment code.
MigrationError = MigrationFailure


class MigrationDiscoveryError(MigrationFailure):
    """The code migration catalog violates the naming/identity contract."""


class MigrationDriftError(MigrationFailure):
    """The database ledger differs from immutable catalog history."""


class MigrationLockError(MigrationFailure):
    """Another migration authority currently owns the database lock."""


class MigrationExecutionError(MigrationFailure):
    """A migration failed, was rolled back, and stopped the chain."""


class MigrationReconciliationError(MigrationFailure):
    """A historical schema state could not be safely reconciled."""


class MigrationStateError(MigrationFailure):
    """The configured database is not ready for application traffic."""


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_sort_key(migration: Migration) -> tuple[int, int, str]:
    logical_order = LEGACY_DEFERRED_ORDER.get(migration.migration_id)
    if logical_order is None:
        logical_order = (int(migration.version), 0)
    return (*logical_order, migration.filename)


def _fingerprint(entries: Iterable[tuple[str, str | None]]) -> str:
    digest = hashlib.sha256()
    for migration_id, checksum in sorted(entries):
        digest.update(migration_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update((checksum or "<missing>").encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def discover_migrations(migrations_dir: Path | None = None) -> list[Migration]:
    """Return the validated catalog in deterministic execution order."""
    directory = migrations_dir or MIGRATIONS_DIR
    if not directory.exists():
        return []

    migrations: list[Migration] = []
    invalid_filenames: list[str] = []
    seen_ids: set[str] = set()
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".sql":
            continue
        match = MIGRATION_FILENAME_RE.fullmatch(path.name)
        if not match:
            invalid_filenames.append(path.name)
            continue
        migration_id = path.stem
        if migration_id in seen_ids:
            raise MigrationDiscoveryError(
                f"Duplicate migration ID {migration_id!r} in {directory}"
            )
        seen_ids.add(migration_id)
        migrations.append(
            Migration(
                migration_id=migration_id,
                version=match.group("version"),
                filename=path.name,
                path=path,
                checksum=_checksum(path),
            )
        )

    if invalid_filenames:
        raise MigrationDiscoveryError(
            "Invalid migration filenames; expected NNN_description.sql: "
            + ", ".join(invalid_filenames)
        )

    files_by_version: dict[str, set[str]] = defaultdict(set)
    for migration in migrations:
        files_by_version[migration.version].add(migration.filename)

    changed_legacy_sets = {
        version: {"expected": expected, "actual": files_by_version.get(version, set())}
        for version, expected in LEGACY_VERSION_COLLISIONS.items()
        if files_by_version.get(version)
        and files_by_version[version] != set(expected)
    }
    if changed_legacy_sets:
        detail = "; ".join(
            f"{version}: expected {', '.join(sorted(values['expected']))}; "
            f"found {', '.join(sorted(values['actual'])) or '<none>'}"
            for version, values in sorted(changed_legacy_sets.items())
        )
        raise MigrationDiscoveryError(
            f"Frozen legacy migration set was changed ({detail})"
        )

    unexpected_collisions = {
        version: filenames
        for version, filenames in files_by_version.items()
        if len(filenames) > 1
        and LEGACY_VERSION_COLLISIONS.get(version) != frozenset(filenames)
    }
    if unexpected_collisions:
        detail = "; ".join(
            f"{version}: {', '.join(sorted(filenames))}"
            for version, filenames in sorted(unexpected_collisions.items())
        )
        raise MigrationDiscoveryError(
            "Duplicate migration versions are forbidden outside the frozen "
            f"legacy allowlist ({detail})"
        )
    return sorted(migrations, key=_migration_sort_key)


def catalog_fingerprint(migrations: Sequence[Migration] | None = None) -> str:
    catalog = list(migrations) if migrations is not None else discover_migrations()
    return _fingerprint(
        (migration.migration_id, migration.checksum) for migration in catalog
    )


def _require_postgresql(conn) -> None:
    if conn.dialect.name != "postgresql":
        raise MigrationStateError(
            "The production migration authority requires PostgreSQL/PostGIS; "
            f"got dialect {conn.dialect.name!r}"
        )


@contextmanager
def _migration_lock(conn):
    """Acquire the PostgreSQL session lock without waiting indefinitely."""
    _require_postgresql(conn)
    acquired = bool(
        conn.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        ).scalar_one()
    )
    conn.commit()
    if not acquired:
        raise MigrationLockError(
            "Another migration authority holds the PostgreSQL advisory lock"
        )
    try:
        yield
    finally:
        try:
            conn.rollback()
            conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )
            conn.commit()
        except Exception:
            logger.exception("[Migrations] Failed to explicitly release advisory lock")


def _quote_identifier(conn, identifier: str) -> str:
    return conn.dialect.identifier_preparer.quote(identifier)


def _validated_runtime_role(conn) -> str:
    runtime_role = os.environ.get(
        MIGRATION_RUNTIME_ROLE_ENV, DEFAULT_MIGRATION_RUNTIME_ROLE
    ).strip()
    if not POSTGRES_IDENTIFIER_RE.fullmatch(runtime_role):
        raise MigrationStateError(
            f"Invalid {MIGRATION_RUNTIME_ROLE_ENV} identifier: {runtime_role!r}"
        )
    role_exists = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
        {"role": runtime_role},
    ).scalar_one()
    if not role_exists:
        raise MigrationStateError(
            f"Configured runtime database role {runtime_role!r} does not exist"
        )
    return runtime_role


def _restrict_runtime_ledger_access(conn, runtime_role: str) -> None:
    """Make the runtime role a ledger reader, even with broad DB defaults."""
    quoted_role = _quote_identifier(conn, runtime_role)
    conn.execute(text(f"ALTER TABLE {T_MIGRATIONS} OWNER TO CURRENT_USER"))
    conn.execute(text(f"ALTER SEQUENCE {LEDGER_SEQUENCE} OWNER TO CURRENT_USER"))
    conn.execute(
        text(f"REVOKE ALL PRIVILEGES ON TABLE {T_MIGRATIONS} FROM PUBLIC")
    )
    conn.execute(
        text(
            f"REVOKE ALL PRIVILEGES ON TABLE {T_MIGRATIONS} FROM "
            f"{quoted_role}"
        )
    )
    conn.execute(
        text(f"GRANT SELECT ON TABLE {T_MIGRATIONS} TO {quoted_role}")
    )
    conn.execute(
        text(f"REVOKE ALL PRIVILEGES ON SEQUENCE {LEDGER_SEQUENCE} FROM PUBLIC")
    )
    conn.execute(
        text(
            f"REVOKE ALL PRIVILEGES ON SEQUENCE {LEDGER_SEQUENCE} FROM "
            f"{quoted_role}"
        )
    )

    permissions = conn.execute(
        text(
            """
            SELECT
                has_table_privilege(:role, :table_name, 'SELECT') AS can_select,
                has_table_privilege(:role, :table_name, 'INSERT')
                    OR has_table_privilege(:role, :table_name, 'UPDATE')
                    OR has_table_privilege(:role, :table_name, 'DELETE')
                    OR has_table_privilege(:role, :table_name, 'TRUNCATE')
                    OR has_table_privilege(:role, :table_name, 'REFERENCES')
                    OR has_table_privilege(:role, :table_name, 'TRIGGER')
                    AS can_write,
                has_sequence_privilege(:role, :sequence_name, 'SELECT')
                    OR has_sequence_privilege(:role, :sequence_name, 'USAGE')
                    OR has_sequence_privilege(:role, :sequence_name, 'UPDATE')
                    AS can_use_sequence
            """
        ),
        {
            "role": runtime_role,
            "table_name": f"public.{T_MIGRATIONS}",
            "sequence_name": f"public.{LEDGER_SEQUENCE}",
        },
    ).mappings().one()
    if not permissions["can_select"]:
        conn.rollback()
        raise MigrationStateError(
            f"Runtime database role {runtime_role!r} cannot read the migration ledger"
        )
    if permissions["can_write"] or permissions["can_use_sequence"]:
        conn.rollback()
        raise MigrationStateError(
            f"Runtime database role {runtime_role!r} retains effective migration "
            "ledger write privileges, possibly through role membership"
        )
    conn.commit()


def _ensure_migrations_table(conn, migrations: Sequence[Migration]) -> None:
    """Forward-upgrade ledger structure without trusting historical content."""
    _require_postgresql(conn)
    runtime_role = _validated_runtime_role(conn)
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {T_MIGRATIONS} (
                id BIGSERIAL PRIMARY KEY,
                migration_id VARCHAR(255) NOT NULL,
                version VARCHAR(32) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                execution_kind VARCHAR(32) NOT NULL DEFAULT 'executed',
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reconciled_at TIMESTAMPTZ,
                reconciled_by TEXT,
                reconciliation_reason TEXT,
                probe_evidence JSONB
            )
            """
        )
    )
    conn.execute(
        text(
            f"""
            ALTER TABLE {T_MIGRATIONS}
                ADD COLUMN IF NOT EXISTS migration_id VARCHAR(255),
                ADD COLUMN IF NOT EXISTS checksum VARCHAR(64),
                ADD COLUMN IF NOT EXISTS execution_kind VARCHAR(32),
                ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS reconciled_by TEXT,
                ADD COLUMN IF NOT EXISTS reconciliation_reason TEXT,
                ADD COLUMN IF NOT EXISTS probe_evidence JSONB
            """
        )
    )
    conn.commit()

    catalog_by_filename = {migration.filename: migration for migration in migrations}
    rows = conn.execute(
        text(
            f"SELECT id, version, filename, migration_id, checksum, execution_kind "
            f"FROM {T_MIGRATIONS} ORDER BY id"
        )
    ).mappings().all()
    for row in rows:
        migration = catalog_by_filename.get(row["filename"])
        inferred_id = Path(row["filename"]).stem
        migration_id = row["migration_id"] or inferred_id
        if migration is not None and migration_id != migration.migration_id:
            raise MigrationDriftError(
                f"Ledger row {row['id']} has migration ID {migration_id!r}, "
                f"but filename maps to {migration.migration_id!r}"
            )
        conn.execute(
            text(
                f"UPDATE {T_MIGRATIONS} "
                "SET migration_id = :migration_id, "
                "execution_kind = COALESCE(execution_kind, 'legacy_unverified') "
                "WHERE id = :row_id"
            ),
            {"migration_id": migration_id, "row_id": row["id"]},
        )
    conn.commit()

    duplicate_ids = conn.execute(
        text(
            f"SELECT migration_id, COUNT(*) AS count FROM {T_MIGRATIONS} "
            "GROUP BY migration_id HAVING COUNT(*) > 1"
        )
    ).mappings().all()
    if duplicate_ids:
        detail = ", ".join(
            f"{row['migration_id']} ({row['count']})" for row in duplicate_ids
        )
        raise MigrationDriftError(f"Duplicate migration IDs in ledger: {detail}")

    constraints = inspect(conn).get_unique_constraints(T_MIGRATIONS)
    for constraint in constraints:
        if constraint.get("column_names") == ["version"]:
            name = constraint.get("name")
            if not name:
                raise MigrationDriftError(
                    "Cannot identify the legacy version uniqueness constraint"
                )
            conn.execute(
                text(
                    f"ALTER TABLE {T_MIGRATIONS} DROP CONSTRAINT "
                    f"{_quote_identifier(conn, name)}"
                )
            )
    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_schema_migrations_migration_id "
            f"ON {T_MIGRATIONS}(migration_id)"
        )
    )
    conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_schema_migrations_filename "
            f"ON {T_MIGRATIONS}(filename)"
        )
    )
    conn.execute(
        text(
            f"ALTER TABLE {T_MIGRATIONS} "
            "ALTER COLUMN migration_id SET NOT NULL, "
            "ALTER COLUMN execution_kind SET NOT NULL"
        )
    )
    _restrict_runtime_ledger_access(conn, runtime_role)


def _enforce_checksum_not_null(conn) -> None:
    missing = conn.execute(
        text(f"SELECT COUNT(*) FROM {T_MIGRATIONS} WHERE checksum IS NULL")
    ).scalar_one()
    if not missing:
        conn.execute(
            text(
                f"ALTER TABLE {T_MIGRATIONS} "
                "ALTER COLUMN checksum SET NOT NULL"
            )
        )
        conn.commit()


def ensure_migrations_table() -> None:
    """Upgrade only the ledger structure; do not apply or baseline migrations."""
    engine = get_engine()
    if engine is None:
        raise MigrationStateError("Database is not configured")
    migrations = discover_migrations()
    with engine.connect() as conn:
        with _migration_lock(conn):
            _ensure_migrations_table(conn, migrations)


def _load_applied(conn) -> tuple[list[dict[str, Any]], str]:
    """Read both legacy and strict ledger layouts without schema writes."""
    columns = {
        column["name"] for column in inspect(conn).get_columns(T_MIGRATIONS)
    }
    strict = {"migration_id", "checksum", "execution_kind"}.issubset(columns)
    selected = ["version", "filename", "applied_at"]
    selected.append("migration_id" if "migration_id" in columns else "NULL AS migration_id")
    selected.append("checksum" if "checksum" in columns else "NULL AS checksum")
    selected.append(
        "execution_kind" if "execution_kind" in columns else "NULL AS execution_kind"
    )
    rows = []
    for row in conn.execute(
        text(
            f"SELECT {', '.join(selected)} FROM {T_MIGRATIONS} "
            "ORDER BY version, filename"
        )
    ).mappings().all():
        payload = dict(row)
        payload["migration_id"] = payload["migration_id"] or Path(
            payload["filename"]
        ).stem
        rows.append(payload)
    return rows, "strict" if strict else "legacy"


def get_applied_versions(conn) -> set[str]:
    """Compatibility helper retained for callers of the old runner."""
    rows, _ = _load_applied(conn)
    return {row["version"] for row in rows}


def _build_schema_report(
    migrations: Sequence[Migration],
    applied: Sequence[Mapping[str, Any]],
    *,
    ledger_present: bool = True,
    ledger_format: str | None = None,
) -> MigrationReport:
    catalog_by_id = {migration.migration_id: migration for migration in migrations}
    id_counts = Counter(str(row["migration_id"]) for row in applied)
    duplicate_applied_ids = tuple(
        sorted(migration_id for migration_id, count in id_counts.items() if count > 1)
    )
    applied_by_id = {
        str(row["migration_id"]): row
        for row in applied
        if id_counts[str(row["migration_id"])] == 1
    }
    pending = tuple(
        migration.migration_id
        for migration in migrations
        if migration.migration_id not in applied_by_id
    )
    unknown_applied = tuple(
        sorted(migration_id for migration_id in applied_by_id if migration_id not in catalog_by_id)
    )
    missing_checksums = tuple(
        sorted(
            str(row["migration_id"])
            for row in applied
            if not row.get("checksum")
        )
    )
    checksum_mismatches: list[dict[str, str]] = []
    metadata_mismatches: list[dict[str, str]] = []
    for migration_id in sorted(catalog_by_id.keys() & applied_by_id.keys()):
        migration = catalog_by_id[migration_id]
        row = applied_by_id[migration_id]
        if row.get("checksum") and row["checksum"] != migration.checksum:
            checksum_mismatches.append(
                {
                    "migration_id": migration_id,
                    "expected": migration.checksum,
                    "actual": str(row["checksum"]),
                }
            )
        if row["version"] != migration.version or row["filename"] != migration.filename:
            metadata_mismatches.append(
                {
                    "migration_id": migration_id,
                    "expected_version": migration.version,
                    "actual_version": str(row["version"]),
                    "expected_filename": migration.filename,
                    "actual_filename": str(row["filename"]),
                }
            )

    has_drift = bool(
        unknown_applied
        or duplicate_applied_ids
        or missing_checksums
        or checksum_mismatches
        or metadata_mismatches
    )
    status = "drift" if has_drift else ("pending" if pending else "in_sync")
    return MigrationReport(
        status=status,
        generated_at=datetime.now(UTC).isoformat(),
        catalog_fingerprint=catalog_fingerprint(migrations),
        database_fingerprint=_fingerprint(
            (str(row["migration_id"]), row.get("checksum")) for row in applied
        ),
        catalog_count=len(migrations),
        applied_count=len(applied),
        pending=pending,
        unknown_applied=unknown_applied,
        duplicate_applied_ids=duplicate_applied_ids,
        missing_checksums=missing_checksums,
        checksum_mismatches=tuple(checksum_mismatches),
        metadata_mismatches=tuple(metadata_mismatches),
        ledger_present=ledger_present,
        ledger_format=ledger_format,
        legacy_version_collisions={
            version: sorted(filenames)
            for version, filenames in LEGACY_VERSION_COLLISIONS.items()
        },
    )


def get_schema_report() -> MigrationReport:
    """Return a read-only catalog/ledger comparison, including legacy ledgers."""
    migrations = discover_migrations()
    engine = get_engine()
    if engine is None:
        return MigrationReport(
            status="database_unconfigured",
            generated_at=datetime.now(UTC).isoformat(),
            catalog_fingerprint=catalog_fingerprint(migrations),
            catalog_count=len(migrations),
            ledger_present=None,
            legacy_version_collisions={
                version: sorted(filenames)
                for version, filenames in LEGACY_VERSION_COLLISIONS.items()
            },
        )
    with engine.connect() as conn:
        with _migration_lock(conn):
            if not inspect(conn).has_table(T_MIGRATIONS):
                report = _build_schema_report(
                    migrations, [], ledger_present=False, ledger_format="missing"
                )
                return replace(report, status="ledger_missing")
            applied, ledger_format = _load_applied(conn)
            return _build_schema_report(
                migrations,
                applied,
                ledger_present=True,
                ledger_format=ledger_format,
            )


def verify_schema_state(*, allow_unconfigured: bool = False) -> MigrationReport:
    """Fail closed unless a configured database exactly matches the catalog."""
    report = get_schema_report()
    if report.status == "database_unconfigured" and allow_unconfigured:
        logger.info("[Migrations] Database unconfigured in explicit non-DB mode")
        return report
    if report.status == "in_sync":
        logger.info(
            "[Migrations] Verified %d migrations; schema fingerprint %s",
            report.applied_count,
            report.database_fingerprint,
        )
        return report
    detail = json.dumps(
        {
            "status": report.status,
            "pending": report.pending,
            "unknown_applied": report.unknown_applied,
            "missing_checksums": report.missing_checksums,
            "checksum_mismatches": report.checksum_mismatches,
            "metadata_mismatches": report.metadata_mismatches,
        },
        sort_keys=True,
    )
    error_type = MigrationDriftError if report.status == "drift" else MigrationStateError
    raise error_type(
        "Database schema is not ready; run the migration authority or explicit "
        f"legacy reconciliation before starting the application: {detail}",
        report,
    )


def verify_runtime_schema_state(
    *,
    required_migrations: Sequence[str] = (),
    allow_unconfigured: bool = False,
) -> MigrationReport:
    """Verify runtime compatibility without requiring unrelated migration heads.

    ``verify_schema_state`` remains the release and migration-authority gate.
    Runtime modules use this narrower boundary so a pending migration owned by
    another capability does not make the whole application unavailable.
    """

    report = get_schema_report()
    if report.status == "database_unconfigured" and allow_unconfigured:
        logger.info("[Migrations] Database unconfigured in explicit non-DB mode")
        return report

    required = tuple(dict.fromkeys(str(value) for value in required_migrations))
    catalog_ids = {migration.migration_id for migration in discover_migrations()}
    unknown_required = tuple(value for value in required if value not in catalog_ids)
    pending_required = tuple(value for value in required if value in report.pending)
    required_checksum_drift = tuple(
        sorted(
            item["migration_id"]
            for item in report.checksum_mismatches
            if item.get("migration_id") in required
        )
    )
    required_missing_checksums = tuple(
        sorted(set(report.missing_checksums) & set(required))
    )
    required_metadata_drift = tuple(
        sorted(
            item["migration_id"]
            for item in report.metadata_mismatches
            if item.get("migration_id") in required
        )
    )
    required_duplicate_drift = tuple(
        sorted(set(report.duplicate_applied_ids) & set(required))
    )
    if (
        report.status in {"database_unconfigured", "ledger_missing"}
        or unknown_required
        or pending_required
        or required_checksum_drift
        or required_missing_checksums
        or required_metadata_drift
        or required_duplicate_drift
    ):
        detail = json.dumps(
            {
                "status": "runtime_incompatible",
                "pending_required": pending_required,
                "required_checksum_drift": required_checksum_drift,
                "required_missing_checksums": required_missing_checksums,
                "required_metadata_drift": required_metadata_drift,
                "required_duplicate_drift": required_duplicate_drift,
                "unknown_required": unknown_required,
                "unrelated_pending": tuple(
                    value for value in report.pending if value not in pending_required
                ),
            },
            sort_keys=True,
        )
        raise MigrationStateError(
            "Database schema is missing migrations required by this runtime "
            f"capability: {detail}",
            report,
        )

    if report.status == "drift" or report.pending:
        logger.warning(
            "[Migrations] Runtime compatible with unrelated control-plane drift: "
            "%d pending, %d checksum mismatches, %d metadata mismatches",
            len(report.pending),
            len(report.checksum_mismatches),
            len(report.metadata_mismatches),
        )
    else:
        logger.info(
            "[Migrations] Runtime schema compatible; schema fingerprint %s",
            report.database_fingerprint,
        )
    return report


@dataclass(frozen=True)
class ProbeSpec:
    name: str
    sql: str
    parameters: dict[str, Any]


def _table_probes(*tables: str) -> tuple[ProbeSpec, ...]:
    return tuple(
        ProbeSpec(
            name=f"table:{table_name}",
            sql="SELECT to_regclass(:qualified_name) IS NOT NULL",
            parameters={"qualified_name": f"public.{table_name}"},
        )
        for table_name in tables
    )


def _column_probes(table_name: str, *columns: str) -> tuple[ProbeSpec, ...]:
    return tuple(
        ProbeSpec(
            name=f"column:{table_name}.{column_name}",
            sql="""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                      AND column_name = :column_name
                )
            """,
            parameters={"table_name": table_name, "column_name": column_name},
        )
        for column_name in columns
    )


def _constraint_probes(
    table_name: str, constraint_name: str, *needles: str
) -> tuple[ProbeSpec, ...]:
    return tuple(
        ProbeSpec(
            name=f"constraint:{table_name}.{constraint_name}:contains:{needle}",
            sql="""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'public'
                      AND t.relname = :table_name
                      AND c.conname = :constraint_name
                      AND pg_get_constraintdef(c.oid) ILIKE :needle
                )
            """,
            parameters={
                "table_name": table_name,
                "constraint_name": constraint_name,
                "needle": f"%{needle}%",
            },
        )
        for needle in needles
    )


def _policy_probes(table_name: str, *policy_names: str) -> tuple[ProbeSpec, ...]:
    return tuple(
        ProbeSpec(
            name=f"policy:{table_name}.{policy_name}",
            sql="""
                SELECT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public'
                      AND tablename = :table_name
                      AND policyname = :policy_name
                )
            """,
            parameters={"table_name": table_name, "policy_name": policy_name},
        )
        for policy_name in policy_names
    )


def _function_probes(schema_name: str, *function_names: str) -> tuple[ProbeSpec, ...]:
    return tuple(
        ProbeSpec(
            name=f"function:{schema_name}.{function_name}",
            sql="""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_proc procedure
                    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = :schema_name
                      AND procedure.proname = :function_name
                )
            """,
            parameters={
                "schema_name": schema_name,
                "function_name": function_name,
            },
        )
        for function_name in function_names
    )


def _data_catalog_014_probes() -> tuple[ProbeSpec, ...]:
    return (
        ProbeSpec(
            name="migration_014:data_catalog_rls_or_048_superseding_view",
            sql="""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class active
                    JOIN pg_namespace n ON n.oid = active.relnamespace
                    WHERE n.nspname = 'public'
                      AND active.relname = 'agent_data_catalog'
                      AND (
                        (
                          active.relkind = 'r'
                          AND active.relrowsecurity
                          AND active.relforcerowsecurity
                          AND (
                            SELECT COUNT(*) FROM pg_policies
                            WHERE schemaname = 'public'
                              AND tablename = 'agent_data_catalog'
                              AND policyname IN (
                                'agent_data_catalog_select',
                                'agent_data_catalog_insert',
                                'agent_data_catalog_update',
                                'agent_data_catalog_delete'
                              )
                          ) = 4
                        )
                        OR
                        (
                          active.relkind = 'v'
                          AND pg_get_viewdef(active.oid, true) ILIKE '%agent_data_assets%'
                          AND EXISTS (
                            SELECT 1
                            FROM pg_class legacy
                            JOIN pg_namespace ln ON ln.oid = legacy.relnamespace
                            WHERE ln.nspname = 'public'
                              AND legacy.relname = 'agent_data_catalog_deprecated'
                              AND legacy.relkind = 'r'
                              AND legacy.relrowsecurity
                              AND legacy.relforcerowsecurity
                          )
                          AND (
                            SELECT COUNT(*) FROM pg_policies
                            WHERE schemaname = 'public'
                              AND tablename = 'agent_data_catalog_deprecated'
                              AND policyname IN (
                                'agent_data_catalog_select',
                                'agent_data_catalog_insert',
                                'agent_data_catalog_update',
                                'agent_data_catalog_delete'
                              )
                          ) = 4
                        )
                      )
                )
            """,
            parameters={},
        ),
    )


# Only known historical out-of-ledger states are eligible for reconciliation.
# A future migration must add its own precise probes before it can be baselined.
RECONCILIATION_PROBES: dict[str, tuple[ProbeSpec, ...]] = {
    "000_legacy_runtime_prerequisites": _table_probes(
        "agent_user_tools",
        "agent_mcp_servers",
        "agent_knowledge_bases",
        "agent_kb_documents",
        "agent_kb_chunks",
    ),
    "011_create_stream_tables": _table_probes(
        "stream_configs", "stream_locations", "stream_alerts"
    ),
    "011_create_semantic_metrics": _table_probes("agent_semantic_metrics"),
    "012_virtual_sources": _table_probes("agent_virtual_sources")
    + _column_probes("agent_virtual_sources", "schema_mapping", "default_crs"),
    "012_create_teams": _table_probes("agent_teams", "agent_team_members"),
    "013_extend_rls_for_teams": _table_probes("agent_teams", "agent_team_members")
    + _policy_probes(
        "agent_table_ownership", "agent_table_ownership_select"
    )
    + _policy_probes("agent_analysis_templates", "agent_templates_select"),
    "013_rating_clone": _column_probes(
        "agent_custom_skills", "rating_sum", "rating_count", "clone_count"
    )
    + _column_probes(
        "agent_user_tools", "rating_sum", "rating_count", "clone_count"
    ),
    "014_workflow_checkpoints": _column_probes(
        "agent_workflow_runs", "node_checkpoints"
    ),
    "014_create_data_catalog": _data_catalog_014_probes(),
    "015_version_tags": _column_probes(
        "agent_custom_skills", "version", "category", "tags", "use_count"
    )
    + _column_probes(
        "agent_user_tools", "version", "category", "tags", "use_count"
    )
    + _table_probes("agent_skill_versions", "agent_tool_versions"),
    "016_skill_approval": _column_probes(
        "agent_custom_skills", "publish_status", "review_note", "reviewed_by"
    ),
    "015_add_email_column": _column_probes("agent_app_users", "email"),
    "016_create_map_annotations": _table_probes("agent_map_annotations"),
    "017_skill_deps_webhook": _column_probes(
        "agent_custom_skills", "depends_on", "webhook_url", "webhook_events"
    ),
    "017_create_workflows": _table_probes(
        "agent_workflows", "agent_workflow_runs"
    ),
    "071_std_documents_and_versions": _table_probes(
        "std_document", "std_document_version"
    )
    + _constraint_probes(
        "std_document", "fk_std_document_current_version", "DEFERRABLE"
    ),
    "072_std_clauses_and_elements": _table_probes(
        "std_clause",
        "std_term",
        "std_value_domain",
        "std_value_domain_item",
        "std_data_element",
    )
    + _column_probes("std_clause", "ordinal_path", "embedding"),
    "073_std_references_and_snapshots": _table_probes(
        "std_web_snapshot", "std_search_session", "std_search_hit", "std_reference"
    ),
    "074_std_outbox": _table_probes("std_outbox"),
    "075_downstream_derived_link_fk": _table_probes("std_derived_link"),
    "076_std_reference_extend_targets": _column_probes(
        "std_reference",
        "target_data_element_id",
        "target_term_id",
        "verification_status",
    )
    + _constraint_probes(
        "std_reference",
        "std_reference_target_kind_check",
        "std_data_element",
        "std_term",
    ),
    "077_relax_internet_search_url_requirement": _constraint_probes(
        "std_reference",
        "std_reference_target_consistency",
        "target_kind = 'internet_search'",
    ),
    "078_std_review_tables": _table_probes(
        "std_review_round", "std_review_comment"
    )
    + _constraint_probes(
        "std_review_round", "std_review_round_outcome_check", "approved"
    ),
    "079_std_publish_derivation": _column_probes(
        "std_data_element", "bound_table", "bound_column"
    )
    + _table_probes("std_publish_event"),
    "080_agent_semantic_hints_derived": _column_probes(
        "agent_semantic_hints", "std_version_id", "derived_status"
    ),
    "083_agent_quality_rules_derived": _column_probes(
        "agent_quality_rules",
        "std_derived_link_id",
        "std_version_id",
        "source_tag",
        "derived_status",
    )
    + _constraint_probes(
        "agent_quality_rules", "agent_quality_rules_derived_link_fk", "FOREIGN KEY"
    ),
    "084_agent_defect_code_bindings": _table_probes(
        "agent_defect_code_bindings"
    ),
    "085_std_data_model_snapshot": _table_probes("std_data_model_snapshot")
    + _constraint_probes(
        "std_derived_link",
        "std_derived_link_source_kind_check",
        "'document_version'::text",
    )
    + _constraint_probes(
        "std_derived_link",
        "std_derived_link_target_kind_check",
        "'data_model'::text",
    ),
    "086_std_market_subscription": _table_probes("std_market_subscription"),
    "087_std_market_listing": _table_probes("std_market_listing"),
    "088_std_market_listing_org_access": _column_probes(
        "std_market_listing", "visibility_scope", "owner_org_id", "allowed_org_ids"
    ),
    "091_twm_spatial_policy_rule_derivation": _constraint_probes(
        "std_derived_link",
        "std_derived_link_target_kind_check",
        "spatial_policy_rule",
    ),
    "132_governed_map_publications": _table_probes(
        "agent_map_publications", "agent_map_publication_events"
    )
    + _function_probes("map_serving", "publication_mvt"),
}


def _run_probes(conn, migration_id: str) -> list[dict[str, Any]]:
    specs = RECONCILIATION_PROBES.get(migration_id)
    if not specs:
        raise MigrationReconciliationError(
            f"Migration {migration_id!r} has no approved reconciliation probes"
        )
    evidence = []
    for spec in specs:
        passed = bool(conn.execute(text(spec.sql), spec.parameters).scalar_one())
        evidence.append({"name": spec.name, "passed": passed})
    return evidence


def _non_baseline_drift(report: MigrationReport) -> bool:
    return bool(
        report.unknown_applied
        or report.duplicate_applied_ids
        or report.checksum_mismatches
        or report.metadata_mismatches
    )


def reconcile_legacy_schema(
    *,
    actor: str,
    reason: str,
    recorded_without_checksum: bool = False,
    migration_ids: Sequence[str] = (),
    all_probed_pending: bool = False,
    exclude_migration_ids: Sequence[str] = (),
) -> MigrationReport:
    """Explicitly baseline verified historical state; never execute migration SQL."""
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise MigrationReconciliationError("Reconciliation requires actor and reason")
    if not (recorded_without_checksum or migration_ids or all_probed_pending):
        raise MigrationReconciliationError(
            "Select --recorded-without-checksum, --migration-id, or "
            "--all-probed-pending"
        )

    migrations = discover_migrations()
    catalog_by_id = {migration.migration_id: migration for migration in migrations}
    engine = get_engine()
    if engine is None:
        raise MigrationStateError("Database is not configured")

    with engine.connect() as conn:
        with _migration_lock(conn):
            _ensure_migrations_table(conn, migrations)
            applied, ledger_format = _load_applied(conn)
            before = _build_schema_report(
                migrations, applied, ledger_present=True, ledger_format=ledger_format
            )
            if _non_baseline_drift(before):
                raise MigrationDriftError(
                    "Non-reconcilable migration drift exists; refusing baseline",
                    before,
                )

            applied_by_id = {row["migration_id"]: row for row in applied}
            targets = set(migration_ids)
            if all_probed_pending:
                targets.update(
                    migration_id
                    for migration_id in before.pending
                    if migration_id in RECONCILIATION_PROBES
                )
            targets.difference_update(exclude_migration_ids)
            unknown_targets = sorted(targets - catalog_by_id.keys())
            if unknown_targets:
                raise MigrationReconciliationError(
                    "Unknown migration IDs: " + ", ".join(unknown_targets), before
                )

            probe_evidence: dict[str, list[dict[str, Any]]] = {}
            probe_failures = []
            for migration_id in sorted(targets):
                if migration_id in applied_by_id:
                    continue
                evidence = _run_probes(conn, migration_id)
                probe_evidence[migration_id] = evidence
                failed = [item for item in evidence if not item["passed"]]
                if failed:
                    probe_failures.append(
                        {"migration_id": migration_id, "failed": failed}
                    )
            if probe_failures:
                report = replace(before, probe_failures=tuple(probe_failures))
                raise MigrationReconciliationError(
                    "Schema probes failed; no migration baselines were written",
                    report,
                )

            reconciled: list[str] = []
            try:
                if recorded_without_checksum:
                    for migration_id in before.missing_checksums:
                        migration = catalog_by_id.get(migration_id)
                        row = applied_by_id.get(migration_id)
                        if migration is None or row is None:
                            raise MigrationReconciliationError(
                                f"Cannot map recorded migration {migration_id!r}", before
                            )
                        conn.execute(
                            text(
                                f"UPDATE {T_MIGRATIONS} SET "
                                "checksum = :checksum, "
                                "execution_kind = 'legacy_checksum_baseline', "
                                "reconciled_at = CURRENT_TIMESTAMP, "
                                "reconciled_by = :actor, "
                                "reconciliation_reason = :reason, "
                                "probe_evidence = CAST(:evidence AS JSONB) "
                                "WHERE migration_id = :migration_id "
                                "AND checksum IS NULL"
                            ),
                            {
                                "checksum": migration.checksum,
                                "actor": actor,
                                "reason": reason,
                                "evidence": json.dumps(
                                    {
                                        "mode": "recorded_ledger_baseline",
                                        "historical_content_unverifiable": True,
                                    }
                                ),
                                "migration_id": migration_id,
                            },
                        )
                        reconciled.append(migration_id)

                for migration_id in sorted(targets):
                    if migration_id in applied_by_id:
                        continue
                    migration = catalog_by_id[migration_id]
                    conn.execute(
                        text(
                            f"INSERT INTO {T_MIGRATIONS} "
                            "(migration_id, version, filename, checksum, "
                            "execution_kind, reconciled_at, reconciled_by, "
                            "reconciliation_reason, probe_evidence) VALUES "
                            "(:migration_id, :version, :filename, :checksum, "
                            "'schema_reconciled', CURRENT_TIMESTAMP, :actor, "
                            ":reason, CAST(:evidence AS JSONB))"
                        ),
                        {
                            "migration_id": migration.migration_id,
                            "version": migration.version,
                            "filename": migration.filename,
                            "checksum": migration.checksum,
                            "actor": actor,
                            "reason": reason,
                            "evidence": json.dumps(probe_evidence[migration_id]),
                        },
                    )
                    reconciled.append(migration_id)
                conn.commit()
                _enforce_checksum_not_null(conn)
            except Exception:
                conn.rollback()
                raise

            current, ledger_format = _load_applied(conn)
            report = _build_schema_report(
                migrations, current, ledger_present=True, ledger_format=ledger_format
            )
            return replace(report, reconciled_this_run=tuple(sorted(reconciled)))


def run_pending_migrations() -> MigrationReport:
    """Apply pending SQL in order; rollback and stop on the first failure."""
    migrations = discover_migrations()
    engine = get_engine()
    if engine is None:
        raise MigrationStateError("Database is not configured")

    with engine.connect() as conn:
        with _migration_lock(conn):
            _ensure_migrations_table(conn, migrations)
            applied, ledger_format = _load_applied(conn)
            before = _build_schema_report(
                migrations, applied, ledger_present=True, ledger_format=ledger_format
            )
            if before.status == "drift":
                raise MigrationDriftError(
                    "Migration ledger drift detected before SQL execution", before
                )
            applied_ids = {row["migration_id"] for row in applied}
            pending = [
                migration
                for migration in migrations
                if migration.migration_id not in applied_ids
            ]
            applied_this_run: list[str] = []
            for migration in pending:
                try:
                    conn.execute(text(migration.path.read_text(encoding="utf-8")))
                    conn.execute(
                        text(
                            f"INSERT INTO {T_MIGRATIONS} "
                            "(migration_id, version, filename, checksum, execution_kind) "
                            "VALUES (:migration_id, :version, :filename, :checksum, "
                            "'executed')"
                        ),
                        {
                            "migration_id": migration.migration_id,
                            "version": migration.version,
                            "filename": migration.filename,
                            "checksum": migration.checksum,
                        },
                    )
                    conn.commit()
                    applied_this_run.append(migration.migration_id)
                    logger.info("[Migrations] Applied: %s", migration.filename)
                except Exception as exc:
                    conn.rollback()
                    raise MigrationExecutionError(
                        f"Migration {migration.filename} failed; later migrations "
                        f"were not attempted: {exc}",
                        before,
                    ) from exc
            _enforce_checksum_not_null(conn)
            current, ledger_format = _load_applied(conn)
            report = _build_schema_report(
                migrations, current, ledger_present=True, ledger_format=ledger_format
            )
            return replace(report, applied_this_run=tuple(applied_this_run))


def compare_schema_reports(
    left: Mapping[str, Any] | MigrationReport,
    right: Mapping[str, Any] | MigrationReport,
) -> dict[str, Any]:
    left_payload = left.to_dict() if isinstance(left, MigrationReport) else dict(left)
    right_payload = right.to_dict() if isinstance(right, MigrationReport) else dict(right)
    fields = (
        "catalog_fingerprint",
        "database_fingerprint",
        "catalog_count",
        "applied_count",
        "status",
    )
    differences = {
        field: {"left": left_payload.get(field), "right": right_payload.get(field)}
        for field in fields
        if left_payload.get(field) != right_payload.get(field)
    }
    return {"match": not differences, "differences": differences}


def _write_report(report: MigrationReport | Mapping[str, Any], output: str | None) -> None:
    payload = report.to_dict() if isinstance(report, MigrationReport) else dict(report)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("validate", "validate the code migration catalog"),
        ("audit", "read-only audit of catalog and database ledger"),
        ("status", "alias for audit"),
        ("migrate", "apply pending migrations"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--output")

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="explicitly baseline probe-verified historical schema"
    )
    reconcile_parser.add_argument("--actor", required=True)
    reconcile_parser.add_argument("--reason", required=True)
    reconcile_parser.add_argument("--recorded-without-checksum", action="store_true")
    reconcile_parser.add_argument("--migration-id", action="append", default=[])
    reconcile_parser.add_argument("--all-probed-pending", action="store_true")
    reconcile_parser.add_argument("--exclude-migration-id", action="append", default=[])
    reconcile_parser.add_argument("--output")

    compare_parser = subparsers.add_parser(
        "compare", help="compare two exported environment reports"
    )
    compare_parser.add_argument("left")
    compare_parser.add_argument("right")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            migrations = discover_migrations()
            _write_report(
                {
                    "status": "valid",
                    "catalog_count": len(migrations),
                    "catalog_fingerprint": catalog_fingerprint(migrations),
                    "legacy_version_collisions": {
                        version: sorted(filenames)
                        for version, filenames in LEGACY_VERSION_COLLISIONS.items()
                    },
                },
                args.output,
            )
            return 0
        if args.command in {"audit", "status"}:
            report = get_schema_report()
            _write_report(report, args.output)
            return 0 if report.status == "in_sync" else 1
        if args.command == "migrate":
            report = run_pending_migrations()
            _write_report(report, args.output)
            return 0 if report.status == "in_sync" else 1
        if args.command == "reconcile":
            report = reconcile_legacy_schema(
                actor=args.actor,
                reason=args.reason,
                recorded_without_checksum=args.recorded_without_checksum,
                migration_ids=args.migration_id,
                all_probed_pending=args.all_probed_pending,
                exclude_migration_ids=args.exclude_migration_id,
            )
            _write_report(report, args.output)
            return 0 if report.status == "in_sync" else 1

        left = json.loads(Path(args.left).read_text(encoding="utf-8"))
        right = json.loads(Path(args.right).read_text(encoding="utf-8"))
        comparison = compare_schema_reports(left, right)
        _write_report(comparison, None)
        return 0 if comparison["match"] else 1
    except (MigrationFailure, SQLAlchemyError, OSError, json.JSONDecodeError) as exc:
        logger.error("[Migrations] %s", exc)
        payload: dict[str, Any] = {"status": "error", "error": str(exc)}
        if isinstance(exc, MigrationFailure) and exc.report is not None:
            payload["report"] = exc.report.to_dict()
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
