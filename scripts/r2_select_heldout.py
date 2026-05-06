"""Select BIRD held-out question IDs not in the original 108q R2 set.

The R2 grounding rules were designed based on error attribution of the 108q set,
so reporting significance on the same 108q set has a test-set tuning risk
(Reviewer B's concern). This script selects held-out question IDs disjoint from
the 108q set for an independent evaluation.
"""
import sqlite3
import json
from pathlib import Path

# Original R2 evaluation: which qids are in it?
R2_DB = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db"
conn = sqlite3.connect(R2_DB)
r2_qids = {r[0] for r in conn.execute("SELECT DISTINCT qid FROM done").fetchall()}
print(f"R2 evaluated qids: {len(r2_qids)} (e.g., {sorted(r2_qids)[:5]}..{sorted(r2_qids)[-5:]})")

# BIRD mini_dev PostgreSQL questions
BIRD_JSON = Path("D:/adk/data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/mini_dev_postgresql.json")
all_questions = json.loads(BIRD_JSON.read_text(encoding="utf-8"))
print(f"Total BIRD mini_dev PG questions: {len(all_questions)}")

# Held-out = all qids not in R2 set
by_id = {q["question_id"]: q for q in all_questions}
held_out_qids = sorted(set(by_id.keys()) - r2_qids)
print(f"Held-out candidates: {len(held_out_qids)}")

# Distribution
from collections import Counter
diff_counts = Counter(by_id[q].get("difficulty", "?") for q in held_out_qids)
db_counts = Counter(by_id[q].get("db_id", "?") for q in held_out_qids)
print(f"Difficulty breakdown:")
for d, n in diff_counts.most_common():
    print(f"  {d}: {n}")
print(f"DB breakdown (top 5):")
for db, n in db_counts.most_common(5):
    print(f"  {db}: {n}")

# Pick a balanced 150q held-out: sample proportionally across difficulty
import random
random.seed(42)

target_size = 150
pick = []
# Proportional sampling
for diff, count in diff_counts.most_common():
    diff_qids = [q for q in held_out_qids if by_id[q].get("difficulty") == diff]
    take = min(len(diff_qids), round(target_size * count / len(held_out_qids)))
    pick.extend(random.sample(diff_qids, take))

pick = sorted(pick)
print(f"\nSelected {len(pick)} held-out qids for BIRD R2 independent evaluation.")
print(f"Sample: {pick[:10]} ... {pick[-5:]}")

# Save
out_path = Path("D:/adk/data_agent/nl2sql_eval_results/bird_heldout_qids.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(pick, indent=2), encoding="utf-8")
print(f"Saved to {out_path}")
