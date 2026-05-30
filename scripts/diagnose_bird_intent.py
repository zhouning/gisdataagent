"""Diagnose intent classification on BIRD English questions."""
import json
from pathlib import Path
from collections import Counter
import sys
sys.path.insert(0, "D:/adk")

from data_agent.nl2sql_intent import classify_rule, IntentLabel

# Load BIRD questions
records = json.loads(Path("data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/full_results.json").read_text(encoding="utf-8"))["records"]

# Sample 30 English questions
sample = records[:30]
print(f"Sample of {len(sample)} BIRD questions through current classify_rule:\n")
for r in sample:
    res = classify_rule(r["question"])
    print(f"  {r['qid']:>5} ({r.get('difficulty', '?'):11s}) -> {res.primary.value:20s} : {r['question'][:80]}")

# Distribution
print("\n\nClassification distribution on full 500 BIRD:")
dist = Counter()
for r in records:
    res = classify_rule(r["question"])
    dist[res.primary.value] += 1
for k, v in dist.most_common():
    print(f"  {k:20s}: {v}")
