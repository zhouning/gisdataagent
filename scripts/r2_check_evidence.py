"""Check evidence for specific QIDs."""
import json
from pathlib import Path

qids_to_trace = [1155, 1164, 1166, 1171, 1179, 1189, 1205, 1209, 1220, 1225, 1227, 1229]
data = json.loads(Path("D:/adk/data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/mini_dev_postgresql.json").read_text(encoding="utf-8"))
by_id = {q.get("question_id", i): q for i, q in enumerate(data)}

for qid in qids_to_trace:
    q = by_id.get(qid)
    if not q:
        print(f"QID {qid}: NOT FOUND")
        continue
    print(f"QID {qid}: db={q.get('db_id')}")
    print(f"  Q: {q.get('question','')}")
    print(f"  EVIDENCE: {q.get('evidence','(empty)')[:350]}")
    print()
