"""Check BIRD schema status."""
import os, sys
sys.path.insert(0, 'D:/adk')
from dotenv import load_dotenv
load_dotenv('data_agent/.env')
from data_agent.db_engine import get_engine
from sqlalchemy import text

eng = get_engine()
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'bird_%' ORDER BY 1"
    )).fetchall()
    print(f"BIRD schemas: {len(rows)}")
    for r in rows:
        # Count tables and FKs per schema
        n_tbl = c.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = :s AND table_type='BASE TABLE'"
        ), {"s": r[0]}).scalar()
        n_fk = c.execute(text(
            "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_schema = :s AND constraint_type='FOREIGN KEY'"
        ), {"s": r[0]}).scalar()
        print(f"  {r[0]:40s}  tables={n_tbl}  fks={n_fk}")
