import sys
sys.path.insert(0, 'D:/adk')
from dotenv import load_dotenv
load_dotenv('data_agent/.env')
from data_agent.db_engine import get_engine
from sqlalchemy import text

eng = get_engine()
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT name FROM agent_semantic_models WHERE name LIKE 'bird_%' AND is_active=true ORDER BY name"
    )).fetchall()
    print(f"Total bird_ models: {len(rows)}")
    by_schema = {}
    for r in rows:
        s = r[0].split('.')[0]
        by_schema[s] = by_schema.get(s, 0) + 1
    for s in sorted(by_schema):
        print(f"  {s}: {by_schema[s]} models")
