import sqlite3
conn = sqlite3.connect("D:/adk/data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/run_state.db")
print("full:", conn.execute("SELECT count(*) FROM done WHERE mode='full'").fetchone()[0])
print("baseline:", conn.execute("SELECT count(*) FROM done WHERE mode='baseline'").fetchone()[0])
