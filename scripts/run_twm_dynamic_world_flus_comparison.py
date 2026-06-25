#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_twm_public_landcover_benchmark import (  # noqa: E402
    BenchmarkRegion,
    LandcoverFrame,
    aggregate_experiments,
    build_ablation_summary,
    build_candidates,
    class_counts,
    load_manifest_regions,
    pixel_metrics,
    project_class_counts,
    transition_prior_probability_cube,
    valid_mask,
)


DEFAULT_MANIFEST = REPO_ROOT / "data/twm_public_landcover/gee_dynamic_world/twm_dynamic_world_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_dynamic_world_admin20_flus_smoke_2026-06-23.json"
DEFAULT_RUN_ROOT = REPO_ROOT / "data/twm_public_landcover/flus_admin20_runs"
DEFAULT_FLUS_EXECUTABLE = Path("/Users/zhouning/FLUS_console_crossplatform/build/flus_console")
FLUS_CANDIDATE_ID = "flus_console_direct"


@dataclass(frozen=True)
class FlusComparisonCase:
    case_id: str
    region_id: str
    train_start_year: int
    train_end_year: int
    holdout_year: int
    train_start: LandcoverFrame
    train_end: LandcoverFrame
    holdout: LandcoverFrame
    valid: np.ndarray
    classes: tuple[int, ...]
    class_labels: dict[int, str]
    cell_area_ha: float
    target_counts: dict[int, int]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package and optionally run FLUS-console comparisons for Dynamic World admin20 rolling cases."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--flus-executable", type=Path, default=DEFAULT_FLUS_EXECUTABLE)
    parser.add_argument("--region-limit", type=int, default=None)
    parser.add_argument("--case-limit", type=int, default=None)
    parser.add_argument(
        "--case-limit-per-region",
        type=int,
        default=None,
        help="Limit rolling holdout cases per selected region for balanced pilot sampling.",
    )
    parser.add_argument("--regions", nargs="*", default=None, help="Optional exact region_id allow-list.")
    parser.add_argument("--max-iterations", type=int, default=30)
    parser.add_argument("--flus-seed", type=int, default=None, help="Optional fixed FLUS_RANDOM_SEED for reproducible CA runs.")
    parser.add_argument(
        "--probability-backend",
        choices=("observed_train_transition_prior_probability_cube", "flus_ann_training"),
        default="observed_train_transition_prior_probability_cube",
    )
    parser.add_argument("--run-flus", action="store_true", help="Execute the local FLUS console after packaging each case.")
    parser.add_argument("--no-run-flus", action="store_true", help="Explicit package-only mode.")
    args = parser.parse_args()

    if args.run_flus and args.no_run_flus:
        raise SystemExit("Use either --run-flus or --no-run-flus, not both.")

    report = run_dynamic_world_flus_comparison(
        manifest_path=args.manifest,
        output_path=args.output,
        run_root=args.run_root,
        flus_executable=args.flus_executable,
        region_limit=args.region_limit,
        case_limit=args.case_limit,
        case_limit_per_region=args.case_limit_per_region,
        region_ids=args.regions,
        max_iterations=args.max_iterations,
        flus_seed=args.flus_seed,
        probability_backend=args.probability_backend,
        run_flus=bool(args.run_flus),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))


def run_dynamic_world_flus_comparison(
    *,
    manifest_path: Path,
    output_path: Path | None = None,
    run_root: Path,
    flus_executable: Path = DEFAULT_FLUS_EXECUTABLE,
    region_limit: int | None = None,
    case_limit: int | None = None,
    case_limit_per_region: int | None = None,
    region_ids: Sequence[str] | None = None,
    max_iterations: int = 30,
    flus_seed: int | None = None,
    probability_backend: str = "observed_train_transition_prior_probability_cube",
    run_flus: bool = False,
) -> dict[str, Any]:
    regions, source = load_manifest_regions(manifest_path)
    selected_regions = select_regions(regions, region_limit=region_limit, region_ids=region_ids)
    cases = select_cases(selected_regions, case_limit=case_limit, case_limit_per_region=case_limit_per_region)
    run_root.mkdir(parents=True, exist_ok=True)

    experiments: list[dict[str, Any]] = []
    packaged_cases: list[dict[str, Any]] = []
    for case in cases:
        package = write_flus_case_package(
            case,
            run_root / case.case_id,
            max_iterations=max_iterations,
            probability_backend=probability_backend,
        )
        if run_flus:
            ann_training = None
            if probability_backend == "flus_ann_training":
                ann_training = run_flus_ann_training(
                    Path(package["run_dir"]),
                    flus_executable=flus_executable,
                    flus_seed=flus_seed,
                )
                package["ann_training"] = ann_training
            if should_run_flus_simulation(package, probability_backend=probability_backend, ann_training=ann_training):
                package["execution"] = run_flus_console(Path(package["run_dir"]), flus_executable=flus_executable, flus_seed=flus_seed)
            else:
                package["execution"] = {
                    "status": "blocked",
                    "reason": "ann_training_failed",
                    "flus_seed": int(flus_seed) if flus_seed is not None else None,
                }
        output_candidates = [
            Path(package["run_dir"]) / f"simresult_{case.holdout_year}.tif",
            Path(package["run_dir"]) / "simresult.tif",
        ]
        existing_output = next((path for path in output_candidates if path.exists()), None)
        evaluation = evaluate_flus_output(case, existing_output) if existing_output is not None else None
        package["evaluation_status"] = "evaluated" if evaluation else "packaged_only"
        package["expected_output_paths"] = [str(path) for path in output_candidates]
        packaged_cases.append(package)
        experiments.append(build_case_experiment(case, package, evaluation))

    aggregate_inputs = [experiment for experiment in experiments if experiment.get("metrics")]
    report = {
        "schema": "territory_world_model.dynamic_world_admin20_flus_comparison.v1",
        "status": "pass" if packaged_cases else "blocked",
        "claim_boundary": "flus_console_adapter_smoke_not_full_twmmodel_superiority_claim",
        "source": source,
        "output_path": str(output_path) if output_path is not None else None,
        "run_policy": {
            "run_flus": bool(run_flus),
            "flus_executable": str(flus_executable),
            "max_iterations": int(max_iterations),
            "probability_backend": probability_backend,
            "demand_mode": "forecast_counts_projected_from_train_start_and_train_end",
            "case_limit": case_limit,
            "case_limit_per_region": case_limit_per_region,
            "flus_seed": flus_seed,
        },
        "data_profile": {
            "region_count": len(selected_regions),
            "case_count": len(cases),
            "packaged_case_count": len(packaged_cases),
            "evaluated_case_count": sum(1 for item in packaged_cases if item["evaluation_status"] == "evaluated"),
        },
        "packaged_cases": packaged_cases,
        "experiments": experiments,
        "summary": aggregate_experiments(aggregate_inputs) if aggregate_inputs else {"status": "not_evaluated_package_only"},
        "formal_forecast_comparison": build_formal_forecast_comparison(aggregate_inputs)
        if aggregate_inputs
        else {"status": "not_evaluated_package_only"},
        "next_steps": [
            "Run --run-flus on one packaged case and inspect FLUS convergence/output naming.",
            "Freeze the probability-generation protocol before comparing all 20 regions.",
            "Scale to all admin20 rolling cases only after one direct FLUS case is evaluated end-to-end.",
        ],
    }
    return report


def select_regions(
    regions: list[BenchmarkRegion],
    *,
    region_limit: int | None,
    region_ids: Sequence[str] | None,
) -> list[BenchmarkRegion]:
    selected = regions
    if region_ids:
        allowed = set(region_ids)
        selected = [region for region in selected if region.region_id in allowed]
    if region_limit is not None:
        selected = selected[: max(0, int(region_limit))]
    return selected


def select_cases(
    regions: list[BenchmarkRegion],
    *,
    case_limit: int | None,
    case_limit_per_region: int | None = None,
) -> list[FlusComparisonCase]:
    cases: list[FlusComparisonCase] = []
    for region in regions:
        frames = list(region.frames)
        region_case_count = 0
        for idx in range(len(frames) - 2):
            train_start = frames[idx]
            train_end = frames[idx + 1]
            holdout = frames[idx + 2]
            valid = valid_mask(train_start, train_end, holdout, region.classes)
            if int(valid.sum()) <= 0:
                continue
            target_counts = project_class_counts(
                train_start.array,
                train_end.array,
                valid,
                list(region.classes),
                train_years=max(1, train_end.year - train_start.year),
                horizon_years=max(1, holdout.year - train_end.year),
            )
            cases.append(
                FlusComparisonCase(
                    case_id=safe_case_id(f"{region.region_id}_{train_start.year}_{train_end.year}_{holdout.year}"),
                    region_id=region.region_id,
                    train_start_year=int(train_start.year),
                    train_end_year=int(train_end.year),
                    holdout_year=int(holdout.year),
                    train_start=train_start,
                    train_end=train_end,
                    holdout=holdout,
                    valid=valid,
                    classes=tuple(int(cls) for cls in region.classes),
                    class_labels=dict(region.class_labels),
                    cell_area_ha=float(region.cell_area_ha),
                    target_counts=target_counts,
                )
            )
            region_case_count += 1
            if case_limit is not None and len(cases) >= int(case_limit):
                return cases
            if case_limit_per_region is not None and region_case_count >= int(case_limit_per_region):
                break
    return cases


def safe_case_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def dynamic_world_to_flus_classes(
    arr: np.ndarray,
    *,
    classes: Sequence[int],
    valid: np.ndarray,
) -> np.ndarray:
    out = np.zeros(arr.shape, dtype=np.uint8)
    for idx, cls in enumerate(classes, start=1):
        out[valid & (arr == int(cls))] = idx
    return out


def flus_to_dynamic_world_classes(
    arr: np.ndarray,
    *,
    classes: Sequence[int],
    valid: np.ndarray,
) -> np.ndarray:
    out = np.zeros(arr.shape, dtype=np.int16)
    for idx, cls in enumerate(classes, start=1):
        out[valid & (arr == idx)] = int(cls)
    return out


def write_flus_case_package(
    case: FlusComparisonCase,
    run_dir: Path,
    *,
    max_iterations: int = 30,
    probability_backend: str = "observed_train_transition_prior_probability_cube",
) -> dict[str, Any]:
    import rasterio

    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    landuse = dynamic_world_to_flus_classes(case.train_end.array, classes=case.classes, valid=case.valid)
    restrict = np.where(case.valid, 1, 0).astype(np.uint8)
    probability = build_flus_probability_cube(case)

    with rasterio.open(case.train_end.path) as src:
        profile = src.profile.copy()
    raster_profile = profile.copy()
    raster_profile.update(driver="GTiff", count=1, dtype="uint8", nodata=0)
    with rasterio.open(run_dir / "landuse.tif", "w", **raster_profile) as dst:
        dst.write(landuse, 1)
    with rasterio.open(run_dir / "restrict.tif", "w", **raster_profile) as dst:
        dst.write(restrict, 1)
    probability_profile = profile.copy()
    probability_profile.update(driver="GTiff", count=len(case.classes), dtype="float32", nodata=0.0)
    with rasterio.open(run_dir / "probability.tif", "w", **probability_profile) as dst:
        dst.write(probability.astype(np.float32))
    files = {
        "landuse": "landuse.tif",
        "probability": "probability.tif",
        "restrict": "restrict.tif",
        "config": "CCregionsimlog.txt",
        "demand": "CCregionMakovChain.csv",
    }
    ann_anchor = {"enabled": False, "anchor_cell_count": 0, "missing_flus_values": []}
    if probability_backend == "flus_ann_training":
        ann_anchor = write_flus_ann_training_package(case, run_dir, profile, landuse)
        files["ann_train_config"] = "CCregiontrainlogCC.txt"
        files["ann_driver"] = "driver_transition_features.tif"
        files["ann_landuse"] = "ann_landuse.tif"

    write_simulation_config(run_dir / "CCregionsimlog.txt", n_types=len(case.classes), max_iterations=max_iterations)
    write_demand_csv(run_dir / "CCregionMakovChain.csv", year=case.holdout_year, target_counts=case.target_counts, classes=case.classes)
    metadata = {
        "schema": "territory_world_model.dynamic_world_flus_case_package.v1",
        "case_id": case.case_id,
        "region_id": case.region_id,
        "train_period": f"{case.train_start_year}->{case.train_end_year}",
        "holdout_period": f"{case.train_end_year}->{case.holdout_year}",
        "valid_cell_count": int(case.valid.sum()),
        "classes": [
            {"dynamic_world_value": int(cls), "flus_value": idx, "label": str(case.class_labels.get(int(cls), cls))}
            for idx, cls in enumerate(case.classes, start=1)
        ],
        "target_counts_dynamic_world": {str(cls): int(case.target_counts[int(cls)]) for cls in case.classes},
        "target_counts_flus_order": [int(case.target_counts[int(cls)]) for cls in case.classes],
        "probability_backend": probability_backend,
        "ann_anchor": ann_anchor,
        "files": files,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "packaged",
        "case_id": case.case_id,
        "region_id": case.region_id,
        "run_dir": str(run_dir),
        "valid_cell_count": int(case.valid.sum()),
        "probability_backend": probability_backend,
        "target_counts": {str(cls): int(case.target_counts[int(cls)]) for cls in case.classes},
        "files": {key: str(run_dir / value) for key, value in metadata["files"].items()},
    }


def write_flus_ann_training_package(
    case: FlusComparisonCase,
    run_dir: Path,
    source_profile: dict[str, Any],
    ca_landuse: np.ndarray,
) -> dict[str, Any]:
    import rasterio

    driver = build_flus_ann_driver_cube(case)
    ann_landuse, ann_anchor = build_ann_training_landuse(ca_landuse, classes=case.classes, valid=case.valid)
    landuse_profile = source_profile.copy()
    landuse_profile.update(driver="GTiff", count=1, dtype="uint8", nodata=0)
    with rasterio.open(run_dir / "ann_landuse.tif", "w", **landuse_profile) as dst:
        dst.write(ann_landuse, 1)
    profile = source_profile.copy()
    profile.update(driver="GTiff", count=driver.shape[0], dtype="float32", nodata=-1.0)
    with rasterio.open(run_dir / "driver_transition_features.tif", "w", **profile) as dst:
        dst.write(driver.astype(np.float32))
    write_ann_training_config(
        run_dir / "CCregiontrainlogCC.txt",
        landuse_path="ann_landuse.tif",
        output_path="probability.tif",
        driver_path="driver_transition_features.tif",
    )
    return ann_anchor


def build_ann_training_landuse(
    ca_landuse: np.ndarray,
    *,
    classes: Sequence[int],
    valid: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    ann_landuse = ca_landuse.copy()
    expected_flus_values = list(range(1, len(classes) + 1))
    present = set(int(value) for value in np.unique(ann_landuse[valid]) if int(value) > 0)
    missing = [value for value in expected_flus_values if value not in present]
    anchor_cells: list[dict[str, int]] = []
    if missing:
        candidates = np.argwhere(valid)
        if len(candidates) < len(missing):
            raise ValueError("not_enough_valid_cells_for_ann_class_anchors")
        for flus_value, (row, col) in zip(missing, candidates):
            ann_landuse[int(row), int(col)] = int(flus_value)
            anchor_cells.append({"row": int(row), "col": int(col), "flus_value": int(flus_value)})
    return ann_landuse, {
        "enabled": bool(anchor_cells),
        "anchor_cell_count": len(anchor_cells),
        "missing_flus_values": [int(value) for value in missing],
        "anchor_cells": anchor_cells,
        "scope": "ann_training_landuse_only",
    }


def build_flus_ann_driver_cube(case: FlusComparisonCase) -> np.ndarray:
    height, width = case.train_end.array.shape
    class_membership = np.zeros((len(case.classes), height, width), dtype=np.float32)
    for idx, cls in enumerate(case.classes):
        class_membership[idx] = (case.train_start.array == int(cls)).astype(np.float32)
    changed = ((case.train_start.array != case.train_end.array) & case.valid).astype(np.float32)[None, :, :]
    row_gradient = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    col_gradient = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    spatial = np.stack(
        [
            np.broadcast_to(row_gradient, (height, width)),
            np.broadcast_to(col_gradient, (height, width)),
        ]
    )
    driver = np.concatenate([class_membership, changed, spatial], axis=0)
    driver[:, ~case.valid] = -1.0
    return driver


def write_ann_training_config(
    path: Path,
    *,
    landuse_path: str,
    output_path: str,
    driver_path: str,
    data_type: str = "Float",
    normalization_type: str = "No Normalization",
    sample_type: str = "Sampling in proportion",
    random_points_percentage: float = 1.0,
    hidden_layer: int = 8,
) -> None:
    lines = [
        "[Path of land use data]",
        landuse_path,
        "[Path of saving data]",
        output_path,
        "[Number of driving data]",
        "1",
        "[Path of driving data]",
        driver_path,
        "[Data type]",
        data_type,
        "[Normalization type]",
        normalization_type,
        "[Sample type]",
        sample_type,
        "[Percentage of Random Points]",
        str(random_points_percentage),
        "[Hidden layer]",
        str(int(hidden_layer)),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_flus_probability_cube(case: FlusComparisonCase) -> np.ndarray:
    model_inputs = {
        "train_start": case.train_start.array,
        "train_end": case.train_end.array,
        "initial": case.train_end.array,
        "actual": case.holdout.array,
        "valid": case.valid,
        "classes": list(case.classes),
        "drivers": {},
        "train_years": max(1, case.train_end_year - case.train_start_year),
        "horizon_years": max(1, case.holdout_year - case.train_end_year),
        "region_id": case.region_id,
        "train_start_year": case.train_start_year,
        "train_end_year": case.train_end_year,
        "holdout_year": case.holdout_year,
    }
    probability = transition_prior_probability_cube(model_inputs).astype(np.float32)
    totals = probability.sum(axis=0, keepdims=True)
    np.divide(probability, totals, out=probability, where=totals > 0)
    fallback = np.ones((len(case.classes), 1, 1), dtype=np.float32) / max(1, len(case.classes))
    probability[:, case.valid & (totals[0] <= 0)] = fallback[:, 0, 0][:, None]
    probability[:, ~case.valid] = 0.0
    return probability


def write_simulation_config(path: Path, *, n_types: int, max_iterations: int) -> None:
    lines = [
        "[Path of land use data]",
        "landuse.tif",
        "[Path of probability data]",
        "probability.tif",
        "[Path of simulation result]",
        "simresult.tif",
        "[Path of restricted area]",
        "restrict.tif",
        "[Number of types]",
        str(int(n_types)),
        "[Future Pixels]",
        *["0" for _ in range(n_types)],
        "[Cost Matrix]",
        *[",".join("1" for _ in range(n_types)) for _ in range(n_types)],
        "[Intensity of neighborhood]",
        *["1" for _ in range(n_types)],
        "[Maximum Number Of Iterations]",
        str(int(max_iterations)),
        "[Size of neighborhood]",
        "3",
        "[Accelerated factor]",
        "0.1",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_demand_csv(path: Path, *, year: int, target_counts: dict[int, int], classes: Sequence[int]) -> None:
    header = ["year", *[f"type{idx}" for idx in range(1, len(classes) + 1)]]
    values = [str(int(year)), *[str(int(target_counts[int(cls)])) for cls in classes]]
    path.write_text(",".join(header) + "\n" + ",".join(values) + "\n", encoding="utf-8")


def run_flus_console(run_dir: Path, *, flus_executable: Path, flus_seed: int | None = None) -> dict[str, Any]:
    if not flus_executable.exists():
        return {"status": "blocked", "reason": "flus_executable_not_found", "flus_executable": str(flus_executable)}
    env = os.environ.copy()
    if flus_seed is not None:
        env["FLUS_RANDOM_SEED"] = str(int(flus_seed))
    completed = subprocess.run(
        [str(flus_executable)],
        cwd=str(run_dir),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "status": "pass" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "flus_seed": int(flus_seed) if flus_seed is not None else None,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def should_run_flus_simulation(
    package: dict[str, Any],
    *,
    probability_backend: str,
    ann_training: dict[str, Any] | None,
) -> bool:
    if probability_backend != "flus_ann_training":
        return True
    return bool(ann_training and ann_training.get("status") == "pass")


def run_flus_ann_training(run_dir: Path, *, flus_executable: Path, flus_seed: int | None = None) -> dict[str, Any]:
    if not flus_executable.exists():
        return {"status": "blocked", "reason": "flus_executable_not_found", "flus_executable": str(flus_executable)}
    env = os.environ.copy()
    if flus_seed is not None:
        env["FLUS_RANDOM_SEED"] = str(int(flus_seed))
    completed = subprocess.run(
        [str(flus_executable), "train", "CCregiontrainlogCC.txt"],
        cwd=str(run_dir),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output_path = run_dir / "probability.tif"
    return {
        "status": "pass" if completed.returncode == 0 and output_path.exists() else "failed",
        "returncode": int(completed.returncode),
        "flus_seed": int(flus_seed) if flus_seed is not None else None,
        "output_path": str(output_path),
        "output_exists": output_path.exists(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def evaluate_flus_output(case: FlusComparisonCase, output_path: Path) -> dict[str, Any]:
    import rasterio

    with rasterio.open(output_path) as src:
        encoded = src.read(1)
    prediction = flus_to_dynamic_world_classes(encoded, classes=case.classes, valid=case.valid)
    metrics = pixel_metrics(
        prediction=prediction,
        actual=case.holdout.array,
        initial=case.train_end.array,
        valid=case.valid,
        classes=list(case.classes),
        cell_area_ha=case.cell_area_ha,
        target_counts=case.target_counts,
    )
    return {
        "status": "evaluated",
        "candidate_id": FLUS_CANDIDATE_ID,
        "output_path": str(output_path),
        "metrics": metrics,
    }


def build_case_experiment(
    case: FlusComparisonCase,
    package: dict[str, Any],
    evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    twm_metrics, twm_metadata = build_twm_case_metrics(case)
    metrics = dict(twm_metrics)
    if evaluation:
        metrics[FLUS_CANDIDATE_ID] = evaluation["metrics"]
    candidate_metadata = dict(twm_metadata)
    candidate_metadata[FLUS_CANDIDATE_ID] = {
        "backend": "local_flus_console_direct" if evaluation else "local_flus_console_package_only",
        "demand_mode": "forecast_demand",
        "uses_holdout_labels_for_training": False,
        "probability_backend": package.get("probability_backend", "observed_train_transition_prior_probability_cube"),
        "target_counts": case.target_counts,
        "package": package,
    }
    forecast_candidates = [
        name for name, payload in candidate_metadata.items() if payload.get("demand_mode") == "forecast_demand" and name in metrics
    ]
    oracle_candidates = [
        name for name, payload in candidate_metadata.items() if payload.get("demand_mode") == "oracle_demand" and name in metrics
    ]
    return {
        "case_id": case.case_id,
        "region_id": case.region_id,
        "train_period": f"{case.train_start_year}->{case.train_end_year}",
        "holdout_period": f"{case.train_end_year}->{case.holdout_year}",
        "valid_cell_count": int(case.valid.sum()),
        "cell_area_ha": case.cell_area_ha,
        "class_labels": {str(key): value for key, value in case.class_labels.items()},
        "demand": {
            "forecast_counts": {str(key): int(value) for key, value in case.target_counts.items()},
            "initial_counts": {str(key): int(value) for key, value in class_counts(case.train_end.array, case.valid, list(case.classes)).items()},
            "oracle_counts": {str(key): int(value) for key, value in class_counts(case.holdout.array, case.valid, list(case.classes)).items()},
        },
        "candidate_metadata": candidate_metadata,
        "metrics": metrics,
        "ablation_summary": build_ablation_summary(metrics),
        "best_forecast_by_change_fom": max(
            forecast_candidates,
            key=lambda name: metrics[name]["change_fom"],
        )
        if forecast_candidates
        else None,
        "best_oracle_by_change_fom": max(
            oracle_candidates,
            key=lambda name: metrics[name]["change_fom"],
        )
        if oracle_candidates
        else None,
        "claim_boundary": "single rolling case; package-only cases are not FLUS accuracy evidence",
    }


def build_case_experiment_from_reused_flus(
    case: FlusComparisonCase,
    existing_experiment: dict[str, Any],
) -> dict[str, Any]:
    twm_metrics, twm_metadata = build_twm_case_metrics(case)
    metrics = dict(twm_metrics)
    existing_metrics = existing_experiment.get("metrics") or {}
    flus_metric = existing_metrics.get(FLUS_CANDIDATE_ID)
    if flus_metric:
        metrics[FLUS_CANDIDATE_ID] = flus_metric
    candidate_metadata = dict(twm_metadata)
    existing_metadata = (existing_experiment.get("candidate_metadata") or {}).get(FLUS_CANDIDATE_ID, {})
    candidate_metadata[FLUS_CANDIDATE_ID] = {
        **existing_metadata,
        "backend": existing_metadata.get("backend", "local_flus_console_direct"),
        "demand_mode": "forecast_demand",
        "uses_holdout_labels_for_training": False,
        "target_counts": case.target_counts,
        "reused_from_existing_report": True,
    }
    forecast_candidates = [
        name for name, payload in candidate_metadata.items() if payload.get("demand_mode") == "forecast_demand" and name in metrics
    ]
    oracle_candidates = [
        name for name, payload in candidate_metadata.items() if payload.get("demand_mode") == "oracle_demand" and name in metrics
    ]
    return {
        **{key: value for key, value in existing_experiment.items() if key not in {"metrics", "candidate_metadata", "ablation_summary"}},
        "case_id": case.case_id,
        "region_id": case.region_id,
        "train_period": f"{case.train_start_year}->{case.train_end_year}",
        "holdout_period": f"{case.train_end_year}->{case.holdout_year}",
        "valid_cell_count": int(case.valid.sum()),
        "cell_area_ha": case.cell_area_ha,
        "class_labels": {str(key): value for key, value in case.class_labels.items()},
        "demand": {
            "forecast_counts": {str(key): int(value) for key, value in case.target_counts.items()},
            "initial_counts": {str(key): int(value) for key, value in class_counts(case.train_end.array, case.valid, list(case.classes)).items()},
            "oracle_counts": {str(key): int(value) for key, value in class_counts(case.holdout.array, case.valid, list(case.classes)).items()},
        },
        "candidate_metadata": candidate_metadata,
        "metrics": metrics,
        "ablation_summary": build_ablation_summary(metrics),
        "best_forecast_by_change_fom": max(
            forecast_candidates,
            key=lambda name: metrics[name]["change_fom"],
        )
        if forecast_candidates
        else None,
        "best_oracle_by_change_fom": max(
            oracle_candidates,
            key=lambda name: metrics[name]["change_fom"],
        )
        if oracle_candidates
        else None,
        "claim_boundary": "recomputed TWM metrics with FLUS metrics reused from existing report",
    }


def recompute_twm_experiments_from_existing_report(
    *,
    existing_report: dict[str, Any],
    cases: Sequence[FlusComparisonCase],
    output_path: Path | None = None,
) -> dict[str, Any]:
    existing_by_case = {str(experiment.get("case_id")): experiment for experiment in existing_report.get("experiments", [])}
    experiments = [
        build_case_experiment_from_reused_flus(case, existing_by_case[case.case_id])
        for case in cases
        if case.case_id in existing_by_case
    ]
    aggregate_inputs = [experiment for experiment in experiments if experiment.get("metrics")]
    report = {
        "schema": "territory_world_model.dynamic_world_admin20_flus_reused_twm_recompute.v1",
        "status": "pass" if experiments else "blocked",
        "source": existing_report.get("source", {}),
        "output_path": str(output_path) if output_path is not None else None,
        "recompute_policy": {
            "flus_metrics_source": "existing_report",
            "twm_metrics_source": "current_code_recomputed",
            "case_matching": "case_id",
            "existing_report_schema": existing_report.get("schema"),
            "existing_run_policy": existing_report.get("run_policy", {}),
        },
        "data_profile": {
            "case_count": len(experiments),
            "existing_case_count": len(existing_report.get("experiments", [])),
            "requested_case_count": len(list(cases)),
            "flus_evaluated_case_count": sum(1 for experiment in experiments if FLUS_CANDIDATE_ID in (experiment.get("metrics") or {})),
        },
        "experiments": experiments,
        "summary": aggregate_experiments(aggregate_inputs) if aggregate_inputs else {"status": "not_evaluated"},
        "formal_forecast_comparison": build_formal_forecast_comparison(aggregate_inputs)
        if aggregate_inputs
        else {"status": "not_evaluated"},
    }
    return report


def build_formal_forecast_comparison(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    rows: dict[str, list[dict[str, Any]]] = {}
    metadata_by_candidate: dict[str, dict[str, Any]] = {}
    paired_rows: dict[str, list[dict[str, float]]] = {}

    for experiment in experiments:
        metrics = experiment.get("metrics") or {}
        metadata = experiment.get("candidate_metadata") or {}
        flus_metric = metrics.get(FLUS_CANDIDATE_ID)

        for candidate_id, candidate_metadata in metadata.items():
            if candidate_metadata.get("demand_mode") != "forecast_demand":
                continue
            metric = metrics.get(candidate_id)
            if not metric:
                continue
            rows.setdefault(candidate_id, []).append(metric)
            metadata_by_candidate.setdefault(candidate_id, _formal_candidate_metadata(candidate_metadata))
            if candidate_id == FLUS_CANDIDATE_ID or not flus_metric:
                continue
            paired_rows.setdefault(candidate_id, []).append(
                {
                    "change_fom_delta": float(metric["change_fom"]) - float(flus_metric["change_fom"]),
                    "overall_accuracy_delta": float(metric["overall_accuracy"]) - float(flus_metric["overall_accuracy"]),
                    "kappa_delta": float(metric["kappa"]) - float(flus_metric["kappa"]),
                    "change_f1_delta": float(metric["change_f1"]) - float(flus_metric["change_f1"]),
                    "macro_f1_delta": float(metric["macro_f1"]) - float(flus_metric["macro_f1"]),
                    "target_demand_abs_error_delta": float(metric["target_total_demand_abs_error"])
                    - float(flus_metric["target_total_demand_abs_error"]),
                    "oracle_demand_abs_error_delta": float(metric["oracle_total_demand_abs_error"])
                    - float(flus_metric["oracle_total_demand_abs_error"]),
                }
            )

    aggregate = {
        candidate_id: {
            "case_count": len(metrics),
            "mean_overall_accuracy": round(float(np.mean([m["overall_accuracy"] for m in metrics])), 6),
            "mean_kappa": round(float(np.mean([m["kappa"] for m in metrics])), 6),
            "mean_change_fom": round(float(np.mean([m["change_fom"] for m in metrics])), 6),
            "mean_change_f1": round(float(np.mean([m["change_f1"] for m in metrics])), 6),
            "mean_macro_f1": round(float(np.mean([m["macro_f1"] for m in metrics])), 6),
            "total_target_demand_abs_error": int(sum(m["target_total_demand_abs_error"] for m in metrics)),
            "total_oracle_demand_abs_error": int(sum(m["oracle_total_demand_abs_error"] for m in metrics)),
            "metadata": metadata_by_candidate.get(candidate_id, {}),
        }
        for candidate_id, metrics in rows.items()
    }
    ranking = sorted(
        [{"candidate_id": candidate_id, **payload} for candidate_id, payload in aggregate.items()],
        key=lambda item: (item["mean_change_fom"], item["mean_overall_accuracy"]),
        reverse=True,
    )
    paired_deltas = {
        candidate_id: _summarize_paired_deltas(deltas)
        for candidate_id, deltas in sorted(paired_rows.items())
        if deltas
    }
    return {
        "schema": "territory_world_model.dynamic_world_formal_forecast_comparison.v1",
        "status": "pass" if ranking else "not_evaluated",
        "selection_rule": "Only candidates with candidate_metadata.demand_mode == forecast_demand are eligible.",
        "excluded_diagnostics": [
            "oracle_demand",
            "no_demand_projection",
        ],
        "flus_candidate_id": FLUS_CANDIDATE_ID,
        "flus_evaluated_case_count": len(rows.get(FLUS_CANDIDATE_ID, [])),
        "aggregate_by_candidate": aggregate,
        "ranking_by_mean_change_fom": ranking,
        "best_candidate_by_mean_change_fom": ranking[0]["candidate_id"] if ranking else None,
        "paired_deltas_vs_flus": paired_deltas,
        "product_mode_recommendations": build_product_mode_recommendations(aggregate, paired_deltas),
        "demand_projection_diagnostics": build_demand_projection_diagnostics(experiments),
        "temporal_strata_vs_flus": build_temporal_strata_vs_flus(experiments),
        "robustness_audit": build_candidate_robustness_audit(experiments),
    }


def build_candidate_robustness_audit(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for experiment in experiments:
        metrics = experiment.get("metrics") or {}
        metadata = experiment.get("candidate_metadata") or {}
        flus_metric = metrics.get(FLUS_CANDIDATE_ID)
        if not flus_metric:
            continue
        holdout_year = _extract_holdout_year(experiment)
        region_id = str(experiment.get("region_id") or "unknown")
        for candidate_id, candidate_metadata in metadata.items():
            if candidate_id == FLUS_CANDIDATE_ID:
                continue
            if candidate_metadata.get("demand_mode") != "forecast_demand":
                continue
            metric = metrics.get(candidate_id)
            if not metric:
                continue
            rows_by_candidate.setdefault(candidate_id, []).append(
                {
                    "case_id": str(experiment.get("case_id") or ""),
                    "region_id": region_id,
                    "holdout_year": holdout_year,
                    "change_fom_delta": float(metric["change_fom"]) - float(flus_metric["change_fom"]),
                    "overall_accuracy_delta": float(metric["overall_accuracy"]) - float(flus_metric["overall_accuracy"]),
                    "macro_f1_delta": float(metric["macro_f1"]) - float(flus_metric["macro_f1"]),
                    "change_f1_delta": float(metric["change_f1"]) - float(flus_metric["change_f1"]),
                }
            )
    return {
        candidate_id: _summarize_candidate_robustness_rows(rows)
        for candidate_id, rows in sorted(rows_by_candidate.items())
        if rows
    }


def _summarize_candidate_robustness_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    change_deltas = [float(row["change_fom_delta"]) for row in rows]
    oa_deltas = [float(row["overall_accuracy_delta"]) for row in rows]
    macro_deltas = [float(row["macro_f1_delta"]) for row in rows]
    by_year = _summarize_robustness_group(rows, key="holdout_year")
    by_region = _summarize_robustness_group(rows, key="region_id")
    year_means = [float(row["mean_change_fom_delta"]) for row in by_year.values()]
    region_means = [float(row["mean_change_fom_delta"]) for row in by_region.values()]
    mean_change_delta = round(float(np.mean(change_deltas)), 6)
    mean_oa_delta = round(float(np.mean(oa_deltas)), 6)
    mean_macro_delta = round(float(np.mean(macro_deltas)), 6)
    negative_year_count = sum(1 for value in year_means if value < 0.0)
    negative_region_count = sum(1 for value in region_means if value < 0.0)
    map_metric_gap = mean_oa_delta < 0.0 or mean_macro_delta < 0.0
    sign_test_p = _exact_two_sided_sign_test_p_value(
        wins=sum(1 for value in change_deltas if value > 0.0),
        losses=sum(1 for value in change_deltas if value < 0.0),
    )
    status = "pass"
    if mean_change_delta <= 0.0 or negative_year_count or negative_region_count or map_metric_gap:
        status = "review"
    if mean_change_delta <= 0.0:
        claim = "no_change_fom_advantage"
    elif negative_year_count or negative_region_count:
        claim = "change_fom_positive_but_not_strata_robust"
    elif map_metric_gap:
        claim = "change_fom_positive_but_map_metrics_trail_flus"
    elif sign_test_p <= 0.05:
        claim = "change_fom_positive_and_strata_robust_on_evaluated_cases"
    else:
        claim = "change_fom_positive_but_statistical_support_limited"
        status = "review"
    return {
        "schema": "territory_world_model.forecast_candidate_robustness_audit.v1",
        "status": status,
        "baseline_candidate_id": FLUS_CANDIDATE_ID,
        "paired_case_count": len(rows),
        "mean_change_fom_delta": mean_change_delta,
        "median_change_fom_delta": round(float(np.median(change_deltas)), 6),
        "change_fom_sign_test_p_value": sign_test_p,
        "wins_by_change_fom": sum(1 for value in change_deltas if value > 0.0),
        "losses_by_change_fom": sum(1 for value in change_deltas if value < 0.0),
        "ties_by_change_fom": sum(1 for value in change_deltas if value == 0.0),
        "overall_accuracy_mean_delta": mean_oa_delta,
        "macro_f1_mean_delta": mean_macro_delta,
        "map_metric_gap": map_metric_gap,
        "holdout_year_count": len(by_year),
        "negative_holdout_year_count": negative_year_count,
        "min_holdout_year_mean_change_fom_delta": round(float(min(year_means)), 6) if year_means else None,
        "region_count": len(by_region),
        "negative_region_count": negative_region_count,
        "min_region_mean_change_fom_delta": round(float(min(region_means)), 6) if region_means else None,
        "generalization_claim": claim,
        "by_holdout_year": by_year,
        "by_region": by_region,
    }


def _summarize_robustness_group(rows: list[dict[str, Any]], *, key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "unknown"), []).append(row)
    return {
        group: _summarize_robustness_group_rows(group_rows)
        for group, group_rows in sorted(grouped.items())
        if group_rows
    }


def _summarize_robustness_group_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [float(row["change_fom_delta"]) for row in rows]
    return {
        "case_count": len(rows),
        "mean_change_fom_delta": round(float(np.mean(deltas)), 6),
        "median_change_fom_delta": round(float(np.median(deltas)), 6),
        "wins_by_change_fom": sum(1 for value in deltas if value > 0.0),
        "losses_by_change_fom": sum(1 for value in deltas if value < 0.0),
        "ties_by_change_fom": sum(1 for value in deltas if value == 0.0),
    }


def build_temporal_strata_vs_flus(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_candidate_year: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for experiment in experiments:
        metrics = experiment.get("metrics") or {}
        metadata = experiment.get("candidate_metadata") or {}
        flus_metric = metrics.get(FLUS_CANDIDATE_ID)
        if not flus_metric:
            continue
        holdout_year = _extract_holdout_year(experiment)

        for candidate_id, candidate_metadata in metadata.items():
            if candidate_id == FLUS_CANDIDATE_ID:
                continue
            if candidate_metadata.get("demand_mode") != "forecast_demand":
                continue
            metric = metrics.get(candidate_id)
            if not metric:
                continue
            rows_by_candidate_year.setdefault(candidate_id, {}).setdefault(holdout_year, []).append(
                {
                    "change_fom_delta": float(metric["change_fom"]) - float(flus_metric["change_fom"]),
                    "candidate_change_fom": float(metric["change_fom"]),
                    "flus_change_fom": float(flus_metric["change_fom"]),
                    "candidate_change_hit_count": int(metric.get("change_hit_count", 0)),
                    "flus_change_hit_count": int(flus_metric.get("change_hit_count", 0)),
                    "candidate_change_false_alarm_count": int(metric.get("change_false_alarm_count", 0)),
                    "flus_change_false_alarm_count": int(flus_metric.get("change_false_alarm_count", 0)),
                    "candidate_change_miss_count": int(metric.get("change_miss_count", 0)),
                    "flus_change_miss_count": int(flus_metric.get("change_miss_count", 0)),
                    "candidate_actual_change_count": int(metric.get("actual_change_count", 0)),
                    "flus_actual_change_count": int(flus_metric.get("actual_change_count", 0)),
                }
            )

    return {
        candidate_id: _summarize_temporal_strata_by_year(by_year)
        for candidate_id, by_year in sorted(rows_by_candidate_year.items())
    }


def _summarize_temporal_strata_by_year(by_year: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    summaries = {
        year: _summarize_temporal_stratum_rows(rows)
        for year, rows in sorted(by_year.items())
        if rows
    }
    worst_year = min(
        summaries,
        key=lambda year: summaries[year]["mean_change_fom_delta"],
        default=None,
    )
    return {
        "schema": "territory_world_model.temporal_strata_vs_flus.v1",
        "by_holdout_year": summaries,
        "worst_holdout_year_by_mean_change_fom_delta": worst_year,
    }


def _summarize_temporal_stratum_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [float(row["change_fom_delta"]) for row in rows]
    candidate_hit = sum(int(row["candidate_change_hit_count"]) for row in rows)
    flus_hit = sum(int(row["flus_change_hit_count"]) for row in rows)
    candidate_false_alarm = sum(int(row["candidate_change_false_alarm_count"]) for row in rows)
    flus_false_alarm = sum(int(row["flus_change_false_alarm_count"]) for row in rows)
    candidate_miss = sum(int(row["candidate_change_miss_count"]) for row in rows)
    flus_miss = sum(int(row["flus_change_miss_count"]) for row in rows)
    candidate_micro_change_fom = _micro_change_fom(
        hit=candidate_hit,
        false_alarm=candidate_false_alarm,
        miss=candidate_miss,
    )
    flus_micro_change_fom = _micro_change_fom(
        hit=flus_hit,
        false_alarm=flus_false_alarm,
        miss=flus_miss,
    )
    mean_delta = round(float(np.mean(deltas)), 6)
    micro_delta = round(candidate_micro_change_fom - flus_micro_change_fom, 6)
    return {
        "paired_case_count": len(rows),
        "mean_change_fom_delta": mean_delta,
        "median_change_fom_delta": round(float(np.median(deltas)), 6),
        "change_fom_sign_test_p_value": _exact_two_sided_sign_test_p_value(
            wins=sum(1 for value in deltas if value > 0),
            losses=sum(1 for value in deltas if value < 0),
        ),
        "wins_by_change_fom": sum(1 for value in deltas if value > 0),
        "losses_by_change_fom": sum(1 for value in deltas if value < 0),
        "ties_by_change_fom": sum(1 for value in deltas if value == 0),
        "candidate_micro_change_fom": round(candidate_micro_change_fom, 6),
        "flus_micro_change_fom": round(flus_micro_change_fom, 6),
        "micro_change_fom_delta": micro_delta,
        "candidate_total_change_hit_count": candidate_hit,
        "flus_total_change_hit_count": flus_hit,
        "total_change_hit_delta": candidate_hit - flus_hit,
        "candidate_total_change_false_alarm_count": candidate_false_alarm,
        "flus_total_change_false_alarm_count": flus_false_alarm,
        "total_change_false_alarm_delta": candidate_false_alarm - flus_false_alarm,
        "candidate_total_change_miss_count": candidate_miss,
        "flus_total_change_miss_count": flus_miss,
        "total_change_miss_delta": candidate_miss - flus_miss,
        "candidate_total_actual_change_count": sum(int(row["candidate_actual_change_count"]) for row in rows),
        "flus_total_actual_change_count": sum(int(row["flus_actual_change_count"]) for row in rows),
        "weighted_vs_unweighted_pattern": _weighted_vs_unweighted_pattern(mean_delta, micro_delta),
    }


def _micro_change_fom(*, hit: int, false_alarm: int, miss: int) -> float:
    denominator = int(hit) + int(false_alarm) + int(miss)
    if denominator == 0:
        return 0.0
    return float(hit) / float(denominator)


def _weighted_vs_unweighted_pattern(mean_delta: float, micro_delta: float) -> str:
    if mean_delta < 0 < micro_delta:
        return "micro_positive_mean_negative"
    if mean_delta > 0 > micro_delta:
        return "micro_negative_mean_positive"
    if mean_delta > 0 and micro_delta > 0:
        return "both_positive"
    if mean_delta < 0 and micro_delta < 0:
        return "both_negative"
    return "mixed_or_tied"


def build_demand_projection_diagnostics(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    rows_by_year: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for experiment in experiments:
        metrics = experiment.get("metrics") or {}
        metadata = experiment.get("candidate_metadata") or {}
        demand = experiment.get("demand") or {}
        oracle_counts = _int_count_dict(demand.get("oracle_counts") or {})
        if not oracle_counts:
            continue

        flus_target_counts = _candidate_target_counts(metadata.get(FLUS_CANDIDATE_ID, {}))
        if not flus_target_counts:
            flus_target_counts = _int_count_dict(demand.get("forecast_counts") or {})
        flus_target_abs_error = (
            _total_abs_count_error(flus_target_counts, oracle_counts) if flus_target_counts else None
        )
        holdout_year = _extract_holdout_year(experiment)

        for candidate_id, candidate_metadata in metadata.items():
            if candidate_metadata.get("demand_mode") != "forecast_demand":
                continue
            metric = metrics.get(candidate_id)
            if not metric:
                continue
            target_counts = _candidate_target_counts(candidate_metadata)
            if not target_counts and candidate_id == FLUS_CANDIDATE_ID:
                target_counts = _int_count_dict(demand.get("forecast_counts") or {})
            if not target_counts:
                continue

            projected_abs_error = _total_abs_count_error(target_counts, oracle_counts)
            row: dict[str, Any] = {
                "case_id": experiment.get("case_id"),
                "region_id": experiment.get("region_id"),
                "holdout_year": holdout_year,
                "demand_projection_source": _demand_projection_source(candidate_id, candidate_metadata),
                "uses_holdout_labels_for_training": bool(candidate_metadata.get("uses_holdout_labels_for_training", False)),
                "projected_vs_oracle_abs_error": int(projected_abs_error),
                "change_fom": float(metric["change_fom"]),
                "overall_accuracy": float(metric["overall_accuracy"]),
                "macro_f1": float(metric["macro_f1"]),
            }
            if flus_target_abs_error is not None:
                row["abs_error_delta_vs_flus_target"] = int(projected_abs_error - flus_target_abs_error)
            rows_by_candidate.setdefault(candidate_id, []).append(row)
            rows_by_year.setdefault(holdout_year, {}).setdefault(candidate_id, []).append(row)

    aggregate_by_candidate = {
        candidate_id: _summarize_demand_projection_rows(rows)
        for candidate_id, rows in sorted(rows_by_candidate.items())
        if rows
    }
    ranking = _rank_demand_projection_aggregate(aggregate_by_candidate)
    return {
        "schema": "territory_world_model.demand_projection_diagnostics.v1",
        "status": "pass" if ranking else "not_evaluated",
        "baseline_candidate_id": FLUS_CANDIDATE_ID,
        "error_definition": "L1 absolute error between candidate target_counts and holdout oracle_counts; lower is better.",
        "aggregate_by_candidate": aggregate_by_candidate,
        "ranking_by_projected_vs_oracle_abs_error": ranking,
        "best_candidate_by_projected_vs_oracle_abs_error": ranking[0]["candidate_id"] if ranking else None,
        "by_holdout_year": {
            year: _summarize_demand_projection_year(by_candidate)
            for year, by_candidate in sorted(rows_by_year.items())
        },
    }


def _summarize_demand_projection_year(by_candidate: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    aggregate = {
        candidate_id: _summarize_demand_projection_rows(rows)
        for candidate_id, rows in sorted(by_candidate.items())
        if rows
    }
    ranking = _rank_demand_projection_aggregate(aggregate)
    case_ids = {
        row["case_id"]
        for rows in by_candidate.values()
        for row in rows
        if row.get("case_id") is not None
    }
    return {
        "case_count": len(case_ids),
        "aggregate_by_candidate": aggregate,
        "ranking_by_projected_vs_oracle_abs_error": ranking,
        "best_candidate_by_projected_vs_oracle_abs_error": ranking[0]["candidate_id"] if ranking else None,
    }


def _summarize_demand_projection_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    abs_errors = [int(row["projected_vs_oracle_abs_error"]) for row in rows]
    deltas = [int(row["abs_error_delta_vs_flus_target"]) for row in rows if "abs_error_delta_vs_flus_target" in row]
    return {
        "case_count": len(rows),
        "demand_projection_source": _single_or_mixed(row["demand_projection_source"] for row in rows),
        "uses_holdout_labels_for_training": _single_or_mixed(row["uses_holdout_labels_for_training"] for row in rows),
        "total_projected_vs_oracle_abs_error": int(sum(abs_errors)),
        "mean_projected_vs_oracle_abs_error": round(float(np.mean(abs_errors)), 6),
        "median_projected_vs_oracle_abs_error": round(float(np.median(abs_errors)), 6),
        "total_abs_error_delta_vs_flus_target": int(sum(deltas)) if deltas else 0,
        "wins_vs_flus_target": sum(1 for value in deltas if value < 0),
        "losses_vs_flus_target": sum(1 for value in deltas if value > 0),
        "ties_vs_flus_target": sum(1 for value in deltas if value == 0),
        "mean_change_fom": round(float(np.mean([row["change_fom"] for row in rows])), 6),
        "mean_overall_accuracy": round(float(np.mean([row["overall_accuracy"] for row in rows])), 6),
        "mean_macro_f1": round(float(np.mean([row["macro_f1"] for row in rows])), 6),
    }


def _rank_demand_projection_aggregate(aggregate: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [{"candidate_id": candidate_id, **payload} for candidate_id, payload in aggregate.items()],
        key=lambda item: (
            item["mean_projected_vs_oracle_abs_error"],
            item["total_projected_vs_oracle_abs_error"],
            item["candidate_id"],
        ),
    )


def _candidate_target_counts(metadata: dict[str, Any]) -> dict[int, int]:
    return _int_count_dict(metadata.get("target_counts") or {})


def _int_count_dict(payload: dict[Any, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for key, value in payload.items():
        counts[int(key)] = int(value)
    return counts


def _total_abs_count_error(left: dict[int, int], right: dict[int, int]) -> int:
    keys = set(left) | set(right)
    return int(sum(abs(int(left.get(key, 0)) - int(right.get(key, 0))) for key in keys))


def _extract_holdout_year(experiment: dict[str, Any]) -> str:
    if experiment.get("holdout_year") is not None:
        return str(experiment["holdout_year"])
    holdout_period = str(experiment.get("holdout_period", ""))
    if "->" in holdout_period:
        return holdout_period.rsplit("->", 1)[-1].strip()
    return "unknown"


def _demand_projection_source(candidate_id: str, metadata: dict[str, Any]) -> str:
    if candidate_id == FLUS_CANDIDATE_ID:
        return "flus_adapter_supplied_forecast_counts"
    training_projection = metadata.get("training_demand_projection") or {}
    if training_projection.get("demand_projection_source"):
        return str(training_projection["demand_projection_source"])
    component_flags = metadata.get("component_flags") or {}
    if component_flags.get("persistence_demand_projection"):
        return "train_end_class_counts"
    if component_flags.get("markov_demand_projection"):
        return "train_start_train_end_markov_transition_counts"
    if component_flags.get("demand_projection"):
        return "projected_from_train_start_train_end"
    return "unknown"


def _single_or_mixed(values: Any) -> Any:
    unique_values = sorted(set(values), key=lambda value: str(value))
    if len(unique_values) == 1:
        return unique_values[0]
    return "mixed"


def build_product_mode_recommendations(
    aggregate: dict[str, dict[str, Any]],
    paired_deltas: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    twm_candidate_ids = [candidate_id for candidate_id in aggregate if candidate_id.startswith("twm_")]

    def recommendation(candidate_id: str | None, selection_rule: str) -> dict[str, Any] | None:
        if candidate_id is None:
            return None
        row = aggregate[candidate_id]
        payload: dict[str, Any] = {
            "candidate_id": candidate_id,
            "selection_rule": selection_rule,
            "mean_change_fom": row["mean_change_fom"],
            "mean_overall_accuracy": row["mean_overall_accuracy"],
            "mean_macro_f1": row["mean_macro_f1"],
            "mean_change_f1": row["mean_change_f1"],
            "total_oracle_demand_abs_error": row["total_oracle_demand_abs_error"],
            "metadata": row.get("metadata", {}),
        }
        if candidate_id in paired_deltas:
            payload["paired_delta_vs_flus"] = paired_deltas[candidate_id]
        return payload

    change_discovery_id = max(
        twm_candidate_ids,
        key=lambda candidate_id: (
            aggregate[candidate_id]["mean_change_fom"],
            aggregate[candidate_id]["mean_change_f1"],
            aggregate[candidate_id]["mean_overall_accuracy"],
        ),
        default=None,
    )
    significant_change_ids = [
        candidate_id
        for candidate_id in twm_candidate_ids
        if paired_deltas.get(candidate_id, {}).get("mean_change_fom_delta", 0.0) > 0
        and paired_deltas.get(candidate_id, {}).get("change_fom_sign_test_p_value", 1.0) <= 0.05
    ]
    map_aware_id = max(
        significant_change_ids,
        key=lambda candidate_id: (
            aggregate[candidate_id]["mean_macro_f1"],
            aggregate[candidate_id]["mean_overall_accuracy"],
            aggregate[candidate_id]["mean_change_fom"],
        ),
        default=None,
    )
    conservative_ids = [
        candidate_id
        for candidate_id in twm_candidate_ids
        if aggregate[candidate_id].get("metadata", {}).get("component_flags", {}).get("conservative_map_mode") is True
    ]
    conservative_pool = conservative_ids or twm_candidate_ids
    conservative_id = max(
        conservative_pool,
        key=lambda candidate_id: (
            aggregate[candidate_id]["mean_overall_accuracy"],
            aggregate[candidate_id]["mean_macro_f1"],
        ),
        default=None,
    )
    return {
        "change_discovery": recommendation(
            change_discovery_id,
            "highest mean change FoM among forecast-demand TWM candidates",
        ),
        "map_aware_simulation": recommendation(
            map_aware_id,
            "highest macro-F1 among TWM candidates with significant positive change-FoM delta versus FLUS",
        ),
        "conservative_map": recommendation(
            conservative_id,
            "highest OA among conservative-map TWM candidates, falling back to all TWM candidates if none are flagged",
        ),
    }


def _formal_candidate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "backend",
        "demand_mode",
        "uses_holdout_labels_for_training",
        "uses_holdout_class_totals",
        "probability_backend",
        "ablation_of",
        "component_flags",
    )
    return {key: metadata[key] for key in keep_keys if key in metadata}


def _summarize_paired_deltas(deltas: list[dict[str, float]]) -> dict[str, Any]:
    def mean(key: str) -> float:
        return round(float(np.mean([row[key] for row in deltas])), 6)

    def median(key: str) -> float:
        return round(float(np.median([row[key] for row in deltas])), 6)

    def sign_test_p_value(key: str) -> float:
        wins = sum(1 for row in deltas if row[key] > 0)
        losses = sum(1 for row in deltas if row[key] < 0)
        return _exact_two_sided_sign_test_p_value(wins=wins, losses=losses)

    return {
        "paired_case_count": len(deltas),
        "mean_change_fom_delta": mean("change_fom_delta"),
        "median_change_fom_delta": median("change_fom_delta"),
        "change_fom_sign_test_p_value": sign_test_p_value("change_fom_delta"),
        "mean_overall_accuracy_delta": mean("overall_accuracy_delta"),
        "median_overall_accuracy_delta": median("overall_accuracy_delta"),
        "overall_accuracy_sign_test_p_value": sign_test_p_value("overall_accuracy_delta"),
        "mean_kappa_delta": mean("kappa_delta"),
        "median_kappa_delta": median("kappa_delta"),
        "kappa_sign_test_p_value": sign_test_p_value("kappa_delta"),
        "mean_change_f1_delta": mean("change_f1_delta"),
        "median_change_f1_delta": median("change_f1_delta"),
        "change_f1_sign_test_p_value": sign_test_p_value("change_f1_delta"),
        "mean_macro_f1_delta": mean("macro_f1_delta"),
        "median_macro_f1_delta": median("macro_f1_delta"),
        "macro_f1_sign_test_p_value": sign_test_p_value("macro_f1_delta"),
        "total_target_demand_abs_error_delta": int(sum(row["target_demand_abs_error_delta"] for row in deltas)),
        "total_oracle_demand_abs_error_delta": int(sum(row["oracle_demand_abs_error_delta"] for row in deltas)),
        "wins_by_change_fom": sum(1 for row in deltas if row["change_fom_delta"] > 0),
        "losses_by_change_fom": sum(1 for row in deltas if row["change_fom_delta"] < 0),
        "ties_by_change_fom": sum(1 for row in deltas if row["change_fom_delta"] == 0),
        "wins_by_overall_accuracy": sum(1 for row in deltas if row["overall_accuracy_delta"] > 0),
        "losses_by_overall_accuracy": sum(1 for row in deltas if row["overall_accuracy_delta"] < 0),
        "ties_by_overall_accuracy": sum(1 for row in deltas if row["overall_accuracy_delta"] == 0),
    }


def _exact_two_sided_sign_test_p_value(*, wins: int, losses: int) -> float:
    n = int(wins) + int(losses)
    if n == 0:
        return 1.0
    tail_count = min(int(wins), int(losses))
    tail_probability = sum(math.comb(n, k) for k in range(tail_count + 1)) / float(2**n)
    return float(min(1.0, 2.0 * tail_probability))


def build_twm_case_metrics(case: FlusComparisonCase) -> tuple[dict[str, Any], dict[str, Any]]:
    model_inputs = {
        "train_start": case.train_start.array,
        "train_end": case.train_end.array,
        "initial": case.train_end.array,
        "actual": case.holdout.array,
        "valid": case.valid,
        "classes": list(case.classes),
        "drivers": {},
        "train_years": max(1, case.train_end_year - case.train_start_year),
        "horizon_years": max(1, case.holdout_year - case.train_end_year),
        "region_id": case.region_id,
        "train_start_year": case.train_start_year,
        "train_end_year": case.train_end_year,
        "holdout_year": case.holdout_year,
    }
    oracle_counts = class_counts(case.holdout.array, case.valid, list(case.classes))
    predictions, metadata = build_candidates(
        model_inputs,
        case.target_counts,
        oracle_counts,
        cross_region_priors=None,
    )
    metrics = {
        name: pixel_metrics(
            prediction=pred,
            actual=case.holdout.array,
            initial=case.train_end.array,
            valid=case.valid,
            classes=list(case.classes),
            cell_area_ha=case.cell_area_ha,
            target_counts=metadata[name]["target_counts"],
        )
        for name, pred in predictions.items()
    }
    return metrics, metadata


if __name__ == "__main__":
    main()
