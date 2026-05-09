"""Cross-family N=3 experiment on the full 85q GIS Spatial benchmark.

Runs DeepSeek baseline × N=3 and DeepSeek full × N=3, at each family's own
default temperature. Gemini baseline and Gemini full × N=3 are NOT re-run —
the historical v5 main-paper samples are reused verbatim (same code path for
the Gemini side: no generate_content_config, same model string, zero 429
errors in the historical records so retry_options add no behavioural drift).

This runner only produces the DeepSeek side; statistics are computed by a
separate stats script that pools all 8 sample files (2 Gemini baselines —
one from Sample2's baseline_results.json — plus 3 Gemini full, plus 3 DeepSeek
baselines and 3 DeepSeek full).

Usage:
  cd D:\\adk
  PYTHONPATH=D:/adk PYTHONIOENCODING=utf-8 \\
    .venv/Scripts/python.exe scripts/nl2sql_bench_cq/run_cross_family_85q.py
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

BENCH = ROOT / "benchmarks" / "chongqing_geo_nl2sql_100_benchmark.json"
OUT_ROOT = ROOT / "data_agent" / "nl2sql_eval_results"


def load_spatial_85q() -> list[dict]:
    rows = json.loads(BENCH.read_text(encoding="utf-8"))
    sp = [r for r in rows
          if str(r.get("difficulty", "")).lower() in ("easy", "medium", "hard")]
    assert len(sp) == 85, f"expected 85 Spatial, got {len(sp)}"
    return sp


def _reset_cq_caches() -> None:
    for name in ("run_cq_eval", "nl2sql_agent", "run_open_source_ablation"):
        if name in sys.modules:
            del sys.modules[name]


async def run_one_cell(family: str, mode: str, qs: list[dict], sample_idx: int,
                       out_dir: Path) -> list[dict]:
    """Run one (family, mode, sample_idx) cell across all 85 questions."""
    _reset_cq_caches()
    if family == "deepseek":
        os.environ["NL2SQL_FORCE_DEEPSEEK"] = "1"
        os.environ["NL2SQL_AGENT_MODEL"] = "deepseek-v4-flash"
    else:
        os.environ.pop("NL2SQL_FORCE_DEEPSEEK", None)
        os.environ["NL2SQL_AGENT_MODEL"] = "gemini-2.5-flash"

    from run_cq_eval import run_one, _init_runtime
    _init_runtime()

    # Probe to assert correct routing (no temperature pinning; each family
    # gets its own provider default)
    if mode == "full":
        from nl2sql_agent import build_nl2sql_agent
        agent = build_nl2sql_agent()
        mt = type(agent.model).__name__
        expected = "LiteLlm" if family == "deepseek" else "Gemini"
        assert mt == expected, f"[{family}/{mode}/s{sample_idx}] expected {expected}, got {mt}"
        assert agent.generate_content_config is None, \
            f"[{family}/{mode}/s{sample_idx}] generate_content_config should be None (default), got {agent.generate_content_config}"
        print(f"  [probe/{family}/{mode}/s{sample_idx}] model_type={mt}  gen_cfg=None (provider default)",
              flush=True)

    recs = []
    for i, q in enumerate(qs, 1):
        t0 = datetime.now()
        try:
            rec = await asyncio.wait_for(run_one(q, mode), timeout=300)
        except asyncio.TimeoutError:
            rec = {
                "qid": q.get("id", q.get("question_id", "?")),
                "ex": 0, "valid": 0, "gen_status": "timeout",
                "gen_error": "300s per-question timeout",
            }
        except Exception as e:
            rec = {
                "qid": q.get("id", q.get("question_id", "?")),
                "ex": 0, "valid": 0, "gen_status": "exception",
                "gen_error": str(e)[:300],
            }
        rec["family"] = family
        rec["mode"] = mode
        rec["sample_idx"] = sample_idx
        recs.append(rec)
        dur = (datetime.now() - t0).total_seconds()
        m = "OK" if rec.get("ex") else ("VAL" if rec.get("valid") else "ERR")
        print(f"  [{family}/{mode}/s{sample_idx} {i}/{len(qs)}] {m} {rec.get('qid')} "
              f"ex={rec.get('ex')} dur={dur:.1f}s", flush=True)
        # Incremental persistence every 10 questions
        if i % 10 == 0 or i == len(qs):
            _persist_cell(out_dir, family, mode, sample_idx, recs, len(qs))
    return recs


def _persist_cell(out_dir: Path, family: str, mode: str, sample_idx: int,
                  recs: list[dict], n_total: int) -> None:
    ex_count = sum(1 for r in recs if r.get("ex"))
    out_path = out_dir / f"{family}_{mode}_s{sample_idx}_results.json"
    out_path.write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(),
            "family": family, "mode": mode, "sample_idx": sample_idx,
            "benchmark": str(BENCH.relative_to(ROOT)),
            "n_questions": n_total,
            "n_completed": len(recs),
            "ex": round(ex_count / max(1, len(recs)), 4),
            "records": recs,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


async def main() -> int:
    qs = load_spatial_85q()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = OUT_ROOT / f"cross_family_85q_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[runner] benchmark: {BENCH.name}, {len(qs)} questions")
    print(f"[runner] out_dir: {out_dir}")

    # Skip Gemini — reuse historical N=3 from v5 main paper (see stats script)

    # DeepSeek baseline × N=3
    for i in (1, 2, 3):
        print(f"\n=== DeepSeek baseline sample {i}/3 ({datetime.now().strftime('%H:%M:%S')}) ===")
        t0 = datetime.now()
        recs = await run_one_cell("deepseek", "baseline", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        print(f"\n[runner] DeepSeek baseline sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  wall={dur_min:.1f}min")

    # DeepSeek full × N=3
    for i in (1, 2, 3):
        print(f"\n=== DeepSeek full sample {i}/3 ({datetime.now().strftime('%H:%M:%S')}) ===")
        t0 = datetime.now()
        recs = await run_one_cell("deepseek", "full", qs, i, out_dir)
        dur_min = (datetime.now() - t0).total_seconds() / 60
        ex_count = sum(1 for r in recs if r.get("ex"))
        print(f"\n[runner] DeepSeek full sample {i}: {ex_count}/{len(recs)} "
              f"EX={ex_count/max(1,len(recs)):.4f}  wall={dur_min:.1f}min")

    print(f"\n[runner] All 6 DeepSeek samples written to: {out_dir}")
    print(f"[runner] Next: run scripts/nl2sql_bench_cq/stats_cross_family_85q.py --out-dir {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
