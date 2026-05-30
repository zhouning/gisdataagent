"""Authoritative single-source-of-truth recompute for v7.

Resolves the two-batch contradiction in v6 by recomputing every headline
number under ONE uniform convention:

  * All three conditions (A/B/C) at N=3 (truncate A,C to first 3 samples).
  * Per-question MAJORITY VOTE across the 3 samples (ex_mv = 1 iff >=2/3 pass).
  * A SINGLE McNemar exact two-sided test on the majority-voted per-question
    table (not pooled across samples -- this addresses the Codex concern that
    pooling repeated observations inflates significance).

Outputs both the new authoritative numbers AND the old pooled numbers so the
audit report can show old -> new for every cell.

Zero quota -- reads only existing jsonl.
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

A_RUN = ROOT / "data_agent/nl2sql_eval_results/v7_gemini35_minimod_n3_20260524"
B_RUN = ROOT / "data_agent/nl2sql_eval_results/v7_gemini35_recheck_n3_2026-05-22_095253"
C_RUN = A_RUN
FAMILY = "gemini-3.5-flash"

SUBSETS = [
    ("Overall (125q)", lambda r: True),
    ("Robustness (40q)", lambda r: r.get("difficulty") == "Robustness"),
    ("Spatial (85q)", lambda r: r.get("difficulty") != "Robustness"),
    ("Easy (24q)", lambda r: r.get("difficulty") == "Easy"),
    ("Medium (36q)", lambda r: r.get("difficulty") == "Medium"),
    ("Hard (25q)", lambda r: r.get("difficulty") == "Hard"),
]


def load_samples(run_dir: Path, family: str, mode: str, cap: int = 3):
    fam_dir = run_dir / family
    out = []
    for sd in sorted(fam_dir.glob("sample_*"),
                     key=lambda p: int(p.name.split("_")[1])):
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
    """Return {qid: {'ex': mv, 'difficulty': ...}} via >=2/3 majority."""
    votes = defaultdict(list)
    meta = {}
    for recs in samples:
        for r in recs:
            votes[r["qid"]].append(r["ex"])
            meta[r["qid"]] = r
    out = {}
    for qid, vs in votes.items():
        mv = 1 if sum(vs) * 2 >= len(vs) else 0  # >=50% passes -> majority
        # strict majority: >=2 of 3
        mv = 1 if sum(vs) > len(vs) / 2 else 0
        out[qid] = {"ex": mv, "difficulty": meta[qid].get("difficulty", "?"),
                    "category": meta[qid].get("category", "?")}
    return out


def mcnemar_exact(b: int, c: int):
    """Two-sided exact binomial McNemar."""
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p": 1.0}
    k = min(b, c)
    # two-sided: 2 * sum_{i=0}^{k} C(n,i) 0.5^n, capped at 1
    s = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return {"b": b, "c": c, "p": min(1.0, 2 * s)}


def mv_rate(mv_table, filter_fn):
    sub = [v["ex"] for q, v in mv_table.items() if filter_fn(v)]
    if not sub:
        return None, 0
    return sum(sub) / len(sub) * 100, len(sub)


def paired_mv(mv_a, mv_x, filter_fn):
    """Single McNemar on majority-voted per-question tables."""
    common = set(mv_a) & set(mv_x)
    sub = [q for q in common if filter_fn(mv_a[q])]
    a_pass = sum(mv_a[q]["ex"] for q in sub)
    x_pass = sum(mv_x[q]["ex"] for q in sub)
    b = sum(1 for q in sub if mv_a[q]["ex"] == 1 and mv_x[q]["ex"] == 0)
    c = sum(1 for q in sub if mv_a[q]["ex"] == 0 and mv_x[q]["ex"] == 1)
    mc = mcnemar_exact(b, c)
    delta = (x_pass - a_pass) / len(sub) * 100 if sub else 0.0
    return {"delta": delta, "n": len(sub), **mc}


def main():
    print("=" * 78)
    print("AUTHORITATIVE RECOMPUTE (uniform N=3, per-question majority vote)")
    print("=" * 78)

    A = load_samples(A_RUN, FAMILY, "baseline", cap=3)
    B = load_samples(B_RUN, FAMILY, "full", cap=3)
    C = load_samples(C_RUN, FAMILY, "full", cap=3)
    print(f"\nLoaded samples: A={len(A)}  B={len(B)}  C={len(C)} "
          f"(all capped to N=3)\n")

    mv_a = majority_vote(A)
    mv_b = majority_vote(B)
    mv_c = majority_vote(C)

    print(f"{'Subset':18s}{'A%':>8s}{'B%':>8s}{'C%':>8s}"
          f"{'B-A':>9s}{'p(B-A)':>9s}{'C-B':>9s}{'p(C-B)':>9s}"
          f"{'C-A':>9s}{'p(C-A)':>9s}")
    print("-" * 96)
    table = {}
    for label, fn in SUBSETS:
        ra, _ = mv_rate(mv_a, fn)
        rb, _ = mv_rate(mv_b, fn)
        rc, _ = mv_rate(mv_c, fn)
        ba = paired_mv(mv_a, mv_b, fn)
        cb = paired_mv(mv_b, mv_c, fn)
        ca = paired_mv(mv_a, mv_c, fn)
        table[label] = {"A": ra, "B": rb, "C": rc,
                        "BA": ba, "CB": cb, "CA": ca}
        print(f"{label:18s}{ra:>7.1f} {rb:>7.1f} {rc:>7.1f}"
              f"{ba['delta']:>+8.2f} {ba['p']:>8.4f}"
              f"{cb['delta']:>+8.2f} {cb['p']:>8.4f}"
              f"{ca['delta']:>+8.2f} {ca['p']:>8.4f}")

    print("\n" + "=" * 78)
    print("KEY HEADLINE NUMBERS (new authoritative vs v6 reported)")
    print("=" * 78)
    sp = table["Spatial (85q)"]
    ro = table["Robustness (40q)"]
    ov = table["Overall (125q)"]
    print(f"Spatial B-A   : NEW {sp['BA']['delta']:+.2f} (p={sp['BA']['p']:.4f}, "
          f"b/c={sp['BA']['b']}/{sp['BA']['c']})   "
          f"v6 reported: -12.16 (N=3 tab4) / -12.55 (pooled tab2)")
    print(f"Robust  B-A   : NEW {ro['BA']['delta']:+.2f} (p={ro['BA']['p']:.4f})   "
          f"v6 reported: +30.83 (tab4) / +29.17 (pooled tab2)")
    print(f"Overall B-A   : NEW {ov['BA']['delta']:+.2f} (p={ov['BA']['p']:.4f})   "
          f"v6 reported: +1.60 (tab4) / +0.80 (pooled tab2)")
    print(f"Spatial C-B   : NEW {sp['CB']['delta']:+.2f} (p={sp['CB']['p']:.4f})   "
          f"v6 reported: +5.88 (p=0.063)")
    print(f"Spatial C-A   : NEW {sp['CA']['delta']:+.2f} (p={sp['CA']['p']:.4f})   "
          f"v6 reported: -6.59 / +5.28 aggregate")


if __name__ == "__main__":
    main()
