"""Diagnose HARD_01 (proximity buffer) regression."""
import json, sys
from pathlib import Path
sys.path.insert(0, "D:/adk")
from data_agent.nl2sql_intent import classify_rule, classify_intent, IntentLabel

# Find HARD_01 question
records = json.loads(Path("data_agent/nl2sql_eval_results/cq_2026-05-03_164213/full_results.json").read_text(encoding="utf-8"))["records"]
hard_01 = next(r for r in records if r["qid"] == "CQ_GEO_HARD_01")
print("HARD_01 question:", hard_01["question"])
print("HARD_01 gold SQL:", hard_01["gold_sql"][:500])
print()
print("HARD_01 pred SQL (full pipeline ERR):", hard_01["pred_sql"][:500])
print()
print("HARD_01 reason:", hard_01.get("reason", ""))
print()
res = classify_rule(hard_01["question"])
print(f"classify_rule: primary={res.primary.value} secondary={[s.value for s in res.secondary]} confidence={res.confidence}")

# Compare with baseline
base = json.loads(Path("data_agent/nl2sql_eval_results/cq_2026-05-03_164213/baseline_results.json").read_text(encoding="utf-8"))["records"]
hb = next(r for r in base if r["qid"] == "CQ_GEO_HARD_01")
print()
print("HARD_01 baseline ex:", hb["ex"], "pred SQL:", hb["pred_sql"][:300])
