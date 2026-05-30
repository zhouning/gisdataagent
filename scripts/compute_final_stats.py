"""Compute ALL final stats for the paper: CI, McNemar, token cost, ablation."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci, format_with_ci
from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired

RUNS = {
    # GIS 100
    "GIS100-baseline": "data_agent/nl2sql_eval_results/cq_2026-05-04_122349/baseline_results.json",
    "GIS100-Full":     "data_agent/nl2sql_eval_results/cq_2026-05-04_122349/full_results.json",
    "GIS20-DINSQL":    "data_agent/nl2sql_eval_results/cq_din_sql_2026-05-03_193407/results.json",
    # BIRD 500
    "BIRD-baseline":   "data_agent/nl2sql_eval_results/bird_pg_2026-05-04_093040/baseline_results.json",
    "BIRD-Full":       "data_agent/nl2sql_eval_results/bird_pg_2026-05-04_093040/full_results.json",
    "BIRD-DINSQL":     "data_agent/nl2sql_eval_results/bird_din_sql_2026-05-03_193412/results.json",
}

print("=" * 80)
print(f"{'Run':25s}  {'N':>5s}  {'EX':>8s}  {'95% CI':>20s}  {'Valid':>6s}  {'mean tok':>10s}")
print("=" * 80)
for name, path in RUNS.items():
    p = Path(path)
    if not p.exists():
        print(f"{name:25s}  MISSING")
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    records = d.get("records", [])
    n = len(records)
    ex_sum = sum(r.get("ex", 0) for r in records)
    valid_sum = sum(r.get("valid", 0) for r in records)
    lo, hi = wilson_ci(ex_sum, n)
    tokens = [r.get("tokens", 0) for r in records if r.get("tokens", 0)]
    mean_tok = sum(tokens) / len(tokens) if tokens else 0
    print(f"{name:25s}  {n:>5d}  {ex_sum/n:>8.3f}  [{lo:.3f}, {hi:.3f}]  {valid_sum/n:>6.3f}  {mean_tok:>10.0f}")

# McNemar: GIS 100 baseline vs full
print("\n" + "=" * 80)
print("McNemar Tests")
print("=" * 80)

gis_base = json.loads(Path(RUNS["GIS100-baseline"]).read_text(encoding="utf-8"))
gis_full = json.loads(Path(RUNS["GIS100-Full"]).read_text(encoding="utf-8"))
base_qids = {r["qid"]: r["ex"] for r in gis_base["records"]}
full_qids = {r["qid"]: r["ex"] for r in gis_full["records"]}
common = sorted(set(base_qids) & set(full_qids))
mc = mcnemar_paired([base_qids[q] for q in common], [full_qids[q] for q in common])
print(f"\nGIS 100 (baseline vs full): n={len(common)}, b={mc['b']}, c={mc['c']}, p={mc['p_value']:.4f}")
print(f"  Significant at 0.05? {'YES' if mc['p_value'] < 0.05 else 'NO'}")

# McNemar: BIRD baseline vs full
bird_base = json.loads(Path(RUNS["BIRD-baseline"]).read_text(encoding="utf-8"))
bird_full = json.loads(Path(RUNS["BIRD-Full"]).read_text(encoding="utf-8"))
bb = {r["qid"]: r["ex"] for r in bird_base["records"]}
bf = {r["qid"]: r["ex"] for r in bird_full["records"]}
common_b = sorted(set(bb) & set(bf))
mc_b = mcnemar_paired([bb[q] for q in common_b], [bf[q] for q in common_b])
print(f"\nBIRD ~495 (baseline vs full): n={len(common_b)}, b={mc_b['b']}, c={mc_b['c']}, p={mc_b['p_value']:.4f}")
print(f"  Significant at 0.05? {'YES' if mc_b['p_value'] < 0.05 else 'NO'}")

# McNemar: BIRD full vs DIN-SQL
bird_din = json.loads(Path(RUNS["BIRD-DINSQL"]).read_text(encoding="utf-8"))
bd = {r["qid"]: r["ex"] for r in bird_din["records"]}
common_d = sorted(set(bf) & set(bd))
mc_d = mcnemar_paired([bd[q] for q in common_d], [bf[q] for q in common_d])
print(f"\nBIRD ~495 (DIN-SQL vs full): n={len(common_d)}, b={mc_d['b']}, c={mc_d['c']}, p={mc_d['p_value']:.4f}")
print(f"  Significant at 0.05? {'YES' if mc_d['p_value'] < 0.05 else 'NO'}")

# Per-difficulty for GIS 100
print("\n" + "=" * 80)
print("GIS 100 per-difficulty")
print("=" * 80)
for name, data in [("baseline", gis_base), ("Full", gis_full)]:
    by_diff = {}
    for r in data["records"]:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r.get("ex", 0)
    print(f"\n{name}:")
    for d in sorted(by_diff):
        n, c = by_diff[d]
        lo, hi = wilson_ci(c, n)
        print(f"  {d:13s} n={n:3d}  EX={c/n:.3f}  [{lo:.3f}, {hi:.3f}]")

# Token cost comparison
print("\n" + "=" * 80)
print("Token Cost Summary")
print("=" * 80)
for name, path in RUNS.items():
    p = Path(path)
    if not p.exists():
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    tokens = [r.get("tokens", 0) for r in d["records"] if r.get("tokens", 0)]
    if tokens:
        print(f"  {name:25s}  mean={sum(tokens)/len(tokens):>8.0f}  median={sorted(tokens)[len(tokens)//2]:>8.0f}  total={sum(tokens):>12,}")
    else:
        print(f"  {name:25s}  (no token data)")
