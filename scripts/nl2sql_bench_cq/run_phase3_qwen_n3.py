"""Phase 3: Qwen3.6-Flash × 85q GIS Spatial × N=3 (baseline + full).

Same protocol as Phase 1 DS:
  - baseline: schema-only direct HTTP with no agent loop (cq run_cq_eval
    baseline_generate). N=3 because Qwen is not deterministic at temp=0.
  - full: ADK LlmAgent loop with R1-R7 prompt (copied from DeepSeek's
    system_instruction.md as Phase 3 starting point). Per-family intent
    bypass applied. Compact grounding template applied. Runtime guards
    active. enable_thinking=False.

Output: data_agent/nl2sql_eval_results/cross_family_85q_phase3_qwen_<ts>/

Pass conditions:
  - Qwen full mean EX >= Qwen baseline mean EX + 0.08
  - Paired McNemar (MV) p < 0.10 for within-Qwen
  - Gate evaluation done by stats_cross_family_85q.py after this run completes
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

# Fix 0 carry-over for Qwen: thinking disabled (dashscope uses different
# field name `enable_thinking`, already wired in _create_qwen_model).
# Registry entry toggles it on/off via `thinking_enabled`; default False.

os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "240"

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


def _reset_caches() -> None:
    for name in ("run_cq_eval", "nl2sql_agent", "run_open_source_ablation"):
        if name in sys.modules:
            del sys.modules[name]


async def run_cell(mode: str, qs: list[dict], sample_idx: int,
                   out_dir: Path) -> list[dict]:
    _reset_caches()
    os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    os.environ["NL2SQL_AGENT_MODEL"] = "qwen3.6-flash"

    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    if mode == "full":
        from nl2sql_agent import build_nl2sql_agent
        agent = build_nl2sql_agent()
        assert type(agent.model).__name__ == "LiteLlm", \
            f"Expected LiteLlm, got {type(agent.model).__name__}"
        print(f"  [probe/qwen/full/s{sample_idx}] "
              f"model={type(agent.model).__name__} "
              f"extra_body={agent.model._additional_args.get('extra_body')} "
              f"family={os.environ.get('NL2SQL_AGENT_FAMILY')}", flush=True)

    recs = []
    for i, q in enumerate(qs, 1):
        t0 = datetime.now()
        try:
            rec = await asyncio.wait_for(run_one(q, mode), timeout=300)
        except asyncio.TimeoutError:
            rec = {
                "qid": q.get("id", q.get("question_id", "?")),
                "ex": 0, "valid": 0, "gen_status": "timeout",
                "gen_error": "300s per-question timeout",
            }
        except Exception as e:
            rec = {
                "qid": q.get("id", q.get("question_id", "?")),
                "ex": 0, "valid": 0, "gen_status": "exception",
                "gen_error": str(e)[:300],
            }
        rec["family"] = "qwen"
        rec["mode"] = mode
        rec["sample_idx"] = sample_idx
        recs.append(rec)
        dur = (datetime.now() - t0).total_seconds()
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [qwen/{mode}/s{sample_idx} {i}/{len(qs)}] {m} "
              f"{rec.get('qid')} ex={rec.get('ex')} dur={dur:.1f}s",
              flush=True)
        if i % 10 == 0 or i == len(qs):
            _persist(out_dir, "qwen", mode, sample_idx, recs, len(qs))
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
    out_dir = OUT_ROOT / f"cross_family_85q_phase3_qwen_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Phase 3 Qwen validation: baseline + full × N=3")
    print(f"[runner] out_dir: {out_dir}")

    # Qwen baseline × N=3
    for i in (1, 2, 3):
        print(f"\n=== Qwen baseline sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_cell("baseline", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        print(f"\n[runner] Qwen baseline sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  wall={dur_min:.1f}min",
              flush=True)

    # Qwen full × N=3
    for i in (1, 2, 3):
        print(f"\n=== Qwen full sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_cell("full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(1 for r in recs if "runtime_guard" in str(r.get("gen_error", "")))
        print(f"\n[runner] Qwen full sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empty}  "
              f"GUARDED={guarded}  wall={dur_min:.1f}min", flush=True)

    print(f"\n[runner] All 6 Qwen samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
