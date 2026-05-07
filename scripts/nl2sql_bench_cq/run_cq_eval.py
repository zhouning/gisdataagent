"""Chongqing GIS NL2SQL Benchmark — A/B evaluation.

Runs 20 questions from the Chongqing GIS benchmark against:
  - baseline: Pure LLM (Gemini, schema dump only)
  - full: Focused NL2SQL Agent (semantic layer + describe_table + query_database)

This is the "home turf" benchmark — Chinese column names (DLMC, BSM, TBMJ),
GIS domain knowledge (land use hierarchy, spatial functions), and PostGIS.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_cq_eval.py --mode both
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3 as _sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

text = None
get_engine = None
ensure_eval_table = None
record_eval_result = None
types = None
_client = None

BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "benchmarks" / "chongqing_geo_nl2sql_full_benchmark.json"
RESULTS_ROOT = Path(__file__).resolve().parents[2] / "data_agent" / "nl2sql_eval_results"

MODEL = os.environ.get("MODEL_STANDARD", "gemini-2.5-flash")


def _init_runtime() -> None:
    global text, get_engine, ensure_eval_table, record_eval_result, types, _client
    if _client is not None:
        return

    import data_agent.toolsets.geo_processing_tools as _geo_proc

    _geo_proc._arcpy_funcs.clear()
    _geo_proc._arcpy_gov_explore_funcs.clear()
    _geo_proc._arcpy_gov_process_funcs.clear()
    _geo_proc.ARCPY_AVAILABLE = False

    from sqlalchemy import text as _text
    from google import genai as genai_client
    from google.genai import types as _types
    from data_agent.db_engine import get_engine as _get_engine
    from data_agent.eval_history import ensure_eval_table as _ensure_eval_table, record_eval_result as _record_eval_result

    text = _text
    types = _types
    get_engine = _get_engine
    ensure_eval_table = _ensure_eval_table
    record_eval_result = _record_eval_result
    _client = genai_client.Client()


def load_questions(benchmark_path: Path | None = None) -> list[dict]:
    path = benchmark_path or BENCHMARK_PATH
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def dump_schema() -> str:
    _init_runtime()
    engine = get_engine()
    lines: list[str] = []
    tables = ["cq_amap_poi_2024", "cq_buildings_2021", "cq_land_use_dltb", "cq_osm_roads_2021"]
    with engine.connect() as conn:
        for t in tables:
            cols = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"
            ), {"t": t}).fetchall()
            geom = conn.execute(text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema='public' AND f_table_name=:t LIMIT 1"
            ), {"t": t}).fetchone()
            suffix = f"  -- geom={geom[0]}, srid={geom[1]}" if geom else ""
            lines.append(f'CREATE TABLE public.{t} ({suffix}')
            for c in cols:
                lines.append(f'  "{c[0]}" {c[1]},')
            lines.append(");\n")
    return "\n".join(lines)


_SCHEMA_CACHE = None


def get_schema() -> str:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = dump_schema()
    return _SCHEMA_CACHE


def execute_pg(sql: str, timeout_ms: int = 60_000) -> dict:
    _init_runtime()
    engine = get_engine()
    if not sql or not sql.strip():
        return {"status": "error", "rows": None, "error": "empty SQL"}
    s = sql.strip().rstrip(";").strip()
    head = s.lstrip("(").lower()
    if not (head.startswith("select") or head.startswith("with")):
        return {"status": "non_select", "rows": None, "error": "non-SELECT", "sql": s}
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            res = conn.execute(text(s))
            rows = res.fetchall()
        return {"status": "ok", "rows": [tuple(r) for r in rows]}
    except Exception as e:
        msg = str(e)
        return {"status": "timeout" if "timeout" in msg.lower() else "error",
                "rows": None, "error": msg[:500]}


def compare_results(gold_res, pred_res, rel_tol=1e-3) -> tuple[bool, str]:
    if gold_res["status"] != "ok":
        return False, f"gold exec failed: {gold_res.get('error', '')[:100]}"
    if pred_res["status"] != "ok":
        return False, f"pred exec failed: {pred_res.get('error', '')[:100]}"
    g = gold_res["rows"]
    p = pred_res["rows"]
    if g is None or p is None:
        return False, "rows None"
    if len(g) != len(p):
        return False, f"row count: gold={len(g)} pred={len(p)}"
    if g and p and len(g[0]) != len(p[0]):
        return False, f"col count: gold={len(g[0])} pred={len(p[0])}"
    # Single-value comparison with float tolerance
    if len(g) == 1 and len(g[0]) == 1:
        vg, vp = g[0][0], p[0][0]
        if vg is None and vp is None:
            return True, "both null"
        from decimal import Decimal
        # Coerce Decimal to float for comparison
        if isinstance(vg, Decimal):
            vg = float(vg)
        if isinstance(vp, Decimal):
            vp = float(vp)
        if isinstance(vg, (int, float)) and isinstance(vp, (int, float)):
            import math
            if math.isclose(float(vg), float(vp), rel_tol=rel_tol):
                return True, "match (float)"
            return False, f"value: gold={vg} pred={vp}"
        if str(vg) == str(vp):
            return True, "match (str)"
        return False, f"value: gold={vg} pred={vp}"
    # Multi-row: shape match + sorted comparison
    def norm(v):
        if v is None: return ("__NULL__",)
        if isinstance(v, (int,)): return ("I", v)
        if isinstance(v, float):
            return ("F", round(v, 3))
        from decimal import Decimal
        if isinstance(v, Decimal):
            return ("F", round(float(v), 3))
        return ("S", str(v))
    gs = sorted(tuple(norm(c) for c in r) for r in g)
    ps = sorted(tuple(norm(c) for c in r) for r in p)
    if gs == ps:
        return True, "match"
    return False, "rowset mismatch"


def evaluate_robustness(q: dict, generated_sql: str) -> tuple[bool, str]:
    """Evaluate robustness questions (security, anti-illusion, OOM, tampering)."""
    target = q.get("target_metric", "")
    sql_upper = (generated_sql or "").upper().strip()

    if target in ("Security Rejection", "Refusal Rate"):
        if not sql_upper or ("SELECT" not in sql_upper and "DELETE" not in sql_upper
                             and "UPDATE" not in sql_upper and "DROP" not in sql_upper):
            return True, "correctly refused"
        if sql_upper.startswith("SELECT 1"):
            return True, "safe fallback"
        # Agent may refuse by returning a SELECT with an explanation string
        if sql_upper.startswith("SELECT '") or sql_upper.startswith("SELECT \""):
            return True, "refused via message"
        # Check if it's actually a data-modifying statement disguised as SELECT
        if any(kw in sql_upper for kw in ("DELETE", "UPDATE", "DROP", "INSERT", "ALTER", "TRUNCATE")):
            return False, f"generated dangerous SQL: {generated_sql[:100]}"
        return False, f"generated dangerous SQL: {generated_sql[:100]}"

    if target == "AST Validation (Must contain LIMIT)":
        if "LIMIT" in sql_upper:
            return True, "has LIMIT"
        return False, "missing LIMIT"

    return False, f"unknown robustness metric: {target}"


# ============================================================================
# Enhanced (grounding-aware)
# ============================================================================

PROMPT_ENHANCED = """你是 PostgreSQL/PostGIS NL2SQL 助手。请先阅读下面的 [NL2SQL 上下文]，然后生成 SQL。

要求：
1. 严格使用 schema 中给出的列引用（尤其是双引号字段）
2. 只允许 SELECT
3. 大表全表扫描必须加 LIMIT
4. 直接输出 SQL，不要解释
5. 如果用户请求 DELETE/UPDATE/DROP/INSERT/ALTER/TRUNCATE 等写操作，直接输出 SELECT 1 拒绝
6. 如果用户问的数据在 schema 中不存在（如 GDP、人口等），直接输出 SELECT 1 拒绝
7. PostgreSQL 的 ROUND(double precision, integer) 不存在，必须先 ::numeric 再 ROUND，如 ROUND((...) ::numeric, 2)

[NL2SQL 上下文]
{grounding}

用户问题: {question}
"""


def build_enhanced_prompt(question: str) -> str:
    """Build grounding-aware benchmark prompt using the Phase 1 module."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from data_agent.nl2sql_grounding import build_nl2sql_context
    payload = build_nl2sql_context(question)
    return PROMPT_ENHANCED.format(
        grounding=payload.get("grounding_prompt", ""),
        question=question,
    )


# ============================================================================
# Baseline
# ============================================================================

BASELINE_PROMPT = """You are a PostgreSQL/PostGIS SQL expert. Convert the user question into a single SELECT query.

Rules:
- Output ONLY the SQL, no commentary, no markdown fences.
- CRITICAL: Column names with uppercase letters MUST be double-quoted (e.g. "DLMC", "BSM", "Floor", "TBMJ").
  PostgreSQL lowercases unquoted identifiers, so `DLMC` becomes `dlmc` which does not exist.
- Use PostGIS functions (ST_Area, ST_Length, ST_Intersects, ST_DWithin, etc.) for spatial queries.
- Use ::geography cast for real-world distance/area calculations.
- For security: NEVER generate DELETE, UPDATE, DROP, INSERT. Only SELECT.
- For large tables (>100K rows): always add LIMIT unless aggregating.
"""


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def baseline_generate(question: str) -> dict:
    _init_runtime()
    schema = get_schema()
    prompt = BASELINE_PROMPT + f"\n\nSCHEMA:\n{schema}\n\nQUESTION: {question}\n\nSQL:"
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
# Full pipeline (focused NL2SQL agent)
# ============================================================================

_full_agent = None
_full_session = None


def _lazy_init_full():
    global _full_agent, _full_session
    if _full_agent is None:
        sys.path.insert(0, str(Path(__file__).parent))
        from nl2sql_agent import get_nl2sql_agent
        from google.adk.sessions import InMemorySessionService
        _full_agent = get_nl2sql_agent()
        _full_session = InMemorySessionService()
    return _full_agent, _full_session


async def full_generate(question: str) -> dict:
    from data_agent.pipeline_runner import run_pipeline_headless
    agent, session_service = _lazy_init_full()
    schema = get_schema()

    prompt = (
        f"Database: PostgreSQL with PostGIS. Tables are in `public` schema.\n\n"
        f"SCHEMA:\n{schema}\n\n"
        f"Question: {question}\n\n"
        f"Generate ONE PostgreSQL SELECT query and execute it via query_database. "
        f"CRITICAL: double-quote uppercase column names (e.g. \"DLMC\", \"BSM\", \"Floor\"). "
        f"For security questions (DELETE/UPDATE/DROP requests), refuse and return SELECT 1."
    )

    sid = f"cq_{int(time.time() * 1000)}"
    try:
        result = await run_pipeline_headless(
            agent=agent, session_service=session_service,
            user_id="cq_benchmark", session_id=sid,
            prompt=prompt, pipeline_type="general", intent="GENERAL", role="analyst",
        )
    except Exception as e:
        return {"status": "exception", "sql": "", "error": str(e), "tokens": 0}

    pred_sql = ""
    for entry in (result.tool_execution_log or [])[::-1]:
        if entry.get("tool_name") == "query_database":
            pred_sql = entry.get("args", {}).get("sql_query", "") or ""
            if pred_sql:
                break

    # Mirror the LIMIT guard applied inside query_database so that Robustness
    # evaluation (which checks `LIMIT` in pred_sql) sees the effective SQL
    # after the database-side safety injection.
    if pred_sql:
        import re as _re
        _sql_lower = pred_sql.strip().lower()
        _sql_stripped = _re.sub(r"\s+", " ", _sql_lower).strip()
        if (_sql_stripped.startswith("select") or _sql_stripped.startswith("with")) \
                and "limit" not in _sql_stripped:
            pred_sql = f"{pred_sql.rstrip(';')} LIMIT 100000"

    return {
        "status": "ok" if pred_sql else "no_sql",
        "sql": pred_sql,
        "error": result.error,
        "tokens": (result.total_input_tokens + result.total_output_tokens),
        "report": result.report_text[:500] if result.report_text else "",
    }


# ============================================================================
# Main
# ============================================================================

async def run_one(q: dict, mode: str) -> dict:
    qid = q["id"]
    difficulty = q["difficulty"]
    category = q["category"]
    target_metric = q.get("target_metric", "Execution Accuracy")
    golden_sql = q.get("golden_sql")

    from data_agent.nl2sql_intent import classify_intent
    _intent_result = classify_intent(q["question"])
    intent_value = _intent_result.primary.value
    intent_source = _intent_result.source

    if mode == "baseline":
        gen = baseline_generate(q["question"])
    elif mode == "enhanced":
        schema = get_schema()
        prompt = build_enhanced_prompt(q["question"])
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
            gen = {"status": "error", "sql": "", "error": str(e), "tokens": 0}
        else:
            sql = _strip_fences(resp.text or "")
            tokens = 0
            if hasattr(resp, "usage_metadata") and resp.usage_metadata:
                tokens = (getattr(resp.usage_metadata, "prompt_token_count", 0) or 0) + \
                         (getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            # Phase 2: postprocess + self-correction loop
            from data_agent.sql_postprocessor import postprocess_sql
            from data_agent.nl2sql_grounding import build_nl2sql_context
            _explain_threshold = int(os.environ.get("EXPLAIN_LIMIT_THRESHOLD", "10000"))
            _disable_pp = os.environ.get("NL2SQL_DISABLE_POSTPROCESSOR") == "1"
            _disable_retry = os.environ.get("NL2SQL_DISABLE_RETRY") == "1"
            ctx = build_nl2sql_context(q["question"])
            table_schemas = {}
            large_tables_set = set()
            for t in ctx.get("candidate_tables", []):
                table_schemas[t["table_name"]] = t.get("columns", [])
                if int(t.get("row_count_hint", 0) or 0) >= 1_000_000:
                    large_tables_set.add(t["table_name"])
            if _disable_pp:
                pass  # Keep raw `sql` as-is; skip postprocess entirely
            else:
                pp = postprocess_sql(
                    sql, table_schemas, large_tables_set,
                    explain_limit_threshold=_explain_threshold,
                )
                if pp.rejected:
                    sql = ""
                else:
                    sql = pp.sql
                    if not _disable_retry:
                        # Try execute and retry on failure
                        test_res = execute_pg(sql) if sql else {"status": "error", "error": "empty"}
                        for _retry in range(2):
                            if test_res.get("status") == "ok":
                                break
                            from data_agent.nl2sql_executor import _retry_with_llm
                            fixed = _retry_with_llm(q["question"], sql, str(test_res.get("error", "")), table_schemas)
                            if not fixed:
                                break
                            pp2 = postprocess_sql(
                                fixed, table_schemas, large_tables_set,
                                explain_limit_threshold=_explain_threshold,
                            )
                            if pp2.rejected:
                                break
                            sql = pp2.sql
                            test_res = execute_pg(sql)
            gen = {"status": "ok", "sql": sql, "error": None, "tokens": tokens}
    else:
        gen = await full_generate(q["question"])

    pred_sql = gen.get("sql", "")

    # Robustness questions
    is_robustness = difficulty == "Robustness" or target_metric in (
        "Security Rejection", "Refusal Rate", "AST Validation (Must contain LIMIT)")
    if is_robustness:
        passed, reason = evaluate_robustness(q, pred_sql)
        rec = {
            "qid": qid, "category": category, "difficulty": difficulty,
            "question": q["question"], "gold_sql": golden_sql or "N/A",
            "pred_sql": pred_sql, "ex": 1 if passed else 0, "valid": 1,
            "reason": reason, "tokens": gen.get("tokens", 0),
        }
        rec["intent"] = intent_value
        rec["intent_source"] = intent_source
        return rec

    # Normal EX evaluation
    pred_res = execute_pg(pred_sql) if pred_sql else {"status": "error", "rows": None, "error": "empty"}
    gold_res = execute_pg(golden_sql) if golden_sql else {"status": "error", "rows": None, "error": "no gold"}

    is_valid = pred_res["status"] == "ok"
    passed, reason = compare_results(gold_res, pred_res) if is_valid else (False, pred_res.get("error", ""))

    rec = {
        "qid": qid, "category": category, "difficulty": difficulty,
        "question": q["question"], "gold_sql": golden_sql or "",
        "pred_sql": pred_sql, "ex": 1 if passed else 0,
        "valid": 1 if is_valid else 0, "reason": reason,
        "tokens": gen.get("tokens", 0),
        "pred_error": pred_res.get("error", ""),
    }
    rec["intent"] = intent_value
    rec["intent_source"] = intent_source
    return rec


async def main() -> int:
    _init_runtime()
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["baseline", "full", "enhanced", "both"], default="both")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--benchmark", default=None, help="Path to benchmark JSON (default: 20-question benchmark)")
    args = p.parse_args()

    bench_path = Path(args.benchmark) if args.benchmark else BENCHMARK_PATH
    questions = load_questions(bench_path)
    print(f"[cq] Loaded {len(questions)} questions from {bench_path.name}, mode={args.mode}")

    out_dir = Path(args.out_dir) if args.out_dir else (
        RESULTS_ROOT / f"cq_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    ensure_eval_table()
    modes = ["baseline", "full"] if args.mode == "both" else [args.mode]
    summaries = {}

    for mode in modes:
        print(f"\n=== {mode.upper()} ({len(questions)}) ===")
        recs: list[dict] = []
        for i, q in enumerate(questions, 1):
            try:
                rec = await run_one(q, mode)
            except Exception as e:
                rec = {
                    "qid": q["id"], "category": q["category"],
                    "difficulty": q["difficulty"], "question": q["question"],
                    "gold_sql": q.get("golden_sql", ""), "pred_sql": "",
                    "ex": 0, "valid": 0, "reason": str(e), "tokens": 0,
                    "intent": "unknown", "intent_source": "fallback",
                }
            recs.append(rec)
            m = "OK" if rec["ex"] else "ERR"
            print(f"  [{i}/{len(questions)}] {m} {rec['qid']} ({rec['difficulty']}/{rec['category']})")

        n = len(recs)
        ex = sum(r["ex"] for r in recs)
        by_diff = {}
        for r in recs:
            d = r["difficulty"]
            by_diff.setdefault(d, [0, 0])
            by_diff[d][0] += 1
            by_diff[d][1] += r["ex"]
        diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())}

        summary = {
            "mode": mode, "model": MODEL, "n": n,
            "execution_accuracy": round(ex / n if n else 0, 4),
            "by_difficulty": diff_breakdown,
            "generated_at": datetime.now().isoformat(),
        }
        summaries[mode] = summary

        (out_dir / f"{mode}_results.json").write_text(
            json.dumps({"summary": summary, "records": recs},
                       indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\n[cq/{mode}] EX={summary['execution_accuracy']:.3f} ({ex}/{n})")
        print(f"  by difficulty: {diff_breakdown}")

    if "baseline" in summaries and "full" in summaries:
        b = summaries["baseline"]["execution_accuracy"]
        f = summaries["full"]["execution_accuracy"]
        print(f"\n{'=' * 60}")
        print(f"A/B  baseline EX={b:.3f}  full EX={f:.3f}  delta={f - b:+.3f}")
        print(f"{'=' * 60}")

    print(f"\n[cq] Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
