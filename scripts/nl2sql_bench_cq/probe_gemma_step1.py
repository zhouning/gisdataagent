"""Gemma Phase 3 smoke probe — same 4 qids as DS/Qwen Step 4 probes."""
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
os.environ["NL2SQL_AGENT_MODEL"] = "gemma-4-31b-it"
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "180"

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
PROBE_QIDS = ["CQ_GEO_EASY_12", "CQ_GEO_EASY_17", "CQ_GEO_EASY_09", "CQ_GEO_EASY_15"]


def _load(qids):
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    by = {r["id"]: r for r in rows}
    return [by[q] for q in qids if q in by]


async def main():
    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    from nl2sql_agent import build_nl2sql_agent
    agent = build_nl2sql_agent()
    print(f"[probe] model class: {type(agent.model).__name__}")
    print(f"[probe] model name: {agent.model.model}")
    print(f"[probe] family env: {os.environ.get('NL2SQL_AGENT_FAMILY')}")
    print()

    for q in _load(PROBE_QIDS):
        print(f"--- {q['id']} ({q['category']}) ---")
        t0 = time.time()
        try:
            rec = await asyncio.wait_for(run_one(q, "full"), timeout=180)
        except asyncio.TimeoutError:
            rec = {"qid": q["id"], "ex": 0, "pred_sql": "", "tokens": 0,
                   "reason": "timeout"}
        dur = time.time() - t0
        pred = (rec.get("pred_sql") or "<EMPTY>")[:200]
        print(f"Gold: {q.get('golden_sql','')[:120]}")
        print(f"Pred: {pred}")
        print(f"=> ex={rec.get('ex')} tokens={rec.get('tokens')} dur={dur:.1f}s "
              f"reason={str(rec.get('reason',''))[:60]}")
        print()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
