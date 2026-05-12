"""v7 PATCH DRAFT — dump_schema_11tables() for all cq_* tables.

**STATUS**: DRAFT — DO NOT IMPORT OR USE UNTIL v6 Phase 3 Gemma N=3 IS COMPLETE.

Current state of `scripts/nl2sql_bench_cq/run_cq_eval.py:77`:

    def dump_schema() -> str:
        ...
        tables = ["cq_amap_poi_2024", "cq_buildings_2021",
                  "cq_land_use_dltb", "cq_osm_roads_2021"]
        ...

This hard-codes 4 tables into the baseline/full prompt. The 7 other
benchmark tables (cq_dltb, cq_osm_roads, cq_historic_districts,
cq_baidu_aoi_2024, cq_baidu_search_index_2023, cq_district_population,
cq_unicom_commuting_2023) are not represented in the prompt schema.

This draft replaces the hard-coded list with an auto-discovery query that
dumps EVERY cq_* table present in the benchmark's golden SQL. It is kept
as a separate file until v6's Phase 3 Gemma N=3 run completes, to avoid
perturbing s3 relative to s1/s2.

Migration plan (executed after v6 close-out):
  1. Replace run_cq_eval.py:77-97 body with `dump_schema_from_benchmark()`
     below, or simply expand the hard-coded list to all 11 tables.
  2. Snapshot one Gemini baseline on the new schema to confirm the 11-table
     prompt still fits in context (Gemini 2.5 Flash has 2M context window,
     so this is a formality, but the sanity check matters).
  3. The new baseline is "schema-full baseline"; the v6 baseline is
     "schema-partial baseline". Both are archived separately.

Delta analysis (what is expected to change):

  - 22/85 questions (26%, "all-target-tables-missing" bucket) will newly
    have their target tables visible to the LLM. Expected baseline uplift:
    +5 to +10 questions on this bucket.
  - 14/85 questions (16%, "some tables in, some missing") will get a full
    schema. Expected baseline uplift: +2 to +4.
  - 49/85 questions (58%, already covered) — no change.

  Total baseline delta estimate: +7 to +14 of 85 questions, i.e. baseline
  rises from 0.529 to 0.61-0.69. Grounding Δ will compress correspondingly.

The v7 cycle will then decompose the harness's contribution into two
independent sources:
  (a) schema-linking uplift (baseline-partial → baseline-full) — now
      measurable by comparing v6 baseline (0.529) vs v7 schema-full baseline.
  (b) residual grounding uplift (baseline-full → full-pipeline full) — now
      measurable by comparing v7 schema-full baseline vs v7 full.

Implementation proposed below. Keep as DRAFT until Gemma N=3 lands.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Discovery approach 1: derive table list from benchmark's golden SQL. This
# is the most conservative choice — we inject exactly the tables that
# questions reference, no more. It avoids dumping grid_l2/l3/l4 helper
# tables that are present in the database but not part of the benchmark.


def _benchmark_tables() -> list[str]:
    """Return sorted list of cq_* table names referenced in the benchmark's
    golden SQL statements. Excludes tables that only appear in Robustness
    'trap' questions (gold_sql=None)."""
    p = Path(__file__).resolve().parents[2] / "benchmarks" / \
        "chongqing_geo_nl2sql_100_benchmark.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    tables = set()
    for r in rows:
        g = r.get("golden_sql") or ""
        for t in re.findall(r"\b(cq_[a-z0-9_]+)\b", g):
            tables.add(t)
    return sorted(tables)


# Discovery approach 2: auto-discover from the live DB catalog. This is
# the cleanest deployment option — whatever cq_* tables exist in the
# public schema will be dumped. Excludes kanon/grid helper tables if their
# naming convention is consistent (e.g. trailing _kanon, _grid_l[234]).

_HELPER_TABLE_RE = re.compile(r"_(kanon|grid_l[2-4])(?:_\w+)?$")


def _db_tables() -> list[str]:
    """Return sorted list of cq_* tables in the live public schema,
    excluding known helper tables (grid_l2/l3/l4, kanon)."""
    from sqlalchemy import text
    from data_agent.db_engine import get_engine
    eng = get_engine()
    with eng.connect() as c:
        r = c.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name LIKE 'cq_%' "
            "ORDER BY table_name"
        ))
        out = [row[0] for row in r]
    return [t for t in out if not _HELPER_TABLE_RE.search(t)]


def dump_schema_11tables(source: str = "benchmark") -> str:
    """Drop-in replacement for run_cq_eval.dump_schema().

    source='benchmark' — tables from benchmark gold SQL (11 tables)
    source='db'        — tables from live DB catalog (may include more)
    """
    from sqlalchemy import text
    from data_agent.db_engine import get_engine

    if source == "benchmark":
        tables = _benchmark_tables()
    elif source == "db":
        tables = _db_tables()
    else:
        raise ValueError(f"unknown source: {source}")

    lines: list[str] = []
    eng = get_engine()
    with eng.connect() as conn:
        for t in tables:
            cols = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t "
                "ORDER BY ordinal_position"
            ), {"t": t}).fetchall()
            if not cols:
                continue  # table in benchmark gold SQL but not in DB
            geom = conn.execute(text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema='public' AND f_table_name=:t LIMIT 1"
            ), {"t": t}).fetchone()
            suffix = f"  -- geom={geom[0]}, srid={geom[1]}" if geom else ""
            lines.append(f'CREATE TABLE public.{t} ({suffix}')
            for c in cols:
                lines.append(f'  "{c[0]}" {c[1]},')
            lines.append(");\n")
    return "\n".join(lines)


def preview() -> None:
    """Dry-run — show what the new schema block looks like and measure size
    relative to the current 4-table schema."""
    new = dump_schema_11tables()
    print(f"=== dump_schema_11tables preview ===")
    print(f"char length: {len(new):,}")
    print(f"line count: {new.count(chr(10))}")
    print(f"table count (CREATE TABLE lines): {new.count('CREATE TABLE')}")
    print()
    # Peek at the first 50 lines
    print("=== first 50 lines ===")
    for line in new.splitlines()[:50]:
        print(line)


if __name__ == "__main__":
    preview()
