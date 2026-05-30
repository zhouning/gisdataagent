"""Debug FK addition for financial schema."""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, 'D:/adk/scripts/nl2sql_bench_bird')
sys.path.insert(0, 'D:/adk')
from dotenv import load_dotenv
load_dotenv('D:/adk/data_agent/.env', override=True)
from sqlalchemy import text
from import_to_pg import extract_sqlite_fks
from data_agent.db_engine import get_engine

eng = get_engine()
schema = "bird_financial"
sqlite_path = "data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/dev_databases/financial/financial.sqlite"

# Check PG column names for "account" table
with eng.connect() as c:
    cols = c.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
    ), {"s": schema, "t": "account"}).fetchall()
    print(f"PG {schema}.account columns:")
    for col in cols:
        print(f"  {col[0]}  ({col[1]})")

    # Try to add an FK manually
    try:
        with eng.begin() as conn:
            conn.execute(text(
                f'ALTER TABLE "{schema}"."account" ADD CONSTRAINT fk_account_district_id_district '
                f'FOREIGN KEY ("district_id") REFERENCES "{schema}"."district" ("district_id")'
            ))
            print("FK added successfully")
    except Exception as e:
        print(f"FK FAILED: {e}")

# Now check SQLite extraction
sqlite_conn = sqlite3.connect(sqlite_path)
fks = extract_sqlite_fks(sqlite_conn, "account")
print(f"\nSQLite extract_sqlite_fks(account): {fks}")
sqlite_conn.close()
