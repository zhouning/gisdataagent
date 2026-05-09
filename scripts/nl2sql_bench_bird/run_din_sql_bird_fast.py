"""BIRD 150q held-out DIN-SQL fast runner.

Loads a pre-materialised benchmark JSON (benchmarks/bird_pg_heldout_150.json),
runs DIN-SQL on each question, and emits paired McNemar statistics against our
Full pipeline predictions.

Does NOT import the semantic layer or the full pipeline — only reuses the BIRD
eval helpers (execute_pg, compare_results, dump_schema, _init_runtime) from
run_pg_eval.py and the DIN-SQL prompt generator from din_sql_runner.py.

Usage:
  cd D:\\adk
  set PYTHONPATH=D:/adk
  set PYTHONIOENCODING=utf-8
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_din_sql_bird_fast.py ^
      --bench benchmarks/bird_pg_heldout_150.json

  # Smoke test (1 question):
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_din_sql_bird_fast.py ^
      --bench benchmarks/bird_pg_heldout_150.json --limit 1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — must happen before any local imports
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]          # D:/adk
sys.path.insert(0, str(SCRIPT_DIR))   # for run_pg_eval (relative imports)
sys.path.insert(0, str(ROOT))         # for data_agent.* and scripts.*

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)

# ---------------------------------------------------------------------------
# Reuse BIRD eval helpers from run_pg_eval (no semantic layer imported here)
# ---------------------------------------------------------------------------
from run_pg_eval import (          # noqa: E402
    execute_pg,
    compare_results,
    dump_schema,
    _init_runtime,
)

# ---------------------------------------------------------------------------
# DIN-SQL generator
# ---------------------------------------------------------------------------
from scripts.nl2sql_bench_baselines.din_sql.din_sql_runner import (  # noqa: E402
    predict as din_sql_predict,
)


# ---------------------------------------------------------------------------
# Paired McNemar exact two-sided test
# ---------------------------------------------------------------------------

def mcnemar_exact_two_sided(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value via binomial CDF.

    b = Full-wins (Full=1, DIN=0)
    c = DIN-wins  (Full=0, DIN=1)
    """
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p_one = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_one)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DIN-SQL fast runner on BIRD 150q held-out benchmark"
    )
    p.add_argument(
        "--bench", required=True,
        help="Path to materialised benchmark JSON (e.g. benchmarks/bird_pg_heldout_150.json)",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Process only the first N questions (smoke test)",
    )
    p.add_argument(
        "--out-dir", default=None,
        help="Output directory (default: data_agent/nl2sql_eval_results/din_sql_bird_150q_<ts>)",
    )
    p.add_argument(
        "--max-retries", type=int, default=1,
        help="DIN-SQL self-correction retries (default 1)",
    )
    p.add_argument(
        "--pair-with", default=None,
        help=(
            "Path to Full pipeline predictions JSON for paired McNemar. "
            "Default: data_agent/nl2sql_eval_results/bird_heldout_R2_eval/full_results.json"
        ),
    )
    return p


# ---------------------------------------------------------------------------
# Single-question runner
# ---------------------------------------------------------------------------

def run_one(q: dict, max_retries: int = 1) -> dict:
    """Run DIN-SQL on a single BIRD question and return an evaluation record."""
    qid = q["question_id"]
    db_id = q["db_id"]
    evidence = q.get("evidence", "")
    gold_sql = q.get("SQL", "")

    # Schema dump (cached per db_id inside dump_schema)
    try:
        schema_text = dump_schema(db_id)
    except Exception as e:
        return {
            "qid": qid, "db_id": db_id,
            "difficulty": q.get("difficulty", "?"),
            "question": q["question"], "gold_sql": gold_sql,
            "pred_sql": "", "ex": 0, "valid": 0,
            "gen_status": "schema_error", "gen_error": str(e)[:300],
            "pred_error": "", "gold_status": "?",
            "din_difficulty": "?", "stages_run": 0, "tokens": 0,
            "duration": 0.0,
        }

    def exec_fn(sql: str) -> dict:
        return execute_pg(sql, db_id)

    t0 = time.time()
    try:
        result = din_sql_predict(
            schema=schema_text,
            question=q["question"],
            evidence=evidence,
            execute_fn=exec_fn,
            max_retries=max_retries,
        )
    except Exception as e:
        return {
            "qid": qid, "db_id": db_id,
            "difficulty": q.get("difficulty", "?"),
            "question": q["question"], "gold_sql": gold_sql,
            "pred_sql": "", "ex": 0, "valid": 0,
            "gen_status": "exception", "gen_error": str(e)[:300],
            "pred_error": "", "gold_status": "?",
            "din_difficulty": "?", "stages_run": 0, "tokens": 0,
            "duration": round(time.time() - t0, 2),
        }

    pred_sql = result.get("sql", "")
    duration = round(time.time() - t0, 2)

    pred_res = execute_pg(pred_sql, db_id) if pred_sql else {
        "status": "error", "rows": None, "error": "empty SQL",
    }
    gold_res = execute_pg(gold_sql, db_id)

    is_valid = pred_res["status"] == "ok"
    is_correct = (
        is_valid
        and gold_res["status"] == "ok"
        and compare_results(gold_res["rows"], pred_res["rows"])
    )

    return {
        "qid": qid,
        "db_id": db_id,
        "difficulty": q.get("difficulty", "?"),
        "question": q["question"],
        "gold_sql": gold_sql,
        "pred_sql": pred_sql,
        "ex": 1 if is_correct else 0,
        "valid": 1 if is_valid else 0,
        "gen_status": "ok" if pred_sql else "no_sql",
        "gen_error": None,
        "pred_error": pred_res.get("error", ""),
        "gold_status": gold_res["status"],
        "din_difficulty": result.get("difficulty", "?"),
        "stages_run": result.get("stages_run", 0),
        "tokens": result.get("tokens", 0),
        "duration": duration,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    _init_runtime()

    p = build_arg_parser()
    args = p.parse_args()

    bench_path = Path(args.bench)
    if not bench_path.is_absolute():
        bench_path = ROOT / bench_path
    questions_raw: list[dict] = json.loads(bench_path.read_text(encoding="utf-8"))

    # Deduplicate by question_id (keep first occurrence) — the BIRD source
    # occasionally has a duplicate question_id entry.
    seen_qids: set[int] = set()
    questions: list[dict] = []
    for q in questions_raw:
        qid = q["question_id"]
        if qid in seen_qids:
            print(f"[warn] duplicate question_id={qid} in benchmark — skipping second occurrence")
            continue
        seen_qids.add(qid)
        questions.append(q)

    if len(questions) != len(questions_raw):
        print(f"[warn] deduplication: {len(questions_raw)} → {len(questions)} questions")

    if args.limit:
        questions = questions[: args.limit]

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = (
        Path(args.out_dir)
        if args.out_dir
        else ROOT / "data_agent" / "nl2sql_eval_results" / f"din_sql_bird_150q_{ts}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[din-sql-bird] Loaded {len(questions)} questions from {bench_path.name}")
    print(f"[din-sql-bird] Output: {out_dir}")

    recs: list[dict] = []

    for i, q in enumerate(questions, 1):
        rec = run_one(q, max_retries=args.max_retries)
        recs.append(rec)

        status_tag = "OK" if rec["ex"] else ("VAL" if rec["valid"] else "ERR")
        print(
            f"  [{i}/{len(questions)}] {status_tag} "
            f"ex={rec['ex']} valid={rec['valid']} "
            f"qid={rec['qid']} db={rec['db_id']} "
            f"din={rec['din_difficulty']} stages={rec['stages_run']} "
            f"dur={rec['duration']}s"
        )

        # Incremental persistence every 10 questions and at the end
        if i % 10 == 0 or i == len(questions):
            _write_results(out_dir, bench_path, recs)

    # Final summary
    n = len(recs)
    ex_count = sum(r["ex"] for r in recs)
    valid_count = sum(r["valid"] for r in recs)
    din_ex = ex_count / max(1, n)

    by_diff: dict[str, list[int]] = {}
    for r in recs:
        d = r.get("difficulty", "?")
        by_diff.setdefault(d, [0, 0])
        by_diff[d][0] += 1
        by_diff[d][1] += r["ex"]
    diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())}

    by_din_diff: dict[str, list[int]] = {}
    for r in recs:
        d = r.get("din_difficulty", "?")
        by_din_diff.setdefault(d, [0, 0])
        by_din_diff[d][0] += 1
        by_din_diff[d][1] += r["ex"]
    din_diff_breakdown = {d: round(c[1] / c[0], 3) for d, c in sorted(by_din_diff.items())}

    summary = {
        "mode": "din_sql",
        "model": "gemini-2.5-flash",
        "benchmark": str(bench_path),
        "n": n,
        "execution_accuracy": round(din_ex, 4),
        "execution_valid_rate": round(valid_count / max(1, n), 4),
        "by_difficulty": diff_breakdown,
        "by_din_difficulty": din_diff_breakdown,
        "generated_at": datetime.now().isoformat(),
    }

    _write_results(out_dir, bench_path, recs, summary=summary)

    print(f"\n[din-sql-bird] DIN-SQL EX = {din_ex:.4f} ({ex_count}/{n})")
    print(f"  Valid rate = {valid_count / max(1, n):.4f}")
    print(f"  by difficulty: {diff_breakdown}")
    print(f"  by DIN difficulty: {din_diff_breakdown}")

    # ------------------------------------------------------------------
    # Paired McNemar vs Full pipeline predictions
    # ------------------------------------------------------------------
    pair_path = Path(args.pair_with) if args.pair_with else (
        ROOT / "data_agent" / "nl2sql_eval_results" / "bird_heldout_R2_eval" / "full_results.json"
    )
    if not pair_path.is_absolute():
        pair_path = ROOT / pair_path

    if pair_path.exists():
        full_data = json.loads(pair_path.read_text(encoding="utf-8"))
        full_recs = full_data.get("records", full_data) if isinstance(full_data, dict) else full_data
        full_by_qid: dict[int, int] = {
            r["qid"]: (1 if r.get("ex") else 0) for r in full_recs
        }
        din_by_qid: dict[int, int] = {r["qid"]: r["ex"] for r in recs}

        common = sorted(set(din_by_qid) & set(full_by_qid))
        if len(common) < len(recs):
            print(f"[warn] only {len(common)} of {len(recs)} DIN-SQL qids found in Full results")

        b = sum(1 for q in common if full_by_qid[q] == 1 and din_by_qid[q] == 0)
        c = sum(1 for q in common if full_by_qid[q] == 0 and din_by_qid[q] == 1)
        p_val = mcnemar_exact_two_sided(b, c)

        full_ex_common = sum(full_by_qid[q] for q in common) / max(1, len(common))
        din_ex_common = sum(din_by_qid[q] for q in common) / max(1, len(common))

        pair_report = {
            "benchmark": str(bench_path),
            "pair_source": str(pair_path),
            "n_aligned": len(common),
            "full_ex": round(full_ex_common, 4),
            "din_sql_ex": round(din_ex_common, 4),
            "discordant_full_wins_b": b,
            "discordant_din_wins_c": c,
            "mcnemar_p_two_sided_exact": round(p_val, 6),
            "significant_at_0_05": p_val < 0.05,
            "generated_at": datetime.now().isoformat(),
        }
        (out_dir / "paired_mcnemar_report.json").write_text(
            json.dumps(pair_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"\nPaired McNemar (n={pair_report['n_aligned']}):")
        print(f"  Full pipeline EX = {pair_report['full_ex']:.4f}")
        print(f"  DIN-SQL      EX = {pair_report['din_sql_ex']:.4f}")
        print(f"  discordant: Full-wins b={b}, DIN-wins c={c}")
        print(f"  McNemar exact p = {pair_report['mcnemar_p_two_sided_exact']:.6f}  "
              f"({'significant' if pair_report['significant_at_0_05'] else 'not significant'} at α=0.05)")
    else:
        print(f"[warn] pair-with file not found: {pair_path} — skipping McNemar")

    print(f"\n[din-sql-bird] Output dir: {out_dir}")
    return 0


def _write_results(out_dir: Path, bench_path: Path, recs: list[dict],
                   summary: dict | None = None) -> None:
    payload: dict = {
        "generated_at": datetime.now().isoformat(),
        "benchmark": str(bench_path),
        "records": recs,
    }
    if summary:
        payload["summary"] = summary
    (out_dir / "din_sql_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
