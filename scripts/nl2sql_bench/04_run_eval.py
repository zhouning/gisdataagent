"""Step 4 — Main NL2SQL evaluation entry.

Modes:
  --mode full       Run via full GIS Data Agent General pipeline (semantic layer + RAG)
  --mode baseline   Run pure-LLM baseline
  --mode both       Run both, side by side

Resume: a SQLite cache `run_state.db` lives in the result dir; rerunning the
same dir skips already-completed (question_id, mode) pairs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_agent.eval_history import ensure_eval_table, record_eval_result  # noqa: E402

# Sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from baseline_agent import generate_sql as baseline_generate_sql, dump_schema  # noqa: E402
from nl2sql_scenario import NL2SQLScenario, aggregate  # noqa: E402
from sql_executor import execute_sql  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "floodsql"
RESULTS_ROOT = Path(__file__).resolve().parents[2] / "data_agent" / "nl2sql_eval_results"

SCENARIO = NL2SQLScenario()


def find_benchmark_jsonl() -> Path:
    """Locate benchmark.jsonl in the downloaded dataset."""
    candidates = list(DATA_DIR.rglob("benchmark.jsonl"))
    if not candidates:
        candidates = list(DATA_DIR.rglob("*.jsonl"))
    if not candidates:
        raise FileNotFoundError(f"no benchmark.jsonl under {DATA_DIR}")
    return candidates[0]


def load_questions(path: Path, limit: int | None = None,
                   difficulties: set[str] | None = None) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = rec.get("id", "")
            diff = qid.split("_", 1)[0] if "_" in qid else "?"
            rec["difficulty"] = diff
            if difficulties and diff not in difficulties:
                continue
            out.append(rec)
            if limit and len(out) >= limit:
                break
    return out


# -------------------- resume cache --------------------

def open_cache(p: Path) -> sqlite3.Connection:
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("""CREATE TABLE IF NOT EXISTS done (
        qid TEXT, mode TEXT, payload TEXT, PRIMARY KEY(qid, mode)
    )""")
    return conn


def cache_get(conn: sqlite3.Connection, qid: str, mode: str) -> dict | None:
    row = conn.execute("SELECT payload FROM done WHERE qid=? AND mode=?", (qid, mode)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(conn: sqlite3.Connection, qid: str, mode: str, payload: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO done VALUES (?, ?, ?)",
                 (qid, mode, json.dumps(payload, default=str)))
    conn.commit()


# -------------------- per-question runners --------------------

def run_baseline_one(q: dict) -> dict:
    gen = baseline_generate_sql(q["question"])
    pred_sql = gen.get("sql", "")
    pred_exec = execute_sql(pred_sql) if pred_sql else None

    # Gold result: fetch from JSONL or execute
    gold_sql = q.get("sql", "")
    gold_exec = execute_sql(gold_sql)

    metrics = SCENARIO.evaluate(
        actual_output={"sql": pred_sql, "exec": pred_exec},
        expected_output={"sql": gold_sql, "exec": gold_exec},
    )
    return {
        "qid": q["id"],
        "difficulty": q["difficulty"],
        "question": q["question"],
        "gold_sql": gold_sql,
        "pred_sql": pred_sql,
        "gen_status": gen.get("status"),
        "gen_error": gen.get("error"),
        "tokens": gen.get("tokens", 0),
        "metrics": metrics,
    }


async def run_full_one(q: dict, agent, session_service) -> dict:
    """Run via full pipeline. Extracts SQL from query_database tool args."""
    from data_agent.pipeline_runner import run_pipeline_headless

    sid = f"nl2sql_{q['id']}_{int(time.time())}"
    try:
        result = await run_pipeline_headless(
            agent=agent,
            session_service=session_service,
            user_id="benchmark",
            session_id=sid,
            prompt=q["question"],
            pipeline_type="general",
            intent="GENERAL",
            role="analyst",
        )
    except Exception as e:
        return {
            "qid": q["id"], "difficulty": q["difficulty"],
            "question": q["question"], "gold_sql": q.get("sql", ""),
            "pred_sql": "", "gen_status": "error", "gen_error": str(e),
            "tokens": 0,
            "metrics": SCENARIO.evaluate(
                actual_output={"sql": "", "exec": None},
                expected_output={"sql": q.get("sql", ""), "exec": execute_sql(q.get("sql", ""))},
            ),
        }

    # Extract last query_database SQL
    pred_sql = ""
    for entry in (result.tool_execution_log or [])[::-1]:
        if entry.get("tool_name") == "query_database":
            pred_sql = entry.get("args", {}).get("sql_query", "") or ""
            if pred_sql:
                break

    pred_exec = execute_sql(pred_sql) if pred_sql else None
    gold_sql = q.get("sql", "")
    gold_exec = execute_sql(gold_sql)

    metrics = SCENARIO.evaluate(
        actual_output={"sql": pred_sql, "exec": pred_exec},
        expected_output={"sql": gold_sql, "exec": gold_exec},
    )
    return {
        "qid": q["id"], "difficulty": q["difficulty"],
        "question": q["question"], "gold_sql": gold_sql,
        "pred_sql": pred_sql, "gen_status": "ok" if pred_sql else "no_sql_emitted",
        "gen_error": result.error,
        "tokens": (result.total_input_tokens + result.total_output_tokens),
        "duration": result.duration_seconds,
        "metrics": metrics,
    }


# -------------------- main loop --------------------

def write_results(out_dir: Path, mode: str, records: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "n": len(records),
        "aggregate": aggregate(records),
        "records": records,
        "generated_at": datetime.now().isoformat(),
    }
    (out_dir / f"{mode}_results.json").write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[run] wrote {out_dir}/{mode}_results.json")


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["full", "baseline", "both"], default="both")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--difficulty", default=None,
                   help="comma-separated, e.g. L0,L1")
    p.add_argument("--out-dir", default=None,
                   help="output dir (default: timestamped under nl2sql_eval_results/)")
    args = p.parse_args()

    diffs = set(args.difficulty.split(",")) if args.difficulty else None

    bench_path = find_benchmark_jsonl()
    questions = load_questions(bench_path, limit=args.limit, difficulties=diffs)
    print(f"[run] loaded {len(questions)} questions from {bench_path}")
    if not questions:
        print("ERROR: no questions matched.", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else (
        RESULTS_ROOT / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = open_cache(out_dir / "run_state.db")
    print(f"[run] output dir: {out_dir}")

    # Pre-warm baseline schema once
    if args.mode in ("baseline", "both"):
        try:
            sd = dump_schema()
            print(f"[run] schema dump cached ({len(sd)} chars)")
        except Exception as e:
            print(f"[run] WARNING: schema dump failed: {e}", file=sys.stderr)

    # Init full pipeline lazily (heavy import)
    full_agent = None
    full_session = None
    if args.mode in ("full", "both"):
        from data_agent.agent import general_pipeline
        from google.adk.sessions import InMemorySessionService
        full_agent = general_pipeline
        full_session = InMemorySessionService()

    ensure_eval_table()

    # ----- BASELINE -----
    baseline_records: list[dict] = []
    if args.mode in ("baseline", "both"):
        print(f"\n=== BASELINE ({len(questions)} questions) ===")
        for i, q in enumerate(questions, 1):
            cached = cache_get(cache, q["id"], "baseline")
            if cached:
                baseline_records.append(cached)
                continue
            try:
                rec = run_baseline_one(q)
            except Exception as e:
                rec = {
                    "qid": q["id"], "difficulty": q["difficulty"],
                    "question": q["question"], "gold_sql": q.get("sql", ""),
                    "pred_sql": "", "gen_status": "exception", "gen_error": str(e),
                    "tokens": 0,
                    "metrics": {"execution_valid": 0.0, "execution_accuracy": 0.0,
                                "exact_match": 0.0, "compare_reason": str(e),
                                "pred_status": "exception", "gold_status": "?"},
                }
            baseline_records.append(rec)
            cache_put(cache, q["id"], "baseline", rec)
            mark = "✓" if rec["metrics"]["execution_accuracy"] == 1.0 else "✗"
            print(f"  [{i}/{len(questions)}] {mark} {q['id']} ({q['difficulty']})")
        write_results(out_dir, "baseline", baseline_records)
        agg = aggregate(baseline_records)
        print(f"[baseline] EX={agg['execution_accuracy']:.3f} valid={agg['execution_valid_rate']:.3f}")
        record_eval_result(
            pipeline="nl2sql_baseline",
            overall_score=agg["execution_accuracy"],
            pass_rate=agg["execution_accuracy"],
            verdict="PASS" if agg["execution_accuracy"] >= 0.5 else "FAIL",
            num_tests=agg["n"],
            num_passed=int(agg["execution_accuracy"] * agg["n"]),
            scenario="nl2sql_floodsql",
            metrics=agg,
            details={"out_dir": str(out_dir)},
        )

    # ----- FULL -----
    full_records: list[dict] = []
    if args.mode in ("full", "both"):
        print(f"\n=== FULL PIPELINE ({len(questions)} questions) ===")
        for i, q in enumerate(questions, 1):
            cached = cache_get(cache, q["id"], "full")
            if cached:
                full_records.append(cached)
                continue
            try:
                rec = await run_full_one(q, full_agent, full_session)
            except Exception as e:
                rec = {
                    "qid": q["id"], "difficulty": q["difficulty"],
                    "question": q["question"], "gold_sql": q.get("sql", ""),
                    "pred_sql": "", "gen_status": "exception", "gen_error": str(e),
                    "tokens": 0,
                    "metrics": {"execution_valid": 0.0, "execution_accuracy": 0.0,
                                "exact_match": 0.0, "compare_reason": str(e),
                                "pred_status": "exception", "gold_status": "?"},
                }
            full_records.append(rec)
            cache_put(cache, q["id"], "full", rec)
            mark = "✓" if rec["metrics"]["execution_accuracy"] == 1.0 else "✗"
            print(f"  [{i}/{len(questions)}] {mark} {q['id']} ({q['difficulty']})")
        write_results(out_dir, "full", full_records)
        agg = aggregate(full_records)
        print(f"[full] EX={agg['execution_accuracy']:.3f} valid={agg['execution_valid_rate']:.3f}")
        record_eval_result(
            pipeline="nl2sql_full",
            overall_score=agg["execution_accuracy"],
            pass_rate=agg["execution_accuracy"],
            verdict="PASS" if agg["execution_accuracy"] >= 0.5 else "FAIL",
            num_tests=agg["n"],
            num_passed=int(agg["execution_accuracy"] * agg["n"]),
            scenario="nl2sql_floodsql",
            metrics=agg,
            details={"out_dir": str(out_dir)},
        )

    print(f"\n[run] DONE. Output: {out_dir}")
    print(f"      Next: python scripts/nl2sql_bench/05_report.py --dir \"{out_dir}\"")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
