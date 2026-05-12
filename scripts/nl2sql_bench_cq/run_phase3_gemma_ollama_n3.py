"""Phase 3: Gemma 4 31B via Ollama × 85q GIS Spatial × N=3 (baseline + full).

v6 Phase 3 retry path. The original AI-Studio variant of this script (commit
6546e81) hit a 16K input-TPM ceiling that made the agent loop impractical;
this rewrite points at the user's local Ollama deployment instead. Network +
TPM ceilings disappear; the trade-off is per-question latency
(measured ~20-100s for full mode on 31B-Q4 over LAN — vs 5-30s for hosted
APIs). Total wall-clock budgeted ~8h.

Differences vs run_phase3_gemma_n3.py (AI Studio variant):
  - NL2SQL_AGENT_MODEL = "gemma-4-31b-it-ollama" (new registry entry)
  - Agent model class is LiteLlm (NOT Gemini); family_of() still returns
    "gemma" because model_str matches.
  - 429 retry loop removed; Ollama has no per-minute quota.
  - per-question timeout raised to 360s (slowest probe question was 105s).

Output: data_agent/nl2sql_eval_results/cross_family_85q_phase3_gemma_ollama_<ts>/
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

os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "360"

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


def _reset_caches() -> None:
    for name in ("run_cq_eval", "nl2sql_agent", "run_open_source_ablation"):
        if name in sys.modules:
            del sys.modules[name]


async def run_cell(mode: str, qs: list[dict], sample_idx: int,
                   out_dir: Path) -> list[dict]:
    _reset_caches()
    os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)
    os.environ["NL2SQL_AGENT_MODEL"] = "gemma-4-31b-it-ollama"

    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    if mode == "full":
        from nl2sql_agent import build_nl2sql_agent
        agent = build_nl2sql_agent()
        assert type(agent.model).__name__ == "LiteLlm", \
            f"Expected LiteLlm class, got {type(agent.model).__name__}"
        print(f"  [probe/gemma-ollama/full/s{sample_idx}] "
              f"model={type(agent.model).__name__}  "
              f"model_str={agent.model.model}  "
              f"family={os.environ.get('NL2SQL_AGENT_FAMILY')}  "
              f"OLLAMA_API_BASE={os.environ.get('OLLAMA_API_BASE')}",
              flush=True)

    recs = []
    for i, q in enumerate(qs, 1):
        t0 = datetime.now()
        try:
            rec = await asyncio.wait_for(run_one(q, mode), timeout=400)
        except asyncio.TimeoutError:
            rec = {"qid": q.get("id", "?"), "ex": 0, "valid": 0,
                   "gen_status": "timeout",
                   "gen_error": "400s per-question timeout"}
        except Exception as e:
            rec = {"qid": q.get("id", "?"), "ex": 0, "valid": 0,
                   "gen_status": "exception",
                   "gen_error": str(e)[:300]}
        rec["family"] = "gemma_ollama"
        rec["mode"] = mode
        rec["sample_idx"] = sample_idx
        recs.append(rec)
        dur = (datetime.now() - t0).total_seconds()
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [gemma-ollama/{mode}/s{sample_idx} {i}/{len(qs)}] {m} "
              f"{rec.get('qid')} ex={rec.get('ex')} dur={dur:.1f}s",
              flush=True)
        if i % 10 == 0 or i == len(qs):
            _persist(out_dir, "gemma_ollama", mode, sample_idx, recs, len(qs))
    return recs


def _persist(out_dir: Path, family: str, mode: str, sample_idx: int,
             recs: list[dict], n_total: int) -> None:
    ex_count = sum(1 for r in recs if r.get("ex"))
    out_path = out_dir / f"{family}_{mode}_s{sample_idx}_results.json"
    out_path.write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "family": family, "mode": mode, "sample_idx": sample_idx,
            "benchmark": "benchmarks/chongqing_geo_nl2sql_100_benchmark.json",
            "n_questions": n_total,
            "n_completed": len(recs),
            "ex": round(ex_count / max(1, len(recs)), 4),
            "records": recs,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


async def main() -> int:
    from run_cross_family_85q import load_spatial_85q
    qs = load_spatial_85q()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"cross_family_85q_phase3_gemma_ollama_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Phase 3 Gemma-Ollama validation: baseline + full × N=3")
    print(f"[runner] out_dir: {out_dir}")
    print(f"[runner] N questions: {len(qs)}")

    for i in (1, 2, 3):
        print(f"\n=== Gemma-Ollama baseline sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_cell("baseline", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        print(f"\n[runner] Gemma-Ollama baseline sample {i}: "
              f"{ex_count}/{len(recs)} EX={ex_count/max(1,len(recs)):.4f}  "
              f"wall={dur_min:.1f}min", flush=True)

    for i in (1, 2, 3):
        print(f"\n=== Gemma-Ollama full sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_cell("full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(1 for r in recs
                      if "runtime_guard" in str(r.get("gen_error", "")))
        print(f"\n[runner] Gemma-Ollama full sample {i}: "
              f"{ex_count}/{len(recs)} EX={ex_count/max(1,len(recs)):.4f}  "
              f"EMPTY={empty}  GUARDED={guarded}  wall={dur_min:.1f}min",
              flush=True)

    print(f"\n[runner] All 6 Gemma-Ollama samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
