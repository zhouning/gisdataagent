"""Run DIN-SQL baseline on GIS 20 (Chongqing) questions.

DIN-SQL is a 4-stage pipeline: schema_linking -> classification -> generation
-> self_correction. This runner mirrors run_cq_eval.py but replaces the
Gemini-direct and full-pipeline modes with the DIN-SQL pipeline.

Note on robustness questions: DIN-SQL has no built-in safety handling (it
does not refuse DELETE/UPDATE/DROP or hallucinated-column questions). The
robustness score is therefore expected to be lower than the full pipeline.
This is intentional — the comparison is honest.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_din_sql.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

# Reuse helpers from run_cq_eval — execute_pg, compare_results, get_schema,
# load_questions, evaluate_robustness, _init_runtime, RESULTS_ROOT
from run_cq_eval import (
    execute_pg,
    compare_results,
    get_schema,
    load_questions,
    evaluate_robustness,
    _init_runtime,
    RESULTS_ROOT,
)

from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import predict as din_sql_predict


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DIN-SQL baseline on GIS 20 Chongqing benchmark"
    )
    p.add_argument("--out-dir", default=None)
    p.add_argument("--max-retries", type=int, default=1,
                   help="DIN-SQL self-correction retries (default 1)")
    return p


def run_one(q: dict, schema_text: str, max_retries: int = 1) -> dict:
    """Run DIN-SQL on a single CQ question and return an evaluation record."""
    qid = q["id"]
    difficulty = q["difficulty"]
    category = q["category"]
    target_metric = q.get("target_metric", "Execution Accuracy")
    golden_sql = q.get("golden_sql")

    def exec_fn(sql: str) -> dict:
        return execute_pg(sql)

    t0 = time.time()
    try:
        result = din_sql_predict(
            schema=schema_text,
            question=q["question"],
            evidence="",
            execute_fn=exec_fn,
            max_retries=max_retries,
        )
    except Exception as e:
        return {
            "qid": qid, "category": category, "difficulty": difficulty,
            "question": q["question"], "gold_sql": golden_sql or "",
            "pred_sql": "", "ex": 0, "valid": 0,
            "reason": f"exception: {e}",
            "din_difficulty": "?", "stages_run": 0, "tokens": 0,
            "duration": round(time.time() - t0, 2),
        }

    pred_sql = result.get("sql", "")
    duration = round(time.time() - t0, 2)

    # Robustness questions use a separate evaluation logic
    is_robustness = difficulty == "Robustness" or target_metric in (
        "Security Rejection", "Refusal Rate", "AST Validation (Must contain LIMIT)"
    )
    if is_robustness:
        passed, reason = evaluate_robustness(q, pred_sql)
        return {
            "qid": qid, "category": category, "difficulty": difficulty,
            "question": q["question"], "gold_sql": golden_sql or "N/A",
            "pred_sql": pred_sql, "ex": 1 if passed else 0, "valid": 1,
            "reason": reason,
            "din_difficulty": result.get("difficulty", "?"),
            "stages_run": result.get("stages_run", 0),
            "tokens": result.get("tokens", 0),
            "duration": duration,
        }

    # Normal EX evaluation
    pred_res = execute_pg(pred_sql) if pred_sql else {
        "status": "error", "rows": None, "error": "empty SQL"
    }
    gold_res = execute_pg(golden_sql) if golden_sql else {
        "status": "error", "rows": None, "error": "no gold"
    }

    is_valid = pred_res["status"] == "ok"
    passed, reason = (
        compare_results(gold_res, pred_res)
        if is_valid
        else (False, pred_res.get("error", "pred exec failed"))
    )

    return {
        "qid": qid,
        "category": category,
        "difficulty": difficulty,
        "question": q["question"],
        "gold_sql": golden_sql or "",
        "pred_sql": pred_sql,
        "ex": 1 if passed else 0,
        "valid": 1 if is_valid else 0,
        "reason": reason,
        "pred_error": pred_res.get("error", ""),
        "din_difficulty": result.get("difficulty", "?"),
        "stages_run": result.get("stages_run", 0),
        "tokens": result.get("tokens", 0),
        "duration": duration,
    }


def main() -> int:
    _init_runtime()
    p = build_arg_parser()
    args = p.parse_args()

    questions = load_questions()
    print(f"[cq-din-sql] Loaded {len(questions)} questions")

    out_dir = Path(args.out_dir) if args.out_dir else (
        RESULTS_ROOT / f"cq_din_sql_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[cq-din-sql] Output: {out_dir}")

    # Pre-fetch schema once (shared for all CQ questions)
    schema_text = get_schema()

    recs: list[dict] = []
    for i, q in enumerate(questions, 1):
        try:
            rec = run_one(q, schema_text, max_retries=args.max_retries)
        except Exception as e:
            rec = {
                "qid": q["id"], "category": q["category"],
                "difficulty": q["difficulty"], "question": q["question"],
                "gold_sql": q.get("golden_sql", ""), "pred_sql": "",
                "ex": 0, "valid": 0, "reason": str(e),
                "din_difficulty": "?", "stages_run": 0, "tokens": 0,
                "duration": 0,
            }

        recs.append(rec)
        m = "OK" if rec["ex"] else "ERR"
        print(
            f"  [{i}/{len(questions)}] {m} {rec['qid']} "
            f"({rec['difficulty']}/{rec['category']}) "
            f"din={rec['din_difficulty']} stages={rec['stages_run']}"
        )

    # Summarize
    n = len(recs)
    ex = sum(r["ex"] for r in recs)

    by_diff: dict[str, list[int]] = {}
    for r in recs:
        d = r["difficulty"]
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r["ex"]
    diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())}

    by_cat: dict[str, list[int]] = {}
    for r in recs:
        c = r["category"]
        by_cat.setdefault(c, [0, 0])
        by_cat[c][0] += 1
        by_cat[c][1] += r["ex"]
    cat_breakdown = {c: round(v[1] / v[0], 3) for c, v in sorted(by_cat.items())}

    summary = {
        "mode": "din_sql",
        "model": "gemini-2.5-flash",
        "n": n,
        "execution_accuracy": round(ex / n if n else 0, 4),
        "by_difficulty": diff_breakdown,
        "by_category": cat_breakdown,
        "generated_at": datetime.now().isoformat(),
    }

    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "records": recs},
                   indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(f"\n[cq-din-sql] EX={summary['execution_accuracy']:.3f} ({ex}/{n})")
    print(f"  by difficulty: {diff_breakdown}")
    print(f"  by category:   {cat_breakdown}")
    print(f"\n[cq-din-sql] Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
