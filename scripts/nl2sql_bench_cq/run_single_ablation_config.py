"""Run a SINGLE ablation config over the 85 GIS Spatial questions.

Purpose: subprocess-isolatable. An outer driver invokes this with a specific
env-flag combination and a wall-clock timeout; if the process hangs on a
Gemini tool-call loop, the outer can SIGTERM/SIGKILL it safely.

Writes records incrementally to <out-dir>/<cfg>_partial.json after EVERY
question so partial progress survives a kill. On clean exit, promotes
partial → <cfg>_results.json.

Usage:
    .venv\\Scripts\\python.exe scripts/nl2sql_bench_cq/run_single_ablation_config.py \\
        <config_name> <out_dir>

config_name: Full | noSemanticGrounding | noIntentRouting | noPostprocessor
             | noSelfCorrection | noFewShot
out_dir: absolute path under data_agent/nl2sql_eval_results/

The env flags for <config_name> are applied at the top; caller does NOT
need to export them.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "D:/adk")
sys.path.insert(0, str(Path("D:/adk/scripts/nl2sql_bench_cq")))

CONFIGS = {
    "Full":                {},
    "noSemanticGrounding": {"NL2SQL_DISABLE_SEMANTIC": "1"},
    "noIntentRouting":     {"NL2SQL_DISABLE_INTENT": "1"},
    "noPostprocessor":     {"NL2SQL_DISABLE_POSTPROCESSOR": "1"},
    "noSelfCorrection":    {"NL2SQL_DISABLE_RETRY": "1"},
    "noFewShot":           {"NL2SQL_DISABLE_FEWSHOT": "1"},
}
_FLAGS = list({k for envs in CONFIGS.values() for k in envs})

BENCHMARK = Path("D:/adk/benchmarks/chongqing_geo_nl2sql_100_benchmark.json")


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: run_single_ablation_config.py <config_name> <out_dir>")
    cfg_name = sys.argv[1]
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    if cfg_name not in CONFIGS:
        raise SystemExit(f"Unknown config {cfg_name!r}. Choices: {list(CONFIGS)}")

    # Apply env flags
    for k in _FLAGS:
        os.environ.pop(k, None)
    for k, v in CONFIGS[cfg_name].items():
        os.environ[k] = v
    # Per-question asyncio-level timeout (best-effort; may not interrupt sync
    # HTTP calls inside the ADK SDK). Outer subprocess-level timeout is the
    # hard guarantee.
    os.environ.setdefault("CQ_EVAL_QUESTION_TIMEOUT", "90")

    # Lazy imports after env flags so they see them on first use
    from run_cq_eval import run_one, _init_runtime, load_questions
    _init_runtime()

    spatial = [q for q in load_questions(BENCHMARK)
               if q.get("difficulty") != "Robustness"]
    assert len(spatial) == 85, f"Expected 85 Spatial questions, got {len(spatial)}"

    partial_file = out_dir / f"{cfg_name}_partial.json"
    final_file = out_dir / f"{cfg_name}_results.json"

    # If partial exists, resume from where it left off
    recs: list[dict] = []
    done_qids: set[str] = set()
    if partial_file.exists():
        try:
            prev = json.loads(partial_file.read_text(encoding="utf-8"))
            recs = prev.get("records", [])
            done_qids = {r["qid"] for r in recs}
            print(f"[resume] {cfg_name}: loaded {len(recs)} prior records",
                  flush=True)
        except Exception as e:
            print(f"[resume] could not load partial ({e}); starting fresh",
                  flush=True)

    print(f"=== {cfg_name} ({len(spatial)} questions) ===", flush=True)
    t_cfg = time.time()

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

        running_ex = sum(r.get("ex", 0) for r in recs)
        ok = "OK" if rec.get("ex") else "--"
        print(f"  [{cfg_name}] {i:>2d}/{len(spatial)} {ok} "
              f"{rec['qid']:24s} {dt:>5.1f}s (running ex={running_ex})",
              flush=True)

        # Write partial after EVERY question so a kill preserves progress
        s = {"n": len(recs), "ex": running_ex,
             "ex_rate": round(running_ex / len(recs), 4),
             "wall_clock_s": round(time.time() - t_cfg, 1)}
        partial_file.write_text(
            json.dumps({"summary": s, "records": recs},
                       indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # Clean exit: promote partial → final
    final_file.write_text(partial_file.read_text(encoding="utf-8"),
                          encoding="utf-8")
    partial_file.unlink()
    s_final = json.loads(final_file.read_text(encoding="utf-8"))["summary"]
    print(f"\n[{cfg_name}] EX = {s_final['ex_rate']:.3f} "
          f"({s_final['ex']}/{s_final['n']}) t={s_final['wall_clock_s']}s",
          flush=True)


if __name__ == "__main__":
    asyncio.run(main())
