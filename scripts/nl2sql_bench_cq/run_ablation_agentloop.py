"""Agent-loop-native ablation on GIS Spatial 85q.

Runs 6 configurations (Full + 5 with one component disabled) on the
enhanced-mode pipeline, which threads the same semantic-grounding +
postprocessor + self-correction components that full agent mode uses.

Each config sets an NL2SQL_DISABLE_* env flag:
  - NL2SQL_DISABLE_SEMANTIC    grounding returns empty payload
  - NL2SQL_DISABLE_INTENT      classify_intent returns UNKNOWN
  - NL2SQL_DISABLE_FEWSHOT     few-shot retrieval returns []
  - NL2SQL_DISABLE_POSTPROCESSOR  bypass postprocess_sql
  - NL2SQL_DISABLE_RETRY       skip self-correction loop

Resume-safe: skips configs whose *_results.json already exists.
Emits a progress line per question so the process never falls silent.

~6 × 85 = 510 Gemini calls; expect 2-3h wall clock.

Responds to 2026-05-07 reviewer A §3.2 and reviewer B §1.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "D:/adk")
sys.path.insert(0, str(Path("D:/adk/scripts/nl2sql_bench_cq")))

from run_cq_eval import run_one, _init_runtime, load_questions, RESULTS_ROOT  # noqa: E402

BENCHMARK = Path("D:/adk/benchmarks/chongqing_geo_nl2sql_100_benchmark.json")

CONFIGS = {
    "Full":                {},
    "noSemanticGrounding": {"NL2SQL_DISABLE_SEMANTIC": "1"},
    "noIntentRouting":     {"NL2SQL_DISABLE_INTENT": "1"},
    "noPostprocessor":     {"NL2SQL_DISABLE_POSTPROCESSOR": "1"},
    "noSelfCorrection":    {"NL2SQL_DISABLE_RETRY": "1"},
    "noFewShot":           {"NL2SQL_DISABLE_FEWSHOT": "1"},
}
_FLAGS = [
    "NL2SQL_DISABLE_SEMANTIC", "NL2SQL_DISABLE_INTENT",
    "NL2SQL_DISABLE_POSTPROCESSOR", "NL2SQL_DISABLE_RETRY",
    "NL2SQL_DISABLE_FEWSHOT",
]


async def main() -> None:
    _init_runtime()
    spatial = [q for q in load_questions(BENCHMARK)
               if q.get("difficulty") != "Robustness"]
    assert len(spatial) == 85, f"Expected 85 Spatial questions, got {len(spatial)}"

    out_dir_name = os.environ.get("ABLATION_OUT_DIR")
    if out_dir_name:
        out_dir = RESULTS_ROOT / out_dir_name
    else:
        out_dir = RESULTS_ROOT / f"ablation_agentloop_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[ablation] out_dir = {out_dir}", flush=True)

    summary: dict[str, dict] = {}
    for cfg, envs in CONFIGS.items():
        out_file = out_dir / f"{cfg}_results.json"
        if out_file.exists():
            s = json.loads(out_file.read_text(encoding="utf-8"))["summary"]
            summary[cfg] = s
            print(f"[skip] {cfg}: already done ({s['ex']}/{s['n']})", flush=True)
            continue

        for k in _FLAGS:
            os.environ.pop(k, None)
        for k, v in envs.items():
            os.environ[k] = v

        print(f"\n=== {cfg} ({len(spatial)} q) ===", flush=True)
        t_cfg = time.time()
        recs: list[dict] = []
        for i, q in enumerate(spatial, 1):
            t0 = time.time()
            try:
                rec = await run_one(q, mode="full")
            except Exception as e:
                rec = {"qid": q["id"], "ex": 0,
                       "reason": f"exc:{type(e).__name__}:{e}"[:200]}
            dt = time.time() - t0
            recs.append(rec)
            ok = "OK" if rec.get("ex") else "--"
            print(f"  [{cfg}] {i:>2d}/{len(spatial)} {ok} {rec['qid']:24s} "
                  f"{dt:>5.1f}s (running ex={sum(r.get('ex', 0) for r in recs)})",
                  flush=True)

        ex = sum(r.get("ex", 0) for r in recs)
        s = {"n": len(recs), "ex": ex, "ex_rate": round(ex / len(recs), 4),
             "wall_clock_s": round(time.time() - t_cfg, 1)}
        summary[cfg] = s
        out_file.write_text(
            json.dumps({"summary": s, "records": recs},
                       indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"[{cfg}] EX = {s['ex_rate']:.3f}  ({ex}/{s['n']})  "
              f"t={s['wall_clock_s']}s", flush=True)

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("\n=== Ablation summary ===", flush=True)
    for cfg, s in summary.items():
        print(f"  {cfg:25s} EX = {s['ex_rate']:.3f}  ({s['ex']}/{s['n']})",
              flush=True)


if __name__ == "__main__":
    asyncio.run(main())
