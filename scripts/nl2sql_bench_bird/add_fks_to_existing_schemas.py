"""Add FK constraints to existing BIRD schemas without re-importing data.

For each BIRD schema in PostgreSQL, walks the corresponding SQLite source DB
and adds FK constraints via PRAGMA foreign_key_list. Skips FKs that fail
(type mismatch, missing parent column, etc.).

Usage:
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/add_fks_to_existing_schemas.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from sqlalchemy import text

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from bird_paths import resolve_bird_layout
from import_to_pg import extract_sqlite_fks, restore_fks
from data_agent.db_engine import get_engine


def list_pg_tables(engine, schema: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_type='BASE TABLE'"
        ), {"schema": schema}).fetchall()
    return [r[0] for r in rows]


def main() -> int:
    layout = resolve_bird_layout()
    bird_root = layout["dev_databases"]
    engine = get_engine()
    if not engine:
        print("ERROR: get_engine() returned None", file=sys.stderr)
        return 2

    sqlite_dirs = sorted(p for p in bird_root.iterdir() if p.is_dir())
    total_added = 0

    for db_dir in sqlite_dirs:
        db_id = db_dir.name
        schema = f"bird_{db_id}"
        sqlite_file = db_dir / f"{db_id}.sqlite"
        if not sqlite_file.exists():
            print(f"  SKIP {schema}: {sqlite_file} not found")
            continue

        pg_tables = set(list_pg_tables(engine, schema))
        if not pg_tables:
            print(f"  SKIP {schema}: no tables in PG")
            continue

        sqlite_conn = sqlite3.connect(str(sqlite_file))
        schema_added = 0
        try:
            cur = sqlite_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            sqlite_tables = [r[0] for r in cur.fetchall()]
            for table in sqlite_tables:
                pg_tbl = table.lower()
                if pg_tbl not in pg_tables:
                    continue
                fks = extract_sqlite_fks(sqlite_conn, table)
                if not fks:
                    continue
                # Filter FKs whose ref table also exists in PG
                fks = [fk for fk in fks if fk["ref_table"] in pg_tables]
                if not fks:
                    continue
                n = restore_fks(engine, schema, pg_tbl, fks)
                schema_added += n
        finally:
            sqlite_conn.close()

        print(f"  {schema:40s}  +{schema_added} FKs")
        total_added += schema_added

    print(f"\nDone. {total_added} FK constraints added across all schemas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
