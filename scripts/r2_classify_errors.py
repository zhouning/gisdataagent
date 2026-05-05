"""Classify both-fail error patterns."""
import sqlite3, json
from collections import Counter

DB = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db"
conn = sqlite3.connect(DB)
base = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="baseline"').fetchall()}
full = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="full"').fetchall()}

both_fail = [q for q in sorted(base) if q in full and base[q].get("ex")==0 and full[q].get("ex")==0]

patterns = Counter()
for qid in both_fail:
    gold = base[qid].get("gold_sql", "").upper()
    pred = full[qid].get("pred_sql", "").upper()

    # Check DISTINCT mismatch
    gold_has_distinct = "SELECT DISTINCT" in gold or "COUNT(DISTINCT" in gold
    pred_has_distinct = "SELECT DISTINCT" in pred or "COUNT(DISTINCT" in pred

    # Check if pred is very similar to gold (just DISTINCT diff)
    gold_no_distinct = gold.replace("DISTINCT ", "").replace("DISTINCT\n", "")
    pred_no_distinct = pred.replace("DISTINCT ", "").replace("DISTINCT\n", "")

    # Check date handling
    has_date_issue = ("BIRTHDAY" in gold or "DATE" in gold or "EXAMINATION DATE" in gold) and ("SUBSTRING" in pred or "CAST" in pred)

    # Check wrong table
    gold_tables = set()
    pred_tables = set()
    for word in gold.split():
        if word in ("PATIENT", "LABORATORY", "EXAMINATION"):
            gold_tables.add(word)
    for word in pred.split():
        if word in ("PATIENT", "LABORATORY", "EXAMINATION"):
            pred_tables.add(word)
    wrong_table = pred_tables != gold_tables

    # Check aggregation mismatch
    agg_mismatch = ("COUNT(*)" in gold and "COUNT(DISTINCT" in pred) or ("COUNT(DISTINCT" in gold and "COUNT(*)" in pred)

    # Classify
    if gold_has_distinct != pred_has_distinct:
        patterns["DISTINCT_mismatch"] += 1
    elif agg_mismatch:
        patterns["aggregation_mismatch"] += 1
    elif wrong_table:
        patterns["wrong_table_join"] += 1
    elif has_date_issue:
        patterns["date_handling"] += 1
    else:
        patterns["other"] += 1

print("=== BOTH-FAIL ERROR PATTERN CLASSIFICATION ===")
print(f"Total both-fail: {len(both_fail)}")
for pat, cnt in patterns.most_common():
    print(f"  {pat}: {cnt}")

# Now check: how many both-fail would pass if we ignore DISTINCT?
print("\n=== DISTINCT-ONLY FAILURES (pred matches gold semantically) ===")
for qid in both_fail:
    gold = base[qid].get("gold_sql", "")
    pred = full[qid].get("pred_sql", "")
    # Simple heuristic: if removing DISTINCT from both makes them very similar
    g = gold.upper().replace("DISTINCT ", "").strip()
    p = pred.upper().replace("DISTINCT ", "").strip()
    # Check if first 80 chars match after normalization
    g_norm = " ".join(g.split())
    p_norm = " ".join(p.split())
    if g_norm[:80] == p_norm[:80] and g_norm[:80]:
        print(f"  QID {qid}: likely DISTINCT-only diff")
