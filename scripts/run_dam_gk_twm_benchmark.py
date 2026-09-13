#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.dam_geospatial_kernel.twm_benchmark import (
    run_twm_cross_region_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--sample-stride", type=int, default=16)
    parser.add_argument("--region-limit", type=int)
    parser.add_argument("--held-out-region-count", type=int, default=0)
    parser.add_argument("--held-out-region", action="append", default=[])
    args = parser.parse_args()
    report = run_twm_cross_region_benchmark(
        data_root=args.data_root,
        seed=args.seed,
        epochs=args.epochs,
        sample_stride=args.sample_stride,
        region_limit=args.region_limit,
        held_out_region_count=args.held_out_region_count,
        held_out_region_ids=args.held_out_region or None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
