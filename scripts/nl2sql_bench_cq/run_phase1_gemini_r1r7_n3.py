"""Gemini × DS-R1R7 portability experiment.

Question: Is the DeepSeek R1-R7 imperative system_instruction.md a family-
portable prompt, or is it specifically tuned to DeepSeek's instruction-
following profile? Result determines whether v6 can claim "uniform harness"
or only "factored architecture (knowledge + per-family rendering)".

Method: Run Gemini full × N=3 on the same 85q Spatial benchmark, but force
Gemini to load DeepSeek's prompt namespace (R1-R7 imperative) instead of
its legacy 5-step narrative. Everything else identical to the standard
Phase 1 Gemini run:
  - same temperature (provider default)
  - same intent classifier path (rule + LLM judge — Gemini's legacy)
  - same compact grounding template (we override family to gemini? NO — we
    keep the path consistent with what an actual deployment would use IF
    R1-R7 is adopted as uniform: also switch to the compact grounding template)

Two test arms compared at end:
  arm A (regression baseline): Gemini full N=3 with v5 prompt + legacy
         grounding (run by run_phase1_gemini_full_n3.py — already running)
  arm B (this script):         Gemini full N=3 with DS R1-R7 prompt +
         compact grounding

  - If arm B EX ≈ arm A within sample variance → R1-R7 is portable; we can
    simplify the namespace.
  - If arm B EX < arm A by ≥ 0.05 → R1-R7 is DS-specific; factored
    architecture is correct; documenting the gap is a real contribution.
  - If arm B EX > arm A → drop the legacy gemini prompt entirely.

The experiment uses an env var override `NL2SQL_PROMPT_FAMILY_OVERRIDE` to
force the prompt namespace selection while keeping `family_of()` intact.
This is a deliberate research instrument, not a permanent code path.

Output: data_agent/nl2sql_eval_results/cross_family_85q_phase1_gemini_r1r7_<ts>/
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

# Force the prompt namespace + intent + grounding paths to behave as if this
# were the DeepSeek family — but the actual model is Gemini.
os.environ["NL2SQL_PROMPT_FAMILY_OVERRIDE"] = "deepseek"
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "240"

from run_cross_family_85q import load_spatial_85q, run_one_cell  # noqa: E402

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


async def main() -> int:
    qs = load_spatial_85q()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"cross_family_85q_phase1_gemini_r1r7_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Portability test: Gemini full × N=3 with DS R1-R7 prompt")
    print(f"[runner] NL2SQL_PROMPT_FAMILY_OVERRIDE = "
          f"{os.environ.get('NL2SQL_PROMPT_FAMILY_OVERRIDE')}")
    print(f"[runner] out_dir: {out_dir}")

    for i in (1, 2, 3):
        print(f"\n=== Gemini full sample {i}/3 (R1-R7) "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_one_cell("gemini", "full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(
            1 for r in recs if "runtime_guard" in str(r.get("gen_error", ""))
        )
        print(f"\n[runner] Gemini full sample {i} (R1-R7): {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empty}  "
              f"GUARDED={guarded}  wall={dur_min:.1f}min", flush=True)

    print(f"\n[runner] All 3 Gemini-R1R7 samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
