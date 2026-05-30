"""Sample remaining UNKNOWN classifications."""
import json, sys
from pathlib import Path
sys.path.insert(0, "D:/adk")
from data_agent.nl2sql_intent import classify_rule, IntentLabel

records = json.loads(Path("data_agent/nl2sql_eval_results/bird_pg_2026-05-01_182457/full_results.json").read_text(encoding="utf-8"))["records"]

unknowns = []
for r in records:
    res = classify_rule(r["question"])
    if res.primary == IntentLabel.UNKNOWN:
        unknowns.append(r)

print(f"Total UNKNOWN: {len(unknowns)}")
print(f"\nFirst 50 unknowns:\n")
for r in unknowns[:50]:
    print(f"  {r['question'][:100]}")
