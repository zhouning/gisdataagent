"""Cross-family ABSOLUTE EX per subset (A=baseline, B=full).

Companion to cross_family_grounding_effect.py — that script emits paired Δ;
this one emits the absolute mean EX (± sd) for cell A and cell B per family per
subset, so the v6 paper's Table 4 can carry baseline/full values, not just Δ.

Zero quota — reads only existing jsonl. Output is a text report + a TeX-ready
table dump.
"""
from __future__ import annotations
import json
import sys
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

# (label, run_dir, family_subdir, short_label_for_tex)
FAMILIES = [
    ("gemini-2.5-flash",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "gemini-2.5-flash", "gemini-2.5-flash"),
    ("gemini-2.5-pro",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "gemini-2.5-pro", "gemini-2.5-pro"),
    ("gemini-3.1-flash-lite-preview",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "gemini-3.1-flash-lite-preview", "gemini-3.1-flash-lite-preview"),
    ("gemini-3.1-pro-preview",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
    ("gemini-3.5-flash NO-mm recheck",
     "data_agent/nl2sql_eval_results/v7_gemini35_recheck_n3_2026-05-22_095253",
     "gemini-3.5-flash", "gemini-3.5-flash"),
    ("deepseek-v4-flash",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "deepseek-v4-flash", "deepseek-v4-flash"),
    ("deepseek-v4-pro",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "deepseek-v4-pro", "deepseek-v4-pro"),
    ("qwen3.6-flash",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "qwen3.6-flash", "qwen3.6-flash"),
    ("qwen3.6-plus",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "qwen3.6-plus", "qwen3.6-plus"),
    ("qwen3.7-max",
     "data_agent/nl2sql_eval_results/v7_qwen37max_n3_2026-05-22_095715",
     "qwen3.7-max", "qwen3.7-max"),
    ("gemma-4-31b-it-ollama",
     "data_agent/nl2sql_eval_results/v7_d1d6_full_n3_2026-05-15_193934",
     "gemma-4-31b-it-ollama", "gemma-4-31b-it"),
]

SUBSETS = [
    ("Spatial (85q)",   lambda r: r.get("difficulty") != "Robustness"),
    ("Robust (40q)",    lambda r: r.get("difficulty") == "Robustness"),
    ("Overall (125q)",  lambda r: True),
    ("Easy (24q)",      lambda r: r.get("difficulty") == "Easy"),
    ("Medium (36q)",    lambda r: r.get("difficulty") == "Medium"),
    ("Hard (25q)",      lambda r: r.get("difficulty") == "Hard"),
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


def cell_ex(samples: list[list[dict]], filter_fn) -> dict:
    """Return mean ± sd of per-sample EX percent for the given subset filter."""
    per_sample = []
    sub_n = None
    for recs in samples:
        sub = [r for r in recs if filter_fn(r)]
        if not sub:
            continue
        sub_n = len(sub)
        per_sample.append(sum(r["ex"] for r in sub) / len(sub) * 100)
    if not per_sample:
        return {"mean": None, "sd": None, "n_samples": 0, "sub_n": sub_n}
    mean = statistics.mean(per_sample)
    sd = statistics.stdev(per_sample) if len(per_sample) > 1 else 0.0
    return {"mean": mean, "sd": sd, "n_samples": len(per_sample), "sub_n": sub_n,
            "values": per_sample}


def main():
    rows = []  # (label_tex, subset, A_dict, B_dict)
    print("# Cross-family ABSOLUTE EX per subset (A=baseline, B=full)\n")
    print(f"{'family':>40s}  {'subset':17s}"
          f"{'A mean±sd':>16s}  {'B mean±sd':>16s}"
          f"{'Δ (B-A)':>10s}{'N':>4s}")
    print("-" * 110)
    for label, run_dir, fam, tex_label in FAMILIES:
        A = load_samples(ROOT / run_dir, fam, "baseline")
        B = load_samples(ROOT / run_dir, fam, "full")
        if not A or not B:
            print(f"{label:>40s}  (missing: A={len(A)} B={len(B)})")
            continue
        for sub_label, fn in SUBSETS:
            ca = cell_ex(A, fn)
            cb = cell_ex(B, fn)
            if ca["mean"] is None or cb["mean"] is None:
                continue
            delta = cb["mean"] - ca["mean"]
            print(f"{label[:40]:>40s}  {sub_label:17s}"
                  f"  {ca['mean']:>5.2f}±{ca['sd']:>4.2f}"
                  f"  {cb['mean']:>5.2f}±{cb['sd']:>4.2f}"
                  f"  {delta:>+7.2f}pp"
                  f"  {ca['n_samples']}")
            rows.append((tex_label, sub_label, ca, cb, delta))
        print()

    # ---- Per-sample raw values (for SOT table appendix) ----
    print("\n" + "=" * 80)
    print("# Per-sample raw EX values (% pass per subset, one row per sample)")
    print("=" * 80)
    print()
    print(f"{'family':>40s}  {'subset':17s}  {'arm':9s}  {'sample EX values'}")
    print("-" * 110)
    for label, run_dir, fam, tex_label in FAMILIES:
        A = load_samples(ROOT / run_dir, fam, "baseline")
        B = load_samples(ROOT / run_dir, fam, "full")
        if not A or not B:
            continue
        for sub_label, fn in SUBSETS:
            ca = cell_ex(A, fn)
            cb = cell_ex(B, fn)
            if ca["mean"] is None or cb["mean"] is None:
                continue
            a_vals = ", ".join(f"{v:.2f}" for v in ca["values"])
            b_vals = ", ".join(f"{v:.2f}" for v in cb["values"])
            print(f"{tex_label[:40]:>40s}  {sub_label:17s}  baseline  [{a_vals}]")
            print(f"{tex_label[:40]:>40s}  {sub_label:17s}  full      [{b_vals}]")
        print()

    # ---- TeX output: 7-col Table 4 (Spatial A/B/Δ + Robust A/B/Δ) ----
    print("\n" + "=" * 80)
    print("# TeX-ready rows for v6 Table 4 (Spatial + Robust, absolute + Δ)")
    print("=" * 80)
    print()
    print("Family & Spatial A & Spatial B & Spatial Δ & Robust A & Robust B & Robust Δ \\\\")
    print("\\midrule")
    # Group rows by family
    by_fam: dict[str, dict[str, tuple]] = {}
    for tex_label, sub_label, ca, cb, delta in rows:
        by_fam.setdefault(tex_label, {})[sub_label] = (ca, cb, delta)
    fam_order = [f[3] for f in FAMILIES]
    for fam in fam_order:
        if fam not in by_fam:
            continue
        spatial = by_fam[fam].get("Spatial (85q)")
        robust = by_fam[fam].get("Robust (40q)")
        if spatial is None or robust is None:
            continue
        s_a, s_b, s_d = spatial
        r_a, r_b, r_d = robust
        is_g35 = "gemini-3.5-flash" in fam
        fam_tex = f"\\textbf{{\\texttt{{{fam}}}}}" if is_g35 else f"\\texttt{{{fam}}}"
        s_d_tex = f"\\mathbf{{{s_d:+.2f}}}" if is_g35 else f"{s_d:+.2f}"
        print(f"{fam_tex} & "
              f"${s_a['mean']:.2f}{{\\scriptstyle\\,\\pm{s_a['sd']:.2f}}}$ & "
              f"${s_b['mean']:.2f}{{\\scriptstyle\\,\\pm{s_b['sd']:.2f}}}$ & "
              f"${s_d_tex}$ & "
              f"${r_a['mean']:.2f}{{\\scriptstyle\\,\\pm{r_a['sd']:.2f}}}$ & "
              f"${r_b['mean']:.2f}{{\\scriptstyle\\,\\pm{r_b['sd']:.2f}}}$ & "
              f"${r_d:+.2f}$ \\\\")


if __name__ == "__main__":
    main()
