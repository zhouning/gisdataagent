"""Phase 1 Step 4 probe: verify DS R2 rule fixes CQ_GEO_EASY_12 COUNT case.

This qid in the Fix 0 run had DS returning SELECT * with 3428 rows instead of
the COUNT(*) gold. Under the new DS system_instruction.md with R2 explicit
COUNT rule, we expect SELECT COUNT(*) instead.

Pass criteria:
  - pred_sql contains "COUNT(*)" or "COUNT( * )"
  - ex=1 (rowset matches gold scalar result)

Usage:
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
      .venv/Scripts/python.exe scripts/nl2sql_bench_cq/probe_ds_step4.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

# Force DS + thinking-off (Fix 0 is still in place from earlier step)
os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
os.environ["NL2SQL_AGENT_MODEL"] = "deepseek-v4-flash"
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "180"

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"

# Probe qids — each was WRONG in Fix 0 run due to specific buckets.
PROBE_QIDS = [
    "CQ_GEO_EASY_12",   # B: intent over-interpret — COUNT → SELECT * listing
    "CQ_GEO_EASY_17",   # B: COUNT DISTINCT → SELECT DISTINCT listing
    "CQ_GEO_EASY_09",   # A: projection drift — multi-col SELECT
    "CQ_GEO_EASY_15",   # D: numeric formatting — ROUND(AVG,2) wrapping
]


def _load_qids(qids: list[str]) -> list[dict]:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows}
    return [by_id[q] for q in qids if q in by_id]


async def main():
    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    from nl2sql_agent import build_nl2sql_agent
    agent = build_nl2sql_agent()
    print(f"[probe] agent.model = {type(agent.model).__name__}")
    print(f"[probe] extra_body = {agent.model._additional_args.get('extra_body')}")
    print(f"[probe] instruction starts with: {agent.instruction[:80]!r}")
    print(f"[probe] R1..R7 markers present: "
          f"{'R1.' in agent.instruction and 'R7.' in agent.instruction}")
    print()

    qs = _load_qids(PROBE_QIDS)
    results = []
    for q in qs:
        print(f"--- {q['id']} ({q['category']}) ---")
        print(f"Q: {q['question'][:100]}")
        print(f"Gold: {q.get('golden_sql','')[:120]}")
        t0 = time.time()
        try:
            rec = await asyncio.wait_for(run_one(q, "full"), timeout=180)
        except asyncio.TimeoutError:
            rec = {"qid": q["id"], "ex": 0, "valid": 0,
                   "pred_sql": "", "tokens": 0, "reason": "timeout"}
        dur = time.time() - t0
        pred = (rec.get("pred_sql") or "<EMPTY>")[:180]
        print(f"Pred: {pred}")
        print(f"=> ex={rec.get('ex')} valid={rec.get('valid')} "
              f"tokens={rec.get('tokens')} dur={dur:.1f}s reason={rec.get('reason','')[:60]}")
        print()
        results.append({
            "qid": q["id"],
            "category": q["category"],
            "pred_sql": rec.get("pred_sql", ""),
            "ex": rec.get("ex", 0),
            "tokens": rec.get("tokens", 0),
            "duration_s": round(dur, 1),
            "reason": rec.get("reason", ""),
        })

    # Summary heuristics
    print("=" * 64)
    for r in results:
        pred = r["pred_sql"].upper().replace(" ", "")
        has_count_star = "COUNT(*)" in pred or "COUNT(*)" in r["pred_sql"].upper()
        has_select_star = "SELECT*FROM" in pred or "SELECT*" in pred[:20]
        print(f"  {r['qid']}: ex={r['ex']} "
              f"COUNT(*)_present={has_count_star} "
              f"SELECT*_present={has_select_star}")

    # Save raw
    out = ROOT / "data_agent" / "nl2sql_eval_results" / "probe_ds_step4.json"
    out.parent.mkdir(exist_ok=True, parents=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\nRaw -> {out}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
