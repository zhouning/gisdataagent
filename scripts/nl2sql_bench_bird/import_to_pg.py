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

import sqlite3
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine  # noqa: E402

BIRD_DBS_ROOT = Path(__file__).resolve().parents[2] / "data" / "bird_mini_dev" / \
    "llm" / "mini_dev_data" / "minidev" / "MINIDEV" / "dev_databases"


def list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [r[0] for r in cur.fetchall()]


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
    engine = get_engine()
    if engine is None:
        print("ERROR: get_engine() returned None.", file=sys.stderr)
        return 2

    if not BIRD_DBS_ROOT.exists():
        print(f"ERROR: {BIRD_DBS_ROOT} not found", file=sys.stderr)
        return 2

    sqlite_dirs = [p for p in BIRD_DBS_ROOT.iterdir() if p.is_dir()]
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
