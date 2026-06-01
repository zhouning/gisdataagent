"""Smoke test for the gemma4-26b-host43 cell (Wave: cross-host benchmark).

Purpose: validate that the new pinned model entry (`gemma4-26b-host43` ->
192.168.43.10:11434, paired with `nomic-embed-text-v2-moe-host43`)
end-to-ends through the NL2SQL eval harness in both baseline and full mode.

Scope: 8 questions × baseline + full × N=1. Not a statistical claim.
Intended runtime: 15-25 min on the user's local network.

Output: data_agent/nl2sql_eval_results/smoke_host43_<ts>/
  - host43_baseline_s1_results.json
  - host43_full_s1_results.json
  - summary.json   (totals + comparison vs golden)

Usage:
  cd D:\\adk
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
    .venv/Scripts/python.exe scripts/nl2sql_bench_cq/smoke_host43.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / "data_agent" / ".env"), override=False)

# Pin both LLM and embedding to the new host BEFORE any imports trigger
# their respective registries.
os.environ["NL2SQL_AGENT_MODEL"] = "gemma4-26b-host43"
os.environ["EMBEDDING_MODEL"] = "nomic-embed-text-v2-moe-host43"
# 192.168.43.10 is meaningfully slower than 192.168.31.252 on Gemma4:26b;
# bump per-question timeout so full-mode multi-step prompts have room.
os.environ["CQ_EVAL_QUESTION_TIMEOUT"] = "540"

OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"
BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"

# Smoke selection: 3 Easy + 2 Medium + 1 Hard + 2 Robustness.
# Coverage: simple count + spatial join + filter + aggregate +
# multi-table + 2 robustness traps.
SMOKE_IDS = [
    "CQ_GEO_EASY_01",          # COUNT WHERE
    "CQ_GEO_EASY_02",          # filter on numeric
    "CQ_GEO_EASY_05",          # text LIKE
    "CQ_GEO_MEDIUM_01",        # SUM with cast::geography
    "CQ_GEO_MEDIUM_03",        # spatial join
    "CQ_GEO_HARD_01",          # multi-table with subquery
    "CQ_GEO_ROBUSTNESS_01",    # nonexistent column trap
    "CQ_GEO_ROBUSTNESS_05",    # nonexistent table trap
]


def _reset_caches() -> None:
    for name in ("run_cq_eval", "nl2sql_agent", "run_open_source_ablation"):
        if name in sys.modules:
            del sys.modules[name]


async def run_cell(mode: str, qs: list[dict],
                   out_dir: Path) -> list[dict]:
    _reset_caches()
    os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
    os.environ.pop("NL2SQL_PROMPT_FAMILY_OVERRIDE", None)

    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    # baseline_generate() is hard-coded to Gemini; redirect it to the
    # family-aware wrapper for the smoke. This is the same trick
    # probe_baseline_gemma_ollama.py uses (just not yet baked into the
    # eval pipeline). We restore at function exit so the rest of the
    # process is unaffected.
    import run_cq_eval as _rcq
    _orig_baseline = _rcq.baseline_generate
    _rcq.baseline_generate = lambda question: _rcq.baseline_generate_family_aware(
        question, "gemma4-26b-host43"
    )

    if mode == "full":
        from nl2sql_agent import build_nl2sql_agent
        agent = build_nl2sql_agent()
        cls_name = type(agent.model).__name__
        model_str = getattr(agent.model, "model", "?")
        api_base = getattr(agent.model, "api_base", "?")
        print(f"  [probe/host43/{mode}] class={cls_name} model={model_str} "
              f"api_base={api_base}", flush=True)

    try:
        recs = []
        for i, q in enumerate(qs, 1):
            t0 = datetime.now()
            try:
                rec = await asyncio.wait_for(run_one(q, mode), timeout=300)
            except asyncio.TimeoutError:
                rec = {"qid": q.get("id", "?"), "ex": 0, "valid": 0,
                       "gen_status": "timeout",
                       "gen_error": "300s per-question timeout"}
            except Exception as e:
                rec = {"qid": q.get("id", "?"), "ex": 0, "valid": 0,
                       "gen_status": "exception",
                       "gen_error": str(e)[:300]}
            rec["family"] = "gemma4-26b-host43"
            rec["mode"] = mode
            recs.append(rec)
            dur = (datetime.now() - t0).total_seconds()
            m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
            print(f"  [host43/{mode} {i}/{len(qs)}] {m} {rec.get('qid')} "
                  f"ex={rec.get('ex')} dur={dur:.1f}s", flush=True)
    finally:
        _rcq.baseline_generate = _orig_baseline

    out_path = out_dir / f"host43_{mode}_s1_results.json"
    out_path.write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "family": "gemma4-26b-host43",
            "mode": mode, "sample_idx": 1,
            "benchmark": str(BENCH.relative_to(ROOT)),
            "host": "192.168.43.10:11434",
            "embedding_model": "nomic-embed-text-v2-moe-host43",
            "n_questions": len(qs),
            "n_completed": len(recs),
            "ex": round(sum(1 for r in recs if r.get("ex"))
                        / max(1, len(recs)), 4),
            "records": recs,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return recs


def _load_smoke_questions() -> list[dict]:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows}
    out: list[dict] = []
    missing: list[str] = []
    for qid in SMOKE_IDS:
        if qid in by_id:
            out.append(by_id[qid])
        else:
            missing.append(qid)
    if missing:
        raise SystemExit(f"smoke ids missing from benchmark: {missing}")
    return out


async def main() -> int:
    qs = _load_smoke_questions()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"smoke_host43_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[smoke] gemma4-26b-host43 (Gemma4:26b @ 192.168.43.10:11434)")
    print(f"[smoke] embedding: nomic-embed-text-v2-moe-host43")
    print(f"[smoke] questions: {len(qs)}  ids: {[q['id'] for q in qs]}")
    print(f"[smoke] out_dir: {out_dir}")

    summary = {"family": "gemma4-26b-host43",
               "host": "192.168.43.10:11434",
               "embedding_model": "nomic-embed-text-v2-moe-host43",
               "n_questions": len(qs), "modes": {}}

    for mode in ("baseline", "full"):
        print(f"\n=== {mode} ({datetime.now().strftime('%H:%M:%S')}) ===",
              flush=True)
        t0 = datetime.now()
        recs = await run_cell(mode, qs, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        empty = sum(1 for r in recs if not r.get("pred_sql"))
        guarded = sum(1 for r in recs
                      if "runtime_guard" in str(r.get("gen_error", "")))
        print(f"\n[smoke] {mode}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  EMPTY={empty}  "
              f"GUARDED={guarded}  wall={dur_min:.1f}min", flush=True)
        summary["modes"][mode] = {
            "ex": ex_count,
            "ex_rate": round(ex_count / max(1, len(recs)), 4),
            "empty": empty,
            "guarded": guarded,
            "wall_minutes": round(dur_min, 1),
            "per_question": [
                {"qid": r["qid"],
                 "difficulty": next((q["difficulty"] for q in qs
                                     if q["id"] == r["qid"]), "?"),
                 "ex": r.get("ex", 0),
                 "valid": r.get("valid", 0),
                 "gen_status": r.get("gen_status", "?")}
                for r in recs
            ],
        }

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\n[smoke] All cells done. Summary: {out_dir / 'summary.json'}")
    print(f"[smoke] Δ (full - baseline): "
          f"{summary['modes']['full']['ex_rate'] - summary['modes']['baseline']['ex_rate']:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
