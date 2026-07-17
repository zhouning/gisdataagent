#!/usr/bin/env python3
"""Run a bounded real-data recursive DAM-GK smoke benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    run_twm_recursive_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/twm_public_landcover/gee_dynamic_world"),
    )
    parser.add_argument("--region-limit", type=int, default=2)
    parser.add_argument("--sample-stride", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    region_ids = sorted(
        path.name
        for path in args.data_root.iterdir()
        if path.is_dir()
        and all(
            (path / f"{path.name}_dynamic_world_{year}_100m.tif").exists()
            for year in range(2017, 2024)
        )
    )[: args.region_limit]
    report = run_twm_recursive_benchmark(
        data_root=args.data_root,
        region_ids=region_ids,
        seed=args.seed,
        sample_stride=args.sample_stride,
        epochs=args.epochs,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
