#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.dam_geospatial_kernel import run_controlled_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=180)
    parser.add_argument("--train-samples", type=int, default=96)
    parser.add_argument("--test-samples", type=int, default=32)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    report = run_controlled_benchmark(
        seed=args.seed,
        train_sample_count=args.train_samples,
        test_sample_count=args.test_samples,
        epochs=args.epochs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
