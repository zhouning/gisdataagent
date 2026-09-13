#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from data_agent.uwm.dam_geospatial_kernel.twm_benchmark import (
    run_twm_cross_region_benchmark,
)


VARIANTS = (
    "dam_gk_multirelational",
    "relative_edge_geometry",
    "no_multiscale_consistency",
    "region_conditioned",
    "relation_channel_residual",
    "single_relation",
    "frozen_topology",
    "target_only_mlp",
)
CHECKS = (
    "beats_strongest_statistical_baseline_change_f1",
    "beats_target_only_mlp_change_f1",
    "region_conditioning_improves_change_f1",
    "multi_relation_improves_change_f1",
    "dynamic_topology_improves_change_f1",
    "relation_shuffle_degrades_change_f1",
    "spatial_rewire_degrades_change_f1",
    "coordinate_permutation_degrades_change_f1",
    "edge_geometry_permutation_degrades_change_f1",
    "relative_edge_geometry_improves_change_f1",
    "multiscale_consistency_reduces_error",
)


def discover_regions(data_root: Path) -> list[str]:
    return sorted(
        path.name
        for path in data_root.iterdir()
        if path.is_dir()
        and (path / f"{path.name}_dynamic_world_2017_100m.tif").exists()
        and (path / f"{path.name}_dynamic_world_2023_100m.tif").exists()
    )


def build_round_robin_folds(region_ids: list[str], fold_count: int) -> list[list[str]]:
    if fold_count < 2 or fold_count > len(region_ids):
        raise ValueError("fold_count_out_of_range")
    return [region_ids[index::fold_count] for index in range(fold_count)]


def summarize_cross_validation(reports: list[dict[str, Any]]) -> dict[str, Any]:
    fold_ids = sorted({int(report["cross_validation_fold"]) for report in reports})
    seeds = sorted({int(report["seed"]) for report in reports})
    expected = {(fold_id, seed) for fold_id in fold_ids for seed in seeds}
    observed = {
        (int(report["cross_validation_fold"]), int(report["seed"]))
        for report in reports
    }
    if expected != observed:
        raise ValueError("incomplete_fold_seed_matrix")
    test_occurrences: dict[str, int] = {}
    for report in reports:
        if report["seed"] != seeds[0]:
            continue
        for region_id in report["test_region_ids"]:
            test_occurrences[region_id] = test_occurrences.get(region_id, 0) + 1

    available_variants = [
        variant
        for variant in VARIANTS
        if all(variant in report["variant_metrics"] for report in reports)
    ]
    variant_summary = {}
    for variant in available_variants:
        values = [
            report["variant_metrics"][variant]["test"]["change_f1"]
            for report in reports
        ]
        fold_means = {
            str(fold_id): round(
                mean(
                    report["variant_metrics"][variant]["test"]["change_f1"]
                    for report in reports
                    if report["cross_validation_fold"] == fold_id
                ),
                8,
            )
            for fold_id in fold_ids
        }
        variant_summary[variant] = {
            "change_f1_mean": round(mean(values), 8),
            "change_f1_population_std": round(pstdev(values), 8),
            "change_f1_min": round(min(values), 8),
            "change_f1_max": round(max(values), 8),
            "fold_mean_change_f1": fold_means,
        }

    available_checks = [
        check
        for check in CHECKS
        if all(check in report["hypothesis_checks"] for report in reports)
    ]
    hypothesis_stability = {}
    for check in available_checks:
        outcomes = [bool(report["hypothesis_checks"][check]) for report in reports]
        fold_passes = {
            str(fold_id): sum(
                bool(report["hypothesis_checks"][check])
                for report in reports
                if report["cross_validation_fold"] == fold_id
            )
            for fold_id in fold_ids
        }
        hypothesis_stability[check] = {
            "passed_runs": sum(outcomes),
            "total_runs": len(outcomes),
            "pass_rate": round(sum(outcomes) / len(outcomes), 8),
            "fold_passes": fold_passes,
            "stable_across_all_runs": all(outcomes),
        }

    return {
        "schema": "gwm.dam_gk.twm_region_cross_validation.v1",
        "fold_count": len(fold_ids),
        "seeds": seeds,
        "run_count": len(reports),
        "test_region_occurrences": test_occurrences,
        "each_region_tested_once_per_seed": all(
            count == 1 for count in test_occurrences.values()
        ),
        "variant_summary": variant_summary,
        "hypothesis_stability": hypothesis_stability,
        "claim_boundary": _claim_boundary(hypothesis_stability),
    }


def _claim_boundary(hypothesis_stability: dict[str, Any]) -> dict[str, bool | None]:
    mapping = {
        "statistical_baseline_advantage_stable": "beats_strongest_statistical_baseline_change_f1",
        "target_only_advantage_stable": "beats_target_only_mlp_change_f1",
        "region_conditioning_necessity_stable": "region_conditioning_improves_change_f1",
        "multi_relation_necessity_stable": "multi_relation_improves_change_f1",
        "dynamic_topology_necessity_stable": "dynamic_topology_improves_change_f1",
        "relation_semantics_used_stably": "relation_shuffle_degrades_change_f1",
        "spatial_topology_used_stably": "spatial_rewire_degrades_change_f1",
        "absolute_coordinates_used_stably": "coordinate_permutation_degrades_change_f1",
        "relative_edge_geometry_used_stably": "edge_geometry_permutation_degrades_change_f1",
        "relative_edge_geometry_improves_stably": "relative_edge_geometry_improves_change_f1",
        "multiscale_consistency_reduces_error_stably": "multiscale_consistency_reduces_error",
    }
    boundary = {
        claim: hypothesis_stability[check]["stable_across_all_runs"]
        if check in hypothesis_stability
        else None
        for claim, check in mapping.items()
    }
    boundary["policy_effect_claim"] = False
    return boundary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fold-count", type=int, default=5)
    parser.add_argument("--seeds", type=int, nargs="+", default=[31, 47, 73])
    parser.add_argument("--epochs", type=int, default=180)
    parser.add_argument("--sample-stride", type=int, default=24)
    args = parser.parse_args()

    region_ids = discover_regions(args.data_root)
    folds = build_round_robin_folds(region_ids, args.fold_count)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for fold_index, test_regions in enumerate(folds, start=1):
        for seed in args.seeds:
            report = run_twm_cross_region_benchmark(
                data_root=args.data_root,
                seed=seed,
                sample_stride=args.sample_stride,
                epochs=args.epochs,
                held_out_region_ids=test_regions,
            )
            report["cross_validation_fold"] = fold_index
            path = args.output_dir / f"fold{fold_index}_seed{seed}.json"
            path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            reports.append(report)
            print(path, flush=True)
    summary = summarize_cross_validation(reports)
    summary["folds"] = {
        str(index): fold for index, fold in enumerate(folds, start=1)
    }
    summary_path = args.output_dir / "cross_validation_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary_path)


if __name__ == "__main__":
    main()
