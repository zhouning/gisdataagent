#!/usr/bin/env python3
"""Run a benchmark-compatible FLUS external baseline on OBSERVED-O1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.build_baselines_and_controls import (
    _transition_matrix,
)
from benchmarks.gwm_bench_foundation_v0_1.observed_evaluator import (
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    evaluate_observed_submission,
)


BENCHMARK_ROOT = Path(__file__).resolve().parent
DEFAULT_BUNDLE_ROOT = BENCHMARK_ROOT / "development"
DEFAULT_OUTPUT_ROOT = DEFAULT_BUNDLE_ROOT / "flus_external_baseline"
DEFAULT_FLUS_ROOT = Path("/Users/zhouning/FLUS_console_crossplatform")
TARGET_YEARS = (2021, 2022, 2023)
CLASS_COUNT = 9
SAMPLE_STRIDE = 24
FEATURE_NAMES = (
    "x_3857",
    "y_3857",
    "srtm_elevation",
    "srtm_slope",
    "viirs_nightlight_2020",
    "viirs_change_2019_2020",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _write_raster(path: Path, values: np.ndarray, *, nodata: float) -> None:
    values = np.asarray(values)
    if values.ndim == 2:
        values = values[None, :, :]
    if values.ndim != 3:
        raise ValueError("raster_values_must_be_two_or_three_dimensional")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[2],
        height=values.shape[1],
        count=values.shape[0],
        dtype=values.dtype,
        crs="EPSG:3857",
        transform=from_origin(0.0, float(values.shape[1]), 1.0, 1.0),
        nodata=nodata,
    ) as dataset:
        dataset.write(values)


def _feature_matrix(frame: pd.DataFrame) -> np.ndarray:
    """Build FLUS occurrence drivers using only information through 2020."""

    if "viirs_nightlight_2020" in frame:
        viirs_2020 = frame["viirs_nightlight_2020"].to_numpy(dtype=np.float32)
        viirs_2019 = frame["viirs_nightlight_2019"].to_numpy(dtype=np.float32)
    else:
        current = frame[frame["year"] == 2020].sort_values(
            ["region_id", "node_id"], kind="mergesort"
        )
        viirs_2020 = current["viirs_nightlight"].to_numpy(dtype=np.float32)
        viirs_2019 = current["viirs_nightlight_lag1"].to_numpy(dtype=np.float32)
        frame = current
    return np.column_stack(
        [
            frame["x_3857"].to_numpy(dtype=np.float32),
            frame["y_3857"].to_numpy(dtype=np.float32),
            frame["srtm_elevation"].to_numpy(dtype=np.float32),
            frame["srtm_slope"].to_numpy(dtype=np.float32),
            np.log1p(np.clip(viirs_2020, 0.0, None)),
            np.log1p(np.clip(viirs_2020, 0.0, None))
            - np.log1p(np.clip(viirs_2019, 0.0, None)),
        ]
    ).astype(np.float32)


def _run_process(
    command: list[str], *, cwd: Path, seed: int, log_path: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["FLUS_RANDOM_SEED"] = str(seed)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    log_path.write_text(
        "$ " + " ".join(command) + "\n\n" + completed.stdout + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode:
        raise RuntimeError(
            f"flus_process_failed:returncode={completed.returncode}:log={log_path}"
        )
    return completed


def _train_fold_suitability(
    *,
    fold_index: int,
    fold_train: pd.DataFrame,
    fold_test: pd.DataFrame,
    flus_binary: Path,
    work_root: Path,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    train_2020 = fold_train[fold_train["year"] == 2020].sort_values(
        ["region_id", "node_id"], kind="mergesort"
    )
    test = fold_test.sort_values(["region_id", "node_id"], kind="mergesort")
    if len(test) > len(train_2020):
        raise ValueError("flus_packed_test_must_not_exceed_training_size")
    train_features = _feature_matrix(train_2020)
    test_features = _feature_matrix(test)
    packed_size = len(train_2020)
    packed_test = np.full(
        (packed_size, len(FEATURE_NAMES)), 0.5, dtype=np.float32
    )
    packed_test[: len(test)] = test_features

    fold_root = work_root / f"fold_{fold_index}" / "suitability"
    (fold_root / "FilesGenerate").mkdir(parents=True, exist_ok=True)
    landuse_path = fold_root / "train_landuse.tif"
    probability_path = fold_root / "test_probability_packed.tif"
    _write_raster(
        landuse_path,
        (train_2020["land_class"].to_numpy(dtype=np.uint8) + 1)[None, :],
        nodata=0,
    )

    train_driver_paths = []
    test_driver_paths = []
    for feature_index, feature_name in enumerate(FEATURE_NAMES):
        train_path = fold_root / f"train_{feature_index}_{feature_name}.tif"
        test_path = fold_root / f"test_{feature_index}_{feature_name}.tif"
        _write_raster(train_path, train_features[:, feature_index][None, :], nodata=-1)
        _write_raster(test_path, packed_test[:, feature_index][None, :], nodata=-1)
        train_driver_paths.append(train_path)
        test_driver_paths.append(test_path)

    train_config = fold_root / "CCregiontrainlogCC.txt"
    train_config.write_text(
        "\n".join(
            [
                "[Path of land use data]",
                str(landuse_path),
                "[Path of saving data]",
                str(probability_path),
                "[Number of driving data]",
                str(len(train_driver_paths)),
                "[Path of driving data]",
                *[str(path) for path in train_driver_paths],
                "[Data type]",
                "Float",
                "[Normalization type]",
                "Normalization",
                "[Sample type]",
                "Proportional Sampling",
                "[Percentage of Random Points]",
                "1000",
                "[Hidden layer]",
                "8",
                "",
            ]
        ),
        encoding="utf-8",
    )
    update_csv = fold_root / "update_drivers.csv"
    update_csv.write_text(
        "".join(f"{index},{path}\n" for index, path in enumerate(test_driver_paths)),
        encoding="utf-8",
    )
    log_path = fold_root / "flus_ann.log"
    _run_process(
        [str(flus_binary), "train-update", str(train_config), str(update_csv)],
        cwd=fold_root,
        seed=seed + fold_index,
        log_path=log_path,
    )
    if not probability_path.exists():
        raise RuntimeError("flus_ann_did_not_create_probability_raster")
    with rasterio.open(probability_path) as dataset:
        packed_probability = dataset.read()[:, 0, : len(test)].T.astype(np.float64)
    if not np.isfinite(packed_probability).all():
        raise ValueError("flus_ann_probability_is_not_finite")
    probability = np.full((len(test), CLASS_COUNT), 1e-12, dtype=np.float64)
    probability[:, : packed_probability.shape[1]] = np.clip(
        packed_probability, 1e-12, None
    )
    probability /= probability.sum(axis=1, keepdims=True)
    indexed = test[["region_id", "node_id"]].copy()
    for class_index in range(CLASS_COUNT):
        indexed[f"probability_{class_index}"] = probability[:, class_index]
    return indexed, {
        "fold_index": fold_index,
        "training_node_count": int(len(train_2020)),
        "test_node_count": int(len(test)),
        "feature_names": list(FEATURE_NAMES),
        "training_maximum_year": 2020,
        "future_observed_inputs_used": False,
        "ann_class_count": int(packed_probability.shape[1]),
        "ann_log": str(log_path),
        "ann_probability_sha256": _sha256(probability_path),
    }


def _apportion_counts(expected: np.ndarray, total: int) -> np.ndarray:
    """Deterministically round counts while retaining every origin class."""

    expected = np.asarray(expected, dtype=np.float64)
    if expected.ndim != 1 or len(expected) == 0 or total < len(expected):
        raise ValueError("invalid_demand_apportionment")
    counts = np.maximum(np.floor(expected).astype(np.int64), 1)
    while int(counts.sum()) > total:
        candidates = np.flatnonzero(counts > 1)
        if not len(candidates):
            raise ValueError("cannot_reduce_apportioned_counts")
        excess = counts[candidates] - expected[candidates]
        counts[candidates[int(np.argmax(excess))]] -= 1
    while int(counts.sum()) < total:
        deficit = expected - counts
        counts[int(np.argmax(deficit))] += 1
    return counts


def _forecast_demands(
    origin_classes: np.ndarray, transition: np.ndarray
) -> tuple[list[int], dict[int, np.ndarray]]:
    active_classes = sorted(set(np.asarray(origin_classes, dtype=np.int64).tolist()))
    sub_transition = transition[np.ix_(active_classes, active_classes)].copy()
    sub_transition /= sub_transition.sum(axis=1, keepdims=True)
    state = np.bincount(
        np.searchsorted(active_classes, origin_classes), minlength=len(active_classes)
    ).astype(np.float64)
    total = len(origin_classes)
    demand_by_year = {}
    for target_year in TARGET_YEARS:
        state = state @ sub_transition
        demand_by_year[target_year] = _apportion_counts(state, total)
    return active_classes, demand_by_year


def _compact_region(
    frame: pd.DataFrame, active_classes: list[int]
) -> tuple[np.ndarray, np.ndarray, dict[str, tuple[int, int]]]:
    frame = frame.sort_values("node_id", kind="mergesort")
    row_min = int(frame["raster_row"].min())
    column_min = int(frame["raster_column"].min())
    rows = ((frame["raster_row"].to_numpy(dtype=np.int64) - row_min) // SAMPLE_STRIDE)
    columns = (
        (frame["raster_column"].to_numpy(dtype=np.int64) - column_min)
        // SAMPLE_STRIDE
    )
    shape = (int(rows.max()) + 1, int(columns.max()) + 1)
    landuse = np.zeros(shape, dtype=np.uint8)
    valid = np.zeros(shape, dtype=np.uint8)
    class_to_code = {class_index: index + 1 for index, class_index in enumerate(active_classes)}
    positions = {}
    for row, compact_row, compact_column in zip(
        frame.itertuples(index=False), rows, columns
    ):
        position = (int(compact_row), int(compact_column))
        if valid[position]:
            raise ValueError("duplicate_compact_grid_position")
        landuse[position] = class_to_code[int(row.land_class_2020)]
        valid[position] = 1
        positions[row.node_id] = position
    return landuse, valid, positions


def _simulate_region(
    *,
    fold_index: int,
    region_frame: pd.DataFrame,
    suitability: pd.DataFrame,
    transition: np.ndarray,
    flus_binary: Path,
    work_root: Path,
    seed: int,
    max_iterations: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    region_frame = region_frame.sort_values("node_id", kind="mergesort")
    region_id = str(region_frame["region_id"].iloc[0])
    origin = region_frame["land_class_2020"].to_numpy(dtype=np.int64)
    active_classes, demands = _forecast_demands(origin, transition)
    landuse, valid, positions = _compact_region(region_frame, active_classes)
    probability_columns = [f"probability_{index}" for index in active_classes]
    joined = region_frame[["node_id"]].merge(
        suitability[["node_id", *probability_columns]],
        on="node_id",
        validate="one_to_one",
        sort=False,
    )
    node_probability = joined[probability_columns].to_numpy(dtype=np.float64)
    node_probability = np.clip(node_probability, 1e-12, None)
    node_probability /= node_probability.sum(axis=1, keepdims=True)
    probability_grid = np.full(
        (len(active_classes), *landuse.shape), 1e-12, dtype=np.float32
    )
    for node_index, node_id in enumerate(joined["node_id"]):
        grid_position = positions[node_id]
        probability_grid[:, grid_position[0], grid_position[1]] = node_probability[
            node_index
        ]

    safe_region = hashlib.sha256(region_id.encode("utf-8")).hexdigest()[:12]
    region_root = work_root / f"fold_{fold_index}" / f"region_{safe_region}"
    region_root.mkdir(parents=True, exist_ok=True)
    probability_path = region_root / "probability.tif"
    restrict_path = region_root / "restrict.tif"
    _write_raster(probability_path, probability_grid, nodata=-1)
    _write_raster(restrict_path, valid, nodata=0)
    current_landuse_path = region_root / "landuse_2020.tif"
    _write_raster(current_landuse_path, landuse, nodata=0)

    code_to_class = {index + 1: value for index, value in enumerate(active_classes)}
    prediction_by_year = {}
    year_reports = []
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
            "year," + ",".join(f"type{index + 1}" for index in range(class_count))
            + "\n"
            + str(target_year)
            + ","
            + ",".join(str(int(value)) for value in demand)
            + "\n",
            encoding="utf-8",
        )
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
            raise RuntimeError("flus_simulation_did_not_create_result")
        with rasterio.open(result_path) as dataset:
            result = dataset.read(1)
        predicted = []
        for node_id in region_frame["node_id"]:
            code = int(result[positions[node_id]])
            if code not in code_to_class:
                raise ValueError("flus_result_contains_invalid_class_code")
            predicted.append(code_to_class[code])
        prediction_by_year[target_year] = np.asarray(predicted, dtype=np.int64)
        actual_counts = np.bincount(
            np.searchsorted(active_classes, prediction_by_year[target_year]),
            minlength=class_count,
        )
        year_reports.append(
            {
                "target_year": target_year,
                "requested_counts": demand.tolist(),
                "actual_counts": actual_counts.tolist(),
                "exact_demand_convergence": bool(np.array_equal(demand, actual_counts)),
                "result_path": str(result_path),
                "result_sha256": _sha256(result_path),
                "log_path": str(log_path),
            }
        )
        current_landuse_path = result_path

    rows = []
    for node_index, input_row in enumerate(region_frame.itertuples(index=False)):
        for target_year in TARGET_YEARS:
            predicted_class = int(prediction_by_year[target_year][node_index])
            probability = np.zeros(CLASS_COUNT, dtype=np.float64)
            probability[predicted_class] = 1.0
            row = {
                "fold_index": fold_index,
                "region_id": region_id,
                "node_id": input_row.node_id,
                "target_year": target_year,
            }
            row.update(
                {
                    column: float(probability[class_index])
                    for class_index, column in enumerate(PROBABILITY_COLUMNS)
                }
            )
            rows.append(row)
    return rows, {
        "region_id": region_id,
        "node_count": int(len(region_frame)),
        "compact_grid_shape": list(landuse.shape),
        "active_original_classes": active_classes,
        "absent_origin_classes_not_seeded": sorted(
            set(range(CLASS_COUNT)) - set(active_classes)
        ),
        "year_runs": year_reports,
    }


def run_flus_observed_baseline(
    *,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    flus_root: Path = DEFAULT_FLUS_ROOT,
    seed: int = 31,
    max_iterations: int = 2000,
    evaluate: bool = True,
) -> dict[str, Any]:
    if max_iterations <= 1:
        raise ValueError("max_iterations_must_exceed_one")
    bundle_root = bundle_root.resolve()
    output_root = output_root.resolve()
    flus_root = flus_root.resolve()
    binary_candidates = [
        flus_root / "build/cmake-release/flus_console",
        flus_root / "build/flus_console",
    ]
    flus_binary = next((path for path in binary_candidates if path.is_file()), binary_candidates[0])
    if not flus_binary.is_file() or not os.access(flus_binary, os.X_OK):
        raise FileNotFoundError(f"flus_binary_not_executable:{flus_binary}")
    folds = json.loads(
        (bundle_root / "region_folds.json").read_text(encoding="utf-8")
    )["folds"]
    train = pd.read_parquet(bundle_root / "observed_train.parquet")
    inputs = pd.read_parquet(bundle_root / "observed_inputs.parquet")
    work_root = output_root / "work"
    rows = []
    fold_reports = []
    for fold in folds:
        fold_index = int(fold["fold_index"])
        fold_train = train[train["fold_index"] == fold_index]
        fold_test = inputs[
            (inputs["fold_index"] == fold_index) & (inputs["split"] == "test")
        ]
        if set(fold_train["region_id"]) != set(fold["training_regions"]):
            raise ValueError("flus_training_regions_do_not_match_frozen_fold")
        if set(fold_test["region_id"]) != set(fold["test_regions"]):
            raise ValueError("flus_test_regions_do_not_match_frozen_fold")
        suitability, suitability_report = _train_fold_suitability(
            fold_index=fold_index,
            fold_train=fold_train,
            fold_test=fold_test,
            flus_binary=flus_binary,
            work_root=work_root,
            seed=seed,
        )
        transition = _transition_matrix(train, fold_index)
        region_reports = []
        for region_id, region_frame in fold_test.groupby("region_id", sort=True):
            region_suitability = suitability[suitability["region_id"] == region_id]
            region_rows, region_report = _simulate_region(
                fold_index=fold_index,
                region_frame=region_frame,
                suitability=region_suitability,
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
    if submission.duplicated(KEY_COLUMNS).any():
        raise ValueError("duplicate_flus_submission_keys")
    expected_rows = int((inputs["split"] == "test").sum()) * len(TARGET_YEARS)
    if len(submission) != expected_rows:
        raise ValueError("flus_submission_row_count_mismatch")
    probability = submission[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(probability).all() or not np.allclose(
        probability.sum(axis=1), 1.0, atol=1e-12, rtol=0.0
    ):
        raise ValueError("invalid_flus_submission_probability")
    submission = submission.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(
        drop=True
    )
    submission_path = output_root / "flus_observed_submission.parquet"
    submission_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = submission_path.with_suffix(".parquet.tmp")
    submission.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(submission_path)
    committed_sha256 = _sha256(submission_path)

    evaluation = None
    evaluation_path = output_root / "flus_observed_evaluation.json"
    if evaluate:
        evaluation = evaluate_observed_submission(
            submission_path=submission_path,
            labels_path=bundle_root / "observed_labels.parquet",
        )
        _write_json(evaluation, evaluation_path)
    exact_runs = [
        year_run["exact_demand_convergence"]
        for fold_report in fold_reports
        for region_report in fold_report["regions"]
        for year_run in region_report["year_runs"]
    ]
    report = {
        "schema": "gwm_bench.flus_observed_run.v1",
        "benchmark_id": "gwm-bench-foundation-v0.1",
        "track_id": "OBSERVED-O1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "flus_external_baseline_completed",
        "method": {
            "name": "FLUS ANN suitability plus FLUS cellular allocation",
            "upstream_model": "GeoSOS FLUS console",
            "citation": (
                "Liu et al. (2017), Landscape and Urban Planning 168:94-116, "
                "doi:10.1016/j.landurbplan.2017.09.019"
            ),
            "license_boundary": "non-commercial academic research",
            "external_source_root": str(flus_root),
            "binary_path": str(flus_binary),
            "binary_sha256": _sha256(flus_binary),
            "seed": seed,
            "max_iterations_per_region_year": max_iterations,
        },
        "protocol": {
            "fit_regions_per_fold": 12,
            "test_regions_per_fold": 4,
            "maximum_observed_input_year": 2020,
            "future_observed_inputs_used": False,
            "validation_labels_used": False,
            "test_labels_loaded_before_submission_commit": False,
            "land_demand": (
                "fold-training add-one transition matrix recursively applied to "
                "each test region's 2020 counts"
            ),
            "new_class_policy": (
                "classes absent from a region at the 2020 origin are not seeded; "
                "demand is renormalized over origin-present classes"
            ),
            "submission_probability_adapter": (
                "one-hot encoding of FLUS deterministic categorical output"
            ),
            "sampled_grid_caveat": (
                "FLUS runs on the benchmark's compact representation of 24-pixel-"
                "stride sampled nodes, not on full-resolution city rasters"
            ),
        },
        "convergence": {
            "region_year_run_count": len(exact_runs),
            "exact_demand_run_count": int(sum(exact_runs)),
            "all_region_year_runs_exact": bool(all(exact_runs)),
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
            "canonical_full_resolution_flus_run": False,
            "published_sota_comparison_supported": False,
            "causal_policy_effect_supported": False,
            "general_gwm_supported": False,
            "external_flus_core_baseline_supported": True,
        },
    }
    _write_json(report, output_root / "flus_observed_run_report.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--flus-root", type=Path, default=DEFAULT_FLUS_ROOT)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--max-iterations", type=int, default=2000)
    parser.add_argument("--no-evaluate", action="store_true")
    args = parser.parse_args()
    report = run_flus_observed_baseline(
        bundle_root=args.bundle_root,
        output_root=args.output_root,
        flus_root=args.flus_root,
        seed=args.seed,
        max_iterations=args.max_iterations,
        evaluate=not args.no_evaluate,
    )
    summary = {
        "status": report["status"],
        "convergence": report["convergence"],
        "primary_metric": (
            report["evaluation"]["primary_metric"]
            if report["evaluation"] is not None
            else None
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
