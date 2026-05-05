"""Round 2 error attribution analysis."""
import sqlite3, json
from scipy.stats import binomtest

DB = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db"
conn = sqlite3.connect(DB)
base = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="baseline"').fetchall()}
full = {r[0]: json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="full"').fetchall()}

paired = sorted(set(base) & set(full))
b_ex = sum(1 for q in paired if base[q].get("ex") == 1)
f_ex = sum(1 for q in paired if full[q].get("ex") == 1)
b_only = [q for q in paired if base[q].get("ex") == 1 and full[q].get("ex") == 0]
f_only = [q for q in paired if base[q].get("ex") == 0 and full[q].get("ex") == 1]
both_fail = [q for q in paired if base[q].get("ex") == 0 and full[q].get("ex") == 0]

print(f"Paired: {len(paired)}, Base EX: {b_ex}/{len(paired)}={b_ex/len(paired):.3f}, Full EX: {f_ex}/{len(paired)}={f_ex/len(paired):.3f}")
print(f"Discordant: b(base-ok,full-err)={len(b_only)}, c(base-err,full-ok)={len(f_only)}")
print(f"Both fail: {len(both_fail)}")

n = len(b_only) + len(f_only)
k = len(f_only)
p = binomtest(k, n, 0.5, alternative="greater").pvalue
print(f"McNemar (1-sided): n={n}, k={k}, p={p:.4f}")

print("\n=== REGRESSIONS (b: base OK -> full ERR) ===")
for qid in sorted(b_only):
    r, f = base[qid], full[qid]
    print(f"QID {qid} [{r.get('db_id','?')}, {r.get('difficulty','?')}]")
    print(f"  Q: {r.get('question','')[:120]}")
    print(f"  GOLD: {r.get('gold_sql','')[:150]}")
    print(f"  BASE: {r.get('pred_sql','')[:150]}")
    print(f"  FULL: {f.get('pred_sql','')[:150]}")
    print()

print("\n=== WINS (c: base ERR -> full OK) ===")
for qid in sorted(f_only):
    r, f = base[qid], full[qid]
    print(f"QID {qid} [{r.get('db_id','?')}, {r.get('difficulty','?')}]")
    print(f"  Q: {r.get('question','')[:120]}")
    print(f"  GOLD: {r.get('gold_sql','')[:150]}")
    print(f"  BASE: {r.get('pred_sql','')[:150]}")
    print(f"  FULL: {f.get('pred_sql','')[:150]}")
    print()

print("\n=== BOTH-FAIL BREAKDOWN BY DB ===")
from collections import Counter
db_counts = Counter(base[q].get("db_id", "?") for q in both_fail)
for db, cnt in db_counts.most_common():
    print(f"  {db}: {cnt}")

print("\n=== SAMPLE BOTH-FAIL (first 10) ===")
for qid in sorted(both_fail)[:10]:
    r, f = base[qid], full[qid]
    print(f"QID {qid} [{r.get('db_id','?')}, {r.get('difficulty','?')}]")
    print(f"  Q: {r.get('question','')[:120]}")
    print(f"  GOLD: {r.get('gold_sql','')[:150]}")
    print(f"  FULL: {f.get('pred_sql','')[:150]}")
    print()
