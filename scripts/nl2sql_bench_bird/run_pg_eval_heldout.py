"""Run BIRD R2 evaluation on held-out question IDs (independent of R2 design set)."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Read held-out qids
heldout_qids = set(json.loads(
    Path("D:/adk/data_agent/nl2sql_eval_results/bird_heldout_qids.json").read_text(encoding="utf-8")
))
print(f"Held-out qids: {len(heldout_qids)}")

# Monkey-patch load_questions to filter to held-out
import run_pg_eval
original_load = run_pg_eval.load_questions

def filtered_load(questions_path, limit=None, difficulties=None, db_ids=None):
    questions = original_load(questions_path, limit=None, difficulties=difficulties, db_ids=db_ids)
    filtered = [q for q in questions if q.get("question_id") in heldout_qids]
    print(f"[heldout] Filtered to {len(filtered)} held-out questions")
    if limit:
        filtered = filtered[:limit]
    return filtered

run_pg_eval.load_questions = filtered_load

# Override output dir to distinguish from main R2 run
import sys as _sys
_sys.argv = ["run_pg_eval.py", "--mode", "both", "--out-dir",
             "D:/adk/data_agent/nl2sql_eval_results/bird_heldout_R2_eval"]

import asyncio
exit_code = asyncio.run(run_pg_eval.main())
_sys.exit(exit_code)
