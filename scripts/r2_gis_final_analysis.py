"""Analyze GIS 125q eval results (Phase 1.3 GIS + Phase 1.4 Robustness)."""
import json
from pathlib import Path
from collections import Counter

RESULTS = Path("D:/adk/data_agent/nl2sql_eval_results/cq_2026-05-05_230059/full_results.json")
data = json.loads(RESULTS.read_text(encoding="utf-8"))
recs = data["records"]
summary = data["summary"]

print(f"=== Overall: {summary} ===\n")

# Phase 1.3: GIS Cross-Lingual 50q (non-Robustness)
gis_cross = [r for r in recs if r.get("difficulty") in ("Easy", "Medium", "Hard")]
gis_50 = gis_cross[:50]
gis_85 = gis_cross[:85]  # as in paper
n, ex = len(gis_50), sum(r.get("ex", 0) for r in gis_50)
n85, ex85 = len(gis_85), sum(r.get("ex", 0) for r in gis_85)
print(f"=== Phase 1.3: GIS Cross-Lingual 50q (Chinese NL -> PostGIS SQL) ===")
print(f"EX = {ex}/{n} = {ex/n:.3f}")
print(f"(Full 85q for paper comparison: EX = {ex85}/{n85} = {ex85/n85:.3f})")

# Phase 1.4: Robustness 40q
robust = [r for r in recs if r.get("difficulty") == "Robustness"]
rn, rex = len(robust), sum(r.get("ex", 0) for r in robust)
print(f"\n=== Phase 1.4: Robustness 40q ===")
print(f"Success rate = {rex}/{rn} = {rex/rn:.3f}")

# By category
cat_stats = {}
for r in robust:
    cat = r.get("category", "?")
    cat_stats.setdefault(cat, [0, 0])
    cat_stats[cat][0] += 1
    cat_stats[cat][1] += r.get("ex", 0)
print("By category:")
for cat in sorted(cat_stats):
    total, ok = cat_stats[cat]
    print(f"  {cat}: {ok}/{total} = {ok/total:.3f}")

# Failed robustness cases
print("\n=== Robustness failures ===")
for r in robust:
    if not r.get("ex"):
        print(f"  {r.get('id','?')} [{r.get('category','?')}]: {r.get('question','')[:80]}")
        print(f"    pred: {(r.get('pred_sql') or '')[:120]}")
