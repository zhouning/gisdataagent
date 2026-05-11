"""Phase 3: Gemma-4-31b-it × 85q GIS Spatial × N=3 (baseline + full).

Runs in parallel with Phase 3 Qwen — different API provider (AI Studio vs
dashscope), no resource contention.

Known limitations observed in pre-experiment probe:
  - Gemma has intermittent EMPTY responses (~2/3 iter on a test question
    returned tokens=0). This is NOT a bug in our code — direct full_generate
    confirms Gemma is capable of correct SQL. The intermittent failures
    appear to be Gemma-side (safety filter or function-call parse flake).
    Experiment records these as EMPTY and the overall EX will reflect the
    portability limit.

Output: data_agent/nl2sql_eval_results/cross_family_85q_phase3_gemma_<ts>/
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
    os.environ["NL2SQL_AGENT_MODEL"] = "gemma-4-31b-it"

    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    if mode == "full":
        from nl2sql_agent import build_nl2sql_agent
        agent = build_nl2sql_agent()
        assert type(agent.model).__name__ == "Gemini", \
            f"Expected Gemini class, got {type(agent.model).__name__}"
        print(f"  [probe/gemma/full/s{sample_idx}] "
              f"model={type(agent.model).__name__}  "
              f"model_str={agent.model.model}  "
              f"family={os.environ.get('NL2SQL_AGENT_FAMILY')}  "
              f"VERTEX={os.environ.get('GOOGLE_GENAI_USE_VERTEXAI')}",
              flush=True)

    recs = []
    # Gemma AI Studio paid-tier rate limit: 16K INPUT TOKENS per minute (the
    # error metric is `generate_content_paid_tier_3_input_token_count`). A
    # full-mode query can spend 14-20K INPUT tokens across the agent loop's
    # multiple turns, so a single query may exceed the per-minute limit on
    # its own. Strategy: parse the `retryDelay` field from 429 errors and
    # sleep exactly as the server instructs, then retry the question.
    import re as _re_429

    def _extract_retry_delay(err_msg: str) -> int:
        """Pull retryDelay seconds from 429 error message; return 65s default."""
        if not err_msg:
            return 65
        m = _re_429.search(r"retry[Dd]elay['\":\s]+(\d+)\s*s", err_msg)
        if m:
            return int(m.group(1)) + 5  # +5s safety
        m = _re_429.search(r"[Rr]etry in (\d+(?:\.\d+)?)s", err_msg)
        if m:
            return int(float(m.group(1))) + 5
        return 65  # safe default — slightly over 1 minute window

    for i, q in enumerate(qs, 1):
        t0 = datetime.now()
        rec = None
        # Up to 3 attempts on 429
        for attempt in range(3):
            try:
                rec = await asyncio.wait_for(run_one(q, mode), timeout=300)
                # Detect 429 inside the gen_error / pred_error fields
                err_blob = (
                    str(rec.get("gen_error", "")) + " "
                    + str(rec.get("pred_error", "")) + " "
                    + str(rec.get("reason", ""))
                )
                if "429" in err_blob or "RESOURCE_EXHAUSTED" in err_blob:
                    delay = _extract_retry_delay(err_blob)
                    print(f"  [gemma/{mode}/s{sample_idx} {i}/{len(qs)}] "
                          f"429 (attempt {attempt+1}/3), sleeping {delay}s",
                          flush=True)
                    await asyncio.sleep(delay)
                    continue
                break  # success or non-429 failure
            except asyncio.TimeoutError:
                rec = {"qid": q.get("id","?"), "ex": 0, "valid": 0,
                       "gen_status": "timeout",
                       "gen_error": "300s per-question timeout"}
                break
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    delay = _extract_retry_delay(msg)
                    print(f"  [gemma/{mode}/s{sample_idx} {i}/{len(qs)}] "
                          f"429 exc (attempt {attempt+1}/3), sleeping {delay}s",
                          flush=True)
                    await asyncio.sleep(delay)
                    continue
                rec = {"qid": q.get("id","?"), "ex": 0, "valid": 0,
                       "gen_status": "exception",
                       "gen_error": msg[:300]}
                break
        if rec is None:
            rec = {"qid": q.get("id","?"), "ex": 0, "valid": 0,
                   "gen_status": "exhausted_429",
                   "gen_error": "exceeded 3 retry attempts on 429"}
        rec["family"] = "gemma"
        rec["mode"] = mode
        rec["sample_idx"] = sample_idx
        recs.append(rec)
        dur = (datetime.now() - t0).total_seconds()
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [gemma/{mode}/s{sample_idx} {i}/{len(qs)}] {m} "
              f"{rec.get('qid')} ex={rec.get('ex')} dur={dur:.1f}s",
              flush=True)
        if i % 10 == 0 or i == len(qs):
            _persist(out_dir, "gemma", mode, sample_idx, recs, len(qs))
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
    out_dir = OUT_ROOT / f"cross_family_85q_phase3_gemma_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Phase 3 Gemma validation: baseline + full × N=3")
    print(f"[runner] out_dir: {out_dir}")

    for i in (1, 2, 3):
        print(f"\n=== Gemma baseline sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_cell("baseline", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        print(f"\n[runner] Gemma baseline sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  wall={dur_min:.1f}min",
              flush=True)

    for i in (1, 2, 3):
        print(f"\n=== Gemma full sample {i}/3 "
              f"({datetime.now().strftime('%H:%M:%S')}) ===", flush=True)
        t0 = datetime.now()
        recs = await run_cell("full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(1 for r in recs if "runtime_guard" in str(r.get("gen_error", "")))
        print(f"\n[runner] Gemma full sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empty}  "
              f"GUARDED={guarded}  wall={dur_min:.1f}min", flush=True)

    print(f"\n[runner] All 6 Gemma samples written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
