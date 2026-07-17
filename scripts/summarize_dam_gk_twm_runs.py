#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


CHECK_NAMES = (
    "beats_strongest_statistical_baseline_change_f1",
    "beats_target_only_mlp_change_f1",
    "region_conditioning_improves_change_f1",
    "relative_edge_geometry_improves_change_f1",
    "multiscale_consistency_reduces_error",
    "multi_relation_improves_change_f1",
    "dynamic_topology_improves_change_f1",
)
VARIANT_NAMES = (
    "dam_gk_multirelational",
    "relative_edge_geometry",
    "no_multiscale_consistency",
    "region_conditioned",
    "single_relation",
    "frozen_topology",
    "target_only_mlp",
)


def summarize(paths: list[Path]) -> dict[str, Any]:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    geographic_splits = {_geographic_split(report) for report in reports}
    if len(geographic_splits) != 1:
        raise ValueError("all_runs_must_share_geographic_split")
    test_region_sets = {
        tuple(_test_region_ids(report)) for report in reports
    }
    if len(test_region_sets) != 1:
        raise ValueError("all_runs_must_share_test_regions")

    variant_summary = {}
    for variant_name in VARIANT_NAMES:
        change_f1 = [
            report["variant_metrics"][variant_name]["test"]["change_f1"]
            for report in reports
        ]
        variant_summary[variant_name] = {
            "change_f1_by_seed": dict(
                zip((str(report["seed"]) for report in reports), change_f1)
            ),
            "change_f1_mean": round(mean(change_f1), 8),
            "change_f1_population_std": round(pstdev(change_f1), 8),
        }

    check_summary = {}
    for check_name in CHECK_NAMES:
        outcomes = [
            bool(report["hypothesis_checks"][check_name]) for report in reports
        ]
        check_summary[check_name] = {
            "passed_seeds": sum(outcomes),
            "total_seeds": len(outcomes),
            "stable_across_all_seeds": all(outcomes),
        }

    return {
        "schema": "gwm.dam_gk.twm_multiseed_summary.v1",
        "geographic_split": _geographic_split(reports[0]),
        "seeds": [report["seed"] for report in reports],
        "training_region_count": len(_training_region_ids(reports[0])),
        "test_region_ids": _test_region_ids(reports[0]),
        "variant_summary": variant_summary,
        "hypothesis_stability": check_summary,
        "claim_boundary": {
            "statistical_baseline_advantage_supported": check_summary[
                "beats_strongest_statistical_baseline_change_f1"
            ]["stable_across_all_seeds"],
            "multi_relation_necessity_supported": check_summary[
                "multi_relation_improves_change_f1"
            ]["stable_across_all_seeds"],
            "region_conditioning_necessity_supported": check_summary[
                "region_conditioning_improves_change_f1"
            ]["stable_across_all_seeds"],
            "multiscale_consistency_supported": check_summary[
                "multiscale_consistency_reduces_error"
            ]["stable_across_all_seeds"],
            "dynamic_topology_necessity_supported": check_summary[
                "dynamic_topology_improves_change_f1"
            ]["stable_across_all_seeds"],
            "policy_effect_claim": False,
        },
    }


def _geographic_split(report: dict[str, Any]) -> str:
    return report.get("geographic_split", "same_regions_strict_future_year")


def _training_region_ids(report: dict[str, Any]) -> list[str]:
    return report.get("training_region_ids", report["region_ids"])


def _test_region_ids(report: dict[str, Any]) -> list[str]:
    return report.get("test_region_ids", report["region_ids"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
