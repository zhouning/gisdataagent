"""v7 P1-pre Smoke-B — 9 families × Nq × (baseline + full) × N samples.

Also serves as the P1 full-matrix runner when invoked with
``--limit 125 --samples 3``: the orchestrator is deliberately one script so
the Smoke-B subset is identical code to the P1 production run (cache reset,
env routing, per-family isolation).

For each family, runs the FIRST ``limit`` questions of the v7 business-lang
benchmark in two modes:
  - baseline: BASELINE_PROMPT + raw schema-dump via baseline_generate_family_aware
  - full: ADK agent via build_nl2sql_agent + semantic-layer grounding

Orchestrator design:
  - Each family runs in isolation: we clear module caches and env between
    families so _cached_agent / _SCHEMA_CACHE / NL2SQL_AGENT_FAMILY don't
    leak. Failed families are logged and skipped; the run continues.
  - Env vars set per family:
      NL2SQL_BASELINE_MODEL  - picked up by baseline_generate_family_aware
      NL2SQL_AGENT_MODEL     - picked up by build_nl2sql_agent
  - Results written per family to data_agent/nl2sql_eval_results/
    v7_smoke_b_<ts>/<family>/records_<mode>.jsonl + summary.json.
  - A top-level matrix.json aggregates EX / valid / failure_bins for all
    (family, mode) pairs.

Expected wall-clock:
  - Smoke-B (20q × N=1): ~55 min serial
  - P1 full (125q × N=3): ~18 hours serial (scales ~20x the Smoke-B wall-clock)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"
V7_BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_125q_business_lang.json"


# Ordered so a failing family (e.g. quota exhaustion) doesn't block the
# downstream families we care most about. Gemini 2.5-flash first so we get a
# parity datapoint early; Ollama last so network LAN round-trip dominates the
# tail of the run, not the head.
FAMILIES: list[tuple[str, str]] = [
    ("gemini-2.5-flash", "gemini"),
    ("gemini-2.5-pro", "gemini"),
    ("gemini-3.1-flash-lite-preview", "gemini"),
    ("gemini-3.1-pro-preview", "gemini"),
    ("deepseek-v4-flash", "deepseek"),
    ("deepseek-v4-pro", "deepseek"),
    ("qwen3.6-flash", "qwen"),
    ("qwen3.6-plus", "qwen"),
    ("gemma-4-31b-it-ollama", "gemma"),
]


def _reset_modules() -> None:
    """Purge cached NL2SQL modules so a fresh family gets a fresh agent."""
    for name in list(sys.modules):
        if name in ("run_cq_eval", "nl2sql_agent") or name.startswith("run_"):
            if name == __name__:
                continue
            sys.modules.pop(name, None)


def load_v7_questions_first_n(n: int) -> list[dict]:
    rows = json.loads(V7_BENCH.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        if not r.get("question_business"):
            continue
        out.append({
            "id": r["id"],
            "question": r["question_business"],
            "category": r.get("category"),
            "difficulty": r.get("difficulty"),
            "target_metric": r.get("target_metric"),
            "golden_sql": r.get("golden_sql"),
            "reasoning_points": r.get("reasoning_points", []),
        })
    return out[:n]


async def run_family(model_name: str, family: str, qs: list[dict],
                     out_dir: Path, *, sample_idx: int = 1,
                     total_samples: int = 1) -> dict:
    """Run baseline + full on ``qs`` for one family. Returns summary dict."""
    print(f"\n{'=' * 80}")
    suffix = f"  sample {sample_idx}/{total_samples}" if total_samples > 1 else ""
    print(f"FAMILY: {model_name}  (family={family}){suffix}")
    print(f"{'=' * 80}", flush=True)

    _reset_modules()

    # Env: these drive model selection in the two code paths.
    os.environ["NL2SQL_BASELINE_MODEL"] = model_name
    os.environ["NL2SQL_AGENT_MODEL"] = model_name
    # Clear any leftover family override from a previous iteration.
    os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)
    os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    # Per-question timeout: Ollama LAN is slow, hosted APIs fast.
    if family == "gemma":
        os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "360"
    else:
        os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "180"

    # Late-import so the fresh modules see the current env.
    from run_cq_eval import (
        _init_runtime, baseline_generate_family_aware,
        compare_results, evaluate_robustness, execute_pg, full_generate,
    )
    from run_v7_iteration import classify_failure
    _init_runtime()

    fam_dir = out_dir / model_name.replace("/", "_")
    if total_samples > 1:
        fam_dir = fam_dir / f"sample_{sample_idx}"
    fam_dir.mkdir(parents=True, exist_ok=True)

    fam_summary: dict = {"model": model_name, "family": family,
                         "sample_idx": sample_idx, "modes": {}}

    for mode in ("baseline", "full"):
        # Skip cells whose records jsonl is already complete (resume support).
        existing = fam_dir / f"records_{mode}.jsonl"
        if existing.exists():
            existing_lines = sum(1 for _ in existing.open(encoding="utf-8"))
            if existing_lines >= len(qs):
                print(f"\n--- [{model_name}] mode={mode} SKIPPED "
                      f"(existing {existing_lines}/{len(qs)} records) ---",
                      flush=True)
                # Hydrate fam_summary from existing records so matrix.json
                # still reflects this mode after the resume run.
                recs_existing = []
                for line in existing.open(encoding="utf-8"):
                    if line.strip():
                        recs_existing.append(json.loads(line))
                ex_e = sum(r.get("ex", 0) for r in recs_existing)
                valid_e = sum(r.get("valid", 1) for r in recs_existing)
                bins_e = {"catalog": 0, "dialect": 0, "golden": 0,
                          "safety": 0, "unknown": 0, "pass": 0}
                for r in recs_existing:
                    bins_e[classify_failure(r)] += 1
                fam_summary["modes"][mode] = {
                    "ex": ex_e, "n": len(recs_existing),
                    "ex_rate": round(ex_e / max(1, len(recs_existing)), 4),
                    "valid": valid_e,
                    "duration_sec": None,
                    "failure_bins": bins_e,
                    "resumed": True,
                }
                continue

        print(f"\n--- [{model_name}] mode={mode} on {len(qs)} questions ---",
              flush=True)
        records: list[dict] = []
        t0 = time.time()
        for i, q in enumerate(qs, 1):
            difficulty = q["difficulty"]
            category = q["category"]
            target_metric = q.get("target_metric") or "Execution Accuracy"
            golden_sql = q.get("golden_sql")

            try:
                # v7 P1 enhancement: capture _hint_injection_stats per question
                # so post-run analysis can correlate hint coverage with pass
                # rate. build_nl2sql_context emits the sidecar; we attach it
                # to the rec regardless of mode (baseline runs grounding too
                # for the stats; we just don't put the hints into the prompt).
                hint_stats = None
                try:
                    from data_agent.nl2sql_grounding import build_nl2sql_context
                    _ctx = build_nl2sql_context(
                        q["question"],
                        family=os.environ.get("NL2SQL_AGENT_FAMILY") or family,
                    )
                    hint_stats = _ctx.get("_hint_injection_stats")
                except Exception:
                    hint_stats = None

                if mode == "baseline":
                    gen = baseline_generate_family_aware(q["question"])
                else:
                    # full_generate uses the ADK agent built lazily with
                    # NL2SQL_AGENT_MODEL=model_name (set above).
                    gen = await full_generate(q["question"])
            except Exception as e:
                gen = {"status": "exception", "sql": "",
                       "error": f"{type(e).__name__}: {str(e)[:300]}",
                       "tokens": 0}

            pred_sql = gen.get("sql", "")
            is_robust = difficulty == "Robustness" or target_metric in (
                "Security Rejection", "Refusal Rate",
                "AST Validation (Must contain LIMIT)")
            if is_robust:
                passed, reason = evaluate_robustness(q, pred_sql)
                rec = {
                    "qid": q["id"], "category": category, "difficulty": difficulty,
                    "question": q["question"],
                    "gold_sql": golden_sql or "N/A",
                    "pred_sql": pred_sql,
                    "ex": 1 if passed else 0, "valid": 1, "reason": reason,
                    "tokens": gen.get("tokens", 0),
                    "is_robust": True,
                    "gen_status": gen.get("status", "?"),
                    "hint_injection_stats": hint_stats,
                }
            else:
                pred_res = execute_pg(pred_sql) if pred_sql else \
                    {"status": "error", "rows": None, "error": "empty"}
                gold_res = execute_pg(golden_sql) if golden_sql else \
                    {"status": "error", "rows": None, "error": "no gold"}
                is_valid = pred_res["status"] == "ok"
                if is_valid:
                    passed, reason = compare_results(gold_res, pred_res, gold_sql=golden_sql or "")
                else:
                    passed, reason = False, pred_res.get("error", "")
                rec = {
                    "qid": q["id"], "category": category, "difficulty": difficulty,
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
                    "gen_status": gen.get("status", "?"),
                    "gen_error": (gen.get("error") or "")[:300],
                    "hint_injection_stats": hint_stats,
                }
            records.append(rec)
            mark = "✓" if rec["ex"] else "✗"
            print(f"  [{i:>2}/{len(qs)}] {q['id']:<28} {mark} "
                  f"{str(rec.get('reason',''))[:70]}", flush=True)
            (fam_dir / f"records_{mode}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                encoding="utf-8")

            # Early-failure detection: if the first 5 records all returned
            # gen_status=exception (LLM call failed before any token was
            # produced), the upstream API is likely down. Abort this cell
            # so we don't waste 1 hour producing 125 empty records, like
            # the qwen3.6-plus s1 / qwen3.6-flash s3 disaster on 2026-05-15
            # 03:00 (DashScope outage, ~125 empty records before noticed).
            if i == 5:
                exc_in_first5 = sum(
                    1 for r in records if r.get("gen_status") == "exception"
                )
                if exc_in_first5 >= 4:
                    print(f"  [ABORT] {exc_in_first5}/5 first records had "
                          f"gen_status=exception — upstream API likely down. "
                          f"Skipping rest of this cell.", flush=True)
                    raise RuntimeError(
                        f"early-failure-abort: {exc_in_first5}/5 exceptions "
                        f"in first 5 records (model={os.environ.get('NL2SQL_BASELINE_MODEL', '?')}, "
                        f"mode={mode})")

        dur = time.time() - t0
        ex = sum(r["ex"] for r in records)
        valid = sum(r.get("valid", 1) for r in records)
        bins = {"catalog": 0, "dialect": 0, "golden": 0,
                "safety": 0, "unknown": 0, "pass": 0}
        for r in records:
            bins[classify_failure(r)] += 1

        print(f"  [{mode}] EX={ex}/{len(records)} = {ex/len(records):.4f}  "
              f"valid={valid}/{len(records)}  wall={dur:.0f}s  bins={bins}",
              flush=True)

        fam_summary["modes"][mode] = {
            "ex": ex, "n": len(records),
            "ex_rate": round(ex / len(records), 4),
            "valid": valid,
            "duration_sec": round(dur, 1),
            "failure_bins": bins,
        }

    (fam_dir / "summary.json").write_text(
        json.dumps(fam_summary, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return fam_summary


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20,
                    help="evaluate only first N questions")
    ap.add_argument("--samples", type=int, default=1,
                    help="N repetitions per (family, mode) cell")
    ap.add_argument("--out-tag", default="smoke_b",
                    help="suffix for output dir")
    ap.add_argument("--out-dir", type=str, default=None,
                    help="explicit output dir (resume into existing dir)")
    ap.add_argument("--only", type=str, default=None,
                    help="comma-separated list of model names to run (debug)")
    args = ap.parse_args()

    questions = load_v7_questions_first_n(args.limit)
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out_dir = OUT_ROOT / f"v7_{args.out_tag}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    families = FAMILIES
    if args.only:
        allowed = {s.strip() for s in args.only.split(",")}
        families = [(m, f) for m, f in families if m in allowed]
    print(f"[smoke-b] running {len(families)} families × {len(questions)}q × "
          f"2 modes × N={args.samples}")
    print(f"[smoke-b] out_dir: {out_dir}")

    matrix: dict = {
        "benchmark": V7_BENCH.name,
        "n_questions": len(questions),
        "n_samples": args.samples,
        "families": {},
        "started_at": datetime.now().isoformat(),
    }

    for model_name, family in families:
        fam_entries: list[dict] = []
        for sample_idx in range(1, args.samples + 1):
            try:
                fam_summary = await run_family(
                    model_name, family, questions, out_dir,
                    sample_idx=sample_idx, total_samples=args.samples,
                )
                fam_entries.append(fam_summary)
            except Exception as e:
                print(f"\n[ERROR] family {model_name} sample {sample_idx} crashed:",
                      f"{type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
                fam_entries.append({
                    "model": model_name, "family": family,
                    "sample_idx": sample_idx,
                    "error": f"{type(e).__name__}: {str(e)[:500]}",
                })
        matrix["families"][model_name] = fam_entries if args.samples > 1 else fam_entries[0]
        # Persist after every family so a late crash doesn't lose earlier data.
        (out_dir / "matrix.json").write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2),
            encoding="utf-8")

    matrix["finished_at"] = datetime.now().isoformat()
    (out_dir / "matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # Compact console summary
    print(f"\n\n{'=' * 88}")
    print(f"SMOKE-B MATRIX SUMMARY")
    print(f"{'=' * 88}")
    header = f"{'Model':<36}  {'baseline':>10}  {'full':>10}  {'Δ':>7}"
    print(header)
    print("-" * len(header))
    for model_name, _ in families:
        fam = matrix["families"].get(model_name, {})
        entries = fam if isinstance(fam, list) else [fam]
        if any("error" in e for e in entries):
            first_err = next(e for e in entries if "error" in e)
            print(f"{model_name:<36}  CRASH: {first_err['error'][:40]}")
            continue
        b_rates = [e.get("modes", {}).get("baseline", {}).get("ex_rate")
                   for e in entries]
        f_rates = [e.get("modes", {}).get("full", {}).get("ex_rate")
                   for e in entries]
        b_rates = [r for r in b_rates if r is not None]
        f_rates = [r for r in f_rates if r is not None]
        if not b_rates or not f_rates:
            print(f"{model_name:<36}  incomplete")
            continue
        b = sum(b_rates) / len(b_rates)
        f = sum(f_rates) / len(f_rates)
        print(f"{model_name:<36}  {b:>10.4f}  {f:>10.4f}  {f - b:>+.4f}")
    print(f"\n[smoke-b] done → {out_dir}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
