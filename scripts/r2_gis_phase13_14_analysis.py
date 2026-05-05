"""Extract GIS cross-lingual 50q results from GIS 125q eval."""
import json, sqlite3
from pathlib import Path
import os

# Find latest cq_ dir
results_root = Path("D:/adk/data_agent/nl2sql_eval_results")
cq_dirs = sorted([d for d in results_root.iterdir() if d.is_dir() and d.name.startswith("cq_2026-05-05")],
                 key=lambda p: p.stat().st_mtime, reverse=True)
if not cq_dirs:
    print("No cq_ dirs found")
    exit(1)
latest = cq_dirs[0]
print(f"Using: {latest}")

db_path = latest / "run_state.db"
if not db_path.exists():
    print(f"No run_state.db in {latest}")
    exit(1)

conn = sqlite3.connect(str(db_path))
recs = [json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="full"').fetchall()]

# Filter non-Robustness questions (those are Chinese GIS NL→English SQL)
gis_cross = [r for r in recs if r.get("difficulty") in ("Easy", "Medium", "Hard")]
# Take first 50
gis_50 = gis_cross[:50]

n = len(gis_50)
ex = sum(r.get("ex", 0) for r in gis_50)
print(f"\n=== GIS Cross-Lingual 50q (Chinese NL -> English Schema SQL) ===")
print(f"EX = {ex}/{n} = {ex/n:.3f}" if n else "No questions")

# Robustness results
robust = [r for r in recs if r.get("difficulty") == "Robustness"]
r_n = len(robust)
r_ex = sum(r.get("ex", 0) for r in robust)
print(f"\n=== Robustness Expanded 40q ===")
print(f"Success rate = {r_ex}/{r_n} = {r_ex/r_n:.3f}" if r_n else "No robustness questions")

# By category
from collections import Counter
cat_stats = {}
for r in robust:
    cat = r.get("category", "?")
    cat_stats.setdefault(cat, [0, 0])
    cat_stats[cat][0] += 1
    cat_stats[cat][1] += r.get("ex", 0)
print("By category:")
for cat, (total, ok) in sorted(cat_stats.items()):
    print(f"  {cat}: {ok}/{total} = {ok/total:.3f}" if total else f"  {cat}: 0/0")
