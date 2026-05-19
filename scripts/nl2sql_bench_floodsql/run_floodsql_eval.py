"""FloodSQL-Bench evaluation orchestrator (mirror of run_v7_smoke_b.py).

Runs N samples × M families × baseline+full on the FloodSQL-Bench
question set, with DuckDB→PostgreSQL SQL rewriting and the floodsql
schema we loaded in load_floodsql.py.

Key differences from CQ orchestrator:
  - Question source: bechmark_updated.jsonl (443 questions, L0–L5)
  - SKIP the 18 few-shot qids (last 3 per level, seeded into reference_queries)
  - Default eval set: stratified sample (configurable via --strategy)
  - Gold SQL rewrite (DuckDB → PG) applied before execute_pg
  - No "business_lang" vs raw question distinction; always uses 'question'

Usage:
    cd D:/adk
    .venv/Scripts/python.exe -u scripts/nl2sql_bench_floodsql/run_floodsql_eval.py \
        --strategy stratified25 \
        --samples 1 \
        --only gemini-2.5-flash \
        --out-tag floodsql_smoke
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)
sys.stdout.reconfigure(encoding="utf-8")

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"
FLOODSQL_BENCH = Path("D:/adk/data/floodsql_bench_repo/benchmark/bechmark_updated.jsonl")
SCHEMA = os.environ.get("FLOODSQL_SCHEMA", "floodsql")
N_FEW_SHOT_PER_LEVEL = 3  # MUST match seed_few_shots.py

# Same family list as CQ
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


# ============================================================================
# DuckDB → PostgreSQL SQL rewrite (same as test_floodsql_gold.py)
# ============================================================================
TABLES_TO_QUALIFY = ["census_tracts", "county", "floodplain", "zcta", "claims",
                     "hospitals", "schools", "svi", "nri", "cre"]


def rewrite_sql_for_pg(sql: str) -> str:
    """Apply 4 DuckDB→PG rewrites to a gold SQL."""
    sql = re.sub(r"STRFTIME\s*\(\s*'%Y'\s*,\s*([^)]+)\)",
                 lambda m: f"EXTRACT(YEAR FROM {m.group(1).strip()})::TEXT",
                 sql, flags=re.IGNORECASE)
    sql = re.sub(r"STRFTIME\s*\(\s*'%m'\s*,\s*([^)]+)\)",
                 lambda m: f"LPAD(EXTRACT(MONTH FROM {m.group(1).strip()})::TEXT, 2, '0')",
                 sql, flags=re.IGNORECASE)
    sql = re.sub(r"AS\s+DOUBLE\b(?!\s+PRECISION)", "AS DOUBLE PRECISION",
                 sql, flags=re.IGNORECASE)

    def _wrap_stpoint(m):
        prefix = sql[max(0, m.start()-12):m.start()].upper().rstrip()
        if prefix.endswith("ST_SETSRID("):
            return m.group(0)
        return f"ST_SetSRID({m.group(0)}, 4326)"
    sql = re.sub(r"ST_Point\s*\([^()]*\)", _wrap_stpoint, sql, flags=re.IGNORECASE)

    for t in TABLES_TO_QUALIFY:
        pat = re.compile(rf"(?<![\w.]){t}\b", re.IGNORECASE)
        sql = pat.sub(f"{SCHEMA}.{t}", sql)
    return sql


# ============================================================================
# Question loader + few-shot exclusion + sampling strategies
# ============================================================================
def get_few_shot_qids() -> set[str]:
    """qids reserved as few-shot examples (last 3 per level). MUST be excluded
    from the evaluation set to avoid train-test leakage."""
    rows = [json.loads(l) for l in FLOODSQL_BENCH.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_lv = defaultdict(list)
    for r in rows:
        by_lv[r["id"].split("_")[0]].append(r)
    qids = set()
    for lv in sorted(by_lv):
        for r in by_lv[lv][-N_FEW_SHOT_PER_LEVEL:]:
            qids.add(r["id"])
    return qids


def load_questions(strategy: str = "stratified25") -> list[dict]:
    """Load + filter + sample the eval set.

    strategy:
      - 'all'           : all 443 - 18 few-shot = 425 questions
      - 'stratified25'  : first 25 per level (with L4 fully kept at 40), excluding few-shot
      - 'stratified10'  : first 10 per level (60 total) — quickest smoke
      - 'first_n:N'     : first N qids after few-shot exclusion
    """
    rows = [json.loads(l) for l in FLOODSQL_BENCH.read_text(encoding="utf-8").splitlines() if l.strip()]
    few_shot_qids = get_few_shot_qids()
    rows = [r for r in rows if r["id"] not in few_shot_qids]

    if strategy == "all":
        return _to_q(rows)

    if strategy.startswith("first_n:"):
        n = int(strategy.split(":")[1])
        return _to_q(rows[:n])

    by_lv = defaultdict(list)
    for r in rows:
        by_lv[r["id"].split("_")[0]].append(r)
    out = []
    per_level = {"stratified10": 10, "stratified25": 25}.get(strategy, 25)
    for lv in sorted(by_lv):
        # L4 only has 43 - 3 = 40 questions after few-shot; cap to all of them
        cap = min(per_level, len(by_lv[lv]))
        out.extend(by_lv[lv][:cap])
    return _to_q(out)


def _to_q(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "question": r["question"],
            "category": r["id"].split("_")[0],   # use level as category
            "difficulty": r["id"].split("_")[0],  # L0..L5
            "target_metric": "Execution Accuracy",
            "golden_sql": rewrite_sql_for_pg(r["sql"]),
            "gold_result": r.get("result"),       # JSONL ground-truth output
            "gold_row_count": r.get("row_count"),
        })
    return out


# ============================================================================
# Family runner (mirror of run_v7_smoke_b.run_family with FloodSQL tweaks)
# ============================================================================
def _reset_modules() -> None:
    for name in list(sys.modules):
        if name in ("run_cq_eval", "nl2sql_agent") or name.startswith("run_"):
            if name == __name__:
                continue
            sys.modules.pop(name, None)


async def run_family(model_name: str, family: str, qs: list[dict],
                     out_dir: Path, *, sample_idx: int = 1,
                     total_samples: int = 1) -> dict:
    print(f"\n{'=' * 80}")
    suffix = f"  sample {sample_idx}/{total_samples}" if total_samples > 1 else ""
    print(f"FAMILY: {model_name}  (family={family}){suffix}")
    print(f"{'=' * 80}", flush=True)

    _reset_modules()

    os.environ["NL2SQL_BASELINE_MODEL"] = model_name
    os.environ["NL2SQL_AGENT_MODEL"] = model_name
    os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)
    os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    # Tell the schema-dump machinery to look at floodsql.* tables instead of
    # public.cq_*. Each FloodSQL gold SQL references the 10 floodsql tables
    # (after schema-qualify rewrite) so the regex captures the bare names.
    os.environ["BENCH_SCHEMA"] = SCHEMA
    os.environ["BENCH_TABLES_JSON"] = str(FLOODSQL_BENCH)
    os.environ["BENCH_TABLE_PREFIX_RE"] = (
        r"\b(?:floodsql\.)?(census_tracts|county|floodplain|zcta|claims|"
        r"hospitals|schools|svi|nri|cre)\b"
    )
    if family == "gemma":
        os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "360"
    else:
        os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "180"

    # Late-import so the fresh modules see the current env.
    from run_cq_eval import (
        _init_runtime, baseline_generate_family_aware,
        compare_results, execute_pg, full_generate,
    )
    _init_runtime()

    fam_dir = out_dir / model_name.replace("/", "_")
    if total_samples > 1:
        fam_dir = fam_dir / f"sample_{sample_idx}"
    fam_dir.mkdir(parents=True, exist_ok=True)

    fam_summary: dict = {"model": model_name, "family": family,
                         "sample_idx": sample_idx, "modes": {}}

    for mode in ("baseline", "full"):
        existing = fam_dir / f"records_{mode}.jsonl"
        if existing.exists():
            existing_lines = sum(1 for _ in existing.open(encoding="utf-8"))
            if existing_lines >= len(qs):
                print(f"\n--- [{model_name}] mode={mode} SKIPPED "
                      f"(existing {existing_lines}/{len(qs)} records) ---",
                      flush=True)
                recs_existing = []
                for line in existing.open(encoding="utf-8"):
                    if line.strip():
                        recs_existing.append(json.loads(line))
                ex_e = sum(r.get("ex", 0) for r in recs_existing)
                valid_e = sum(r.get("valid", 1) for r in recs_existing)
                # per-level breakdown
                by_lv = defaultdict(lambda: {"n": 0, "ex": 0})
                for r in recs_existing:
                    lv = r["qid"].split("_")[0]
                    by_lv[lv]["n"] += 1
                    by_lv[lv]["ex"] += r.get("ex", 0)
                fam_summary["modes"][mode] = {
                    "ex": ex_e, "n": len(recs_existing),
                    "ex_rate": round(ex_e / max(1, len(recs_existing)), 4),
                    "valid": valid_e,
                    "duration_sec": None,
                    "by_level": {lv: dict(v) for lv, v in by_lv.items()},
                    "resumed": True,
                }
                continue

        print(f"\n--- [{model_name}] mode={mode} on {len(qs)} questions ---",
              flush=True)
        records: list[dict] = []
        t0 = time.time()
        for i, q in enumerate(qs, 1):
            difficulty = q["difficulty"]
            golden_sql = q.get("golden_sql")

            try:
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
                    gen = await full_generate(q["question"])
            except Exception as e:
                gen = {"status": "exception", "sql": "",
                       "error": f"{type(e).__name__}: {str(e)[:300]}",
                       "tokens": 0}

            pred_sql = gen.get("sql", "")
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
                "qid": q["id"], "category": difficulty, "difficulty": difficulty,
                "question": q["question"],
                "gold_sql": golden_sql or "",
                "pred_sql": pred_sql,
                "ex": 1 if passed else 0,
                "valid": 1 if is_valid else 0,
                "reason": reason,
                "tokens": gen.get("tokens", 0),
                "pred_error": (pred_res.get("error") or "")[:300],
                "gold_error": (gold_res.get("error") or "")[:300],
                "gen_status": gen.get("status", "?"),
                "gen_error": (gen.get("error") or "")[:300],
                "hint_injection_stats": hint_stats,
            }
            records.append(rec)
            mark = "OK" if rec["ex"] else "FAIL"
            print(f"  [{i:>3}/{len(qs)}] {q['id']:<12} {mark} "
                  f"{str(rec.get('reason',''))[:70]}", flush=True)
            (fam_dir / f"records_{mode}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                encoding="utf-8")

            # Early-failure abort (same as CQ)
            if i == 5:
                exc_in_first5 = sum(
                    1 for r in records if r.get("gen_status") == "exception"
                )
                if exc_in_first5 >= 4:
                    print(f"  [ABORT] {exc_in_first5}/5 first records had exception", flush=True)
                    raise RuntimeError(
                        f"early-failure-abort: {exc_in_first5}/5 exceptions "
                        f"(model={model_name}, mode={mode})")

        dur = time.time() - t0
        ex = sum(r["ex"] for r in records)
        valid = sum(r.get("valid", 1) for r in records)
        by_lv = defaultdict(lambda: {"n": 0, "ex": 0})
        for r in records:
            lv = r["qid"].split("_")[0]
            by_lv[lv]["n"] += 1
            by_lv[lv]["ex"] += r.get("ex", 0)

        print(f"  [{mode}] EX={ex}/{len(records)} = {ex/len(records):.4f}  "
              f"valid={valid}/{len(records)}  wall={dur:.0f}s",
              flush=True)
        for lv in sorted(by_lv):
            v = by_lv[lv]
            print(f"    {lv}: {v['ex']}/{v['n']} = {v['ex']/v['n']:.4f}", flush=True)

        fam_summary["modes"][mode] = {
            "ex": ex, "n": len(records),
            "ex_rate": round(ex / len(records), 4),
            "valid": valid,
            "duration_sec": round(dur, 1),
            "by_level": {lv: dict(v) for lv, v in by_lv.items()},
        }

    (fam_dir / "summary.json").write_text(
        json.dumps(fam_summary, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return fam_summary


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="stratified25",
                    help="all | stratified25 | stratified10 | first_n:N (default stratified25)")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--out-tag", default="floodsql_smoke")
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument("--only", type=str, default=None,
                    help="comma-separated list of model names")
    args = ap.parse_args()

    questions = load_questions(args.strategy)
    print(f"[floodsql] strategy={args.strategy} → {len(questions)} questions")
    by_lv = defaultdict(int)
    for q in questions:
        by_lv[q["difficulty"]] += 1
    for lv in sorted(by_lv):
        print(f"  {lv}: {by_lv[lv]}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out_dir = OUT_ROOT / f"floodsql_{args.out_tag}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    families = FAMILIES
    if args.only:
        allowed = {s.strip() for s in args.only.split(",")}
        families = [(m, f) for m, f in families if m in allowed]
    print(f"[floodsql] running {len(families)} families × {len(questions)}q × "
          f"2 modes × N={args.samples}")
    print(f"[floodsql] out_dir: {out_dir}")

    matrix: dict = {
        "benchmark": "floodsql_bench " + args.strategy,
        "n_questions": len(questions),
        "n_samples": args.samples,
        "schema": SCHEMA,
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
        (out_dir / "matrix.json").write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2),
            encoding="utf-8")

    matrix["finished_at"] = datetime.now().isoformat()
    (out_dir / "matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
