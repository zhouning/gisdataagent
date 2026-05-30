import sqlite3
conn = sqlite3.connect("data_agent/nl2sql_eval_results/bird_pg_2026-05-04_093040/run_state.db")
bl = conn.execute("SELECT count(*) FROM done WHERE mode='baseline'").fetchone()[0]
fl = conn.execute("SELECT count(*) FROM done WHERE mode='full'").fetchone()[0]
print(f"BIRD P2: baseline={bl}/500, full={fl}/500")
conn.close()
