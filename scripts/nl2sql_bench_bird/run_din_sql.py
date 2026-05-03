"""Run DIN-SQL baseline on BIRD 500 questions.

DIN-SQL is a 4-stage pipeline: schema_linking -> classification -> generation
-> self_correction. This runner mirrors run_pg_eval.py but replaces the
Gemini-direct and full-pipeline modes with the DIN-SQL pipeline.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_din_sql.py
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_din_sql.py --limit 20
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_din_sql.py --difficulty simple
"""
from __future__ import annotations

import argparse
import json
import sqlite3 as _sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from bird_paths import resolve_bird_layout

# Reuse helpers from run_pg_eval — execute_pg, compare_results, dump_schema,
# load_questions, open_cache, cache_get, cache_put, _init_runtime
from run_pg_eval import (
    execute_pg,
    compare_results,
    dump_schema,
    load_questions,
    open_cache,
    cache_get,
    cache_put,
    _init_runtime,
    build_arg_parser as _base_arg_parser,
)

from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import predict as din_sql_predict


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DIN-SQL baseline on BIRD 500 (PostgreSQL)"
    )
    p.add_argument("--bird-root", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--difficulty", default=None,
                   help="Comma-separated difficulty filter, e.g. simple,moderate")
    p.add_argument("--db-id", default=None, help="Filter by single db_id")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--max-retries", type=int, default=1,
                   help="DIN-SQL self-correction retries (default 1)")
    return p


def run_one(q: dict, max_retries: int = 1) -> dict:
    """Run DIN-SQL on a single BIRD question and return an evaluation record."""
    qid = q["question_id"]
    db_id = q["db_id"]
    evidence = q.get("evidence", "")
    gold_sql = q.get("SQL", "")

    schema_text = dump_schema(db_id)

    def exec_fn(sql: str) -> dict:
        return execute_pg(sql, db_id)

    t0 = time.time()
    try:
        result = din_sql_predict(
            schema=schema_text,
            question=q["question"],
            evidence=evidence,
            execute_fn=exec_fn,
            max_retries=max_retries,
        )
    except Exception as e:
        return {
            "qid": qid, "db_id": db_id,
            "difficulty": q.get("difficulty", "?"),
            "question": q["question"], "gold_sql": gold_sql,
            "pred_sql": "", "ex": 0, "valid": 0,
            "gen_status": "exception", "gen_error": str(e),
            "pred_error": "", "gold_status": "?",
            "din_difficulty": "?", "stages_run": 0, "tokens": 0,
            "duration": round(time.time() - t0, 2),
        }

    pred_sql = result.get("sql", "")
    duration = round(time.time() - t0, 2)

    pred_res = execute_pg(pred_sql, db_id) if pred_sql else {
        "status": "error", "rows": None, "error": "empty SQL"
    }
    gold_res = execute_pg(gold_sql, db_id)

    is_valid = pred_res["status"] == "ok"
    is_correct = (
        is_valid
        and gold_res["status"] == "ok"
        and compare_results(gold_res["rows"], pred_res["rows"])
    )

    return {
        "qid": qid,
        "db_id": db_id,
        "difficulty": q.get("difficulty", "?"),
        "question": q["question"],
        "gold_sql": gold_sql,
        "pred_sql": pred_sql,
        "ex": 1 if is_correct else 0,
        "valid": 1 if is_valid else 0,
        "gen_status": "ok" if pred_sql else "no_sql",
        "gen_error": None,
        "pred_error": pred_res.get("error", ""),
        "gold_status": gold_res["status"],
        "din_difficulty": result.get("difficulty", "?"),
        "stages_run": result.get("stages_run", 0),
        "tokens": result.get("tokens", 0),
        "duration": duration,
    }


def main() -> int:
    _init_runtime()
    p = build_arg_parser()
    args = p.parse_args()

    layout = resolve_bird_layout(args.bird_root)
    pg_questions = layout["pg_questions"]
    results_root = layout["results_root"]

    diffs = set(args.difficulty.split(",")) if args.difficulty else None
    dbs = set(args.db_id.split(",")) if args.db_id else None

    questions = load_questions(
        questions_path=pg_questions,
        limit=args.limit,
        difficulties=diffs,
        db_ids=dbs,
    )
    print(f"[bird-din-sql] Loaded {len(questions)} questions")

    out_dir = Path(args.out_dir) if args.out_dir else (
        results_root / f"bird_din_sql_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = open_cache(out_dir / "run_state.db")
    print(f"[bird-din-sql] Output: {out_dir}")

    mode = "din_sql"
    recs: list[dict] = []

    for i, q in enumerate(questions, 1):
        cached = cache_get(cache, q["question_id"], mode)
        if cached:
            recs.append(cached)
            m = "OK" if cached.get("ex") else ("VAL" if cached.get("valid") else "ERR")
            print(f"  [{i}/{len(questions)}] {m} {q['question_id']} (cached)")
            continue

        try:
            rec = run_one(q, max_retries=args.max_retries)
        except Exception as e:
            rec = {
                "qid": q["question_id"], "db_id": q["db_id"],
                "difficulty": q.get("difficulty", "?"),
                "question": q["question"], "gold_sql": q.get("SQL", ""),
                "pred_sql": "", "ex": 0, "valid": 0,
                "gen_status": "exception", "gen_error": str(e),
                "pred_error": "", "gold_status": "?",
                "din_difficulty": "?", "stages_run": 0, "tokens": 0,
                "duration": 0,
            }

        recs.append(rec)
        cache_put(cache, q["question_id"], mode, rec)
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(
            f"  [{i}/{len(questions)}] {m} {rec['qid']} "
            f"({rec['difficulty']}) db={rec['db_id']} "
            f"din={rec['din_difficulty']} stages={rec['stages_run']}"
        )

    # Summarize
    n = len(recs)
    ex = sum(r["ex"] for r in recs)
    valid = sum(r["valid"] for r in recs)

    by_diff: dict[str, list[int]] = {}
    for r in recs:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r["ex"]
    diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())}

    by_din_diff: dict[str, list[int]] = {}
    for r in recs:
        d = r.get("din_difficulty", "?")
        by_din_diff.setdefault(d, [0, 0])
        by_din_diff[d][0] += 1
        by_din_diff[d][1] += r["ex"]
    din_diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_din_diff.items())}

    summary = {
        "mode": mode,
        "model": "gemini-2.5-flash",
        "n": n,
        "execution_accuracy": round(ex / n if n else 0, 4),
        "execution_valid_rate": round(valid / n if n else 0, 4),
        "by_difficulty": diff_breakdown,
        "by_din_difficulty": din_diff_breakdown,
        "generated_at": datetime.now().isoformat(),
    }

    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "records": recs},
                   indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(f"\n[bird-din-sql] EX={summary['execution_accuracy']:.3f} ({ex}/{n}), "
          f"Valid={summary['execution_valid_rate']:.3f}")
    print(f"  by difficulty: {diff_breakdown}")
    print(f"  by DIN difficulty: {din_diff_breakdown}")
    print(f"\n[bird-din-sql] Output dir: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
