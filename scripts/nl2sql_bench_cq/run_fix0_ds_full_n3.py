"""DeepSeek full × N=3 re-run with thinking disabled (Fix 0 validation).

Reuses run_one_cell from run_cross_family_85q. Only runs the DS full cells; DS
baseline and Gemini cells reuse existing data (baseline doesn't use the agent
loop so thinking flag doesn't apply).

Per-question timeout raised to 240s (was 120s) so that the EMPTY-bucket
contribution from wall-clock truncation is minimised; this lets us see whether
thinking-off actually solves the EX problem as opposed to just shifting where
in the loop we get cut off.

Output: data_agent/nl2sql_eval_results/cross_family_85q_fix0_<ts>/

Usage:
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
      .venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_fix0_ds_full_n3.py
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

# Fix 0: ensure thinking is disabled on DS via the gateway
from data_agent.model_gateway import ModelRegistry
ModelRegistry._builtin_models["deepseek-v4-flash"]["thinking_enabled"] = False

# Allow longer wall-clock per question so the timeout doesn't dominate again
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "240"

from run_cross_family_85q import load_spatial_85q, run_one_cell  # noqa: E402

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


async def main() -> int:
    qs = load_spatial_85q()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"cross_family_85q_fix0_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Fix 0 validation: thinking-off + timeout=240s")
    print(f"[runner] out_dir: {out_dir}")
    print(f"[runner] benchmark: 85q Spatial")

    for i in (1, 2, 3):
        print(f"\n=== DeepSeek full sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_one_cell("deepseek", "full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empties = sum(1 for r in recs if not r.get("pred_sql"))
        print(f"\n[runner] DeepSeek full sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empties}  "
              f"wall={dur_min:.1f}min", flush=True)

    print(f"\n[runner] All 3 DS full samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
