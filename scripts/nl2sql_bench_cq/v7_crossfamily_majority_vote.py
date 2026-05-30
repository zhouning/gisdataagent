"""Cross-family B-A under per-question majority vote (uniform N=3, single McNemar).

Companion to v7_authoritative_recompute.py: applies the same honest statistical
convention to all 11 families, to check whether the 'single-family pathology'
framing survives the de-pooled significance test.
"""
from __future__ import annotations
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import json
import math
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]

FAMILIES = [
    ("gemini-2.5-flash", "v7_d1d6_full_n3_2026-05-15_193934", "gemini-2.5-flash"),
    ("gemini-2.5-pro", "v7_d1d6_full_n3_2026-05-15_193934", "gemini-2.5-pro"),
    ("gemini-3.1-flash-lite-preview", "v7_d1d6_full_n3_2026-05-15_193934", "gemini-3.1-flash-lite-preview"),
    ("gemini-3.1-pro-preview", "v7_d1d6_full_n3_2026-05-15_193934", "gemini-3.1-pro-preview"),
    ("gemini-3.5-flash", "v7_gemini35_recheck_n3_2026-05-22_095253", "gemini-3.5-flash"),
    ("deepseek-v4-flash", "v7_d1d6_full_n3_2026-05-15_193934", "deepseek-v4-flash"),
    ("deepseek-v4-pro", "v7_d1d6_full_n3_2026-05-15_193934", "deepseek-v4-pro"),
    ("qwen3.6-flash", "v7_d1d6_full_n3_2026-05-15_193934", "qwen3.6-flash"),
    ("qwen3.6-plus", "v7_d1d6_full_n3_2026-05-15_193934", "qwen3.6-plus"),
    ("qwen3.7-max", "v7_qwen37max_n3_2026-05-22_095715", "qwen3.7-max"),
    ("gemma-4-31b-it", "v7_d1d6_full_n3_2026-05-15_193934", "gemma-4-31b-it-ollama"),
]

SUBSETS = [
    ("Robust", lambda r: r.get("difficulty") == "Robustness"),
    ("Spatial", lambda r: r.get("difficulty") != "Robustness"),
    ("Medium", lambda r: r.get("difficulty") == "Medium"),
]


def load_samples(run_dir, family, mode, cap=3):
    fam_dir = ROOT / "data_agent/nl2sql_eval_results" / run_dir / family
    out = []
    for sd in sorted(fam_dir.glob("sample_*"), key=lambda p: int(p.name.split("_")[1])):
        p = sd / f"records_{mode}.jsonl"
        if not p.exists():
            continue
        recs = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
        if len(recs) == 125:
            out.append(recs)
        if len(out) >= cap:
            break
    return out


def majority_vote(samples):
    votes = defaultdict(list)
    meta = {}
    for recs in samples:
        for r in recs:
            votes[r["qid"]].append(r["ex"])
            meta[r["qid"]] = r
    return {q: {"ex": 1 if sum(vs) > len(vs) / 2 else 0,
                "difficulty": meta[q].get("difficulty", "?")}
            for q, vs in votes.items()}


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    s = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2 * s)


def paired_mv(mv_a, mv_x, fn):
    common = set(mv_a) & set(mv_x)
    sub = [q for q in common if fn(mv_a[q])]
    if not sub:
        return None
    a_pass = sum(mv_a[q]["ex"] for q in sub)
    x_pass = sum(mv_x[q]["ex"] for q in sub)
    b = sum(1 for q in sub if mv_a[q]["ex"] == 1 and mv_x[q]["ex"] == 0)
    c = sum(1 for q in sub if mv_a[q]["ex"] == 0 and mv_x[q]["ex"] == 1)
    return {"delta": (x_pass - a_pass) / len(sub) * 100, "b": b, "c": c,
            "p": mcnemar_exact(b, c), "n": len(sub)}


def main():
    print("Cross-family B-A under majority vote (N=3, single McNemar)\n")
    print(f"{'Family':32s}{'Spatial Δ':>12s}{'p':>9s}"
          f"{'Robust Δ':>12s}{'p':>9s}{'Medium Δ':>12s}{'p':>9s}")
    print("-" * 95)
    for tex, run, fam in FAMILIES:
        A = load_samples(run, fam, "baseline")
        B = load_samples(run, fam, "full")
        if not A or not B:
            print(f"{tex:32s}  MISSING (A={len(A)} B={len(B)})")
            continue
        mv_a, mv_b = majority_vote(A), majority_vote(B)
        cells = {}
        for label, fn in SUBSETS:
            cells[label] = paired_mv(mv_a, mv_b, fn)
        sp, ro, me = cells["Spatial"], cells["Robust"], cells["Medium"]
        mark = "  <-- REGRESSION" if sp["delta"] < 0 and sp["p"] < 0.05 else (
               "  (neg n.s.)" if sp["delta"] < 0 else "")
        print(f"{tex:32s}{sp['delta']:>+11.2f} {sp['p']:>8.4f}"
              f"{ro['delta']:>+11.2f} {ro['p']:>8.4f}"
              f"{me['delta']:>+11.2f} {me['p']:>8.4f}{mark}")


if __name__ == "__main__":
    main()
