"""Gemini full × N=3 regression check for Phase 1.

After Phase 1 adds family-aware prompt namespace + compact grounding + intent
bypass + runtime guards, we need to confirm Gemini's numbers haven't moved:

  - system_instruction.md for gemini/ was verified byte-equivalent to the old
    hardcoded instruction (Step 3).
  - family-aware classify_intent: when family='gemini' the legacy path (rule +
    LLM judge) runs exactly as before.
  - _format_grounding_prompt: when family='gemini' or None the legacy
    rendering runs; compact path is only taken when family in {deepseek, qwen}.
  - runtime_guards: new code, runs on ALL families but legitimate Gemini SQL
    should never trigger give_up or hallucinated_table guards.

Gate to pass: Gemini within-family Δ EX ≥ +0.10, paired McNemar p ≤ 0.10
(historical v5: Δ +0.129, p=0.052). A statistically indistinguishable result
counts as pass.

Output: data_agent/nl2sql_eval_results/cross_family_85q_phase1_gemini_<ts>/
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

# Allow longer wall-clock to match the DS phase 1 runs (Gemini is faster than
# DS but we keep the same 240s cap for protocol symmetry).
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "240"

from run_cross_family_85q import load_spatial_85q, run_one_cell  # noqa: E402

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


async def main() -> int:
    qs = load_spatial_85q()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"cross_family_85q_phase1_gemini_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Phase 1 regression: Gemini full × N=3")
    print(f"[runner] out_dir: {out_dir}")
    print(f"[runner] benchmark: 85q GIS Spatial")

    for i in (1, 2, 3):
        print(f"\n=== Gemini full sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_one_cell("gemini", "full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(
            1 for r in recs if "runtime_guard" in str(r.get("gen_error", ""))
        )
        print(f"\n[runner] Gemini full sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empty}  "
              f"GUARDED={guarded}  wall={dur_min:.1f}min", flush=True)

    print(f"\n[runner] All 3 Gemini full samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
