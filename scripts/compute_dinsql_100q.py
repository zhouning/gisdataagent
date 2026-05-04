"""Compute DIN-SQL 100q vs Full McNemar + split Spatial/Robustness."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.nl2sql_bench_common.bootstrap_ci import wilson_ci
from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired

GIS_DIR = Path("data_agent/nl2sql_eval_results/cq_2026-05-04_122349")
DIN_DIR = Path("data_agent/nl2sql_eval_results/cq_din_sql_2026-05-04_151650")

base = json.loads((GIS_DIR / "baseline_results.json").read_text(encoding="utf-8"))
full = json.loads((GIS_DIR / "full_results.json").read_text(encoding="utf-8"))
din = json.loads((DIN_DIR / "results.json").read_text(encoding="utf-8"))

print("=" * 70)
print("DIN-SQL on GIS 100 — full breakdown")
print("=" * 70)

# Split records
def split_recs(records):
    spatial = [r for r in records if r.get("difficulty") != "Robustness"]
    robust = [r for r in records if r.get("difficulty") == "Robustness"]
    return spatial, robust

# Note: DIN-SQL records use "qid" (per run_din_sql.py)
# Confirm by inspecting first record
print(f"\nFirst DIN-SQL record keys: {list(din['records'][0].keys())}")

b_sp, b_rb = split_recs(base["records"])
f_sp, f_rb = split_recs(full["records"])
d_sp, d_rb = split_recs(din["records"])


def stats(records, label):
    n = len(records)
    s = sum(r.get("ex", 0) for r in records)
    if n == 0: return None
    lo, hi = wilson_ci(s, n)
    print(f"  {label:35s} n={n:3d}  EX={s/n:.3f}  [{lo:.3f}, {hi:.3f}]")
    return {"n": n, "s": s, "ex": s/n}


print("\n--- Overall (100q) ---")
stats(base["records"], "Baseline")
stats(full["records"], "Full")
stats(din["records"], "DIN-SQL")

print("\n--- Spatial (85q normal spatial-SQL) ---")
b_sp_s = stats(b_sp, "Baseline Spatial EX")
f_sp_s = stats(f_sp, "Full Spatial EX")
d_sp_s = stats(d_sp, "DIN-SQL Spatial EX")
print(f"  Full vs DIN-SQL: {f_sp_s['ex'] - d_sp_s['ex']:+.3f}")

print("\n--- Robustness (15q safety/refusal) ---")
b_rb_s = stats(b_rb, "Baseline Robustness")
f_rb_s = stats(f_rb, "Full Robustness")
d_rb_s = stats(d_rb, "DIN-SQL Robustness")

# Paired McNemar: Full vs DIN-SQL on Spatial 85q
print("\n--- McNemar: Full vs DIN-SQL on Spatial 85q ---")
f_qids = {r["qid"]: r["ex"] for r in f_sp}
d_qids = {r["qid"]: r["ex"] for r in d_sp}
common = sorted(set(f_qids) & set(d_qids))
mc = mcnemar_paired([d_qids[q] for q in common], [f_qids[q] for q in common])
print(f"  n={len(common)}, b={mc['b']} (DIN OK, Full ERR), c={mc['c']} (DIN ERR, Full OK)")
print(f"  p-value = {mc['p_value']:.4f}")
print(f"  Significant at α=0.05? {'YES' if mc['p_value'] < 0.05 else 'NO'}")

# McNemar: DIN-SQL vs Baseline on Spatial
print("\n--- McNemar: DIN-SQL vs Baseline on Spatial 85q ---")
b_qids = {r["qid"]: r["ex"] for r in b_sp}
common_bd = sorted(set(b_qids) & set(d_qids))
mc_bd = mcnemar_paired([b_qids[q] for q in common_bd], [d_qids[q] for q in common_bd])
print(f"  n={len(common_bd)}, b={mc_bd['b']}, c={mc_bd['c']}, p={mc_bd['p_value']:.4f}")
print(f"  Significant? {'YES' if mc_bd['p_value'] < 0.05 else 'NO'}")

# McNemar: Full vs DIN-SQL on Robustness 15q
print("\n--- McNemar: Full vs DIN-SQL on Robustness 15q ---")
f_qids_r = {r["qid"]: r["ex"] for r in f_rb}
d_qids_r = {r["qid"]: r["ex"] for r in d_rb}
common_r = sorted(set(f_qids_r) & set(d_qids_r))
mc_r = mcnemar_paired([d_qids_r[q] for q in common_r], [f_qids_r[q] for q in common_r])
print(f"  n={len(common_r)}, b={mc_r['b']}, c={mc_r['c']}, p={mc_r['p_value']:.4f}")
print(f"  Significant? {'YES' if mc_r['p_value'] < 0.05 else 'NO'}")
