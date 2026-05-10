"""DeepSeek full × N=3 validation with Phase 1 adapter (system_instruction R1-R7
+ compact grounding + family-aware intent + runtime guards).

Fix 0 already provided thinking-off + timeout=240s. Phase 1 stacks on top:
  - DS system_instruction.md (R1-R7 strict rules)
  - Compact grounding prompt (family='deepseek' path in _format_grounding_prompt)
  - Intent classifier bypasses LLM judge on DS (rule-stage only)
  - runtime_guards.is_safe_sql post-hoc check before execution

DS baseline is reused from the Fix 0 run (no agent-loop code touched it).

Output: data_agent/nl2sql_eval_results/cross_family_85q_phase1_<ts>/

Usage:
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
      .venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_phase1_ds_full_n3.py
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

# Fix 0 carry-over: thinking disabled on DS via model_gateway
from data_agent.model_gateway import ModelRegistry
ModelRegistry._builtin_models["deepseek-v4-flash"]["thinking_enabled"] = False

# Allow more wall-clock per question so timeouts stop dominating
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "240"

from run_cross_family_85q import load_spatial_85q, run_one_cell  # noqa: E402

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


async def main() -> int:
    qs = load_spatial_85q()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"cross_family_85q_phase1_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Phase 1 validation: DS prompt adapter + guards")
    print(f"[runner] out_dir: {out_dir}")
    print(f"[runner] benchmark: 85q GIS Spatial")

    for i in (1, 2, 3):
        print(f"\n=== DeepSeek full sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_one_cell("deepseek", "full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(1 for r in recs if "runtime_guard" in str(r.get("gen_error", "")))
        print(f"\n[runner] DeepSeek full sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empty}  "
              f"GUARDED={guarded}  wall={dur_min:.1f}min", flush=True)

    print(f"\n[runner] All 3 DS full samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
