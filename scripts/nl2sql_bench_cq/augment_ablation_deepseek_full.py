"""Augment the baseline-only cross-family ablation with a DeepSeek-full run.

The existing report at data_agent/nl2sql_eval_results/open_source_ablation_2026-05-09_171426/
holds Gemini baseline/full and DeepSeek baseline. This script adds the missing
DeepSeek full run on the same 30q, so we get a true 4-cell cross-family factorial.

The original runner defaulted to ADK's LlmAgent with a bare Gemini model string;
this was fixed in nl2sql_agent.py:64 to route through model_gateway.create_model(),
which wraps DeepSeek via google.adk.models.lite_llm.LiteLlm. The fix makes this
augmentation possible.

Usage:
  cd D:\\adk
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
    .venv/Scripts/python.exe scripts/nl2sql_bench_cq/augment_ablation_deepseek_full.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

BENCH = ROOT / "benchmarks" / "gis_spatial_30q_subset.json"
EXISTING_DIR = ROOT / "data_agent" / "nl2sql_eval_results" / "open_source_ablation_2026-05-09_171426"


def mcnemar_exact_two_sided(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p_one = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_one)


def ex_by_qid(recs):
    return {r["qid"]: (1 if r.get("ex") else 0) for r in recs}


def paired(a_ex, b_ex, label_a, label_b):
    qids = sorted(a_ex.keys() & b_ex.keys())
    fp = fn = 0
    for q in qids:
        pa, pb = a_ex[q], b_ex[q]
        if pa and not pb:
            fp += 1
        elif not pa and pb:
            fn += 1
    p = mcnemar_exact_two_sided(fp, fn)
    return {
        "n": len(qids), "label_a": label_a, "label_b": label_b,
        "ex_a": round(sum(a_ex[q] for q in qids) / max(1, len(qids)), 4),
        "ex_b": round(sum(b_ex[q] for q in qids) / max(1, len(qids)), 4),
        "discordant_a1b0": fp, "discordant_a0b1": fn,
        "mcnemar_p_two_sided_exact": round(p, 4),
    }


async def run_deepseek_full(qs: list[dict]) -> list[dict]:
    """Run DeepSeek full-mode across qs, using the v5-fixed nl2sql_agent.

    Forces model_gateway to pick DeepSeek via NL2SQL_AGENT_MODEL, and forces
    generate_text retries to DeepSeek via NL2SQL_FORCE_DEEPSEEK.
    """
    os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
    os.environ["NL2SQL_AGENT_MODEL"] = "deepseek-v4-flash"

    # Re-import run_cq_eval fresh so it rebuilds the agent with the new env
    import importlib
    if "run_cq_eval" in sys.modules:
        importlib.reload(sys.modules["run_cq_eval"])
    if "nl2sql_agent" in sys.modules:
        importlib.reload(sys.modules["nl2sql_agent"])
    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    out = []
    for i, q in enumerate(qs, 1):
        t0 = datetime.now()
        try:
            rec = await asyncio.wait_for(run_one(q, "full"), timeout=240)
        except asyncio.TimeoutError:
            rec = {
                "qid": q.get("id", q.get("question_id", "?")),
                "ex": 0, "valid": 0, "gen_status": "timeout",
                "gen_error": "240s per-question timeout",
            }
        except Exception as e:
            rec = {
                "qid": q.get("id", q.get("question_id", "?")),
                "ex": 0, "valid": 0, "gen_status": "exception",
                "gen_error": str(e)[:300],
            }
        rec["family"] = "deepseek"
        rec["mode"] = "full"
        out.append(rec)
        dur = (datetime.now() - t0).total_seconds()
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [{i}/{len(qs)}] {m} {rec.get('qid')} ex={rec.get('ex')} "
              f"gen_status={rec.get('gen_status')} dur={dur:.1f}s", flush=True)
    return out


def main() -> int:
    qs = json.loads(BENCH.read_text(encoding="utf-8"))
    print(f"[augment] benchmark: {BENCH.name}, {len(qs)} questions")
    print(f"[augment] existing dir: {EXISTING_DIR}")

    report_path = EXISTING_DIR / "open_source_ablation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    print(f"\n=== DeepSeek FULL on 30q ({datetime.now().strftime('%H:%M:%S')}) ===")
    t0 = datetime.now()
    ds_full_recs = asyncio.run(run_deepseek_full(qs))
    wall_min = (datetime.now() - t0).total_seconds() / 60
    print(f"\n[augment] DeepSeek full done in {wall_min:.1f} min")

    # Persist the deepseek_full records alongside the existing three files
    (EXISTING_DIR / "deepseek_full_results.json").write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "family": "deepseek", "mode": "full",
            "benchmark": str(BENCH.relative_to(ROOT)),
            "wall_clock_minutes": round(wall_min, 2),
            "records": ds_full_recs,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Splice into the report and recompute pairs
    report.setdefault("deepseek", {})["full"] = ds_full_recs

    gm_base = ex_by_qid(report["gemini"]["baseline"])
    gm_full = ex_by_qid(report["gemini"]["full"])
    ds_base = ex_by_qid(report["deepseek"]["baseline"])
    ds_full = ex_by_qid(ds_full_recs)

    report["pairs"] = [
        paired(gm_base, gm_full, "gemini_baseline", "gemini_full"),
        paired(ds_base, ds_full, "deepseek_baseline", "deepseek_full"),
        paired(gm_base, ds_base, "gemini_baseline", "deepseek_baseline"),
        paired(gm_full, ds_full, "gemini_full", "deepseek_full"),
    ]
    report["deepseek_grounding_delta"] = round(
        (sum(ds_full.values()) / max(1, len(ds_full)))
        - (sum(ds_base.values()) / max(1, len(ds_base))), 4)
    report["augmented_at"] = datetime.now().isoformat()
    report["scope_note"] = (
        "Full 4-cell cross-family factorial: Gemini baseline/full + DeepSeek "
        "baseline/full, all 30 questions. DeepSeek full runs through ADK's "
        "google.adk.models.lite_llm.LiteLlm wrapper (openai/deepseek-v4-flash); "
        "nl2sql_agent.py was updated in v5 to route NL2SQL_AGENT_MODEL via "
        "model_gateway.create_model() so non-Gemini backends are wrapped "
        "correctly instead of being passed as a bare string."
    )
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(f"\nReport updated: {report_path}")
    for pr in report["pairs"]:
        print(f"  {pr['label_a']:22s} EX={pr['ex_a']}  vs  {pr['label_b']:22s} EX={pr['ex_b']}  "
              f"b/c={pr['discordant_a1b0']}/{pr['discordant_a0b1']}  p={pr['mcnemar_p_two_sided_exact']}")
    print(f"\nDeepSeek grounding delta: {report['deepseek_grounding_delta']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
