"""Minimal probe: 1 DeepSeek full-mode question with thinking disabled.

Goal: verify the Fix 0 (thinking={"type":"disabled"}) actually lands at the API
and produces fast/cheap responses. Compares against a control run with thinking
explicitly re-enabled.

Pass criteria:
  - thinking-disabled: wall-clock <= 25s, tokens <= 8000 on a Easy question
  - thinking-enabled control: wall-clock and tokens noticeably higher

Usage:
  cd D:\\adk
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
      .venv/Scripts/python.exe scripts/nl2sql_bench_cq/probe_deepseek_thinking.py
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

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"


def _easy_question() -> dict:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    for r in rows:
        if r.get("id") == "CQ_GEO_EASY_01":
            return r
    raise RuntimeError("CQ_GEO_EASY_01 not found")


def _reset_caches():
    for name in ("run_cq_eval", "nl2sql_agent", "data_agent.model_gateway"):
        if name in sys.modules:
            del sys.modules[name]


async def probe_one(label: str, thinking_enabled: bool, question: dict) -> dict:
    _reset_caches()
    os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
    os.environ["NL2SQL_AGENT_MODEL"] = "deepseek-v4-flash"

    # Override the registry entry's thinking_enabled flag for this probe
    from data_agent.model_gateway import ModelRegistry
    if "deepseek-v4-flash" in ModelRegistry._builtin_models:
        ModelRegistry._builtin_models["deepseek-v4-flash"]["thinking_enabled"] = thinking_enabled

    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    from nl2sql_agent import build_nl2sql_agent
    agent = build_nl2sql_agent()
    print(f"[{label}] model={type(agent.model).__name__} "
          f"extra_body={getattr(agent.model, '_additional_args', {}).get('extra_body')}",
          flush=True)

    t0 = time.time()
    try:
        rec = await asyncio.wait_for(run_one(question, "full"), timeout=240)
    except asyncio.TimeoutError:
        rec = {"qid": question["id"], "ex": 0, "valid": 0,
               "pred_sql": "", "tokens": 0, "reason": "probe-timeout"}
    dur = time.time() - t0

    print(f"[{label}] qid={rec.get('qid')} ex={rec.get('ex')} "
          f"valid={rec.get('valid')} tokens={rec.get('tokens')} "
          f"dur={dur:.1f}s pred_sql_len={len(rec.get('pred_sql') or '')}",
          flush=True)
    return {"label": label, "duration_s": dur, **rec}


async def main():
    q = _easy_question()
    print(f"Probe question: {q['id']}: {q['question'][:80]}...", flush=True)
    print(f"Gold: {q.get('golden_sql','')[:120]}", flush=True)
    print()

    results = []
    # First: thinking DISABLED (the fix we want to validate)
    results.append(await probe_one("THINKING-OFF", thinking_enabled=False, question=q))
    print()
    # Second: thinking ENABLED (control / baseline behavior, matches old runs)
    results.append(await probe_one("THINKING-ON ", thinking_enabled=True, question=q))

    print()
    print("=" * 64)
    print("Summary:")
    for r in results:
        print(f"  {r['label']}: dur={r['duration_s']:.1f}s tokens={r.get('tokens',0)} "
              f"ex={r.get('ex',0)} pred_sql_present={bool(r.get('pred_sql'))}")

    # Save raw
    out = ROOT / "data_agent" / "nl2sql_eval_results" / "probe_deepseek_thinking.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\nResults -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
