"""Cross-family grounding-effect subset analysis.

For each available family, compute paired B − A (grounding effect) per subset.
Specifically targets: does the spatial-subset regression observed in
gemini-3.5-flash generalise to any other family?

Zero quota — reads only existing jsonl. Output is single text report.
"""
from __future__ import annotations
import json
import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))
from post_analysis import t_test, mcnemar_exact

# (label, run_dir, family_subdir)
FAMILIES = [
    ("gemini-3.5-flash w/ mini-mod (N=5)",
     "data_agent/nl2sql_eval_results/v7_gemini35_minimod_n3_20260524", "gemini-3.5-flash"),
    ("gemini-3.5-flash NO-mm recheck (N=3)",
     "data_agent/nl2sql_eval_results/v7_gemini35_recheck_n3_2026-05-22_095253", "gemini-3.5-flash"),
    # All families below: N=3, no mini-mod, from the same 5-15 batch run
    ("gemini-2.5-flash (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "gemini-2.5-flash"),
    ("gemini-2.5-pro (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "gemini-2.5-pro"),
    ("gemini-3.1-flash-lite-preview (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "gemini-3.1-flash-lite-preview"),
    ("gemini-3.1-pro-preview (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "gemini-3.1-pro-preview"),
    ("deepseek-v4-flash (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "deepseek-v4-flash"),
    ("deepseek-v4-pro (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "deepseek-v4-pro"),
    ("qwen3.6-flash (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "qwen3.6-flash"),
    ("qwen3.6-plus (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "qwen3.6-plus"),
    ("qwen3.7-max (5-22)",
     "data_agent/nl2sql_eval_results/v7_qwen37max_n3_2026-05-22_095715", "qwen3.7-max"),
    ("gemma-4-31b-it-ollama (5-15)",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934", "gemma-4-31b-it-ollama"),
]

SUBSETS = [
    ("Overall (125q)", lambda r: True),
    ("Robust (40q)", lambda r: r.get("difficulty") == "Robustness"),
    ("Spatial (85q)", lambda r: r.get("difficulty") != "Robustness"),
    ("Easy (24q)", lambda r: r.get("difficulty") == "Easy"),
    ("Medium (36q)", lambda r: r.get("difficulty") == "Medium"),
    ("Hard (25q)", lambda r: r.get("difficulty") == "Hard"),
]


def load_samples(run_dir: Path, family: str, mode: str) -> list[list[dict]]:
    fam_dir = run_dir / family
    if not fam_dir.exists():
        return []
    out = []
    for sd in sorted(fam_dir.glob("sample_*"),
                     key=lambda p: int(p.name.split("_")[1])):
        p = sd / f"records_{mode}.jsonl"
        if not p.exists():
            continue
        recs = [json.loads(l) for l in p.open(encoding="utf-8")]
        if len(recs) == 125:
            out.append(recs)
    return out


def paired_delta(base_samples: list[list[dict]],
                 full_samples: list[list[dict]],
                 filter_fn) -> dict:
    n_pair = min(len(base_samples), len(full_samples))
    deltas = []
    bb = cc = 0
    for i in range(n_pair):
        a_idx = {r["qid"]: r for r in base_samples[i]}
        x_idx = {r["qid"]: r for r in full_samples[i]}
        common = set(a_idx) & set(x_idx)
        sub = [q for q in common if filter_fn(a_idx[q])]
        if not sub:
            continue
        a_ex = sum(a_idx[q]["ex"] for q in sub)
        x_ex = sum(x_idx[q]["ex"] for q in sub)
        deltas.append((x_ex - a_ex) / len(sub) * 100)
        bb += sum(1 for q in sub if a_idx[q]["ex"] == 1 and x_idx[q]["ex"] == 0)
        cc += sum(1 for q in sub if a_idx[q]["ex"] == 0 and x_idx[q]["ex"] == 1)
    stats = t_test(deltas) if deltas else None
    mc = mcnemar_exact(bb, cc)
    return {"n_paired": n_pair, "stats": stats, "mcnemar": mc, "deltas": deltas}


def main():
    print("# Cross-family grounding-effect subset analysis (paired B − A)\n")
    print("Tests the hypothesis: is grounding-induced spatial regression "
          "specific to gemini-3.5-flash?\n")
    print(f"{'family':>55s}  {'subset':18s}{'mean Δ':>10s}{'95% CI':>22s}{'McNm p':>10s}{'b/c':>10s}{'N':>4s}")
    print("-" * 130)
    for label, run_dir, fam in FAMILIES:
        A = load_samples(ROOT / run_dir, fam, "baseline")
        B = load_samples(ROOT / run_dir, fam, "full")
        if not A or not B:
            print(f"{label:>55s}  (missing data: A={len(A)} B={len(B)})")
            continue
        for sub_label, fn in SUBSETS:
            d = paired_delta(A, B, fn)
            s = d["stats"]
            mc = d["mcnemar"]
            if s is None:
                continue
            marker = ""
            if sub_label.startswith("Spatial") and s["mean"] < 0:
                marker = "  ← REGRESSION"
            elif sub_label.startswith("Spatial") and s["mean"] >= 0:
                marker = ""
            print(f"{label[:55]:>55s}  {sub_label:18s}"
                  f"{s['mean']:>+9.2f}pp"
                  f"  [{s['ci95_lo']:+.2f},{s['ci95_hi']:+.2f}]"
                  f"{mc['p']:>9.4f}"
                  f"  {mc['b']}/{mc['c']}"
                  f"{s['n']:>4d}{marker}")
        print()


if __name__ == "__main__":
    main()
