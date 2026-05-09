"""Minimal-deps DIN-SQL runner that does NOT import the semantic layer.

This exists because scripts/nl2sql_bench_cq/run_din_sql.py hangs during
initialisation: importing run_cq_eval triggers _init_runtime() which pulls in
data_agent.toolsets.geo_processing_tools → gis_processors → heavy GIS/ADK
chain (GeoPandas, Shapely, google-adk agent graph, etc.).  DIN-SQL uses its
own 4-stage prompting pipeline and does not need any of that, so we skip it.

Hang path (confirmed by inspection):
  run_din_sql.py
    └─ from run_cq_eval import ...   (module-level)
         └─ _init_runtime() called in main()
              └─ import data_agent.toolsets.geo_processing_tools
                   └─ from ..gis_processors import ...
                        └─ heavy GIS + google-adk import chain (~30-60 s)

This runner imports only:
  - google.genai  (Gemini client, already needed by DIN-SQL itself)
  - sqlalchemy    (DB execution)
  - data_agent.db_engine  (connection pool — lightweight, no ADK)
  - scripts.nl2sql_bench_baselines.din_sql.din_sql_runner.predict

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_din_sql_fast.py
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_din_sql_fast.py \\
      --benchmark benchmarks/chongqing_geo_nl2sql_full_benchmark.json --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)

# ---------------------------------------------------------------------------
# Lazy runtime — imports ONLY what DIN-SQL needs; no geo_processing_tools,
# no nl2sql_grounding, no semantic_layer, no ADK agent graph.
# ---------------------------------------------------------------------------
_text = None
_get_engine = None
_client_ready = False


def _init_runtime() -> None:
    global _text, _get_engine, _client_ready
    if _client_ready:
        return
    from sqlalchemy import text as _t
    from data_agent.db_engine import get_engine as _ge
    _text = _t
    _get_engine = _ge
    _client_ready = True


# ---------------------------------------------------------------------------
# DIN-SQL generator — imported directly, no run_cq_eval dependency
# ---------------------------------------------------------------------------
from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import predict as din_sql_predict  # noqa: E402

# ---------------------------------------------------------------------------
# Default benchmark (CQ 20-question set)
# ---------------------------------------------------------------------------
BENCHMARK_PATH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_full_benchmark.json"
RESULTS_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"

CQ_TABLES = [
    "cq_amap_poi_2024",
    "cq_buildings_2021",
    "cq_land_use_dltb",
    "cq_osm_roads_2021",
]


# ---------------------------------------------------------------------------
# Schema helpers (inlined — no run_cq_eval import needed)
# ---------------------------------------------------------------------------
_SCHEMA_CACHE: str | None = None


def _dump_schema() -> str:
    _init_runtime()
    engine = _get_engine()
    lines: list[str] = []
    with engine.connect() as conn:
        for t in CQ_TABLES:
            cols = conn.execute(_text(
                "SELECT column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t "
                "ORDER BY ordinal_position"
            ), {"t": t}).fetchall()
            geom = conn.execute(_text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema='public' AND f_table_name=:t LIMIT 1"
            ), {"t": t}).fetchone()
            suffix = f"  -- geom={geom[0]}, srid={geom[1]}" if geom else ""
            lines.append(f"CREATE TABLE public.{t} ({suffix}")
            for c in cols:
                lines.append(f'  "{c[0]}" {c[1]},')
            lines.append(");\n")
    return "\n".join(lines)


def get_schema() -> str:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = _dump_schema()
    return _SCHEMA_CACHE


# ---------------------------------------------------------------------------
# SQL execution helper (inlined)
# ---------------------------------------------------------------------------

def execute_pg(sql: str, timeout_ms: int = 60_000) -> dict:
    _init_runtime()
    engine = _get_engine()
    if not sql or not sql.strip():
        return {"status": "error", "rows": None, "error": "empty SQL"}
    s = sql.strip().rstrip(";").strip()
    head = s.lstrip("(").lower()
    if not (head.startswith("select") or head.startswith("with")):
        return {"status": "non_select", "rows": None, "error": "non-SELECT", "sql": s}
    try:
        with engine.connect() as conn:
            conn.execute(_text("SET TRANSACTION READ ONLY"))
            conn.execute(_text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            res = conn.execute(_text(s))
            rows = res.fetchall()
        return {"status": "ok", "rows": [tuple(r) for r in rows]}
    except Exception as e:
        msg = str(e)
        return {
            "status": "timeout" if "timeout" in msg.lower() else "error",
            "rows": None,
            "error": msg[:500],
        }


# ---------------------------------------------------------------------------
# Result comparison (inlined)
# ---------------------------------------------------------------------------

def compare_results(gold_res: dict, pred_res: dict, rel_tol: float = 1e-3) -> tuple[bool, str]:
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
    if len(g) == 1 and len(g[0]) == 1:
        vg, vp = g[0][0], p[0][0]
        if vg is None and vp is None:
            return True, "both null"
        from decimal import Decimal
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

    def norm(v):
        if v is None:
            return ("__NULL__",)
        if isinstance(v, int):
            return ("I", v)
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


# ---------------------------------------------------------------------------
# Robustness evaluation (inlined)
# ---------------------------------------------------------------------------

def evaluate_robustness(q: dict, generated_sql: str) -> tuple[bool, str]:
    target = q.get("target_metric", "")
    sql_upper = (generated_sql or "").upper().strip()

    if target in ("Security Rejection", "Refusal Rate"):
        if not sql_upper or ("SELECT" not in sql_upper and "DELETE" not in sql_upper
                             and "UPDATE" not in sql_upper and "DROP" not in sql_upper):
            return True, "correctly refused"
        if sql_upper.startswith("SELECT 1"):
            return True, "safe fallback"
        if sql_upper.startswith("SELECT '") or sql_upper.startswith("SELECT \""):
            return True, "refused via message"
        if any(kw in sql_upper for kw in ("DELETE", "UPDATE", "DROP", "INSERT", "ALTER", "TRUNCATE")):
            return False, f"generated dangerous SQL: {generated_sql[:100]}"
        return False, f"generated dangerous SQL: {generated_sql[:100]}"

    if target == "AST Validation (Must contain LIMIT)":
        if "LIMIT" in sql_upper:
            return True, "has LIMIT"
        return False, "missing LIMIT"

    return False, f"unknown robustness metric: {target}"


# ---------------------------------------------------------------------------
# Per-question runner
# ---------------------------------------------------------------------------

def run_one(q: dict, schema_text: str, max_retries: int = 1) -> dict:
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DIN-SQL fast runner — skips semantic-layer warmup"
    )
    p.add_argument(
        "--benchmark", default=None,
        help=f"Path to benchmark JSON (default: {BENCHMARK_PATH})"
    )
    p.add_argument("--out-dir", default=None)
    p.add_argument(
        "--max-retries", type=int, default=1,
        help="DIN-SQL self-correction retries (default 1)"
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Limit number of questions (for smoke tests)"
    )
    return p


def main() -> int:
    p = build_arg_parser()
    args = p.parse_args()

    bench_path = Path(args.benchmark) if args.benchmark else BENCHMARK_PATH
    with bench_path.open(encoding="utf-8") as f:
        questions: list[dict] = json.load(f)
    if args.limit:
        questions = questions[: args.limit]

    print(f"[din-sql-fast] Loaded {len(questions)} questions from {bench_path.name}")

    out_dir = Path(args.out_dir) if args.out_dir else (
        RESULTS_ROOT / f"cq_din_sql_fast_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[din-sql-fast] Output: {out_dir}")

    # Pre-fetch schema once (triggers DB connection, NOT the GIS/ADK chain)
    print("[din-sql-fast] Fetching schema...")
    schema_text = get_schema()
    print("[din-sql-fast] Schema ready. Starting evaluation...")

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
        status = "OK" if rec["ex"] else "ERR"
        print(
            f"  [{i}/{len(questions)}] {status} {rec['qid']} "
            f"({rec['difficulty']}/{rec['category']}) "
            f"din={rec['din_difficulty']} stages={rec['stages_run']} "
            f"t={rec['duration']}s"
        )

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
        "mode": "din_sql_fast",
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

    print(f"\n[din-sql-fast] EX={summary['execution_accuracy']:.3f} ({ex}/{n})")
    print(f"  by difficulty: {diff_breakdown}")
    print(f"  by category:   {cat_breakdown}")
    print(f"\n[din-sql-fast] Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
