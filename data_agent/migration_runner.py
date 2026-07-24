"""Fail-closed SQL migration runner and schema ledger.

Migration filenames are stable identifiers: ``NNN_description.sql``.  The
numeric prefix controls ordering, while the full filename (without ``.sql``)
is the migration ID.  A checksum makes applied migration content immutable.

Versions 011-017 contain known historical collisions.  They are explicitly
allowlisted so existing databases can converge without renaming or rewriting
already-applied migrations.  Any new version collision is rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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

# These collisions predate the strict ledger.  The complete filename sets are
# frozen here; adding another file at one of these versions fails validation.
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
}

# Several v14-era files reused old numeric prefixes even though they depend on
# later migrations.  Preserve their IDs and content, but execute them after the
# dependency that existed when they were originally introduced.
LEGACY_DEFERRED_ORDER = {
    "014_workflow_checkpoints": (17, 1),
    "013_rating_clone": (21, 1),
    "015_version_tags": (21, 2),
    "016_skill_approval": (21, 3),
    "017_skill_deps_webhook": (21, 4),
}


class MigrationError(RuntimeError):
    """Base class for migration contract and execution failures."""


class MigrationDiscoveryError(MigrationError):
    """The migration catalog does not satisfy the filename/ID contract."""


class MigrationDriftError(MigrationError):
    """The database ledger differs from the migration catalog."""


class MigrationExecutionError(MigrationError):
    """A migration failed and was rolled back."""


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_sort_key(migration: dict[str, Any]) -> tuple[int, int, str]:
    logical_order = LEGACY_DEFERRED_ORDER.get(migration["migration_id"])
    if logical_order is None:
        logical_order = (int(migration["version"]), 0)
    return (*logical_order, migration["filename"])


def _fingerprint(entries: Iterable[tuple[str, str | None]]) -> str:
    digest = hashlib.sha256()
    for migration_id, checksum in sorted(entries):
        digest.update(migration_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update((checksum or "<missing>").encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def discover_migrations(migrations_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return the validated migration catalog in deterministic apply order."""
    directory = migrations_dir or MIGRATIONS_DIR
    if not directory.exists():
        return []

    migrations: list[dict[str, Any]] = []
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
            {
                "migration_id": migration_id,
                "version": match.group("version"),
                "filename": path.name,
                "path": path,
                "checksum": _checksum(path),
            }
        )

    if invalid_filenames:
        raise MigrationDiscoveryError(
            "Invalid migration filenames; expected NNN_description.sql: "
            + ", ".join(invalid_filenames)
        )

    files_by_version: dict[str, set[str]] = defaultdict(set)
    for migration in migrations:
        files_by_version[migration["version"]].add(migration["filename"])

    collisions = {
        version: filenames
        for version, filenames in files_by_version.items()
        if len(filenames) > 1
    }
    incomplete_legacy_sets = {
        version: {
            "expected": expected,
            "actual": files_by_version.get(version, set()),
        }
        for version, expected in LEGACY_VERSION_COLLISIONS.items()
        if files_by_version.get(version)
        and files_by_version[version] != set(expected)
    }
    if incomplete_legacy_sets:
        detail = "; ".join(
            f"{version}: expected {', '.join(sorted(values['expected']))}; "
            f"found {', '.join(sorted(values['actual'])) or '<none>'}"
            for version, values in sorted(incomplete_legacy_sets.items())
        )
        raise MigrationDiscoveryError(
            f"Frozen legacy migration set was changed ({detail})"
        )

    unexpected = {
        version: filenames
        for version, filenames in collisions.items()
        if LEGACY_VERSION_COLLISIONS.get(version) != frozenset(filenames)
    }
    if unexpected:
        detail = "; ".join(
            f"{version}: {', '.join(sorted(filenames))}"
            for version, filenames in sorted(unexpected.items())
        )
        raise MigrationDiscoveryError(
            "Duplicate migration versions are forbidden outside the frozen "
            f"legacy allowlist ({detail})"
        )

    return sorted(migrations, key=_migration_sort_key)


def catalog_fingerprint(migrations: list[dict[str, Any]] | None = None) -> str:
    """Return a stable fingerprint for the code migration catalog."""
    catalog = migrations if migrations is not None else discover_migrations()
    return _fingerprint(
        (migration["migration_id"], migration["checksum"])
        for migration in catalog
    )


def _quote_identifier(conn, identifier: str) -> str:
    return conn.dialect.identifier_preparer.quote(identifier)


def _ensure_migrations_table(conn, migrations: list[dict[str, Any]]) -> None:
    """Create or forward-upgrade the migration ledger on one connection."""
    conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {T_MIGRATIONS} (
                id BIGSERIAL PRIMARY KEY,
                migration_id VARCHAR(255) NOT NULL,
                version VARCHAR(32) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    conn.commit()

    schema = inspect(conn)
    columns = {
        column["name"]: column for column in schema.get_columns(T_MIGRATIONS)
    }
    if "migration_id" not in columns:
        conn.execute(
            text(
                f"ALTER TABLE {T_MIGRATIONS} "
                "ADD COLUMN migration_id VARCHAR(255)"
            )
        )
    if "checksum" not in columns:
        conn.execute(
            text(
                f"ALTER TABLE {T_MIGRATIONS} "
                "ADD COLUMN checksum VARCHAR(64)"
            )
        )
    conn.commit()

    catalog_by_filename = {
        migration["filename"]: migration for migration in migrations
    }
    rows = conn.execute(
        text(
            f"SELECT id, version, filename, migration_id, checksum "
            f"FROM {T_MIGRATIONS} ORDER BY id"
        )
    ).mappings().all()
    for row in rows:
        migration = catalog_by_filename.get(row["filename"])
        migration_id = row["migration_id"] or Path(row["filename"]).stem
        checksum = row["checksum"] or (
            migration["checksum"] if migration is not None else None
        )
        conn.execute(
            text(
                f"UPDATE {T_MIGRATIONS} "
                "SET migration_id = :migration_id, checksum = :checksum "
                "WHERE id = :row_id"
            ),
            {
                "migration_id": migration_id,
                "checksum": checksum,
                "row_id": row["id"],
            },
        )
    conn.commit()

    duplicate_ids = conn.execute(
        text(
            f"SELECT migration_id, COUNT(*) AS count "
            f"FROM {T_MIGRATIONS} "
            "WHERE migration_id IS NOT NULL "
            "GROUP BY migration_id HAVING COUNT(*) > 1"
        )
    ).mappings().all()
    if duplicate_ids:
        detail = ", ".join(
            f"{row['migration_id']} ({row['count']})" for row in duplicate_ids
        )
        raise MigrationDriftError(f"Duplicate migration IDs in ledger: {detail}")

    if "migration_id" not in columns or columns["migration_id"].get(
        "nullable", True
    ):
        conn.execute(
            text(
                f"ALTER TABLE {T_MIGRATIONS} "
                "ALTER COLUMN migration_id SET NOT NULL"
            )
        )

    missing_checksum_count = conn.execute(
        text(
            f"SELECT COUNT(*) FROM {T_MIGRATIONS} WHERE checksum IS NULL"
        )
    ).scalar_one()
    if (
        not missing_checksum_count
        and (
            "checksum" not in columns
            or columns["checksum"].get("nullable", True)
        )
    ):
        conn.execute(
            text(
                f"ALTER TABLE {T_MIGRATIONS} "
                "ALTER COLUMN checksum SET NOT NULL"
            )
        )

    unique_constraints = inspect(conn).get_unique_constraints(T_MIGRATIONS)
    for constraint in unique_constraints:
        if constraint.get("column_names") == ["version"]:
            constraint_name = constraint.get("name")
            if not constraint_name:
                raise MigrationDriftError(
                    "Cannot identify the legacy version uniqueness constraint"
                )
            conn.execute(
                text(
                    f"ALTER TABLE {T_MIGRATIONS} DROP CONSTRAINT "
                    f"{_quote_identifier(conn, constraint_name)}"
                )
            )

    has_id_unique = any(
        constraint.get("column_names") == ["migration_id"]
        for constraint in unique_constraints
    )
    if not has_id_unique:
        conn.execute(
            text(
                f"ALTER TABLE {T_MIGRATIONS} "
                "ADD CONSTRAINT uq_schema_migrations_migration_id "
                "UNIQUE (migration_id)"
            )
        )
    conn.commit()


def ensure_migrations_table() -> None:
    """Create/upgrade the ledger without applying catalog migrations."""
    engine = get_engine()
    if engine is None:
        return
    migrations = discover_migrations()
    with engine.connect() as conn:
        with _migration_lock(conn):
            _ensure_migrations_table(conn, migrations)


def _load_applied(conn) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            text(
                f"SELECT migration_id, version, filename, checksum, applied_at "
                f"FROM {T_MIGRATIONS} ORDER BY version, filename"
            )
        ).mappings().all()
    ]


def get_applied_versions(conn) -> set[str]:
    """Compatibility helper returning numeric versions from the new ledger."""
    return {row["version"] for row in _load_applied(conn)}


@contextmanager
def _migration_lock(conn):
    """Serialize migration runners with a PostgreSQL session advisory lock."""
    is_postgres = conn.dialect.name == "postgresql"
    if is_postgres:
        conn.execute(
            text("SELECT pg_advisory_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )
    try:
        yield
    finally:
        if is_postgres:
            conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )


def _build_schema_report(
    migrations: list[dict[str, Any]], applied: list[dict[str, Any]]
) -> dict[str, Any]:
    catalog_by_id = {
        migration["migration_id"]: migration for migration in migrations
    }
    applied_by_id = {row["migration_id"]: row for row in applied}

    pending = [
        migration["migration_id"]
        for migration in migrations
        if migration["migration_id"] not in applied_by_id
    ]
    unknown_applied = sorted(
        migration_id
        for migration_id in applied_by_id
        if migration_id not in catalog_by_id
    )
    missing_checksums = sorted(
        row["migration_id"] for row in applied if not row.get("checksum")
    )
    checksum_mismatches = []
    metadata_mismatches = []
    for migration_id in sorted(catalog_by_id.keys() & applied_by_id.keys()):
        migration = catalog_by_id[migration_id]
        row = applied_by_id[migration_id]
        if row.get("checksum") and row["checksum"] != migration["checksum"]:
            checksum_mismatches.append(
                {
                    "migration_id": migration_id,
                    "expected": migration["checksum"],
                    "actual": row["checksum"],
                }
            )
        if (
            row["version"] != migration["version"]
            or row["filename"] != migration["filename"]
        ):
            metadata_mismatches.append(
                {
                    "migration_id": migration_id,
                    "expected_version": migration["version"],
                    "actual_version": row["version"],
                    "expected_filename": migration["filename"],
                    "actual_filename": row["filename"],
                }
            )

    has_drift = bool(
        unknown_applied
        or missing_checksums
        or checksum_mismatches
        or metadata_mismatches
    )
    status = "drift" if has_drift else ("pending" if pending else "in_sync")
    return {
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "catalog_fingerprint": catalog_fingerprint(migrations),
        "database_fingerprint": _fingerprint(
            (row["migration_id"], row.get("checksum")) for row in applied
        ),
        "catalog_count": len(migrations),
        "applied_count": len(applied),
        "pending": pending,
        "unknown_applied": unknown_applied,
        "missing_checksums": missing_checksums,
        "checksum_mismatches": checksum_mismatches,
        "metadata_mismatches": metadata_mismatches,
        "legacy_version_collisions": {
            version: sorted(filenames)
            for version, filenames in LEGACY_VERSION_COLLISIONS.items()
        },
    }


def get_schema_report() -> dict[str, Any]:
    """Return code/database fingerprints and actionable schema differences."""
    migrations = discover_migrations()
    engine = get_engine()
    if engine is None:
        return {
            "format_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "database_unconfigured",
            "catalog_fingerprint": catalog_fingerprint(migrations),
            "catalog_count": len(migrations),
        }

    with engine.connect() as conn:
        with _migration_lock(conn):
            _ensure_migrations_table(conn, migrations)
            return _build_schema_report(migrations, _load_applied(conn))


def compare_schema_reports(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    """Compare two exported environment reports without database access."""
    fields = (
        "catalog_fingerprint",
        "database_fingerprint",
        "catalog_count",
        "applied_count",
        "status",
    )
    differences = {
        field: {"left": left.get(field), "right": right.get(field)}
        for field in fields
        if left.get(field) != right.get(field)
    }
    return {"match": not differences, "differences": differences}


def run_pending_migrations() -> dict[str, Any]:
    """Apply all pending migrations transactionally; raise on any failure."""
    migrations = discover_migrations()
    engine = get_engine()
    if engine is None:
        logger.info("[Migrations] Database is not configured; nothing to apply")
        return {
            "status": "database_unconfigured",
            "catalog_fingerprint": catalog_fingerprint(migrations),
            "catalog_count": len(migrations),
        }

    with engine.connect() as conn:
        with _migration_lock(conn):
            _ensure_migrations_table(conn, migrations)
            applied = _load_applied(conn)
            before = _build_schema_report(migrations, applied)
            if before["status"] == "drift":
                raise MigrationDriftError(
                    "Migration ledger drift detected: "
                    + json.dumps(
                        {
                            "unknown_applied": before["unknown_applied"],
                            "missing_checksums": before["missing_checksums"],
                            "checksum_mismatches": before["checksum_mismatches"],
                            "metadata_mismatches": before["metadata_mismatches"],
                        },
                        sort_keys=True,
                    )
                )

            applied_ids = {row["migration_id"] for row in applied}
            pending = [
                migration
                for migration in migrations
                if migration["migration_id"] not in applied_ids
            ]
            if not pending:
                logger.info(
                    "[Migrations] All %d migrations already applied",
                    len(migrations),
                )
                return before

            for migration in pending:
                try:
                    sql = migration["path"].read_text(encoding="utf-8")
                    conn.execute(text(sql))
                    conn.execute(
                        text(
                            f"INSERT INTO {T_MIGRATIONS} "
                            "(migration_id, version, filename, checksum) "
                            "VALUES (:migration_id, :version, :filename, :checksum)"
                        ),
                        {
                            "migration_id": migration["migration_id"],
                            "version": migration["version"],
                            "filename": migration["filename"],
                            "checksum": migration["checksum"],
                        },
                    )
                    conn.commit()
                    logger.info("[Migrations] Applied: %s", migration["filename"])
                except Exception as exc:
                    conn.rollback()
                    raise MigrationExecutionError(
                        f"Migration {migration['filename']} failed; startup is "
                        f"blocked: {exc}"
                    ) from exc

            report = _build_schema_report(migrations, _load_applied(conn))
            logger.info(
                "[Migrations] Applied %d migrations; schema fingerprint %s",
                len(pending),
                report["database_fingerprint"],
            )
            return report


def _write_report(report: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="validate the code migration catalog"
    )
    validate_parser.add_argument("--output")

    status_parser = subparsers.add_parser(
        "status", help="report catalog/database schema state"
    )
    status_parser.add_argument("--output")

    migrate_parser = subparsers.add_parser(
        "migrate", help="apply pending migrations"
    )
    migrate_parser.add_argument("--output")

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
        if args.command == "status":
            report = get_schema_report()
            _write_report(report, args.output)
            return 0 if report["status"] == "in_sync" else 1
        if args.command == "migrate":
            report = run_pending_migrations()
            _write_report(report, args.output)
            return 0 if report["status"] == "in_sync" else 1

        left = json.loads(Path(args.left).read_text(encoding="utf-8"))
        right = json.loads(Path(args.right).read_text(encoding="utf-8"))
        comparison = compare_schema_reports(left, right)
        _write_report(comparison, None)
        return 0 if comparison["match"] else 1
    except (
        MigrationError,
        SQLAlchemyError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        logger.error("[Migrations] %s", exc)
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
