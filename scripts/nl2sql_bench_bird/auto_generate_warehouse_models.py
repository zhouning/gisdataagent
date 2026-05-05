"""Auto-generate MetricFlow warehouse models for BIRD schemas.

Walks each BIRD schema in PostgreSQL, infers fact/dimension roles from
FK constraints and column types, and registers semantic models via
SemanticModelStore.

Usage:
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/auto_generate_warehouse_models.py
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/auto_generate_warehouse_models.py --dry-run
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/auto_generate_warehouse_models.py --schema bird_financial
"""
from __future__ import annotations

import argparse
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
from import_to_pg import extract_sqlite_fks
from data_agent.db_engine import get_engine
from data_agent.semantic_model import SemanticModelGenerator, SemanticModelStore
from data_agent.semantic_layer import invalidate_semantic_cache

BIRD_SCHEMAS = [
    "bird_california_schools",
    "bird_card_games",
    "bird_codebase_community",
    "bird_debit_card_specializing",
    "bird_european_football_2",
    "bird_financial",
    "bird_formula_1",
    "bird_student_club",
    "bird_superhero",
    "bird_thrombosis_prediction",
    "bird_toxicology",
]


def list_tables(engine, schema: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ), {"schema": schema}).fetchall()
    return [r[0] for r in rows]


def load_sqlite_fks_for_schema(schema: str) -> dict[str, list[dict]]:
    """Read FKs from BIRD SQLite source. Returns {pg_table_lowercased: [{column, ref_table, ref_column}]}.

    PG tables don't carry FK constraints (the SQLite import didn't create unique
    indexes on referenced columns, so PG would reject ALTER TABLE ... ADD FK).
    Instead we read FKs straight from the SQLite source and pass them to
    `generate_from_table(..., fks=...)` for fact/dimension classification.
    """
    db_id = schema.removeprefix("bird_")
    layout = resolve_bird_layout()
    sqlite_path = layout["dev_databases"] / db_id / f"{db_id}.sqlite"
    if not sqlite_path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        for (name,) in cur.fetchall():
            fks_raw = extract_sqlite_fks(conn, name)
            if not fks_raw:
                continue
            out[name.lower()] = [
                {"column": fk["from_col"], "ref_table": fk["ref_table"], "ref_column": fk["ref_col"]}
                for fk in fks_raw
            ]
    finally:
        conn.close()
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Print YAML without saving")
    p.add_argument("--schema", default=None, help="Process a single schema")
    args = p.parse_args()

    engine = get_engine()
    if not engine:
        print("ERROR: get_engine() returned None", file=sys.stderr)
        return 2

    schemas = [args.schema] if args.schema else BIRD_SCHEMAS
    gen = SemanticModelGenerator()
    store = SemanticModelStore()
    total_models = 0
    total_errors = 0
    total_fks_found = 0

    for schema in schemas:
        tables = list_tables(engine, schema)
        if not tables:
            print(f"[{schema}] No tables found, skipping")
            continue
        fks_by_table = load_sqlite_fks_for_schema(schema)
        n_schema_fks = sum(len(v) for v in fks_by_table.values())
        total_fks_found += n_schema_fks
        print(f"\n[{schema}] {len(tables)} tables, {n_schema_fks} FKs from SQLite")
        for table in tables:
            try:
                fks = fks_by_table.get(table.lower(), [])
                yaml_text = gen.generate_from_table(table, schema=schema, fks=fks)
                name = f"{schema}.{table}"
                if args.dry_run:
                    print(f"  {name} ({len(fks)} FKs):")
                    for line in yaml_text.split("\n")[:8]:
                        print(f"    {line}")
                    if len(yaml_text.split("\n")) > 8:
                        print(f"    ...")
                else:
                    store.save(name, yaml_text, description=f"Auto-generated for {schema}", created_by="auto_gen")
                    print(f"  + {name} ({len(fks)} FKs)")
                total_models += 1
            except Exception as e:
                print(f"  ERROR {schema}.{table}: {e}", file=sys.stderr)
                total_errors += 1

    if not args.dry_run:
        try:
            invalidate_semantic_cache()
        except Exception:
            pass

    print(f"\nDone. {total_models} models {'generated' if args.dry_run else 'registered'}, "
          f"{total_fks_found} FKs found across schemas, {total_errors} errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
