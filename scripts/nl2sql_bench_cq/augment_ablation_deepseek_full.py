"""Rerun Gemini full + DeepSeek full on the 30q subset with matched config.

Addresses a rigour concern in the first augment attempt: the originally
committed Gemini-full results were produced with an LlmAgent that had no
explicit generate_content_config, so the decoding temperature defaulted to
whatever ADK's Gemini wrapper uses. A DeepSeek-full run through LiteLlm would
have defaulted to OpenAI's temperature=1.0. The difference would have conflated
model-family with decoding stochasticity.

This rerun pins both families to temperature=0.0 via the updated
nl2sql_agent.py (commit enforcing generate_content_config on the LlmAgent).
Baselines (gemini_baseline, deepseek_baseline) are preserved from the original
run because they already used temperature=0.0 explicitly (see
run_cq_eval.baseline_generate's GenerateContentConfig, and
run_open_source_ablation.deepseek_baseline_generate's generate_text(..., temperature=0.0)).

Output: splices deepseek_full + replaces gemini_full in the existing report,
records the agent generation config in the report for auditability.

Usage:
  cd D:\\adk
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
    .venv/Scripts/python.exe scripts/nl2sql_bench_cq/augment_ablation_deepseek_full.py
"""
from __future__ import annotations

import asyncio
import importlib
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


def _reset_cq_caches() -> None:
    """Fully reload run_cq_eval and nl2sql_agent so env var changes propagate.

    nl2sql_agent.py caches the built LlmAgent in _cached_agent, so a module
    reload is not enough — we must also clear the cache variable, which means
    we must reload the submodule *after* the env is set. importlib.reload
    re-runs module body but does NOT re-run nested import-time captures in
    run_cq_eval's lazy init; so we also clear its lazy-init flag.
    """
    for name in ("run_cq_eval", "nl2sql_agent"):
        if name in sys.modules:
            del sys.modules[name]


async def _run_full_family(family: str, model_name: str, qs: list[dict], label: str) -> list[dict]:
    """Run NL2SQL full-mode for one family. Each family gets a fresh process state
    (caches cleared, env configured, modules re-imported)."""
    if family == "deepseek":
        os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
    else:
        os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    os.environ["NL2SQL_AGENT_MODEL"] = model_name

    _reset_cq_caches()
    from run_cq_eval import run_one, _init_runtime  # fresh import under new env
    _init_runtime()

    # Probe the constructed agent to confirm routing + config are correct before
    # burning 30 questions.
    from nl2sql_agent import build_nl2sql_agent
    probe = build_nl2sql_agent()
    actual_model_type = type(probe.model).__name__
    actual_model_repr = repr(probe.model)[:200]
    actual_gen_cfg = probe.generate_content_config
    actual_temp = getattr(actual_gen_cfg, "temperature", None) if actual_gen_cfg else None
    print(f"\n  [probe/{label}] model_type={actual_model_type}  "
          f"temperature={actual_temp}  force_deepseek={os.environ.get('NL2SQL_FORCE_DEEPSEEK','0')}")
    print(f"  [probe/{label}] model={actual_model_repr}", flush=True)
    if family == "deepseek":
        assert actual_model_type == "LiteLlm", \
            f"Expected LiteLlm for DeepSeek, got {actual_model_type}"
    else:
        assert actual_model_type == "Gemini", \
            f"Expected Gemini for Gemini family, got {actual_model_type}"
    assert actual_temp == 0.0, \
        f"Expected temperature=0.0 for reproducibility, got {actual_temp}"

    out = []
    for i, q in enumerate(qs, 1):
        t0 = datetime.now()
        try:
            rec = await asyncio.wait_for(run_one(q, "full"), timeout=300)
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
        rec["family"] = family
        rec["mode"] = "full"
        out.append(rec)
        dur = (datetime.now() - t0).total_seconds()
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [{label} {i}/{len(qs)}] {m} {rec.get('qid')} ex={rec.get('ex')} "
              f"gen_status={rec.get('gen_status')} dur={dur:.1f}s", flush=True)
    return out


def main() -> int:
    qs = json.loads(BENCH.read_text(encoding="utf-8"))
    print(f"[augment] benchmark: {BENCH.name}, {len(qs)} questions")
    print(f"[augment] target dir: {EXISTING_DIR}")

    report_path = EXISTING_DIR / "open_source_ablation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Preserve baselines verbatim (both already at temperature=0.0)
    gm_base_recs = report["gemini"]["baseline"]
    ds_base_recs = report["deepseek"]["baseline"]
    print(f"\n[augment] preserving gemini baseline ({len(gm_base_recs)}) and "
          f"deepseek baseline ({len(ds_base_recs)}) from existing report")

    # Rerun Gemini full at temp=0.0 for parity
    print(f"\n=== Gemini FULL (temp=0.0 enforced) on 30q  {datetime.now().strftime('%H:%M:%S')} ===")
    gm_t0 = datetime.now()
    gm_full_recs = asyncio.run(_run_full_family("gemini", "gemini-2.5-flash", qs, "gemini/full"))
    gm_min = (datetime.now() - gm_t0).total_seconds() / 60
    print(f"\n[augment] gemini/full done in {gm_min:.1f} min")

    # Rerun DeepSeek full at temp=0.0
    print(f"\n=== DeepSeek FULL (temp=0.0 enforced) on 30q  {datetime.now().strftime('%H:%M:%S')} ===")
    ds_t0 = datetime.now()
    ds_full_recs = asyncio.run(_run_full_family("deepseek", "deepseek-v4-flash", qs, "deepseek/full"))
    ds_min = (datetime.now() - ds_t0).total_seconds() / 60
    print(f"\n[augment] deepseek/full done in {ds_min:.1f} min")

    # Write per-family full files
    (EXISTING_DIR / "gemini_full_results.json").write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "family": "gemini", "mode": "full",
            "benchmark": str(BENCH.relative_to(ROOT)),
            "temperature": 0.0, "wall_clock_minutes": round(gm_min, 2),
            "records": gm_full_recs,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (EXISTING_DIR / "deepseek_full_results.json").write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "family": "deepseek", "mode": "full",
            "benchmark": str(BENCH.relative_to(ROOT)),
            "temperature": 0.0, "wall_clock_minutes": round(ds_min, 2),
            "records": ds_full_recs,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Splice into report + recompute pairs (4-cell factorial)
    report["gemini"]["full"] = gm_full_recs
    report.setdefault("deepseek", {})["full"] = ds_full_recs

    gm_base = ex_by_qid(gm_base_recs)
    gm_full = ex_by_qid(gm_full_recs)
    ds_base = ex_by_qid(ds_base_recs)
    ds_full = ex_by_qid(ds_full_recs)

    report["pairs"] = [
        paired(gm_base, gm_full, "gemini_baseline", "gemini_full"),
        paired(ds_base, ds_full, "deepseek_baseline", "deepseek_full"),
        paired(gm_base, ds_base, "gemini_baseline", "deepseek_baseline"),
        paired(gm_full, ds_full, "gemini_full", "deepseek_full"),
    ]
    report["gemini_grounding_delta"] = round(
        (sum(gm_full.values()) / max(1, len(gm_full)))
        - (sum(gm_base.values()) / max(1, len(gm_base))), 4)
    report["deepseek_grounding_delta"] = round(
        (sum(ds_full.values()) / max(1, len(ds_full)))
        - (sum(ds_base.values()) / max(1, len(ds_base))), 4)
    report["augmented_at"] = datetime.now().isoformat()
    report["scope_note"] = (
        "Full 4-cell cross-family factorial on the 30q stratified Spatial subset. "
        "All four cells use temperature=0.0. Baselines (schema-only generation) go "
        "through direct-HTTP providers: Gemini via google.genai, DeepSeek via "
        "OpenAI-compatible SDK with force-deepseek; the full pipeline goes through "
        "ADK's LlmAgent with model selection via data_agent.model_gateway.create_model() "
        "(Gemini wrapped in google.adk.models.google_llm.Gemini; DeepSeek wrapped in "
        "google.adk.models.lite_llm.LiteLlm with model='openai/deepseek-v4-flash'). "
        "All four cells use the same prompt, the same grounding tool definitions, "
        "and the same 30-question stratified sample. The paired McNemar tests isolate "
        "(a) within-family grounding gain; (b) cross-family baseline capability parity; "
        "(c) cross-family full-pipeline capability."
    )
    report["agent_generate_content_config"] = {"temperature": 0.0}
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(f"\nReport updated: {report_path}")
    for pr in report["pairs"]:
        print(f"  {pr['label_a']:22s} EX={pr['ex_a']}  vs  {pr['label_b']:22s} EX={pr['ex_b']}  "
              f"b/c={pr['discordant_a1b0']}/{pr['discordant_a0b1']}  p={pr['mcnemar_p_two_sided_exact']}")
    print(f"\nGemini   grounding delta: {report['gemini_grounding_delta']:+.3f}")
    print(f"DeepSeek grounding delta: {report['deepseek_grounding_delta']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
