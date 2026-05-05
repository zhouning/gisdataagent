"""Analyze Chinese BIRD eval results."""
import sqlite3, json
DB = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_chinese_2026-05-05_201113/run_state.db"
conn = sqlite3.connect(DB)
recs = [json.loads(r[1]) for r in conn.execute('SELECT qid,payload FROM done WHERE mode="full_zh"').fetchall()]
n = len(recs)
ex = sum(r.get("ex", 0) for r in recs)
valid = sum(r.get("valid", 0) for r in recs)
print(f"Chinese BIRD {n}q: EX={ex}/{n}={ex/n:.3f}, Valid={valid}/{n}={valid/n:.3f}")

# Compare with R2 English baseline (108q result)
# R2 full EX was 0.593; for the same 50 qids we need to match
r2_db = "D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db"
r2_conn = sqlite3.connect(r2_db)
r2_full = {r[0]: json.loads(r[1]) for r in r2_conn.execute('SELECT qid,payload FROM done WHERE mode="full"').fetchall()}

# Match qids
zh_qids = {r["qid"] for r in recs}
en_subset = [(qid, r2_full[qid].get("ex", 0)) for qid in zh_qids if qid in r2_full]
en_ex = sum(x for _, x in en_subset)
print(f"English R2 on same {len(en_subset)} qids: EX={en_ex}/{len(en_subset)}={en_ex/len(en_subset):.3f}")

# Per-question compare
zh_by_qid = {r["qid"]: r for r in recs}
diff = 0
for qid, en_x in en_subset:
    zh_x = zh_by_qid[qid].get("ex", 0)
    if zh_x != en_x:
        diff += 1
print(f"Discordant pairs (zh vs en): {diff}/{len(en_subset)}")

# Difficulty breakdown
from collections import Counter
by_diff = {}
for r in recs:
    d = r.get("difficulty", "?")
    by_diff.setdefault(d, [0, 0])
    by_diff[d][0] += 1
    by_diff[d][1] += r.get("ex", 0)
print("\nBy difficulty:")
for d, (total, ok) in sorted(by_diff.items()):
    print(f"  {d}: {ok}/{total}={ok/total:.3f}")
