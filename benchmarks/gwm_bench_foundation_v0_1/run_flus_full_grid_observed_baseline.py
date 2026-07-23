#!/usr/bin/env python3
"""Run FLUS on full 100 m rasters, then score the frozen OBSERVED-O1 nodes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    evaluate_observed_submission,
)
from benchmarks.gwm_bench_foundation_v0_1.run_flus_observed_baseline import (
    CLASS_COUNT,
    DEFAULT_FLUS_ROOT,
    FEATURE_NAMES,
    TARGET_YEARS,
    _forecast_demands,
    _run_process,
    _sha256,
    _write_json,
    _write_raster,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEFAULT_BUNDLE_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_SOURCE_ROOT = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world"
DEFAULT_OUTPUT_ROOT = DEFAULT_BUNDLE_ROOT / "flus_full_grid_external_baseline"
CONTRACT_PATH = BENCHMARK_ROOT / "benchmark_contract.json"


@dataclass(frozen=True)
class FullGridRegion:
    region_id: str
    land_by_year: dict[int, np.ndarray]
    viirs_by_year: dict[int, np.ndarray]
    elevation: np.ndarray
    slope: np.ndarray
    valid_input: np.ndarray
    transform: Any
    crs: Any
    source_lineage: tuple[dict[str, Any], ...]

    @property
    def valid_flat_indices(self) -> np.ndarray:
        return np.flatnonzero(self.valid_input.ravel())

    @property
    def valid_cell_count(self) -> int:
        return int(self.valid_input.sum())


def _valid_class(values: np.ndarray, nodata: float | None) -> np.ndarray:
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata
    valid &= values == np.floor(values)
    valid &= (values >= 0) & (values < CLASS_COUNT)
    return valid


def _valid_continuous(values: np.ndarray, nodata: float | None) -> np.ndarray:
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata
    return valid


def _read_region_input(source_root: Path, region_id: str) -> FullGridRegion:
    """Read only pre-origin inputs; future label paths are never constructed."""

    region_root = source_root / region_id
    reference = None
    lineage = []

    def read(path: Path) -> tuple[np.ndarray, float | None]:
        nonlocal reference
        with rasterio.open(path) as dataset:
            if dataset.count != 1 or dataset.crs is None:
                raise ValueError(f"invalid_full_grid_input:{path}")
            current = (dataset.shape, dataset.transform, dataset.crs)
            if reference is None:
                reference = current
            elif current != reference:
                raise ValueError(f"full_grid_input_alignment_mismatch:{path}")
            values = dataset.read(1)
            nodata = dataset.nodata
        lineage.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "sha256": _sha256(path),
                "role": "observed_input",
            }
        )
        return values, nodata

    land = {}
    land_valid = []
    for year in range(2017, 2021):
        path = region_root / f"{region_id}_dynamic_world_{year}_100m.tif"
        values, nodata = read(path)
        land[year] = values.astype(np.int16, copy=False)
        land_valid.append(_valid_class(values, nodata))
    viirs = {}
    viirs_valid = []
    for year in range(2016, 2021):
        path = region_root / f"{region_id}_viirs_nightlight_{year}_100m.tif"
        values, nodata = read(path)
        viirs[year] = values.astype(np.float32, copy=False)
        viirs_valid.append(_valid_continuous(values, nodata))
    terrain = {}
    terrain_valid = []
    for layer in ("srtm_elevation", "srtm_slope"):
        path = region_root / f"{region_id}_{layer}_100m.tif"
        values, nodata = read(path)
        terrain[layer] = values.astype(np.float32, copy=False)
        terrain_valid.append(_valid_continuous(values, nodata))
    assert reference is not None
    valid_input = np.logical_and.reduce([*land_valid, *viirs_valid, *terrain_valid])
    if not valid_input.any():
        raise ValueError(f"full_grid_region_has_no_valid_input:{region_id}")
    return FullGridRegion(
        region_id=region_id,
        land_by_year=land,
        viirs_by_year=viirs,
        elevation=terrain["srtm_elevation"],
        slope=terrain["srtm_slope"],
        valid_input=valid_input,
        transform=reference[1],
        crs=reference[2],
        source_lineage=tuple(lineage),
    )


def _region_features(region: FullGridRegion) -> np.ndarray:
    rows, columns = np.nonzero(region.valid_input)
    x = (
        region.transform.a * (columns + 0.5)
        + region.transform.b * (rows + 0.5)
        + region.transform.c
    )
    y = (
        region.transform.d * (columns + 0.5)
        + region.transform.e * (rows + 0.5)
        + region.transform.f
    )
    viirs_2020 = np.log1p(np.clip(region.viirs_by_year[2020][rows, columns], 0, None))
    viirs_2019 = np.log1p(np.clip(region.viirs_by_year[2019][rows, columns], 0, None))
    return np.column_stack(
        [
            x,
            y,
            region.elevation[rows, columns],
            region.slope[rows, columns],
            viirs_2020,
            viirs_2020 - viirs_2019,
        ]
    ).astype(np.float32)


def _full_transition_matrix(regions: list[FullGridRegion]) -> np.ndarray:
    counts = np.ones((CLASS_COUNT, CLASS_COUNT), dtype=np.float64)
    for region in regions:
        valid = region.valid_input
        for source_year, target_year in zip(range(2017, 2020), range(2018, 2021)):
            source = region.land_by_year[source_year][valid].astype(np.int64)
            target = region.land_by_year[target_year][valid].astype(np.int64)
            np.add.at(counts, (source, target), 1.0)
    return counts / counts.sum(axis=1, keepdims=True)


def _write_like(
    path: Path,
    values: np.ndarray,
    *,
    region: FullGridRegion,
    nodata: float,
) -> None:
    values = np.asarray(values)
    if values.ndim == 2:
        values = values[None, :, :]
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[2],
        height=values.shape[1],
        count=values.shape[0],
        dtype=values.dtype,
        crs=region.crs,
        transform=region.transform,
        nodata=nodata,
        compress="deflate",
    ) as dataset:
        dataset.write(values)


def _train_full_grid_suitability(
    *,
    fold_index: int,
    training_regions: list[FullGridRegion],
    test_regions: list[FullGridRegion],
    flus_binary: Path,
    work_root: Path,
    seed: int,
    sample_per_mille: float,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    train_features = np.concatenate(
        [_region_features(region) for region in training_regions], axis=0
    )
    train_labels = np.concatenate(
        [
            region.land_by_year[2020][region.valid_input].astype(np.uint8) + 1
            for region in training_regions
        ]
    )
    test_features_by_region = {
        region.region_id: _region_features(region) for region in test_regions
    }
    test_features = np.concatenate(list(test_features_by_region.values()), axis=0)
    if len(test_features) > len(train_features):
        raise ValueError("full_grid_test_pixels_exceed_training_pixels")
    packed_test = np.full_like(train_features, 0.5, dtype=np.float32)
    packed_test[: len(test_features)] = test_features

    fold_root = work_root / f"fold_{fold_index}" / "suitability"
    (fold_root / "FilesGenerate").mkdir(parents=True, exist_ok=True)
    landuse_path = fold_root / "train_landuse_packed.tif"
    probability_path = fold_root / "test_probability_packed.tif"
    _write_raster(landuse_path, train_labels[None, :], nodata=0)
    train_paths = []
    test_paths = []
    for feature_index, feature_name in enumerate(FEATURE_NAMES):
        train_path = fold_root / f"train_{feature_index}_{feature_name}.tif"
        test_path = fold_root / f"test_{feature_index}_{feature_name}.tif"
        _write_raster(train_path, train_features[:, feature_index][None, :], nodata=-1)
        _write_raster(test_path, packed_test[:, feature_index][None, :], nodata=-1)
        train_paths.append(train_path)
        test_paths.append(test_path)
    config_path = fold_root / "CCregiontrainlogCC.txt"
    config_path.write_text(
        "\n".join(
            [
                "[Path of land use data]",
                str(landuse_path),
                "[Path of saving data]",
                str(probability_path),
                "[Number of driving data]",
                str(len(train_paths)),
                "[Path of driving data]",
                *[str(path) for path in train_paths],
                "[Data type]",
                "Float",
                "[Normalization type]",
                "Normalization",
                "[Sample type]",
                "Proportional Sampling",
                "[Percentage of Random Points]",
                str(sample_per_mille),
                "[Hidden layer]",
                "8",
                "",
            ]
        ),
        encoding="utf-8",
    )
    update_path = fold_root / "update_drivers.csv"
    update_path.write_text(
        "".join(f"{index},{path}\n" for index, path in enumerate(test_paths)),
        encoding="utf-8",
    )
    started = time.monotonic()
    log_path = fold_root / "flus_ann.log"
    _run_process(
        [str(flus_binary), "train-update", str(config_path), str(update_path)],
        cwd=fold_root,
        seed=seed + fold_index,
        log_path=log_path,
    )
    if not probability_path.exists():
        raise RuntimeError("full_grid_flus_ann_did_not_create_probability")
    with rasterio.open(probability_path) as dataset:
        packed_probability = dataset.read()[:, 0, : len(test_features)].T.astype(
            np.float64
        )
    probability = np.full((len(test_features), CLASS_COUNT), 1e-12, dtype=np.float64)
    probability[:, : packed_probability.shape[1]] = np.clip(
        packed_probability, 1e-12, None
    )
    probability /= probability.sum(axis=1, keepdims=True)
    by_region = {}
    offset = 0
    for region in test_regions:
        count = region.valid_cell_count
        by_region[region.region_id] = probability[offset : offset + count]
        offset += count
    if offset != len(test_features):
        raise AssertionError("full_grid_probability_partition_mismatch")
    return by_region, {
        "fold_index": fold_index,
        "training_valid_cell_count": int(len(train_features)),
        "test_valid_cell_count": int(len(test_features)),
        "training_sample_per_mille": sample_per_mille,
        "expected_training_sample_count": int(
            len(train_features) * sample_per_mille * 0.001
        ),
        "ann_class_count": int(packed_probability.shape[1]),
        "feature_names": list(FEATURE_NAMES),
        "elapsed_seconds": time.monotonic() - started,
        "probability_sha256": _sha256(probability_path),
        "log_path": str(log_path),
    }


def _simulate_full_grid_region(
    *,
    fold_index: int,
    region: FullGridRegion,
    sampled_inputs: pd.DataFrame,
    suitability: np.ndarray,
    transition: np.ndarray,
    flus_binary: Path,
    work_root: Path,
    seed: int,
    max_iterations: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    origin = region.land_by_year[2020][region.valid_input].astype(np.int64)
    active_classes, demands = _forecast_demands(origin, transition)
    class_to_code = {
        class_index: index + 1 for index, class_index in enumerate(active_classes)
    }
    code_to_class = {code: class_index for class_index, code in class_to_code.items()}
    landuse = np.zeros(region.valid_input.shape, dtype=np.uint8)
    for class_index, code in class_to_code.items():
        landuse[region.valid_input & (region.land_by_year[2020] == class_index)] = code
    restrict = region.valid_input.astype(np.uint8)
    active_probability = np.clip(suitability[:, active_classes], 1e-12, None)
    active_probability /= active_probability.sum(axis=1, keepdims=True)
    probability_grid = np.full(
        (len(active_classes), *region.valid_input.shape), -1.0, dtype=np.float32
    )
    for class_position in range(len(active_classes)):
        probability_grid[class_position][region.valid_input] = active_probability[
            :, class_position
        ]

    safe_region = hashlib.sha256(region.region_id.encode("utf-8")).hexdigest()[:12]
    region_root = work_root / f"fold_{fold_index}" / f"region_{safe_region}"
    region_root.mkdir(parents=True, exist_ok=True)
    landuse_path = region_root / "landuse_2020.tif"
    probability_path = region_root / "probability.tif"
    restrict_path = region_root / "restrict.tif"
    _write_like(landuse_path, landuse, region=region, nodata=0)
    _write_like(probability_path, probability_grid, region=region, nodata=-1)
    _write_like(restrict_path, restrict, region=region, nodata=0)

    sampled_inputs = sampled_inputs.sort_values("node_id", kind="mergesort")
    prediction_by_year = {}
    year_reports = []
    current_landuse_path = landuse_path
    for target_year in TARGET_YEARS:
        output_base = region_root / f"simresult_{target_year}.tif"
        config_path = region_root / "CCregionsimlog.txt"
        demand_path = region_root / "CCregionMakovChain.csv"
        class_count = len(active_classes)
        demand = demands[target_year]
        config_path.write_text(
            "\n".join(
                [
                    "[Path of land use data]",
                    str(current_landuse_path),
                    "[Path of probability data]",
                    str(probability_path),
                    "[Path of simulation result]",
                    str(output_base),
                    "[Path of restricted area]",
                    str(restrict_path),
                    "[Number of types]",
                    str(class_count),
                    "[Future Pixels]",
                    *[str(int(value)) for value in demand],
                    "[Cost Matrix]",
                    *[",".join("1" for _ in range(class_count)) for _ in range(class_count)],
                    "[Intensity of neighborhood]",
                    *["1" for _ in range(class_count)],
                    "[Maximum Number Of Iterations]",
                    str(max_iterations),
                    "[Size of neighborhood]",
                    "3",
                    "[Accelerated factor]",
                    "0.1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        demand_path.write_text(
            "year," + ",".join(f"type{i + 1}" for i in range(class_count)) + "\n"
            + str(target_year)
            + ","
            + ",".join(str(int(value)) for value in demand)
            + "\n",
            encoding="utf-8",
        )
        started = time.monotonic()
        log_path = region_root / f"flus_simulation_{target_year}.log"
        _run_process(
            [str(flus_binary)],
            cwd=region_root,
            seed=seed + fold_index * 100 + target_year,
            log_path=log_path,
        )
        converged_path = output_base.with_name(
            f"{output_base.stem}_{target_year}{output_base.suffix}"
        )
        result_path = converged_path if converged_path.exists() else output_base
        if not result_path.exists():
            raise RuntimeError("full_grid_flus_did_not_create_result")
        with rasterio.open(result_path) as dataset:
            result = dataset.read(1)
        predicted = []
        for row in sampled_inputs.itertuples(index=False):
            code = int(result[int(row.raster_row), int(row.raster_column)])
            if code not in code_to_class:
                raise ValueError("invalid_full_grid_flus_class_at_sampled_node")
            predicted.append(code_to_class[code])
        prediction_by_year[target_year] = np.asarray(predicted, dtype=np.int64)
        full_codes = result[region.valid_input].astype(np.int64)
        actual_counts = np.bincount(full_codes, minlength=class_count + 1)[1:]
        demand_tvd = float(
            np.abs(demand.astype(np.float64) - actual_counts).sum()
            / (2.0 * demand.sum())
        )
        year_reports.append(
            {
                "target_year": target_year,
                "requested_counts": demand.tolist(),
                "actual_counts": actual_counts.tolist(),
                "exact_demand_convergence": bool(np.array_equal(demand, actual_counts)),
                "demand_total_variation_distance": demand_tvd,
                "elapsed_seconds": time.monotonic() - started,
                "result_path": str(result_path),
                "result_sha256": _sha256(result_path),
                "log_path": str(log_path),
            }
        )
        current_landuse_path = result_path

    rows = []
    for node_position, input_row in enumerate(sampled_inputs.itertuples(index=False)):
        for target_year in TARGET_YEARS:
            predicted_class = int(prediction_by_year[target_year][node_position])
            row = {
                "fold_index": fold_index,
                "region_id": region.region_id,
                "node_id": input_row.node_id,
                "target_year": target_year,
            }
            row.update(
                {
                    column: float(class_index == predicted_class)
                    for class_index, column in enumerate(PROBABILITY_COLUMNS)
                }
            )
            rows.append(row)
    return rows, {
        "region_id": region.region_id,
        "full_grid_shape": list(region.valid_input.shape),
        "full_valid_cell_count": region.valid_cell_count,
        "scored_sampled_node_count": int(len(sampled_inputs)),
        "active_original_classes": active_classes,
        "year_runs": year_reports,
    }


def run_flus_full_grid_observed_baseline(
    *,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    source_root: Path = DEFAULT_SOURCE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    flus_root: Path = DEFAULT_FLUS_ROOT,
    seed: int = 31,
    sample_per_mille: float = 10.0,
    max_iterations: int = 500,
    evaluate: bool = True,
) -> dict[str, Any]:
    if not 0 < sample_per_mille <= 1000:
        raise ValueError("sample_per_mille_must_be_in_zero_1000")
    if max_iterations <= 1:
        raise ValueError("max_iterations_must_exceed_one")
    bundle_root = bundle_root.resolve()
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    flus_root = flus_root.resolve()
    binary_candidates = [
        flus_root / "build/cmake-release/flus_console",
        flus_root / "build/flus_console",
    ]
    flus_binary = next((path for path in binary_candidates if path.is_file()), binary_candidates[0])
    if not flus_binary.is_file() or not os.access(flus_binary, os.X_OK):
        raise FileNotFoundError(f"flus_binary_not_executable:{flus_binary}")
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    folds = json.loads(
        (bundle_root / "region_folds.json").read_text(encoding="utf-8")
    )["folds"]
    inputs = pd.read_parquet(bundle_root / "observed_inputs.parquet")
    regions = {
        region_id: _read_region_input(source_root, region_id)
        for region_id in contract["observed_region_ids"]
    }
    work_root = output_root / "work"
    rows = []
    fold_reports = []
    for fold in folds:
        fold_index = int(fold["fold_index"])
        training_regions = [regions[value] for value in fold["training_regions"]]
        test_regions = [regions[value] for value in fold["test_regions"]]
        suitability, suitability_report = _train_full_grid_suitability(
            fold_index=fold_index,
            training_regions=training_regions,
            test_regions=test_regions,
            flus_binary=flus_binary,
            work_root=work_root,
            seed=seed,
            sample_per_mille=sample_per_mille,
        )
        transition = _full_transition_matrix(training_regions)
        region_reports = []
        fold_test = inputs[
            (inputs["fold_index"] == fold_index) & (inputs["split"] == "test")
        ]
        for region in test_regions:
            sampled = fold_test[fold_test["region_id"] == region.region_id]
            if sampled.empty:
                raise ValueError("full_grid_test_region_has_no_scored_nodes")
            for input_row in sampled.itertuples(index=False):
                if not region.valid_input[
                    int(input_row.raster_row), int(input_row.raster_column)
                ]:
                    raise ValueError("scored_node_is_not_full_grid_input_valid")
            region_rows, region_report = _simulate_full_grid_region(
                fold_index=fold_index,
                region=region,
                sampled_inputs=sampled,
                suitability=suitability[region.region_id],
                transition=transition,
                flus_binary=flus_binary,
                work_root=work_root,
                seed=seed,
                max_iterations=max_iterations,
            )
            rows.extend(region_rows)
            region_reports.append(region_report)
        fold_reports.append(
            {
                "fold_index": fold_index,
                "training_regions": fold["training_regions"],
                "validation_regions": fold["validation_regions"],
                "test_regions": fold["test_regions"],
                "validation_region_use": "reserved_not_used",
                "suitability": suitability_report,
                "regions": region_reports,
            }
        )

    submission = pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS)
    expected_rows = int((inputs["split"] == "test").sum()) * len(TARGET_YEARS)
    if len(submission) != expected_rows or submission.duplicated(KEY_COLUMNS).any():
        raise ValueError("invalid_full_grid_submission_keys")
    submission = submission.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(
        drop=True
    )
    submission_path = output_root / "flus_full_grid_observed_submission.parquet"
    submission_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = submission_path.with_suffix(".parquet.tmp")
    submission.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(submission_path)
    committed_sha256 = _sha256(submission_path)

    evaluation = None
    evaluation_path = output_root / "flus_full_grid_observed_evaluation.json"
    if evaluate:
        evaluation = evaluate_observed_submission(
            submission_path=submission_path,
            labels_path=bundle_root / "observed_labels.parquet",
        )
        _write_json(evaluation, evaluation_path)
    exact_runs = [
        year_run["exact_demand_convergence"]
        for fold in fold_reports
        for region in fold["regions"]
        for year_run in region["year_runs"]
    ]
    demand_distances = [
        year_run["demand_total_variation_distance"]
        for fold in fold_reports
        for region in fold["regions"]
        for year_run in region["year_runs"]
    ]
    demand_distance_by_year = {
        str(target_year): float(
            np.mean(
                [
                    year_run["demand_total_variation_distance"]
                    for fold in fold_reports
                    for region in fold["regions"]
                    for year_run in region["year_runs"]
                    if year_run["target_year"] == target_year
                ]
            )
        )
        for target_year in TARGET_YEARS
    }
    source_lineage = [
        row for region in regions.values() for row in region.source_lineage
    ]
    report = {
        "schema": "gwm_bench.flus_full_grid_observed_run.v1",
        "benchmark_id": "gwm-bench-foundation-v0.1",
        "track_id": "OBSERVED-O1-full-grid-external-baseline",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "flus_full_grid_external_baseline_completed",
        "method": {
            "name": "FLUS ANN suitability plus full-grid FLUS cellular allocation",
            "citation": (
                "Liu et al. (2017), Landscape and Urban Planning 168:94-116, "
                "doi:10.1016/j.landurbplan.2017.09.019"
            ),
            "license_boundary": "non-commercial academic research",
            "binary_path": str(flus_binary),
            "binary_sha256": _sha256(flus_binary),
            "seed": seed,
            "training_sample_per_mille": sample_per_mille,
            "max_iterations_per_region_year": max_iterations,
        },
        "protocol": {
            "allocation_grid": "complete aligned 100 m source raster",
            "evaluation_grid": "frozen 24-pixel-stride OBSERVED-O1 nodes",
            "maximum_observed_input_year": 2020,
            "future_source_paths_constructed_before_commit": False,
            "future_observed_inputs_used": False,
            "validation_labels_used": False,
            "test_labels_loaded_before_submission_commit": False,
            "land_demand": (
                "fold-training full-grid add-one transition matrix recursively "
                "applied to each test region's 2020 full-grid counts"
            ),
            "submission_probability_adapter": "one-hot FLUS categorical output",
        },
        "source_lineage": {
            "input_file_count": len(source_lineage),
            "maximum_year": 2020,
            "files": source_lineage,
        },
        "convergence": {
            "region_year_run_count": len(exact_runs),
            "exact_demand_run_count": int(sum(exact_runs)),
            "all_region_year_runs_exact": bool(all(exact_runs)),
            "mean_demand_total_variation_distance": float(
                np.mean(demand_distances)
            ),
            "median_demand_total_variation_distance": float(
                np.median(demand_distances)
            ),
            "maximum_demand_total_variation_distance": float(
                np.max(demand_distances)
            ),
            "mean_demand_total_variation_distance_by_year": (
                demand_distance_by_year
            ),
        },
        "folds": fold_reports,
        "artifacts": {
            "submission": {
                "path": str(submission_path),
                "row_count": int(len(submission)),
                "sha256": committed_sha256,
            },
            "evaluation": str(evaluation_path) if evaluation is not None else None,
        },
        "evaluation": evaluation,
        "claim_boundary": {
            "full_resolution_flus_allocation_supported": True,
            "external_flus_core_baseline_supported": True,
            "hidden_test_comparison_supported": False,
            "published_sota_comparison_supported": False,
            "general_gwm_supported": False,
        },
    }
    _write_json(report, output_root / "flus_full_grid_observed_run_report.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--flus-root", type=Path, default=DEFAULT_FLUS_ROOT)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--sample-per-mille", type=float, default=10.0)
    parser.add_argument("--max-iterations", type=int, default=500)
    parser.add_argument("--no-evaluate", action="store_true")
    args = parser.parse_args()
    report = run_flus_full_grid_observed_baseline(
        bundle_root=args.bundle_root,
        source_root=args.source_root,
        output_root=args.output_root,
        flus_root=args.flus_root,
        seed=args.seed,
        sample_per_mille=args.sample_per_mille,
        max_iterations=args.max_iterations,
        evaluate=not args.no_evaluate,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "convergence": report["convergence"],
                "primary_metric": (
                    report["evaluation"]["primary_metric"]
                    if report["evaluation"] is not None
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
