"""Compute split GIS 100 stats: Spatial EX (85q) vs Robustness Success (15q)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci
from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired

GIS_DIR = Path("data_agent/nl2sql_eval_results/cq_2026-05-04_122349")
base = json.loads((GIS_DIR / "baseline_results.json").read_text(encoding="utf-8"))
full = json.loads((GIS_DIR / "full_results.json").read_text(encoding="utf-8"))


def split_records(records):
    spatial = [r for r in records if r.get("difficulty") != "Robustness"]
    robust = [r for r in records if r.get("difficulty") == "Robustness"]
    return spatial, robust


def stats(records, label):
    n = len(records)
    s = sum(r.get("ex", 0) for r in records)
    if n == 0:
        return None
    lo, hi = wilson_ci(s, n)
    print(f"  {label:35s} n={n:3d}  EX={s/n:.3f}  [{lo:.3f}, {hi:.3f}]")
    return {"n": n, "s": s, "ex": s/n, "ci": (lo, hi)}


print("=" * 70)
print("GIS 100 — Split into Spatial EX vs Robustness Success Rate")
print("=" * 70)

print("\n--- Spatial EX (85 normal spatial-SQL questions) ---")
b_sp, b_rb = split_records(base["records"])
f_sp, f_rb = split_records(full["records"])
b_sp_stats = stats(b_sp, "Baseline Spatial EX")
f_sp_stats = stats(f_sp, "Full Spatial EX")
delta_sp = f_sp_stats["ex"] - b_sp_stats["ex"]
print(f"  Delta = {delta_sp:+.3f}")

print("\n--- Robustness Success Rate (15 safety/refusal questions) ---")
b_rb_stats = stats(b_rb, "Baseline Robustness Success")
f_rb_stats = stats(f_rb, "Full Robustness Success")
delta_rb = f_rb_stats["ex"] - b_rb_stats["ex"]
print(f"  Delta = {delta_rb:+.3f}")

# Paired McNemar on Spatial only
print("\n--- McNemar on Spatial (85q) ---")
b_qids = {r["qid"]: r["ex"] for r in b_sp}
f_qids = {r["qid"]: r["ex"] for r in f_sp}
common = sorted(set(b_qids) & set(f_qids))
mc = mcnemar_paired([b_qids[q] for q in common], [f_qids[q] for q in common])
print(f"  n={len(common)}, b={mc['b']} (base OK, full ERR), c={mc['c']} (base ERR, full OK)")
print(f"  p-value = {mc['p_value']:.4f}")
print(f"  Significant at α=0.05? {'YES' if mc['p_value'] < 0.05 else 'NO'}")

print("\n--- McNemar on Robustness (15q) ---")
b_qids_r = {r["qid"]: r["ex"] for r in b_rb}
f_qids_r = {r["qid"]: r["ex"] for r in f_rb}
common_r = sorted(set(b_qids_r) & set(f_qids_r))
mc_r = mcnemar_paired([b_qids_r[q] for q in common_r], [f_qids_r[q] for q in common_r])
print(f"  n={len(common_r)}, b={mc_r['b']}, c={mc_r['c']}")
print(f"  p-value = {mc_r['p_value']:.4f}")
print(f"  Significant at α=0.05? {'YES' if mc_r['p_value'] < 0.05 else 'NO'}")

# Per-difficulty breakdown for Spatial
print("\n--- Spatial 85q per-difficulty ---")
for label, recs in [("Baseline", b_sp), ("Full", f_sp)]:
    by_diff = {}
    for r in recs:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r.get("ex", 0)
    print(f"\n  {label}:")
    for d in sorted(by_diff):
        n, c = by_diff[d]
        lo, hi = wilson_ci(c, n)
        print(f"    {d:13s} n={n:3d}  EX={c/n:.3f}  [{lo:.3f}, {hi:.3f}]")
