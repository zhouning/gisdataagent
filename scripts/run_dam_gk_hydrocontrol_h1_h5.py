#!/usr/bin/env python3
"""Run the frozen DAM-GK HydroControl H1/H5 retrospective protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_benchmark import (
    run_hydrocontrol_dam_gk_benchmark,
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--panel",
        type=Path,
        default=root
        / "data/gwm_hydrocontrol_california_hourly_v3/hourly_state_action_outcome_panel.parquet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root
        / "data/benchmarks/dam_gk_2026-07-20/hydrocontrol_h1_h5.json",
    )
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=31)
    args = parser.parse_args()
    report = run_hydrocontrol_dam_gk_benchmark(
        pd.read_parquet(args.panel.resolve()),
        seed=args.seed,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["adjudication"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
