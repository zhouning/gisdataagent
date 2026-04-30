"""BIRD mini_dev NL2SQL Benchmark — pure-LLM baseline evaluation.

Runs 500 questions from BIRD mini_dev against Gemini, executes generated SQL
on the corresponding SQLite database, and compares results with gold SQL.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_bird_eval.py --limit 10
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_bird_eval.py  # full 500
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bird_paths import resolve_bird_layout
from dotenv import load_dotenv
from google import genai as genai_client  # noqa: E402
from google.genai import types  # noqa: E402

load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

MODEL = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
_client = genai_client.Client()

SYSTEM_PROMPT = """You are a SQLite SQL expert. Convert the user question into a
single SQLite SELECT query over the given schema.

Rules:
- Output ONLY the SQL, no commentary, no markdown fences.
- Use SQLite syntax (e.g. SUBSTR, IIF, CAST(x AS REAL), || for concat).
- Do not add LIMIT unless the question explicitly asks for top-K.
- Use the evidence/hints provided to guide your query logic.
"""


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--bird-root", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--difficulty", default=None, help="simple,moderate,challenging")
    p.add_argument("--out-dir", default=None)
    return p


def load_questions(questions_path: Path, limit: int | None = None, difficulties: set[str] | None = None) -> list[dict]:
    out: list[dict] = []
    with questions_path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line.strip())
            if difficulties and rec.get("difficulty") not in difficulties:
                continue
            out.append(rec)
            if limit and len(out) >= limit:
                break
    return out


def find_db_path(db_id: str, db_root: Path, bird_root: Path) -> Path | None:
    """Locate the SQLite file for a given db_id."""
    candidates = [
        db_root / db_id / f"{db_id}.sqlite",
        db_root / db_id / f"{db_id}.db",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Fallback: search
    matches = list(bird_root.rglob(f"{db_id}/{db_id}.sqlite"))
    if matches:
        return matches[0]
    matches = list(bird_root.rglob(f"{db_id}.sqlite"))
    return matches[0] if matches else None


def execute_sqlite(sql: str, db_path: Path, timeout: float = 30.0) -> dict:
    """Execute SQL on SQLite, return {status, rows, error}."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()
        return {"status": "ok", "rows": rows}
    except Exception as e:
        return {"status": "error", "rows": None, "error": str(e)}


def strip_fences(s: str) -> str:
    s = s.strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def generate_sql(question: str, schema: str, evidence: str) -> dict:
    """Call Gemini to generate SQL."""
    prompt = (
        SYSTEM_PROMPT
        + f"\n\nSCHEMA:\n{schema}"
        + (f"\n\nEVIDENCE/HINTS:\n{evidence}" if evidence else "")
        + f"\n\nQUESTION: {question}\n\nSQL:"
    )
    try:
        resp = _client.models.generate_content(
            model=MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(timeout=60_000,
                    retry_options=types.HttpRetryOptions(initial_delay=2.0, attempts=3)),
                temperature=0.0,
            ),
        )
    except Exception as e:
        return {"status": "error", "sql": "", "error": str(e), "tokens": 0}

    sql = strip_fences(resp.text or "")
    tokens = 0
    if hasattr(resp, "usage_metadata") and resp.usage_metadata:
        tokens = (getattr(resp.usage_metadata, "prompt_token_count", 0) or 0) + \
                 (getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
    return {"status": "ok", "sql": sql, "error": None, "tokens": tokens}


def compare_results(gold_rows: list, pred_rows: list) -> bool:
    """Multiset comparison with float tolerance and None-safe sorting."""
    if gold_rows is None or pred_rows is None:
        return False
    if len(gold_rows) != len(pred_rows):
        return False

    def norm(v):
        if v is None:
            return ("__NULL__",)  # wrap so sort is type-stable
        if isinstance(v, float):
            return ("F", round(v, 4))
        if isinstance(v, bool):
            return ("B", int(v))
        if isinstance(v, int):
            return ("I", v)
        return ("S", str(v))

    g = sorted(tuple(norm(c) for c in r) for r in gold_rows)
    p = sorted(tuple(norm(c) for c in r) for r in pred_rows)
    return g == p


import sqlite3 as _sqlite3_local


def open_resume_cache(p: Path) -> _sqlite3_local.Connection:
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = _sqlite3_local.connect(str(p))
    conn.execute("CREATE TABLE IF NOT EXISTS done (qid INTEGER PRIMARY KEY, payload TEXT)")
    return conn


def cache_get(conn, qid: int) -> dict | None:
    row = conn.execute("SELECT payload FROM done WHERE qid=?", (qid,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(conn, qid: int, payload: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO done VALUES (?, ?)",
                 (qid, json.dumps(payload, default=str, ensure_ascii=False)))
    conn.commit()


def main() -> int:
    p = build_arg_parser()
    args = p.parse_args()

    layout = resolve_bird_layout(args.bird_root)
    bird_root = layout["bird_root"]
    questions_path = layout["sqlite_questions"]
    db_root = layout["dev_databases"]
    results_root = layout["results_root"]

    diffs = set(args.difficulty.split(",")) if args.difficulty else None
    questions = load_questions(questions_path=questions_path, limit=args.limit, difficulties=diffs)
    print(f"[bird] Loaded {len(questions)} questions")

    if not db_root.exists():
        # Try alternate paths
        alt = list(bird_root.rglob("dev_databases"))
        if alt:
            _db_root = alt[0]
            print(f"[bird] Using DB root: {_db_root}")
        else:
            print(f"ERROR: DB root not found. Expected: {db_root}", file=sys.stderr)
            print("Run: unzip minidev.zip first", file=sys.stderr)
            return 2
    else:
        _db_root = db_root

    out_dir = Path(args.out_dir) if args.out_dir else (
        results_root / f"bird_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = open_resume_cache(out_dir / "run_state.db")
    print(f"[bird] Output dir: {out_dir}")

    records: list[dict] = []
    correct = 0
    valid = 0

    for i, q in enumerate(questions, 1):
        qid = q["question_id"]
        db_id = q["db_id"]
        difficulty = q.get("difficulty", "?")

        # Resume cache
        cached = cache_get(cache, qid)
        if cached:
            records.append(cached)
            if cached.get("ex"):
                correct += 1
            if cached.get("valid"):
                valid += 1
            mark = "OK" if cached.get("ex") else ("VAL" if cached.get("valid") else "ERR")
            print(f"  [{i}/{len(questions)}] {mark} {qid} ({difficulty}) db={db_id} (cached)")
            continue

        db_path = find_db_path(db_id, _db_root, bird_root)
        if db_path is None:
            rec = {"qid": qid, "db_id": db_id, "difficulty": difficulty,
                   "question": q["question"], "gold_sql": q["SQL"],
                   "pred_sql": "", "ex": 0, "valid": 0, "error": "db_not_found"}
            records.append(rec)
            print(f"  [{i}/{len(questions)}] ? {qid} db={db_id} NOT FOUND")
            continue

        # Generate SQL
        gen = generate_sql(q["question"], q["schema"], q.get("evidence", ""))
        pred_sql = gen.get("sql", "")

        # Execute gold
        gold_res = execute_sqlite(q["SQL"], db_path)
        # Execute pred
        pred_res = execute_sqlite(pred_sql, db_path) if pred_sql else {"status": "error", "rows": None}

        is_valid = pred_res["status"] == "ok"
        is_correct = False
        if is_valid and gold_res["status"] == "ok":
            is_correct = compare_results(gold_res["rows"], pred_res["rows"])

        if is_valid:
            valid += 1
        if is_correct:
            correct += 1

        rec = {
            "qid": qid, "db_id": db_id, "difficulty": difficulty,
            "question": q["question"], "gold_sql": q["SQL"],
            "pred_sql": pred_sql, "ex": 1 if is_correct else 0,
            "valid": 1 if is_valid else 0,
            "error": pred_res.get("error") or gen.get("error"),
            "tokens": gen.get("tokens", 0),
        }
        records.append(rec)
        cache_put(cache, qid, rec)
        mark = "OK" if is_correct else ("VAL" if is_valid else "ERR")
        print(f"  [{i}/{len(questions)}] {mark} {qid} ({difficulty}) db={db_id}")

    # Aggregate
    n = len(records)
    ex_rate = correct / n if n else 0
    valid_rate = valid / n if n else 0

    by_diff: dict[str, dict] = {}
    for r in records:
        d = r["difficulty"]
        by_diff.setdefault(d, {"n": 0, "correct": 0})
        by_diff[d]["n"] += 1
        by_diff[d]["correct"] += r["ex"]
    diff_breakdown = {d: round(v["correct"] / v["n"], 3) for d, v in sorted(by_diff.items())}

    summary = {
        "model": MODEL,
        "n": n,
        "execution_accuracy": round(ex_rate, 4),
        "execution_valid_rate": round(valid_rate, 4),
        "by_difficulty": diff_breakdown,
        "generated_at": datetime.now().isoformat(),
    }

    # Write output
    payload = {"summary": summary, "records": records}
    out_file = out_dir / "bird_baseline_results.json"
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"[bird] RESULTS: EX={ex_rate:.3f} ({correct}/{n}), Valid={valid_rate:.3f}")
    print(f"[bird] By difficulty: {diff_breakdown}")
    print(f"[bird] Output: {out_file}")
    print(f"{'='*60}")

    # Record to eval_history if DB available
    try:
        from data_agent.eval_history import ensure_eval_table, record_eval_result
        ensure_eval_table()
        record_eval_result(
            pipeline="nl2sql_bird_baseline",
            overall_score=ex_rate,
            pass_rate=ex_rate,
            verdict="PASS" if ex_rate >= 0.5 else "FAIL",
            num_tests=n,
            num_passed=correct,
            model=MODEL,
            scenario="bird_mini_dev",
            metrics=summary,
        )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
