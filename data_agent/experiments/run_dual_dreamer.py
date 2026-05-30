"""Run Dual-Layer Geospatial Dreamer experiments.

Main entrypoint for:
- full 5-method comparison
- smoke tests
- ablations

Examples:
    python -m data_agent.experiments.run_dual_dreamer --mode smoke
    python -m data_agent.experiments.run_dual_dreamer --mode main --seeds 5
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from data_agent.dual_dreamer_pipeline import PipelineConfig, run_pipeline

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Run Dual-Layer Dreamer experiments")
    parser.add_argument("--mode", choices=["smoke", "main", "ablation"], default="smoke")
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--eval-episodes", type=int, default=10)
    parser.add_argument("--dream-steps", type=int, default=5000)
    parser.add_argument("--output-dir", default="results_dual_dreamer")
    args = parser.parse_args()

    if args.mode == "smoke":
        cfg = PipelineConfig(
            seeds=list(range(1, args.seeds + 1)),
            eval_episodes=args.eval_episodes,
            dream_total_timesteps=min(args.dream_steps, 5000),
            n_episodes_random=20,
            n_episodes_greedy=20,
            tm_epochs=2,
            output_dir=args.output_dir,
        )
        results = run_pipeline(cfg, phases="1,2,3,4,5,6")
    elif args.mode == "main":
        cfg = PipelineConfig(
            seeds=list(range(1, args.seeds + 1)),
            eval_episodes=args.eval_episodes,
            dream_total_timesteps=max(args.dream_steps, 100000),
            output_dir=args.output_dir,
        )
        results = run_pipeline(cfg, phases="1,2,3,4,5,6")
    else:
        ablation_results = {}
        for interval in [1, 5, 10, 20]:
            cfg = PipelineConfig(
                seeds=list(range(1, args.seeds + 1)),
                eval_episodes=args.eval_episodes,
                dream_total_timesteps=min(args.dream_steps, 20000),
                calibration_interval=interval,
                output_dir=str(Path(args.output_dir) / f"calib_{interval}"),
                n_episodes_random=50,
                n_episodes_greedy=50,
                tm_epochs=5,
            )
            ablation_results[f"calibration_interval_{interval}"] = run_pipeline(cfg, phases="1,2,3,4,5,6")
        results = ablation_results
        out_file = Path(args.output_dir) / "ablation_summary.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        logger.info("Ablation summary saved to %s", out_file)

    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
