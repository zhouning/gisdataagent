"""Delete full-mode cache entries for both-fail QIDs so they get re-evaluated."""
import sqlite3, json

DB = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db"
conn = sqlite3.connect(DB)

base = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="baseline"').fetchall()}
full = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="full"').fetchall()}

both_fail = [q for q in sorted(base) if q in full and base[q].get("ex")==0 and full[q].get("ex")==0]

# Also delete regressions (base OK, full ERR) to see if we fix them
regressions = [q for q in sorted(base) if q in full and base[q].get("ex")==1 and full[q].get("ex")==0]

to_delete = both_fail + regressions
print(f"Deleting {len(to_delete)} full-mode cache entries ({len(both_fail)} both-fail + {len(regressions)} regressions)")

for qid in to_delete:
    conn.execute("DELETE FROM done WHERE qid=? AND mode='full'", (qid,))
conn.commit()

# Verify
remaining = conn.execute("SELECT count(*) FROM done WHERE mode='full'").fetchone()[0]
print(f"Remaining full cache entries: {remaining} (should be {108 - len(to_delete)})")
conn.close()
