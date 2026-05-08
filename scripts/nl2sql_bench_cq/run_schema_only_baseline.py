"""Schema-only + postprocessor + retry middle baseline on GIS Spatial 85q.

Disables semantic grounding / intent routing / few-shot; keeps postprocessor
and self-correction (which the pure baseline lacks). Isolates what portion
of the Full-vs-baseline gain comes from semantic grounding specifically vs
from the generic postprocessor+retry scaffold.

Responds to 2026-05-07 reviewer A §3.3.
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

os.environ["NL2SQL_DISABLE_SEMANTIC"] = "1"
os.environ["NL2SQL_DISABLE_INTENT"] = "1"
os.environ["NL2SQL_DISABLE_FEWSHOT"] = "1"
os.environ.setdefault("CQ_EVAL_QUESTION_TIMEOUT", "90")

from run_cq_eval import run_one, _init_runtime, load_questions, RESULTS_ROOT  # noqa: E402

BENCHMARK = Path("D:/adk/benchmarks/chongqing_geo_nl2sql_100_benchmark.json")


async def main() -> None:
    _init_runtime()
    spatial = [q for q in load_questions(BENCHMARK)
               if q.get("difficulty") != "Robustness"]
    assert len(spatial) == 85, f"Expected 85 Spatial, got {len(spatial)}"

    out_dir = RESULTS_ROOT / f"schema_only_baseline_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    partial_file = out_dir / "results_partial.json"
    final_file = out_dir / "results.json"

    recs: list[dict] = []
    done_qids: set[str] = set()
    if partial_file.exists():
        prev = json.loads(partial_file.read_text(encoding="utf-8"))
        recs = prev.get("records", [])
        done_qids = {r["qid"] for r in recs}
        print(f"[resume] loaded {len(recs)} prior records", flush=True)

    t0_all = time.time()
    for i, q in enumerate(spatial, 1):
        if q["id"] in done_qids:
            continue
        t0 = time.time()
        try:
            rec = await run_one(q, mode="full")
        except Exception as e:
            rec = {"qid": q["id"], "ex": 0,
                   "reason": f"exc:{type(e).__name__}:{e}"[:200]}
        dt = time.time() - t0
        recs.append(rec)
        running = sum(r.get("ex", 0) for r in recs)
        ok = "OK" if rec.get("ex") else "--"
        print(f"  [schema_only] {i:>2d}/{len(spatial)} {ok} "
              f"{rec['qid']:24s} {dt:>5.1f}s (running ex={running})",
              flush=True)
        s = {"n": len(recs), "ex": running,
             "ex_rate": round(running / len(recs), 4),
             "wall_clock_s": round(time.time() - t0_all, 1)}
        partial_file.write_text(
            json.dumps({"summary": s, "records": recs},
                       indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    final_file.write_text(partial_file.read_text(encoding="utf-8"),
                          encoding="utf-8")
    partial_file.unlink()
    s = json.loads(final_file.read_text(encoding="utf-8"))["summary"]
    print(f"\nschema-only+pp+retry EX = {s['ex_rate']:.3f} "
          f"({s['ex']}/{s['n']}) t={s['wall_clock_s']}s  "
          f"dir={out_dir.name}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
