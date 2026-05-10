"""Phase 1 Step 6 probe: verify DS grounding template + Step 5 (intent bypass).

CQ_GEO_HARD_08 — "按 fclass + bridge 分组统计" — was failing under Fix 0
because:
  1. Intent LLM judge classified it as 'attribute_filter' (wrong)
  2. The Gemini-shaped grounding prompt then injected long aggregation rule
     blocks that DS over-applied (CASE rewrites, NULL filters, etc.)

After Step 5 (DS bypasses LLM judge → only rule stage runs, which correctly
detects AGGREGATION via "分组" / "GROUP BY") and Step 6 (DS gets compact
grounding without the long aggregation prose), we expect DS to produce a
clean GROUP BY fclass, bridge.

Pass criteria:
  - pred_sql contains GROUP BY ... fclass ... bridge
  - ex=1 (rowset matches gold)

Usage:
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
      .venv/Scripts/python.exe scripts/nl2sql_bench_cq/probe_ds_step6.py
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

os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
os.environ["NL2SQL_AGENT_MODEL"] = "deepseek-v4-flash"
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "180"

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"

PROBE_QIDS = [
    "CQ_GEO_HARD_08",   # B+grounding: GROUP BY misinterpretation under old prompt
    "CQ_GEO_MEDIUM_12", # B: HAVING + GROUP BY misinterpretation
    "CQ_GEO_HARD_03",   # A: projection drift on SUM(area)
    "CQ_GEO_HARD_01",   # A+E: AVG with extra COUNT col, EXISTS vs JOIN
]


def _load(qids):
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows}
    return [by_id[q] for q in qids if q in by_id]


async def main():
    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    from nl2sql_agent import build_nl2sql_agent
    agent = build_nl2sql_agent()
    print(f"[probe] family env = {os.environ.get('NL2SQL_AGENT_FAMILY')}")
    print(f"[probe] model = {type(agent.model).__name__}")
    print(f"[probe] extra_body = {agent.model._additional_args.get('extra_body')}")
    print()

    qs = _load(PROBE_QIDS)
    results = []
    for q in qs:
        print(f"--- {q['id']} ({q['category']}) ---")
        print(f"Q: {q['question'][:120]}")
        print(f"Gold: {q.get('golden_sql','')[:160]}")
        t0 = time.time()
        try:
            rec = await asyncio.wait_for(run_one(q, "full"), timeout=180)
        except asyncio.TimeoutError:
            rec = {"qid": q["id"], "ex": 0, "valid": 0,
                   "pred_sql": "", "tokens": 0, "reason": "timeout"}
        dur = time.time() - t0
        pred = (rec.get("pred_sql") or "<EMPTY>")[:200]
        print(f"Pred: {pred}")
        print(f"=> ex={rec.get('ex')} valid={rec.get('valid')} "
              f"intent={rec.get('intent','')}/{rec.get('intent_source','')} "
              f"tokens={rec.get('tokens')} dur={dur:.1f}s "
              f"reason={str(rec.get('reason',''))[:60]}")
        print()
        results.append({
            "qid": q["id"],
            "category": q["category"],
            "pred_sql": rec.get("pred_sql", ""),
            "ex": rec.get("ex", 0),
            "intent": rec.get("intent", ""),
            "intent_source": rec.get("intent_source", ""),
            "tokens": rec.get("tokens", 0),
            "duration_s": round(dur, 1),
            "reason": rec.get("reason", ""),
        })

    print("=" * 64)
    ok = sum(1 for r in results if r["ex"] == 1)
    print(f"Result: {ok}/{len(results)} passed")
    for r in results:
        print(f"  {r['qid']}: ex={r['ex']} intent={r['intent']}({r['intent_source']}) tokens={r['tokens']}")

    out = ROOT / "data_agent" / "nl2sql_eval_results" / "probe_ds_step6.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nRaw -> {out}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
