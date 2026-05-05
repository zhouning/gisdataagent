"""Drill into thrombosis both-fail."""
import sqlite3, json
DB = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db"
conn = sqlite3.connect(DB)
base = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="baseline"').fetchall()}
full = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="full"').fetchall()}

both_fail_thrombosis = [q for q in sorted(base) if q in full and base[q].get("ex")==0 and full[q].get("ex")==0 and base[q].get("db_id")=="thrombosis_prediction"]

print(f"# both-fail thrombosis: {len(both_fail_thrombosis)}\n")
for qid in both_fail_thrombosis:
    r, f = base[qid], full[qid]
    print(f"QID {qid} [{r.get('difficulty','?')}]")
    print(f"  Q: {r.get('question','')}")
    print(f"  GOLD: {r.get('gold_sql','')}")
    print(f"  FULL_PRED: {f.get('pred_sql','')}")
    print(f"  FULL_ERR: {(f.get('error') or '')[:250]}")
    print()
