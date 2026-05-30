"""Check SQLite FK declarations in BIRD databases."""
import sqlite3
from pathlib import Path

DB_ROOT = Path("data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/dev_databases")

for db_dir in sorted(DB_ROOT.iterdir()):
    if not db_dir.is_dir():
        continue
    sqlite_file = db_dir / f"{db_dir.name}.sqlite"
    if not sqlite_file.exists():
        continue
    conn = sqlite3.connect(str(sqlite_file))
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    total_fks = 0
    fk_in_ddl = 0
    for t in tables:
        fks = conn.execute(f"PRAGMA foreign_key_list(\"{t}\")").fetchall()
        total_fks += len(fks)
        ddl = conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{t}'").fetchone()
        if ddl and ddl[0] and ("FOREIGN" in ddl[0].upper() or "REFERENCES" in ddl[0].upper()):
            fk_in_ddl += 1
    conn.close()
    print(f"{db_dir.name:35s}  tables={len(tables):2d}  pragma_fks={total_fks:2d}  ddl_fk_tables={fk_in_ddl}")
