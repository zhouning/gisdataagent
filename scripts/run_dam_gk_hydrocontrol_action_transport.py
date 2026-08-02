#!/usr/bin/env python3
"""Run HydroControl DAM-GK v0.2 action-transport evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_action_transport_benchmark import (
    evaluate_action_transport_kernel,
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-year", type=int, choices=(2024, 2025), required=True)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument(
        "--panel",
        type=Path,
        default=root
        / "data/gwm_hydrocontrol_california_hourly_v3/"
        "hourly_state_action_outcome_panel.parquet",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        root
        / "data/benchmarks/dam_gk_2026-07-20/"
        f"hydrocontrol_action_transport_{args.evaluation_year}.json"
    )
    report = evaluate_action_transport_kernel(
        pd.read_parquet(args.panel.resolve()),
        evaluation_year=args.evaluation_year,
        seed=args.seed,
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
