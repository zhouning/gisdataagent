#!/usr/bin/env python3
"""Run five-fold, three-seed recursive DAM-GK region validation."""

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
    parser.add_argument("--fold-count", type=int, default=5)
    parser.add_argument("--sample-stride", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--seeds", type=int, nargs="+", default=[31, 47, 73])
    parser.add_argument("--output-dir", type=Path, required=True)
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
    folds = [region_ids[index :: args.fold_count] for index in range(args.fold_count)]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in args.seeds:
        for fold_index in range(args.fold_count):
            test_regions = folds[fold_index]
            validation_regions = folds[(fold_index + 1) % args.fold_count]
            excluded = set(test_regions) | set(validation_regions)
            training_regions = [region for region in region_ids if region not in excluded]
            report = run_twm_recursive_region_holdout(
                data_root=args.data_root,
                training_region_ids=training_regions,
                validation_region_ids=validation_regions,
                test_region_ids=test_regions,
                seed=seed,
                sample_stride=args.sample_stride,
                epochs=args.epochs,
                use_temporal_history_context=not args.disable_temporal_history_context,
            )
            report["fold_index"] = fold_index
            report["fold_count"] = args.fold_count
            run_path = args.output_dir / f"fold_{fold_index}_seed_{seed}.json"
            run_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            recursive = report["reports"]["recursive_writeback"]["final_horizon"]
            frozen = report["reports"]["no_state_writeback"]["final_horizon"]
            chained = report["reports"]["independent_one_step_chain"][
                "final_horizon"
            ]
            persistence = report["reports"]["persistence"]["final_horizon"]
            rows.append(
                {
                    "seed": seed,
                    "fold_index": fold_index,
                    "test_regions": test_regions,
                    "recursive_change_f1": recursive["change_f1"],
                    "frozen_change_f1": frozen["change_f1"],
                    "chained_change_f1": chained["change_f1"],
                    "recursive_class_macro_f1": recursive["next_class_macro_f1"],
                    "frozen_class_macro_f1": frozen["next_class_macro_f1"],
                    "persistence_class_macro_f1": persistence[
                        "next_class_macro_f1"
                    ],
                    "recursive_changed_destination_macro_f1": recursive[
                        "changed_destination_macro_f1"
                    ],
                    "frozen_changed_destination_macro_f1": frozen[
                        "changed_destination_macro_f1"
                    ],
                    "chained_changed_destination_macro_f1": chained[
                        "changed_destination_macro_f1"
                    ],
                }
            )
            print(f"completed fold={fold_index} seed={seed}", flush=True)

    summary = {
        "schema": "gwm.dam_gk.twm_recursive_region_matrix.v1",
        "fold_count": args.fold_count,
        "seeds": args.seeds,
        "sample_stride": args.sample_stride,
        "epochs": args.epochs,
        "temporal_history_context": not args.disable_temporal_history_context,
        "run_count": len(rows),
        "rows": rows,
        "aggregate": {
            "recursive_beats_frozen_change_f1": sum(
                row["recursive_change_f1"] > row["frozen_change_f1"] for row in rows
            ),
            "recursive_beats_frozen_class_macro_f1": sum(
                row["recursive_class_macro_f1"]
                > row["frozen_class_macro_f1"]
                for row in rows
            ),
            "recursive_beats_one_step_chain_change_f1": sum(
                row["recursive_change_f1"] > row["chained_change_f1"]
                for row in rows
            ),
            "recursive_beats_persistence_class_macro_f1": sum(
                row["recursive_class_macro_f1"]
                > row["persistence_class_macro_f1"]
                for row in rows
            ),
            "mean_recursive_change_f1": _mean(
                row["recursive_change_f1"] for row in rows
            ),
            "mean_frozen_change_f1": _mean(
                row["frozen_change_f1"] for row in rows
            ),
            "mean_chained_change_f1": _mean(
                row["chained_change_f1"] for row in rows
            ),
            "mean_recursive_class_macro_f1": _mean(
                row["recursive_class_macro_f1"] for row in rows
            ),
            "mean_persistence_class_macro_f1": _mean(
                row["persistence_class_macro_f1"] for row in rows
            ),
            "recursive_beats_frozen_changed_destination_macro_f1": sum(
                row["recursive_changed_destination_macro_f1"]
                > row["frozen_changed_destination_macro_f1"]
                for row in rows
            ),
            "recursive_beats_chain_changed_destination_macro_f1": sum(
                row["recursive_changed_destination_macro_f1"]
                > row["chained_changed_destination_macro_f1"]
                for row in rows
            ),
            "mean_recursive_changed_destination_macro_f1": _mean(
                row["recursive_changed_destination_macro_f1"] for row in rows
            ),
            "mean_frozen_changed_destination_macro_f1": _mean(
                row["frozen_changed_destination_macro_f1"] for row in rows
            ),
            "mean_chained_changed_destination_macro_f1": _mean(
                row["chained_changed_destination_macro_f1"] for row in rows
            ),
        },
        "claim_boundary": {
            "all_run_stability_required": True,
            "action_conditioning_claim": False,
            "policy_effect_claim": False,
        },
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary["aggregate"], ensure_ascii=False, indent=2))


def _mean(values) -> float:
    rows = list(values)
    return round(sum(rows) / len(rows), 6)


if __name__ == "__main__":
    main()
