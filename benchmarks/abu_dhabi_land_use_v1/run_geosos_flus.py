#!/usr/bin/env python3
"""Run the external GeoSOS-FLUS ANN+CA on the unified Abu Dhabi bundle."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_origin

try:
    from .shared import CLASSES, evaluate_prediction
except ImportError:  # Direct script execution from the benchmark directory.
    from shared import CLASSES, evaluate_prediction

HERE = Path(__file__).resolve().parent
INPUT_ROOT = HERE / "artifacts/gee"
OSM_ROOT = HERE / "artifacts/osm"
BUNDLE_ROOT = HERE / "artifacts/bundle"
DEFAULT_OUTPUT = HERE / "artifacts/predictions/geosos_flus"
DEFAULT_BINARY = Path("/Users/zhouning/FLUS_console_crossplatform/build/cmake-release/flus_console")
FIT_YEARS = (2021,)
SEEDS = (31, 47, 73)
FEATURE_NAMES = (
    "x_utm",
    "y_utm",
    "elevation",
    "slope",
    "log_viirs",
    "log_distance_road",
    "log_distance_major_road",
)


def _read(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with rasterio.open(path) as dataset:
        return dataset.read(), dataset.profile.copy()


def _write_compact(path: Path, values: np.ndarray, *, nodata: float) -> None:
    data = np.asarray(values)
    if data.ndim == 2:
        data = data[None, ...]
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[2],
        height=data.shape[1],
        count=data.shape[0],
        dtype=data.dtype,
        crs="EPSG:3857",
        transform=from_origin(0, data.shape[1], 1, 1),
        nodata=nodata,
    ) as dataset:
        dataset.write(data)


def _write_like(
    path: Path,
    values: np.ndarray,
    *,
    reference: dict[str, Any],
    nodata: float,
) -> None:
    data = np.asarray(values)
    if data.ndim == 2:
        data = data[None, ...]
    profile = reference.copy()
    profile.update(count=data.shape[0], dtype=str(data.dtype), nodata=nodata)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(data)


def _run_process(command: list[str], *, cwd: Path, seed: int, log_path: Path) -> None:
    environment = os.environ.copy()
    environment["FLUS_RANDOM_SEED"] = str(seed)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    log_path.write_text(
        "$ " + " ".join(command) + "\n\n" + completed.stdout + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode:
        raise RuntimeError(f"flus_failed:{completed.returncode}:{log_path}")


class FlusInputs:
    def __init__(self) -> None:
        city, self.reference = _read(HERE / "artifacts/abu_dhabi_city_100m_mask.tif")
        common, _ = _read(BUNDLE_ROOT / "common_valid_mask_100m.tif")
        hard, _ = _read(BUNDLE_ROOT / "hard_exclusion_2022_100m.tif")
        self.city = city[0].astype(bool)
        self.valid = common[0].astype(bool)
        self.hard = hard[0].astype(bool)
        self.states = {
            year: _read(INPUT_ROOT / "land_cover" / f"land_cover_{year}_100m.tif")[0][0]
            for year in range(2017, 2025)
        }
        terrain, _ = _read(INPUT_ROOT / "terrain" / "copernicus_dem_2024_1_slope_100m.tif")
        roads, _ = _read(OSM_ROOT / "road_accessibility_100m.tif")
        self.elevation = terrain[0]
        self.slope = terrain[1]
        self.road_distance = roads[0]
        self.major_road_distance = roads[1]
        self.viirs = {
            year: _read(INPUT_ROOT / "viirs" / f"viirs_{year}_100m.tif")[0][0]
            for year in range(2017, 2025)
        }
        rows, columns = np.indices(self.valid.shape)
        transform = self.reference["transform"]
        self.x = transform.c + (columns + 0.5) * transform.a
        self.y = transform.f + (rows + 0.5) * transform.e

    def features(self, year: int) -> np.ndarray:
        return np.column_stack(
            [
                self.x[self.valid],
                self.y[self.valid],
                self.elevation[self.valid],
                self.slope[self.valid],
                np.log1p(np.clip(self.viirs[year][self.valid], 0, None)),
                np.log1p(np.clip(self.road_distance[self.valid], 0, None)),
                np.log1p(np.clip(self.major_road_distance[self.valid], 0, None)),
            ]
        ).astype(np.float32)


def train_suitability(
    inputs: FlusInputs,
    *,
    binary: Path,
    seed: int,
    work_root: Path,
    target_driver_year: int = 2022,
) -> tuple[np.ndarray, dict[str, Any]]:
    training_features = np.concatenate([inputs.features(year) for year in FIT_YEARS])
    training_labels = np.concatenate(
        [inputs.states[year][inputs.valid].astype(np.uint8) for year in FIT_YEARS]
    )
    target_features = inputs.features(target_driver_year)
    packed_target = np.full_like(training_features, 0.5, dtype=np.float32)
    packed_target[: len(target_features)] = target_features
    ann_root = work_root / "ann"
    (ann_root / "FilesGenerate").mkdir(parents=True, exist_ok=True)
    label_path = ann_root / "training_landuse.tif"
    probability_path = ann_root / "target_probability.tif"
    _write_compact(label_path, training_labels[None, :], nodata=0)
    training_paths = []
    target_paths = []
    for index, name in enumerate(FEATURE_NAMES):
        training_path = ann_root / f"train_{index}_{name}.tif"
        target_path = ann_root / f"target_{index}_{name}.tif"
        _write_compact(training_path, training_features[:, index][None, :], nodata=-1)
        _write_compact(target_path, packed_target[:, index][None, :], nodata=-1)
        training_paths.append(training_path)
        target_paths.append(target_path)
    config_path = ann_root / "CCregiontrainlogCC.txt"
    config_path.write_text(
        "\n".join(
            [
                "[Path of land use data]",
                str(label_path),
                "[Path of saving data]",
                str(probability_path),
                "[Number of driving data]",
                str(len(training_paths)),
                "[Path of driving data]",
                *[str(path) for path in training_paths],
                "[Data type]",
                "Float",
                "[Normalization type]",
                "Normalization",
                "[Sample type]",
                "Proportional Sampling",
                "[Percentage of Random Points]",
                "100",
                "[Hidden layer]",
                "8",
                "",
            ]
        ),
        encoding="utf-8",
    )
    update_path = ann_root / "update_drivers.csv"
    update_path.write_text(
        "".join(f"{index},{path}\n" for index, path in enumerate(target_paths)),
        encoding="utf-8",
    )
    started = time.perf_counter()
    _run_process(
        [str(binary), "train-update", str(config_path), str(update_path)],
        cwd=ann_root,
        seed=seed,
        log_path=ann_root / "flus_ann.log",
    )
    with rasterio.open(probability_path) as dataset:
        raw = dataset.read()[:, 0, : len(target_features)].astype(np.float32)
    probability = np.full((len(CLASSES), len(target_features)), 1e-9, dtype=np.float32)
    probability[: raw.shape[0]] = np.clip(raw, 1e-9, None)
    probability /= probability.sum(axis=0, keepdims=True)
    cube = np.full((len(CLASSES), *inputs.valid.shape), -1.0, dtype=np.float32)
    cube[:, inputs.valid] = probability
    return cube, {
        "seed": seed,
        "training_pixel_rows": len(training_features),
        "target_pixel_rows": len(target_features),
        "feature_names": list(FEATURE_NAMES),
        "fit_label_years": list(FIT_YEARS),
        "target_driver_year": target_driver_year,
        "fit_seconds": time.perf_counter() - started,
    }


def _actions() -> list[dict[str, Any]]:
    return json.loads((BUNDLE_ROOT / "allocation_actions.json").read_text())["actions"]


def simulate_year(
    current: np.ndarray,
    probability: np.ndarray,
    *,
    action: dict[str, Any],
    inputs: FlusInputs,
    binary: Path,
    seed: int,
    work_root: Path,
) -> tuple[np.ndarray, dict[str, Any]]:
    target_year = int(action["target_year"])
    target_counts = {
        int(key): int(value) for key, value in action["feasible_target_counts"].items()
    }
    landuse_path = work_root / f"landuse_{target_year - 1}.tif"
    probability_path = work_root / "probability.tif"
    restrict_path = work_root / "restrict.tif"
    result_base = work_root / f"prediction_{target_year}.tif"
    _write_like(landuse_path, current.astype(np.uint8), reference=inputs.reference, nodata=0)
    _write_like(probability_path, probability, reference=inputs.reference, nodata=-1)
    allowed = (inputs.valid & ~inputs.hard).astype(np.uint8)
    _write_like(restrict_path, allowed, reference=inputs.reference, nodata=0)
    cost_rows = []
    for source in CLASSES:
        row = []
        for target in CLASSES:
            prohibited = source != target and (source in {1, 4} or target in {1, 4})
            row.append("0" if prohibited else "1")
        cost_rows.append(",".join(row))
    config_path = work_root / "CCregionsimlog.txt"
    config_path.write_text(
        "\n".join(
            [
                "[Path of land use data]",
                str(landuse_path),
                "[Path of probability data]",
                str(probability_path),
                "[Path of simulation result]",
                str(result_base),
                "[Path of restricted area]",
                str(restrict_path),
                "[Number of types]",
                str(len(CLASSES)),
                "[Future Pixels]",
                *[str(target_counts[value]) for value in CLASSES],
                "[Cost Matrix]",
                *cost_rows,
                "[Intensity of neighborhood]",
                *["1" for _ in CLASSES],
                "[Maximum Number Of Iterations]",
                "1000",
                "[Size of neighborhood]",
                "3",
                "[Accelerated factor]",
                "0.1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    demand_path = work_root / "CCregionMakovChain.csv"
    demand_path.write_text(
        "year,"
        + ",".join(f"type{value}" for value in CLASSES)
        + "\n"
        + str(target_year)
        + ","
        + ",".join(str(target_counts[value]) for value in CLASSES)
        + "\n",
        encoding="utf-8",
    )
    started = time.perf_counter()
    _run_process(
        [str(binary)],
        cwd=work_root,
        seed=seed * 10000 + target_year,
        log_path=work_root / f"flus_ca_{target_year}.log",
    )
    generated = result_base.with_name(f"{result_base.stem}_{target_year}{result_base.suffix}")
    result_path = generated if generated.is_file() else result_base
    if not result_path.is_file():
        raise RuntimeError("flus_prediction_missing")
    with rasterio.open(result_path) as dataset:
        result = dataset.read(1).astype(np.uint8)
    result[~inputs.valid] = 0
    if np.any(result[inputs.valid & inputs.hard] != current[inputs.valid & inputs.hard]):
        raise RuntimeError("flus_changed_hard_exclusion")
    return result, {
        "target_year": target_year,
        "ca_seconds": time.perf_counter() - started,
        "target_counts": target_counts,
    }


def run_seed(
    inputs: FlusInputs,
    *,
    binary: Path,
    seed: int,
    output_root: Path,
    temporary_root: Path,
) -> dict[str, Any]:
    seed_work = temporary_root / f"seed_{seed}"
    seed_work.mkdir(parents=True, exist_ok=True)
    probability, training = train_suitability(
        inputs,
        binary=binary,
        seed=seed,
        work_root=seed_work,
    )
    current = inputs.states[2022].copy()
    year_rows = []
    for action in _actions():
        current, simulation = simulate_year(
            current,
            probability,
            action=action,
            inputs=inputs,
            binary=binary,
            seed=seed,
            work_root=seed_work / f"ca_{action['target_year']}",
        )
        target_year = int(action["target_year"])
        output_path = output_root / f"seed_{seed}" / f"prediction_{target_year}.tif"
        _write_like(output_path, current, reference=inputs.reference, nodata=0)
        reliability, _ = _read(HERE / action["reliability_mask"])
        evaluation = evaluate_prediction(
            current,
            origin_state=inputs.states[2022],
            observed_target=inputs.states[target_year],
            valid_mask=inputs.valid,
            hard_exclusion_mask=inputs.hard,
            requested_counts=simulation["target_counts"],
            reliability_mask=reliability[0].astype(bool),
        )
        year_rows.append(
            {
                **simulation,
                "prediction_path": str(output_path.relative_to(HERE)),
                "evaluation": evaluation,
            }
        )
    return {"seed": seed, "training": training, "years": year_rows}


def run(*, binary: Path, seeds: tuple[int, ...], output_root: Path) -> dict[str, Any]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise FileNotFoundError(f"flus_binary_not_executable:{binary}")
    started = time.perf_counter()
    inputs = FlusInputs()
    reports = []
    work_root = output_root / "work"
    for seed in seeds:
        reports.append(
            run_seed(
                inputs,
                binary=binary.resolve(),
                seed=seed,
                output_root=output_root,
                temporary_root=work_root,
            )
        )
        print(f"geosos_flus:seed_{seed}:complete", flush=True)
    report = {
        "schema": "gwm.abu_dhabi_geosos_flus_run.v1",
        "benchmark_id": "abu-dhabi-land-use-v1",
        "model_id": "geosos_flus",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "external_binary": str(binary.resolve()),
        "state_writeback": True,
        "test_label_access_during_fit": False,
        "seeds": reports,
        "wall_seconds": time.perf_counter() - started,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--seeds", default=",".join(str(value) for value in SEEDS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(
        binary=args.binary,
        seeds=tuple(int(value) for value in args.seeds.split(",") if value.strip()),
        output_root=args.output,
    )
    print(json.dumps({"status": report["status"], "wall_seconds": report["wall_seconds"]}))


if __name__ == "__main__":
    main()
