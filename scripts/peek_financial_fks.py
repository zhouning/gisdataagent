import sqlite3
conn = sqlite3.connect('data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/dev_databases/financial/financial.sqlite')
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
for r in cur.fetchall():
    t = r[0]
    fks = conn.execute(f'PRAGMA foreign_key_list("{t}")').fetchall()
    if fks:
        print(t, '->', len(fks), 'FKs')
        for fk in fks:
            print('  ', fk)
conn.close()
