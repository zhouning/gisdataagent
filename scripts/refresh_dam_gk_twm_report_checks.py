#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def refresh(report: dict) -> dict:
    variants = report["variant_metrics"]
    full = variants["dam_gk_multirelational"]["test"]
    controls = variants["dam_gk_multirelational"].get(
        "geographic_negative_controls", {}
    )
    geometry = variants.get("relative_edge_geometry")
    geometry_test = geometry["test"] if geometry else full
    geometry_controls = geometry.get("geographic_negative_controls", {}) if geometry else {}
    baselines = report["baselines"]
    strongest_baseline = max(
        value["test"]["change_f1"]
        for name, value in baselines.items()
        if name != "persistence"
    )
    checks = report["hypothesis_checks"]
    checks.update(
        {
            "beats_strongest_statistical_baseline_change_f1": full["change_f1"]
            > strongest_baseline,
            "beats_target_only_mlp_change_f1": full["change_f1"]
            > variants["target_only_mlp"]["test"]["change_f1"],
            "region_conditioning_improves_change_f1": variants[
                "region_conditioned"
            ]["test"]["change_f1"]
            > full["change_f1"],
            "multi_relation_improves_change_f1": full["change_f1"]
            > variants["single_relation"]["test"]["change_f1"],
            "dynamic_topology_improves_change_f1": full["change_f1"]
            > variants["frozen_topology"]["test"]["change_f1"],
            "relation_shuffle_degrades_change_f1": controls.get(
                "relation_type_shuffle", full
            )["change_f1"]
            < full["change_f1"],
            "spatial_rewire_degrades_change_f1": controls.get(
                "edge_target_rewire", full
            )["change_f1"]
            < full["change_f1"],
            "coordinate_permutation_degrades_change_f1": controls.get(
                "coordinate_permutation", full
            )["change_f1"]
            < full["change_f1"],
            "edge_geometry_permutation_degrades_change_f1": geometry_controls.get(
                "edge_geometry_permutation", geometry_test
            )["change_f1"]
            < geometry_test["change_f1"],
            "relative_edge_geometry_improves_change_f1": geometry_test["change_f1"]
            > full["change_f1"],
        }
    )
    if "no_multiscale_consistency" in variants:
        checks["multiscale_consistency_reduces_error"] = full[
            "fine_coarse_consistency_mae"
        ] < variants["no_multiscale_consistency"]["test"][
            "fine_coarse_consistency_mae"
        ]
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.paths:
        report = refresh(json.loads(path.read_text(encoding="utf-8")))
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
