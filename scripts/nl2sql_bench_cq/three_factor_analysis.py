"""3-factor attribution analysis for prompt patch evaluation.

Reads three sets of jsonl:
  A. baseline (no grounding):       baseline mode of any minimod run (5 samples)
  B. grounding only (no patch):     full mode of 5-22 recheck (5 samples)
  C. grounding + patch (mini-mod):  full mode of N=5 minimod run (5 samples)

For each cell, reports:
  - Overall EX
  - Robustness 40q EX
  - Spatial 85q EX
  - Easy/Medium/Hard EX
  - Top categories Δ
  - Paired t-test (vs A) and McNemar (vs A) on overall and each subset
  - Three-factor decomposition: grounding effect (B-A), patch net effect (C-B), total (C-A)

Output is single text report. Quota cost: zero (existing jsonl).
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))
from run_v7_iteration import classify_failure  # noqa
from post_analysis import (
    relaxed_ex, t_test, mcnemar_exact, T_CRIT_95
)


# ---- data sources -----------------------------------------------------------

A_RUN = ROOT / "data_agent/nl2sql_eval_results/v7_gemini35_minimod_n3_20260524"
B_RUN = ROOT / "data_agent/nl2sql_eval_results/v7_gemini35_recheck_n3_2026-05-22_095253"
C_RUN = A_RUN  # same dir, full mode
FAMILY = "gemini-3.5-flash"

CONDITIONS = [
    ("A: no-grounding (baseline mode of N=5 mm run)", A_RUN, "baseline", 5),
    ("B: grounding only (full mode of 5-22 recheck)", B_RUN, "full", 5),
    ("C: grounding + minimod (full mode of N=5 mm run)", C_RUN, "full", 5),
]


def load_records(run_dir: Path, mode: str) -> list[list[dict]]:
    """Return list of N samples, each sample is list of records."""
    fam_dir = run_dir / FAMILY
    samples = sorted(fam_dir.glob("sample_*"),
                     key=lambda p: int(p.name.split("_")[1]))
    out = []
    for sd in samples:
        p = sd / f"records_{mode}.jsonl"
        if not p.exists():
            continue
        recs = [json.loads(l) for l in p.open(encoding="utf-8")]
        if len(recs) == 125:
            out.append(recs)
    return out


def per_qid_index(records: list[dict]) -> dict:
    return {r["qid"]: r for r in records}


def ex_on_subset(samples: list[list[dict]], filter_fn) -> dict:
    """For each sample, compute EX on subset; return list of (n, pass) tuples + mean rate."""
    per_sample = []
    for recs in samples:
        sub = [r for r in recs if filter_fn(r)]
        if not sub:
            continue
        per_sample.append((len(sub), sum(r["ex"] for r in sub)))
    if not per_sample:
        return {"n_samples": 0, "rate_mean": None, "rate_sd": None, "raw": []}
    rates = [p / n for n, p in per_sample]
    m = sum(rates) / len(rates)
    sd = (sum((x - m) ** 2 for x in rates) / max(len(rates) - 1, 1)) ** 0.5 if len(rates) > 1 else 0.0
    return {"n_samples": len(per_sample), "rate_mean": m,
            "rate_sd": sd, "n_q_per_sample": per_sample[0][0],
            "raw": per_sample}


def paired_delta_to_A(samples_A: list[list[dict]],
                      samples_X: list[list[dict]],
                      filter_fn) -> dict:
    """Compute (X − A) Δ paired by qid+sample_index, on subset.

    A and X may have different N samples. We pair by min(N_A, N_X) leading samples.
    """
    n_pair = min(len(samples_A), len(samples_X))
    deltas = []
    bb_total, cc_total = 0, 0
    for i in range(n_pair):
        a_idx = per_qid_index(samples_A[i])
        x_idx = per_qid_index(samples_X[i])
        common = set(a_idx) & set(x_idx)
        sub = [q for q in common if filter_fn(a_idx[q])]
        if not sub:
            continue
        a_ex = sum(a_idx[q]["ex"] for q in sub)
        x_ex = sum(x_idx[q]["ex"] for q in sub)
        d = (x_ex - a_ex) / len(sub) * 100
        deltas.append(d)
        bb_total += sum(1 for q in sub if a_idx[q]["ex"] == 1 and x_idx[q]["ex"] == 0)
        cc_total += sum(1 for q in sub if a_idx[q]["ex"] == 0 and x_idx[q]["ex"] == 1)
    stats = t_test(deltas) if deltas else None
    mc = mcnemar_exact(bb_total, cc_total)
    return {"n_paired_samples": n_pair, "deltas": deltas,
            "stats": stats, "mcnemar": mc}


def main():
    print(f"# 3-factor attribution analysis: {FAMILY}\n")
    print(f"## Data sources\n")
    cells = {}
    for label, run_dir, mode, expect_n in CONDITIONS:
        samples = load_records(run_dir, mode)
        print(f"  {label}: N={len(samples)} (expected {expect_n})")
        cells[label] = samples

    A = cells[CONDITIONS[0][0]]
    B = cells[CONDITIONS[1][0]]
    C = cells[CONDITIONS[2][0]]

    print()
    print("## EX rate per cell × subset\n")
    subsets = [
        ("Overall (125q)", lambda r: True),
        ("Robustness (40q)", lambda r: r.get("difficulty") == "Robustness"),
        ("Spatial / non-robust (85q)", lambda r: r.get("difficulty") != "Robustness"),
        ("Easy (24q)", lambda r: r.get("difficulty") == "Easy"),
        ("Medium (36q)", lambda r: r.get("difficulty") == "Medium"),
        ("Hard (25q)", lambda r: r.get("difficulty") == "Hard"),
    ]

    print(f"  {'subset':32s}{'A (no-gnd)':>14s}{'B (gnd only)':>16s}{'C (gnd+mm)':>14s}")
    print(f"  {'':32s}{'mean ± sd':>14s}{'mean ± sd':>16s}{'mean ± sd':>14s}")
    for label, fn in subsets:
        a = ex_on_subset(A, fn)
        b = ex_on_subset(B, fn)
        c = ex_on_subset(C, fn)
        def _fmt(s):
            if s["rate_mean"] is None:
                return "n/a".rjust(14)
            return f"{s['rate_mean']*100:>5.1f} ± {s['rate_sd']*100:.1f}%".rjust(14)
        print(f"  {label:32s}{_fmt(a)}{_fmt(b):>16s}{_fmt(c)}")

    print()
    print("## Three-factor decomposition (X − A paired Δ, pp)\n")
    print(f"  {'subset':32s}{'B − A (grounding only)':>30s}{'C − A (grounding+mm)':>26s}")
    for label, fn in subsets:
        bma = paired_delta_to_A(A, B, fn)
        cma = paired_delta_to_A(A, C, fn)
        def _ds(d):
            if not d["stats"]:
                return "n/a"
            s = d["stats"]
            mc = d["mcnemar"]
            return (f"{s['mean']:+6.2f}pp [{s['ci95_lo']:+5.2f},{s['ci95_hi']:+5.2f}] "
                    f"McNm p={mc['p']:.3f} N={s['n']}")
        print(f"  {label:32s}  {_ds(bma):>30s}  {_ds(cma):>26s}")

    print()
    print("## Patch net effect (C − B paired Δ on overlapping samples)\n")
    # For each subset, compare C samples 1-3 against B samples 1-3 directly
    print(f"  {'subset':32s}{'C − B (minimod net)':>30s}")
    for label, fn in subsets:
        cmb = paired_delta_to_A(B, C, fn)  # treat B as 'baseline' here
        def _ds(d):
            if not d["stats"]:
                return "n/a"
            s = d["stats"]
            mc = d["mcnemar"]
            return (f"{s['mean']:+6.2f}pp [{s['ci95_lo']:+5.2f},{s['ci95_hi']:+5.2f}] "
                    f"McNm p={mc['p']:.3f} N={s['n']}")
        print(f"  {label:32s}  {_ds(cmb):>30s}")

    # ---- Per-category breakdown across 3 conditions ----
    print()
    print("## Per-category EX rate (top categories by n_q)\n")
    # Use one sample to enumerate categories
    cats = sorted({r.get("category") for r in A[0]} - {None}, key=str)
    print(f"  {'category':30s}{'n_q':>6s}{'A %':>10s}{'B %':>10s}{'C %':>10s}{'B−A':>10s}{'C−B':>10s}")
    for cat in cats:
        n_q = sum(1 for r in A[0] if r.get("category") == cat)
        if n_q < 3:
            continue
        def fn(r): return r.get("category") == cat
        a = ex_on_subset(A, fn)
        b = ex_on_subset(B, fn)
        c = ex_on_subset(C, fn)
        if a["rate_mean"] is None: continue
        ar, br, cr = a["rate_mean"]*100, b["rate_mean"]*100, c["rate_mean"]*100
        print(f"  {cat[:30]:30s}{n_q:>6d}{ar:>9.1f}%{br:>9.1f}%{cr:>9.1f}%"
              f"{br-ar:>+9.1f}{cr-br:>+9.1f}")


if __name__ == "__main__":
    main()
