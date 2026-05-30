"""v7 P0-d — Single-family error-driven iteration runner.

Runs Gemini 2.5-flash on the v7 business-lang benchmark (125 questions,
both baseline and full modes), then bins failures into four buckets so
the catalog/dialect/golden/safety remediation work has a structured
attack list.

Differences from `run_cq_eval.py`:
  - Reads `chongqing_geo_nl2sql_125q_business_lang.json` and uses
    `question_business` as the model input (NOT `question`).
  - Carries `question_original` + `golden_sql_v6_original` (when present)
    into the result records for forensic comparison.
  - After both modes finish, classifies each failure into one of:
      * `catalog`  — column-name aliasing / value-pattern issues that
                     a richer semantic catalog could fix
      * `dialect`  — PostgreSQL-specific things like ROUND(double,int),
                     ::geography casts, GROUP BY ordinal usage
      * `golden`   — golden SQL itself returns 0 rows or PG error
                     (should be 0 after P0-b but caught defensively)
      * `safety`   — refusal / OOM / AST-LIMIT issues (Robustness)
      * `unknown`  — none of the above; needs human review

Usage:
  cd D:\\adk
  $env:PYTHONPATH = "D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_v7_iteration.py --mode both
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

from run_cq_eval import (  # type: ignore
    _init_runtime, _strip_fences, baseline_generate,
    baseline_generate_family_aware, build_enhanced_prompt,
    compare_results, evaluate_robustness, execute_pg, full_generate,
    get_schema, types,
)

def _get_client():
    """Fetch the live _client from run_cq_eval module (after _init_runtime)."""
    import run_cq_eval
    return run_cq_eval._client

V7_BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang.json"
RESULTS_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


def load_v7_questions() -> list[dict]:
    rows = json.loads(V7_BENCH.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        if not r.get("question_business"):
            continue
        out.append({
            "id": r["id"],
            "question": r["question_business"],
            "question_v6_original": r.get("question_original"),
            "category": r.get("category"),
            "difficulty": r.get("difficulty"),
            "target_metric": r.get("target_metric"),
            "golden_sql": r.get("golden_sql"),
            "reasoning_points": r.get("reasoning_points", []),
        })
    return out


async def run_one(q: dict, mode: str) -> dict:
    qid = q["id"]
    difficulty = q["difficulty"]
    category = q["category"]
    target_metric = q.get("target_metric") or "Execution Accuracy"
    golden_sql = q.get("golden_sql")

    if mode == "baseline":
        # Use family-aware baseline so DeepSeek / Qwen / Gemma go through the
        # same BASELINE_PROMPT + raw schema-dump protocol as Gemini. The model
        # is picked up from NL2SQL_BASELINE_MODEL (set by the runner) or falls
        # back to the module-level MODEL constant.
        gen = baseline_generate_family_aware(q["question"])
    elif mode == "enhanced":
        # Enhanced mode — uses schema + grounding + 13 v7 rules + postprocessor + retry
        from run_cq_eval import MODEL
        import os as _os
        schema = get_schema()
        prompt = build_enhanced_prompt(q["question"])
        try:
            resp = _get_client().models.generate_content(
                model=MODEL, contents=[prompt],
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(
                        timeout=60_000,
                        retry_options=types.HttpRetryOptions(initial_delay=2.0, attempts=3)),
                    temperature=0.0,
                ),
            )
            sql = _strip_fences(resp.text or "")
            tokens = 0
            if hasattr(resp, "usage_metadata") and resp.usage_metadata:
                tokens = (getattr(resp.usage_metadata, "prompt_token_count", 0) or 0) + \
                         (getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            # Stage 3: postprocess + self-correction
            from data_agent.sql_postprocessor import postprocess_sql
            from data_agent.nl2sql_grounding import build_nl2sql_context
            _et = int(_os.environ.get("EXPLAIN_LIMIT_THRESHOLD", "10000"))
            _disable_pp = _os.environ.get("NL2SQL_DISABLE_POSTPROCESSOR") == "1"
            _disable_retry = _os.environ.get("NL2SQL_DISABLE_RETRY") == "1"
            ctx = build_nl2sql_context(q["question"])
            table_schemas = {}
            large_tables = set()
            for t in ctx.get("candidate_tables", []):
                table_schemas[t["table_name"]] = t.get("columns", [])
                if int(t.get("row_count_hint", 0) or 0) >= 1_000_000:
                    large_tables.add(t["table_name"])
            if not _disable_pp:
                pp = postprocess_sql(sql, table_schemas, large_tables,
                                     explain_limit_threshold=_et)
                if pp.rejected:
                    sql = ""
                else:
                    sql = pp.sql
                    if not _disable_retry:
                        test_res = execute_pg(sql) if sql else {"status": "error", "error": "empty"}
                        for _retry in range(2):
                            if test_res.get("status") == "ok":
                                break
                            from data_agent.nl2sql_executor import _retry_with_llm
                            fixed = _retry_with_llm(q["question"], sql,
                                                    str(test_res.get("error", "")),
                                                    table_schemas)
                            if not fixed:
                                break
                            pp2 = postprocess_sql(fixed, table_schemas, large_tables,
                                                  explain_limit_threshold=_et)
                            if pp2.rejected:
                                break
                            sql = pp2.sql
                            test_res = execute_pg(sql)
            gen = {"status": "ok", "sql": sql, "error": None, "tokens": tokens}
        except Exception as e:
            gen = {"status": "error", "sql": "", "error": str(e), "tokens": 0}
    elif mode == "full":
        gen = await full_generate(q["question"])
    else:
        raise ValueError(mode)

    pred_sql = gen.get("sql", "")
    is_robust = difficulty == "Robustness" or target_metric in (
        "Security Rejection", "Refusal Rate",
        "AST Validation (Must contain LIMIT)")
    if is_robust:
        passed, reason = evaluate_robustness(q, pred_sql)
        rec = {
            "qid": qid, "category": category, "difficulty": difficulty,
            "question": q["question"],
            "gold_sql": golden_sql or "N/A",
            "pred_sql": pred_sql,
            "ex": 1 if passed else 0, "valid": 1, "reason": reason,
            "tokens": gen.get("tokens", 0),
            "is_robust": True,
        }
        return rec
    pred_res = execute_pg(pred_sql) if pred_sql else {"status": "error", "rows": None, "error": "empty"}
    gold_res = execute_pg(golden_sql) if golden_sql else {"status": "error", "rows": None, "error": "no gold"}
    is_valid = pred_res["status"] == "ok"
    passed, reason = compare_results(gold_res, pred_res) if is_valid else (False, pred_res.get("error", ""))
    return {
        "qid": qid, "category": category, "difficulty": difficulty,
        "question": q["question"],
        "gold_sql": golden_sql or "",
        "pred_sql": pred_sql,
        "ex": 1 if passed else 0,
        "valid": 1 if is_valid else 0,
        "reason": reason,
        "tokens": gen.get("tokens", 0),
        "pred_error": pred_res.get("error", ""),
        "gold_error": gold_res.get("error", ""),
        "is_robust": False,
    }


# ---- failure classification ------------------------------------------------

def classify_failure(rec: dict) -> str:
    """Bin a failed row into one of {catalog, dialect, golden, safety, unknown}."""
    if rec["ex"] == 1:
        return "pass"
    reason = (rec.get("reason") or "").lower()
    perr = (rec.get("pred_error") or "").lower()
    gerr = (rec.get("gold_error") or "").lower()
    pred = (rec.get("pred_sql") or "").lower()
    if rec.get("is_robust"):
        return "safety"
    # Golden execution problems take precedence (shouldn't happen post P0-b)
    if gerr and "no gold" not in gerr:
        return "golden"
    # Dialect signatures
    if "round(double precision, integer)" in perr:
        return "dialect"
    if "operator does not exist" in perr:
        return "dialect"
    if "function" in perr and "does not exist" in perr:
        return "dialect"
    # Schema-level issues — column not found means catalog needs aliases
    if "column" in perr and "does not exist" in perr:
        return "catalog"
    if "relation" in perr and "does not exist" in perr:
        return "catalog"
    # Empty SQL = generation gave up
    if not pred:
        return "unknown"
    # Row-count mismatch / value mismatch likely indicates filter logic
    # error rooted in unmapped business term → catalog
    if "row count" in reason or "rowset mismatch" in reason or "value:" in reason:
        return "catalog"
    return "unknown"


async def main() -> int:
    _init_runtime()
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "full", "enhanced", "both"], default="both")
    ap.add_argument("--limit", type=int, default=None,
                    help="evaluate only first N questions (debug)")
    ap.add_argument("--out-tag", default="iteration1",
                    help="suffix for the output dir")
    args = ap.parse_args()

    questions = load_v7_questions()
    if args.limit:
        questions = questions[:args.limit]

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = RESULTS_ROOT / f"v7_{args.out_tag}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {"benchmark": V7_BENCH.name, "n": len(questions), "modes": {}}

    for mode in (["baseline", "full"] if args.mode == "both" else [args.mode]):
        print(f"\n=== Running mode={mode} on {len(questions)} questions ===\n", flush=True)
        records = []
        t0 = time.time()
        for i, q in enumerate(questions, 1):
            rec = await run_one(q, mode)
            records.append(rec)
            mark = "✓" if rec["ex"] else "✗"
            print(f"  [{i:>3}/{len(questions)}] {q['id']:<30} {mark} {rec.get('reason','')[:60]}",
                  flush=True)
            (out_dir / f"records_{mode}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                encoding="utf-8")
        dur = time.time() - t0
        ex = sum(r["ex"] for r in records)
        valid = sum(r.get("valid", 1) for r in records)
        print(f"\n[{mode}] EX={ex}/{len(records)} = {ex/len(records):.4f}  "
              f"valid={valid}/{len(records)}  wall={dur:.0f}s", flush=True)
        summary["modes"][mode] = {
            "ex": ex, "n": len(records),
            "ex_rate": ex / len(records),
            "valid": valid, "duration_sec": dur,
        }

        # Classification of failures
        bins = {"catalog": 0, "dialect": 0, "golden": 0,
                "safety": 0, "unknown": 0, "pass": 0}
        per_id = []
        for r in records:
            c = classify_failure(r)
            bins[c] += 1
            per_id.append({"qid": r["qid"], "ex": r["ex"], "bucket": c,
                           "reason": (r.get("reason") or "")[:120]})
        summary["modes"][mode]["failure_bins"] = bins
        (out_dir / f"failure_bins_{mode}.json").write_text(
            json.dumps({"bins": bins, "per_qid": per_id}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"[{mode}] failure bins: {bins}", flush=True)

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] results: {out_dir}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
