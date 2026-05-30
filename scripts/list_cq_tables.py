"""List CQ tables with row counts and columns."""
import sys
sys.path.insert(0, "D:/adk")
from dotenv import load_dotenv
load_dotenv("data_agent/.env")
from data_agent.db_engine import get_engine
from sqlalchemy import text

eng = get_engine()
with eng.connect() as c:
    tables = c.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'cq_%' ORDER BY table_name"
    )).fetchall()
    for (tbl,) in tables:
        rc = c.execute(text("SELECT reltuples::bigint FROM pg_class WHERE relname = :t"), {"t": tbl}).fetchone()
        cols = c.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"
        ), {"t": tbl}).fetchall()
        print(f"\n{tbl} (~{int(rc[0]) if rc else 0:,} rows)")
        for cn, dt in cols:
            print(f"  {cn:30s} {dt}")
