"""Regression: the 8 OOM Prevention questions must now produce non-empty SQL
containing LIMIT, after the Task 6 agent prompt fix.

Usage:
    $env:PYTHONPATH="D:\\adk"
    .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/test_oom_regression.py
"""
import asyncio, json, os, sys
from pathlib import Path

sys.path.insert(0, "D:/adk")
sys.path.insert(0, str(Path("D:/adk/scripts/nl2sql_bench_cq")))

os.environ.setdefault("EXPLAIN_LIMIT_THRESHOLD", "10000")

from run_cq_eval import run_one, _init_runtime  # noqa: E402

BENCHMARK = Path("D:/adk/benchmarks/chongqing_geo_nl2sql_100_benchmark.json")

async def main():
    _init_runtime()
    qs = [q for q in json.loads(BENCHMARK.read_text(encoding="utf-8"))
          if q.get("category") == "OOM Prevention"]
    print(f"Running {len(qs)} OOM regressions")
    passed = 0
    for i, q in enumerate(qs, 1):
        rec = await run_one(q, mode="full")
        sql = rec.get("pred_sql") or ""
        non_empty = bool(sql.strip())
        has_limit = "LIMIT" in sql.upper()
        ok = non_empty and has_limit
        passed += int(ok)
        print(f"[{i}/{len(qs)}] {'PASS' if ok else 'FAIL'} {q['id']} "
              f"non_empty={non_empty} has_limit={has_limit} "
              f"sql={sql[:90]}")
    print(f"\n{passed}/{len(qs)} OOM regressions pass (pre-fix baseline: 1/8)")
    if passed < 7:
        raise SystemExit(f"Target >=7/8 not met: {passed}/8")

if __name__ == "__main__":
    asyncio.run(main())
