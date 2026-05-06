"""Verify OOM Prevention fix: re-run just the 8 OOM questions in full mode."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "D:/adk")
sys.path.insert(0, str(Path("D:/adk/scripts/nl2sql_bench_cq")))

from run_cq_eval import run_one, _init_runtime

BENCHMARK = Path("D:/adk/benchmarks/chongqing_geo_nl2sql_100_benchmark.json")
all_questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
oom_questions = [q for q in all_questions if q.get("target_metric") == "AST Validation (Must contain LIMIT)"]
print(f"Found {len(oom_questions)} OOM questions")

async def main():
    _init_runtime()
    results = []
    for i, q in enumerate(oom_questions, 1):
        rec = await run_one(q, mode="full")
        pred = rec.get("pred_sql", "")
        has_limit = "LIMIT" in pred.upper()
        passed = rec.get("ex") == 1
        status = "PASS" if passed else "FAIL"
        print(f"[{i}/{len(oom_questions)}] {status} {q['id']}: has_limit={has_limit}")
        print(f"    pred_sql: {pred[:200]}")
        print(f"    reason: {rec.get('reason','')}")
        results.append(rec)

    passed_n = sum(1 for r in results if r.get("ex"))
    print(f"\n{passed_n}/{len(results)} OOM questions pass (was 0/8 before fix)")

asyncio.run(main())
