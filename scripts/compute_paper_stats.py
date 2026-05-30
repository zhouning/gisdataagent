"""Compute bootstrap CIs and token-cost comparison for paper Tables."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci, format_with_ci

RUNS = {
    "GIS-baseline": "data_agent/nl2sql_eval_results/cq_2026-05-03_164213/baseline_results.json",
    "GIS-Full":     "data_agent/nl2sql_eval_results/cq_2026-05-03_164213/full_results.json",
    "GIS-DINSQL":   "data_agent/nl2sql_eval_results/cq_din_sql_2026-05-03_193407/results.json",
    "BIRD-baseline": "data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/baseline_results.json",
    "BIRD-Full":     "data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/full_results.json",
    "BIRD-DINSQL":   "data_agent/nl2sql_eval_results/bird_din_sql_2026-05-03_193412/results.json",
}

print("=" * 70)
print(f"{'Run':25s}  {'N':>5s}  {'EX':>10s}  {'95% CI':>20s}  {'mean tokens':>12s}")
print("=" * 70)
for name, path in RUNS.items():
    p = Path(path)
    if not p.exists():
        print(f"{name:25s}  MISSING: {path}")
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    records = d.get("records", [])
    if not records:
        print(f"{name:25s}  no records")
        continue
    n = len(records)
    ex_outcomes = [r.get("ex", 0) for r in records]
    successes = sum(ex_outcomes)
    ex_pct = successes / n
    lo, hi = wilson_ci(successes, n)
    tokens = [r.get("tokens", 0) for r in records if r.get("tokens", 0)]
    mean_tok = sum(tokens) / len(tokens) if tokens else 0
    print(f"{name:25s}  {n:>5d}  {ex_pct:>10.3f}  [{lo:.3f}, {hi:.3f}]  {mean_tok:>10.0f}")

# Per-difficulty breakdown for BIRD
print()
print("=" * 70)
print("BIRD 500 per-difficulty CI")
print("=" * 70)
for name, path in [("baseline", "data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/baseline_results.json"),
                   ("Full", "data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/full_results.json"),
                   ("DIN-SQL", "data_agent/nl2sql_eval_results/bird_din_sql_2026-05-03_193412/results.json")]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    by_diff = {}
    for r in d["records"]:
        diff = r.get("difficulty", "?")
        by_diff.setdefault(diff, []).append(r.get("ex", 0))
    print(f"\n{name}:")
    for diff in sorted(by_diff):
        out = by_diff[diff]
        n = len(out)
        s = sum(out)
        lo, hi = wilson_ci(s, n)
        print(f"  {diff:13s} n={n:3d}  EX={s/n:.3f}  [{lo:.3f}, {hi:.3f}]")

# GIS per-difficulty breakdown
print()
print("=" * 70)
print("GIS 20 per-difficulty CI")
print("=" * 70)
for name, path in [("baseline", "data_agent/nl2sql_eval_results/cq_2026-05-03_164213/baseline_results.json"),
                   ("Full", "data_agent/nl2sql_eval_results/cq_2026-05-03_164213/full_results.json"),
                   ("DIN-SQL", "data_agent/nl2sql_eval_results/cq_din_sql_2026-05-03_193407/results.json")]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    by_diff = {}
    for r in d["records"]:
        diff = r.get("difficulty", "?")
        by_diff.setdefault(diff, []).append(r.get("ex", 0))
    print(f"\n{name}:")
    for diff in sorted(by_diff):
        out = by_diff[diff]
        n = len(out)
        s = sum(out)
        lo, hi = wilson_ci(s, n)
        print(f"  {diff:13s} n={n:3d}  EX={s/n:.3f}  [{lo:.3f}, {hi:.3f}]")
