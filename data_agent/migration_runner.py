"""
Auto-migration runner — applies pending SQL migrations at startup.

Tracks applied migrations in a `schema_migrations` table.
Migration files: data_agent/migrations/NNN_description.sql
"""
import os
import re
import logging
from pathlib import Path

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
T_MIGRATIONS = "schema_migrations"


def ensure_migrations_table():
    """Create schema_migrations tracking table if not exists."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_MIGRATIONS} (
                    id SERIAL PRIMARY KEY,
                    version VARCHAR(10) NOT NULL UNIQUE,
                    filename VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
    except Exception as e:
        logger.warning("[Migrations] Failed to create tracking table: %s", e)


def get_applied_versions(conn) -> set:
    """Return set of already-applied migration version numbers."""
    try:
        rows = conn.execute(text(
            f"SELECT version FROM {T_MIGRATIONS}"
        )).fetchall()
        return {row[0] for row in rows}
    except Exception:
        return set()


def discover_migrations() -> list:
    """Find all .sql files in migrations/ dir, sorted by version number."""
    if not MIGRATIONS_DIR.exists():
        return []

    pattern = re.compile(r'^(\d{3})_.*\.sql$')
    migrations = []
    for f in sorted(MIGRATIONS_DIR.iterdir()):
        m = pattern.match(f.name)
        if m:
            migrations.append({
                "version": m.group(1),
                "filename": f.name,
                "path": f,
            })
    return migrations


def run_pending_migrations():
    """Apply all pending migrations in order. Called at startup."""
    engine = get_engine()
    if not engine:
        return

    ensure_migrations_table()

    migrations = discover_migrations()
    if not migrations:
        return

    try:
        with engine.connect() as conn:
            applied = get_applied_versions(conn)
            pending = [m for m in migrations if m["version"] not in applied]

            if not pending:
                logger.info("[Migrations] All %d migrations already applied", len(migrations))
                return

            for mig in pending:
                sql = mig["path"].read_text(encoding="utf-8")
                try:
                    conn.execute(text(sql))
                    conn.execute(text(
                        f"INSERT INTO {T_MIGRATIONS} (version, filename) "
                        f"VALUES (:ver, :fn)"
                    ), {"ver": mig["version"], "fn": mig["filename"]})
                    conn.commit()
                    logger.info("[Migrations] Applied: %s", mig["filename"])
                except Exception as e:
                    conn.rollback()
                    logger.warning("[Migrations] Failed %s: %s (skipping)", mig["filename"], e)

            logger.info("[Migrations] %d/%d pending migrations processed",
                        len(pending), len(migrations))
    except Exception as e:
        logger.error("[Migrations] Runner error: %s", e)
