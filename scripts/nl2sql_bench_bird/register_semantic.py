"""Bulk-register all BIRD PG schemas to the semantic layer.

For each `bird_<db_id>` schema, register every table into
`agent_semantic_sources` with display_name + synonyms derived from the table name,
and every column into `agent_semantic_registry` with description = data_type.

This populates the semantic layer so that `resolve_semantic_context()` can
match user questions against BIRD tables/columns.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine  # noqa: E402

OWNER = "bird_benchmark"


def main() -> int:
    engine = get_engine()
    if engine is None:
        print("ERROR: get_engine() returned None.", file=sys.stderr)
        return 2

    with engine.begin() as conn:
        # Find all bird_* schemas
        schemas = [r[0] for r in conn.execute(text(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name LIKE 'bird_%' ORDER BY schema_name"
        )).fetchall()]
        print(f"[register] Found {len(schemas)} BIRD schemas")

        total_tables = 0
        total_cols = 0

        for schema in schemas:
            db_id = schema.removeprefix("bird_")
            tables = [r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=:s ORDER BY table_name"
            ), {"s": schema}).fetchall()]

            for table in tables:
                # Note: agent_semantic_sources has UNIQUE(table_name) constraint,
                # so we prefix table_name with schema to avoid collisions
                # across multiple BIRD DBs (e.g. several have a "users" table).
                qualified_name = f"{schema}.{table}"
                display = f"{db_id}.{table}"
                synonyms = [table, f"{db_id}_{table}"]

                conn.execute(text("""
                    INSERT INTO agent_semantic_sources
                        (table_name, display_name, description, geometry_type, srid,
                         synonyms, suggested_analyses, owner_username)
                    VALUES (:t, :dn, :desc, NULL, NULL,
                            CAST(:syn AS jsonb), CAST('[]' AS jsonb), :owner)
                    ON CONFLICT (table_name) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        synonyms = EXCLUDED.synonyms,
                        updated_at = NOW()
                """), {
                    "t": qualified_name,
                    "dn": display,
                    "desc": f"BIRD mini_dev: {db_id}",
                    "syn": json.dumps(synonyms),
                    "owner": OWNER,
                })
                total_tables += 1

                # Columns
                cols = conn.execute(text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
                ), {"s": schema, "t": table}).fetchall()

                for col_name, data_type in cols:
                    conn.execute(text("""
                        INSERT INTO agent_semantic_registry
                            (table_name, column_name, semantic_domain, aliases,
                             unit, description, is_geometry, owner_username)
                        VALUES (:t, :col, NULL, CAST('[]' AS jsonb),
                                '', :desc, FALSE, :owner)
                        ON CONFLICT (table_name, column_name) DO UPDATE SET
                            description = EXCLUDED.description,
                            updated_at = NOW()
                    """), {
                        "t": qualified_name,
                        "col": col_name,
                        "desc": data_type,
                        "owner": OWNER,
                    })
                    total_cols += 1

            print(f"  {schema:35s} {len(tables):>3d} tables registered")

        print(f"\n[register] Done: {total_tables} tables, {total_cols} columns")

    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache()
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
