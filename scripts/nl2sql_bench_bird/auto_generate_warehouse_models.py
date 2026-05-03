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
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine
from data_agent.semantic_model import SemanticModelGenerator, SemanticModelStore
from data_agent.semantic_layer import invalidate_semantic_cache

BIRD_SCHEMAS = [
    "bird_california_schools",
    "bird_card_games",
    "bird_codebase_community",
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

    for schema in schemas:
        tables = list_tables(engine, schema)
        if not tables:
            print(f"[{schema}] No tables found, skipping")
            continue
        print(f"\n[{schema}] {len(tables)} tables")
        for table in tables:
            try:
                yaml_text = gen.generate_from_table(table, schema=schema)
                name = f"{schema}.{table}"
                if args.dry_run:
                    print(f"  {name}:")
                    for line in yaml_text.split("\n")[:10]:
                        print(f"    {line}")
                    print(f"    ...")
                else:
                    store.save(name, yaml_text, description=f"Auto-generated for {schema}", created_by="auto_gen")
                    print(f"  + {name}")
                total_models += 1
            except Exception as e:
                print(f"  ERROR {schema}.{table}: {e}", file=sys.stderr)
                total_errors += 1

    if not args.dry_run:
        try:
            invalidate_semantic_cache()
        except Exception:
            pass

    print(f"\nDone. {total_models} models {'generated' if args.dry_run else 'registered'}, {total_errors} errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
