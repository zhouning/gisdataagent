"""Cross-lingual (Chinese) BIRD evaluation — translate English questions to Chinese,
run the full NL2SQL pipeline, and compare with English results.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  $env:PYTHONIOENCODING="utf-8"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_chinese_eval.py --limit 50
  # Smoke test
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/run_chinese_eval.py --limit 10
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

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bird_paths import resolve_bird_layout
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

# Lazy globals — initialised by _init_runtime()
_client = None
_types = None

TRANSLATE_MODEL = os.environ.get("MODEL_ROUTER", "gemini-2.0-flash")
CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "bird_mini_dev" / "chinese_questions_50.json"


def _init_translate():
    global _client, _types
    if _client is not None:
        return
    from google import genai as genai_client
    from google.genai import types
    _client = genai_client.Client()
    _types = types


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

TRANSLATE_PROMPT = (
    "Translate this database question to natural Chinese. "
    "Keep proper nouns, table/column references in their original form. "
    "Output only the translation."
)


def translate_batch(questions: list[dict]) -> list[dict]:
    """Translate English questions to Chinese, with file-based caching."""
    # Load cache
    cached: dict[int, dict] = {}
    if CACHE_FILE.exists():
        for rec in json.loads(CACHE_FILE.read_text(encoding="utf-8")):
            cached[rec["question_id"]] = rec

    needed = [q for q in questions if q["question_id"] not in cached]
    if not needed:
        print(f"[zh-eval] All {len(questions)} translations cached.")
        return [cached[q["question_id"]] for q in questions]

    print(f"[zh-eval] Translating {len(needed)} questions via {TRANSLATE_MODEL} ...")
    _init_translate()

    for i, q in enumerate(needed, 1):
        prompt = f"{TRANSLATE_PROMPT}\n\n{q['question']}"
        try:
            resp = _client.models.generate_content(
                model=TRANSLATE_MODEL, contents=[prompt],
                config=_types.GenerateContentConfig(temperature=0.0),
            )
            zh = (resp.text or "").strip()
        except Exception as e:
            print(f"  [{i}/{len(needed)}] FAIL qid={q['question_id']}: {e}")
            zh = q["question"]  # fallback to English

        rec = {**q, "question_en": q["question"], "question": zh}
        cached[q["question_id"]] = rec
        print(f"  [{i}/{len(needed)}] qid={q['question_id']}: {zh[:60]}...")

        # Incremental save
        if i % 10 == 0 or i == len(needed):
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(
                json.dumps(list(cached.values()), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    return [cached[q["question_id"]] for q in questions]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    p = argparse.ArgumentParser(description="Cross-lingual Chinese BIRD eval")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--bird-root", default=None)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--skip-english", action="store_true",
                   help="Skip English re-run; load latest English results for comparison")
    args = p.parse_args()

    layout = resolve_bird_layout(args.bird_root)
    results_root = layout["results_root"]

    # Import run_pg_eval as module — its globals (ensure_eval_table etc.) are
    # None until _init_runtime() is called, so we access them as module attrs.
    import run_pg_eval as _eval

    # 1. Load English questions
    en_questions = _eval.load_questions(layout["pg_questions"], limit=args.limit)
    print(f"[zh-eval] Loaded {len(en_questions)} English questions")

    # 2. Translate to Chinese
    zh_questions = translate_batch(en_questions)

    # 3. Prepare output dir
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else (results_root / f"bird_pg_chinese_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[zh-eval] Output: {out_dir}")

    # 4. Init runtime (DB, Gemini, eval table)
    _eval._init_runtime()
    _eval.ensure_eval_table()

    # 5. Run full pipeline on Chinese questions
    cache_zh = _eval.open_cache(out_dir / "run_state.db")
    recs_zh: list[dict] = []
    print(f"\n=== CHINESE FULL ({len(zh_questions)}) ===")
    for i, q in enumerate(zh_questions, 1):
        cached = _eval.cache_get(cache_zh, q["question_id"], "full_zh")
        if cached:
            recs_zh.append(cached)
            m = "OK" if cached.get("ex") else ("VAL" if cached.get("valid") else "ERR")
            print(f"  [{i}/{len(zh_questions)}] {m} {q['question_id']} (cached)")
            continue
        try:
            rec = await _eval.run_one(q, "full")
        except Exception as e:
            rec = {
                "qid": q["question_id"], "db_id": q["db_id"],
                "difficulty": q.get("difficulty", "?"), "question": q["question"],
                "question_en": q.get("question_en", ""),
                "gold_sql": q.get("SQL", ""), "pred_sql": "",
                "ex": 0, "valid": 0, "gen_status": "exception", "gen_error": str(e),
                "pred_error": "", "gold_status": "?", "tokens": 0,
            }
        # Attach English original for comparison
        rec["question_en"] = q.get("question_en", "")
        rec["question_zh"] = q["question"]
        recs_zh.append(rec)
        _eval.cache_put(cache_zh, q["question_id"], "full_zh", rec)
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [{i}/{len(zh_questions)}] {m} {rec['qid']} ({rec['difficulty']}) db={rec['db_id']}")

    # 6. Run full pipeline on English questions (for head-to-head comparison)
    recs_en: list[dict] = []
    if not args.skip_english:
        cache_en = _eval.open_cache(out_dir / "run_state.db")
        print(f"\n=== ENGLISH FULL ({len(en_questions)}) ===")
        for i, q in enumerate(en_questions, 1):
            cached = _eval.cache_get(cache_en, q["question_id"], "full_en")
            if cached:
                recs_en.append(cached)
                m = "OK" if cached.get("ex") else ("VAL" if cached.get("valid") else "ERR")
                print(f"  [{i}/{len(en_questions)}] {m} {q['question_id']} (cached)")
                continue
            try:
                rec = await _eval.run_one(q, "full")
            except Exception as e:
                rec = {
                    "qid": q["question_id"], "db_id": q["db_id"],
                    "difficulty": q.get("difficulty", "?"), "question": q["question"],
                    "gold_sql": q.get("SQL", ""), "pred_sql": "",
                    "ex": 0, "valid": 0, "gen_status": "exception", "gen_error": str(e),
                    "pred_error": "", "gold_status": "?", "tokens": 0,
                }
            recs_en.append(rec)
            _eval.cache_put(cache_en, q["question_id"], "full_en", rec)
            m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
            print(f"  [{i}/{len(en_questions)}] {m} {rec['qid']} ({rec['difficulty']}) db={rec['db_id']}")

    # 7. Summarize
    def summarize(recs, label):
        n = len(recs)
        if n == 0:
            return None
        ex = sum(r["ex"] for r in recs)
        valid = sum(r["valid"] for r in recs)
        by_diff = {}
        for r in recs:
            d = r.get("difficulty", "?")
            by_diff.setdefault(d, [0, 0])
            by_diff[d][0] += 1
            by_diff[d][1] += r["ex"]
        diff_bk = {d: round(c[1] / c[0], 3) for d, c in sorted(by_diff.items())}
        s = {
            "label": label, "n": n,
            "execution_accuracy": round(ex / n, 4),
            "valid_rate": round(valid / n, 4),
            "by_difficulty": diff_bk,
        }
        print(f"\n[{label}] EX={s['execution_accuracy']:.3f} ({ex}/{n}), Valid={s['valid_rate']:.3f}")
        print(f"  by difficulty: {diff_bk}")
        return s

    sum_zh = summarize(recs_zh, "Chinese-full")
    sum_en = summarize(recs_en, "English-full") if recs_en else None

    # 8. Per-question comparison
    if sum_en and sum_zh:
        en_map = {r["qid"]: r for r in recs_en}
        zh_map = {r["qid"]: r for r in recs_zh}
        both_ok = both_fail = en_only = zh_only = 0
        for qid in en_map:
            e, z = en_map[qid].get("ex", 0), zh_map.get(qid, {}).get("ex", 0)
            if e and z: both_ok += 1
            elif e and not z: en_only += 1
            elif z and not e: zh_only += 1
            else: both_fail += 1
        delta = sum_zh["execution_accuracy"] - sum_en["execution_accuracy"]
        print(f"\n{'=' * 60}")
        print(f"Cross-lingual comparison (n={sum_zh['n']})")
        print(f"  English EX = {sum_en['execution_accuracy']:.3f}")
        print(f"  Chinese EX = {sum_zh['execution_accuracy']:.3f}")
        print(f"  Delta      = {delta:+.3f}")
        print(f"  Both OK={both_ok}  EN-only={en_only}  ZH-only={zh_only}  Both FAIL={both_fail}")
        print(f"{'=' * 60}")

    # 9. Persist results
    report = {
        "generated_at": datetime.now().isoformat(),
        "limit": args.limit,
        "chinese_summary": sum_zh,
        "english_summary": sum_en,
        "chinese_records": recs_zh,
        "english_records": recs_en,
    }
    (out_dir / "chinese_eval_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8",
    )

    # Record to eval history
    if sum_zh:
        _eval.record_eval_result(
            pipeline="nl2sql_bird_pg_chinese_full",
            overall_score=sum_zh["execution_accuracy"],
            pass_rate=sum_zh["execution_accuracy"],
            verdict="PASS" if sum_zh["execution_accuracy"] >= 0.5 else "FAIL",
            num_tests=sum_zh["n"], num_passed=sum(r["ex"] for r in recs_zh),
            model=os.environ.get("MODEL_STANDARD", "gemini-2.5-flash"),
            scenario="bird_mini_dev_pg_chinese", metrics=sum_zh,
        )

    print(f"\n[zh-eval] Report saved to {out_dir / 'chinese_eval_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
