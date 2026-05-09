"""Pool cross-family 85q N=3 results (reuses historical Gemini samples).

Assembles an 8-sample matrix (Gemini baseline×1 + Gemini full×3 + DeepSeek
baseline×3 + DeepSeek full×3) on the Chongqing Spatial 85q benchmark, and
reports:
  - Per-cell EX mean ± SD
  - Per-sample paired McNemar baseline→full (within family)
  - Majority-vote EX per family × mode (vote=1 iff ≥2/3 samples correct)
  - Paired McNemar on majority-vote: within-family grounding + cross-family
  - 4-cell summary ready to paste into Supplement S3

Gemini paths (reused from v5 main paper; NOT re-run because the same code
path produced them, and zero 429/quota errors in historical records, so
retry_options add no behavioural drift):
  Gemini baseline: cq_2026-05-08_090919/baseline_results.json (Spatial 45/85)
  Gemini full sample 1: ablation_agentloop_2026-05-07_233516/Full_results.json (60/85)
  Gemini full sample 2: cq_2026-05-08_090919/full_results.json (52/85)
  Gemini full sample 3: full_resample_2026-05-08_1040/Full_results.json (57/85)

DeepSeek paths (produced by run_cross_family_85q.py; caller passes --out-dir):
  <out-dir>/deepseek_baseline_s{1,2,3}_results.json
  <out-dir>/deepseek_full_s{1,2,3}_results.json

Usage:
  cd D:\\adk
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
    .venv/Scripts/python.exe scripts/nl2sql_bench_cq/stats_cross_family_85q.py \\
        --out-dir data_agent/nl2sql_eval_results/cross_family_85q_<ts>
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from math import comb
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

GEMINI_SOURCES = {
    "baseline": [
        ROOT / "data_agent" / "nl2sql_eval_results" / "cq_2026-05-08_090919" / "baseline_results.json",
    ],
    "full": [
        ROOT / "data_agent" / "nl2sql_eval_results" / "ablation_agentloop_2026-05-07_233516" / "Full_results.json",
        ROOT / "data_agent" / "nl2sql_eval_results" / "cq_2026-05-08_090919" / "full_results.json",
        ROOT / "data_agent" / "nl2sql_eval_results" / "full_resample_2026-05-08_1040" / "Full_results.json",
    ],
}


def mcnemar_exact_two_sided(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p_one = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_one)


def load_recs(path: Path) -> list[dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return d.get("records", d) if isinstance(d, dict) else d


def filter_spatial(recs: list[dict]) -> list[dict]:
    return [r for r in recs
            if str(r.get("difficulty", "")).lower() in ("easy", "medium", "hard")]


def ex_by_qid(recs: list[dict]) -> dict[str, int]:
    return {r["qid"]: (1 if r.get("ex") else 0) for r in filter_spatial(recs)}


def paired(a_ex: dict, b_ex: dict, label_a: str, label_b: str) -> dict:
    qids = sorted(set(a_ex) & set(b_ex))
    tp = fp = fn = tn = 0
    for q in qids:
        pa, pb = a_ex[q], b_ex[q]
        if pa and pb: tp += 1
        elif pa and not pb: fp += 1
        elif not pa and pb: fn += 1
        else: tn += 1
    return {
        "n": len(qids), "label_a": label_a, "label_b": label_b,
        "ex_a": round(sum(a_ex[q] for q in qids) / max(1, len(qids)), 4),
        "ex_b": round(sum(b_ex[q] for q in qids) / max(1, len(qids)), 4),
        "both_correct": tp, "only_a": fp, "only_b": fn, "both_wrong": tn,
        "discordant_a_wins_b": fp, "discordant_b_wins_a": fn,
        "mcnemar_p_two_sided_exact": round(mcnemar_exact_two_sided(fp, fn), 6),
    }


def majority_vote(samples: list[dict[str, int]]) -> dict[str, int]:
    """Per-qid majority vote across N samples. 1 iff ≥ N/2 samples say 1."""
    if not samples:
        return {}
    qids = sorted(set().union(*samples))
    thresh = (len(samples) + 1) // 2
    return {q: (1 if sum(s.get(q, 0) for s in samples) >= thresh else 0)
            for q in qids}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True,
                   help="Directory with deepseek_{baseline,full}_s{1,2,3}_results.json")
    p.add_argument("--report", default=None,
                   help="Output report path (default: <out-dir>/cross_family_85q_report.json)")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    report_path = Path(args.report) if args.report else (out_dir / "cross_family_85q_report.json")

    # ---- Load Gemini historical samples (Spatial 85q only)
    gm_base_ex = ex_by_qid(load_recs(GEMINI_SOURCES["baseline"][0]))
    gm_full_samples_ex = [ex_by_qid(load_recs(p)) for p in GEMINI_SOURCES["full"]]

    # ---- Load new DeepSeek samples
    ds_base_files = [out_dir / f"deepseek_baseline_s{i}_results.json" for i in (1, 2, 3)]
    ds_full_files = [out_dir / f"deepseek_full_s{i}_results.json" for i in (1, 2, 3)]
    for f in ds_base_files + ds_full_files:
        if not f.exists():
            raise SystemExit(f"Missing required input: {f}")

    ds_base_samples_ex = [ex_by_qid(load_recs(p)) for p in ds_base_files]
    ds_full_samples_ex = [ex_by_qid(load_recs(p)) for p in ds_full_files]

    # Sanity: all cells must cover the same 85 qids
    all_cells = [gm_base_ex] + gm_full_samples_ex + ds_base_samples_ex + ds_full_samples_ex
    qid_sets = [set(c.keys()) for c in all_cells]
    common_qids = set.intersection(*qid_sets)
    if len(common_qids) != 85:
        print(f"[warn] intersected qids = {len(common_qids)} (expected 85); "
              f"proceeding with intersection", file=sys.stderr)

    # ---- Per-cell EX
    def ex_rate(d): return round(sum(d.values()) / max(1, len(d)), 4)

    cells = {
        "gemini_baseline": [ex_rate(gm_base_ex)],
        "gemini_full": [ex_rate(s) for s in gm_full_samples_ex],
        "deepseek_baseline": [ex_rate(s) for s in ds_base_samples_ex],
        "deepseek_full": [ex_rate(s) for s in ds_full_samples_ex],
    }

    def mean_sd(vs):
        if len(vs) <= 1:
            return {"mean": round(vs[0], 4) if vs else 0.0, "sd": None, "n": len(vs)}
        return {"mean": round(statistics.mean(vs), 4),
                "sd": round(statistics.stdev(vs), 4),
                "n": len(vs)}

    # ---- Majority votes
    # Gemini baseline is N=1 so "majority" = the one sample
    gm_base_mv = gm_base_ex
    gm_full_mv = majority_vote(gm_full_samples_ex)
    ds_base_mv = majority_vote(ds_base_samples_ex)
    ds_full_mv = majority_vote(ds_full_samples_ex)

    # ---- Paired McNemar
    # Within-family on majority votes:
    within_gm_mv = paired(gm_base_mv, gm_full_mv, "gemini_baseline_mv", "gemini_full_mv")
    within_ds_mv = paired(ds_base_mv, ds_full_mv, "deepseek_baseline_mv", "deepseek_full_mv")
    # Cross-family on majority votes:
    cross_base_mv = paired(gm_base_mv, ds_base_mv, "gemini_baseline_mv", "deepseek_baseline_mv")
    cross_full_mv = paired(gm_full_mv, ds_full_mv, "gemini_full_mv", "deepseek_full_mv")

    # Per-sample within-family paired McNemar for auditability:
    # Gemini: baseline (N=1) vs each full sample
    gm_per_sample = [paired(gm_base_ex, s, "gemini_baseline", f"gemini_full_s{i+1}")
                     for i, s in enumerate(gm_full_samples_ex)]
    # DeepSeek: each baseline sample vs each full sample with matched index
    # (paired McNemar requires same qids, not matched base/full samples;
    # but without pairing assumption, we use each baseline vs each full by sample_idx)
    ds_per_sample = [paired(ds_base_samples_ex[i], ds_full_samples_ex[i],
                            f"deepseek_baseline_s{i+1}", f"deepseek_full_s{i+1}")
                     for i in range(3)]

    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "benchmark": "benchmarks/chongqing_geo_nl2sql_100_benchmark.json (Spatial 85q)",
        "scope_note": (
            "4-cell cross-family factorial on GIS Spatial 85q. Each family runs baseline "
            "(schema-only direct HTTP) and full (LlmAgent with grounding + intent routing + "
            "postprocessor + self-correction). Temperature is NOT pinned: each family uses "
            "its own provider default (Gemini server-side default; DeepSeek OpenAI-spec "
            "default, temperature=1.0). Stochastic variance is captured via N=3 sampling "
            "per full cell and N=3 per DeepSeek baseline (Gemini baseline is N=1 because "
            "baseline_generate uses temperature=0.0 explicitly and is deterministic for "
            "that family; DeepSeek's API is not deterministic even at temperature=0.0, "
            "so we report N=3 for its baseline too). Paired McNemar is on majority-vote "
            "per qid across the N=3 samples."
        ),
        "sample_provenance": {
            "gemini_baseline": [str(p.relative_to(ROOT)) for p in GEMINI_SOURCES["baseline"]],
            "gemini_full":     [str(p.relative_to(ROOT)) for p in GEMINI_SOURCES["full"]],
            "deepseek_baseline": [str(p.relative_to(ROOT)) for p in ds_base_files],
            "deepseek_full":     [str(p.relative_to(ROOT)) for p in ds_full_files],
        },
        "cells_mean_sd": {k: mean_sd(v) for k, v in cells.items()},
        "cells_per_sample_ex": cells,
        "paired_mcnemar_on_majority_vote": {
            "within_family_gemini":  within_gm_mv,
            "within_family_deepseek": within_ds_mv,
            "cross_family_baseline":  cross_base_mv,
            "cross_family_full":      cross_full_mv,
        },
        "paired_mcnemar_per_sample": {
            "gemini_baseline_vs_full_per_sample":  gm_per_sample,
            "deepseek_baseline_vs_full_per_sample": ds_per_sample,
        },
    }

    # Deltas for the narrative
    def cell_mean(k): return report["cells_mean_sd"][k]["mean"]
    report["gemini_grounding_delta_mean"]   = round(cell_mean("gemini_full") - cell_mean("gemini_baseline"), 4)
    report["deepseek_grounding_delta_mean"] = round(cell_mean("deepseek_full") - cell_mean("deepseek_baseline"), 4)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # ---- Console summary ----
    print(f"\n{'=' * 76}")
    print(f"Cross-family 85q N=3 report ({report['benchmark']})")
    print(f"{'=' * 76}")
    print("\nCells (mean ± SD across N samples):")
    for k, v in report["cells_mean_sd"].items():
        sd_str = f"±{v['sd']}" if v["sd"] is not None else "(N=1)"
        print(f"  {k:22s} n={v['n']}  EX mean={v['mean']}  {sd_str}")

    print("\nPaired McNemar on majority-vote per qid:")
    for label in ("within_family_gemini", "within_family_deepseek",
                  "cross_family_baseline", "cross_family_full"):
        r = report["paired_mcnemar_on_majority_vote"][label]
        print(f"  {label:28s}  {r['label_a']} EX={r['ex_a']}  vs  "
              f"{r['label_b']} EX={r['ex_b']}  "
              f"b/c={r['discordant_a_wins_b']}/{r['discordant_b_wins_a']}  "
              f"p={r['mcnemar_p_two_sided_exact']}")

    print("\nGrounding deltas (mean):")
    print(f"  Gemini:   {report['gemini_grounding_delta_mean']:+.4f}")
    print(f"  DeepSeek: {report['deepseek_grounding_delta_mean']:+.4f}")

    print(f"\nReport saved: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
