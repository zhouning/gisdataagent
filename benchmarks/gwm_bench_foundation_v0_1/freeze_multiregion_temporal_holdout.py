#!/usr/bin/env python3
"""Seal the still-unscored 19-region 2024-2025 temporal holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import rasterio


BENCHMARK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_ROOT.parents[1]
DEVELOPMENT_ROOT = BENCHMARK_ROOT / "development"
SOURCE_ROOT = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world"
SOURCE_MANIFEST = SOURCE_ROOT / "twm_dynamic_world_manifest.json"
FOLLOWUP_MANIFEST = SOURCE_ROOT / "twm_dynamic_world_followup_2024_2025_manifest.json"
DOWNLOAD_STATUS = (
    REPO_ROOT
    / "docs/reports/twm_gee_dynamic_world_followup_2024_2025_download_status_2026-07-23.json"
)
DEFAULT_OUTPUT = DEVELOPMENT_ROOT / "multiregion_temporal_holdout/protocol.json"
EXCLUDED_REGION_ID = "上海市_浦东新区_祝桥镇"
PREDICTION_YEARS = (2021, 2022, 2023, 2024, 2025)
SCORED_YEARS = (2024, 2025)
MEMBER_RUNS = {
    31: DEVELOPMENT_ROOT / "twm_scenario_shared_calibration",
    47: DEVELOPMENT_ROOT / "twm_scenario_shared_calibration_seed_47",
    73: DEVELOPMENT_ROOT / "twm_scenario_shared_calibration_seed_73",
}
SHANGHAI_WEIGHT_ROOT = DEVELOPMENT_ROOT / "shanghai_temporal_holdout/twm"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(path: Path, *, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(REPO_ROOT.resolve())),
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _grid(path: Path) -> dict[str, Any]:
    """Read only raster metadata, not pixel values."""

    with rasterio.open(path) as dataset:
        return {
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "dtype": dataset.dtypes[0],
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "transform": list(dataset.transform)[:6],
            "nodata": dataset.nodata,
        }


def freeze_multiregion_temporal_holdout(
    *, output_path: Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    source = _load_json(SOURCE_MANIFEST)
    followup = _load_json(FOLLOWUP_MANIFEST)
    status = _load_json(DOWNLOAD_STATUS)
    if status["status"] != "pass" or int(status["downloaded_raster_count"]) != 40:
        raise ValueError("followup_download_is_not_complete")
    source_regions = {row["region_id"]: row for row in source["regions"]}
    followup_regions = {row["region_id"]: row for row in followup["regions"]}
    if set(source_regions) != set(followup_regions) or len(source_regions) != 20:
        raise ValueError("followup_region_set_mismatch")
    scored_regions = sorted(set(source_regions) - {EXCLUDED_REGION_ID})
    if len(scored_regions) != 19:
        raise ValueError("expected_exactly_19_unscored_regions")

    labels = []
    for region_id in scored_regions:
        region_root = SOURCE_ROOT / region_id
        origin_path = region_root / f"{region_id}_dynamic_world_2020_100m.tif"
        reference_grid = _grid(origin_path)
        followup_by_year = {
            int(row["year"]): SOURCE_ROOT / row["path"]
            for row in followup_regions[region_id]["raster_stack"]
        }
        paths = {
            2023: region_root / f"{region_id}_dynamic_world_2023_100m.tif",
            **followup_by_year,
        }
        if set(paths) != {2023, 2024, 2025}:
            raise ValueError(f"incomplete_temporal_label_stack:{region_id}")
        for year, path in sorted(paths.items()):
            grid = _grid(path)
            if grid != reference_grid:
                raise ValueError(f"temporal_label_grid_mismatch:{region_id}:{year}")
            labels.append(
                {
                    **_artifact(
                        path,
                        role=(
                            "known_2023_bridge_label"
                            if year == 2023
                            else "sealed_unscored_temporal_label"
                        ),
                    ),
                    "region_id": region_id,
                    "year": year,
                    "grid": grid,
                }
            )

    folds = _load_json(DEVELOPMENT_ROOT / "region_folds.json")["folds"]
    members = []
    for seed, run_root in MEMBER_RUNS.items():
        report_path = run_root / "twm_observed_run_report.json"
        report = _load_json(report_path)
        offsets = {}
        for fold in report["folds"]:
            values = fold["validation_calibration"][
                "selected_logit_offsets_by_horizon"
            ]
            if len(values) != 3 or len(set(values)) != 1:
                raise ValueError(f"non_shared_calibration:{seed}:{fold['fold_index']}")
            offsets[str(int(fold["fold_index"]))] = float(values[0])
        weight_path = SHANGHAI_WEIGHT_ROOT / f"seed_{seed}/model_state_dict.pt"
        members.append(
            {
                "seed": seed,
                "epochs": int(report["candidate"]["epochs"]),
                "shared_change_logit_offset_by_fold": offsets,
                "development_report": _artifact(
                    report_path, role="nominal_development_configuration"
                ),
                "preexisting_fold0_weights": _artifact(
                    weight_path, role="fold0_weights_fixed_before_shanghai_label_scoring"
                ),
            }
        )

    input_artifacts = [
        _artifact(SOURCE_MANIFEST, role="2017_2023_source_manifest"),
        _artifact(FOLLOWUP_MANIFEST, role="2024_2025_followup_manifest"),
        _artifact(DOWNLOAD_STATUS, role="followup_download_status"),
    ]
    for name in (
        "bundle_manifest.json",
        "region_folds.json",
        "observed_train.parquet",
        "observed_inputs.parquet",
        "observed_edges.parquet",
    ):
        input_artifacts.append(
            _artifact(DEVELOPMENT_ROOT / name, role="frozen_model_input")
        )
    for path in (
        Path(__file__).resolve(),
        BENCHMARK_ROOT / "run_twm_multiregion_temporal_holdout.py",
        BENCHMARK_ROOT / "score_multiregion_temporal_holdout.py",
        BENCHMARK_ROOT / "run_twm_observed_scenario.py",
        BENCHMARK_ROOT / "run_twm_shanghai_temporal_holdout.py",
        REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/model.py",
        REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/contracts.py",
        REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_transition_head.py",
        REPO_ROOT / "data_agent/uwm/dam_geospatial_kernel/twm_sequence_benchmark.py",
    ):
        input_artifacts.append(_artifact(path, role="frozen_prediction_code"))

    payload = {
        "schema": "gwm_bench.multiregion_temporal_holdout_protocol.v1",
        "protocol_id": "MULTIREGION-TEMPORAL-2024-2025-v1",
        "status": "sealed_before_19_region_label_scoring",
        "forecast_origin_year": 2020,
        "prediction_years": list(PREDICTION_YEARS),
        "scored_years": list(SCORED_YEARS),
        "scored_regions": scored_regions,
        "excluded_regions": [
            {
                "region_id": EXCLUDED_REGION_ID,
                "reason": "2024_2025_labels_already_scored_before_this_protocol",
            }
        ],
        "benchmark_role": (
            "19_region_unseen_region_and_future_time_extrapolation_stress_test"
        ),
        "model_selection_status": (
            "nominal_configuration_fixed_on_2021_2023_development_and_unchanged_after_shanghai_scoring"
        ),
        "twm_candidate": {
            "candidate_identity": "current_source_rerun_of_frozen_nominal_configuration",
            "training_years": [2017, 2018, 2019, 2020],
            "region_folds": folds,
            "state_writeback_mode": "categorical_mixture",
            "training_objective": "legacy_change_focal",
            "kernel_variant": "full",
            "ensemble_method": "arithmetic_mean_of_class_probabilities",
            "members": members,
            "continuation_rule": (
                "predict 2021-2023, write calibrated 2023 probabilities back, "
                "run a second three-step chunk, retain 2024-2025"
            ),
            "post_origin_observed_land_or_viirs": "none",
            "shanghai_score_used_for_configuration_or_training": False,
        },
        "metrics": {
            "primary": "unweighted_mean_of_38_region_year_change_f1_values",
            "secondary": [
                "overall_change_f1",
                "changed_destination_macro_f1",
                "overall_class_macro_f1",
                "multiclass_brier_score",
            ],
            "no_single_composite_score": True,
        },
        "input_artifacts": input_artifacts,
        "label_artifacts": labels,
        "seal_procedure": {
            "2024_2025_label_file_bytes_hashed": True,
            "label_grid_metadata_checked": True,
            "label_pixel_values_used_for_model_or_metric_selection": False,
            "prediction_hashes_must_be_committed_before_scoring": True,
        },
        "claim_boundary": {
            "external_hidden_test": False,
            "bounded_19_region_temporal_extrapolation": True,
            "independent_new_geography": False,
            "operational_forecasting": False,
            "general_twm_supported": False,
            "general_gwm_supported": False,
        },
    }
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "scored_region_count": len(scored_regions),
                "sealed_label_count": len(labels),
                "protocol": str(output_path),
                "protocol_sha256": _sha256(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    freeze_multiregion_temporal_holdout(output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
