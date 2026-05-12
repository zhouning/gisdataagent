"""Gemma Ollama Stage 3 — full ADK agent loop on 4 NL2SQL questions.

Same 4 qids as probe_qwen_step1.py / probe_ds_step4.py, so cross-family
comparison is direct: A (projection drift), B x2 (COUNT variants), D
(numeric formatting).

Pass criteria:
  - agent builds without error against gemma-4-31b-it-ollama
  - end-to-end loop completes for all 4 questions within 5min each
  - at least 2/4 ex=1 (Qwen probe baseline was 4/4; we allow headroom for
    a brand-new local backend)
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

# Reset family-related env so this probe stands alone.
os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)
os.environ["NL2SQL_AGENT_MODEL"] = "gemma-4-31b-it-ollama"
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "300"

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
    print(f"[probe] family env: {os.environ.get('NL2SQL_AGENT_FAMILY')}")
    print(f"[probe] OLLAMA_API_BASE: {os.environ.get('OLLAMA_API_BASE')}")
    print()

    qs = _load(PROBE_QIDS)
    results = []
    for q in qs:
        print(f"--- {q['id']} ({q.get('category','?')}) ---")
        print(f"Q: {q['question'][:100]}")
        print(f"Gold: {q.get('golden_sql','')[:120]}")
        t0 = time.time()
        try:
            rec = await asyncio.wait_for(run_one(q, "full"), timeout=300)
        except asyncio.TimeoutError:
            rec = {"qid": q["id"], "ex": 0, "valid": 0,
                   "pred_sql": "", "tokens": 0, "reason": "timeout"}
        dur = time.time() - t0
        pred = (rec.get("pred_sql") or "<EMPTY>")[:200]
        print(f"Pred: {pred}")
        print(f"=> ex={rec.get('ex')} valid={rec.get('valid')} "
              f"tokens={rec.get('tokens')} dur={dur:.1f}s "
              f"reason={str(rec.get('reason',''))[:60]}")
        print()
        results.append(rec)

    ex_count = sum(1 for r in results if r.get("ex"))
    valid_count = sum(1 for r in results if r.get("valid"))
    print(f"[probe summary] ex={ex_count}/{len(results)} "
          f"valid={valid_count}/{len(results)}")
    print(f"[probe gate] {'PASS' if ex_count >= 2 else 'FAIL'} "
          f"(need >= 2/4 ex)")
    return 0 if ex_count >= 2 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
