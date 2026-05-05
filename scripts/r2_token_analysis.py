"""Measure token cost of grounding context for BIRD questions."""
import sys
sys.path.insert(0, "D:/adk")
import json, asyncio
from pathlib import Path

# Rough token estimate: 1 token ~ 4 chars for English, ~2 chars for Chinese
def estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return (ascii_chars // 4) + (non_ascii // 2)

from data_agent.nl2sql_grounding import build_nl2sql_context

bird_data = json.loads(Path("D:/adk/data/bird_mini_dev/llm/mini_dev_data/minidev/MINIDEV/mini_dev_postgresql.json").read_text(encoding="utf-8"))

# Sample 20 questions across schemas
sample_qids = [1149, 1155, 1164, 1179, 1220, 1331, 1350, 1387, 1432, 1464,
               1473, 1484, 1501, 1506, 1528, 1533, 1148, 1150, 1166, 1189]
by_id = {q["question_id"]: q for q in bird_data}

total_tokens = 0
count = 0
for qid in sample_qids:
    q = by_id.get(qid)
    if not q:
        continue
    schema_pg = f"bird_{q['db_id']}"
    try:
        ctx = build_nl2sql_context(q["question"], schema_filter=schema_pg)
        tokens = estimate_tokens(ctx)
        total_tokens += tokens
        count += 1
        print(f"QID {qid} ({q['db_id']}): ~{tokens} tokens, len={len(ctx)}")
    except Exception as e:
        print(f"QID {qid}: ERROR {e}")

if count:
    print(f"\nAverage grounding context: ~{total_tokens//count} tokens ({count} samples)")
    # Compare with baseline (just question + schema dump)
    # Baseline prompt is roughly: question + DDL (~200-400 tokens)
    print(f"Baseline estimate: ~300 tokens (question + DDL)")
    print(f"Ratio: ~{total_tokens//count / 300:.1f}x")
