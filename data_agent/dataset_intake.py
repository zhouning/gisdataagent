"""Dataset Intake — schema scanning, profile generation, and onboarding state machine.

Implements the semi-automatic cold-start pipeline for NL2Semantic2SQL:
  discovered → drafted → reviewed → validated → active
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

VALID_STATUSES = ("discovered", "drafted", "reviewed", "validated", "active")
VALID_TRANSITIONS = {
    "discovered": ("drafted",),
    "drafted": ("reviewed", "discovered"),
    "reviewed": ("validated", "drafted"),
    "validated": ("active", "reviewed"),
    "active": ("validated",),
}

_PII_PATTERNS = {"phone", "email", "id_card", "ssn", "password", "secret", "token"}
_LARGE_TABLE_THRESHOLD = 100_000


def _ensure_tables(conn):
    """Run intake migration idempotently."""
    import os
    mig = os.path.join(os.path.dirname(__file__), "migrations", "066_intake_metadata.sql")
    if os.path.exists(mig):
        with open(mig, encoding="utf-8") as f:
            sql = f.read()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass


def scan_tables(
    schema_name: str = "public",
    table_filter: Optional[list[str]] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Scan PostGIS tables and create dataset profiles.

    Returns dict with job_id, tables_found, profiles.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "error": "no database engine"}

    with engine.begin() as conn:
        _ensure_tables(conn)

        # Create intake job
        row = conn.execute(text("""
            INSERT INTO agent_intake_jobs (source_type, source_ref, status, created_by)
            VALUES ('postgis', :schema, 'running', :user)
            RETURNING id
        """), {"schema": schema_name, "user": created_by or "system"}).fetchone()
        job_id = row[0]

        # Discover tables
        filter_clause = ""
        params: dict = {"schema": schema_name}
        if table_filter:
            filter_clause = "AND c.table_name = ANY(:tables)"
            params["tables"] = table_filter

        tables = conn.execute(text(f"""
            SELECT c.table_name,
                   obj_description((quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass) AS tbl_comment
            FROM information_schema.tables c
            WHERE c.table_schema = :schema
              AND c.table_type = 'BASE TABLE'
              AND c.table_name NOT LIKE 'agent_%'
              AND c.table_name NOT LIKE 'pg_%'
              {filter_clause}
            ORDER BY c.table_name
        """), params).fetchall()

        profiles = []
        # Collect tables that already have a non-discovered profile (any job)
        existing_statuses = {}
        try:
            rows_existing = conn.execute(text("""
                SELECT DISTINCT ON (table_name) table_name, status
                FROM agent_dataset_profiles
                WHERE schema_name = :schema
                ORDER BY table_name, id DESC
            """), {"schema": schema_name}).fetchall()
            existing_statuses = {r[0]: r[1] for r in rows_existing}
        except Exception:
            pass

        for tbl_name, tbl_comment in tables:
            prev_status = existing_statuses.get(tbl_name)
            if prev_status and prev_status != "discovered":
                continue
            profile = _scan_single_table(conn, schema_name, tbl_name, tbl_comment, job_id)
            if profile:
                profiles.append(profile)

        conn.execute(text("""
            UPDATE agent_intake_jobs
            SET status = 'completed', tables_found = :n, finished_at = NOW()
            WHERE id = :jid
        """), {"n": len(profiles), "jid": job_id})

    return {
        "status": "ok",
        "job_id": job_id,
        "tables_found": len(profiles),
        "profiles": profiles,
    }


def _scan_single_table(conn, schema_name: str, table_name: str,
                        table_comment: Optional[str], job_id: int) -> Optional[dict]:
    """Scan a single table and insert its profile."""
    try:
        # Columns
        cols = conn.execute(text("""
            SELECT column_name, data_type, udt_name, is_nullable,
                   col_description((quote_ident(:schema) || '.' || quote_ident(:tbl))::regclass,
                                   ordinal_position) AS col_comment
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :tbl
            ORDER BY ordinal_position
        """), {"schema": schema_name, "tbl": table_name}).fetchall()

        columns_json = []
        for c in cols:
            col_name, data_type, udt_name, nullable, col_comment = c
            columns_json.append({
                "column_name": col_name,
                "data_type": data_type,
                "udt_name": udt_name,
                "nullable": nullable == "YES",
                "comment": col_comment or "",
            })

        # Geometry info
        geom = conn.execute(text("""
            SELECT type, srid FROM geometry_columns
            WHERE f_table_schema = :schema AND f_table_name = :tbl LIMIT 1
        """), {"schema": schema_name, "tbl": table_name}).fetchone()
        geometry_type = geom[0] if geom else None
        srid = geom[1] if geom else None

        # Row count estimate
        row_count = 0
        try:
            r = conn.execute(text(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = :t"
            ), {"t": table_name}).scalar()
            row_count = max(int(r or 0), 0)
        except Exception:
            pass

        # Sample values (first 3 non-geometry columns, 5 rows)
        sample_cols = [c["column_name"] for c in columns_json
                       if c["udt_name"] not in ("geometry", "geography")][:3]
        sample_values = {}
        if sample_cols:
            try:
                quoted = ", ".join(f'"{c}"' for c in sample_cols)
                sample_rows = conn.execute(text(
                    f'SELECT {quoted} FROM "{table_name}" LIMIT 5'
                )).fetchall()
                for i, col in enumerate(sample_cols):
                    sample_values[col] = [str(r[i]) if r[i] is not None else None
                                          for r in sample_rows]
            except Exception:
                pass

        # Primary key candidates
        pk_candidates = []
        try:
            pks = conn.execute(text("""
                SELECT a.attname FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = (quote_ident(:schema) || '.' || quote_ident(:tbl))::regclass
                  AND i.indisprimary
            """), {"schema": schema_name, "tbl": table_name}).fetchall()
            pk_candidates = [r[0] for r in pks]
        except Exception:
            pass

        # Risk tags
        risk_tags = []
        for c in columns_json:
            cn_lower = c["column_name"].lower()
            if any(p in cn_lower for p in _PII_PATTERNS):
                risk_tags.append({"type": "pii_suspect", "column": c["column_name"]})
        if row_count > _LARGE_TABLE_THRESHOLD:
            risk_tags.append({"type": "large_table", "row_count": row_count})
        if not geometry_type:
            risk_tags.append({"type": "no_geometry"})

        # Insert profile
        conn.execute(text("""
            INSERT INTO agent_dataset_profiles
                (job_id, table_name, schema_name, row_count, geometry_type, srid,
                 columns_json, sample_values, primary_key_candidates,
                 risk_tags, table_comment, status)
            VALUES (:jid, :tbl, :schema, :rows, :geom_type, :srid,
                    CAST(:cols AS jsonb), CAST(:samples AS jsonb), CAST(:pks AS jsonb),
                    CAST(:risks AS jsonb), :comment, 'discovered')
            ON CONFLICT (job_id, table_name) DO UPDATE SET
                row_count = EXCLUDED.row_count,
                columns_json = EXCLUDED.columns_json,
                sample_values = EXCLUDED.sample_values,
                risk_tags = EXCLUDED.risk_tags,
                updated_at = NOW()
        """), {
            "jid": job_id, "tbl": table_name, "schema": schema_name,
            "rows": row_count, "geom_type": geometry_type, "srid": srid,
            "cols": json.dumps(columns_json, ensure_ascii=False),
            "samples": json.dumps(sample_values, ensure_ascii=False),
            "pks": json.dumps(pk_candidates),
            "risks": json.dumps(risk_tags, ensure_ascii=False),
            "comment": table_comment,
        })

        return {
            "table_name": table_name,
            "row_count": row_count,
            "geometry_type": geometry_type,
            "srid": srid,
            "columns": len(columns_json),
            "risk_tags": [r["type"] for r in risk_tags],
        }
    except Exception as e:
        logger.warning("Failed to scan table %s: %s", table_name, e)
        return None


def get_job(job_id: int) -> Optional[dict]:
    """Get intake job status."""
    engine = get_engine()
    if not engine:
        return None
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id, source_type, source_ref, status, tables_found, error, "
            "started_at, finished_at, created_by FROM agent_intake_jobs WHERE id = :jid"
        ), {"jid": job_id}).fetchone()
        if not row:
            return None
        return dict(zip(
            ["id", "source_type", "source_ref", "status", "tables_found",
             "error", "started_at", "finished_at", "created_by"], row
        ))


def get_profile(table_name: str, job_id: Optional[int] = None) -> Optional[dict]:
    """Get the latest dataset profile for a table."""
    engine = get_engine()
    if not engine:
        return None
    with engine.connect() as conn:
        if job_id:
            row = conn.execute(text(
                "SELECT * FROM agent_dataset_profiles WHERE table_name = :t AND job_id = :j"
            ), {"t": table_name, "j": job_id}).fetchone()
        else:
            row = conn.execute(text(
                "SELECT * FROM agent_dataset_profiles WHERE table_name = :t ORDER BY id DESC LIMIT 1"
            ), {"t": table_name}).fetchone()
        if not row:
            return None
        keys = row._fields if hasattr(row, '_fields') else row.keys()
        return dict(zip(keys, row))


def list_profiles(
    status: Optional[str] = None,
    job_id: Optional[int] = None,
    schema_name: Optional[str] = None,
    latest_only: bool = True,
) -> list[dict]:
    """List dataset profiles, optionally filtered by status/job/schema.

    By default returns only the latest profile for each (schema_name, table_name)
    pair to avoid surfacing stale scan results.
    """
    engine = get_engine()
    if not engine:
        return []
    clauses = []
    params: dict = {}
    if status:
        clauses.append("status = :s")
        params["s"] = status
    if job_id:
        clauses.append("job_id = :j")
        params["j"] = job_id
    if schema_name:
        clauses.append("schema_name = :schema")
        params["schema"] = schema_name
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with engine.connect() as conn:
        if latest_only:
            rows = conn.execute(text(
                f"""
                WITH ranked AS (
                  SELECT id, table_name, schema_name, row_count, geometry_type, status, created_at,
                         ROW_NUMBER() OVER (PARTITION BY schema_name, table_name ORDER BY id DESC) AS rn
                  FROM agent_dataset_profiles
                  {where}
                )
                SELECT id, table_name, schema_name, row_count, geometry_type, status, created_at
                FROM ranked
                WHERE rn = 1
                ORDER BY schema_name, table_name
                """
            ), params).fetchall()
        else:
            rows = conn.execute(text(
                f"SELECT id, table_name, schema_name, row_count, geometry_type, status, created_at "
                f"FROM agent_dataset_profiles {where} ORDER BY schema_name, table_name, id DESC"
            ), params).fetchall()
        return [dict(zip(["id", "table_name", "schema_name", "row_count", "geometry_type", "status", "created_at"], r))
                for r in rows]


def transition_status(profile_id: int, new_status: str) -> bool:
    """Transition a dataset profile to a new status (state machine enforced)."""
    if new_status not in VALID_STATUSES:
        return False
    engine = get_engine()
    if not engine:
        return False
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT status FROM agent_dataset_profiles WHERE id = :pid"
        ), {"pid": profile_id}).fetchone()
        if not row:
            return False
        current = row[0]
        if new_status not in VALID_TRANSITIONS.get(current, ()):
            logger.warning("Invalid transition %s → %s for profile %d", current, new_status, profile_id)
            return False
        conn.execute(text(
            "UPDATE agent_dataset_profiles SET status = :s, updated_at = NOW() WHERE id = :pid"
        ), {"s": new_status, "pid": profile_id})
    return True
