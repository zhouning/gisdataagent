"""Baseline-only cross-family ablation on the GIS Spatial 30q subset.

Three runs only:
  1. Gemini baseline  (no grounding; direct SQL from schema)
  2. Gemini full      (full ADK pipeline with semantic grounding)
  3. DeepSeek baseline (no grounding; FORCE_DEEPSEEK=1 via generate_text)

Two paired McNemar comparisons:
  - Gemini baseline vs Gemini full      -> within-family grounding gain on 30q
  - Gemini baseline vs DeepSeek baseline -> cross-family baseline head-to-head
                                           (quality check that 30q is tractable
                                           by an open-weight model)

SCOPE: full-pipeline cross-family (DeepSeek + grounding + agent loop) requires a
DeepSeek-native agent loop. ADK's LlmAgent is Gemini-only (no hook to redirect
its HTTP layer to DeepSeek), so that run is scheduled for future work.

Usage:
  PYTHONPATH=D:\\adk PYTHONIOENCODING=utf-8 \\
    D:\\adk\\.venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_open_source_ablation.py

Environment variables:
  ABLATION_LIMIT            - if set, only run that many questions (dry-run)
  CQ_EVAL_QUESTION_TIMEOUT  - per-question timeout (seconds, default 120)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

# Load .env first so DB/API keys are available before any data_agent import.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

BENCH = ROOT / "benchmarks" / "gis_spatial_30q_subset.json"
OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


# ---------------------------------------------------------------------------
# Paired McNemar (exact two-sided)
# ---------------------------------------------------------------------------

def mcnemar_exact_two_sided(b: int, c: int) -> float:
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p_one = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_one)


# ---------------------------------------------------------------------------
# DeepSeek-aware baseline (bypasses Gemini genai client in run_cq_eval)
# ---------------------------------------------------------------------------

BASELINE_PROMPT_TEMPLATE = """You are a PostgreSQL/PostGIS SQL expert. Convert the user question into a single SELECT query.

Rules:
- Output ONLY the SQL, no commentary, no markdown fences.
- CRITICAL: Column names with uppercase letters MUST be double-quoted (e.g. "DLMC", "BSM", "Floor", "TBMJ").
  PostgreSQL lowercases unquoted identifiers, so `DLMC` becomes `dlmc` which does not exist.
- Use PostGIS functions (ST_Area, ST_Length, ST_Intersects, ST_DWithin, etc.) for spatial queries.
- Use ::geography cast for real-world distance/area calculations.
- For security: NEVER generate DELETE, UPDATE, DROP, INSERT. Only SELECT.
- For large tables (>100K rows): always add LIMIT unless aggregating.

SCHEMA:
{schema}

QUESTION: {question}

SQL:"""


def _strip_fences(s: str) -> str:
    import re
    s = (s or "").strip()
    m = re.match(r"^```(?:sql)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else s


def deepseek_baseline_generate(question: str, schema: str) -> dict:
    """Baseline generation via generate_text() with FORCE_DEEPSEEK=1."""
    from data_agent.llm_client import generate_text
    prompt = BASELINE_PROMPT_TEMPLATE.format(schema=schema, question=question)
    try:
        sql_raw = generate_text(prompt, tier="standard", temperature=0.0, timeout_ms=60_000)
        sql = _strip_fences(sql_raw)
        return {"status": "ok", "sql": sql, "error": None, "tokens": 0}
    except Exception as e:
        return {"status": "error", "sql": "", "error": str(e), "tokens": 0}


# ---------------------------------------------------------------------------
# Module-cache reset (so env var changes between runs take effect)
# ---------------------------------------------------------------------------

_CQ_MODULES = ["run_cq_eval", "nl2sql_agent"]


def _reset_cq_module_cache() -> None:
    for mod in _CQ_MODULES:
        sys.modules.pop(mod, None)


# ---------------------------------------------------------------------------
# Per-question evaluation (shared between Gemini full/baseline and DS baseline)
# ---------------------------------------------------------------------------

def _evaluate_pred_sql(q: dict, pred_sql: str, gen: dict) -> dict:
    """Given a predicted SQL, run EX comparison and return a record dict."""
    from run_cq_eval import execute_pg, compare_results, evaluate_robustness
    target_metric = q.get("target_metric", "Execution Accuracy")
    difficulty = q.get("difficulty", "")
    is_robustness = difficulty == "Robustness" or target_metric in (
        "Security Rejection", "Refusal Rate",
        "AST Validation (Must contain LIMIT)",
    )
    if is_robustness:
        passed, reason = evaluate_robustness(q, pred_sql)
        return {
            "qid": q["id"], "category": q.get("category", ""),
            "difficulty": difficulty, "question": q["question"],
            "gold_sql": q.get("golden_sql", "N/A"),
            "pred_sql": pred_sql,
            "ex": 1 if passed else 0, "valid": 1, "reason": reason,
            "tokens": gen.get("tokens", 0),
        }
    golden_sql = q.get("golden_sql")
    pred_res = execute_pg(pred_sql) if pred_sql else {
        "status": "error", "rows": None, "error": "empty"}
    gold_res = execute_pg(golden_sql) if golden_sql else {
        "status": "error", "rows": None, "error": "no gold"}
    is_valid = pred_res["status"] == "ok"
    passed, reason = (
        compare_results(gold_res, pred_res)
        if is_valid else (False, pred_res.get("error", ""))
    )
    return {
        "qid": q["id"], "category": q.get("category", ""),
        "difficulty": difficulty, "question": q["question"],
        "gold_sql": golden_sql or "",
        "pred_sql": pred_sql,
        "ex": 1 if passed else 0,
        "valid": 1 if is_valid else 0,
        "reason": reason,
        "tokens": gen.get("tokens", 0),
        "pred_error": pred_res.get("error", ""),
    }


# ---------------------------------------------------------------------------
# Gemini family: baseline + full (via run_cq_eval.run_one)
# ---------------------------------------------------------------------------

async def run_gemini_family(qs: list[dict], out_dir: Path) -> dict[str, list[dict]]:
    print(f"\n{'=' * 60}")
    print(f"  FAMILY: GEMINI  ({len(qs)} questions x 2 modes)")
    print(f"{'=' * 60}")

    os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    os.environ["NL2SQL_AGENT_MODEL"] = "gemini-2.5-flash"
    _reset_cq_module_cache()

    import run_cq_eval  # noqa: E402
    run_cq_eval._init_runtime()

    out: dict[str, list[dict]] = {"baseline": [], "full": []}
    timeout_s = float(os.environ.get("CQ_EVAL_QUESTION_TIMEOUT", "120"))

    for mode in ("baseline", "full"):
        print(f"\n  --- gemini/{mode} ---")
        for i, q in enumerate(qs, 1):
            t0 = time.monotonic()
            try:
                rec = await asyncio.wait_for(
                    run_cq_eval.run_one(q, mode), timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                rec = {"qid": q["id"], "ex": 0,
                       "gen_status": "timeout", "gen_error": "question-level timeout"}
            except Exception as e:
                rec = {"qid": q["id"], "ex": 0,
                       "gen_status": "exception", "gen_error": str(e)}
            rec["family"] = "gemini"
            rec["mode"] = mode
            elapsed = time.monotonic() - t0
            status = "OK " if rec.get("ex") else "ERR"
            print(f"    [{status}] {i:02d}/{len(qs)} {q['id']:28s} "
                  f"ex={rec.get('ex', 0)}  {elapsed:.1f}s")
            out[mode].append(rec)

        (out_dir / f"gemini_{mode}_results.json").write_text(
            json.dumps(out[mode], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        n = len(out[mode])
        ex = sum(r.get("ex", 0) for r in out[mode])
        print(f"  [gemini/{mode}] EX={ex}/{n} = {ex/max(1,n):.3f}")

    return out


# ---------------------------------------------------------------------------
# DeepSeek family: baseline only (cross-family head-to-head)
# ---------------------------------------------------------------------------

async def run_deepseek_baseline_only(qs: list[dict], out_dir: Path) -> dict[str, list[dict]]:
    print(f"\n{'=' * 60}")
    print(f"  FAMILY: DEEPSEEK  ({len(qs)} questions, baseline only)")
    print(f"{'=' * 60}")

    os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
    os.environ["NL2SQL_AGENT_MODEL"] = "gemini-2.5-flash"  # unused here, kept safe
    _reset_cq_module_cache()

    import run_cq_eval  # noqa: E402
    run_cq_eval._init_runtime()
    schema = run_cq_eval.get_schema()

    out: dict[str, list[dict]] = {"baseline": []}
    print(f"\n  --- deepseek/baseline ---")
    for i, q in enumerate(qs, 1):
        t0 = time.monotonic()
        try:
            gen = deepseek_baseline_generate(q["question"], schema)
            pred_sql = gen.get("sql", "")
            rec = _evaluate_pred_sql(q, pred_sql, gen)
        except Exception as e:
            rec = {"qid": q["id"], "ex": 0,
                   "gen_status": "exception", "gen_error": str(e)}
        rec["family"] = "deepseek"
        rec["mode"] = "baseline"
        elapsed = time.monotonic() - t0
        status = "OK " if rec.get("ex") else "ERR"
        print(f"    [{status}] {i:02d}/{len(qs)} {q['id']:28s} "
              f"ex={rec.get('ex', 0)}  {elapsed:.1f}s")
        out["baseline"].append(rec)

    (out_dir / "deepseek_baseline_results.json").write_text(
        json.dumps(out["baseline"], indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    n = len(out["baseline"])
    ex = sum(r.get("ex", 0) for r in out["baseline"])
    print(f"  [deepseek/baseline] EX={ex}/{n} = {ex/max(1,n):.3f}")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    qs = json.loads(BENCH.read_text(encoding="utf-8"))

    limit = os.environ.get("ABLATION_LIMIT")
    if limit:
        qs = qs[:int(limit)]
        print(f"[ablation] DRY-RUN: limited to {len(qs)} question(s)")

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"open_source_ablation_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[ablation] Output dir: {out_dir}")
    print(f"[ablation] Benchmark: {BENCH} ({len(qs)} questions)")
    print(f"[ablation] Total generations: {len(qs)} gemini/baseline + "
          f"{len(qs)} gemini/full + {len(qs)} deepseek/baseline = {len(qs)*3}")

    t_start = time.monotonic()

    gemini = await run_gemini_family(qs, out_dir)
    deepseek = await run_deepseek_baseline_only(qs, out_dir)

    elapsed_total = time.monotonic() - t_start
    print(f"\n[ablation] Total wall-clock: {elapsed_total/60:.1f} min")

    # -----------------------------------------------------------------------
    # Paired statistics
    # -----------------------------------------------------------------------

    def ex_by_qid(recs: list[dict]) -> dict[str, int]:
        return {r["qid"]: (1 if r.get("ex") else 0) for r in recs}

    def paired_stat(a_ex, b_ex, label_a, label_b) -> dict:
        qids = sorted(a_ex.keys() & b_ex.keys())
        tp = fp = fn = tn = 0
        for q in qids:
            pa, pb = a_ex[q], b_ex[q]
            if pa and pb: tp += 1
            elif pa and not pb: fp += 1
            elif not pa and pb: fn += 1
            else: tn += 1
        p = mcnemar_exact_two_sided(fp, fn)
        n_a = max(1, len(a_ex))
        n_b = max(1, len(b_ex))
        return {
            "n": len(qids),
            "label_a": label_a, "label_b": label_b,
            "ex_a": round(sum(a_ex.values()) / n_a, 4),
            "ex_b": round(sum(b_ex.values()) / n_b, 4),
            "discordant_a1b0": fp, "discordant_a0b1": fn,
            "mcnemar_p_two_sided_exact": round(p, 4),
        }

    gm_base = ex_by_qid(gemini["baseline"])
    gm_full = ex_by_qid(gemini["full"])
    ds_base = ex_by_qid(deepseek["baseline"])

    pairs = [
        paired_stat(gm_base, gm_full, "gemini_baseline", "gemini_full"),
        paired_stat(gm_base, ds_base, "gemini_baseline", "deepseek_baseline"),
    ]

    gemini_grounding_delta = pairs[0]["ex_b"] - pairs[0]["ex_a"]
    cross_family_delta = pairs[1]["ex_b"] - pairs[1]["ex_a"]

    report = {
        "generated_at": datetime.now().isoformat(),
        "benchmark": str(BENCH.relative_to(ROOT)),
        "n_questions": len(qs),
        "wall_clock_minutes": round(elapsed_total / 60, 1),
        "gemini_grounding_delta": round(gemini_grounding_delta, 4),
        "cross_family_baseline_delta": round(cross_family_delta, 4),
        "scope_note": (
            "Baseline-only cross-family ablation. DeepSeek baseline shows the 30q "
            "subset is tractable by an open-weight model. Full-pipeline under DeepSeek "
            "(grounding + agent loop + retry) requires a DeepSeek-native agent loop; "
            "ADK's LlmAgent is Gemini-only and its HTTP layer cannot be redirected to "
            "DeepSeek without refactoring. Scheduled for future work."
        ),
        "pairs": pairs,
        "gemini": gemini,
        "deepseek": deepseek,
    }

    out_path = out_dir / "open_source_ablation_report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 60}")
    print(f"  ABLATION REPORT")
    print(f"{'=' * 60}")
    print(f"  Benchmark: {report['benchmark']}  ({report['n_questions']}q)")
    print(f"  Wall-clock: {report['wall_clock_minutes']} min")
    print()
    for pr in pairs:
        sig = "**" if pr["mcnemar_p_two_sided_exact"] < 0.05 else "  "
        print(f"  {sig} {pr['label_a']:30s} EX={pr['ex_a']:.3f}")
        print(f"     {pr['label_b']:30s} EX={pr['ex_b']:.3f}")
        print(f"     delta={pr['ex_b']-pr['ex_a']:+.3f}  "
              f"p={pr['mcnemar_p_two_sided_exact']}  "
              f"discordant b/c={pr['discordant_a1b0']}/{pr['discordant_a0b1']}")
        print()
    print(f"  Gemini within-family grounding delta: {gemini_grounding_delta:+.3f}")
    print(f"  Cross-family baseline delta (gm-ds):  {cross_family_delta:+.3f}")
    print(f"\n  Report: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


