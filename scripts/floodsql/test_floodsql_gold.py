"""Test FloodSQL-Bench gold SQLs run on PostgreSQL/PostGIS.

Reads the first N rows of bechmark_updated.jsonl, executes the gold SQL
against the loaded `floodsql` schema, and compares row count + first
result against the gold output stored in the JSONL.

Critical for catching dialect mismatches (DuckDB → PG) early.

Usage:
    .venv/Scripts/python.exe scripts/floodsql/test_floodsql_gold.py
       [--n 5]              # how many to test (default 5)
       [--level L0]         # filter by level
       [--qid L1_0001]      # test single qid
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from sqlalchemy import text

# Reuse the loader's engine + schema constants
import sys
sys.path.insert(0, str(Path(__file__).parent))
from load_floodsql import get_engine, SCHEMA  # noqa: E402

BENCH_PATH = Path("D:/adk/data/floodsql_bench_repo/benchmark/bechmark_updated.jsonl")


def rewrite_sql_for_pg(sql: str) -> tuple[str, list[str]]:
    """Apply minimal DuckDB → PostgreSQL rewrites.

    Returns (rewritten_sql, list_of_changes_applied).
    """
    changes: list[str] = []

    # 1. STRFTIME('%Y', col) → EXTRACT(YEAR FROM col)::TEXT
    # 1.a STRFTIME('%m', col) → LPAD(EXTRACT(MONTH FROM col)::TEXT, 2, '0')
    def _repl_strftime_year(m):
        changes.append("STRFTIME→EXTRACT(YEAR)")
        return f"EXTRACT(YEAR FROM {m.group(1).strip()})::TEXT"
    sql = re.sub(r"STRFTIME\s*\(\s*'%Y'\s*,\s*([^)]+)\)",
                 _repl_strftime_year, sql, flags=re.IGNORECASE)

    def _repl_strftime_month(m):
        changes.append("STRFTIME→EXTRACT(MONTH)")
        return f"LPAD(EXTRACT(MONTH FROM {m.group(1).strip()})::TEXT, 2, '0')"
    sql = re.sub(r"STRFTIME\s*\(\s*'%m'\s*,\s*([^)]+)\)",
                 _repl_strftime_month, sql, flags=re.IGNORECASE)

    # 1.b CAST(... AS DOUBLE) → CAST(... AS DOUBLE PRECISION). DuckDB accepts
    # bare DOUBLE; PG only accepts DOUBLE PRECISION (or FLOAT8). Negative
    # lookahead so we don't double-rewrite "DOUBLE PRECISION" already correct.
    def _repl_cast_double(m):
        changes.append("CAST DOUBLE→DOUBLE PRECISION")
        return m.group(0)[:-len("DOUBLE")] + "DOUBLE PRECISION"
    sql = re.sub(r"AS\s+DOUBLE\b(?!\s+PRECISION)",
                 _repl_cast_double, sql, flags=re.IGNORECASE)

    # 1.c ST_Point(lon, lat) needs SRID=4326 in PG to match polygon SRID.
    # DuckDB spatial extension returns SRID=0 by default and PG raises
    # "Operation on mixed SRID geometries (Point, 0) != (Polygon, 4326)".
    # Wrap unwrapped ST_Point(...) calls with ST_SetSRID(..., 4326).
    # Skip rewrites that are already wrapped: ST_SetSRID(ST_Point(...), N).
    def _repl_st_point(m):
        # Don't double-wrap if outer call is already ST_SetSRID
        prefix = sql[max(0, m.start()-12):m.start()].upper().rstrip()
        if prefix.endswith("ST_SETSRID("):
            return m.group(0)
        changes.append("ST_Point→SetSRID(...,4326)")
        return f"ST_SetSRID({m.group(0)}, 4326)"
    sql = re.sub(r"ST_Point\s*\([^()]*\)",
                 _repl_st_point, sql, flags=re.IGNORECASE)

    # 2. Schema-qualify all 10 known table names if not already qualified
    tables = ["census_tracts", "county", "floodplain", "zcta", "claims",
              "hospitals", "schools", "svi", "nri", "cre"]
    for t in tables:
        # Match `\bt\b` not preceded by `.`
        pat = re.compile(rf"(?<![\w.]){t}\b", re.IGNORECASE)
        new_sql = pat.sub(f"{SCHEMA}.{t}", sql)
        if new_sql != sql:
            changes.append(f"qualify→{SCHEMA}.{t}")
            sql = new_sql

    return sql, changes


def compare_results(gold_result, pred_rows, rel_tol=1e-3) -> tuple[bool, str]:
    """Compare gold vs pred result. gold_result is list of lists from JSONL."""
    gold = [tuple(r) if isinstance(r, list) else (r,) for r in gold_result]
    pred = [tuple(r) for r in pred_rows]
    if len(gold) != len(pred):
        return False, f"row count: gold={len(gold)} pred={len(pred)}"
    if not gold:
        return True, "both empty"
    if len(gold[0]) != len(pred[0]):
        return False, f"col count: gold={len(gold[0])} pred={len(pred[0])}"

    def norm(v):
        if v is None:
            return ("__NULL__",)
        if isinstance(v, (int,)):
            return ("I", v)
        if isinstance(v, float):
            return ("F", round(v, 3))
        from decimal import Decimal
        if isinstance(v, Decimal):
            return ("F", round(float(v), 3))
        return ("S", str(v))

    if len(gold) == 1 and len(gold[0]) == 1:
        vg, vp = gold[0][0], pred[0][0]
        if vg is None and vp is None:
            return True, "both null"
        from decimal import Decimal
        if isinstance(vg, Decimal):
            vg = float(vg)
        if isinstance(vp, Decimal):
            vp = float(vp)
        if isinstance(vg, (int, float)) and isinstance(vp, (int, float)):
            import math
            if math.isclose(float(vg), float(vp), rel_tol=rel_tol):
                return True, "match (float)"
            return False, f"value: gold={vg} pred={vp}"
        if str(vg) == str(vp):
            return True, "match (str)"
        return False, f"value: gold={vg} pred={vp}"

    gs = sorted(tuple(norm(c) for c in r) for r in gold)
    ps = sorted(tuple(norm(c) for c in r) for r in pred)
    if gs == ps:
        return True, "match"
    return False, "rowset mismatch"


def execute_sql(engine, sql: str, timeout_ms: int = 60_000) -> dict:
    s = sql.strip().rstrip(";").strip()
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            res = conn.execute(text(s))
            rows = res.fetchall()
        return {"status": "ok", "rows": [tuple(r) for r in rows]}
    except Exception as e:
        msg = str(e)
        return {"status": "timeout" if "timeout" in msg.lower() else "error",
                "rows": None, "error": msg[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--level", default=None,
                    help="filter by level (L0,L1,L2,L3,L4,L5)")
    ap.add_argument("--qid", default=None, help="run single qid, e.g. L0_0001")
    ap.add_argument("--timeout-ms", type=int, default=60_000)
    args = ap.parse_args()

    bench = [json.loads(line) for line in BENCH_PATH.read_text(encoding="utf-8").splitlines()
             if line.strip()]

    if args.qid:
        bench = [r for r in bench if r["id"] == args.qid]
    elif args.level:
        bench = [r for r in bench if r["id"].split("_")[0] == args.level]

    bench = bench[: args.n]
    print(f"Testing {len(bench)} questions against {SCHEMA} schema")

    engine = get_engine()
    summary = {"pass": 0, "fail": 0, "error": 0, "timeout": 0}

    for r in bench:
        qid = r["id"]
        gold_sql = r["sql"]
        gold_result = r["result"]
        gold_rc = r.get("row_count", -1)

        new_sql, changes = rewrite_sql_for_pg(gold_sql)
        chg_str = f" [rewrites: {', '.join(changes)}]" if changes else ""
        print(f"\n=== {qid} ===")
        print(f"  Q: {r['question'][:100]}")
        print(f"  gold rc={gold_rc}{chg_str}")

        t0 = time.time()
        res = execute_sql(engine, new_sql, args.timeout_ms)
        elapsed = time.time() - t0

        if res["status"] != "ok":
            print(f"  [FAIL exec] {res['status']} ({elapsed:.1f}s): {res.get('error', '')[:200]}")
            print(f"  SQL: {new_sql[:200]}")
            summary[res["status"]] = summary.get(res["status"], 0) + 1
            continue

        ok, reason = compare_results(gold_result, res["rows"])
        if ok:
            print(f"  [PASS] {reason} ({elapsed:.1f}s, {len(res['rows'])} rows)")
            summary["pass"] += 1
        else:
            print(f"  [FAIL] {reason} ({elapsed:.1f}s)")
            print(f"  gold: {gold_result[:2]}")
            print(f"  pred: {res['rows'][:2]}")
            summary["fail"] += 1

    print(f"\n=== Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
