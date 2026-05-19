"""Seed FloodSQL-Bench few-shot examples into reference_queries store.

Selects the last 3 questions from each of L0–L5 (18 total) as held-out
in-context examples. The eval-time question set (Phase 0e onwards) MUST
skip these qids to avoid train-test leakage.

Usage:
    cd D:/adk
    .venv/Scripts/python.exe scripts/nl2sql_bench_floodsql/seed_few_shots.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from collections import defaultdict

from data_agent.reference_queries import ReferenceQueryStore

BENCH_PATH = Path("D:/adk/data/floodsql_bench_repo/benchmark/bechmark_updated.jsonl")
FEW_SHOT_TAG = "floodsql_bench_few_shot"
N_PER_LEVEL = 3


def get_few_shot_qids() -> set[str]:
    """Return the qids reserved as few-shot (last N_PER_LEVEL per level)."""
    bench = [json.loads(l) for l in BENCH_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_lv = defaultdict(list)
    for r in bench:
        by_lv[r["id"].split("_")[0]].append(r)
    qids = set()
    for lv in sorted(by_lv):
        for r in by_lv[lv][-N_PER_LEVEL:]:
            qids.add(r["id"])
    return qids


def main() -> int:
    bench = [json.loads(l) for l in BENCH_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_lv = defaultdict(list)
    for r in bench:
        by_lv[r["id"].split("_")[0]].append(r)

    # SQL Rewrite for PG dialect (same as test_floodsql_gold)
    import re
    SCHEMA = "floodsql"
    TABLES = ["census_tracts", "county", "floodplain", "zcta", "claims",
              "hospitals", "schools", "svi", "nri", "cre"]

    def rewrite(sql: str) -> str:
        sql = re.sub(r"STRFTIME\s*\(\s*'%Y'\s*,\s*([^)]+)\)",
                     lambda m: f"EXTRACT(YEAR FROM {m.group(1).strip()})::TEXT",
                     sql, flags=re.IGNORECASE)
        sql = re.sub(r"AS\s+DOUBLE\b(?!\s+PRECISION)", "AS DOUBLE PRECISION",
                     sql, flags=re.IGNORECASE)
        sql = re.sub(r"ST_Point\s*\([^()]*\)",
                     lambda m: m.group(0) if m.string[max(0, m.start()-12):m.start()].upper().rstrip().endswith("ST_SETSRID(")
                                else f"ST_SetSRID({m.group(0)}, 4326)",
                     sql, flags=re.IGNORECASE)
        for t in TABLES:
            pat = re.compile(rf"(?<![\w.]){t}\b", re.IGNORECASE)
            sql = pat.sub(f"{SCHEMA}.{t}", sql)
        return sql

    store = ReferenceQueryStore()
    written = 0
    skipped = 0
    for lv in sorted(by_lv):
        for r in by_lv[lv][-N_PER_LEVEL:]:
            qid = r["id"]
            question = r["question"]
            gold_sql = rewrite(r["sql"])
            try:
                ref_id = store.add(
                    query_text=question,
                    description=f"FloodSQL-Bench {qid} ({lv} difficulty)",
                    response_summary=gold_sql,
                    tags=[FEW_SHOT_TAG, lv, "floodsql_bench"],
                    task_type="nl2sql",
                    source="floodsql_bench",
                    created_by="floodsql_seed",
                )
                if ref_id is None:
                    print(f"  [skip-dup] {qid}")
                    skipped += 1
                else:
                    print(f"  [ok] {qid} → ref_id={ref_id}")
                    written += 1
            except Exception as e:
                print(f"  [ERR] {qid}: {type(e).__name__}: {e}")
                skipped += 1

    print(f"\nFloodSQL few-shot seed done: written={written}, skipped/dup={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
