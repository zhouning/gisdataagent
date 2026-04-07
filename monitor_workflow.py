#!/usr/bin/env python3
import os, time
from sqlalchemy import create_engine, text, URL
from dotenv import load_dotenv

load_dotenv('data_agent/.env')

db_url = URL.create(
    "postgresql",
    username=os.getenv('POSTGRES_USER'),
    password=os.getenv('POSTGRES_PASSWORD'),
    host=os.getenv('POSTGRES_HOST'),
    port=int(os.getenv('POSTGRES_PORT', 5432)),
    database=os.getenv('POSTGRES_DATABASE'),
)
engine = create_engine(db_url)

print("=== 监控工作流执行 ===\n")

for i in range(60):  # 监控 2 分钟
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, status, parameters_used->>'file_path' as file_path, started_at
            FROM agent_workflow_runs
            WHERE workflow_id IN (SELECT id FROM agent_workflows WHERE workflow_name LIKE '%92805b%')
            ORDER BY started_at DESC LIMIT 1
        """))

        row = result.fetchone()
        if row:
            print(f"\r[{i*2}s] Run #{row[0]} | Status: {row[1]} | File: {row[2][:50] if row[2] else 'N/A'}...", end='', flush=True)
            if row[1] in ('completed', 'failed'):
                print(f"\n\n✅ 工作流已{row[1]}！")
                break

    time.sleep(2)
