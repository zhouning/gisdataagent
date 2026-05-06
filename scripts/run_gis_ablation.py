"""Component-level ablation runner for GIS 100 benchmark.

IMPORTANT: This ablation runs on the SINGLE-PASS ENHANCED pipeline
(PROMPT_ENHANCED template + deterministic postprocessor + bounded retry),
which corresponds to the `enhanced` mode in run_cq_eval.py --- NOT the
`full` mode (which uses an ADK agent loop with multi-turn tool calls).

The GIS main table in the paper reports `full` (agent-loop) EX. The
`enhanced` single-pass EX is systematically lower because the agent loop
can iterate on tool feedback and call multiple tools per question.

The ablation is therefore INTERNAL TO THE ENHANCED PIPELINE and measures
component contributions within a controlled, deterministic baseline. This
is stated explicitly in the paper to avoid confusing ablation deltas with
main-table EX.

Runs 6 ablation configurations (all on enhanced single-pass):
  ablate_none:             full enhanced pipeline (grounding + postprocess + self-correct + intent routing + R2 rules)
  ablate_no_intent:        intent routing disabled (always UNKNOWN -> all rules injected)
  ablate_no_postprocess:   skip postprocess_sql (no LIMIT injection, no quoting fixes)
  ablate_no_selfcorrect:   skip the LLM-based retry on execution failure
  ablate_no_r2_rules:      strip R2 rule sections (DISTINCT / avoid-over-JOIN / output format)
  ablate_no_join_hints:    strip multi-hop warehouse join hints from grounding

Output: data_agent/nl2sql_eval_results/gis_ablation_<timestamp>/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[1] / "data_agent" / ".env"), override=True)

# Disable ArcPy before importing anything from data_agent
import data_agent.toolsets.geo_processing_tools as _geo_proc
_geo_proc._arcpy_funcs.clear()
_geo_proc._arcpy_gov_explore_funcs.clear()
_geo_proc._arcpy_gov_process_funcs.clear()
_geo_proc.ARCPY_AVAILABLE = False

# Now safe to import run_cq_eval helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "nl2sql_bench_cq"))
from run_cq_eval import (
    _init_runtime,
    load_questions,
    get_schema,
    execute_pg,
    compare_results,
    evaluate_robustness,
    _strip_fences,
    build_enhanced_prompt,
    PROMPT_ENHANCED,
    BENCHMARK_PATH,
    RESULTS_ROOT,
    MODEL,
)

ABLATIONS = ["none", "no_intent", "no_postprocess", "no_selfcorrect", "no_r2_rules", "no_join_hints"]


# Headers of R2-added rule sections (commit c03ece9). When ablating, we strip
# the section starting at the header up to the next `##` or end of string.
R2_RULE_HEADERS = (
    "## DISTINCT 使用规则",
    "## 避免过度 JOIN",
    "## 输出列格式",
)
JOIN_HINT_HEADER = "## 数据仓库 Join 路径提示"


def _strip_rule_sections(grounding: str, headers: tuple[str, ...]) -> str:
    """Remove lines from `## <header>` until the next `## ` or EOF."""
    if not grounding:
        return grounding
    out_lines: list[str] = []
    skip = False
    for line in grounding.splitlines():
        stripped = line.strip()
        if skip:
            if stripped.startswith("## "):
                # New section begins — stop skipping unless it's also a target
                skip = any(stripped == h.strip() for h in headers)
                if not skip:
                    out_lines.append(line)
            # else: still inside the section being stripped — drop the line
        else:
            if any(stripped == h.strip() for h in headers):
                skip = True
            else:
                out_lines.append(line)
    return "\n".join(out_lines)


def single_pass_generate(question: str, ablation: str) -> dict:
    """Single-pass enhanced mode with optional component ablation."""
    import run_cq_eval as cq
    cq._init_runtime()  # ensure _client/types/etc are initialized

    # Build grounding (with or without intent routing)
    from data_agent.nl2sql_grounding import build_nl2sql_context
    from data_agent.sql_postprocessor import postprocess_sql
    from data_agent.nl2sql_intent import IntentLabel

    if ablation == "no_intent":
        # Override classify_intent to always return UNKNOWN, forcing all-rule injection
        import data_agent.nl2sql_intent as ni
        from data_agent.nl2sql_intent import IntentResult
        original_classify = ni.classify_intent
        ni.classify_intent = lambda q: IntentResult(primary=IntentLabel.UNKNOWN, confidence=0.0, source="ablated")
        try:
            ctx = build_nl2sql_context(question)
        finally:
            ni.classify_intent = original_classify
    else:
        ctx = build_nl2sql_context(question)

    # Ablate R2 rule sections or join hints by stripping from grounding_prompt
    grounding_text = ctx.get("grounding_prompt", "")
    if ablation == "no_r2_rules":
        grounding_text = _strip_rule_sections(grounding_text, R2_RULE_HEADERS)
    elif ablation == "no_join_hints":
        grounding_text = _strip_rule_sections(grounding_text, (JOIN_HINT_HEADER,))

    # LLM generation with grounding prompt
    prompt = PROMPT_ENHANCED.format(
        grounding=grounding_text,
        question=question,
    )
    try:
        resp = cq._client.models.generate_content(
            model=MODEL, contents=[prompt],
            config=cq.types.GenerateContentConfig(
                http_options=cq.types.HttpOptions(
                    timeout=60_000,
                    retry_options=cq.types.HttpRetryOptions(initial_delay=2.0, attempts=3)),
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

    # Postprocess (or skip if ablated)
    table_schemas = {}
    large_tables_set = set()
    for t in ctx.get("candidate_tables", []):
        table_schemas[t["table_name"]] = t.get("columns", [])
        if int(t.get("row_count_hint", 0) or 0) >= 1_000_000:
            large_tables_set.add(t["table_name"])

    intent = ctx.get("intent")

    if ablation == "no_postprocess":
        # Skip postprocess entirely — use raw LLM SQL
        pass
    else:
        pp = postprocess_sql(sql, table_schemas, large_tables_set, intent=intent)
        if pp.rejected:
            sql = ""
        else:
            sql = pp.sql

    # Self-correction (or skip if ablated)
    if sql and ablation != "no_selfcorrect":
        test_res = execute_pg(sql)
        for _retry in range(2):
            if test_res.get("status") == "ok":
                break
            from data_agent.nl2sql_executor import _retry_with_llm
            fixed = _retry_with_llm(question, sql, str(test_res.get("error", "")), table_schemas)
            if not fixed:
                break
            if ablation == "no_postprocess":
                sql = fixed
            else:
                pp2 = postprocess_sql(fixed, table_schemas, large_tables_set, intent=intent)
                if pp2.rejected:
                    break
                sql = pp2.sql
            test_res = execute_pg(sql)

    return {"status": "ok" if sql else "no_sql", "sql": sql, "error": None, "tokens": tokens}


def run_one(q: dict, ablation: str) -> dict:
    qid = q["id"]
    difficulty = q["difficulty"]
    category = q["category"]
    target_metric = q.get("target_metric", "Execution Accuracy")
    golden_sql = q.get("golden_sql")

    gen = single_pass_generate(q["question"], ablation)
    pred_sql = gen.get("sql", "")

    is_robustness = difficulty == "Robustness" or target_metric in (
        "Security Rejection", "Refusal Rate", "AST Validation (Must contain LIMIT)")
    if is_robustness:
        passed, reason = evaluate_robustness(q, pred_sql)
        return {
            "qid": qid, "category": category, "difficulty": difficulty,
            "question": q["question"], "gold_sql": golden_sql or "N/A",
            "pred_sql": pred_sql, "ex": 1 if passed else 0, "valid": 1,
            "reason": reason, "tokens": gen.get("tokens", 0),
            "ablation": ablation,
        }

    pred_res = execute_pg(pred_sql) if pred_sql else {"status": "error", "rows": None, "error": "empty"}
    gold_res = execute_pg(golden_sql) if golden_sql else {"status": "error", "rows": None, "error": "no gold"}

    is_valid = pred_res["status"] == "ok"
    passed, reason = compare_results(gold_res, pred_res) if is_valid else (False, pred_res.get("error", ""))

    return {
        "qid": qid, "category": category, "difficulty": difficulty,
        "question": q["question"], "gold_sql": golden_sql or "",
        "pred_sql": pred_sql, "ex": 1 if passed else 0,
        "valid": 1 if is_valid else 0, "reason": reason,
        "tokens": gen.get("tokens", 0),
        "pred_error": pred_res.get("error", ""),
        "ablation": ablation,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--benchmark", default=str(BENCHMARK_PATH))
    p.add_argument("--ablations", default=",".join(ABLATIONS),
                   help="Comma-separated list of ablations to run")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="Limit number of questions (for smoke tests)")
    args = p.parse_args()

    _init_runtime()

    questions = load_questions(Path(args.benchmark))
    if args.limit:
        questions = questions[:args.limit]
    print(f"[ablate] Loaded {len(questions)} questions from {Path(args.benchmark).name}")

    out_dir = Path(args.out_dir) if args.out_dir else (
        RESULTS_ROOT / f"gis_ablation_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    ablations = [a.strip() for a in args.ablations.split(",") if a.strip()]
    summaries = {}

    for ablation in ablations:
        print(f"\n=== Ablation: {ablation} ({len(questions)}q) ===")
        recs = []
        for i, q in enumerate(questions, 1):
            try:
                rec = run_one(q, ablation)
            except Exception as e:
                rec = {
                    "qid": q["id"], "category": q["category"],
                    "difficulty": q["difficulty"], "question": q["question"],
                    "gold_sql": q.get("golden_sql", ""), "pred_sql": "",
                    "ex": 0, "valid": 0, "reason": str(e), "tokens": 0,
                    "ablation": ablation,
                }
            recs.append(rec)
            m = "OK" if rec["ex"] else "ERR"
            print(f"  [{i:3d}/{len(questions)}] {m} {rec['qid']:25s} ({rec['difficulty']:11s})")

        n = len(recs)
        ex = sum(r["ex"] for r in recs)
        spatial = [r for r in recs if r["difficulty"] != "Robustness"]
        robust = [r for r in recs if r["difficulty"] == "Robustness"]
        sp_ex = sum(r["ex"] for r in spatial) / len(spatial) if spatial else 0
        rb_ex = sum(r["ex"] for r in robust) / len(robust) if robust else 0
        summary = {
            "ablation": ablation, "n": n,
            "execution_accuracy": round(ex / n, 4),
            "spatial_ex": round(sp_ex, 4), "spatial_n": len(spatial),
            "robustness_success": round(rb_ex, 4), "robustness_n": len(robust),
            "generated_at": datetime.now().isoformat(),
        }
        out = {"summary": summary, "records": recs}
        out_path = out_dir / f"ablation_{ablation}_results.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[ablate/{ablation}] Overall EX={ex/n:.3f} ({ex}/{n})")
        print(f"  Spatial 85q EX={sp_ex:.3f} ({sum(r['ex'] for r in spatial)}/{len(spatial)})")
        print(f"  Robustness 15q Success={rb_ex:.3f} ({sum(r['ex'] for r in robust)}/{len(robust)})")
        summaries[ablation] = summary

    # Final summary
    print("\n" + "=" * 70)
    print(f"{'Ablation':25s}  {'Spatial':>10s}  {'Robust':>10s}  {'Overall':>10s}")
    print("=" * 70)
    for ab, s in summaries.items():
        print(f"  {ab:25s}  {s['spatial_ex']:>10.3f}  {s['robustness_success']:>10.3f}  {s['execution_accuracy']:>10.3f}")

    print(f"\n[ablate] Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
