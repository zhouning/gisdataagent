"""N=5 thinking on/off A/B test on the full agent loop, same question.

Previous N=1 single-sample test was too noisy (cold-start, cache, network).
This runs thinking-off × 5 interleaved with thinking-on × 5, captures
duration and tokens per run, then prints mean/median/SD.

Gate for proceeding with Fix 0:
  - thinking-off duration mean is meaningfully lower (>= 15% reduction)
  - OR thinking-off tokens mean is meaningfully lower (>= 20% reduction)
  - AND ex=1 rate is not worse

Usage:
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
      .venv/Scripts/python.exe scripts/nl2sql_bench_cq/probe_deepseek_thinking_n5.py
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"


def _pick_questions(n: int, seed: int = 42) -> list[dict]:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    sp = [r for r in rows
          if str(r.get("difficulty", "")).lower() in ("easy", "medium", "hard")]
    rng = random.Random(seed)
    return rng.sample(sp, n)


def _reset_caches():
    for name in list(sys.modules):
        if name.startswith(("run_cq_eval", "nl2sql_agent")):
            del sys.modules[name]


async def run_one(thinking_enabled: bool, question: dict) -> dict:
    _reset_caches()
    os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
    os.environ["NL2SQL_AGENT_MODEL"] = "deepseek-v4-flash"

    from data_agent.model_gateway import ModelRegistry
    ModelRegistry._builtin_models["deepseek-v4-flash"]["thinking_enabled"] = thinking_enabled

    from run_cq_eval import run_one as _run_one, _init_runtime
    _init_runtime()

    t0 = time.time()
    try:
        rec = await asyncio.wait_for(_run_one(question, "full"), timeout=180)
        tm = "ok"
    except asyncio.TimeoutError:
        rec = {"qid": question["id"], "ex": 0, "valid": 0,
               "pred_sql": "", "tokens": 0, "reason": "timeout"}
        tm = "timeout"
    dur = time.time() - t0
    return {
        "thinking": "on" if thinking_enabled else "off",
        "qid": rec.get("qid"),
        "ex": rec.get("ex", 0),
        "tokens": rec.get("tokens", 0),
        "duration_s": round(dur, 1),
        "status": tm,
        "pred_sql_len": len(rec.get("pred_sql") or ""),
    }


async def main():
    N = 5  # per arm
    qs = _pick_questions(N, seed=42)
    print(f"Sampled {N} questions (seed=42):")
    for q in qs:
        print(f"  {q['id']} ({q['difficulty']}): {q['question'][:60]}...")
    print()

    results = []
    # Interleaved: (off, q1), (on, q1), (off, q2), (on, q2), ...
    for i, q in enumerate(qs):
        order = ("off", "on") if i % 2 == 0 else ("on", "off")
        for mode in order:
            print(f"[{i+1}/{N} thinking-{mode}] starting {q['id']}...", flush=True)
            r = await run_one(mode == "on", q)
            print(f"  -> ex={r['ex']} tokens={r['tokens']} dur={r['duration_s']}s "
                  f"status={r['status']}", flush=True)
            results.append(r)

    print()
    print("=" * 72)
    for arm in ("off", "on"):
        rs = [r for r in results if r["thinking"] == arm]
        durs = [r["duration_s"] for r in rs]
        toks = [r["tokens"] for r in rs]
        exs = sum(r["ex"] for r in rs)
        print(f"thinking-{arm} (n={len(rs)}):")
        print(f"  duration: mean={statistics.mean(durs):.1f}s "
              f"median={statistics.median(durs):.1f}s "
              f"min={min(durs):.1f}s max={max(durs):.1f}s "
              f"sd={statistics.stdev(durs):.1f}s")
        print(f"  tokens:   mean={statistics.mean(toks):.0f} "
              f"median={statistics.median(toks):.0f} "
              f"min={min(toks)} max={max(toks)}")
        print(f"  ex:       {exs}/{len(rs)} = {exs/len(rs):.2f}")

    # Also: did thinking-off timeout less?
    timeouts_off = sum(1 for r in results if r["thinking"] == "off" and r["status"] == "timeout")
    timeouts_on = sum(1 for r in results if r["thinking"] == "on" and r["status"] == "timeout")
    print(f"\ntimeouts: off={timeouts_off}  on={timeouts_on}  (timeout=180s)")

    out = ROOT / "data_agent" / "nl2sql_eval_results" / "probe_ds_thinking_n5.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRaw -> {out}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
