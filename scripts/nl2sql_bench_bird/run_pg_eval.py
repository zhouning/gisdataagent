"""BIRD mini_dev FULL PIPELINE evaluation — A/B test of GIS Data Agent.

Compares two modes head-to-head on BIRD mini_dev (PostgreSQL flavor):
  - baseline:  Pure LLM (Gemini direct, schema dump only)
  - full:      Full General Pipeline (semantic layer + ContextEngine + RAG + LLM)

Both modes execute generated SQL against the imported `bird_<db_id>` schemas in
PostgreSQL and compare result sets with the official PG gold SQL.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  # Smoke
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both --limit 10
  # Full
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_pg_eval.py --mode both
"""
from __future__ import annotations

import argparse


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--bird-root", default=None)
    p.add_argument("--mode", choices=["baseline", "full", "both"], default="both")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--difficulty", default=None)
    p.add_argument("--db-id", default=None, help="filter by single db_id")
    p.add_argument("--out-dir", default=None)
    return p


import asyncio
import json
import os
import re
import sqlite3 as _sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bird_paths import resolve_bird_layout
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

text = None
get_engine = None
ensure_eval_table = None
record_eval_result = None
types = None
MODEL = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")
_client = None


def _init_runtime() -> None:
    global text, get_engine, ensure_eval_table, record_eval_result, types, _client
    if _client is not None:
        return

    # Disable ArcPy tools BEFORE any data_agent import — works around a duplicate
    # function-declaration error that surfaces when the same arcpy_* tool ends up
    # in multiple ADK agents within general_pipeline. Benchmark questions never
    # need ArcPy, so this is safe.
    import data_agent.toolsets.geo_processing_tools as _geo_proc  # noqa: E402

    _geo_proc._arcpy_funcs.clear()
    _geo_proc._arcpy_gov_explore_funcs.clear()
    _geo_proc._arcpy_gov_process_funcs.clear()
    _geo_proc.ARCPY_AVAILABLE = False
    print("[bird-pg] ArcPy tools disabled for benchmark run.")

    from sqlalchemy import text as _text  # noqa: E402
    from google import genai as genai_client  # noqa: E402
    from google.genai import types as _types  # noqa: E402
    from data_agent.db_engine import get_engine as _get_engine  # noqa: E402
    from data_agent.eval_history import ensure_eval_table as _ensure_eval_table, record_eval_result as _record_eval_result  # noqa: E402

    text = _text
    types = _types
    get_engine = _get_engine
    ensure_eval_table = _ensure_eval_table
    record_eval_result = _record_eval_result
    _client = genai_client.Client()


# ============================================================================
# Question loading
# ============================================================================

def load_questions(questions_path: Path,
                   limit: int | None = None,
                   difficulties: set[str] | None = None,
                   db_ids: set[str] | None = None) -> list[dict]:
    out: list[dict] = []
    with questions_path.open(encoding="utf-8") as f:
        data = json.load(f)
    for rec in data:
        if difficulties and rec.get("difficulty") not in difficulties:
            continue
        if db_ids and rec.get("db_id") not in db_ids:
            continue
        out.append(rec)
        if limit and len(out) >= limit:
            break
    return out


# ============================================================================
# Schema dump (cached per db_id for baseline)
# ============================================================================

_SCHEMA_CACHE: dict[str, str] = {}


def dump_schema(db_id: str) -> str:
    _init_runtime()
    if db_id in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[db_id]
    schema_pg = f"bird_{db_id}"
    engine = get_engine()
    lines: list[str] = []
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=:s ORDER BY table_name"
        ), {"s": schema_pg}).fetchall()]
        for t in tables:
            cols = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema=:s AND table_name=:t ORDER BY ordinal_position"
            ), {"s": schema_pg, "t": t}).fetchall()
            lines.append(f'CREATE TABLE "{t}" (')
            lines.append(",\n".join(f'  "{c[0]}" {c[1]}' for c in cols))
            lines.append(");\n")
    out = "\n".join(lines)
    _SCHEMA_CACHE[db_id] = out
    return out


# ============================================================================
# SQL execution against PG (with per-DB search_path)
# ============================================================================

def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip().rstrip(";").strip() if m else s.rstrip(";").strip()


def execute_pg(sql: str, db_id: str, timeout_ms: int = 30_000) -> dict:
    """Run SQL with search_path set to bird_<db_id>, public."""
    _init_runtime()
    engine = get_engine()
    if not engine:
        return {"status": "error", "rows": None, "error": "no engine"}
    if not sql:
        return {"status": "error", "rows": None, "error": "empty SQL"}

    schema_pg = f"bird_{db_id}"
    head = sql.strip().lstrip("(").lower()
    if not (head.startswith("select") or head.startswith("with")):
        return {"status": "error", "rows": None, "error": "non-SELECT"}

    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            conn.execute(text(f'SET LOCAL search_path TO "{schema_pg}", public'))
            res = conn.execute(text(sql))
            rows = res.fetchall()
        return {"status": "ok", "rows": [tuple(r) for r in rows]}
    except Exception as e:
        msg = str(e)
        return {"status": "timeout" if "timeout" in msg.lower() else "error",
                "rows": None, "error": msg}


def compare_results(gold_rows, pred_rows) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    if len(gold_rows) != len(pred_rows):
        return False

    def norm(v):
        if v is None: return ("__NULL__",)
        if isinstance(v, bool): return ("B", int(v))
        if isinstance(v, float):
            try: return ("F", round(v, 4))
            except Exception: return ("F", str(v))
        if isinstance(v, int): return ("I", v)
        from decimal import Decimal
        if isinstance(v, Decimal):
            try: return ("F", round(float(v), 4))
            except Exception: return ("S", str(v))
        return ("S", str(v))

    g = sorted(tuple(norm(c) for c in r) for r in gold_rows)
    p = sorted(tuple(norm(c) for c in r) for r in pred_rows)
    return g == p


# ============================================================================
# Mode A: Baseline (pure Gemini, schema dump prompt)
# ============================================================================

BASELINE_PROMPT = """You are a PostgreSQL SQL expert. Convert the user question into a single SELECT query.

Rules:
- Output ONLY the SQL, no commentary, no markdown fences.
- Use bare table names (search_path is preset to the correct schema).
- Use PostgreSQL syntax (CASE WHEN, NULLIF, ::numeric, etc. — NO SQLite IIF/SUBSTR-as-text-cast tricks).
- Do not add LIMIT unless the question explicitly asks for top-K.
- Use the evidence/hints when provided.
"""


def baseline_generate(question: str, db_id: str, evidence: str = "") -> dict:
    _init_runtime()
    schema = dump_schema(db_id)
    prompt = (
        BASELINE_PROMPT
        + f"\n\nSCHEMA:\n{schema}"
        + (f"\n\nEVIDENCE/HINTS:\n{evidence}" if evidence else "")
        + f"\n\nQUESTION: {question}\n\nSQL:"
    )
    try:
        resp = _client.models.generate_content(
            model=MODEL, contents=[prompt],
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    timeout=60_000,
                    retry_options=types.HttpRetryOptions(initial_delay=2.0, attempts=3)),
                temperature=0.0,
            ),
        )
    except Exception as e:
        return {"status": "error", "sql": "", "error": str(e), "tokens": 0}
    sql = _strip_fences(resp.text or "")
    tokens = 0
    if hasattr(resp, "usage_metadata") and resp.usage_metadata:
        tokens = (getattr(resp.usage_metadata, "prompt_token_count", 0) or 0) + \
                 (getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
    return {"status": "ok", "sql": sql, "error": None, "tokens": tokens}


# ============================================================================
# Mode B: Full pipeline (lazy import — heavy)
# ============================================================================

_full_agent = None
_full_session = None


def _lazy_init_full():
    global _full_agent, _full_session
    if _full_agent is None:
        # Use the focused NL2SQL agent (DatabaseToolset + SemanticLayerToolset only),
        # NOT the full general_pipeline. This isolates the NL→Semantic→SQL step
        # from the multi-agent product orchestration (intent router, viz, summary loop).
        from nl2sql_agent import get_nl2sql_agent
        from google.adk.sessions import InMemorySessionService
        _full_agent = get_nl2sql_agent()
        _full_session = InMemorySessionService()
    return _full_agent, _full_session


async def full_generate(question: str, db_id: str, evidence: str = "") -> dict:
    """Run full NL2Semantic2SQL pipeline (grounding + postprocess + self-correction)."""
    from data_agent.pipeline_runner import run_pipeline_headless

    agent, session_service = _lazy_init_full()
    schema_pg = f"bird_{db_id}"

    # Inject FULL schema (tables + columns) into the prompt, same as baseline gets.
    # This gives Agent information parity — baseline already sees the full DDL.
    schema_dump = dump_schema(db_id)

    prompt = (
        f"Database: PostgreSQL schema `{schema_pg}`.\n\n"
        f"SCHEMA:\n{schema_dump}\n"
        + (f"{evidence}\n\n" if evidence else "\n")
        + f"Question: {question}\n\n"
        + f"请按标准流程执行：先调用 prepare_nl2sql_context 获取 grounding，"
        + f"然后生成 SQL，最后调用 execute_nl2sql 执行。"
        + f"表名需要 schema 限定（如 `{schema_pg}.customers`）。"
    )

    sid = f"bird_{db_id}_{int(time.time() * 1000)}"
    try:
        result = await run_pipeline_headless(
            agent=agent, session_service=session_service,
            user_id="bird_benchmark", session_id=sid,
            prompt=prompt, pipeline_type="general", intent="GENERAL", role="analyst",
        )
    except Exception as e:
        return {"status": "exception", "sql": "", "error": str(e), "tokens": 0}

    # Extract SQL from execute_nl2sql or query_database tool calls
    pred_sql = ""
    for entry in (result.tool_execution_log or [])[::-1]:
        tool = entry.get("tool_name", "")
        if tool == "execute_nl2sql":
            pred_sql = entry.get("args", {}).get("sql", "") or ""
            if pred_sql:
                break
        elif tool == "query_database":
            pred_sql = entry.get("args", {}).get("sql_query", "") or ""
            if pred_sql:
                break

    return {
        "status": "ok" if pred_sql else "no_sql",
        "sql": pred_sql,
        "error": result.error,
        "tokens": (result.total_input_tokens + result.total_output_tokens),
        "duration": result.duration_seconds,
    }


# ============================================================================
# Resume cache
# ============================================================================

def open_cache(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = _sqlite3.connect(str(p))
    conn.execute("CREATE TABLE IF NOT EXISTS done (qid INTEGER, mode TEXT, payload TEXT, PRIMARY KEY(qid, mode))")
    return conn


def cache_get(conn, qid: int, mode: str) -> dict | None:
    row = conn.execute("SELECT payload FROM done WHERE qid=? AND mode=?", (qid, mode)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(conn, qid: int, mode: str, payload: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO done VALUES (?, ?, ?)",
                 (qid, mode, json.dumps(payload, default=str, ensure_ascii=False)))
    conn.commit()


# ============================================================================
# Main loop
# ============================================================================

async def run_one(q: dict, mode: str) -> dict:
    qid = q["question_id"]
    db_id = q["db_id"]
    evidence = q.get("evidence", "")
    gold_sql = q.get("SQL", "")

    from data_agent.nl2sql_intent import classify_intent
    _intent_result = classify_intent(q["question"])
    intent_value = _intent_result.primary.value
    intent_source = _intent_result.source

    # Generate
    if mode == "baseline":
        gen = baseline_generate(q["question"], db_id, evidence)
    else:
        gen = await full_generate(q["question"], db_id, evidence)

    pred_sql = gen.get("sql", "")
    pred_res = execute_pg(pred_sql, db_id) if pred_sql else {"status": "error", "rows": None}
    gold_res = execute_pg(gold_sql, db_id)

    is_valid = pred_res["status"] == "ok"
    is_correct = is_valid and gold_res["status"] == "ok" and \
                 compare_results(gold_res["rows"], pred_res["rows"])

    rec = {
        "qid": qid, "db_id": db_id, "difficulty": q.get("difficulty", "?"),
        "question": q["question"], "gold_sql": gold_sql, "pred_sql": pred_sql,
        "ex": 1 if is_correct else 0, "valid": 1 if is_valid else 0,
        "gen_status": gen.get("status"), "gen_error": gen.get("error"),
        "pred_error": pred_res.get("error"), "gold_status": gold_res["status"],
        "tokens": gen.get("tokens", 0),
    }
    rec["intent"] = intent_value
    rec["intent_source"] = intent_source
    return rec


async def main() -> int:
    _init_runtime()
    p = build_arg_parser()
    args = p.parse_args()

    layout = resolve_bird_layout(args.bird_root)
    pg_questions = layout["pg_questions"]
    results_root = layout["results_root"]

    diffs = set(args.difficulty.split(",")) if args.difficulty else None
    dbs = set(args.db_id.split(",")) if args.db_id else None

    questions = load_questions(questions_path=pg_questions, limit=args.limit, difficulties=diffs, db_ids=dbs)
    print(f"[bird-pg] Loaded {len(questions)} questions, mode={args.mode}")

    out_dir = Path(args.out_dir) if args.out_dir else (
        results_root / f"bird_pg_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = open_cache(out_dir / "run_state.db")
    print(f"[bird-pg] Output: {out_dir}")

    ensure_eval_table()
    modes = ["baseline", "full"] if args.mode == "both" else [args.mode]
    summaries: dict[str, dict] = {}

    for mode in modes:
        print(f"\n=== {mode.upper()} ({len(questions)}) ===")
        recs: list[dict] = []
        for i, q in enumerate(questions, 1):
            cached = cache_get(cache, q["question_id"], mode)
            if cached:
                recs.append(cached)
                m = "OK" if cached.get("ex") else ("VAL" if cached.get("valid") else "ERR")
                print(f"  [{i}/{len(questions)}] {m} {q['question_id']} (cached)")
                continue
            try:
                rec = await asyncio.wait_for(run_one(q, mode), timeout=180)
            except asyncio.TimeoutError:
                rec = {
                    "qid": q["question_id"], "db_id": q["db_id"],
                    "difficulty": q.get("difficulty", "?"), "question": q["question"],
                    "gold_sql": q.get("SQL", ""), "pred_sql": "",
                    "ex": 0, "valid": 0, "gen_status": "timeout", "gen_error": "180s timeout",
                    "pred_error": "", "gold_status": "?", "tokens": 0,
                    "intent": "unknown", "intent_source": "fallback",
                }
            except Exception as e:
                rec = {
                    "qid": q["question_id"], "db_id": q["db_id"],
                    "difficulty": q.get("difficulty", "?"), "question": q["question"],
                    "gold_sql": q.get("SQL", ""), "pred_sql": "",
                    "ex": 0, "valid": 0, "gen_status": "exception", "gen_error": str(e),
                    "pred_error": "", "gold_status": "?", "tokens": 0,
                    "intent": "unknown", "intent_source": "fallback",
                }
            recs.append(rec)
            cache_put(cache, q["question_id"], mode, rec)
            m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
            print(f"  [{i}/{len(questions)}] {m} {rec['qid']} ({rec['difficulty']}) db={rec['db_id']}")

        # Summarize
        n = len(recs)
        ex = sum(r["ex"] for r in recs)
        valid = sum(r["valid"] for r in recs)
        by_diff = {}
        for r in recs:
            d = r.get("difficulty", "?")
            by_diff.setdefault(d, [0, 0])
            by_diff[d][0] += 1
            by_diff[d][1] += r["ex"]
        diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())}

        summary = {
            "mode": mode, "model": MODEL, "n": n,
            "execution_accuracy": round(ex / n if n else 0, 4),
            "execution_valid_rate": round(valid / n if n else 0, 4),
            "by_difficulty": diff_breakdown,
            "generated_at": datetime.now().isoformat(),
        }
        summaries[mode] = summary

        # Persist
        (out_dir / f"{mode}_results.json").write_text(
            json.dumps({"summary": summary, "records": recs},
                       indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\n[bird-pg/{mode}] EX={summary['execution_accuracy']:.3f} "
              f"({ex}/{n}), Valid={summary['execution_valid_rate']:.3f}")
        print(f"  by difficulty: {diff_breakdown}")

        record_eval_result(
            pipeline=f"nl2sql_bird_pg_{mode}",
            overall_score=summary["execution_accuracy"],
            pass_rate=summary["execution_accuracy"],
            verdict="PASS" if summary["execution_accuracy"] >= 0.5 else "FAIL",
            num_tests=n, num_passed=ex,
            model=MODEL, scenario="bird_mini_dev_pg", metrics=summary,
        )

    # A/B comparison
    if "baseline" in summaries and "full" in summaries:
        b = summaries["baseline"]["execution_accuracy"]
        f = summaries["full"]["execution_accuracy"]
        print(f"\n{'=' * 60}")
        print(f"A/B  baseline EX={b:.3f}  full EX={f:.3f}  delta={f - b:+.3f}")
        print(f"{'=' * 60}")

    print(f"\n[bird-pg] Output dir: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
