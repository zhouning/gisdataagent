"""Qwen Phase 3 smoke probe — 4 qids covering buckets A/B/D.

Same qids as probe_ds_step4.py so we can compare Qwen vs DS directly.
Pass criteria:
  - agent builds, Qwen API returns valid SQL
  - ex >= 2/4 (equivalent DS Phase 1 step 4 was 4/4; we allow some headroom
    for Qwen being a new family)
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

os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)
os.environ["NL2SQL_AGENT_MODEL"] = "qwen3.6-flash"
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "180"

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"

PROBE_QIDS = [
    "CQ_GEO_EASY_12",   # B: COUNT vs listing
    "CQ_GEO_EASY_17",   # B: COUNT DISTINCT
    "CQ_GEO_EASY_09",   # A: projection drift
    "CQ_GEO_EASY_15",   # D: numeric formatting
]


def _load(qids):
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    by = {r["id"]: r for r in rows}
    return [by[q] for q in qids if q in by]


async def main():
    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    from nl2sql_agent import build_nl2sql_agent
    agent = build_nl2sql_agent()
    print(f"[probe] agent class: {type(agent.model).__name__}")
    print(f"[probe] model string: {agent.model.model}")
    print(f"[probe] extra_body: {agent.model._additional_args.get('extra_body')}")
    print(f"[probe] family env: {os.environ.get('NL2SQL_AGENT_FAMILY')}")
    print()

    qs = _load(PROBE_QIDS)
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
        pred = (rec.get("pred_sql") or "<EMPTY>")[:200]
        print(f"Pred: {pred}")
        print(f"=> ex={rec.get('ex')} tokens={rec.get('tokens')} "
              f"dur={dur:.1f}s reason={str(rec.get('reason',''))[:60]}")
        print()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
