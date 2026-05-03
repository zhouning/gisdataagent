"""Import BIRD mini_dev SQLite databases into PostgreSQL.

Each SQLite DB → PG schema named `bird_<db_id>`. Tables are recreated
(if_exists='replace'). All columns ported as text/numeric/integer based
on SQLite affinity.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/import_to_pg.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bird_paths import resolve_bird_layout
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--bird-root", default=None)
    return p


def list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [r[0] for r in cur.fetchall()]


def extract_sqlite_fks(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Extract foreign key relationships from a SQLite table.

    Returns list of dicts: [{from_col, ref_table, ref_col}, ...]
    """
    cur = conn.execute(f'PRAGMA foreign_key_list("{table}")')
    fks = []
    for row in cur.fetchall():
        # PRAGMA foreign_key_list returns: (id, seq, table, from, to, on_update, on_delete, match)
        fks.append({
            "from_col": row[3].lower(),
            "ref_table": row[2].lower(),
            "ref_col": row[4].lower() if row[4] else "id",
        })
    return fks


def restore_fks(engine, schema: str, table: str, fks: list[dict]) -> int:
    """Create FK constraints in PostgreSQL. Returns count of FKs created.

    Each FK is wrapped in its own transaction so a single failure (e.g. type
    mismatch with a parent column) does not abort the entire batch.
    """
    created = 0
    for fk in fks:
        constraint_name = f"fk_{table}_{fk['from_col']}_{fk['ref_table']}"
        try:
            with engine.begin() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.table_constraints "
                    "WHERE constraint_schema = :schema AND constraint_name = :name"
                ), {"schema": schema, "name": constraint_name}).fetchone()
                if exists:
                    continue
                conn.execute(text(
                    f'ALTER TABLE "{schema}"."{table}" '
                    f'ADD CONSTRAINT "{constraint_name}" '
                    f'FOREIGN KEY ("{fk["from_col"]}") '
                    f'REFERENCES "{schema}"."{fk["ref_table"]}" ("{fk["ref_col"]}")'
                ))
                created += 1
        except Exception:
            pass  # Skip on type mismatch, missing ref table, or other constraint errors
    return created


def import_sqlite_db(sqlite_path: Path, schema: str, engine, chunksize: int = 5000) -> dict:
    """Copy all tables from one SQLite file into a PG schema."""
    out = {"schema": schema, "tables": [], "total_rows": 0, "errors": []}

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    try:
        with engine.begin() as pg_conn:
            pg_conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

        for table in list_tables(sqlite_conn):
            try:
                # Read entire table (mini_dev DBs are small enough)
                df = pd.read_sql_query(f'SELECT * FROM "{table}"', sqlite_conn)
                # Lowercase + sanitize column names for PostgreSQL case-insensitive use.
                # BIRD gold SQL uses bare identifiers (e.g. "Currency"), which PG
                # automatically lowercases unless quoted — so making the column
                # actually lowercase makes the gold SQL "just work".
                df.columns = [
                    c.replace("`", "").replace('"', "").lower()
                    for c in df.columns
                ]
                df.to_sql(
                    table.lower(), engine, schema=schema,
                    if_exists="replace", index=False, chunksize=chunksize,
                )
                # Extract and restore foreign keys
                fks = extract_sqlite_fks(sqlite_conn, table)
                if fks:
                    n_fk = restore_fks(engine, schema, table.lower(), fks)
                    if n_fk:
                        print(f"    + {n_fk} FK constraints restored")
                out["tables"].append({"name": table, "rows": len(df)})
                out["total_rows"] += len(df)
                print(f"  {schema}.{table:30s} {len(df):>8,} rows")
            except Exception as e:
                err = f"{table}: {e}"
                out["errors"].append(err)
                print(f"  ERROR {table}: {e}", file=sys.stderr)
    finally:
        sqlite_conn.close()
    return out


def main() -> int:
    p = build_arg_parser()
    args = p.parse_args()

    layout = resolve_bird_layout(args.bird_root)
    bird_dbs_root = layout["dev_databases"]

    engine = get_engine()
    if engine is None:
        print("ERROR: get_engine() returned None.", file=sys.stderr)
        return 2

    if not bird_dbs_root.exists():
        print(f"ERROR: {bird_dbs_root} not found", file=sys.stderr)
        return 2

    sqlite_dirs = [p for p in bird_dbs_root.iterdir() if p.is_dir()]
    print(f"[bird-import] Found {len(sqlite_dirs)} SQLite databases")

    summary: list[dict] = []
    for db_dir in sorted(sqlite_dirs):
        db_id = db_dir.name
        sqlite_file = db_dir / f"{db_id}.sqlite"
        if not sqlite_file.exists():
            print(f"  SKIP {db_id}: {sqlite_file} not found")
            continue
        schema = f"bird_{db_id}"
        size_mb = sqlite_file.stat().st_size / 1e6
        print(f"\n[bird-import] {db_id} ({size_mb:.1f} MB) -> schema {schema}")
        result = import_sqlite_db(sqlite_file, schema, engine)
        summary.append(result)

    print(f"\n[bird-import] Done. {len(summary)} schemas created.")
    for s in summary:
        n_tables = len(s["tables"])
        n_errors = len(s["errors"])
        print(f"  {s['schema']:35s} {n_tables:>3d} tables, {s['total_rows']:>10,} rows, "
              f"{n_errors} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
