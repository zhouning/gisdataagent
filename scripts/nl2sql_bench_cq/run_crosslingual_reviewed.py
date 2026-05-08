"""Re-evaluate the cross-lingual 50q benchmark on human-reviewed translations.

Pipeline (runs both versions on the SAME v4 agent, to isolate translation from
agent version):
  1. Read benchmarks/bird_chinese_50q_review.csv (status: ok / fix / drop;
     for fix rows, corrected_chinese is the human-cleaned Chinese).
  2. Read benchmarks/bird_chinese_100_benchmark.json (source of truth for
     gold SQL, evidence, db_id, question_en, original LLM translation).
  3. Build benchmarks/bird_chinese_50q_reviewed.json (the 50 kept qids, with
     both the LLM translation and the human-corrected Chinese attached).
  4. Run the v4 agent (full mode + EXPLAIN guard) TWICE on each kept qid:
        * pre-review  -> uses the original LLM-translated Chinese
        * post-review -> uses the human-corrected Chinese (or the LLM one
                         for status=ok, since no human edit was needed)
     Holding the agent constant across the two runs is what lets us isolate
     translation-artifact effects from agent capability.
  5. Paired McNemar on pre vs post ex, plus sub-group stats for status=fix
     (where translation was edited) and status=ok (where it was kept).

Responds to 2026-05-07 reviewer B section 3 (Validity of Cross-lingual Eval).

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  $env:PYTHONIOENCODING="utf-8"
  $env:EXPLAIN_LIMIT_THRESHOLD="10000"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_crosslingual_reviewed.py
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_bird"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=True)

REVIEW_CSV = ROOT / "benchmarks" / "bird_chinese_50q_review.csv"
SRC_BENCHMARK = ROOT / "benchmarks" / "bird_chinese_100_benchmark.json"
OUT_REVIEWED_BENCH = ROOT / "benchmarks" / "bird_chinese_50q_reviewed.json"


def build_reviewed_benchmark() -> list[dict]:
    """Build 50q with both LLM and human-corrected Chinese attached."""
    bench = json.loads(SRC_BENCHMARK.read_text(encoding="utf-8"))
    by_qid = {q["question_id"]: q for q in bench}

    kept: list[dict] = []
    n_ok = n_fix = n_drop = 0
    with REVIEW_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = int(row["qid"])
            status = row["status"].strip().lower()
            if status == "drop":
                n_drop += 1
                continue
            if qid not in by_qid:
                raise SystemExit(f"qid {qid} missing from {SRC_BENCHMARK.name}")
            q = dict(by_qid[qid])
            llm_zh = q["question"]
            if status == "fix":
                corrected = row["corrected_chinese"].strip()
                if not corrected:
                    raise SystemExit(
                        f"qid {qid} marked 'fix' but corrected_chinese is empty"
                    )
                q["question_zh_llm"] = llm_zh
                q["question_zh_human"] = corrected
                q["review_status"] = "fix"
                n_fix += 1
            elif status == "ok":
                q["question_zh_llm"] = llm_zh
                q["question_zh_human"] = llm_zh  # unchanged
                q["review_status"] = "ok"
                n_ok += 1
            else:
                raise SystemExit(f"qid {qid} has unknown status: {status!r}")
            kept.append(q)

    OUT_REVIEWED_BENCH.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[reviewed] kept={len(kept)}  ok={n_ok}  fix={n_fix}  drop={n_drop}")
    print(f"[reviewed] wrote {OUT_REVIEWED_BENCH}")
    return kept


def mcnemar_exact_two_sided(b: int, c: int) -> float:
    """Exact binomial McNemar (two-sided), null p=0.5 on b+c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    from math import comb
    p_one = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p_one)


async def run_variant(reviewed: list[dict], variant: str, out_dir: Path) -> list[dict]:
    """Run the v4 agent on `reviewed` with q['question'] = zh_<variant>.

    variant is 'llm' or 'human'.
    """
    import run_pg_eval as _eval
    _eval._init_runtime()
    _eval.ensure_eval_table()
    cache = _eval.open_cache(out_dir / "run_state.db")

    recs: list[dict] = []
    cache_key = f"v4_{variant}"
    for i, base_q in enumerate(reviewed, 1):
        zh = base_q[f"question_zh_{variant}"]
        q = dict(base_q)
        q["question"] = zh

        cached = _eval.cache_get(cache, q["question_id"], cache_key)
        if cached:
            recs.append(cached)
            m = "OK" if cached.get("ex") else ("VAL" if cached.get("valid") else "ERR")
            print(f"  [{i}/{len(reviewed)}] {m} {q['question_id']} [{variant}] (cached)")
            continue
        try:
            rec = await asyncio.wait_for(_eval.run_one(q, "full"), timeout=120)
        except asyncio.TimeoutError:
            rec = {
                "qid": q["question_id"], "db_id": q["db_id"],
                "difficulty": q.get("difficulty", "?"),
                "question": q["question"], "gold_sql": q.get("SQL", ""),
                "pred_sql": "", "ex": 0, "valid": 0,
                "gen_status": "timeout", "gen_error": "120s timeout",
                "pred_error": "", "gold_status": "?", "tokens": 0,
            }
        except Exception as e:
            rec = {
                "qid": q["question_id"], "db_id": q["db_id"],
                "difficulty": q.get("difficulty", "?"),
                "question": q["question"], "gold_sql": q.get("SQL", ""),
                "pred_sql": "", "ex": 0, "valid": 0,
                "gen_status": "exception", "gen_error": str(e),
                "pred_error": "", "gold_status": "?", "tokens": 0,
            }
        rec["review_status"] = base_q["review_status"]
        rec["variant"] = variant
        rec["question_used"] = zh
        recs.append(rec)
        _eval.cache_put(cache, q["question_id"], cache_key, rec)
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [{i}/{len(reviewed)}] {m} {rec['qid']} [{variant}] "
              f"({rec['difficulty']}) status={rec['review_status']}")
    return recs


def paired_summary(pre_recs: list[dict], post_recs: list[dict]) -> dict:
    pre_by_qid = {int(r["qid"]): r for r in pre_recs}
    post_by_qid = {int(r["qid"]): r for r in post_recs}
    qids = sorted(pre_by_qid.keys() & post_by_qid.keys())

    aligned = []
    a = b = c = d_count = 0
    for qid in qids:
        p = 1 if pre_by_qid[qid].get("ex") else 0
        q = 1 if post_by_qid[qid].get("ex") else 0
        aligned.append({
            "qid": qid,
            "pre": p, "post": q,
            "review_status": pre_by_qid[qid].get("review_status", "?"),
        })
        if p and q: a += 1
        elif p and not q: b += 1
        elif not p and q: c += 1
        else: d_count += 1

    n = len(aligned)
    pre_ex = sum(x["pre"] for x in aligned) / n if n else 0.0
    post_ex = sum(x["post"] for x in aligned) / n if n else 0.0
    p_val = mcnemar_exact_two_sided(b, c)

    def subset_stats(label: str) -> dict:
        sub = [x for x in aligned if x["review_status"] == label]
        if not sub:
            return {"n": 0}
        return {
            "n": len(sub),
            "pre_ex": round(sum(x["pre"] for x in sub) / len(sub), 4),
            "post_ex": round(sum(x["post"] for x in sub) / len(sub), 4),
        }

    return {
        "n": n,
        "pre_ex": round(pre_ex, 4),
        "post_ex": round(post_ex, 4),
        "delta": round(post_ex - pre_ex, 4),
        "contingency": {
            "both_correct": a, "pre1_post0": b,
            "pre0_post1": c, "both_wrong": d_count,
        },
        "mcnemar_b": b, "mcnemar_c": c,
        "mcnemar_p_two_sided_exact": round(p_val, 4),
        "subset_fix": subset_stats("fix"),
        "subset_ok": subset_stats("ok"),
        "aligned": aligned,
    }


async def main() -> int:
    if not REVIEW_CSV.exists():
        raise SystemExit(f"Missing {REVIEW_CSV}")

    reviewed = build_reviewed_benchmark()

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = ROOT / "data_agent" / "nl2sql_eval_results" / f"crosslingual_reviewed_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[reviewed] eval out_dir={out_dir}")

    print(f"\n=== V4 on LLM-translated 50q (pre-review baseline) ===")
    pre_recs = await run_variant(reviewed, "llm", out_dir)
    print(f"\n=== V4 on human-corrected 50q (post-review) ===")
    post_recs = await run_variant(reviewed, "human", out_dir)

    summary = paired_summary(pre_recs, post_recs)

    print(f"\n{'=' * 60}")
    print(f"Cross-lingual paired comparison (v4 agent, n={summary['n']})")
    print(f"  pre  (LLM-translated)      EX = {summary['pre_ex']:.3f}")
    print(f"  post (human-corrected)     EX = {summary['post_ex']:.3f}")
    print(f"  delta                         = {summary['delta']:+.3f}")
    print(f"  contingency: {summary['contingency']}")
    print(f"  McNemar exact two-sided p  = {summary['mcnemar_p_two_sided_exact']:.4f}")
    s_fix = summary["subset_fix"]; s_ok = summary["subset_ok"]
    print(f"  subset fix (n={s_fix.get('n')}): "
          f"pre={s_fix.get('pre_ex')} -> post={s_fix.get('post_ex')}")
    print(f"  subset ok  (n={s_ok.get('n')}): "
          f"pre={s_ok.get('pre_ex')} -> post={s_ok.get('post_ex')}")
    print(f"{'=' * 60}\n")

    report = {
        "generated_at": datetime.now().isoformat(),
        "agent_version": "v4 (feat/v12-extensible-platform, post EXPLAIN-guard + OOM prompt)",
        "summary": summary,
        "pre_records": pre_recs,
        "post_records": post_recs,
        "reviewed_benchmark": str(OUT_REVIEWED_BENCH.relative_to(ROOT)),
    }
    out_path = out_dir / "crosslingual_paired_report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"[reviewed] report saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
