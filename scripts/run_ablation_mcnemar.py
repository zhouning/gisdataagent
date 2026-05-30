"""Run ablation + McNemar analysis for the paper."""
import json, sys
sys.path.insert(0, "D:/adk")
from collections import Counter
from scripts.nl2sql_bench_common.derive_ablation import derive_ablation
from scripts.nl2sql_bench_common.mcnemar import mcnemar_paired

GIS_DIR = "data_agent/nl2sql_eval_results/cq_2026-05-03_164213"
BIRD_DIR = "data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457"

# ---- GIS 20 ----
gis_base = json.load(open(f"{GIS_DIR}/baseline_results.json", encoding="utf-8"))
gis_full = json.load(open(f"{GIS_DIR}/full_results.json", encoding="utf-8"))

print("=" * 60)
print("GIS 20 — Intent Distribution (full)")
print("=" * 60)
intents = Counter(r.get("intent") for r in gis_full["records"])
for k, v in intents.most_common():
    print(f"  {k}: {v}")

print("\n" + "=" * 60)
print("GIS 20 — Ablation (drop each intent from full)")
print("=" * 60)
all_intents = sorted(set(r.get("intent") for r in gis_full["records"] if r.get("intent")))
full_ex = sum(r["ex"] for r in gis_full["records"]) / len(gis_full["records"])
print(f"  FULL (all intents): n=20, EX={full_ex:.4f}")
for intent in all_intents:
    res = derive_ablation(f"{GIS_DIR}/full_results.json", drop_intent=intent)
    delta = res["execution_accuracy"] - full_ex
    print(f"  drop {intent}: n={res['n']}, EX={res['execution_accuracy']:.4f} (delta={delta:+.4f})")

print("\n" + "=" * 60)
print("GIS 20 — McNemar (baseline vs full)")
print("=" * 60)
base_qids = {r["qid"]: r["ex"] for r in gis_base["records"]}
full_qids = {r["qid"]: r["ex"] for r in gis_full["records"]}
common = sorted(set(base_qids) & set(full_qids))
base_vec = [base_qids[q] for q in common]
full_vec = [full_qids[q] for q in common]
mc = mcnemar_paired(base_vec, full_vec)
print(f"  n={len(common)}, b={mc['b']} (base OK, full ERR), c={mc['c']} (base ERR, full OK)")
print(f"  p-value = {mc['p_value']:.4f}")
print(f"  Significant at 0.05? {'YES' if mc['p_value'] < 0.05 else 'NO'}")

# Per-question discordant pairs
print("\n  Discordant pairs:")
for q in common:
    b, f = base_qids[q], full_qids[q]
    if b != f:
        direction = "base OK -> full ERR" if b == 1 else "base ERR -> full OK"
        intent = next((r.get("intent", "?") for r in gis_full["records"] if r["qid"] == q), "?")
        print(f"    {q}: {direction} (intent={intent})")

# ---- BIRD 500 ----
print("\n" + "=" * 60)
print("BIRD 500 — McNemar (baseline vs full)")
print("=" * 60)
bird_base = json.load(open(f"{BIRD_DIR}/baseline_results.json", encoding="utf-8"))
bird_full = json.load(open(f"{BIRD_DIR}/full_results.json", encoding="utf-8"))
bb_qids = {r["qid"]: r["ex"] for r in bird_base["records"]}
bf_qids = {r["qid"]: r["ex"] for r in bird_full["records"]}
common_b = sorted(set(bb_qids) & set(bf_qids))
base_b = [bb_qids[q] for q in common_b]
full_b = [bf_qids[q] for q in common_b]
mc_b = mcnemar_paired(base_b, full_b)
print(f"  n={len(common_b)}, b={mc_b['b']} (base OK, full ERR), c={mc_b['c']} (base ERR, full OK)")
print(f"  p-value = {mc_b['p_value']:.4f}")
print(f"  Significant at 0.05? {'YES' if mc_b['p_value'] < 0.05 else 'NO'}")

print("\n" + "=" * 60)
print("BIRD 500 — Per-difficulty breakdown")
print("=" * 60)
for mode, data in [("baseline", bird_base), ("full", bird_full)]:
    by_diff = {}
    for r in data["records"]:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r["ex"]
    print(f"  {mode}: EX={data['summary']['execution_accuracy']}")
    for d in sorted(by_diff):
        n, c = by_diff[d]
        print(f"    {d}: {c}/{n} = {c/n:.3f}")
