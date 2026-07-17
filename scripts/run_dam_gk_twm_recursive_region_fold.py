#!/usr/bin/env python3
"""Run one disjoint-region fold of the recursive DAM-GK benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.dam_geospatial_kernel.twm_sequence_benchmark import (
    run_twm_recursive_region_holdout,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/twm_public_landcover/gee_dynamic_world"),
    )
    parser.add_argument("--fold-index", type=int, default=0)
    parser.add_argument("--fold-count", type=int, default=5)
    parser.add_argument("--sample-stride", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--disable-temporal-history-context", action="store_true")
    args = parser.parse_args()

    region_ids = sorted(
        path.name
        for path in args.data_root.iterdir()
        if path.is_dir()
        and all(
            (path / f"{path.name}_dynamic_world_{year}_100m.tif").exists()
            for year in range(2017, 2024)
        )
    )
    if args.fold_count < 3 or len(region_ids) < args.fold_count:
        raise ValueError("at_least_three_nonempty_region_folds_required")
    folds = [region_ids[index :: args.fold_count] for index in range(args.fold_count)]
    if not 0 <= args.fold_index < args.fold_count:
        raise ValueError("fold_index_out_of_range")
    test_regions = folds[args.fold_index]
    validation_regions = folds[(args.fold_index + 1) % args.fold_count]
    excluded = set(test_regions) | set(validation_regions)
    training_regions = [region for region in region_ids if region not in excluded]
    report = run_twm_recursive_region_holdout(
        data_root=args.data_root,
        training_region_ids=training_regions,
        validation_region_ids=validation_regions,
        test_region_ids=test_regions,
        seed=args.seed,
        sample_stride=args.sample_stride,
        epochs=args.epochs,
        use_temporal_history_context=not args.disable_temporal_history_context,
    )
    report["fold_index"] = args.fold_index
    report["fold_count"] = args.fold_count
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
