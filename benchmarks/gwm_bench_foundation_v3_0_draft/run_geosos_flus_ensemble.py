#!/usr/bin/env python3
"""Run the three-seed GeoSOS FLUS full-grid ensemble for GWM-Bench V3."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio

from prediction_runtime import (
    BUNDLE_MANIFEST_PATH,
    BUNDLE_ROOT,
    DRAFT_ROOT,
    KEY_COLUMNS,
    PROBABILITY_COLUMNS,
    PROTOCOL_PATH,
    REPO_ROOT,
    SUBMISSION_CONTRACT_PATH,
    artifact,
    enforce_label_firewall,
    fingerprint,
    load_json,
    load_prediction_contract,
    peak_memory_bytes,
    prediction_summary,
    runtime_environment,
    sha256_file,
    utc_now,
    validate_submission,
    write_json_atomic,
    write_parquet_atomic,
)


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.gwm_bench_foundation_v0_1.run_flus_full_grid_observed_baseline import (
    _valid_class,
    _valid_continuous,
    _write_like,
)
from benchmarks.gwm_bench_foundation_v0_1.run_flus_observed_baseline import (
    _apportion_counts,
    _run_process,
    _write_raster,
)


CLASS_COUNT = 9
HISTORY_YEARS = (2017, 2018, 2019, 2020, 2021, 2022)
TARGET_YEARS = (2023, 2024, 2025)
SEEDS = (31, 47, 73)
FEATURE_NAMES = (
    "x_3857",
    "y_3857",
    "srtm_elevation",
    "srtm_slope",
    "log1p_viirs_mean_2017_2022",
)
SAMPLE_PER_MILLE = 10.0
MAX_ITERATIONS = 500
FLUS_ROOT = Path("/Users/zhouning/FLUS_console_crossplatform")
DEFAULT_OUTPUT_ROOT = DRAFT_ROOT / "predictions/geosos_flus_three_seed_ensemble"
V0_FLUS_SOURCES = (
    REPO_ROOT
    / "benchmarks/gwm_bench_foundation_v0_1/run_flus_observed_baseline.py",
    REPO_ROOT
    / "benchmarks/gwm_bench_foundation_v0_1/run_flus_full_grid_observed_baseline.py",
    REPO_ROOT
    / "benchmarks/gwm_bench_foundation_v0_1/run_flus_full_grid_historical_backtest.py",
)


@dataclass(frozen=True)
class FullGridRegion:
    region_id: str
    land_by_year: dict[int, np.ndarray]
    elevation: np.ndarray
    slope: np.ndarray
    viirs_mean: np.ndarray
    valid_input: np.ndarray
    transform: Any
    crs: Any
    source_artifacts: tuple[dict[str, Any], ...]

    @property
    def valid_cell_count(self) -> int:
        return int(self.valid_input.sum())


def _external_artifact(path: Path, *, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "path_scope": "absolute_external_not_distributed",
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _flus_binary(flus_root: Path) -> Path:
    candidates = (
        flus_root / "build/cmake-release/flus_console",
        flus_root / "build/flus_console",
    )
    binary = next((path for path in candidates if path.is_file()), candidates[0])
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise FileNotFoundError(f"flus_binary_not_executable:{binary}")
    return binary.resolve()


def _read_region(
    *,
    root: Path,
    entry: dict[str, Any],
    source_role: str,
) -> FullGridRegion:
    region_id = entry["region_id"]
    reference = None
    artifacts = []

    def read(path: Path, *, role: str) -> tuple[np.ndarray, float | None]:
        nonlocal reference
        with rasterio.open(path) as dataset:
            if dataset.count != 1 or dataset.crs is None:
                raise ValueError(f"invalid_flus_full_grid_input:{path}")
            current = (dataset.shape, dataset.transform, dataset.crs)
            if reference is None:
                reference = current
            elif current != reference:
                raise ValueError(f"flus_full_grid_alignment_mismatch:{path}")
            values = dataset.read(1)
            nodata = dataset.nodata
        artifacts.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "role": role,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
        return values, nodata

    raster_by_year = {
        int(row["year"]): row for row in entry["raster_stack"]
    }
    if any(year not in raster_by_year for year in HISTORY_YEARS):
        raise ValueError(f"flus_region_missing_2017_2022:{region_id}")
    land = {}
    valid_masks = []
    for year in HISTORY_YEARS:
        path = root / raster_by_year[year]["path"]
        values, nodata = read(path, role=f"{source_role}_land_state_{year}")
        land[year] = values.astype(np.int16, copy=False)
        valid_masks.append(_valid_class(values, nodata))

    driver_by_name = {row["name"]: row for row in entry["driver_layers"]}
    required_drivers = ("srtm_elevation", "srtm_slope", "viirs_nightlight_mean")
    if any(name not in driver_by_name for name in required_drivers):
        raise ValueError(f"flus_region_missing_driver:{region_id}")
    drivers = {}
    for name in required_drivers:
        path = root / driver_by_name[name]["path"]
        values, nodata = read(path, role=f"{source_role}_{name}")
        drivers[name] = values.astype(np.float32, copy=False)
        valid_masks.append(_valid_continuous(values, nodata))
    assert reference is not None
    valid_input = np.logical_and.reduce(valid_masks)
    if not valid_input.any():
        raise ValueError(f"flus_region_has_no_complete_input:{region_id}")
    return FullGridRegion(
        region_id=region_id,
        land_by_year=land,
        elevation=drivers["srtm_elevation"],
        slope=drivers["srtm_slope"],
        viirs_mean=drivers["viirs_nightlight_mean"],
        valid_input=valid_input,
        transform=reference[1],
        crs=reference[2],
        source_artifacts=tuple(artifacts),
    )


def _load_regions(
    *, root: Path, manifest_path: Path, source_role: str
) -> list[FullGridRegion]:
    manifest = load_json(manifest_path)
    if len(manifest["regions"]) != 20:
        raise ValueError(f"{source_role}_manifest_must_have_20_regions")
    return [
        _read_region(root=root, entry=entry, source_role=source_role)
        for entry in sorted(manifest["regions"], key=lambda row: row["region_id"])
    ]


def _features(region: FullGridRegion) -> np.ndarray:
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
    viirs = np.log1p(np.clip(region.viirs_mean[rows, columns], 0.0, None))
    return np.column_stack(
        [
            x,
            y,
            region.elevation[rows, columns],
            region.slope[rows, columns],
            viirs,
        ]
    ).astype(np.float32)


def _transition_matrix(regions: list[FullGridRegion]) -> tuple[np.ndarray, np.ndarray]:
    counts = np.ones((CLASS_COUNT, CLASS_COUNT), dtype=np.float64)
    for region in regions:
        valid = region.valid_input
        for source_year, target_year in zip(
            HISTORY_YEARS[:-1], HISTORY_YEARS[1:]
        ):
            source = region.land_by_year[source_year][valid].astype(np.int64)
            target = region.land_by_year[target_year][valid].astype(np.int64)
            np.add.at(counts, (source, target), 1.0)
    return counts, counts / counts.sum(axis=1, keepdims=True)


def _train_suitability(
    *,
    seed: int,
    training_regions: list[FullGridRegion],
    target_regions: list[FullGridRegion],
    flus_binary: Path,
    work_root: Path,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    started = time.perf_counter()
    train_features = np.concatenate([_features(region) for region in training_regions])
    train_labels = np.concatenate(
        [
            region.land_by_year[2022][region.valid_input].astype(np.uint8) + 1
            for region in training_regions
        ]
    )
    target_features_by_region = {
        region.region_id: _features(region) for region in target_regions
    }
    target_features = np.concatenate(list(target_features_by_region.values()))
    if len(train_features) == 0 or len(target_features) == 0:
        raise ValueError("flus_ann_requires_nonempty_train_and_target_pixels")

    ann_root = work_root / "ann"
    ann_root.mkdir(parents=True, exist_ok=True)
    landuse_path = ann_root / "train_landuse.tif"
    _write_raster(landuse_path, train_labels[None, :], nodata=0)
    train_paths = []
    for feature_index, feature_name in enumerate(FEATURE_NAMES):
        path = ann_root / f"train_{feature_index}_{feature_name}.tif"
        _write_raster(path, train_features[:, feature_index][None, :], nodata=-1)
        train_paths.append(path)

    probability_chunks = []
    chunk_reports = []
    chunk_size = len(train_features)
    for chunk_index, offset in enumerate(range(0, len(target_features), chunk_size)):
        chunk = target_features[offset : offset + chunk_size]
        chunk_root = ann_root / f"chunk_{chunk_index}"
        (chunk_root / "FilesGenerate").mkdir(parents=True, exist_ok=True)
        packed = np.full_like(train_features, 0.5, dtype=np.float32)
        packed[: len(chunk)] = chunk
        test_paths = []
        for feature_index, feature_name in enumerate(FEATURE_NAMES):
            path = chunk_root / f"target_{feature_index}_{feature_name}.tif"
            _write_raster(path, packed[:, feature_index][None, :], nodata=-1)
            test_paths.append(path)
        probability_path = chunk_root / "target_probability.tif"
        config_path = chunk_root / "CCregiontrainlogCC.txt"
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
                    str(SAMPLE_PER_MILLE),
                    "[Hidden layer]",
                    "8",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        update_path = chunk_root / "update_drivers.csv"
        update_path.write_text(
            "".join(
                f"{index},{path}\n" for index, path in enumerate(test_paths)
            ),
            encoding="utf-8",
        )
        log_path = chunk_root / "flus_ann.log"
        chunk_started = time.perf_counter()
        _run_process(
            [str(flus_binary), "train-update", str(config_path), str(update_path)],
            cwd=chunk_root,
            seed=seed,
            log_path=log_path,
        )
        if not probability_path.is_file():
            raise RuntimeError("v3_flus_ann_probability_missing")
        with rasterio.open(probability_path) as dataset:
            raw = dataset.read()[:, 0, : len(chunk)].T.astype(np.float64)
        probability = np.full((len(chunk), CLASS_COUNT), 1e-12, dtype=np.float64)
        probability[:, : raw.shape[1]] = np.clip(raw, 1e-12, None)
        probability /= probability.sum(axis=1, keepdims=True)
        probability_chunks.append(probability)
        chunk_reports.append(
            {
                "chunk_index": chunk_index,
                "target_pixel_count": len(chunk),
                "derived_process_seed": seed,
                "probability_sha256": sha256_file(probability_path),
                "elapsed_seconds": time.perf_counter() - chunk_started,
            }
        )
    target_probability = np.concatenate(probability_chunks)
    by_region = {}
    offset = 0
    for region in target_regions:
        count = region.valid_cell_count
        by_region[region.region_id] = target_probability[offset : offset + count]
        offset += count
    if offset != len(target_probability):
        raise AssertionError("v3_flus_probability_partition_mismatch")
    return by_region, {
        "base_seed": seed,
        "training_valid_cell_count": len(train_features),
        "target_valid_cell_count": len(target_features),
        "training_sample_per_mille": SAMPLE_PER_MILLE,
        "expected_training_sample_count": int(
            len(train_features) * SAMPLE_PER_MILLE * 0.001
        ),
        "feature_names": list(FEATURE_NAMES),
        "training_label_year": 2022,
        "target_label_pixels_read": False,
        "chunk_count": len(chunk_reports),
        "chunks": chunk_reports,
        "elapsed_seconds": time.perf_counter() - started,
    }


def _derived_simulation_seed(base_seed: int, region_index: int, year: int) -> int:
    return base_seed * 100000 + region_index * 100 + (year - 2000)


def _simulate_region(
    *,
    seed: int,
    region_index: int,
    region: FullGridRegion,
    sampled_inputs: pd.DataFrame,
    suitability: np.ndarray,
    transition: np.ndarray,
    flus_binary: Path,
    work_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sampled_inputs = sampled_inputs.sort_values("node_id", kind="mergesort")
    for row in sampled_inputs.itertuples(index=False):
        if not region.valid_input[int(row.raster_row), int(row.raster_column)]:
            raise ValueError(f"flus_sampled_node_not_input_valid:{region.region_id}")

    origin = region.land_by_year[2022][region.valid_input].astype(np.int64)
    active_classes = sorted(set(origin.tolist()))
    active_transition = transition[np.ix_(active_classes, active_classes)].copy()
    active_transition /= active_transition.sum(axis=1, keepdims=True)
    class_to_code = {
        class_index: position + 1
        for position, class_index in enumerate(active_classes)
    }
    code_to_class = {code: cls for cls, code in class_to_code.items()}
    active_probability = np.clip(suitability[:, active_classes], 1e-12, None)
    active_probability /= active_probability.sum(axis=1, keepdims=True)
    probability_grid = np.full(
        (len(active_classes), *region.valid_input.shape), -1.0, dtype=np.float32
    )
    for position in range(len(active_classes)):
        probability_grid[position][region.valid_input] = active_probability[:, position]
    restrict = region.valid_input.astype(np.uint8)

    safe_region = hashlib.sha256(region.region_id.encode("utf-8")).hexdigest()[:12]
    region_root = work_root / f"region_{region_index:02d}_{safe_region}"
    region_root.mkdir(parents=True, exist_ok=True)
    probability_path = region_root / "probability.tif"
    restrict_path = region_root / "restrict.tif"
    _write_like(probability_path, probability_grid, region=region, nodata=-1)
    _write_like(restrict_path, restrict, region=region, nodata=0)

    current_classes = origin.copy()
    prediction_by_year = {}
    year_reports = []
    for target_year in TARGET_YEARS:
        current_positions = np.searchsorted(active_classes, current_classes)
        current_counts = np.bincount(
            current_positions, minlength=len(active_classes)
        ).astype(np.float64)
        demand = _apportion_counts(
            current_counts @ active_transition, len(current_classes)
        )
        landuse = np.zeros(region.valid_input.shape, dtype=np.uint8)
        encoded_current = np.array(
            [class_to_code[int(value)] for value in current_classes], dtype=np.uint8
        )
        landuse[region.valid_input] = encoded_current
        landuse_path = region_root / f"landuse_{target_year - 1}.tif"
        _write_like(landuse_path, landuse, region=region, nodata=0)

        output_base = region_root / f"simresult_{target_year}.tif"
        config_path = region_root / "CCregionsimlog.txt"
        demand_path = region_root / "CCregionMakovChain.csv"
        class_count = len(active_classes)
        config_path.write_text(
            "\n".join(
                [
                    "[Path of land use data]",
                    str(landuse_path),
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
                    *[
                        ",".join("1" for _ in range(class_count))
                        for _ in range(class_count)
                    ],
                    "[Intensity of neighborhood]",
                    *["1" for _ in range(class_count)],
                    "[Maximum Number Of Iterations]",
                    str(MAX_ITERATIONS),
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
            "year,"
            + ",".join(f"type{index + 1}" for index in range(class_count))
            + "\n"
            + str(target_year)
            + ","
            + ",".join(str(int(value)) for value in demand)
            + "\n",
            encoding="utf-8",
        )
        process_seed = _derived_simulation_seed(seed, region_index, target_year)
        log_path = region_root / f"flus_simulation_{target_year}.log"
        year_started = time.perf_counter()
        _run_process(
            [str(flus_binary)],
            cwd=region_root,
            seed=process_seed,
            log_path=log_path,
        )
        converged_path = output_base.with_name(
            f"{output_base.stem}_{target_year}{output_base.suffix}"
        )
        result_path = converged_path if converged_path.is_file() else output_base
        if not result_path.is_file():
            raise RuntimeError("v3_full_grid_flus_result_missing")
        with rasterio.open(result_path) as dataset:
            result = dataset.read(1)
        full_codes = result[region.valid_input].astype(np.int64)
        if not np.isin(full_codes, list(code_to_class)).all():
            raise ValueError("v3_full_grid_flus_result_contains_invalid_code")
        current_classes = np.array(
            [code_to_class[int(code)] for code in full_codes], dtype=np.int64
        )
        sampled_prediction = []
        for row in sampled_inputs.itertuples(index=False):
            code = int(result[int(row.raster_row), int(row.raster_column)])
            if code not in code_to_class:
                raise ValueError("v3_flus_invalid_class_at_sampled_node")
            sampled_prediction.append(code_to_class[code])
        prediction_by_year[target_year] = sampled_prediction
        actual_counts = np.bincount(
            np.searchsorted(active_classes, current_classes),
            minlength=len(active_classes),
        )
        distance = float(
            np.abs(demand.astype(np.float64) - actual_counts).sum()
            / (2.0 * demand.sum())
        )
        year_reports.append(
            {
                "target_year": target_year,
                "derived_process_seed": process_seed,
                "requested_counts": demand.tolist(),
                "actual_counts": actual_counts.tolist(),
                "exact_demand_convergence": bool(np.array_equal(demand, actual_counts)),
                "demand_total_variation_distance": distance,
                "result_sha256": sha256_file(result_path),
                "elapsed_seconds": time.perf_counter() - year_started,
            }
        )

    rows = []
    for node_position, row in enumerate(sampled_inputs.itertuples(index=False)):
        for target_year in TARGET_YEARS:
            predicted_class = int(prediction_by_year[target_year][node_position])
            output = {
                "region_id": region.region_id,
                "node_id": row.node_id,
                "target_year": target_year,
            }
            output.update(
                {
                    column: float(index == predicted_class)
                    for index, column in enumerate(PROBABILITY_COLUMNS)
                }
            )
            rows.append(output)
    return rows, {
        "region_id": region.region_id,
        "full_grid_shape": list(region.valid_input.shape),
        "full_valid_cell_count": region.valid_cell_count,
        "scored_sampled_node_count": len(sampled_inputs),
        "active_original_classes": active_classes,
        "year_runs": year_reports,
    }


def _mean_predictions(frames: list[pd.DataFrame]) -> pd.DataFrame:
    keys = frames[0][KEY_COLUMNS].reset_index(drop=True)
    if any(not frame[KEY_COLUMNS].reset_index(drop=True).equals(keys) for frame in frames[1:]):
        raise ValueError("flus_seed_prediction_keys_mismatch")
    result = keys.copy()
    result[PROBABILITY_COLUMNS] = np.mean(
        np.stack(
            [frame[PROBABILITY_COLUMNS].to_numpy(dtype=np.float64) for frame in frames]
        ),
        axis=0,
    )
    return result


def _directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def run(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    flus_root: Path = FLUS_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    protocol = load_json(PROTOCOL_PATH)
    firewall_before = enforce_label_firewall(protocol)
    bundle_manifest = load_json(BUNDLE_MANIFEST_PATH)
    contract, expected_keys = load_prediction_contract()
    sampled_inputs = pd.read_parquet(BUNDLE_ROOT / "observed_inputs.parquet")
    flus_binary = _flus_binary(flus_root.resolve())

    development_manifest_path = REPO_ROOT / protocol["dataset"][
        "development_region_manifest"
    ]
    development_root = development_manifest_path.parent
    target_root = REPO_ROOT / protocol["dataset"]["phase_a_input_root"]
    target_manifest_path = target_root / "manifest.json"
    development_regions = _load_regions(
        root=development_root,
        manifest_path=development_manifest_path,
        source_role="development",
    )
    target_regions = _load_regions(
        root=target_root,
        manifest_path=target_manifest_path,
        source_role="v3_phase_a",
    )
    development_ids = {region.region_id for region in development_regions}
    target_ids = {region.region_id for region in target_regions}
    if development_ids & target_ids:
        raise ValueError("flus_development_and_v3_regions_overlap")
    if target_ids != set(sampled_inputs["region_id"].unique()):
        raise ValueError("flus_full_grid_regions_do_not_match_submission_nodes")

    counts, transition = _transition_matrix(development_regions)
    source_payload = {
        "schema": "gwm_bench.v3_flus_source_manifest.v1",
        "development_years_read": list(HISTORY_YEARS),
        "maximum_development_label_year_read": 2022,
        "v3_phase_a_years_read": list(HISTORY_YEARS),
        "v3_target_pixels_read": False,
        "development_region_count": len(development_regions),
        "v3_region_count": len(target_regions),
        "development_valid_cell_count": sum(
            region.valid_cell_count for region in development_regions
        ),
        "v3_valid_cell_count": sum(region.valid_cell_count for region in target_regions),
        "artifacts": sorted(
            [
                row
                for region in [*development_regions, *target_regions]
                for row in region.source_artifacts
            ],
            key=lambda row: row["path"],
        ),
    }
    source_payload["source_fingerprint"] = fingerprint(source_payload)

    output_root.mkdir(parents=True, exist_ok=True)
    source_path = output_root / "source_manifest.json"
    environment_path = output_root / "runtime_environment.json"
    write_json_atomic(source_payload, source_path)
    write_json_atomic(runtime_environment(), environment_path)

    work_root = Path(
        tempfile.mkdtemp(prefix="gwm-v3-flus-", dir="/private/tmp")
    )
    total_temporary_bytes = 0
    member_frames = []
    member_artifacts = []
    member_reports = []
    try:
        for seed in SEEDS:
            seed_started = time.perf_counter()
            seed_work = work_root / f"seed_{seed}"
            suitability, ann_report = _train_suitability(
                seed=seed,
                training_regions=development_regions,
                target_regions=target_regions,
                flus_binary=flus_binary,
                work_root=seed_work,
            )
            rows = []
            region_reports = []
            for region_index, region in enumerate(target_regions):
                region_rows, region_report = _simulate_region(
                    seed=seed,
                    region_index=region_index,
                    region=region,
                    sampled_inputs=sampled_inputs[
                        sampled_inputs["region_id"] == region.region_id
                    ],
                    suitability=suitability[region.region_id],
                    transition=transition,
                    flus_binary=flus_binary,
                    work_root=seed_work,
                )
                rows.extend(region_rows)
                region_reports.append(region_report)
                print(
                    f"flus seed={seed} region={region_index + 1}/20 {region.region_id} complete",
                    flush=True,
                )
            member = validate_submission(
                pd.DataFrame(rows, columns=KEY_COLUMNS + PROBABILITY_COLUMNS),
                contract=contract,
                expected_keys=expected_keys,
            )
            member_path = output_root / "members" / f"seed_{seed}" / "prediction.parquet"
            write_parquet_atomic(member, member_path)
            member_artifact = artifact(
                member_path, role="flus_full_grid_seed_member_prediction"
            )
            seed_temp_bytes = _directory_size(seed_work)
            total_temporary_bytes += seed_temp_bytes
            seed_report = {
                "schema": "gwm_bench.v3_flus_seed_run.v1",
                "seed": seed,
                "status": "COMPLETE",
                "ann": ann_report,
                "regions": region_reports,
                "prediction": member_artifact,
                "temporary_bytes": seed_temp_bytes,
                "wall_time_seconds": time.perf_counter() - seed_started,
                "target_pixels_read": False,
            }
            seed_report_path = output_root / "members" / f"seed_{seed}" / "run_report.json"
            write_json_atomic(seed_report, seed_report_path)
            member_frames.append(member)
            member_artifacts.append(
                {
                    "seed": seed,
                    "prediction": member_artifact,
                    "run_report": artifact(
                        seed_report_path, role="flus_seed_runtime_report"
                    ),
                }
            )
            member_reports.append(seed_report)
            shutil.rmtree(seed_work)
            print(
                f"flus seed={seed} member sha256={member_artifact['sha256']}",
                flush=True,
            )
    except Exception:
        print(f"FLUS failed; temporary evidence retained at {work_root}", flush=True)
        raise
    else:
        shutil.rmtree(work_root)

    ensemble = validate_submission(
        _mean_predictions(member_frames),
        contract=contract,
        expected_keys=expected_keys,
    )
    prediction_path = output_root / "prediction.parquet"
    write_parquet_atomic(ensemble, prediction_path)

    binary_artifact = _external_artifact(
        flus_binary, role="geosos_flus_cross_platform_executable"
    )
    adapter_source = artifact(Path(__file__), role="v3_flus_runtime_r2_adapter")
    implementation_sources = [
        artifact(path, role="prior_validated_flus_adapter_source")
        for path in V0_FLUS_SOURCES
    ]
    model_spec = {
        "schema": "gwm_bench.v3_geosos_flus_candidate.v1",
        "model_id": "geosos_flus_three_seed_ensemble",
        "method": "GeoSOS FLUS ANN suitability plus cellular allocation",
        "citation": (
            "Liu et al. (2017), Landscape and Urban Planning 168:94-116, "
            "doi:10.1016/j.landurbplan.2017.09.019"
        ),
        "license_boundary": "non-commercial academic research",
        "binary": binary_artifact,
        "base_seeds": list(SEEDS),
        "seed_ensemble": "equal empirical probability over three categorical members",
        "training": {
            "regions": "all 20 frozen development regions",
            "land_years": list(HISTORY_YEARS),
            "ann_label_year": 2022,
            "ann_features": list(FEATURE_NAMES),
            "omitted_driver": (
                "annual VIIRS change is unavailable in Phase A; a constant-zero "
                "column is excluded because FLUS min-max normalization is undefined"
            ),
            "sample_per_mille": SAMPLE_PER_MILLE,
            "hidden_layer": 8,
            "transition_estimator": "add-one global 9x9 matrix over 2017-2022 full-grid development transitions",
        },
        "allocation": {
            "grid": "complete 100 m input-valid raster before node extraction",
            "origin_year": 2022,
            "target_years": list(TARGET_YEARS),
            "writeback": "previous FLUS categorical full-grid result",
            "demand": "apply frozen development transition matrix to previous predicted full-grid counts",
            "maximum_iterations": MAX_ITERATIONS,
            "neighborhood_size": 3,
            "accelerated_factor": 0.1,
        },
        "selection": {
            "v3_target_labels_used": False,
            "post_prediction_adjustment_allowed": False,
            "parameter_origin": "pre-existing V1 full-grid FLUS historical baseline",
        },
        "transition_counts_with_smoothing": counts.tolist(),
        "transition_probability": transition.tolist(),
        "source_fingerprint": source_payload["source_fingerprint"],
        "implementation_sources": [adapter_source, *implementation_sources],
    }
    model_spec_path = output_root / "model_spec.json"
    write_json_atomic(model_spec, model_spec_path)

    all_year_runs = [
        year_run
        for member in member_reports
        for region in member["regions"]
        for year_run in region["year_runs"]
    ]
    firewall_after = enforce_label_firewall(protocol)
    prediction_artifact = artifact(
        prediction_path, role="sealed_v3_flus_ensemble_prediction"
    )
    environment_artifact = artifact(
        environment_path, role="runtime_environment_descriptor"
    )
    model_spec_artifact = artifact(
        model_spec_path, role="frozen_v3_flus_model_and_adapter_spec"
    )
    report = {
        "schema": "gwm_bench.runtime_r2_prediction_run.v1",
        "suite_id": protocol["suite_id"],
        "model_group": "geosos_flus_three_seed_ensemble",
        "status": "PREDICTION_COMPLETE_LABEL_FIREWALL_INTACT_REPLAY_PENDING",
        "created_at": utc_now(),
        "lifecycle": {
            "prepare": "complete",
            "predict": "complete",
            "writeback": "predicted_full_grid_categorical_state",
            "audit": "complete",
        },
        "label_firewall": {
            "before": firewall_before,
            "after": firewall_after,
            "target_pixels_read": False,
        },
        "contract": {
            "submission_contract_sha256": sha256_file(SUBMISSION_CONTRACT_PATH),
            "protocol_sha256": sha256_file(PROTOCOL_PATH),
            "phase_a_bundle_fingerprint": bundle_manifest["bundle_fingerprint"],
            "submission_keys_sha256": bundle_manifest["artifacts"][
                "submission_keys.parquet"
            ]["sha256"],
        },
        "hashes": {
            "protocol": sha256_file(PROTOCOL_PATH),
            "phase_a_bundle": bundle_manifest["bundle_fingerprint"],
            "runtime_environment": environment_artifact["sha256"],
            "adapter_source": adapter_source["sha256"],
            "model_or_binary": binary_artifact["sha256"],
            "random_seed_or_seed_set": fingerprint(
                {
                    "base_seeds": list(SEEDS),
                    "simulation_seed_formula": "base*100000+region_index*100+(year-2000)",
                }
            ),
            "prediction": prediction_artifact["sha256"],
        },
        "artifacts": {
            "prediction": prediction_artifact,
            "member_predictions": member_artifacts,
            "model_spec": model_spec_artifact,
            "adapter_source": adapter_source,
            "runtime_environment": environment_artifact,
            "source_manifest": artifact(
                source_path, role="flus_development_and_phase_a_source_manifest"
            ),
            "binary": binary_artifact,
        },
        "full_grid_execution": {
            "development_valid_cell_count": source_payload[
                "development_valid_cell_count"
            ],
            "v3_valid_cell_count_per_seed": source_payload["v3_valid_cell_count"],
            "region_seed_run_count": len(SEEDS) * len(target_regions),
            "region_year_run_count": len(all_year_runs),
            "exact_demand_run_count": int(
                sum(row["exact_demand_convergence"] for row in all_year_runs)
            ),
            "mean_demand_total_variation_distance": float(
                np.mean(
                    [row["demand_total_variation_distance"] for row in all_year_runs]
                )
            ),
            "maximum_demand_total_variation_distance": float(
                np.max(
                    [row["demand_total_variation_distance"] for row in all_year_runs]
                )
            ),
            "large_temporary_rasters_committed": False,
        },
        "prediction_summary": prediction_summary(ensemble, sampled_inputs),
        "resource_usage": {
            "wall_time_seconds": time.perf_counter() - started,
            "peak_memory_bytes": peak_memory_bytes(),
            "temporary_bytes": total_temporary_bytes,
            "exit_status": 0,
        },
        "replay": {
            "stochastic_member_count": len(SEEDS),
            "all_seed_members_materialized": True,
            "required": True,
            "verified": False,
        },
        "claim_boundary": {
            "external_flus_core_baseline": True,
            "published_sota_comparison": False,
            "operational_forecast_supported": False,
            "quality_claimed_before_labels": False,
        },
    }
    report_path = output_root / "run_report.json"
    write_json_atomic(report, report_path)
    print(
        f"flus ensemble: rows={len(ensemble)} sha256={prediction_artifact['sha256']}",
        flush=True,
    )
    print(f"report: {report_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--flus-root", type=Path, default=FLUS_ROOT)
    args = parser.parse_args()
    run(output_root=args.output_root.resolve(), flus_root=args.flus_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
